"""Simulierter Ollama-Server für Tests (httpx.MockTransport)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx


def ndjson(*objects: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(obj).encode() + b"\n" for obj in objects)


def stream_text(*parts: str, thinking: str = "") -> list[dict[str, Any]]:
    """Chat-Antwort als Liste von Stream-Objekten."""
    objects: list[dict[str, Any]] = []
    if thinking:
        objects.append({"message": {"role": "assistant", "content": "", "thinking": thinking}})
    objects += [
        {"message": {"role": "assistant", "content": part}, "done": False} for part in parts
    ]
    objects.append({"message": {"role": "assistant", "content": ""}, "done": True})
    return objects


def stream_tool_call(name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
            },
            "done": False,
        },
        {"message": {"role": "assistant", "content": ""}, "done": True},
    ]


@dataclass
class FakeOllama:
    """Konfigurierbarer Fake; zeichnet alle Anfragen auf."""

    models: dict[str, dict[str, Any]] = field(default_factory=dict)
    chat_replies: list[list[dict[str, Any]]] = field(default_factory=list)
    embedding_dim: int = 4
    embed_fn: Callable[[str], list[float]] | None = None
    unreachable: bool = False
    requests: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def add_model(
        self,
        name: str,
        parameter_size: str = "9.7B",
        capabilities: tuple[str, ...] = ("completion", "tools"),
    ) -> FakeOllama:
        self.models[name] = {"parameter_size": parameter_size, "capabilities": list(capabilities)}
        return self

    def _known(self, name: str) -> bool:
        full = name if ":" in name else f"{name}:latest"
        return name in self.models or full in self.models

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.unreachable:
            raise httpx.ConnectError("Connection refused", request=request)
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        self.requests.append((request.url.path, body))
        path = request.url.path
        if path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": name,
                            "size": 5 * 1024**3,
                            "digest": f"sha-{name}",
                            "details": {
                                "parameter_size": info["parameter_size"],
                                "quantization_level": "Q4_K_M",
                            },
                        }
                        for name, info in self.models.items()
                    ]
                },
            )
        model = str(body.get("model", ""))
        if not self._known(model):
            return httpx.Response(404, json={"error": f"model '{model}' not found"})
        if path == "/api/show":
            info = self.models.get(model) or self.models[f"{model}:latest"]
            return httpx.Response(
                200,
                json={
                    "details": {"parameter_size": info["parameter_size"]},
                    "capabilities": info["capabilities"],
                },
            )
        if path == "/api/embed":
            embed = self.embed_fn or (lambda text: [0.5] * self.embedding_dim)
            vectors = [embed(text) for text in body["input"]]
            return httpx.Response(200, json={"embeddings": vectors})
        if path == "/api/chat":
            reply = self.chat_replies.pop(0) if self.chat_replies else stream_text("ok")
            return httpx.Response(200, content=ndjson(*reply))
        return httpx.Response(404, json={"error": "unknown endpoint"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]


VOCABULARY = ("config", "toml", "ollama", "server", "rag", "index", "katze", "hund", "test")


def keyword_embedding(text: str) -> list[float]:
    """Deterministisches Bag-of-Words-Embedding über ein kleines Vokabular (+ Bias)."""
    words = re.findall(r"\w+", text.lower())
    return [float(words.count(word)) for word in VOCABULARY] + [0.1]
