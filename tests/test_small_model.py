from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from lcc.agent.sandbox import Confirmer, Sandbox
from lcc.agent.small_model import (
    PLAN_SCHEMA,
    Plan,
    PlanError,
    PlanStep,
    SmallModelEvents,
    SmallModelRunner,
    StepSummary,
    parse_plan,
    phase_tools,
    validate_plan,
)
from lcc.agent.tools import ToolContext, available_tool_names, default_registry
from lcc.agent.verify import detect_verify_commands, failure_text, trim_failure
from lcc.config import Config, default_config
from lcc.ollama_client import OllamaClient
from tests.fake_ollama import FakeOllama, stream_text, stream_tool_call

PY = sys.executable

# Prüft calc.py und gibt den Fehler so aus wie ein fehlgeschlagener Test.
CHECK_SCRIPT = """
import sys
text = open("calc.py", encoding="utf-8").read()
if "a + b" not in text:
    print("AssertionError: add(2, 3) ergibt -1 statt 5")
    sys.exit(1)
"""


def plan_reply(*steps: dict[str, Any]) -> list[dict[str, Any]]:
    content = json.dumps({"steps": list(steps)})
    return [{"message": {"role": "assistant", "content": content}, "done": True}]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (root / "check.py").write_text(CHECK_SCRIPT, encoding="utf-8")
    return root


def make_config(workspace: Path, **small: Any) -> Config:
    config = default_config(workspace)
    small.setdefault("verify_commands", (f"{PY} check.py",))
    return dataclasses.replace(
        config,
        agent=dataclasses.replace(config.agent, shell_allowlist=(PY,)),
        small_model=dataclasses.replace(config.small_model, **small),
    )


def make_runner(
    workspace: Path,
    fake: FakeOllama,
    events: SmallModelEvents | None = None,
    **small: Any,
) -> SmallModelRunner:
    fake.add_model("m", capabilities=("completion", "tools", "thinking"))
    config = make_config(workspace, **small)
    ctx = ToolContext(
        config=config,
        sandbox=Sandbox(workspace, config.workspace.ignore),
        confirmer=Confirmer(interactive=False, assume_yes=True),
        small_mode=True,
    )
    return SmallModelRunner(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        context=ctx,
        model="m",
        events=events,
    )


def recording(target: list[Plan]) -> Any:
    """on_plan-Callback, der den Plan merkt und unverändert bestätigt."""

    def confirm(plan: Plan) -> Plan:
        target.append(plan)
        return plan

    return confirm


def chats(fake: FakeOllama) -> list[dict[str, Any]]:
    return [body for path, body in fake.requests if path == "/api/chat"]


def tool_names(body: dict[str, Any]) -> list[str]:
    return [t["function"]["name"] for t in body.get("tools", [])]


FIX = {
    "path": "calc.py",
    "old_str": "return a - b",
    "new_str": "return a + b",
}


# -- Plan --------------------------------------------------------------------


def test_validate_plan_ok() -> None:
    plan = validate_plan(
        {
            "steps": [
                {"goal": "lesen", "phase": "explore", "files": ["a.py"]},
                {"goal": "x", "phase": "edit"},
            ]
        }
    )
    assert plan.steps == (PlanStep("lesen", "explore", ("a.py",)), PlanStep("x", "edit"))
    assert not plan.is_simple
    assert plan.render() == "1. [explore] lesen (a.py)\n2. [edit] x"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "steps"),
        ({"steps": []}, "0 Schritte"),
        ({"steps": [{"goal": "x", "phase": "edit"}] * 9}, "9 Schritte"),
        ({"steps": [{"phase": "edit"}]}, "goal"),
        ({"steps": [{"goal": "x", "phase": "deploy"}]}, "phase"),
        ({"steps": [{"goal": "x", "phase": "edit", "files": "a.py"}]}, "files"),
        ({"steps": ["x"]}, "kein Objekt"),
    ],
)
def test_validate_plan_errors(data: Any, message: str) -> None:
    with pytest.raises(PlanError, match=message):
        validate_plan(data)


def test_parse_plan_broken_json() -> None:
    with pytest.raises(PlanError, match="JSON"):
        parse_plan('{"steps": [')


def test_make_plan_retries_once_then_succeeds(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            [{"message": {"content": '{"steps": []}'}, "done": True}],
            plan_reply({"goal": "ändern", "phase": "edit"}),
        ]
    )
    runner = make_runner(workspace, fake)
    plan = runner.make_plan("x", runner_auto(runner))
    assert plan.steps == (PlanStep("ändern", "edit"),)
    first, second = chats(fake)
    assert first["format"] == PLAN_SCHEMA
    assert first["think"] is True  # think_on_plan + Thinking-Modell
    assert first["options"]["temperature"] == 0.1
    assert "ungültig" in second["messages"][-1]["content"]


def test_make_plan_falls_back_after_two_invalid(workspace: Path) -> None:
    bad = [{"message": {"content": "kein json"}, "done": True}]
    fake = FakeOllama(chat_replies=[bad, bad])
    infos: list[str] = []
    runner = make_runner(workspace, fake, SmallModelEvents(on_info=infos.append))
    plan = runner.make_plan("füge add hinzu", runner_auto(runner))
    assert plan.fallback
    assert plan.steps == (PlanStep("füge add hinzu", "edit"),)
    assert len(chats(fake)) == 2
    assert infos and "ungültig" in infos[0]


def test_plan_first_false_uses_single_free_step(workspace: Path) -> None:
    runner = make_runner(workspace, FakeOllama(), plan_first=False)
    plan = runner.make_plan("x", runner_auto(runner))
    assert plan.steps == (PlanStep("x", "free"),)


def runner_auto(runner: SmallModelRunner) -> Any:
    from lcc.agent.context import AutoContext

    return AutoContext()


# -- Phasen-Tools ------------------------------------------------------------


def test_phase_tool_sets(workspace: Path) -> None:
    config = make_config(workspace)
    ctx = ToolContext(config=config, sandbox=Sandbox(workspace), small_mode=True)
    available = available_tool_names(default_registry(), ctx)
    assert phase_tools("explore", available, 5) == ["read_file", "list_dir", "search_code"]
    assert phase_tools("edit", available, 5) == [
        "read_file",
        "edit_file",
        "replace_lines",
        "write_file",
    ]
    assert phase_tools("verify", available, 5) == ["run_shell", "read_file"]
    assert phase_tools("edit", available, 2) == ["read_file", "edit_file"]
    # Skill mit run_shell (z. B. commit-nachricht: nur run_shell + read_file)
    restricted = ["read_file", "run_shell"]
    assert phase_tools("explore", restricted, 5) == ["read_file"]
    assert phase_tools("explore", restricted, 5, skill_tools=restricted) == [
        "read_file",
        "run_shell",
    ]


# -- Zusammenfassung ---------------------------------------------------------


def test_step_summary_is_deterministic() -> None:
    summary = StepSummary(
        2,
        "Fehler beheben",
        "edit",
        read_files=["calc.py"],
        changed_files=["calc.py"],
        commands=[("pytest -q", 1)],
        tool_errors=1,
        note="Erledigt.",
    )
    assert summary.render() == (
        "Schritt 2 (edit): Fehler beheben\n"
        "  gelesen: calc.py\n"
        "  geändert: calc.py\n"
        "  Befehl: pytest -q → exit 1\n"
        "  Tool-Fehler: 1\n"
        "  Ergebnis: Erledigt."
    )


# -- Gesamtablauf ------------------------------------------------------------


def test_full_run_plan_steps_verify(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply(
                {"goal": "calc.py lesen", "phase": "explore", "files": ["calc.py"]},
                {"goal": "add korrigieren", "phase": "edit"},
            ),
            stream_tool_call("read_file", {"path": "calc.py"}),
            stream_text("add subtrahiert."),
            stream_tool_call("edit_file", FIX),
            stream_text("Korrigiert."),
        ]
    )
    plans: list[Plan] = []
    steps: list[int] = []
    events = SmallModelEvents(
        on_plan=recording(plans),
        on_step=lambda n, total, step: steps.append(n),
    )
    result = make_runner(workspace, fake, events).run("Korrigiere add in calc.py")
    assert result.ok, result.content
    assert result.content == "Korrigiert."
    assert len(plans) == 1 and steps == [1, 2]
    assert [c.ok for c in result.checks] == [True]
    assert result.changed == ["calc.py"]
    assert "a + b" in (workspace / "calc.py").read_text()

    requests = chats(fake)
    explore, _, edit, _ = requests[1:5]
    assert tool_names(explore) == ["read_file", "list_dir", "search_code"]
    assert tool_names(edit) == ["read_file", "edit_file", "replace_lines", "write_file"]
    assert explore["think"] is False
    # Kontext wird je Schritt neu gebaut: Auftrag zuletzt, Zusammenfassung von Schritt 1 drin
    task_message = edit["messages"][-1]["content"]
    assert task_message.startswith("Auftrag: Korrigiere add in calc.py")
    assert "Schritt 1 (explore): calc.py lesen\n  gelesen: calc.py" in task_message
    assert "Jetzt Schritt 2/2 (edit): add korrigieren" in task_message
    assert any("1| def add(a, b):" in m["content"] for m in edit["messages"])
    assert edit["messages"][0]["content"].count("\n") < 20  # kompakter Systemprompt


def test_simple_plan_has_no_overhead(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "erklären", "phase": "explore"}),
            stream_text("calc.py enthält add."),
        ]
    )
    called: list[Plan] = []
    events = SmallModelEvents(on_plan=recording(called))
    result = make_runner(workspace, fake, events).run("Was steht in calc.py?")
    assert result.ok
    assert result.content == "calc.py enthält add."
    assert called == []
    assert result.checks == []


def test_plan_cancelled(workspace: Path) -> None:
    fake = FakeOllama(chat_replies=[plan_reply({"goal": "x", "phase": "edit"})])
    result = make_runner(workspace, fake, SmallModelEvents(on_plan=lambda p: None)).run("x")
    assert not result.ok
    assert result.aborted == "Plan abgebrochen."
    assert len(chats(fake)) == 1


def test_repair_loop_fixes_failing_check(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "Kommentar ergänzen", "phase": "edit"}),
            stream_tool_call(
                "edit_file",
                {"path": "calc.py", "old_str": "def add", "new_str": "# Summe\ndef add"},
            ),
            stream_text("Kommentar ergänzt."),
            stream_tool_call("edit_file", FIX),
            stream_text("Fehler behoben."),
        ]
    )
    infos: list[str] = []
    result = make_runner(workspace, fake, SmallModelEvents(on_info=infos.append)).run("x")
    assert result.ok, result.content
    assert result.repairs == 1
    assert any("Repair-Versuch 1" in i for i in infos)
    repair_prompt = chats(fake)[3]["messages"][-1]["content"]
    assert "Behebe diesen Fehler:" in repair_prompt
    assert "AssertionError: add(2, 3) ergibt -1 statt 5" in repair_prompt
    assert tool_names(chats(fake)[3]) == ["read_file", "edit_file", "replace_lines", "write_file"]


def test_same_error_twice_aborts_honestly(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "Kommentar", "phase": "edit"}),
            stream_tool_call(
                "edit_file", {"path": "calc.py", "old_str": "def", "new_str": "# x\ndef"}
            ),
            stream_text("ok"),
            stream_text("Ich weiß nicht weiter."),  # Repair ändert nichts → gleicher Fehler
            stream_text("nochmal nichts"),
        ]
    )
    infos: list[str] = []
    result = make_runner(workspace, fake, SmallModelEvents(on_info=infos.append)).run("x")
    assert not result.ok
    assert result.repairs == 1
    assert any("Gleicher Fehler" in i for i in infos)
    assert result.aborted is not None
    assert "nicht erfolgreich" in result.aborted
    assert "AssertionError" in result.aborted
    assert "lcc undo" in result.aborted
    assert "calc.py" in result.aborted


def test_max_repair_attempts(workspace: Path) -> None:
    (workspace / "check.py").write_text(
        "import random, sys\nprint('Fehler', random.random())\nsys.exit(1)\n", encoding="utf-8"
    )
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "x", "phase": "edit"}),
            stream_tool_call("write_file", {"path": "neu.py", "content": "x = 1"}),
            stream_text("ok"),
        ]
    )
    result = make_runner(workspace, fake, max_repair_attempts=2).run("x")
    assert not result.ok
    assert result.repairs == 2
    assert len(chats(fake)) == 1 + 2 + 2  # Plan, Schritt (2 Runden), 2 Repair-Schritte


def test_escalation_uses_bigger_model(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "Kommentar", "phase": "edit"}),
            stream_tool_call(
                "edit_file", {"path": "calc.py", "old_str": "def", "new_str": "# x\ndef"}
            ),
            stream_text("ok"),
            stream_text("keine Ahnung"),  # Repair mit kleinem Modell scheitert
            stream_tool_call("edit_file", FIX),  # Eskalation behebt
            stream_text("behoben"),
        ]
    )
    fake.add_model("gross:27b")
    infos: list[str] = []
    runner = make_runner(
        workspace,
        fake,
        SmallModelEvents(on_info=infos.append),
        escalate_model="gross:27b",
        max_repair_attempts=1,
    )
    result = runner.run("x")
    assert result.ok, result.content
    assert result.escalated
    assert "↑ Eskaliert an gross:27b" in infos
    assert chats(fake)[-2]["model"] == "gross:27b"


def test_verify_hint_lists_allowlist(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "a", "phase": "explore"}, {"goal": "prüfen", "phase": "verify"}),
            stream_text("gelesen"),
            stream_text("geprüft"),
        ]
    )
    make_runner(workspace, fake).run("x")
    verify_prompt = chats(fake)[-1]["messages"][-1]["content"]
    assert f"Ohne Rückfrage erlaubt: {PY}." in verify_prompt
    assert tool_names(chats(fake)[-1]) == ["run_shell", "read_file"]


def test_no_checks_without_changes(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "a", "phase": "explore"}, {"goal": "b", "phase": "verify"}),
            stream_text("gelesen"),
            stream_text("geprüft"),
        ]
    )
    result = make_runner(workspace, fake).run("x")
    assert result.ok
    assert result.checks == []


def test_global_step_budget(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            plan_reply({"goal": "a", "phase": "explore"}, {"goal": "b", "phase": "explore"}),
            *[stream_tool_call("list_dir", {"path": str(i)}) for i in range(10)],
        ]
    )
    runner = make_runner(workspace, fake, max_steps_per_plan_step=3)
    runner.config = dataclasses.replace(
        runner.config, agent=dataclasses.replace(runner.config.agent, max_steps=3)
    )
    runner.ctx.config = runner.config
    result = runner.run("x")
    assert not result.ok
    assert result.aborted is not None and "Gesamtlimit" in result.aborted


# -- Verify-Hilfen -----------------------------------------------------------


def test_detect_verify_commands(tmp_path: Path) -> None:
    assert detect_verify_commands(tmp_path, ["a.py", "b b.py", "README.md"]) == [
        "python -m py_compile a.py 'b b.py'"
    ]
    (tmp_path / "tests").mkdir()
    assert detect_verify_commands(tmp_path, ["README.md"]) == ["python -m pytest -q"]


def test_trim_failure_prefers_first_traceback() -> None:
    output = (
        "lauter Kram\n" * 100
        + 'Traceback (most recent call last):\n  File "a.py", line 1\n    x()\n'
        + "NameError: name 'x' is not defined\nnoch mehr\n"
    )
    trimmed = trim_failure(output)
    assert trimmed.startswith("Traceback")
    assert trimmed.endswith("NameError: name 'x' is not defined")
    assert len(trim_failure("zeile\n" * 500).splitlines()) == 60


def test_failure_text_none_when_green() -> None:
    assert failure_text([]) is None


def test_runaway_plan_thinking_is_stopped(workspace: Path) -> None:
    endless = [{"message": {"content": "", "thinking": "hmm " * 300}, "done": False}] * 10
    endless.append({"message": {"content": '{"steps": []}'}, "done": True})
    fake = FakeOllama(chat_replies=[endless, plan_reply({"goal": "ändern", "phase": "edit"})])
    infos: list[str] = []
    runner = make_runner(workspace, fake, SmallModelEvents(on_info=infos.append))
    plan = runner.make_plan("x", runner_auto(runner))
    assert plan.steps == (PlanStep("ändern", "edit"),)
    first, second = chats(fake)
    assert first["think"] is True
    assert second["think"] is False
    assert any("ohne Thinking" in i for i in infos)


def test_plan_thinking_within_budget_is_kept(workspace: Path) -> None:
    reply = [
        {"message": {"content": "", "thinking": "kurz überlegt"}, "done": False},
        *plan_reply({"goal": "lesen", "phase": "explore"}),
    ]
    fake = FakeOllama(chat_replies=[reply])
    runner = make_runner(workspace, fake)
    plan = runner.make_plan("x", runner_auto(runner))
    assert plan.steps == (PlanStep("lesen", "explore"),)
    assert len(chats(fake)) == 1


def test_plan_thinking_time_limit(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    clock = iter(range(0, 1000, 30))  # jeder Aufruf: +30 s
    monkeypatch.setattr(time, "monotonic", lambda: float(next(clock)))
    slow = [{"message": {"content": "", "thinking": "a"}, "done": False}] * 5
    fake = FakeOllama(chat_replies=[slow, plan_reply({"goal": "x", "phase": "edit"})])
    runner = make_runner(workspace, fake)
    plan = runner.make_plan("x", runner_auto(runner))
    assert plan.steps == (PlanStep("x", "edit"),)
    assert [c["think"] for c in chats(fake)] == [True, False]
