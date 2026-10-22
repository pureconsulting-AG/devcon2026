from __future__ import annotations

import io

from rich.console import Console

from lcc.ollama_client import ChatChunk, ToolCall
from lcc.output import ChatRenderer


def renderer(
    *, terminal: bool = True, json_mode: bool = False, thinking: bool = False
) -> ChatRenderer:
    err = Console(file=io.StringIO(), force_terminal=terminal, width=80)
    out = Console(file=io.StringIO(), force_terminal=False, width=80)
    return ChatRenderer(
        json_mode=json_mode,
        markdown=False,
        show_thinking=thinking,
        console=out,
        err_console=err,
    )


def test_spinner_until_first_token() -> None:
    r = renderer()
    r.start_waiting()
    assert r._waiting_live is not None
    r.on_chunk(ChatChunk(content=""))
    assert r._waiting_live is not None
    r.on_chunk(ChatChunk(content="Hallo"))
    assert r._waiting_live is None


def test_spinner_stops_on_tool_call() -> None:
    r = renderer()
    r.start_waiting()
    r.on_chunk(ChatChunk(tool_calls=(ToolCall("list_dir", {}),)))
    assert r._waiting_live is None


def test_hidden_thinking_changes_label() -> None:
    r = renderer()
    r.start_waiting()
    r.on_chunk(ChatChunk(thinking="hmm"))
    assert r._waiting is not None
    assert r._waiting.label == "überlegt …"
    r.end_message()
    assert r._waiting_live is not None  # Nachricht fertig ≠ Auftrag fertig
    r.done()
    assert r._waiting_live is None


def test_shown_thinking_stops_spinner() -> None:
    r = renderer(thinking=True)
    r.start_waiting()
    r.on_chunk(ChatChunk(thinking="hmm"))
    assert r._waiting_live is None


def test_no_spinner_without_terminal_or_in_json_mode() -> None:
    for r in (renderer(terminal=False), renderer(json_mode=True)):
        r.start_waiting()
        assert r._waiting_live is None


def test_abort_stops_spinner() -> None:
    r = renderer()
    r.start_waiting()
    r.abort()
    assert r._waiting_live is None


def test_spinner_runs_during_tools_steps_and_checks() -> None:
    from lcc.agent.small_model import PlanStep

    r = renderer()
    r.tool_call(ToolCall("run_shell", {"command": "pytest"}))
    assert r._waiting is not None and r._waiting.label == "führt run_shell aus …"
    r.step(2, 3, PlanStep("ändern", "edit"))
    assert r._waiting is not None and r._waiting.label == "bereitet den Schritt vor …"
    r.check_start("python -m pytest -q")
    assert r._waiting is not None and r._waiting.label == "prüft: python -m pytest -q …"
    r.info("⚙ Skill: pytest-test")
    r.notice("Hinweis")
    assert r._waiting_live is not None  # Statuszeilen erscheinen über dem Spinner
    r.on_chunk(ChatChunk(content="Antwort"))
    assert r._waiting_live is None  # Antworttext ersetzt den Spinner


def test_start_waiting_relabels_running_spinner() -> None:
    r = renderer()
    r.start_waiting("eins")
    live = r._waiting_live
    r.start_waiting()
    assert r._waiting_live is live
    assert r._waiting is not None and r._waiting.label == "denkt nach …"
    r.final("x")
    assert r._waiting_live is None


def test_confirmer_pauses_spinner_before_prompt() -> None:
    from lcc.agent.sandbox import Confirmer

    r = renderer()
    r.start_waiting()
    seen: list[bool] = []

    def ask(prompt: str) -> str:
        seen.append(r._waiting_live is None)
        return "j"

    confirmer = Confirmer(
        interactive=True, ask=ask, before_prompt=r.stop_waiting, console=r.err_console
    )
    assert confirmer.confirm_command("touch x")
    r.start_waiting()
    assert confirmer.confirm_write("a.py", "+x")
    r.start_waiting()
    confirmer.ask_line("> ")
    assert seen == [True, True, True]
