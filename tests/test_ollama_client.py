from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from lcc.ollama_client import (
    ChatChunk,
    ModelNotFoundError,
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
    OllamaResponseError,
    ToolCall,
    model_available,
    normalize_model_name,
)

Handler = Callable[[httpx.Request], httpx.Response]


def ndjson(*objects: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(obj).encode() + b"\n" for obj in objects)


def make_client(handler: Handler, **kwargs: Any) -> OllamaClient:
    return OllamaClient("http://ollama:11434", transport=httpx.MockTransport(handler), **kwargs)


def chat_handler(*objects: dict[str, Any], seen: list[dict[str, Any]] | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, content=ndjson(*objects))

    return handler


def test_chat_stream_yields_content_in_order() -> None:
    client = make_client(
        chat_handler(
            {"message": {"role": "assistant", "content": "Hal"}, "done": False},
            {"message": {"role": "assistant", "content": "lo"}, "done": False},
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "done_reason": "stop",
                "eval_count": 7,
            },
        )
    )
    chunks = list(client.chat_stream("m", [{"role": "user", "content": "hi"}]))
    assert [c.content for c in chunks] == ["Hal", "lo", ""]
    assert chunks[-1].done
    assert chunks[-1].eval_count == 7


def test_chat_collects_tool_calls_and_calls_on_chunk() -> None:
    seen_chunks: list[ChatChunk] = []
    client = make_client(
        chat_handler(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "read_file", "arguments": {"path": "a.py"}}},
                        {"function": {"name": "list_dir", "arguments": '{"path": "."}'}},
                    ],
                },
                "done": False,
            },
            {"message": {"role": "assistant", "content": ""}, "done": True},
        )
    )
    result = client.chat("m", [], on_chunk=seen_chunks.append)
    assert result.tool_calls == [
        ToolCall("read_file", {"path": "a.py"}),
        ToolCall("list_dir", {"path": "."}),
    ]
    assert len(seen_chunks) == 2
    assert result.as_message() == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "a.py"}}},
            {"function": {"name": "list_dir", "arguments": {"path": "."}}},
        ],
    }


def test_thinking_kept_separate_and_not_in_history() -> None:
    client = make_client(
        chat_handler(
            {"message": {"role": "assistant", "content": "", "thinking": "hmm"}, "done": False},
            {"message": {"role": "assistant", "content": "42"}, "done": True},
        )
    )
    result = client.chat("m", [])
    assert result.thinking == "hmm"
    assert result.content == "42"
    assert "thinking" not in result.as_message()


def test_payload_only_contains_set_fields() -> None:
    seen: list[dict[str, Any]] = []
    done = {"message": {"role": "assistant", "content": ""}, "done": True}
    client = make_client(chat_handler(done, seen=seen), keep_alive="10m")
    client.chat("m", [{"role": "user", "content": "x"}])
    tools = [{"type": "function", "function": {"name": "t", "parameters": {}}}]
    client.chat(
        "m", [], tools=tools, options={"num_ctx": 1}, think=False, format={"type": "object"}
    )
    assert seen[0] == {
        "model": "m",
        "messages": [{"role": "user", "content": "x"}],
        "stream": True,
        "keep_alive": "10m",
    }
    assert seen[1]["tools"] == tools
    assert seen[1]["options"] == {"num_ctx": 1}
    assert seen[1]["think"] is False
    assert seen[1]["format"] == {"type": "object"}


def test_chat_404_is_model_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'x' not found"})

    client = make_client(handler)
    with pytest.raises(ModelNotFoundError) as info:
        list(client.chat_stream("x", []))
    assert info.value.exit_code == 4
    assert "ollama pull x" in str(info.value)


def test_other_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "kaputt"})

    with pytest.raises(OllamaResponseError, match="kaputt"):
        make_client(handler).chat("m", [])


def test_error_line_in_stream() -> None:
    client = make_client(
        chat_handler(
            {"message": {"role": "assistant", "content": "a"}, "done": False},
            {"error": "out of memory"},
        )
    )
    with pytest.raises(OllamaResponseError, match="out of memory"):
        client.chat("m", [])


def test_connect_error_retried_once_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, content=ndjson({"message": {"content": "ok"}, "done": True}))

    result = make_client(handler).chat("m", [])
    assert result.content == "ok"
    assert calls == 2


def test_connect_error_twice_is_exit_3_with_url() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(OllamaConnectionError) as info:
        make_client(handler).chat("m", [])
    assert calls == 2
    assert info.value.exit_code == 3
    assert "http://ollama:11434" in str(info.value)


def test_read_timeout_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(OllamaError, match="timeout_seconds") as info:
        make_client(handler).chat("m", [])
    assert calls == 1
    assert not isinstance(info.value, OllamaConnectionError)


class BrokenStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        yield ndjson({"message": {"content": "erstes"}, "done": False})
        raise httpx.ReadError("connection reset")


def test_no_retry_after_first_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, stream=BrokenStream())

    received: list[str] = []
    with pytest.raises(OllamaConnectionError):
        for chunk in make_client(handler).chat_stream("m", []):
            received.append(chunk.content)
    assert received == ["erstes"]
    assert calls == 1


def test_embed() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2], [0.3, 0.4]]})

    vectors = make_client(handler).embed("e", ["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    assert seen[0]["input"] == ["a", "b"]


def test_embed_wrong_count_is_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1]]})

    with pytest.raises(OllamaResponseError):
        make_client(handler).embed("e", ["a", "b"])


def test_embed_404_model_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ModelNotFoundError) as info:
        make_client(handler).embed("nomic", ["a"])
    assert info.value.model == "nomic"


def test_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "qwen3.5:9b",
                        "size": 6_000_000_000,
                        "digest": "abc",
                        "details": {
                            "parameter_size": "9.7B",
                            "family": "qwen35",
                            "quantization_level": "Q4_K_M",
                        },
                    }
                ]
            },
        )

    [model] = make_client(handler).list_models()
    assert model.name == "qwen3.5:9b"
    assert model.parameter_size == "9.7B"
    assert model.quantization == "Q4_K_M"


def test_show_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"model": "m"}
        return httpx.Response(200, json={"capabilities": ["completion", "tools"]})

    assert make_client(handler).show_model("m")["capabilities"] == ["completion", "tools"]


def test_list_models_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(OllamaConnectionError):
        make_client(handler).list_models()


def test_model_name_normalization() -> None:
    assert normalize_model_name("nomic-embed-text") == "nomic-embed-text:latest"
    assert normalize_model_name("qwen3.5:9b") == "qwen3.5:9b"
    assert normalize_model_name("hf.co/org/model") == "hf.co/org/model:latest"
    assert model_available("nomic-embed-text", ["nomic-embed-text:latest"])
    assert model_available("qwen3.5:9b", ["qwen3.5:9b"])
    assert not model_available("qwen3.5:27b", ["qwen3.5:9b"])


def test_think_param_and_capability_cache() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        caps = ["completion", "thinking"] if model == "thinker" else ["completion"]
        return httpx.Response(200, json={"capabilities": caps})

    client = make_client(handler)
    assert client.think_param("thinker", enabled=True) is True
    assert client.think_param("thinker", enabled=False) is False
    assert client.think_param("plain", enabled=False) is None
    assert client.think_param("thinker", enabled=False) is False
    assert calls == ["thinker", "plain"]
