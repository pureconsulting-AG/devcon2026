"""Fallback: Tool-Calls aus dem Antworttext lesen, wenn keine nativen tool_calls kamen.

Erkannt wird {"tool": "...", "arguments": {...}} – frei im Text oder in ```json-Fences.
Mit bekannter Tool-Liste wird zusätzlich {"name": "...", "arguments": {...}} akzeptiert
(so schreiben manche Modelle ihre Aufrufe); unbekannte Tools werden ignoriert.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from typing import Any

from lcc.ollama_client import ToolCall

_DECODER = json.JSONDecoder()


def _as_call(obj: Any, known: Collection[str] | None) -> ToolCall | None:
    if not isinstance(obj, dict):
        return None
    name = obj.get("tool")
    if name is None and known is not None:
        name = obj.get("name")
    arguments = obj.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return None
    if not isinstance(name, str) or not isinstance(arguments, dict):
        return None
    if set(obj) - {"tool", "name", "arguments"}:
        return None  # wahrscheinlich normales JSON in der Antwort, kein Aufruf
    if known is not None and name not in known:
        return None
    return ToolCall(name=name, arguments=arguments)


def parse_tool_calls(text: str, known: Collection[str] | None = None) -> list[ToolCall]:
    """Alle Tool-Aufrufe im Text, in Reihenfolge. Kaputtes JSON wird übersprungen."""
    calls: list[ToolCall] = []
    index = text.find("{")
    while index != -1:
        try:
            obj, end = _DECODER.raw_decode(text, index)
        except json.JSONDecodeError:
            index = text.find("{", index + 1)
            continue
        call = _as_call(obj, known)
        if call is not None:
            calls.append(call)
            index = text.find("{", end)
        else:
            index = text.find("{", index + 1)
    return calls
