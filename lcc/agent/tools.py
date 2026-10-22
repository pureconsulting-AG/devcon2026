"""Tool-Registry und Tool-Implementierungen.

Tool-Fehler werden als Text an das Modell zurückgegeben, nie als Exception.
Beschreibungen sind bewusst kurz – kleine Modelle lesen jedes Wort.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lcc import texts
from lcc.agent import fuzzy
from lcc.agent.sandbox import (
    Confirmer,
    Sandbox,
    SandboxError,
    is_allowlisted,
    split_command,
    unified_diff,
)
from lcc.config import Config
from lcc.ollama_client import ToolCall

if TYPE_CHECKING:
    from lcc.rag.search import RagSearcher
    from lcc.skills.active import SkillSession


class ToolError(Exception):
    """Erwarteter Fehler eines Tools; Text geht an das Modell."""


@dataclass
class ToolContext:
    """Alles, was Tools zur Laufzeit brauchen (wird explizit durchgereicht)."""

    config: Config
    sandbox: Sandbox
    confirmer: Confirmer = field(default_factory=Confirmer)
    rag: RagSearcher | None = None
    skills: SkillSession | None = None
    # Kleinmodell-Modus: fuzzy edit_file, replace_lines, Sperre für write_file auf großen Dateien
    small_mode: bool = False
    # sha256 je Datei beim letzten read_file (für replace_lines)
    read_hashes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    content: str
    ok: bool = True


Handler = Callable[[ToolContext, dict[str, Any]], str]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Mapping[str, Any]
    handler: Handler
    example: Mapping[str, Any] = field(default_factory=dict)

    def to_ollama(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(self.parameters),
            },
        }

    def example_call(self) -> str:
        return json.dumps({"tool": self.name, "arguments": dict(self.example)}, ensure_ascii=False)


def truncate_middle(text: str, limit: int) -> str:
    """Kürzt lange Ausgaben auf Anfang + Ende."""
    if limit <= 0 or len(text) <= limit:
        return text
    marker_budget = 60
    keep = max(limit - marker_budget, 0)
    head = keep * 2 // 3
    tail = keep - head
    removed = len(text) - head - tail
    end = text[len(text) - tail :] if tail else ""
    return text[:head] + texts.TOOL_TRUNCATED.format(count=removed) + end


_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate_arguments(spec: ToolSpec, arguments: Mapping[str, Any]) -> list[str]:
    """Prüft Argumente gegen das (einfache) JSON-Schema. Liefert Problemtexte."""
    properties: Mapping[str, Any] = spec.parameters.get("properties", {})
    problems: list[str] = []
    for name in spec.parameters.get("required", []):
        if arguments.get(name) is None:
            problems.append(texts.TOOL_ARG_MISSING.format(arg=name))
    for name, value in arguments.items():
        if name not in properties:
            problems.append(texts.TOOL_ARG_UNKNOWN.format(arg=name))
            continue
        expected = properties[name].get("type")
        if value is None or expected not in _JSON_TYPES:
            continue
        allowed = _JSON_TYPES[expected]
        is_bool = isinstance(value, bool)
        if not isinstance(value, allowed) or (is_bool and expected in ("integer", "number")):
            problems.append(texts.TOOL_ARG_TYPE.format(arg=name, expected=expected))
    return problems


def _coerce_arguments(spec: ToolSpec, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Kleine Modelle schicken Zahlen oft als Strings ("12") – das reparieren wir still."""
    properties: Mapping[str, Any] = spec.parameters.get("properties", {})
    result = dict(arguments)
    for name, value in arguments.items():
        expected = properties.get(name, {}).get("type")
        if expected == "integer" and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            result[name] = int(value.strip())
        elif expected == "integer" and isinstance(value, float) and value.is_integer():
            result[name] = int(value)
    return result


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec] = ()) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        self._specs[spec.name] = spec

    def names(self) -> list[str]:
        return list(self._specs)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(name)

    def schemas(self, names: Sequence[str] | None = None) -> list[dict[str, Any]]:
        selected = self.names() if names is None else [n for n in names if n in self._specs]
        return [self._specs[name].to_ollama() for name in selected]

    def execute(
        self, call: ToolCall, ctx: ToolContext, allowed: Sequence[str] | None = None
    ) -> ToolResult:
        available = self.names() if allowed is None else [n for n in allowed if n in self._specs]
        spec = self._specs.get(call.name)
        if spec is None or call.name not in available:
            return ToolResult(
                texts.TOOL_UNKNOWN.format(name=call.name, available=", ".join(available)),
                ok=False,
            )
        arguments = _coerce_arguments(spec, call.arguments)
        problems = validate_arguments(spec, arguments)
        if problems:
            return ToolResult(
                texts.TOOL_BAD_ARGS.format(
                    name=spec.name, problems="; ".join(problems), example=spec.example_call()
                ),
                ok=False,
            )
        limit = ctx.config.agent.max_tool_output_chars
        try:
            output = spec.handler(ctx, arguments)
        except (ToolError, SandboxError) as exc:
            return ToolResult(texts.TOOL_FAILED.format(error=exc), ok=False)
        except Exception as exc:  # Tool-Fehler nie als Exception an die Schleife
            return ToolResult(
                texts.TOOL_FAILED.format(error=f"{type(exc).__name__}: {exc}"), ok=False
            )
        return ToolResult(truncate_middle(output, limit))


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------

MAX_LIST_DEPTH = 5


def _iter_tree(sandbox: Sandbox, directory: Path, depth: int, indent: str) -> Iterator[str]:
    try:
        entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return
    for entry in entries:
        if sandbox.is_ignored(entry):
            continue
        if entry.is_dir():
            yield f"{indent}{entry.name}/"
            if depth > 1 and not entry.is_symlink():
                yield from _iter_tree(sandbox, entry, depth - 1, indent + "  ")
        else:
            yield f"{indent}{entry.name}"


def list_dir(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = ctx.sandbox.resolve_read(args.get("path") or ".")
    if not path.exists():
        raise ToolError(texts.TOOL_NOT_FOUND.format(path=args.get("path")))
    if not path.is_dir():
        raise ToolError(texts.TOOL_NOT_A_DIR.format(path=args.get("path")))
    depth = max(1, min(int(args.get("depth") or 1), MAX_LIST_DEPTH))
    lines = list(_iter_tree(ctx.sandbox, path, depth, ""))
    rel = ctx.sandbox.relpath(path)
    if not lines:
        return texts.TOOL_DIR_EMPTY.format(path=rel)
    return f"{rel}/\n" + "\n".join("  " + line for line in lines)


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def read_text(path: Path) -> str:
    data = path.read_bytes()
    if is_binary(data):
        raise ToolError(texts.TOOL_BINARY.format(path=path.name))
    return data.decode("utf-8", errors="replace")


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def number_lines(lines: Sequence[str], start: int) -> str:
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{n:>{width}}| {line}" for n, line in enumerate(lines, start))


def read_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    raw_path = str(args["path"])
    path = ctx.sandbox.resolve_read(raw_path)
    if not path.exists():
        raise ToolError(texts.TOOL_NOT_FOUND.format(path=raw_path))
    if not path.is_file():
        raise ToolError(texts.TOOL_NOT_A_FILE.format(path=raw_path))
    lines = read_text(path).splitlines()
    ctx.read_hashes[str(path)] = file_hash(path)
    rel = ctx.sandbox.relpath(path)
    total = len(lines)
    if total == 0:
        return texts.TOOL_READ_EMPTY.format(path=rel)
    start = max(1, int(args.get("start_line") or 1))
    end = min(total, int(args.get("end_line") or total))
    if start > total or end < start:
        raise ToolError(texts.TOOL_READ_RANGE.format(start=start, end=end, total=total))

    limit = ctx.config.agent.max_tool_output_chars
    header = texts.TOOL_READ_HEADER.format(path=rel, start=start, end=end, total=total)
    body = number_lines(lines[start - 1 : end], start)
    if len(header) + len(body) + 1 <= limit:
        return f"{header}\n{body}"
    # Lieber an einer Zeilengrenze abschneiden als in der Mitte (Zeilennummern bleiben gültig).
    kept: list[str] = []
    budget = limit - len(header) - len(texts.TOOL_READ_TRUNCATED_HINT) - 1
    for line in body.splitlines():
        if budget - len(line) - 1 < 0:
            break
        kept.append(line)
        budget -= len(line) + 1
    last = start + len(kept) - 1
    header = texts.TOOL_READ_HEADER.format(path=rel, start=start, end=last, total=total)
    return f"{header}\n" + "\n".join(kept) + texts.TOOL_READ_TRUNCATED_HINT


# ---------------------------------------------------------------------------
# search_code
# ---------------------------------------------------------------------------

SEARCH_MAX_MATCHES = 200
SEARCH_MAX_LINE_CHARS = 300


def _format_match(rel: str, line_no: int, text: str) -> str:
    text = text.rstrip("\n")
    if len(text) > SEARCH_MAX_LINE_CHARS:
        text = text[:SEARCH_MAX_LINE_CHARS] + "…"
    return f"{rel}:{line_no}: {text}"


def _search_rg(
    rg: str, sandbox: Sandbox, pattern: str, base: Path, glob: str | None
) -> list[str] | None:
    """Suche mit ripgrep; None, wenn rg nicht nutzbar war."""
    command = [rg, "--line-number", "--no-heading", "--color", "never", "--hidden"]
    command += ["--max-columns", str(SEARCH_MAX_LINE_CHARS)]
    for pattern_ignore in sandbox.ignore:
        command += ["--glob", f"!{pattern_ignore}"]
    if glob:
        command += ["--glob", glob]
    command += ["-e", pattern, "--", os.path.relpath(base, sandbox.root)]
    try:
        proc = subprocess.run(
            command, cwd=sandbox.root, capture_output=True, text=True, timeout=60, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode == 2:
        raise ToolError(
            texts.TOOL_SEARCH_BAD_REGEX.format(pattern=pattern, error=proc.stderr.strip())
        )
    matches: list[str] = []
    for line in proc.stdout.splitlines():
        rel, _, rest = line.partition(":")
        line_no, _, text = rest.partition(":")
        if not line_no.isdigit():
            continue
        rel = Path(rel).as_posix().removeprefix("./")
        matches.append(_format_match(rel, int(line_no), text))
    return matches


def _iter_files(sandbox: Sandbox, base: Path) -> Iterator[Path]:
    if base.is_file():
        yield base
        return
    for dirpath, dirnames, filenames in os.walk(base):
        current = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not sandbox.is_ignored(current / d))
        for name in sorted(filenames):
            path = current / name
            if not sandbox.is_ignored(path):
                yield path


def _search_python(sandbox: Sandbox, pattern: str, base: Path, glob: str | None) -> list[str]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(texts.TOOL_SEARCH_BAD_REGEX.format(pattern=pattern, error=exc)) from exc
    matches: list[str] = []
    for path in _iter_files(sandbox, base):
        rel = sandbox.relpath(path)
        if glob and not (Path(rel).match(glob) or Path(path.name).match(glob)):
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if is_binary(data):
            continue
        for line_no, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
            if regex.search(line):
                matches.append(_format_match(rel, line_no, line))
                if len(matches) > SEARCH_MAX_MATCHES:
                    return matches
    return matches


def search_code(ctx: ToolContext, args: dict[str, Any]) -> str:
    pattern = str(args["pattern"])
    base = ctx.sandbox.resolve_read(args.get("path") or ".")
    if not base.exists():
        raise ToolError(texts.TOOL_NOT_FOUND.format(path=args.get("path")))
    glob = args.get("glob") or None
    matches: list[str] | None = None
    rg = shutil.which("rg")
    if rg:
        matches = _search_rg(rg, ctx.sandbox, pattern, base, glob)
    if matches is None:
        matches = _search_python(ctx.sandbox, pattern, base, glob)
    if not matches:
        return texts.TOOL_SEARCH_NONE.format(pattern=pattern)
    matches.sort(key=_match_sort_key)
    if len(matches) > SEARCH_MAX_MATCHES:
        matches = [
            *matches[:SEARCH_MAX_MATCHES],
            texts.TOOL_SEARCH_LIMIT.format(limit=SEARCH_MAX_MATCHES),
        ]
    return "\n".join(matches)


def _match_sort_key(match: str) -> tuple[str, int]:
    rel, _, rest = match.partition(":")
    line_no = rest.partition(":")[0]
    return rel, int(line_no) if line_no.isdigit() else 0


# ---------------------------------------------------------------------------
# write_file / edit_file
# ---------------------------------------------------------------------------


def _line_count(text: str) -> int:
    return len(text.splitlines())


def _confirm_and_write(ctx: ToolContext, path: Path, before: str | None, after: str) -> None:
    """Diff zeigen, Bestätigung einholen, mit Backup schreiben. Ablehnung → ToolError."""
    rel = ctx.sandbox.relpath(path)
    diff = unified_diff(before or "", after, rel)
    if not ctx.confirmer.confirm_write(rel, diff):
        if ctx.confirmer.interactive:
            raise ToolError(texts.WRITE_DENIED.format(path=rel))
        raise ToolError(texts.WRITE_DENIED_NON_TTY.format(path=rel))
    ctx.sandbox.write_text(path, after)


def _read_existing(path: Path) -> str | None:
    if not path.exists():
        return None
    return read_text(path)


def write_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = ctx.sandbox.resolve_write(str(args["path"]))
    content = str(args["content"])
    if content and not content.endswith("\n"):
        content += "\n"
    before = _read_existing(path)
    rel = ctx.sandbox.relpath(path)
    if before == content:
        return texts.WRITE_UNCHANGED.format(path=rel)
    if ctx.small_mode and before is not None and _line_count(before) > SMALL_WRITE_MAX_LINES:
        raise ToolError(
            texts.WRITE_TOO_LONG.format(
                path=rel, lines=_line_count(before), limit=SMALL_WRITE_MAX_LINES
            )
        )
    _confirm_and_write(ctx, path, before, content)
    template = texts.WRITE_DONE_NEW if before is None else texts.WRITE_DONE
    return template.format(path=rel, lines=_line_count(content))


def _occurrence_lines(text: str, needle: str) -> list[int]:
    lines: list[int] = []
    start = text.find(needle)
    while start != -1:
        lines.append(text.count("\n", 0, start) + 1)
        start = text.find(needle, start + 1)
    return lines


def edit_file(ctx: ToolContext, args: dict[str, Any]) -> str:
    raw_path = str(args["path"])
    path = ctx.sandbox.resolve_write(raw_path)
    old, new = str(args["old_str"]), str(args["new_str"])
    if not path.is_file():
        raise ToolError(texts.TOOL_NOT_FOUND.format(path=raw_path))
    if not old:
        raise ToolError(texts.EDIT_EMPTY)
    if old == new:
        raise ToolError(texts.EDIT_SAME)
    before = read_text(path)
    rel = ctx.sandbox.relpath(path)
    occurrences = _occurrence_lines(before, old)
    fuzzy = ctx.small_mode and ctx.config.small_model.fuzzy_edit
    if not occurrences and fuzzy:
        return _fuzzy_edit(ctx, path, rel, before, old, new)
    if not occurrences:
        raise ToolError(texts.EDIT_NOT_FOUND.format(path=rel))
    if len(occurrences) > 1:
        message = texts.EDIT_AMBIGUOUS.format(
            path=rel, count=len(occurrences), lines=", ".join(map(str, occurrences))
        )
        if fuzzy:
            message += "\n" + _locations_text(before.splitlines(), old)
        raise ToolError(message)
    after = before.replace(old, new, 1)
    _confirm_and_write(ctx, path, before, after)
    start = occurrences[0]
    end = start + max(_line_count(new), 1) - 1
    return texts.EDIT_DONE.format(path=rel, start=start, end=end)


# ---------------------------------------------------------------------------
# Kleinmodell-Werkzeuge: fuzzy edit_file, replace_lines
# ---------------------------------------------------------------------------

SMALL_WRITE_MAX_LINES = 200


def _locations_text(lines: list[str], old: str) -> str:
    locations = fuzzy.similar_locations(lines, old)
    if not locations:
        return ""
    return fuzzy.format_locations(locations, texts.EDIT_SIMILAR_HEADER, texts.EDIT_SIMILAR_LINE)


def _fuzzy_edit(ctx: ToolContext, path: Path, rel: str, before: str, old: str, new: str) -> str:
    """Kein exakter Treffer: Vergleich mit normalisiertem Whitespace."""
    lines = before.splitlines(keepends=True)
    plain = [line.rstrip("\r\n") for line in lines]
    matches = fuzzy.find_fuzzy(plain, old)
    if len(matches) != 1:
        if matches:
            numbers = ", ".join(str(m + 1) for m in matches)
            message = texts.EDIT_AMBIGUOUS.format(path=rel, count=len(matches), lines=numbers)
        else:
            message = texts.EDIT_NOT_FOUND.format(path=rel)
        raise ToolError(message + "\n" + _locations_text(plain, old))
    start = matches[0]
    size = len(fuzzy.needle_lines(old))
    replacement = fuzzy.reindent(new, plain[start])
    ends_with_newline = lines[start + size - 1].endswith("\n")
    if replacement and ends_with_newline and not replacement.endswith("\n"):
        replacement += "\n"
    after = "".join(lines[:start]) + replacement + "".join(lines[start + size :])
    _confirm_and_write(ctx, path, before, after)
    end = start + max(_line_count(replacement), 1)
    return texts.EDIT_DONE_FUZZY.format(path=rel, start=start + 1, end=end)


def replace_lines(ctx: ToolContext, args: dict[str, Any]) -> str:
    raw_path = str(args["path"])
    path = ctx.sandbox.resolve_write(raw_path)
    if not path.is_file():
        raise ToolError(texts.TOOL_NOT_FOUND.format(path=raw_path))
    rel = ctx.sandbox.relpath(path)
    if ctx.read_hashes.get(str(path)) != file_hash(path):
        raise ToolError(texts.REPLACE_REREAD.format(path=rel))
    before = read_text(path)
    lines = before.splitlines(keepends=True)
    start, end = int(args["start_line"]), int(args["end_line"])
    if start < 1 or end < start or end > len(lines):
        raise ToolError(
            texts.REPLACE_RANGE.format(start=start, end=end, total=len(lines), path=rel)
        )
    content = str(args["content"])
    if content and not content.endswith("\n"):
        content += "\n"
    after = "".join(lines[: start - 1]) + content + "".join(lines[end:])
    _confirm_and_write(ctx, path, before, after)
    ctx.read_hashes.pop(str(path), None)  # Zeilennummern haben sich ggf. verschoben
    return texts.REPLACE_DONE.format(path=rel, start=start, end=end, count=_line_count(content))


# ---------------------------------------------------------------------------
# run_shell
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommandResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def format(self) -> str:
        return texts.SHELL_RESULT.format(
            code=self.exit_code, stdout=self.stdout.rstrip("\n"), stderr=self.stderr.rstrip("\n")
        )


def resolve_program(tokens: list[str]) -> list[str]:
    """'python' ohne python im PATH → der Interpreter, unter dem lcc läuft.

    Häufig, wenn lcc als .venv/bin/lcc ohne aktivierte venv gestartet wird: dann gibt es nur
    python3, und Checks wie 'python -m pytest' würden mit „nicht gefunden“ scheitern.
    Erlaubt bleibt, was die Allowlist erlaubt – hier wird nur das Programm aufgelöst.
    """
    if tokens and tokens[0] == "python" and shutil.which("python") is None:
        return [sys.executable, *tokens[1:]]
    return tokens


def run_command(ctx: ToolContext, command: str) -> CommandResult:
    """Führt einen Befehl über die Sandbox aus (Allowlist/Bestätigung, Timeout, kein shell=True).

    Ablehnung, Timeout und unbekanntes Programm → ToolError.
    """
    command = command.strip()
    tokens = split_command(command)
    agent_cfg = ctx.config.agent
    if not is_allowlisted(tokens, agent_cfg.shell_allowlist) and not ctx.confirmer.confirm_command(
        command
    ):
        if ctx.confirmer.interactive:
            raise ToolError(texts.SHELL_DENIED.format(command=command))
        raise ToolError(
            texts.SHELL_DENIED_NON_TTY.format(
                command=command, allowlist=", ".join(agent_cfg.shell_allowlist)
            )
        )
    timeout = agent_cfg.shell_timeout_seconds
    try:
        proc = subprocess.run(
            resolve_program(tokens),
            cwd=ctx.sandbox.root,
            capture_output=True,
            text=True,
            errors="replace",
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(texts.SHELL_NOT_FOUND.format(program=tokens[0])) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(texts.SHELL_TIMEOUT.format(seconds=timeout, command=command)) from exc
    return CommandResult(command, proc.returncode, proc.stdout, proc.stderr)


def run_shell(ctx: ToolContext, args: dict[str, Any]) -> str:
    return run_command(ctx, str(args["command"])).format()


# ---------------------------------------------------------------------------
# rag_search
# ---------------------------------------------------------------------------


def rag_search(ctx: ToolContext, args: dict[str, Any]) -> str:
    from lcc.rag.search import format_hits

    if ctx.rag is None:
        raise ToolError(texts.RAG_DISABLED)
    query = str(args["query"])
    hits = ctx.rag.search(query, top_k=args.get("top_k") or None)
    if not hits:
        return texts.RAG_NO_HITS.format(min_score=ctx.config.rag.min_score, query=query)
    return format_hits(hits)


# ---------------------------------------------------------------------------
# load_skill
# ---------------------------------------------------------------------------


def load_skill(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.skills is None:
        raise ToolError(texts.SKILL_DISABLED)
    return ctx.skills.load(str(args["name"]), ctx)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

LIST_DIR = ToolSpec(
    name="list_dir",
    description="List files and folders. Use first to get an overview.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Folder, relative to workspace. Default '.'"},
            "depth": {"type": "integer", "description": "Levels to show (1-5). Default 1"},
        },
        "required": [],
    },
    handler=list_dir,
    example={"path": "src", "depth": 2},
)

READ_FILE = ToolSpec(
    name="read_file",
    description="Read a text file with line numbers. Use start_line/end_line for large files.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File, relative to workspace"},
            "start_line": {"type": "integer", "description": "First line (1-based)"},
            "end_line": {"type": "integer", "description": "Last line (inclusive)"},
        },
        "required": ["path"],
    },
    handler=read_file,
    example={"path": "src/app.py", "start_line": 1, "end_line": 80},
)

SEARCH_CODE = ToolSpec(
    name="search_code",
    description="Search files with a regex. Returns file:line: text.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regular expression"},
            "path": {"type": "string", "description": "Folder or file. Default '.'"},
            "glob": {"type": "string", "description": "File filter, e.g. '*.py'"},
        },
        "required": ["pattern"],
    },
    handler=search_code,
    example={"pattern": "def slugify", "glob": "*.py"},
)

WRITE_FILE = ToolSpec(
    name="write_file",
    description=(
        "Create a new file (missing folders are created) or replace a whole file. "
        "Prefer edit_file for small changes."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File, relative to workspace"},
            "content": {"type": "string", "description": "Complete new file content"},
        },
        "required": ["path", "content"],
    },
    handler=write_file,
    example={"path": "src/util.py", "content": "def add(a, b):\n    return a + b\n"},
)

EDIT_FILE = ToolSpec(
    name="edit_file",
    description="Replace old_str with new_str in a file. old_str must match exactly once.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File, relative to workspace"},
            "old_str": {"type": "string", "description": "Exact text to replace (no line numbers)"},
            "new_str": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_str", "new_str"],
    },
    handler=edit_file,
    example={"path": "src/util.py", "old_str": "return a - b", "new_str": "return a + b"},
)

RUN_SHELL = ToolSpec(
    name="run_shell",
    description="Run a shell command in the workspace (no pipes). Returns exit code and output.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command, e.g. 'python -m pytest -q'"},
        },
        "required": ["command"],
    },
    handler=run_shell,
    example={"command": "python -m pytest -q"},
)

RAG_SEARCH = ToolSpec(
    name="rag_search",
    description="Search the project documentation. Cite results as [n] in your answer.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "What to look for, as a question"},
            "top_k": {"type": "integer", "description": "Number of results. Default 5"},
        },
        "required": ["query"],
    },
    handler=rag_search,
    example={"query": "Wie wird die Config geladen?"},
)

LOAD_SKILL = ToolSpec(
    name="load_skill",
    description="Load the instructions of a listed skill before doing that kind of task.",
    parameters={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Skill name from the list"}},
        "required": ["name"],
    },
    handler=load_skill,
    example={"name": "pytest-test"},
)

REPLACE_LINES = ToolSpec(
    name="replace_lines",
    description="Replace lines start_line..end_line with content. Line numbers from read_file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File, relative to workspace"},
            "start_line": {"type": "integer", "description": "First line to replace"},
            "end_line": {"type": "integer", "description": "Last line to replace (inclusive)"},
            "content": {"type": "string", "description": "New lines (without line numbers)"},
        },
        "required": ["path", "start_line", "end_line", "content"],
    },
    handler=replace_lines,
    example={"path": "src/util.py", "start_line": 2, "end_line": 2, "content": "    return a + b"},
)

READ_ONLY_TOOLS: tuple[ToolSpec, ...] = (LIST_DIR, READ_FILE, SEARCH_CODE)
WRITE_TOOLS: tuple[ToolSpec, ...] = (WRITE_FILE, EDIT_FILE, RUN_SHELL)


def default_registry() -> ToolRegistry:
    return ToolRegistry((*READ_ONLY_TOOLS, *WRITE_TOOLS, RAG_SEARCH, LOAD_SKILL, REPLACE_LINES))


def available_tool_names(registry: ToolRegistry, ctx: ToolContext) -> list[str]:
    """Tools, die im aktuellen Kontext sinnvoll sind.

    rag_search nur mit aktivem RAG, load_skill nur mit Skills. Ein aktiver Skill mit
    tools-Liste schränkt die Auswahl weiter ein (Schnittmenge).
    """
    names = [
        name
        for name in registry.names()
        if (name != "rag_search" or ctx.rag is not None)
        and (name != "load_skill" or (ctx.skills is not None and bool(ctx.skills.available)))
        and (name != "replace_lines" or ctx.small_mode)
    ]
    return ctx.skills.allowed_tools(names) if ctx.skills is not None else names
