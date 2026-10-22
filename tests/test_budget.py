from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from lcc.agent.context import estimate_tokens, fit_to_budget
from lcc.agent.loop import AgentEvents, create_agent
from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import ToolContext
from lcc.config import default_config
from lcc.ollama_client import OllamaClient
from tests.fake_ollama import FakeOllama, stream_text, stream_tool_call


def tool(name: str, size: int) -> dict[str, Any]:
    return {"role": "tool", "tool_name": name, "content": "x" * size}


def test_estimate_tokens() -> None:
    assert estimate_tokens([{"role": "user", "content": "a" * 350}]) == 100
    calls = [{"function": {"name": "read_file", "arguments": {"path": "a" * 100}}}]
    assert estimate_tokens([{"role": "assistant", "content": "", "tool_calls": calls}]) > 28


def test_fit_to_budget_trims_oldest_tool_results_only() -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "s" * 700},
        {"role": "user", "content": "u" * 700},
        tool("a", 3500),
        {"role": "assistant", "content": "zwischen" * 50},
        tool("b", 3500),
        tool("c", 3500),
        tool("d", 3500),
    ]
    # ~4500 Tokens bei num_ctx 4000 → Grenze 3200
    shortened = fit_to_budget(messages, 4000)
    assert shortened == 2
    assert [m["content"] for m in messages if m["role"] == "tool"][:2] == ["[gekürzt]"] * 2
    assert messages[5]["content"] == "x" * 3500  # die letzten zwei bleiben
    assert messages[6]["content"] == "x" * 3500
    assert messages[0]["content"] == "s" * 700
    assert messages[1]["content"] == "u" * 700
    assert messages[3]["content"] == "zwischen" * 50
    assert estimate_tokens(messages) <= 3200


def test_fit_to_budget_stops_as_soon_as_possible() -> None:
    messages: list[dict[str, Any]] = [tool("a", 3500), tool("b", 350), tool("c", 10), tool("d", 10)]
    assert fit_to_budget(messages, 1200) == 1
    assert messages[1]["content"] == "x" * 350


def test_fit_to_budget_noop() -> None:
    messages: list[dict[str, Any]] = [tool("a", 35_000), tool("b", 10), tool("c", 10)]
    assert fit_to_budget(messages, None) == 0
    assert fit_to_budget([tool("a", 10)], 4000) == 0
    small: list[dict[str, Any]] = [tool("a", 35_000), tool("b", 10)]
    assert fit_to_budget(small, 100) == 0  # nur die letzten zwei – nichts zu kürzen


def test_agent_sends_trimmed_history(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("zeile\n" * 3000, encoding="utf-8")
    config = default_config(tmp_path)
    config = dataclasses.replace(
        config, models=dataclasses.replace(config.models, options={"num_ctx": 6000})
    )
    ctx = ToolContext(config=config, sandbox=Sandbox(tmp_path, config.workspace.ignore))
    fake = FakeOllama(
        chat_replies=[
            stream_tool_call("read_file", {"path": "big.txt", "start_line": 1}),
            stream_tool_call("read_file", {"path": "big.txt", "start_line": 2}),
            stream_tool_call("read_file", {"path": "big.txt", "start_line": 3}),
            stream_text("fertig"),
        ]
    ).add_model("m")
    infos: list[str] = []
    agent = create_agent(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        context=ctx,
        model="m",
        events=AgentEvents(on_info=infos.append),
    )
    agent.run("lies big.txt")
    last = [b for p, b in fake.requests if p == "/api/chat"][-1]["messages"]
    tool_contents = [m["content"] for m in last if m["role"] == "tool"]
    assert tool_contents[0] == "[gekürzt]"
    assert tool_contents[-1].startswith("big.txt (Zeilen 3-")
    assert any("gekürzt" in i for i in infos)
