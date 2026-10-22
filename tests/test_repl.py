from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from rich.console import Console

from lcc.config import CliOverrides, load_config
from lcc.ollama_client import OllamaClient
from lcc.repl import Repl, SlashCompleter
from tests.fake_ollama import FakeOllama, stream_text, stream_tool_call


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "ws"
    (root / ".git").mkdir(parents=True)
    (root / "app.py").write_text("print('app')\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # Normaler Agent; der Kleinmodell-Modus hat einen eigenen Test (test_small_mode_in_repl).
    user_config = home / ".config" / "lcc" / "config.toml"
    user_config.parent.mkdir(parents=True)
    user_config.write_text('[small_model]\nmode = "off"\n', encoding="utf-8")
    monkeypatch.delenv("LCC_OLLAMA_URL", raising=False)
    monkeypatch.delenv("LCC_CODE_MODEL", raising=False)
    return root


class Harness:
    def __init__(self, workspace: Path, fake: FakeOllama, answers: list[str] | None = None):
        self.fake = fake
        self.output = io.StringIO()
        loaded = load_config(cwd=workspace, env={}, overrides=CliOverrides())
        self.answers = list(answers or [])
        self.repl = Repl(
            loaded,
            OllamaClient("http://x:1", transport=fake.transport()),
            console=Console(file=self.output, width=200, force_terminal=False),
            ask=lambda prompt: self.answers.pop(0),
        )

    def text(self) -> str:
        return self.output.getvalue()

    def chats(self) -> list[dict[str, Any]]:
        return [body for path, body in self.fake.requests if path == "/api/chat"]


def script(*items: str | BaseException) -> Callable[[], str]:
    queue = list(items)

    def read() -> str:
        if not queue:
            raise EOFError
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    return read


def server() -> FakeOllama:
    return FakeOllama().add_model("qwen3.5:9b").add_model("other:3b")


def test_conversation_keeps_history(workspace: Path) -> None:
    fake = server()
    fake.chat_replies += [stream_text("Hallo!"), stream_text("Du hast hallo gesagt.")]
    harness = Harness(workspace, fake)
    assert harness.repl.run(script("hallo", "was habe ich gesagt?")) == 0
    second = harness.chats()[1]["messages"]
    assert [m["role"] for m in second] == ["system", "user", "assistant", "user"]
    assert second[1]["content"] == "hallo"
    assert second[2]["content"] == "Hallo!"
    assert "Du hast hallo gesagt." in harness.text()


def test_history_contains_tool_messages(workspace: Path) -> None:
    fake = server()
    fake.chat_replies += [
        stream_tool_call("read_file", {"path": "app.py"}),
        stream_text("Gibt app aus."),
        stream_text("ok"),
    ]
    harness = Harness(workspace, fake)
    harness.repl.run(script("was macht app.py?", "danke"))
    roles = [m["role"] for m in harness.chats()[-1]["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "assistant", "user"]


def test_session_autosaved(workspace: Path) -> None:
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.run(script("hallo"))
    path = harness.repl.session.path
    assert path.is_file()
    assert path.is_relative_to(Path.home() / ".local" / "state" / "lcc" / "sessions")
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_clear_empties_history(workspace: Path) -> None:
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.run(script("eins", "/clear", "zwei"))
    last = harness.chats()[-1]["messages"]
    assert [m["content"] for m in last][1:] == ["zwei"]


def test_ctrl_c_during_generation_keeps_repl(workspace: Path) -> None:
    fake = server()
    calls = 0
    original = fake.handler

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/api/chat":
            calls += 1
            if calls == 1:
                raise KeyboardInterrupt
        return original(request)

    harness = Harness(workspace, fake)
    harness.repl.client = OllamaClient("http://x:1", transport=httpx.MockTransport(handler))
    harness.repl.run(script("lang", "kurz"))
    assert "Abgebrochen" in harness.text()
    assert calls == 2
    # Unterbrochene Runde landet nicht im Verlauf.
    assert [r["content"] for r in harness.repl.session.records] == ["kurz", "ok"]


def test_double_ctrl_c_at_prompt_exits(workspace: Path) -> None:
    harness = Harness(workspace, server())
    assert harness.repl.run(script(KeyboardInterrupt(), KeyboardInterrupt(), "nie")) == 0
    assert "Nochmal Strg-C" in harness.text()
    assert harness.chats() == []


def test_single_ctrl_c_then_input_continues(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script(KeyboardInterrupt(), "hallo", KeyboardInterrupt(), "noch da"))
    assert len(harness.chats()) == 2


def test_exit_command(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script("/exit", "nie"))
    assert harness.chats() == []
    assert "Tschüss" in harness.text()


def test_help_and_unknown_command(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script("/help", "/hepl"))
    assert "/undo" in harness.text()
    assert "Unbekannter Befehl /hepl. Meintest du /help?" in harness.text()


def test_model_switch(workspace: Path) -> None:
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.run(script("/model other:3b", "/model gibtsnicht:1b", "/model", "hallo"))
    assert "ollama pull gibtsnicht:1b" in harness.text()
    assert "Aktuelles Modell: other:3b" in harness.text()
    assert harness.chats()[-1]["model"] == "other:3b"


def test_models_marks_current(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script("/models"))
    assert "* qwen3.5:9b" in harness.text()
    assert "  other:3b" in harness.text()


def test_add_attaches_file_once(workspace: Path) -> None:
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.run(script("/add app.py", "erkläre", "und jetzt?", "/add ../geheim"))
    first = harness.chats()[0]["messages"][-1]["content"]
    assert "1| print('app')" in first
    assert first.endswith("erkläre")
    second = harness.chats()[1]["messages"][-1]["content"]
    assert second == "und jetzt?"
    assert "außerhalb" in harness.text()


def test_diff_and_undo(workspace: Path) -> None:
    fake = server()
    fake.chat_replies += [
        stream_tool_call("write_file", {"path": "neu.py", "content": "x = 1"}),
        stream_text("angelegt"),
    ]
    harness = Harness(workspace, fake, answers=["j"])
    harness.repl.run(script("/diff", "leg neu.py an", "/diff", "/undo", "/undo"))
    out = harness.text()
    assert "Keine Änderungen in dieser Session." in out
    assert "+x = 1" in out
    assert "gelöscht" in out
    assert "Nichts zum Zurücknehmen." in out
    assert not (workspace / "neu.py").exists()


def test_confirm_always_persists_across_turns(workspace: Path) -> None:
    fake = server()
    fake.chat_replies += [
        stream_tool_call("write_file", {"path": "a.py", "content": "1"}),
        stream_text("ok"),
        stream_tool_call("write_file", {"path": "b.py", "content": "2"}),
        stream_text("ok"),
    ]
    harness = Harness(workspace, fake, answers=["i"])
    harness.repl.run(script("a", "b"))
    assert (workspace / "a.py").exists() and (workspace / "b.py").exists()
    assert harness.answers == []


def test_save_and_load(workspace: Path) -> None:
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.run(
        script("merk dir 42", "/save meine", "/clear", "/load", "/load meine", "weiter")
    )
    out = harness.text()
    assert "meine.jsonl" in out
    assert "meine" in out and "Nachrichten" in out
    last = harness.chats()[-1]["messages"]
    assert [m["content"] for m in last][1:] == ["merk dir 42", "ok", "weiter"]


def test_load_unknown_session(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script("/load gibtsnicht"))
    assert "nicht gefunden" in harness.text()


def test_config_command(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script("/config"))
    assert 'code = "qwen3.5:9b"  # Default' in harness.text()


def test_rag_toggle(workspace: Path) -> None:
    harness = Harness(workspace, server())
    harness.repl.run(script("/rag off"))
    assert harness.repl.rag_enabled is False


def test_server_error_keeps_repl(workspace: Path) -> None:
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.model = "fehlt:1b"
    harness.repl.run(script("hallo", "/exit"))
    assert "ollama pull fehlt:1b" in harness.text()
    assert "Tschüss" in harness.text()


def test_completer(workspace: Path) -> None:
    completer = SlashCompleter(workspace)
    event = CompleteEvent()
    names = [c.text for c in completer.get_completions(Document("/mo"), event)]
    assert names == ["/model", "/models"]
    assert list(completer.get_completions(Document("hallo /mo"), event)) == []
    paths = [c.text for c in completer.get_completions(Document("/add ap"), event)]
    assert paths == ["p.py"]


def test_rag_command_and_toggle(workspace: Path) -> None:
    from lcc.rag.indexer import Indexer
    from lcc.rag.store import Store
    from tests.fake_ollama import keyword_embedding

    (workspace / "docs").mkdir()
    (workspace / "docs" / "tiere.md").write_text("# Tiere\n\nDie katze.\n", encoding="utf-8")
    (workspace / ".lcc").mkdir()
    (workspace / ".lcc" / "config.toml").write_text("[rag]\nmin_score = 0.1\n", encoding="utf-8")
    fake = server().add_model("bge-m3:latest", capabilities=("embedding",))
    fake.embed_fn = keyword_embedding
    config = load_config(cwd=workspace, env={}, overrides=CliOverrides()).config
    with Store(config.rag.index_path) as store:
        Indexer(config, OllamaClient("http://x:1", transport=fake.transport()), store).run()

    harness = Harness(workspace, fake)
    assert harness.repl.context.rag is not None
    harness.repl.run(script("/rag katze", "/rag off", "frage", "/rag on", "frage2"))
    assert "[1] docs/tiere.md:1-3" in harness.text()
    chats = harness.chats()
    assert "rag_search" not in [t["function"]["name"] for t in chats[0]["tools"]]
    assert "rag_search" in [t["function"]["name"] for t in chats[1]["tools"]]


def test_skill_commands_and_auto_load(workspace: Path) -> None:
    from lcc.skills.scaffold import create_skill

    create_skill(workspace / ".lcc" / "skills", "pytest-test", example=True)
    create_skill(workspace / ".lcc" / "skills", "anderer")
    fake = server()
    harness = Harness(workspace, fake)
    harness.repl.run(
        script(
            "/skills", "/skill anderer", "/skill anderer", "/skill nope", "schreib Tests", "/skills"
        )
    )
    out = harness.text()
    assert "pytest-test: Schreibt pytest-Tests" in out
    assert "⚙ Skill: anderer" in out
    assert "bereits geladen" in out
    assert "Unbekannter Skill 'nope'" in out
    assert "⚙ Skill: pytest-test" in out
    assert "⚙ pytest-test" in out
    chat = harness.chats()[-1]
    contents = [m["content"] for m in chat["messages"]]
    assert any("Skill 'anderer'" in c for c in contents)
    assert any("# pytest-Tests schreiben" in c for c in contents)
    # Skill-Bodies bleiben im Verlauf
    assert any("pytest-Tests schreiben" in r["content"] for r in harness.repl.session.records)


def test_small_mode_in_repl_with_plan_dialog(workspace: Path) -> None:
    import json as _json

    Path.home().joinpath(".config/lcc/config.toml").unlink()  # mode = "auto", 9.7B → klein
    (workspace / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    plan = {"steps": [{"goal": "add korrigieren", "phase": "edit", "files": ["calc.py"]}]}
    fake = server()
    fake.chat_replies += [
        [{"message": {"role": "assistant", "content": _json.dumps(plan)}, "done": True}],
        stream_tool_call("edit_file", {"path": "calc.py", "old_str": "a - b", "new_str": "a + b"}),
        stream_text("Korrigiert."),
        [{"message": {"role": "assistant", "content": _json.dumps(plan)}, "done": True}],
    ]
    # Plan 1: mit Enter ausführen (+ Schreib-Bestätigung "j"), Plan 2: mit "n" abbrechen
    harness = Harness(workspace, fake, answers=["", "j", "n"])
    harness.repl.run(script("korrigiere add in calc.py", "nochmal"))
    out = harness.text()
    assert "Plan:" in out and "1. [edit] add korrigieren (calc.py)" in out
    assert "▶ Schritt 1/1 [edit]: add korrigieren" in out
    assert "✓ Check bestanden: python -m py_compile calc.py" in out
    assert "a + b" in (workspace / "calc.py").read_text()
    assert "Plan abgebrochen." in out
    contents = [r["content"] for r in harness.repl.session.records]
    assert contents == ["korrigiere add in calc.py", "Korrigiert.", "nochmal", "Plan abgebrochen."]
