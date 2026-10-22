from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc import cli
from lcc.config import Config
from lcc.ollama_client import OllamaClient
from tests.fake_ollama import FakeOllama, stream_text, stream_tool_call

runner = CliRunner()


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeOllama:
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LCC_OLLAMA_URL", raising=False)
    monkeypatch.delenv("LCC_CODE_MODEL", raising=False)
    monkeypatch.chdir(work)
    monkeypatch.setenv("COLUMNS", "200")
    # Diese Tests prüfen den normalen Agenten; der Kleinmodell-Modus hat eigene Tests (--small).
    user_config = home / ".config" / "lcc" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('[small_model]\nmode = "off"\n', encoding="utf-8")
    server = FakeOllama()

    def make_client(config: Config) -> OllamaClient:
        return OllamaClient.from_config(config.ollama, transport=server.transport())

    monkeypatch.setattr(cli, "make_client", make_client)
    return server


def standard_server(fake: FakeOllama) -> FakeOllama:
    fake.add_model("qwen3.5:9b", capabilities=("completion", "tools", "thinking"))
    fake.add_model("bge-m3:latest", "566.70M", ("embedding",))
    return fake


# -- ask ---------------------------------------------------------------------


def test_ask_streams_answer(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies.append(stream_text("Hallo ", "Welt"))
    result = runner.invoke(cli.app, ["ask", "Sag hallo"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "Hallo Welt\n"
    path, body = fake.requests[-1]
    assert path == "/api/chat"
    assert body["model"] == "qwen3.5:9b"
    assert body["messages"] == [{"role": "user", "content": "Sag hallo"}]
    assert "tools" not in body
    assert body["think"] is False  # Thinking-Modell, Thinking in der Config aus
    assert body["options"] == {"num_ctx": 16384, "temperature": 0.2}
    assert body["keep_alive"] == "10m"


def test_ask_no_think_for_non_thinking_model(fake: FakeOllama, tmp_path: Path) -> None:
    standard_server(fake).add_model("plain:3b", capabilities=("completion",))
    result = runner.invoke(cli.app, ["--model", "plain:3b", "ask", "x"])
    assert result.exit_code == 0, result.output
    assert "think" not in fake.requests[-1][1]


def test_ask_uses_chat_model(fake: FakeOllama, tmp_path: Path) -> None:
    standard_server(fake).add_model("small:1b")
    cfg = tmp_path / "c.toml"
    cfg.write_text('[models]\nchat = "small:1b"\n', encoding="utf-8")
    result = runner.invoke(cli.app, ["--config", str(cfg), "ask", "x"])
    assert result.exit_code == 0, result.output
    assert fake.requests[-1][1]["model"] == "small:1b"


def test_ask_with_stdin_appends_context(fake: FakeOllama) -> None:
    standard_server(fake)
    result = runner.invoke(cli.app, ["ask", "erkläre"], input="def f():\n    return 1\n")
    assert result.exit_code == 0, result.output
    content = fake.requests[-1][1]["messages"][0]["content"]
    assert content.startswith("erkläre\n")
    assert "def f():\n    return 1" in content


def test_ask_stdin_only(fake: FakeOllama) -> None:
    standard_server(fake)
    result = runner.invoke(cli.app, ["ask"], input="Was ist 2+2?\n")
    assert result.exit_code == 0, result.output
    assert fake.requests[-1][1]["messages"][0]["content"] == "Was ist 2+2?"


def test_ask_without_input_is_error(fake: FakeOllama) -> None:
    result = runner.invoke(cli.app, ["ask"], input="")
    assert result.exit_code == 1
    assert fake.requests == []


def test_ask_json_events(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies.append(stream_text("a", "b"))
    result = runner.invoke(cli.app, ["--json", "ask", "x"])
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert events == [
        {"type": "token", "content": "a"},
        {"type": "token", "content": "b"},
        {"type": "final", "content": "ab", "model": "qwen3.5:9b", "sources": []},
    ]


def test_ask_thinking_hidden_by_default(fake: FakeOllama, tmp_path: Path) -> None:
    standard_server(fake).chat_replies.append(stream_text("42", thinking="grübel"))
    cfg = tmp_path / "c.toml"
    cfg.write_text("[models.thinking]\nenabled = true\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["--config", str(cfg), "ask", "x"])
    assert result.exit_code == 0, result.output
    assert fake.requests[-1][1]["think"] is True
    assert "grübel" not in result.output
    assert result.stdout == "42\n"


def test_ask_show_thinking_goes_to_stderr(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies.append(stream_text("42", thinking="grübel"))
    result = runner.invoke(cli.app, ["--show-thinking", "ask", "x"])
    assert result.exit_code == 0, result.output
    assert "grübel" in result.stderr
    assert result.stdout == "42\n"


def test_ask_server_unreachable_exit_3(fake: FakeOllama) -> None:
    fake.unreachable = True
    result = runner.invoke(cli.app, ["ask", "x"])
    assert result.exit_code == 3
    assert "http://192.168.178.79:11434" in result.stderr


def test_ask_model_missing_exit_4(fake: FakeOllama) -> None:
    result = runner.invoke(cli.app, ["ask", "x"])
    assert result.exit_code == 4
    assert "ollama pull qwen3.5:9b" in result.stderr


def test_ask_error_as_json(fake: FakeOllama) -> None:
    result = runner.invoke(cli.app, ["--json", "ask", "x"])
    assert result.exit_code == 4
    event = json.loads(result.stdout.strip())
    assert event["type"] == "error"
    assert event["exit_code"] == 4


def test_model_flag_overrides(fake: FakeOllama) -> None:
    standard_server(fake).add_model("other:3b")
    result = runner.invoke(cli.app, ["--model", "other:3b", "ask", "x"])
    assert result.exit_code == 0, result.output
    assert fake.requests[-1][1]["model"] == "other:3b"


# -- models ------------------------------------------------------------------


def test_models_lists_and_marks_missing(fake: FakeOllama) -> None:
    fake.add_model("qwen3.5:9b").add_model("llama3:8b")
    result = runner.invoke(cli.app, ["models"])
    assert result.exit_code == 0, result.output
    assert "qwen3.5:9b" in result.stdout
    assert "llama3:8b" in result.stdout
    assert "code, chat" in result.stdout
    assert "ollama pull bge-m3" in result.stdout


def test_models_json(fake: FakeOllama) -> None:
    standard_server(fake)
    result = runner.invoke(cli.app, ["--json", "models"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    roles = {model["name"]: model["roles"] for model in data["models"]}
    assert roles == {"qwen3.5:9b": ["code", "chat"], "bge-m3:latest": ["embed"]}
    assert data["missing"] == []


def test_models_unreachable(fake: FakeOllama) -> None:
    fake.unreachable = True
    assert runner.invoke(cli.app, ["models"]).exit_code == 3


# -- doctor ------------------------------------------------------------------


def test_doctor_all_green(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies.append(stream_tool_call("echo", {"text": "ok"}))
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "native tool_calls funktionieren" in result.stdout
    assert "Dimension 4" in result.stdout
    assert "✗" not in result.stdout


def test_doctor_json(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies.append(stream_tool_call("echo", {"text": "ok"}))
    result = runner.invoke(cli.app, ["--json", "doctor"])
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert {e["status"] for e in events if e["type"] == "check"} == {"ok"}
    model_events = [e for e in events if e["type"] == "model"]
    assert {e["name"] for e in model_events} == {"qwen3.5:9b", "bge-m3"}


def test_doctor_unreachable_exit_3(fake: FakeOllama) -> None:
    fake.unreachable = True
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 3
    assert "nicht erreichbar" in result.stdout


def test_doctor_model_missing_exit_4(fake: FakeOllama) -> None:
    fake.add_model("qwen3.5:9b").chat_replies.append(stream_tool_call("echo", {"text": "ok"}))
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 4
    assert "ollama pull bge-m3" in result.stdout


def test_doctor_text_tool_mode_is_warning(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies.append(stream_text('{"tool": "echo"}'))
    result = runner.invoke(cli.app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "Text-Tool-Modus" in result.stdout


# -- run ---------------------------------------------------------------------


def test_run_reads_file_and_answers(fake: FakeOllama) -> None:
    Path("hello.py").write_text("print('hallo')\n", encoding="utf-8")
    standard_server(fake).chat_replies += [
        stream_tool_call("read_file", {"path": "hello.py"}),
        stream_text("Gibt hallo aus."),
    ]
    result = runner.invoke(cli.app, ["run", "Was macht hello.py?"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "Gibt hallo aus.\n"
    assert "→ read_file(path='hello.py')" in result.stderr
    first_request = next(body for path, body in fake.requests if path == "/api/chat")
    assert first_request["model"] == "qwen3.5:9b"
    assert first_request["messages"][0]["role"] == "system"
    assert first_request["messages"][-1] == {"role": "user", "content": "Was macht hello.py?"}


def test_run_json_events(fake: FakeOllama) -> None:
    Path("hello.py").write_text("x\n", encoding="utf-8")
    standard_server(fake).chat_replies += [
        stream_tool_call("read_file", {"path": "hello.py"}),
        stream_text("fertig"),
    ]
    result = runner.invoke(cli.app, ["--json", "run", "lies hello.py"])
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert [e["type"] for e in events] == ["tool_call", "tool_result", "token", "final"]
    assert events[1]["ok"] is True
    assert events[-1]["stop_reason"] == "done"


def test_run_max_steps_exit_1(fake: FakeOllama, tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    cfg.write_text("[agent]\nmax_steps = 1\n", encoding="utf-8")
    standard_server(fake).chat_replies.append(stream_tool_call("list_dir", {}))
    result = runner.invoke(cli.app, ["--config", str(cfg), "run", "x"])
    assert result.exit_code == 1
    assert "Maximale Anzahl" in result.stderr


def test_run_without_task(fake: FakeOllama) -> None:
    assert runner.invoke(cli.app, ["run"], input="").exit_code == 1


def test_run_includes_agent_md(fake: FakeOllama) -> None:
    Path(".lcc").mkdir()
    Path(".lcc/AGENT.md").write_text("Antworte immer mit Emoji.", encoding="utf-8")
    standard_server(fake)
    result = runner.invoke(cli.app, ["run", "x"])
    assert result.exit_code == 0, result.output
    chat = next(body for path, body in fake.requests if path == "/api/chat")
    assert "Antworte immer mit Emoji." in chat["messages"][0]["content"]


# -- run: Schreiben ----------------------------------------------------------


def test_run_without_yes_and_tty_denies_write(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies += [
        stream_tool_call("write_file", {"path": "neu.py", "content": "x = 1"}),
        stream_text("Konnte nicht schreiben."),
    ]
    result = runner.invoke(cli.app, ["run", "leg neu.py an"])
    assert result.exit_code == 0, result.output
    assert not Path("neu.py").exists()
    tool_message = fake.requests[-1][1]["messages"][-1]
    assert "--yes" in tool_message["content"]


def test_run_yes_writes_and_undo_restores(fake: FakeOllama) -> None:
    standard_server(fake).chat_replies += [
        stream_tool_call("write_file", {"path": "neu.py", "content": "x = 1"}),
        stream_text("Angelegt."),
    ]
    result = runner.invoke(cli.app, ["run", "--yes", "leg neu.py an"])
    assert result.exit_code == 0, result.output
    assert Path("neu.py").read_text(encoding="utf-8") == "x = 1\n"

    result = runner.invoke(cli.app, ["undo"])
    assert result.exit_code == 0, result.output
    assert "gelöscht" in result.stderr
    assert not Path("neu.py").exists()

    result = runner.invoke(cli.app, ["undo"])
    assert result.exit_code == 1
    assert "Nichts" in result.stderr


# -- rag ---------------------------------------------------------------------


@pytest.fixture
def rag_project(fake: FakeOllama) -> FakeOllama:
    from tests.fake_ollama import keyword_embedding

    Path("docs").mkdir()
    Path("docs/tiere.md").write_text("# Tiere\n\nDie katze schläft.\n", encoding="utf-8")
    Path("docs/server.md").write_text("# Server\n\nDer ollama server.\n", encoding="utf-8")
    Path(".lcc").mkdir()
    Path(".lcc/config.toml").write_text('[rag]\nsources = ["../docs"]\nmin_score = 0.1\n')
    fake.embed_fn = keyword_embedding
    return standard_server(fake)


def test_rag_index_search_stats(rag_project: FakeOllama) -> None:
    result = runner.invoke(cli.app, ["rag", "stats"])
    assert result.exit_code == 1
    assert "lcc rag index" in result.stderr

    result = runner.invoke(cli.app, ["rag", "index"])
    assert result.exit_code == 0, result.output
    assert "2 neu" in result.stderr
    assert "2 Dateien" in result.stderr

    result = runner.invoke(cli.app, ["rag", "index"])
    assert "2 unverändert" in result.stderr

    result = runner.invoke(cli.app, ["rag", "search", "katze"])
    assert result.exit_code == 0, result.output
    assert "[1] docs/tiere.md:1-3" in result.stdout

    result = runner.invoke(cli.app, ["--json", "rag", "search", "katze", "-k", "1"])
    hits = json.loads(result.stdout)
    assert len(hits) == 1
    assert hits[0]["path"] == "docs/tiere.md"

    result = runner.invoke(cli.app, ["--json", "rag", "stats"])
    stats = json.loads(result.stdout)
    assert stats["documents"] == 2
    assert stats["model"] == "bge-m3"
    assert stats["dimension"] == 10


def test_rag_search_without_index(rag_project: FakeOllama) -> None:
    result = runner.invoke(cli.app, ["rag", "search", "x"])
    assert result.exit_code == 1
    assert "lcc rag index" in result.stderr


def test_ask_uses_rag_context(rag_project: FakeOllama) -> None:
    runner.invoke(cli.app, ["rag", "index"])
    result = runner.invoke(cli.app, ["ask", "Was macht die katze?"])
    assert result.exit_code == 0, result.output
    assert "RAG: [1] docs/tiere.md:1-3" in result.stderr
    content = rag_project.requests[-1][1]["messages"][0]["content"]
    assert content.startswith("Auszüge aus der Projektdokumentation")
    assert "[1] docs/tiere.md:1-3 (score" in content
    assert content.endswith("Was macht die katze?")


def test_ask_no_rag_flag(rag_project: FakeOllama) -> None:
    runner.invoke(cli.app, ["rag", "index"])
    result = runner.invoke(cli.app, ["--no-rag", "ask", "Was macht die katze?"])
    assert result.exit_code == 0, result.output
    assert rag_project.requests[-1][1]["messages"][0]["content"] == "Was macht die katze?"


def test_run_offers_rag_search_only_with_index(rag_project: FakeOllama) -> None:
    runner.invoke(cli.app, ["run", "x"])
    tools = [t["function"]["name"] for t in rag_project.requests[-1][1]["tools"]]
    assert "rag_search" not in tools

    runner.invoke(cli.app, ["rag", "index"])
    rag_project.chat_replies += [
        stream_tool_call("rag_search", {"query": "katze"}),
        stream_text("ok"),
    ]
    result = runner.invoke(cli.app, ["run", "Was steht in der Doku zur katze?"])
    assert result.exit_code == 0, result.output
    chat = rag_project.requests[-1][1]
    assert "rag_search" in [t["function"]["name"] for t in chat["tools"]]
    assert "[n]" in chat["messages"][0]["content"]
    assert "[1] docs/tiere.md:1-3" in chat["messages"][-1]["content"]


# -- skills ------------------------------------------------------------------


def test_skills_new_list_show_check_match(fake: FakeOllama) -> None:
    result = runner.invoke(cli.app, ["skills"])
    assert result.exit_code == 0
    assert "Keine Skills" in result.stderr

    assert runner.invoke(cli.app, ["skills", "new"]).exit_code == 1
    result = runner.invoke(cli.app, ["skills", "new", "--example"])
    assert result.exit_code == 0, result.output
    assert Path(".lcc/skills/pytest-test/SKILL.md").is_file()
    assert runner.invoke(cli.app, ["skills", "new", "--example"]).exit_code == 1
    assert runner.invoke(cli.app, ["skills", "new", "mein-skill"]).exit_code == 0
    result = runner.invoke(cli.app, ["skills", "new", "--user", "user-skill"])
    assert result.exit_code == 0, result.output
    assert (Path.home() / ".config/lcc/skills/user-skill/SKILL.md").is_file()

    result = runner.invoke(cli.app, ["skills"])
    assert "pytest-test" in result.stdout
    assert "Projekt" in result.stdout and "Benutzer" in result.stdout

    result = runner.invoke(cli.app, ["skills", "show", "pytest-test"])
    assert result.exit_code == 0
    assert "triggers: pytest, tests" in result.stdout
    assert "# pytest-Tests schreiben" in result.stdout
    assert runner.invoke(cli.app, ["skills", "show", "nope"]).exit_code == 1

    result = runner.invoke(cli.app, ["skills", "check"])
    assert result.exit_code == 0, result.output
    assert "0 Fehler" in result.stdout

    standard_server(fake)
    result = runner.invoke(cli.app, ["--json", "skills", "match", "schreib Tests für slugify"])
    assert result.exit_code == 0, result.output
    matches = json.loads(result.stdout)
    assert matches[0]["name"] == "pytest-test"
    assert matches[0]["score"] == 1.0
    assert matches[0]["reason"] == "Trigger 'tests'"
    assert matches[0]["auto_load"] is True

    result = runner.invoke(cli.app, ["skills", "match", "schreib Tests für slugify"])
    assert "wird automatisch geladen" in result.stdout


def test_skills_check_reports_errors(fake: FakeOllama) -> None:
    broken = Path(".lcc/skills/kaputt/SKILL.md")
    broken.parent.mkdir(parents=True)
    broken.write_text("---\nname: kaputt\n---\nBody\n", encoding="utf-8")
    result = runner.invoke(cli.app, ["skills", "check"])
    assert result.exit_code == 1
    assert "description" in result.stdout


def test_run_auto_loads_skill_and_runs_checks(fake: FakeOllama, tmp_path: Path) -> None:
    import sys

    runner.invoke(cli.app, ["skills", "new", "--example"])
    skill = Path(".lcc/skills/pytest-test/SKILL.md")
    text = skill.read_text(encoding="utf-8").replace(
        "checks: python -m pytest -q {test_file}",
        f'checks: {sys.executable} -c "import sys; sys.exit(1)" {{test_file}}',
    )
    skill.write_text(text, encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text(f'[agent]\nshell_allowlist = ["{sys.executable}"]\n', encoding="utf-8")
    standard_server(fake).chat_replies += [
        stream_tool_call("write_file", {"path": "tests/test_utils.py", "content": "x"}),
        stream_text("Tests geschrieben."),
    ]
    result = runner.invoke(
        cli.app, ["--config", str(cfg), "run", "--yes", "schreib Tests für slugify"]
    )
    assert "⚙ Skill: pytest-test" in result.stderr
    chat = next(b for p, b in fake.requests if p == "/api/chat")
    assert "- pytest-test: Schreibt pytest-Tests" in chat["messages"][0]["content"]
    assert chat["messages"][1]["role"] == "system"
    assert "# pytest-Tests schreiben" in chat["messages"][1]["content"]
    assert chat["messages"][-1]["content"] == "schreib Tests für slugify"
    assert "✗ Check fehlgeschlagen" in result.stderr
    assert "nicht erfolgreich" in result.stderr
    assert result.exit_code == 1


def test_no_skills_flag(fake: FakeOllama) -> None:
    runner.invoke(cli.app, ["skills", "new", "--example"])
    standard_server(fake)
    result = runner.invoke(cli.app, ["--no-skills", "run", "schreib Tests"])
    assert result.exit_code == 0, result.output
    chat = next(b for p, b in fake.requests if p == "/api/chat")
    assert "pytest-test" not in chat["messages"][0]["content"]
    assert "load_skill" not in [t["function"]["name"] for t in chat["tools"]]


def test_doctor_shows_small_model_column(fake: FakeOllama) -> None:
    Path.home().joinpath(".config/lcc/config.toml").unlink()  # Default: mode = "auto"
    standard_server(fake).chat_replies.append(stream_tool_call("echo", {"text": "ok"}))
    result = runner.invoke(cli.app, ["--json", "doctor"])
    models = {
        e["name"]: e for e in map(json.loads, result.stdout.splitlines()) if e["type"] == "model"
    }
    assert models["qwen3.5:9b"]["small_model"] is True
    assert models["bge-m3"]["small_model"] is None


# -- Kleinmodell-Modus --------------------------------------------------------


def _plan(*steps: dict[str, object]) -> list[dict[str, object]]:
    content = json.dumps({"steps": list(steps)})
    return [{"message": {"role": "assistant", "content": content}, "done": True}]


def test_run_small_mode_plan_steps_and_verify(fake: FakeOllama) -> None:
    Path("calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    standard_server(fake).chat_replies += [
        _plan(
            {"goal": "calc.py lesen", "phase": "explore", "files": ["calc.py"]},
            {"goal": "add korrigieren", "phase": "edit"},
        ),
        stream_text("add subtrahiert."),
        stream_tool_call("edit_file", {"path": "calc.py", "old_str": "a - b", "new_str": "a + b"}),
        stream_text("Korrigiert."),
    ]
    result = runner.invoke(cli.app, ["--json", "run", "--small", "--yes", "korrigiere calc.py"])
    assert result.exit_code == 0, result.output
    events = [json.loads(line) for line in result.stdout.splitlines()]
    types = [e["type"] for e in events]
    assert types.count("step") == 2
    plan = next(e for e in events if e["type"] == "plan")
    assert [s["phase"] for s in plan["steps"]] == ["explore", "edit"]
    checks = [e for e in events if e["type"] == "check"]
    assert checks and checks[0]["command"] == "python -m py_compile calc.py"
    assert checks[0]["ok"] is True
    final = events[-1]
    assert final["type"] == "final" and final["small_mode"] is True and final["ok"] is True
    assert "a + b" in Path("calc.py").read_text()


def test_run_auto_small_mode_from_model_size(fake: FakeOllama) -> None:
    Path.home().joinpath(".config/lcc/config.toml").unlink()
    standard_server(fake).chat_replies += [
        _plan({"goal": "erklären", "phase": "explore"}),
        stream_text("Erklärt."),
    ]
    result = runner.invoke(cli.app, ["run", "erkläre das Projekt"])
    assert result.exit_code == 0, result.output
    assert "Kleinmodell-Modus (qwen3.5:9b, 9.7B)" in result.stderr
    assert fake.requests[[p for p, _ in fake.requests].index("/api/chat")][1]["format"]
    assert result.stdout.strip() == "Erklärt."
    # --no-small schaltet ab
    standard_server(fake).chat_replies.append(stream_text("normal"))
    result = runner.invoke(cli.app, ["run", "--no-small", "x"])
    assert "Kleinmodell" not in result.stderr
    assert "format" not in fake.requests[-1][1]


def test_run_small_mode_honest_failure_exit_1(fake: FakeOllama, tmp_path: Path) -> None:
    import sys

    Path("calc.py").write_text("x = 1\n", encoding="utf-8")
    cfg = tmp_path / "c.toml"
    cfg.write_text(
        f'[agent]\nshell_allowlist = ["{sys.executable}"]\n'
        f'[small_model]\nverify_commands = ["{sys.executable} -c \\"raise SystemExit(1)\\""]\n'
        "max_repair_attempts = 1\n",
        encoding="utf-8",
    )
    standard_server(fake).chat_replies += [
        _plan({"goal": "ändern", "phase": "edit"}),
        stream_tool_call("write_file", {"path": "calc.py", "content": "x = 2"}),
        stream_text("geändert"),
        stream_text("weiß nicht"),
        stream_text("immer noch nicht"),
    ]
    result = runner.invoke(cli.app, ["--config", str(cfg), "run", "--small", "--yes", "x"])
    assert result.exit_code == 1
    assert "nicht erfolgreich abgeschlossen" in result.stderr
    assert "lcc undo" in result.stderr


def test_plan_dialog_edit_and_cancel() -> None:
    from lcc.agent.small_model import Plan, PlanStep, confirm_plan

    plan = Plan((PlanStep("a", "edit"),))
    said: list[str] = []
    answers = iter(["e", "explore: lesen", "edit: ändern", "", "x", ""])
    edited = confirm_plan(plan, lambda prompt: next(answers), said.append)
    assert edited is not None
    assert [(s.phase, s.goal) for s in edited.steps] == [("explore", "lesen"), ("edit", "ändern")]
    assert confirm_plan(plan, lambda prompt: "n", said.append) is None
    bad = iter(["e", "falsch", "", "j"])
    assert confirm_plan(plan, lambda prompt: next(bad), said.append) == plan
    assert any("Ungültige Zeile" in s for s in said)


def test_json_config_error_and_undo(fake: FakeOllama, tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[agent]\nmax_steps = "x"\n', encoding="utf-8")
    result = runner.invoke(cli.app, ["--json", "--config", str(bad), "run", "x"])
    assert result.exit_code == 2
    event = json.loads(result.stdout.strip())
    assert event == {"type": "error", "message": event["message"], "exit_code": 2}
    assert "agent.max_steps" in event["message"]

    result = runner.invoke(cli.app, ["--json", "undo"])
    assert result.exit_code == 1
    assert json.loads(result.stdout) == {"type": "undo", "ok": False}
    standard_server(fake).chat_replies += [
        stream_tool_call("write_file", {"path": "neu.py", "content": "x"}),
        stream_text("ok"),
    ]
    runner.invoke(cli.app, ["run", "--yes", "x"])
    result = runner.invoke(cli.app, ["--json", "undo"])
    assert json.loads(result.stdout) == {
        "type": "undo",
        "ok": True,
        "path": "neu.py",
        "action": "deleted",
    }
