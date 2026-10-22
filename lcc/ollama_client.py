"""HTTP-Client für Ollama: chat (stream), embed, list_models, show_model.

Der httpx-Transport ist injizierbar, damit alles ohne echten Server testbar ist.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

from lcc import texts
from lcc.config import OllamaConfig

Message = dict[str, Any]


class OllamaError(Exception):
    """Basisfehler; exit_code bestimmt den Exit-Code der CLI."""

    exit_code = 1


class OllamaConnectionError(OllamaError):
    exit_code = 3


class ModelNotFoundError(OllamaError):
    exit_code = 4

    def __init__(self, message: str, model: str) -> None:
        super().__init__(message)
        self.model = model


class OllamaResponseError(OllamaError):
    exit_code = 1


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]

    def to_message(self) -> dict[str, Any]:
        return {"function": {"name": self.name, "arguments": self.arguments}}


@dataclass(frozen=True)
class ChatChunk:
    content: str = ""
    thinking: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    done: bool = False
    done_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


@dataclass
class ChatResult:
    content: str = ""
    thinking: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done_reason: str | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None

    def as_message(self) -> Message:
        """Assistant-Nachricht für den Verlauf – Thinking wird nie übernommen."""
        message: Message = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            message["tool_calls"] = [call.to_message() for call in self.tool_calls]
        return message


@dataclass(frozen=True)
class ModelInfo:
    name: str
    size: int
    digest: str
    parameter_size: str
    family: str
    quantization: str


def normalize_model_name(name: str) -> str:
    """'nomic-embed-text' und 'nomic-embed-text:latest' sind dasselbe Modell."""
    last = name.rsplit("/", 1)[-1]
    return name if ":" in last else f"{name}:latest"


def model_available(name: str, available: Sequence[str]) -> bool:
    wanted = normalize_model_name(name)
    return any(normalize_model_name(item) == wanted for item in available)


def _parse_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    calls: list[ToolCall] = []
    if not isinstance(raw, list):
        return ()
    for item in raw:
        function = item.get("function", {}) if isinstance(item, dict) else {}
        name = function.get("name")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}
        if isinstance(name, str) and isinstance(arguments, dict):
            calls.append(ToolCall(name=name, arguments=arguments))
    return tuple(calls)


def _parse_chunk(data: Mapping[str, Any]) -> ChatChunk:
    message = data.get("message") or {}
    return ChatChunk(
        content=message.get("content") or "",
        thinking=message.get("thinking") or "",
        tool_calls=_parse_tool_calls(message.get("tool_calls")),
        done=bool(data.get("done")),
        done_reason=data.get("done_reason"),
        prompt_eval_count=data.get("prompt_eval_count"),
        eval_count=data.get("eval_count"),
    )


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 300,
        connect_timeout_seconds: float = 5,
        keep_alive: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.keep_alive = keep_alive
        self._capabilities: dict[str, list[str]] = {}
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds, connect=connect_timeout_seconds),
            transport=transport,
        )

    @classmethod
    def from_config(
        cls, config: OllamaConfig, transport: httpx.BaseTransport | None = None
    ) -> OllamaClient:
        return cls(
            config.base_url,
            timeout_seconds=config.timeout_seconds,
            connect_timeout_seconds=config.connect_timeout_seconds,
            keep_alive=config.keep_alive,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- Fehlerbehandlung -------------------------------------------------

    def _connection_error(self, exc: Exception) -> OllamaConnectionError:
        return OllamaConnectionError(
            texts.OLLAMA_UNREACHABLE.format(url=self.base_url, error=str(exc) or type(exc).__name__)
        )

    def _check_status(self, response: httpx.Response, model: str | None) -> None:
        if response.status_code < 400:
            return
        response.read()
        try:
            detail = str(response.json().get("error", response.text))
        except (json.JSONDecodeError, AttributeError):
            detail = response.text
        if response.status_code == 404 and model is not None:
            raise ModelNotFoundError(
                texts.OLLAMA_MODEL_MISSING.format(model=model, url=self.base_url), model
            )
        raise OllamaResponseError(
            texts.OLLAMA_HTTP_ERROR.format(status=response.status_code, error=detail.strip())
        )

    def _request(
        self, method: str, path: str, *, json_body: Any = None, model: str | None = None
    ) -> Any:
        """Nicht-streamende Anfrage mit einem Retry bei Verbindungsfehlern."""
        for attempt in range(2):
            try:
                response = self._http.request(method, path, json=json_body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 0:
                    continue
                raise self._connection_error(exc) from exc
            except httpx.TimeoutException as exc:
                raise OllamaError(texts.OLLAMA_TIMEOUT.format(url=self.base_url)) from exc
            except httpx.TransportError as exc:
                raise self._connection_error(exc) from exc
            self._check_status(response, model)
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise OllamaResponseError(texts.OLLAMA_BAD_RESPONSE.format(path=path)) from exc
        raise AssertionError("unreachable")  # pragma: no cover

    # -- Endpunkte --------------------------------------------------------

    def chat_stream(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        options: Mapping[str, Any] | None = None,
        think: bool | None = None,
        format: Mapping[str, Any] | str | None = None,
    ) -> Iterator[ChatChunk]:
        """POST /api/chat mit stream=true; liefert Chunks, sobald sie ankommen.

        Retry nur bei Verbindungsfehlern vor dem ersten Chunk, nie während der Generierung.
        """
        payload: dict[str, Any] = {"model": model, "messages": list(messages), "stream": True}
        if tools:
            payload["tools"] = list(tools)
        if options:
            payload["options"] = dict(options)
        if think is not None:
            payload["think"] = think
        if format is not None:
            payload["format"] = format
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive

        started = False
        for attempt in range(2):
            try:
                with self._http.stream("POST", "/api/chat", json=payload) as response:
                    self._check_status(response, model)
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError as exc:
                            raise OllamaResponseError(
                                texts.OLLAMA_BAD_RESPONSE.format(path="/api/chat")
                            ) from exc
                        if "error" in data:
                            raise OllamaResponseError(
                                texts.OLLAMA_STREAM_ERROR.format(error=data["error"])
                            )
                        started = True
                        yield _parse_chunk(data)
                return
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                if attempt == 0 and not started:
                    continue
                raise self._connection_error(exc) from exc
            except httpx.TimeoutException as exc:
                raise OllamaError(texts.OLLAMA_TIMEOUT.format(url=self.base_url)) from exc
            except httpx.TransportError as exc:
                if attempt == 0 and not started:
                    continue
                raise self._connection_error(exc) from exc

    def chat(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        options: Mapping[str, Any] | None = None,
        think: bool | None = None,
        format: Mapping[str, Any] | str | None = None,
        on_chunk: Callable[[ChatChunk], None] | None = None,
    ) -> ChatResult:
        """Streamt und sammelt das Ergebnis; on_chunk bekommt jeden Chunk sofort."""
        result = ChatResult()
        content: list[str] = []
        thinking: list[str] = []
        for chunk in self.chat_stream(
            model, messages, tools=tools, options=options, think=think, format=format
        ):
            if on_chunk is not None:
                on_chunk(chunk)
            content.append(chunk.content)
            thinking.append(chunk.thinking)
            result.tool_calls.extend(chunk.tool_calls)
            if chunk.done:
                result.done_reason = chunk.done_reason
                result.prompt_eval_count = chunk.prompt_eval_count
                result.eval_count = chunk.eval_count
        result.content = "".join(content)
        result.thinking = "".join(thinking)
        return result

    def embed(self, model: str, inputs: Sequence[str]) -> list[list[float]]:
        """POST /api/embed; ein Vektor je Eingabe."""
        payload: dict[str, Any] = {"model": model, "input": list(inputs)}
        if self.keep_alive:
            payload["keep_alive"] = self.keep_alive
        data = self._request("POST", "/api/embed", json_body=payload, model=model)
        embeddings = data.get("embeddings") if isinstance(data, dict) else None
        if not isinstance(embeddings, list) or len(embeddings) != len(inputs):
            raise OllamaResponseError(texts.OLLAMA_BAD_RESPONSE.format(path="/api/embed"))
        return [[float(value) for value in vector] for vector in embeddings]

    def list_models(self) -> list[ModelInfo]:
        """GET /api/tags."""
        data = self._request("GET", "/api/tags")
        models: list[ModelInfo] = []
        for item in data.get("models", []) if isinstance(data, dict) else []:
            details = item.get("details") or {}
            models.append(
                ModelInfo(
                    name=item.get("name") or item.get("model", ""),
                    size=int(item.get("size") or 0),
                    digest=item.get("digest", ""),
                    parameter_size=details.get("parameter_size", ""),
                    family=details.get("family", ""),
                    quantization=details.get("quantization_level", ""),
                )
            )
        return models

    def show_model(self, model: str) -> dict[str, Any]:
        """POST /api/show (Details, Fähigkeiten)."""
        data = self._request("POST", "/api/show", json_body={"model": model}, model=model)
        if not isinstance(data, dict):
            raise OllamaResponseError(texts.OLLAMA_BAD_RESPONSE.format(path="/api/show"))
        return data

    def capabilities(self, model: str) -> list[str]:
        """Fähigkeiten aus /api/show (pro Client gecacht)."""
        if model not in self._capabilities:
            raw = self.show_model(model).get("capabilities") or []
            self._capabilities[model] = [str(item) for item in raw]
        return self._capabilities[model]

    def think_param(self, model: str, enabled: bool) -> bool | None:
        """Wert für 'think': True wenn aktiviert; sonst False nur bei Thinking-Modellen.

        Ollama lässt Thinking-Modelle ohne 'think' standardmäßig denken – das kostet bei
        kleinen Modellen viel Zeit. Nicht-Thinking-Modelle bekommen den Parameter nicht.
        """
        if enabled:
            return True
        return False if "thinking" in self.capabilities(model) else None
