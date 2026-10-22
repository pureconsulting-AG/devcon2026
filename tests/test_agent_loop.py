from __future__ import annotations

from pathlib import Path

import pytest

from lcc.agent.loop import Agent, AgentEvents
from lcc.agent.prompts import SkillListing, build_system_prompt, load_agent_md
from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import ToolContext, ToolResult, available_tool_names, default_registry
from lcc.config import default_config
from lcc.ollama_client import OllamaClient, ToolCall
from tests.fake_ollama import FakeOllama, stream_text, stream_tool_call


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "a.py").write_text("print('hi')\n", encoding="utf-8")
    return root


def make_agent(
    workspace: Path, fake: FakeOllama, max_steps: int = 5, events: AgentEvents | None = None
) -> Agent:
    fake.add_model("m")
    config = default_config(workspace)
    registry = default_registry()
    context = ToolContext(config=config, sandbox=Sandbox(workspace, config.workspace.ignore))
    return Agent(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        registry=registry,
        context=context,
        model="m",
        system_prompt="SYS",
        tool_names=available_tool_names(registry, context),
        max_steps=max_steps,
        events=events or AgentEvents(),
    )


def test_tool_call_then_answer(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            stream_tool_call("read_file", {"path": "a.py"}),
            stream_text("Die Datei gibt hi aus."),
        ]
    )
    seen: list[tuple[str, bool]] = []
    events = AgentEvents(on_tool_result=lambda c, r: seen.append((c.name, r.ok)))
    result = make_agent(workspace, fake, events=events).run("Was macht a.py?")

    assert result.ok
    assert result.steps == 2
    assert result.content == "Die Datei gibt hi aus."
    assert seen == [("read_file", True)]

    _, second_request = fake.requests[-1]
    messages = second_request["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "assistant", "tool"]
    assert messages[0]["content"] == "SYS"
    assert messages[3]["tool_name"] == "read_file"
    assert "print('hi')" in messages[3]["content"]
    assert [t["function"]["name"] for t in second_request["tools"]] == [
        "list_dir",
        "read_file",
        "search_code",
        "write_file",
        "edit_file",
        "run_shell",
    ]


def test_tool_error_goes_back_to_model(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[stream_tool_call("read_file", {"path": "../etc"}), stream_text("ok")]
    )
    result = make_agent(workspace, fake).run("x")
    assert result.ok
    tool_message = fake.requests[-1][1]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert "außerhalb" in tool_message["content"]


def test_max_steps_stops_with_notice(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            stream_tool_call("read_file", {"path": "a.py", "start_line": i}) for i in (1, 1)
        ]
        + [stream_tool_call("list_dir", {})]
    )
    notices: list[str] = []
    result = make_agent(
        workspace, fake, max_steps=2, events=AgentEvents(on_notice=notices.append)
    ).run("x")
    assert result.stop_reason == "max_steps"
    assert not result.ok
    assert len(fake.requests) == 2
    assert "(2)" in notices[0]


def test_same_call_three_times_aborts(workspace: Path) -> None:
    fake = FakeOllama(chat_replies=[stream_tool_call("list_dir", {"path": "."}) for _ in range(5)])
    executed: list[ToolCall] = []
    notices: list[str] = []
    events = AgentEvents(on_tool_call=executed.append, on_notice=notices.append)
    result = make_agent(workspace, fake, max_steps=10, events=events).run("x")
    assert result.stop_reason == "repeated_call"
    assert len(executed) == 2
    assert "list_dir" in notices[0]


def test_different_calls_do_not_trigger_repeat(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            stream_tool_call("list_dir", {"path": "."}),
            stream_tool_call("list_dir", {"path": "."}),
            stream_tool_call("read_file", {"path": "a.py"}),
            stream_tool_call("list_dir", {"path": "."}),
            stream_text("fertig"),
        ]
    )
    result = make_agent(workspace, fake, max_steps=10).run("x")
    assert result.ok


def test_thinking_not_in_history(workspace: Path) -> None:
    fake = FakeOllama(
        chat_replies=[
            [
                {"message": {"content": "", "thinking": "überlege"}, "done": False},
                *stream_tool_call("list_dir", {}),
            ],
            stream_text("ok"),
        ]
    )
    make_agent(workspace, fake).run("x")
    for message in fake.requests[-1][1]["messages"]:
        assert "thinking" not in message
        assert "überlege" not in str(message.get("content"))


def test_history_is_prepended(workspace: Path) -> None:
    fake = FakeOllama(chat_replies=[stream_text("ok")])
    history = [{"role": "user", "content": "alt"}, {"role": "assistant", "content": "alt2"}]
    make_agent(workspace, fake).run("neu", history=history)
    contents = [m["content"] for m in fake.requests[-1][1]["messages"]]
    assert contents == ["SYS", "alt", "alt2", "neu"]


def test_events_receive_results(workspace: Path) -> None:
    fake = FakeOllama(chat_replies=[stream_tool_call("nope", {}), stream_text("ok")])
    results: list[ToolResult] = []
    make_agent(
        workspace, fake, events=AgentEvents(on_tool_result=lambda c, r: results.append(r))
    ).run("x")
    assert not results[0].ok


# -- Systemprompt ------------------------------------------------------------


def test_system_prompt_de(workspace: Path) -> None:
    prompt = build_system_prompt(
        language="de",
        workspace_root=workspace,
        tool_names=["read_file", "rag_search"],
        rag_enabled=True,
        skills=[SkillListing("pytest-test", "Schreibt pytest-Tests.")],
        agent_md="Nutze immer Typhints.",
    )
    assert "Coding-Agent" in prompt
    assert str(workspace) in prompt
    assert "read_file, rag_search" in prompt
    assert "- pytest-test: Schreibt pytest-Tests." in prompt
    assert "rag_search" in prompt and "[n]" in prompt
    assert "Nutze immer Typhints." in prompt


def test_system_prompt_en_without_optional_parts(workspace: Path) -> None:
    prompt = build_system_prompt(language="en", workspace_root=workspace, tool_names=["read_file"])
    assert "coding agent" in prompt
    assert "Skills" not in prompt
    assert "[n]" not in prompt


def test_compact_prompt_is_shorter(workspace: Path) -> None:
    args = {"language": "de", "workspace_root": workspace, "tool_names": ["read_file"]}
    normal = build_system_prompt(**args)  # type: ignore[arg-type]
    compact = build_system_prompt(**args, compact=True, example_call='{"tool": "read_file"}')  # type: ignore[arg-type]
    assert len(compact) < len(normal) + 40
    assert '{"tool": "read_file"}' in compact


def test_load_agent_md(workspace: Path) -> None:
    assert load_agent_md(workspace) is None
    (workspace / ".lcc").mkdir()
    (workspace / ".lcc" / "AGENT.md").write_text("Regel 1\n", encoding="utf-8")
    assert load_agent_md(workspace) == "Regel 1"


def test_request_start_event_per_step(workspace: Path) -> None:
    fake = FakeOllama(chat_replies=[stream_tool_call("list_dir", {}), stream_text("ok")])
    starts: list[int] = []
    events = AgentEvents(on_request_start=lambda: starts.append(1))
    make_agent(workspace, fake, events=events).run("x")
    assert len(starts) == 2
