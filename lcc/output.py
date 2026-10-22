"""Ausgabe: Streaming im Terminal (Markdown), Rohtext in Pipes, JSON-Zeilen mit --json."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, TextIO

from rich.console import Console, RenderableType
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from lcc import texts
from lcc.agent.loop import AgentEvents
from lcc.agent.sandbox import Confirmer
from lcc.agent.small_model import Plan, PlanStep, SmallModelEvents, confirm_plan
from lcc.agent.tools import ToolResult
from lcc.agent.verify import CheckOutcome
from lcc.ollama_client import ChatChunk, ChatResult, ToolCall

TOOL_ARG_PREVIEW_CHARS = 60


def emit_json(event: dict[str, Any], stream: TextIO | None = None) -> None:
    """Eine JSON-Zeile je Ereignis (token, tool_call, tool_result, final, error)."""
    out = stream or sys.stdout
    out.write(json.dumps(event, ensure_ascii=False) + "\n")
    out.flush()


class WaitingIndicator:
    """Spinner mit Laufzeit, solange das Modell noch nichts Sichtbares geliefert hat."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.started = time.monotonic()
        self._spinner = Spinner("dots", style="cyan")

    def __rich__(self) -> RenderableType:
        elapsed = time.monotonic() - self.started
        self._spinner.update(text=Text(f"{self.label} {elapsed:.0f}s", style="dim"))
        return self._spinner


class ChatRenderer:
    """Gibt gestreamte Chat-Chunks aus. Thinking nur mit show_thinking, nach stderr."""

    def __init__(
        self,
        *,
        json_mode: bool,
        markdown: bool,
        show_thinking: bool,
        show_tool_calls: bool = True,
        console: Console | None = None,
        err_console: Console | None = None,
    ) -> None:
        self.json_mode = json_mode
        self.show_thinking = show_thinking
        self.show_tool_calls = show_tool_calls
        self.console = console or Console()
        self.err_console = err_console or Console(stderr=True)
        self.markdown = markdown and self.console.is_terminal
        self._text: list[str] = []
        self._live: Live | None = None
        self._thinking_open = False
        self._waiting: WaitingIndicator | None = None
        self._waiting_live: Live | None = None

    # -- Warteanzeige --------------------------------------------------------

    def start_waiting(self, label: str | None = None) -> None:
        """Spinner, solange lcc arbeitet (nur im Terminal, nicht mit --json).

        Läuft er schon, werden nur Text und Laufzeit neu gesetzt.
        """
        if self.json_mode or not self.err_console.is_terminal:
            return
        label = label or texts.STATUS_WAITING
        if self._waiting is not None and self._waiting_live is not None:
            self._waiting.label = label
            self._waiting.started = time.monotonic()
            return
        self._waiting = WaitingIndicator(label)
        self._waiting_live = Live(
            self._waiting, console=self.err_console, refresh_per_second=10, transient=True
        )
        self._waiting_live.start()

    def stop_waiting(self) -> None:
        if self._waiting_live is not None:
            self._waiting_live.stop()
            self._waiting_live = None
            self._waiting = None

    def on_chunk(self, chunk: ChatChunk) -> None:
        if chunk.thinking:
            if self.show_thinking:
                self.stop_waiting()
                self._thinking(chunk.thinking)
            elif self._waiting is not None:
                self._waiting.label = texts.STATUS_THINKING
        if chunk.tool_calls:
            self.stop_waiting()
        if not chunk.content:
            return
        self.stop_waiting()
        if self.json_mode:
            emit_json({"type": "token", "content": chunk.content})
            return
        self._close_thinking()
        self._text.append(chunk.content)
        if self.markdown:
            if self._live is None:
                self._live = Live(
                    console=self.console,
                    refresh_per_second=8,
                    vertical_overflow="visible",
                )
                self._live.start()
            self._live.update(Markdown("".join(self._text)))
        else:
            self.console.file.write(chunk.content)
            self.console.file.flush()

    def _thinking(self, text: str) -> None:
        if self.json_mode:
            emit_json({"type": "thinking", "content": text})
            return
        self._thinking_open = True
        self.err_console.print(text, style="dim italic", end="", markup=False, highlight=False)

    def _close_thinking(self) -> None:
        if self._thinking_open:
            self.err_console.print()
            self._thinking_open = False

    def end_message(self) -> None:
        """Eine Assistant-Nachricht ist fertig (im Agent-Lauf folgen ggf. weitere)."""
        self._close_thinking()
        text = "".join(self._text)
        self._text = []
        if self._live is not None:
            self._live.update(Markdown(text))
            self._live.stop()
            self._live = None
        elif not self.json_mode and text and not text.endswith("\n"):
            self.console.file.write("\n")
            self.console.file.flush()

    def done(self) -> None:
        """Auftrag fertig: Antwort abschließen, Spinner weg (z. B. vor dem nächsten REPL-Prompt)."""
        self.end_message()
        self.stop_waiting()

    def finish(self, result: ChatResult, **extra: Any) -> None:
        self.done()
        if self.json_mode:
            emit_json({"type": "final", "content": result.content, **extra})

    def final(self, content: str, **extra: Any) -> None:
        """Abschluss eines Agent-Laufs (Text wurde bereits gestreamt)."""
        self.done()
        if self.json_mode:
            emit_json({"type": "final", "content": content, **extra})

    def tool_call(self, call: ToolCall) -> None:
        if self.json_mode:
            emit_json({"type": "tool_call", "name": call.name, "arguments": call.arguments})
            return
        if self.show_tool_calls:
            args = ", ".join(f"{key}={_preview(value)}" for key, value in call.arguments.items())
            self.err_console.print(
                f"→ {call.name}({args})", style="cyan", markup=False, highlight=False
            )
        self.start_waiting(texts.STATUS_TOOL.format(name=call.name))

    def tool_result(self, call: ToolCall, result: ToolResult) -> None:
        if self.json_mode:
            emit_json(
                {
                    "type": "tool_result",
                    "name": call.name,
                    "ok": result.ok,
                    "content": result.content,
                }
            )
            return
        if not result.ok:
            first_line = result.content.splitlines()[0] if result.content else ""
            self.err_console.print(f"  ✗ {first_line}", style="red", markup=False, highlight=False)
        elif self.show_tool_calls:
            lines = result.content.count("\n") + 1
            self.err_console.print(
                texts.TOOL_RESULT_LINES.format(lines=lines),
                style="dim",
                markup=False,
                highlight=False,
            )

    def notice(self, text: str) -> None:
        if self.json_mode:
            emit_json({"type": "notice", "message": text})
        else:
            self.end_message()
            self.err_console.print(text, style="yellow", markup=False, highlight=False)

    def info(self, text: str) -> None:
        """Neutrale Statuszeile, z. B. '⚙ Skill: pytest-test'."""
        if self.json_mode:
            emit_json({"type": "info", "message": text})
            return
        self.end_message()
        self.err_console.print(text, style="cyan", markup=False, highlight=False)

    def check_start(self, command: str) -> None:
        self.start_waiting(texts.STATUS_CHECK.format(command=command))

    def check_outcome(self, outcome: CheckOutcome) -> None:
        if self.json_mode:
            emit_json(
                {
                    "type": "check",
                    "command": outcome.command,
                    "ok": outcome.ok,
                    "skipped": outcome.skipped,
                    "output": outcome.output(),
                }
            )
            return
        if outcome.skipped:
            text = texts.SKILL_CHECK_SKIPPED.format(
                placeholder=outcome.skipped_placeholder, command=outcome.command
            )
            self.err_console.print(text, style="dim", markup=False, highlight=False)
        elif outcome.ok:
            text = texts.SKILL_CHECK_OK.format(command=outcome.command)
            self.err_console.print(text, style="green", markup=False, highlight=False)
        else:
            text = texts.SKILL_CHECK_FAILED.format(command=outcome.command)
            self.err_console.print(text, style="red", markup=False, highlight=False)
            tail = "\n".join(outcome.output().splitlines()[-20:])
            self.err_console.print(tail, style="dim", markup=False, highlight=False)

    def plan(self, plan: Plan) -> None:
        if self.json_mode:
            steps = [{"goal": s.goal, "phase": s.phase, "files": list(s.files)} for s in plan.steps]
            emit_json({"type": "plan", "steps": steps, "fallback": plan.fallback})
            return
        self.end_message()
        self.err_console.print(texts.PLAN_HEADER, style="bold", markup=False)
        self.err_console.print(plan.render(), markup=False, highlight=False)

    def step(self, number: int, total: int, step: PlanStep) -> None:
        if self.json_mode:
            emit_json(
                {
                    "type": "step",
                    "number": number,
                    "total": total,
                    "phase": step.phase,
                    "goal": step.goal,
                }
            )
            return
        self.end_message()
        goal = step.goal.splitlines()[0] if step.goal else ""
        text = texts.STEP_HEADER.format(number=number, total=total, phase=step.phase, goal=goal)
        self.err_console.print(text, style="bold cyan", markup=False, highlight=False)
        self.start_waiting(texts.STATUS_PREPARE)

    def agent_events(self) -> AgentEvents:
        """Callbacks für die Agent-Schleife."""
        return AgentEvents(
            on_request_start=self.start_waiting,
            on_chunk=self.on_chunk,
            on_message_end=self.end_message,
            on_tool_call=self.tool_call,
            on_tool_result=self.tool_result,
            on_notice=self.notice,
            on_info=self.info,
        )

    def abort(self) -> None:
        """Bei Fehler/Abbruch Live-Anzeige sauber beenden."""
        self.stop_waiting()
        self._close_thinking()
        if self._live is not None:
            self._live.stop()
            self._live = None


def _preview(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else repr(value)
    if len(text) > TOOL_ARG_PREVIEW_CHARS:
        text = text[: TOOL_ARG_PREVIEW_CHARS - 1] + "…"
    return text


def small_events(renderer: ChatRenderer, confirmer: Confirmer, *, ask: bool) -> SmallModelEvents:
    """Events für den Kleinmodell-Modus; ask=True zeigt den Plan-Dialog."""

    def on_plan(plan: Plan) -> Plan | None:
        renderer.plan(plan)
        if not ask:
            return plan

        def say(text: str) -> None:
            renderer.err_console.print(text, markup=False, highlight=False)

        return confirm_plan(plan, confirmer.ask_line, say)

    return SmallModelEvents(
        agent=renderer.agent_events(),
        on_plan=on_plan,
        on_step=renderer.step,
        on_check=renderer.check_outcome,
        on_check_start=renderer.check_start,
        on_info=renderer.info,
    )
