from __future__ import annotations

from pathlib import Path

from lcc.agent.loop import create_agent
from lcc.agent.sandbox import Sandbox
from lcc.agent.toolcall_parser import parse_tool_calls
from lcc.agent.tools import ToolContext
from lcc.config import default_config
from lcc.ollama_client import OllamaClient, ToolCall
from tests.fake_ollama import FakeOllama, stream_text, stream_tool_call

KNOWN = {"read_file", "list_dir", "edit_file"}


def test_valid_plain_and_fenced() -> None:
    text = 'Ich lese die Datei.\n{"tool": "read_file", "arguments": {"path": "a.py"}}'
    assert parse_tool_calls(text, KNOWN) == [ToolCall("read_file", {"path": "a.py"})]
    fenced = 'So:\n```json\n{\n  "tool": "list_dir",\n  "arguments": {"path": "."}\n}\n```\n'
    assert parse_tool_calls(fenced, KNOWN) == [ToolCall("list_dir", {"path": "."})]


def test_broken_json_is_ignored() -> None:
    text = '{"tool": "read_file", "arguments": {"path": "a.py"}'  # schließende Klammer fehlt
    assert parse_tool_calls(text, KNOWN) == []
    text = '{"tool": "read_file", "arguments": {path: a.py}}'
    assert parse_tool_calls(text, KNOWN) == []


def test_unknown_tool_is_ignored() -> None:
    assert parse_tool_calls('{"tool": "rm_rf", "arguments": {}}', KNOWN) == []
    # ohne Liste bekannter Tools wird jeder {"tool": …}-Block übernommen
    assert parse_tool_calls('{"tool": "rm_rf", "arguments": {}}') == [ToolCall("rm_rf", {})]


def test_multiple_blocks_in_order() -> None:
    text = (
        '{"tool": "read_file", "arguments": {"path": "a.py"}}\n'
        "und dann\n"
        '```json\n{"tool": "edit_file", "arguments": {"path": "a.py", "old_str": "x", '
        '"new_str": "y"}}\n```'
    )
    assert [c.name for c in parse_tool_calls(text, KNOWN)] == ["read_file", "edit_file"]


def test_name_variant_and_string_arguments() -> None:
    text = '<tool_call>{"name": "read_file", "arguments": "{\\"path\\": \\"a.py\\"}"}</tool_call>'
    assert parse_tool_calls(text, KNOWN) == [ToolCall("read_file", {"path": "a.py"})]
    assert parse_tool_calls('{"name": "read_file", "arguments": {}}') == []


def test_ordinary_json_is_not_a_call() -> None:
    text = 'Ergebnis: {"tool": "read_file", "arguments": {}, "comment": "nur Beispiel"}'
    assert parse_tool_calls(text, KNOWN) == []
    assert parse_tool_calls('{"name": "Max", "alter": 3}', KNOWN) == []
    assert parse_tool_calls("keine Klammern hier", KNOWN) == []


# -- Einsatz in der Agent-Schleife -------------------------------------------


def make_ctx(tmp_path: Path) -> ToolContext:
    (tmp_path / "a.py").write_text("print('a')\n", encoding="utf-8")
    config = default_config(tmp_path)
    return ToolContext(config=config, sandbox=Sandbox(tmp_path, config.workspace.ignore))


def test_loop_uses_fallback_only_without_native_calls(tmp_path: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            stream_text('{"tool": "read_file", "arguments": {"path": "a.py"}}'),
            stream_text("Die Datei druckt a."),
        ]
    ).add_model("m")
    agent = create_agent(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        context=make_ctx(tmp_path),
        model="m",
    )
    result = agent.run("was macht a.py?")
    assert result.ok and result.steps == 2
    tool_message = [b for p, b in fake.requests if p == "/api/chat"][-1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "print('a')" in tool_message["content"]


def test_native_calls_win_over_text(tmp_path: Path) -> None:
    reply = stream_tool_call("list_dir", {})
    reply[0]["message"]["content"] = '{"tool": "read_file", "arguments": {"path": "a.py"}}'
    fake = FakeOllama(chat_replies=[reply, stream_text("ok")]).add_model("m")
    agent = create_agent(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        context=make_ctx(tmp_path),
        model="m",
    )
    agent.run("x")
    last = [b for p, b in fake.requests if p == "/api/chat"][-1]["messages"]
    assert [m.get("tool_name") for m in last if m["role"] == "tool"] == ["list_dir"]


def test_text_tool_mode(tmp_path: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            stream_text('```json\n{"tool": "read_file", "arguments": {"path": "a.py"}}\n```'),
            stream_text("fertig"),
        ]
    ).add_model("m", capabilities=("completion",))
    agent = create_agent(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        context=make_ctx(tmp_path),
        model="m",
        text_tools=True,
    )
    result = agent.run("x")
    assert result.ok
    chats = [b for p, b in fake.requests if p == "/api/chat"]
    assert "tools" not in chats[0]
    system = chats[0]["messages"][0]["content"]
    assert "NUR einen JSON-Block" in system
    assert "- read_file(path, start_line?, end_line?):" in system
    result_message = chats[1]["messages"][-1]
    assert result_message["role"] == "user"
    assert result_message["content"].startswith("Ergebnis von read_file:")
