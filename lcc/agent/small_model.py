"""Kleinmodell-Modus: Plan → Schritte → Verify → Repair → Eskalation.

Schwächen kleiner Modelle (lange Kontexte, viele Tools, mehrstufige Planung) werden durch
Struktur in lcc ausgeglichen, nicht durch längere Prompts:
- strukturierter Plan (Ollama 'format' mit JSON-Schema),
- je Schritt frischer, fokussierter Kontext und nur die Tools der Phase,
- deterministische Schritt-Zusammenfassungen statt kompletter Historie,
- Verify-Befehle, Repair-Schritte mit dem Fehlertext, optional Eskalation, ehrlicher Abbruch.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from lcc import texts
from lcc.agent.context import AutoContext, build_auto_context
from lcc.agent.loop import Agent, AgentEvents, AgentResult, describe_tools
from lcc.agent.prompts import SkillListing, build_system_prompt, load_agent_md
from lcc.agent.tools import (
    ToolContext,
    ToolRegistry,
    ToolResult,
    available_tool_names,
    default_registry,
)
from lcc.agent.verify import (
    CheckOutcome,
    changed_files,
    detect_verify_commands,
    failure_text,
    run_checks,
)
from lcc.ollama_client import ChatChunk, Message, OllamaClient, ToolCall

PHASES = ("explore", "edit", "verify")
MAX_PLAN_STEPS = 8

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["steps"],
    "properties": {
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_PLAN_STEPS,
            "items": {
                "type": "object",
                "required": ["goal", "phase"],
                "properties": {
                    "goal": {"type": "string"},
                    "phase": {"enum": list(PHASES)},
                    "files": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}

PHASE_TOOLS: dict[str, tuple[str, ...]] = {
    "explore": ("read_file", "list_dir", "search_code", "rag_search", "load_skill"),
    "edit": ("read_file", "edit_file", "replace_lines", "write_file"),
    "verify": ("run_shell", "read_file"),
    # Ohne Plan (plan_first = false): ein Schritt mit allen Datei-Tools
    "free": (
        "read_file",
        "list_dir",
        "search_code",
        "edit_file",
        "replace_lines",
        "write_file",
        "run_shell",
        "rag_search",
        "load_skill",
    ),
}

NOTE_MAX_CHARS = 400
# Bremse für das Thinking beim Plan (was zuerst eintritt): ~1000 Tokens oder 60 s ohne Plan-Text;
# danach ohne Thinking neu anfragen
PLAN_THINKING_MAX_CHARS = 4000
PLAN_THINKING_MAX_SECONDS = 60.0
HISTORY_MAX_MESSAGES = 6
HISTORY_MAX_CHARS = 600


class PlanError(ValueError):
    pass


@dataclass(frozen=True)
class PlanStep:
    goal: str
    phase: str
    files: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plan:
    steps: tuple[PlanStep, ...]
    fallback: bool = False

    @property
    def is_simple(self) -> bool:
        """Genau ein explore-Schritt: kein Overhead (keine Anzeige, kein Verify)."""
        return len(self.steps) == 1 and self.steps[0].phase == "explore"

    def render(self) -> str:
        lines = []
        for number, step in enumerate(self.steps, 1):
            files = f" ({', '.join(step.files)})" if step.files else ""
            lines.append(f"{number}. [{step.phase}] {step.goal}{files}")
        return "\n".join(lines)


def validate_plan(data: Any) -> Plan:
    """Prüft die Plan-Antwort gegen das Schema (ohne JSON-Schema-Bibliothek)."""
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise PlanError(texts.PLAN_ERR_STEPS)
    raw_steps = data["steps"]
    if not 1 <= len(raw_steps) <= MAX_PLAN_STEPS:
        raise PlanError(texts.PLAN_ERR_COUNT.format(count=len(raw_steps), max=MAX_PLAN_STEPS))
    steps: list[PlanStep] = []
    for number, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, dict):
            raise PlanError(texts.PLAN_ERR_STEP.format(number=number))
        goal, phase, files = raw.get("goal"), raw.get("phase"), raw.get("files", [])
        if not isinstance(goal, str) or not goal.strip():
            raise PlanError(texts.PLAN_ERR_GOAL.format(number=number))
        if phase not in PHASES:
            raise PlanError(texts.PLAN_ERR_PHASE.format(number=number, phases=", ".join(PHASES)))
        if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
            raise PlanError(texts.PLAN_ERR_FILES.format(number=number))
        steps.append(PlanStep(goal.strip(), str(phase), tuple(files)))
    return Plan(tuple(steps))


def parse_plan(text: str) -> Plan:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(texts.PLAN_ERR_JSON.format(error=exc.msg)) from exc
    return validate_plan(data)


def fallback_plan(task: str) -> Plan:
    return Plan((PlanStep(task, "edit"),), fallback=True)


def phase_tools(
    phase: str, available: Sequence[str], limit: int, skill_tools: Sequence[str] = ()
) -> list[str]:
    """Tools der Phase, die im Kontext verfügbar sind (inkl. Skill-Schnittmenge), max. limit.

    Listet ein aktiver Skill run_shell ausdrücklich (z. B. für git diff), darf er es auch in
    der explore-Phase nutzen – sonst bliebe ihm dort oft nur read_file.
    """
    wanted = list(PHASE_TOOLS.get(phase, PHASE_TOOLS["free"]))
    if phase == "explore" and "run_shell" in skill_tools:
        wanted.append("run_shell")
    tools = [name for name in wanted if name in available]
    return tools if phase == "free" else tools[:limit]


# ---------------------------------------------------------------------------
# Schritt-Zusammenfassung (deterministisch, ohne LLM)
# ---------------------------------------------------------------------------


@dataclass
class StepSummary:
    number: int
    goal: str
    phase: str
    read_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    commands: list[tuple[str, int | None]] = field(default_factory=list)
    tool_errors: int = 0
    note: str = ""
    stop_reason: str = "done"

    def render(self) -> str:
        lines = [texts.SUMMARY_HEAD.format(number=self.number, phase=self.phase, goal=self.goal)]
        if self.read_files:
            lines.append(texts.SUMMARY_READ.format(files=", ".join(self.read_files)))
        if self.changed_files:
            lines.append(texts.SUMMARY_CHANGED.format(files=", ".join(self.changed_files)))
        for command, code in self.commands:
            shown = "?" if code is None else str(code)
            lines.append(texts.SUMMARY_COMMAND.format(command=command, code=shown))
        if self.tool_errors:
            lines.append(texts.SUMMARY_ERRORS.format(count=self.tool_errors))
        if self.stop_reason != "done":
            lines.append(texts.SUMMARY_STOPPED.format(reason=self.stop_reason))
        if self.note:
            lines.append(texts.SUMMARY_NOTE.format(note=self.note))
        return "\n".join(lines)


class _Recorder:
    """Merkt sich Tool-Aufrufe eines Schritts und leitet die Events weiter."""

    def __init__(self, ctx: ToolContext, events: AgentEvents) -> None:
        self.ctx = ctx
        self.events = events
        self.read_files: list[str] = []
        self.commands: list[tuple[str, int | None]] = []
        self.errors = 0

    def on_tool_result(self, call: ToolCall, result: ToolResult) -> None:
        if not result.ok:
            self.errors += 1
        elif call.name == "read_file":
            path = str(call.arguments.get("path", ""))
            if path and path not in self.read_files:
                self.read_files.append(path)
        if call.name == "run_shell":
            self.commands.append((str(call.arguments.get("command", "")), _exit_code(result)))
        if self.events.on_tool_result is not None:
            self.events.on_tool_result(call, result)

    def agent_events(self) -> AgentEvents:
        return AgentEvents(
            on_request_start=self.events.on_request_start,
            on_chunk=self.events.on_chunk,
            on_message_end=self.events.on_message_end,
            on_tool_call=self.events.on_tool_call,
            on_tool_result=self.on_tool_result,
            on_notice=self.events.on_notice,
            on_info=self.events.on_info,
        )


def _exit_code(result: ToolResult) -> int | None:
    first = result.content.splitlines()[0] if result.content else ""
    if result.ok and first.startswith("exit code: "):
        try:
            return int(first.removeprefix("exit code: "))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Ablauf
# ---------------------------------------------------------------------------


@dataclass
class SmallModelEvents:
    agent: AgentEvents = field(default_factory=AgentEvents)
    # Plan anzeigen/bestätigen: Rückgabe = (ggf. bearbeiteter) Plan oder None (abbrechen)
    on_plan: Callable[[Plan], Plan | None] | None = None
    on_step: Callable[[int, int, PlanStep], None] | None = None
    on_check: Callable[[CheckOutcome], None] | None = None
    on_check_start: Callable[[str], None] | None = None
    on_info: Callable[[str], None] | None = None


@dataclass
class SmallRunResult:
    ok: bool
    content: str
    plan: Plan | None = None
    summaries: list[StepSummary] = field(default_factory=list)
    checks: list[CheckOutcome] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    repairs: int = 0
    escalated: bool = False
    aborted: str | None = None
    messages: list[Message] = field(default_factory=list)


class SmallModelRunner:
    def __init__(
        self,
        *,
        client: OllamaClient,
        context: ToolContext,
        model: str,
        events: SmallModelEvents | None = None,
        skills: Sequence[SkillListing] = (),
        text_tools: bool = False,
        history: Sequence[Message] = (),
    ) -> None:
        self.client = client
        self.ctx = context
        self.config = context.config
        self.model = model
        self.events = events or SmallModelEvents()
        self.skills = list(skills)
        self.text_tools = text_tools
        self.history = list(history)
        self.registry: ToolRegistry = default_registry()
        self.steps_used = 0
        self.agent_md = load_agent_md(context.sandbox.root)
        self._last_messages: list[Message] = []
        self._changes_start = len(context.sandbox.session_changes)

    # -- Hilfen -------------------------------------------------------------

    def _info(self, text: str) -> None:
        if self.events.on_info is not None:
            self.events.on_info(text)

    def _options(self) -> dict[str, object]:
        options: dict[str, object] = dict(self.config.models.options)
        options["temperature"] = self.config.small_model.temperature
        return options

    def _plan_think(self) -> bool | None:
        model_can_think = "thinking" in self.client.capabilities(self.model)
        if self.config.small_model.think_on_plan and model_can_think:
            return True
        return self.client.think_param(self.model, False)

    def _skill_messages(self) -> list[Message]:
        if self.ctx.skills is None:
            return []
        return [
            {"role": "system", "content": self.ctx.skills.content(skill, self.ctx)}
            for skill in self.ctx.skills.loaded
        ]

    def _history_text(self) -> str:
        relevant = [
            m for m in self.history if m.get("role") in ("user", "assistant") and m.get("content")
        ][-HISTORY_MAX_MESSAGES:]
        return "\n".join(f"{m['role']}: {str(m['content'])[:HISTORY_MAX_CHARS]}" for m in relevant)

    # -- Plan ---------------------------------------------------------------

    def make_plan(self, task: str, auto: AutoContext) -> Plan:
        if not self.config.small_model.plan_first:
            return Plan((PlanStep(task, "free"),))
        messages: list[Message] = [
            {"role": "system", "content": texts.PLAN_SYSTEM},
            *self._skill_messages(),
            *auto.messages(),
        ]
        history = self._history_text()
        if history:
            messages.append({"role": "system", "content": texts.SMALL_HISTORY.format(text=history)})
        messages.append({"role": "user", "content": task})
        think = self._plan_think()
        for attempt in range(2):
            content = self._plan_request(messages, think)
            if content is None:
                # Thinking ufert aus (kommt bei qwen3.5 mit JSON-Schema vor) – ohne Thinking neu
                self._info(texts.PLAN_THINKING_TOO_LONG)
                think = self.client.think_param(self.model, False)
                content = self._plan_request(messages, think) or ""
            try:
                return parse_plan(content)
            except PlanError as exc:
                if attempt == 1:
                    break
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content": texts.PLAN_RETRY.format(error=exc)})
        self._info(texts.PLAN_FALLBACK)
        return fallback_plan(task)

    def _plan_request(self, messages: Sequence[Message], think: bool | None) -> str | None:
        """Streamt die Plan-Antwort; None, wenn das Thinking die Bremse überschreitet.

        Ohne diese Bremse kann ein Thinking-Modell minutenlang denken, ohne je zu antworten –
        Thinking-Tokens halten die Verbindung offen, ein Timeout greift nicht.
        """
        events = self.events.agent
        if events.on_request_start is not None:
            events.on_request_start()
        content: list[str] = []
        thinking = 0
        started = time.monotonic()
        stream = self.client.chat_stream(
            self.model, messages, format=PLAN_SCHEMA, options=self._options(), think=think
        )
        try:
            for chunk in stream:
                if events.on_chunk is not None and chunk.thinking:
                    events.on_chunk(ChatChunk(thinking=chunk.thinking))
                thinking += len(chunk.thinking)
                content.append(chunk.content)
                runaway = (
                    thinking > PLAN_THINKING_MAX_CHARS
                    or time.monotonic() - started > PLAN_THINKING_MAX_SECONDS
                )
                if runaway and chunk.thinking and not "".join(content).strip():
                    return None
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                close()  # Verbindung schließen → Ollama bricht die Generierung ab
            if events.on_message_end is not None:
                events.on_message_end()
        return "".join(content)

    # -- Schritt ------------------------------------------------------------

    def run_step(
        self,
        step: PlanStep,
        number: int,
        task: str,
        plan: Plan,
        summaries: Sequence[StepSummary],
        model: str | None = None,
    ) -> StepSummary:
        cfg = self.config
        model = model or self.model
        available = available_tool_names(self.registry, self.ctx)
        skill_tools = [
            tool
            for skill in (self.ctx.skills.loaded if self.ctx.skills is not None else [])
            for tool in (skill.tools or ())
        ]
        tools = phase_tools(step.phase, available, cfg.small_model.max_tools_per_step, skill_tools)
        example = self.registry.get(tools[0]) if tools else None
        system_prompt = build_system_prompt(
            language=cfg.agent.prompt_language,
            workspace_root=self.ctx.sandbox.root,
            tool_names=tools,
            rag_enabled=self.ctx.rag is not None,
            skills=self.skills,
            agent_md=self.agent_md,
            compact=True,
            example_call=example.example_call() if example else None,
            tool_text=describe_tools(self.registry, tools) if self.text_tools else None,
        )
        auto = (
            build_auto_context(self.ctx, task, extra_files=step.files)
            if cfg.small_model.auto_context
            else AutoContext()
        )
        prompt = texts.SMALL_STEP.format(
            task=task,
            plan=plan.render(),
            done="\n\n".join(s.render() for s in summaries) or texts.SMALL_NOTHING_DONE,
            number=number,
            total=len(plan.steps),
            phase=step.phase,
            goal=step.goal,
            hint=texts.PHASE_HINTS.get(step.phase, "").format(
                allowlist=", ".join(cfg.agent.shell_allowlist)
            ),
        )
        history = self._history_text()
        preface: list[Message] = [*self._skill_messages(), *auto.messages()]
        if history:
            preface.insert(
                0, {"role": "system", "content": texts.SMALL_HISTORY.format(text=history)}
            )
        budget = max(
            0, min(cfg.small_model.max_steps_per_plan_step, cfg.agent.max_steps - self.steps_used)
        )
        summary = StepSummary(number, step.goal, step.phase)
        if budget == 0:
            summary.stop_reason = "max_steps"
            return summary
        recorder = _Recorder(self.ctx, self.events.agent)
        changes_before = len(self.ctx.sandbox.session_changes)
        agent = Agent(
            client=self.client,
            registry=self.registry,
            context=self.ctx,
            model=model,
            system_prompt=system_prompt,
            tool_names=tools,
            max_steps=budget,
            options=self._options(),
            think=self.client.think_param(model, False),
            events=recorder.agent_events(),
            text_tools=self.text_tools,
        )
        result: AgentResult = agent.run(prompt, preface=preface)
        self.steps_used += result.steps
        self._last_messages = result.messages
        summary.read_files = recorder.read_files
        summary.changed_files = changed_files(self.ctx.sandbox, changes_before)
        summary.commands = recorder.commands
        summary.tool_errors = recorder.errors
        summary.stop_reason = result.stop_reason
        summary.note = " ".join(result.content.split())[:NOTE_MAX_CHARS]
        return summary

    # -- Verify -------------------------------------------------------------

    def verify_commands(self, changed: Sequence[str]) -> list[str]:
        if self.ctx.skills is not None and self.ctx.skills.checks():
            return self.ctx.skills.checks()
        if self.config.small_model.verify_commands:
            return list(self.config.small_model.verify_commands)
        return detect_verify_commands(self.ctx.sandbox.root, changed)

    def verify(self, changed: Sequence[str]) -> list[CheckOutcome]:
        commands = self.verify_commands(changed)
        if not commands or not changed:
            return []
        return run_checks(
            self.ctx, commands, changed, self.events.on_check, self.events.on_check_start
        )

    # -- Gesamtablauf -------------------------------------------------------

    def run(self, task: str) -> SmallRunResult:
        changes_start = self._changes_start = len(self.ctx.sandbox.session_changes)
        auto = (
            build_auto_context(self.ctx, task)
            if self.config.small_model.auto_context
            else AutoContext()
        )
        plan = self.make_plan(task, auto)
        result = SmallRunResult(ok=False, content="", plan=plan)

        if not plan.is_simple and self.events.on_plan is not None:
            confirmed = self.events.on_plan(plan)
            if confirmed is None:
                result.aborted = texts.PLAN_CANCELLED
                result.content = texts.PLAN_CANCELLED
                return result
            plan = confirmed
            result.plan = plan

        for number, step in enumerate(plan.steps, 1):
            if self.steps_used >= self.config.agent.max_steps:
                result.aborted = texts.SMALL_BUDGET.format(max_steps=self.config.agent.max_steps)
                break
            if self.events.on_step is not None and not plan.is_simple:
                self.events.on_step(number, len(plan.steps), step)
            result.summaries.append(self.run_step(step, number, task, plan, result.summaries))

        result.content = result.summaries[-1].note if result.summaries else ""
        result.messages = self._last_messages
        if plan.is_simple:
            result.ok = result.summaries[-1].stop_reason == "done"
            result.content = self._final_answer()
            return result

        changed = changed_files(self.ctx.sandbox, changes_start)
        result.checks = self.verify(changed)
        error = failure_text(result.checks)
        previous_error: str | None = None
        while error is not None and result.repairs < self.config.small_model.max_repair_attempts:
            if error == previous_error:
                self._info(texts.REPAIR_SAME_ERROR)
                break
            previous_error = error
            result.repairs += 1
            self._info(texts.REPAIR_START.format(attempt=result.repairs))
            error = self._repair(task, plan, result, error)
            changed = changed_files(self.ctx.sandbox, changes_start)

        escalate_model = self.config.small_model.escalate_model
        if error is not None and escalate_model and escalate_model != self.model:
            self._info(texts.ESCALATED.format(model=escalate_model))
            result.escalated = True
            error = self._repair(task, plan, result, error, model=escalate_model)

        result.changed = changed_files(self.ctx.sandbox, changes_start)
        if error is not None:
            result.ok = False
            result.aborted = texts.SMALL_ABORT.format(
                done=", ".join(result.changed) or texts.SMALL_NONE,
                missing=texts.SMALL_MISSING_CHECKS,
                error=error,
            )
            result.content = result.aborted
            return result
        if result.aborted is not None:
            result.ok = False
            return result
        # Laufen Checks, entscheiden sie (alle grün, sonst wären wir oben abgebrochen);
        # ohne Checks müssen alle Schritte regulär geendet haben.
        result.ok = bool(result.checks) or all(s.stop_reason == "done" for s in result.summaries)
        result.content = self._final_answer()
        return result

    def _repair(
        self,
        task: str,
        plan: Plan,
        result: SmallRunResult,
        error: str,
        model: str | None = None,
    ) -> str | None:
        step = PlanStep(texts.REPAIR_GOAL.format(error=error), "edit")
        repair_plan = Plan((*plan.steps, step))
        number = len(repair_plan.steps)
        if self.events.on_step is not None:
            self.events.on_step(number, number, step)
        summary = self.run_step(step, number, task, repair_plan, result.summaries, model=model)
        result.summaries.append(summary)
        changes = changed_files(self.ctx.sandbox, self._changes_start)
        result.checks = self.verify(changes)
        return failure_text(result.checks)

    def _final_answer(self) -> str:
        """Letzte inhaltliche Antwort des Modells (bereits gestreamt)."""
        for message in reversed(self._last_messages):
            if message.get("role") == "assistant" and str(message.get("content", "")).strip():
                return str(message["content"])
        return ""


def summaries_text(summaries: Sequence[StepSummary]) -> str:
    return "\n\n".join(summary.render() for summary in summaries)


# ---------------------------------------------------------------------------
# Plan-Dialog: [Enter] ausführen / [e] bearbeiten / [n] abbrechen
# ---------------------------------------------------------------------------


def parse_plan_lines(lines: Sequence[str]) -> Plan:
    """Bearbeiteter Plan: je Zeile 'phase: Ziel'."""
    steps: list[PlanStep] = []
    for line in lines:
        phase, sep, goal = line.partition(":")
        phase = phase.strip().lower()
        if not sep or phase not in PHASES or not goal.strip():
            raise PlanError(texts.PLAN_EDIT_INVALID.format(line=line))
        steps.append(PlanStep(goal.strip(), phase))
    return validate_plan({"steps": [{"goal": s.goal, "phase": s.phase} for s in steps]})


def confirm_plan(plan: Plan, ask: Callable[[str], str], say: Callable[[str], None]) -> Plan | None:
    """Fragt nach dem Plan; liefert den (ggf. bearbeiteten) Plan oder None (abbrechen)."""
    while True:
        answer = ask(texts.PLAN_PROMPT).strip().lower()
        if answer in ("", "j", "ja", "y", "yes"):
            return plan
        if answer in ("n", "nein", "no"):
            return None
        if answer in ("e", "edit", "bearbeiten"):
            say(texts.PLAN_EDIT_HELP)
            lines: list[str] = []
            while line := ask("> ").strip():
                lines.append(line)
            try:
                plan = parse_plan_lines(lines)
            except PlanError as exc:
                say(str(exc))
                continue
            say(texts.PLAN_HEADER + "\n" + plan.render())
