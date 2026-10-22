"""Sandbox: Pfad-Jail, Schreibschutz, Undo-Backups, Shell-Allowlist und Bestätigungen.

Alle Dateizugriffe des Agenten bleiben innerhalb von workspace.root. Vor jeder
Schreibänderung wird ein Backup unter .lcc/undo/<timestamp>/ angelegt.
"""

from __future__ import annotations

import difflib
import fnmatch
import json
import shlex
import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.text import Text

from lcc import texts

UNDO_RELPATH = Path(".lcc/undo")
MANIFEST_NAME = "manifest.json"
BACKUP_NAME = "original"


class SandboxError(Exception):
    """Zugriff verweigert; Text geht als Tool-Ergebnis an das Modell."""


@dataclass(frozen=True)
class Change:
    """Eine Schreibänderung mit Backup-Ordner (Basis für /undo und /diff)."""

    path: Path
    backup_dir: Path
    existed: bool


class Sandbox:
    def __init__(
        self,
        root: Path,
        ignore: Sequence[str] = (),
        extra_read_roots: Sequence[Path] = (),
    ) -> None:
        self.root = root.resolve()
        self.ignore = tuple(ignore)
        self.extra_read_roots = tuple(path.resolve() for path in extra_read_roots)
        self.undo_dir = self.root / UNDO_RELPATH
        self.session_changes: list[Change] = []

    def add_read_root(self, path: Path) -> None:
        """Zusätzlicher, nur lesbarer Ordner (z. B. ein aktiver Skill)."""
        resolved = path.resolve()
        if resolved not in self.extra_read_roots:
            self.extra_read_roots = (*self.extra_read_roots, resolved)

    # -- Pfade --------------------------------------------------------------

    def _candidate(self, path: str | Path) -> Path:
        raw = Path(str(path).strip() or ".").expanduser()
        return raw if raw.is_absolute() else self.root / raw

    def resolve_read(self, path: str | Path) -> Path:
        """Löst einen Pfad auf (inkl. Symlinks) und prüft, dass er lesbar erlaubt ist."""
        resolved = self._candidate(path).resolve()
        allowed = (self.root, *self.extra_read_roots)
        if not any(resolved.is_relative_to(base) for base in allowed):
            raise SandboxError(texts.SANDBOX_OUTSIDE.format(path=path, root=self.root))
        return resolved

    def resolve_write(self, path: str | Path) -> Path:
        """Wie resolve_read, aber nur im Workspace und nie in .git/ oder .lcc/undo/."""
        resolved = self._candidate(path).resolve()
        if not resolved.is_relative_to(self.root) or resolved == self.root:
            raise SandboxError(texts.SANDBOX_OUTSIDE.format(path=path, root=self.root))
        rel = resolved.relative_to(self.root)
        if ".git" in rel.parts:
            raise SandboxError(texts.SANDBOX_GIT.format(path=path))
        if resolved.is_relative_to(self.undo_dir):
            raise SandboxError(texts.SANDBOX_UNDO_DIR.format(path=path))
        if resolved.is_dir():
            raise SandboxError(texts.TOOL_NOT_A_FILE.format(path=path))
        return resolved

    def relpath(self, path: Path) -> str:
        """Pfad relativ zum Workspace (für Ausgaben an Modell und Nutzer)."""
        try:
            rel = path.resolve().relative_to(self.root)
        except ValueError:
            return str(path)
        return rel.as_posix() or "."

    def is_ignored(self, path: Path) -> bool:
        """True, wenn ein Pfadteil oder der relative Pfad auf workspace.ignore passt."""
        try:
            rel = path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return False
        if rel == ".":
            return False
        if rel == UNDO_RELPATH.as_posix() or rel.startswith(UNDO_RELPATH.as_posix() + "/"):
            return True
        parts = rel.split("/")
        for pattern in self.ignore:
            pattern = pattern.strip("/")
            if "/" in pattern:
                if fnmatch.fnmatch(rel, pattern) or rel.startswith(pattern + "/"):
                    return True
            elif any(fnmatch.fnmatch(part, pattern) for part in parts):
                return True
        return False

    # -- Schreiben + Undo ---------------------------------------------------

    def _new_backup_dir(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        candidate = self.undo_dir / stamp
        counter = 1
        while candidate.exists():
            candidate = self.undo_dir / f"{stamp}-{counter}"
            counter += 1
        candidate.mkdir(parents=True)
        return candidate

    def write_text(self, path: Path, content: str) -> Change:
        """Schreibt eine Datei im Workspace (Pfad wird geprüft) – mit Backup vorher."""
        target = self.resolve_write(path)
        backup_dir = self._new_backup_dir()
        existed = target.exists()
        if existed:
            shutil.copy2(target, backup_dir / BACKUP_NAME)
        manifest = {"path": self.relpath(target), "existed": existed}
        (backup_dir / MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        change = Change(path=target, backup_dir=backup_dir, existed=existed)
        self.session_changes.append(change)
        return change

    def backups(self) -> list[Path]:
        """Alle Backup-Ordner, älteste zuerst."""
        if not self.undo_dir.is_dir():
            return []
        return sorted(p for p in self.undo_dir.iterdir() if (p / MANIFEST_NAME).is_file())

    def undo_last(self) -> Change | None:
        """Nimmt die letzte Änderung zurück (auch aus früheren Sessions)."""
        backups = self.backups()
        if not backups:
            return None
        backup_dir = backups[-1]
        manifest = json.loads((backup_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        target = self.resolve_write(manifest["path"])
        existed = bool(manifest["existed"])
        if existed:
            shutil.copy2(backup_dir / BACKUP_NAME, target)
        elif target.exists():
            target.unlink()
        shutil.rmtree(backup_dir)
        change = Change(path=target, backup_dir=backup_dir, existed=existed)
        self.session_changes = [c for c in self.session_changes if c.backup_dir != backup_dir]
        return change

    def session_diff(self) -> str:
        """Unified Diff aller Dateien, die in dieser Session geändert wurden."""
        first_backup: dict[Path, Change] = {}
        for change in self.session_changes:
            first_backup.setdefault(change.path, change)
        parts: list[str] = []
        for path, change in first_backup.items():
            before = ""
            if change.existed:
                before = (change.backup_dir / BACKUP_NAME).read_text(
                    encoding="utf-8", errors="replace"
                )
            after = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            parts.append(unified_diff(before, after, self.relpath(path)))
        return "".join(part for part in parts if part)


def unified_diff(before: str, after: str, name: str) -> str:
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{name}",
        tofile=f"b/{name}",
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


# ---------------------------------------------------------------------------
# Shell
# ---------------------------------------------------------------------------


def split_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise SandboxError(texts.SHELL_PARSE_ERROR.format(error=exc)) from exc
    if not tokens:
        raise SandboxError(texts.SHELL_EMPTY)
    return tokens


def is_allowlisted(tokens: Sequence[str], allowlist: Sequence[str]) -> bool:
    """Präfix-Vergleich auf Token-Ebene: 'git status' erlaubt 'git status -s', nicht 'git push'."""
    for entry in allowlist:
        entry_tokens = shlex.split(entry)
        if entry_tokens and list(tokens[: len(entry_tokens)]) == entry_tokens:
            return True
    return False


# ---------------------------------------------------------------------------
# Bestätigungen
# ---------------------------------------------------------------------------

Answer = Literal["yes", "no", "always"]
AskFn = Callable[[str], str]


def render_diff(diff: str) -> Text:
    text = Text()
    for line in diff.splitlines(keepends=True):
        if line.startswith(("+++", "---")):
            style = "bold"
        elif line.startswith("+"):
            style = "green"
        elif line.startswith("-"):
            style = "red"
        elif line.startswith("@@"):
            style = "cyan"
        else:
            style = ""
        text.append(line, style=style)
    return text


@dataclass
class Confirmer:
    """Fragt vor Schreiben/Shell nach: [j]a / [n]ein / [i]mmer für diese Session.

    Ohne TTY (interactive=False) wird alles abgelehnt, was eine Rückfrage bräuchte.
    assume_yes (--yes) überspringt nur Schreib-Bestätigungen, nicht die Shell.
    """

    interactive: bool = False
    assume_yes: bool = False
    confirm_writes: bool = True
    confirm_shell: bool = True
    console: Console = field(default_factory=lambda: Console(stderr=True))
    ask: AskFn | None = None
    # Wird vor jeder Eingabe aufgerufen (z. B. um den Spinner anzuhalten)
    before_prompt: Callable[[], None] | None = None
    _always_writes: bool = False
    _always_commands: set[str] = field(default_factory=set)

    def _prompt(self) -> Answer:
        ask = self.ask or self._console_input
        while True:
            answer = ask(texts.CONFIRM_PROMPT).strip().lower()
            if answer in ("j", "ja", "y", "yes"):
                return "yes"
            if answer in ("", "n", "nein", "no"):
                return "no"
            if answer in ("i", "immer", "a", "always"):
                return "always"

    def _pause(self) -> None:
        if self.before_prompt is not None:
            self.before_prompt()

    def ask_line(self, prompt: str) -> str:
        """Freie Eingabe (z. B. Plan-Dialog) über denselben Kanal wie die Bestätigungen."""
        self._pause()
        return (self.ask or self._console_input)(prompt)

    def _console_input(self, prompt: str) -> str:
        # markup=False: sonst liest rich "[j]", "[n]", "[i]" als Formatierung und verschluckt sie.
        return self.console.input(prompt, markup=False)

    def confirm_write(self, relpath: str, diff: str) -> bool:
        if not self.confirm_writes or self.assume_yes or self._always_writes:
            return True
        if not self.interactive:
            return False
        self._pause()
        self.console.print(texts.CONFIRM_WRITE.format(path=relpath), style="bold", markup=False)
        self.console.print(render_diff(diff) if diff else texts.CONFIRM_NO_CHANGES)
        answer = self._prompt()
        if answer == "always":
            self._always_writes = True
        return answer != "no"

    def confirm_command(self, command: str) -> bool:
        if not self.confirm_shell or command in self._always_commands:
            return True
        if not self.interactive:
            return False
        self._pause()
        self.console.print(texts.CONFIRM_SHELL.format(command=command), style="bold", markup=False)
        answer = self._prompt()
        if answer == "always":
            self._always_commands.add(command)
        return answer != "no"
