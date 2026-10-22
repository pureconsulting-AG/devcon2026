"""Verify-Befehle (Skill-checks) mit Platzhaltern ausführen.

Platzhalter: {changed} = geänderte Dateien dieses Laufs, {test_file} = zuletzt
geschriebene Datei unter tests/. Ausführung immer über die Sandbox (Allowlist/Bestätigung).
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lcc import texts
from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import CommandResult, ToolContext, ToolError, run_command

PLACEHOLDERS = ("{changed}", "{test_file}")


@dataclass(frozen=True)
class CheckOutcome:
    command: str
    result: CommandResult | None = None
    error: str | None = None
    skipped_placeholder: str | None = None

    @property
    def skipped(self) -> bool:
        return self.skipped_placeholder is not None

    @property
    def ok(self) -> bool:
        return self.skipped or (self.result is not None and self.result.ok)

    def output(self) -> str:
        if self.error is not None:
            return self.error
        if self.result is not None:
            return self.result.format()
        return ""


def changed_files(sandbox: Sandbox, since: int = 0) -> list[str]:
    """Relative Pfade der Dateien, die seit Änderung Nr. 'since' geschrieben wurden."""
    seen: dict[str, None] = {}
    for change in sandbox.session_changes[since:]:
        if change.path.exists():
            seen[sandbox.relpath(change.path)] = None
    return list(seen)


def last_test_file(changed: Sequence[str]) -> str | None:
    tests = [path for path in changed if path.startswith("tests/")]
    return tests[-1] if tests else None


def expand(command: str, changed: Sequence[str], test_file: str | None) -> tuple[str, str | None]:
    """Setzt Platzhalter ein. Liefert (Befehl, fehlender Platzhalter oder None)."""
    if "{changed}" in command:
        if not changed:
            return command, "{changed}"
        command = command.replace("{changed}", " ".join(shlex.quote(p) for p in changed))
    if "{test_file}" in command:
        if test_file is None:
            return command, "{test_file}"
        command = command.replace("{test_file}", shlex.quote(test_file))
    return command, None


def run_checks(
    ctx: ToolContext,
    commands: Sequence[str],
    changed: Sequence[str],
    on_outcome: Callable[[CheckOutcome], None] | None = None,
    on_start: Callable[[str], None] | None = None,
) -> list[CheckOutcome]:
    test_file = last_test_file(changed)
    outcomes: list[CheckOutcome] = []
    for template in commands:
        command, missing = expand(template, changed, test_file)
        if missing is not None:
            outcome = CheckOutcome(command, skipped_placeholder=missing)
        else:
            if on_start is not None:
                on_start(command)
            try:
                outcome = CheckOutcome(command, result=run_command(ctx, command))
            except ToolError as exc:
                outcome = CheckOutcome(command, error=texts.TOOL_FAILED.format(error=exc))
        outcomes.append(outcome)
        if on_outcome is not None:
            on_outcome(outcome)
    return outcomes


# ---------------------------------------------------------------------------
# Kleinmodell-Modus: Verify-Befehle erkennen, Fehlerausgabe für den Repair-Schritt kürzen
# ---------------------------------------------------------------------------

FAILURE_MAX_LINES = 60


def detect_verify_commands(root: Path, changed: Sequence[str]) -> list[str]:
    """Automatisch: py_compile für geänderte Python-Dateien, pytest wenn tests/ existiert."""
    commands: list[str] = []
    python_files = [path for path in changed if path.endswith(".py")]
    if python_files:
        commands.append(
            "python -m py_compile " + " ".join(shlex.quote(path) for path in python_files)
        )
    if (root / "tests").is_dir():
        commands.append("python -m pytest -q")
    return commands


def trim_failure(output: str, max_lines: int = FAILURE_MAX_LINES) -> str:
    """Erste Exception mit Traceback – sonst die letzten max_lines Zeilen."""
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("Traceback (most recent call last)"):
            block: list[str] = []
            for follow in lines[index:]:
                block.append(follow)
                is_exception = bool(follow) and not follow.startswith((" ", "Traceback"))
                if is_exception and len(block) > 1:
                    break
            return "\n".join(block[-max_lines:])
    return "\n".join(lines[-max_lines:])


def failure_text(outcomes: Sequence[CheckOutcome]) -> str | None:
    """Gekürzte Ausgabe des ersten fehlgeschlagenen Checks (None, wenn alles grün ist)."""
    for outcome in outcomes:
        if not outcome.ok:
            return f"$ {outcome.command}\n{trim_failure(outcome.output())}"
    return None
