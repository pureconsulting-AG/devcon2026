"""Agent-Schleife: Chat mit Tools → Tool-Calls ausführen → Ergebnisse zurück → bis fertig."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from lcc import texts
from lcc.agent.context import fit_to_budget
from lcc.agent.prompts import SkillListing, build_system_prompt, load_agent_md
from lcc.agent.toolcall_parser import parse_tool_calls
from lcc.agent.tools import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    available_tool_names,
    default_registry,
)
from lcc.ollama_client import ChatChunk, Message, OllamaClient, ToolCall

StopReason = Literal["done", "max_steps", "repeated_call"]

REPEAT_LIMIT = 3


@dataclass
class AgentEvents:
    """Callbacks für die Anzeige; alle optional."""

    on_request_start: Callable[[], None] | None = None
    on_chunk: Callable[[ChatChunk], None] | None = None
    on_message_end: Callable[[], None] | None = None
    on_tool_call: Callable[[ToolCall], None] | None = None
    on_tool_result: Callable[[ToolCall, ToolResult], None] | None = None
    on_notice: Callable[[str], None] | None = None
    on_info: Callable[[str], None] | None = None


@dataclass
class AgentResult:
    content: str
    stop_reason: StopReason
    steps: int
    messages: list[Message] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.stop_reason == "done"


def _num_ctx(options: dict[str, object]) -> int | None:
    value = options.get("num_ctx")
    return value if isinstance(value, int) else None


def _call_key(call: ToolCall) -> str:
    return call.name + json.dumps(call.arguments, sort_keys=True, ensure_ascii=False)


@dataclass
class Agent:
    client: OllamaClient
    registry: ToolRegistry
    context: ToolContext
    model: str
    system_prompt: str
    tool_names: Sequence[str]
    max_steps: int = 25
    options: dict[str, object] = field(default_factory=dict)
    think: bool | None = None
    events: AgentEvents = field(default_factory=AgentEvents)
    # Text-Tool-Modus: Modell ohne 'tools'-Fähigkeit – Tools stehen im Prompt, Aufrufe kommen
    # als JSON im Text, Ergebnisse gehen als normale Nachricht zurück.
    text_tools: bool = False

    def _notice(self, text: str) -> None:
        if self.events.on_notice is not None:
            self.events.on_notice(text)

    def _step_tools(self) -> list[str]:
        """Tools für den nächsten Schritt – ein mittendrin geladener Skill schränkt sofort ein."""
        if self.context.skills is None:
            return list(self.tool_names)
        return self.context.skills.allowed_tools(self.tool_names)

    def _step_model(self) -> tuple[str, bool | None]:
        skill_model = self.context.skills.model() if self.context.skills is not None else None
        if not skill_model or skill_model == self.model:
            return self.model, self.think
        enabled = self.context.config.models.thinking.enabled
        return skill_model, self.client.think_param(skill_model, enabled)

    def _tool_message(self, call: ToolCall, result: ToolResult) -> Message:
        if self.text_tools:
            content = texts.TOOL_RESULT_AS_TEXT.format(name=call.name, content=result.content)
            # tool_name bleibt dran, damit das Kontextbudget das Ergebnis erkennt
            return {"role": "user", "content": content, "tool_name": call.name}
        return {"role": "tool", "content": result.content, "tool_name": call.name}

    def run(
        self, task: str, history: Sequence[Message] = (), preface: Sequence[Message] = ()
    ) -> AgentResult:
        """preface: zusätzliche Systemnachrichten direkt vor dem Auftrag (z. B. Skill-Body)."""
        messages: list[Message] = [{"role": "system", "content": self.system_prompt}]
        messages += list(history)
        messages += list(preface)
        messages.append({"role": "user", "content": task})

        last_key: str | None = None
        repeat_count = 0
        last_content = ""
        for step in range(1, self.max_steps + 1):
            if self.events.on_request_start is not None:
                self.events.on_request_start()
            step_tools = self._step_tools()
            model, think = self._step_model()
            shortened = fit_to_budget(messages, _num_ctx(self.options))
            if shortened and self.events.on_info is not None:
                self.events.on_info(texts.CONTEXT_SHORTENED.format(count=shortened))
            result = self.client.chat(
                model,
                messages,
                tools=None if self.text_tools else self.registry.schemas(step_tools),
                options=self.options,
                think=think,
                on_chunk=self.events.on_chunk,
            )
            if self.events.on_message_end is not None:
                self.events.on_message_end()
            messages.append(result.as_message())
            if result.content.strip():
                last_content = result.content
            # Fallback (6.1): nur wenn keine nativen tool_calls kamen.
            calls = result.tool_calls or parse_tool_calls(result.content, known=step_tools)
            if not calls:
                return AgentResult(result.content, "done", step, messages)

            for call in calls:
                key = _call_key(call)
                repeat_count = repeat_count + 1 if key == last_key else 1
                last_key = key
                if repeat_count >= REPEAT_LIMIT:
                    self._notice(texts.AGENT_REPEATED_CALL.format(name=call.name))
                    return AgentResult(last_content, "repeated_call", step, messages)
                if self.events.on_tool_call is not None:
                    self.events.on_tool_call(call)
                loaded_before = (
                    len(self.context.skills.loaded) if self.context.skills is not None else 0
                )
                tool_result = self.registry.execute(call, self.context, allowed=step_tools)
                if (
                    self.context.skills is not None
                    and len(self.context.skills.loaded) > loaded_before
                    and self.events.on_info is not None
                ):
                    name = self.context.skills.loaded[-1].name
                    self.events.on_info(texts.SKILL_LOADED.format(name=name))
                if self.events.on_tool_result is not None:
                    self.events.on_tool_result(call, tool_result)
                messages.append(self._tool_message(call, tool_result))

        self._notice(texts.AGENT_MAX_STEPS.format(max_steps=self.max_steps))
        return AgentResult(last_content, "max_steps", self.max_steps, messages)


def create_agent(
    *,
    client: OllamaClient,
    context: ToolContext,
    model: str,
    events: AgentEvents | None = None,
    skills: Sequence[SkillListing] = (),
    text_tools: bool = False,
) -> Agent:
    """Standard-Agent aus der Config: Tools, Systemprompt inkl. Skill-Liste und AGENT.md."""
    cfg = context.config
    registry = default_registry()
    tool_names = available_tool_names(registry, context)
    system_prompt = build_system_prompt(
        language=cfg.agent.prompt_language,
        workspace_root=context.sandbox.root,
        tool_names=tool_names,
        rag_enabled=context.rag is not None,
        skills=skills,
        agent_md=load_agent_md(context.sandbox.root),
        tool_text=describe_tools(registry, tool_names) if text_tools else None,
    )
    return Agent(
        client=client,
        registry=registry,
        context=context,
        model=model,
        system_prompt=system_prompt,
        tool_names=tool_names,
        max_steps=cfg.agent.max_steps,
        options=dict(cfg.models.options),
        think=client.think_param(model, cfg.models.thinking.enabled),
        events=events or AgentEvents(),
        text_tools=text_tools,
    )


def describe_tools(registry: ToolRegistry, names: Sequence[str]) -> str:
    """Kompakte Tool-Liste für den Text-Tool-Modus: name(arg, optional?): Beschreibung."""
    lines: list[str] = []
    for name in names:
        spec = registry.get(name)
        if spec is None:
            continue
        required = set(spec.parameters.get("required", []))
        args = ", ".join(
            arg if arg in required else f"{arg}?" for arg in spec.parameters.get("properties", {})
        )
        lines.append(f"- {name}({args}): {spec.description}")
    return "\n".join(lines)
