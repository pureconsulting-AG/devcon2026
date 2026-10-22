"""Auto-Kontext für kleine Modelle: erwähnte Dateien, Repo-Map, RAG-Treffer.

Reihenfolge im Verlauf: Systemprompt → Skill → Repo-Map → Dateien → RAG → Auftrag
(der Auftrag steht immer zuletzt, kleine Modelle gewichten das Ende stärker).
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lcc import texts
from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import ToolContext, ToolError, file_hash, number_lines, read_text
from lcc.ollama_client import Message

MAX_WORKSPACE_FILES = 5000
MAX_MENTIONED_FILES = 3
FILE_CONTEXT_MAX_CHARS = 4000
MAX_SYMBOLS_PER_FILE = 12
RAG_CONTEXT_TOP_K = 3

MAP_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".abap",
        ".md",
        ".toml",
        ".txt",
        ".json",
        ".yaml",
        ".yml",
        ".sh",
        ".sql",
        ".java",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cpp",
        ".cfg",
        ".ini",
        ".html",
        ".css",
    }
)

_SYMBOL_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    ".py": (re.compile(r"^(?:async\s+)?def\s+(\w+)"), re.compile(r"^class\s+(\w+)")),
    ".js": (
        re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"),
        re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)"),
    ),
    ".abap": (
        re.compile(r"^\s*CLASS\s+(\w+)\s+DEFINITION", re.IGNORECASE),
        re.compile(r"^\s*METHOD\s+([\w~]+)", re.IGNORECASE),
        re.compile(r"^\s*(?:FORM|FUNCTION)\s+(\w+)", re.IGNORECASE),
    ),
}
_SYMBOL_PATTERNS[".ts"] = _SYMBOL_PATTERNS[".tsx"] = _SYMBOL_PATTERNS[".jsx"] = _SYMBOL_PATTERNS[
    ".js"
]

# Datei-artige Wörter im Auftrag: utils.py, src/app/main.ts, abap/zcl_x.clas.abap
_PATH_TOKEN = re.compile(r"[\w./\\-]*\w\.[A-Za-z0-9]{1,8}\b")


def workspace_files(sandbox: Sandbox, limit: int = MAX_WORKSPACE_FILES) -> list[Path]:
    """Alle Dateien im Workspace (ohne workspace.ignore), flach zuerst, dann alphabetisch."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(sandbox.root):
        current = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not sandbox.is_ignored(current / d))
        for name in sorted(filenames):
            path = current / name
            if not sandbox.is_ignored(path) and not path.is_symlink():
                found.append(path)
                if len(found) >= limit:
                    break
        if len(found) >= limit:
            break
    return sorted(found, key=lambda p: (len(p.relative_to(sandbox.root).parts), str(p)))


def mentioned_files(
    task: str, sandbox: Sandbox, files: Sequence[Path], limit: int = MAX_MENTIONED_FILES
) -> list[Path]:
    """Dateien, die im Auftrag genannt werden (exakter Pfad, Pfad-Ende oder Dateiname)."""
    by_rel = {sandbox.relpath(path): path for path in files}
    result: list[Path] = []
    for token in _PATH_TOKEN.findall(task):
        token = token.replace("\\", "/").removeprefix("./")
        candidates = [path for rel, path in by_rel.items() if rel == token]
        if not candidates:
            candidates = [path for rel, path in by_rel.items() if rel.endswith("/" + token)]
        if not candidates:
            candidates = [path for path in files if path.name == Path(token).name]
        for path in candidates[:1]:
            if path not in result:
                result.append(path)
        if len(result) >= limit:
            break
    return result


def symbols(path: Path, text: str) -> list[str]:
    patterns = _SYMBOL_PATTERNS.get(path.suffix.lower(), ())
    found: list[str] = []
    for line in text.splitlines():
        for pattern in patterns:
            match = pattern.match(line)
            if match and match.group(1) not in found:
                found.append(match.group(1))
        if len(found) >= MAX_SYMBOLS_PER_FILE:
            break
    return found


def repo_map(sandbox: Sandbox, files: Iterable[Path], max_chars: int) -> str:
    """Dateibaum mit Top-Level-Symbolen, begrenzt auf max_chars."""
    lines: list[str] = []
    used = 0
    candidates = [p for p in files if p.suffix.lower() in MAP_SUFFIXES]
    for index, path in enumerate(candidates):
        rel = sandbox.relpath(path)
        try:
            text = read_text(path) if path.stat().st_size < 500_000 else ""
        except (OSError, ToolError):
            text = ""
        names = symbols(path, text)
        line = f"{rel}: {', '.join(names)}" if names else rel
        if used + len(line) + 1 > max_chars:
            lines.append(texts.CONTEXT_MAP_MORE.format(count=len(candidates) - index))
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def file_excerpt(ctx: ToolContext, path: Path, max_chars: int = FILE_CONTEXT_MAX_CHARS) -> str:
    """Datei mit Zeilennummern (gekürzt an Zeilengrenze); merkt den Hash für replace_lines."""
    text = read_text(path)
    ctx.read_hashes[str(path)] = file_hash(path)
    lines = text.splitlines()
    numbered = number_lines(lines, 1) if lines else ""
    if len(numbered) <= max_chars:
        return numbered
    kept: list[str] = []
    used = 0
    for line in numbered.splitlines():
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept) + texts.CONTEXT_FILE_TRUNCATED.format(total=len(lines))


@dataclass
class AutoContext:
    repo_map: str = ""
    files: list[tuple[str, str]] = field(default_factory=list)
    rag: str = ""

    def messages(self) -> list[Message]:
        result: list[Message] = []
        if self.repo_map:
            result.append(
                {"role": "system", "content": texts.CONTEXT_REPO_MAP.format(map=self.repo_map)}
            )
        if self.files:
            body = "\n\n".join(f"--- {rel} ---\n{text}" for rel, text in self.files)
            result.append({"role": "system", "content": texts.CONTEXT_FILES.format(files=body)})
        if self.rag:
            result.append({"role": "system", "content": texts.CONTEXT_RAG.format(hits=self.rag)})
        return result

    @property
    def file_names(self) -> list[str]:
        return [rel for rel, _ in self.files]


def build_auto_context(
    ctx: ToolContext,
    task: str,
    *,
    extra_files: Sequence[str] = (),
    include_map: bool = True,
    include_rag: bool = True,
) -> AutoContext:
    """Sammelt Repo-Map, erwähnte (bzw. im Plan genannte) Dateien und RAG-Treffer."""
    from lcc.rag.search import format_hits

    sandbox = ctx.sandbox
    files = workspace_files(sandbox)
    result = AutoContext()
    if include_map:
        result.repo_map = repo_map(sandbox, files, ctx.config.small_model.repo_map_max_chars)
    wanted = mentioned_files(" ".join([task, *extra_files]), sandbox, files)
    for path in wanted:
        try:
            result.files.append((sandbox.relpath(path), file_excerpt(ctx, path)))
        except (OSError, ToolError):
            continue
    if include_rag and ctx.rag is not None:
        hits = ctx.rag.search(task, top_k=RAG_CONTEXT_TOP_K)
        if hits:
            result.rag = format_hits(hits)
    return result


# ---------------------------------------------------------------------------
# Kontextbudget
# ---------------------------------------------------------------------------

CHARS_PER_TOKEN = 3.5
BUDGET_RATIO = 0.8
KEEP_RECENT_TOOL_RESULTS = 2


def estimate_tokens(messages: Sequence[Message]) -> int:
    """Grobe Schätzung: Zeichen / 3.5 (inkl. Tool-Call-Argumenten)."""
    chars = 0
    for message in messages:
        chars += len(str(message.get("content", "")))
        for call in message.get("tool_calls") or []:
            chars += len(str(call))
    return int(chars / CHARS_PER_TOKEN)


def fit_to_budget(messages: list[Message], num_ctx: int | None) -> int:
    """Ersetzt ältere Tool-Ergebnisse durch '[gekürzt]', bis ~80 % von num_ctx erreicht sind.

    Nutzer-, Assistant- und Systemnachrichten bleiben unverändert, ebenso die letzten
    Tool-Ergebnisse (das Modell braucht sie für den nächsten Schritt). Ändert die Liste
    an Ort und Stelle und liefert die Anzahl gekürzter Ergebnisse.
    """
    if not num_ctx or num_ctx <= 0:
        return 0
    limit = int(num_ctx * BUDGET_RATIO)
    if estimate_tokens(messages) <= limit:
        return 0
    tool_indices = [
        index
        for index, message in enumerate(messages)
        if message.get("tool_name") is not None and message.get("content") != texts.TRUNCATED
    ]
    shortened = 0
    for index in tool_indices[:-KEEP_RECENT_TOOL_RESULTS] if KEEP_RECENT_TOOL_RESULTS else []:
        messages[index] = {**messages[index], "content": texts.TRUNCATED}
        shortened += 1
        if estimate_tokens(messages) <= limit:
            break
    return shortened
