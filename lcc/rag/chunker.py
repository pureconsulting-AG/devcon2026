"""Zerlegt Dateien in Chunks mit Zeilenbereichen.

- Markdown: an Überschriften (außerhalb von Code-Fences), große Abschnitte nach Zeichen.
- Code: Blöcke an Leerzeilen und vor Funktions-/Klassengrenzen, gepackt bis chunk_size.
- Rest: nach Zeichen mit Overlap, an Zeilengrenzen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
CODE_SUFFIXES = frozenset(
    {".py", ".abap", ".js", ".ts", ".java", ".go", ".rs", ".c", ".h", ".cpp", ".sh", ".sql"}
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
# Grenzen, vor denen ein neuer Code-Block beginnt (Python, JS, ABAP u. ä.).
_CODE_BOUNDARY = re.compile(
    r"^(?:async\s+def|def|class|function|export\s+(?:default\s+)?(?:function|class)"
    r"|CLASS|METHOD|FORM|FUNCTION|MODULE|REPORT)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    start_line: int
    end_line: int
    text: str
    heading: str | None = None


# (Zeilennummer, Text) – Zeilennummern sind 1-basiert.
Line = tuple[int, str]


def _join(lines: list[Line]) -> str:
    return "\n".join(text for _, text in lines)


def split_lines(lines: list[Line], size: int, overlap: int) -> list[list[Line]]:
    """Fenster an Zeilengrenzen bis 'size' Zeichen; das nächste Fenster überlappt ~overlap."""
    windows: list[list[Line]] = []
    start = 0
    while start < len(lines):
        length = 0
        end = start
        while end < len(lines) and (end == start or length + len(lines[end][1]) + 1 <= size):
            length += len(lines[end][1]) + 1
            end += 1
        window = lines[start:end]
        # Einzelne überlange Zeile hart teilen (gleiche Zeilennummer).
        if len(window) == 1 and len(window[0][1]) > size:
            number, text = window[0]
            step = max(size - overlap, 1)
            windows += [[(number, text[i : i + size])] for i in range(0, len(text), step)]
        else:
            windows.append(window)
        if end >= len(lines):
            break
        # Overlap: so viele Zeilen vom Ende zurückgehen, wie in 'overlap' passen.
        back = end
        carried = 0
        while back - 1 > start and carried + len(lines[back - 1][1]) + 1 <= overlap:
            back -= 1
            carried += len(lines[back][1]) + 1
        start = back if back > start else end
    return windows


def _pack(blocks: list[list[Line]], size: int, overlap: int) -> list[list[Line]]:
    """Packt Blöcke gierig bis 'size'; zu große Blöcke werden nach Zeichen geteilt."""
    result: list[list[Line]] = []
    current: list[Line] = []
    for block in blocks:
        block_len = len(_join(block))
        if block_len > size:
            if current:
                result.append(current)
                current = []
            result += split_lines(block, size, overlap)
            continue
        if current and len(_join(current)) + 1 + block_len > size:
            result.append(current)
            current = []
        current = [*current, *block]
    if current:
        result.append(current)
    return result


def _strip_blank_edges(lines: list[Line]) -> list[Line]:
    start, end = 0, len(lines)
    while start < end and not lines[start][1].strip():
        start += 1
    while end > start and not lines[end - 1][1].strip():
        end -= 1
    return lines[start:end]


def _blocks_by_blank_lines(lines: list[Line], code: bool) -> list[list[Line]]:
    """Teilt an Leerzeilen (und im Code vor Funktionsgrenzen).

    Leerzeilen bleiben am vorangehenden Block hängen, damit aufeinanderfolgende Blöcke
    lückenlos sind und ein gepackter Chunk exakt seinem Zeilenbereich entspricht.
    """
    blocks: list[list[Line]] = []
    current: list[Line] = []
    for line in lines:
        if not line[1].strip():
            if current:
                current.append(line)
            continue
        after_blank = bool(current) and not current[-1][1].strip()
        at_boundary = code and bool(_CODE_BOUNDARY.match(line[1]))
        if current and (after_blank or at_boundary):
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _markdown_sections(lines: list[Line]) -> list[tuple[str | None, list[Line]]]:
    sections: list[tuple[str | None, list[Line]]] = []
    stack: list[tuple[int, str]] = []
    heading: str | None = None
    current: list[Line] = []
    in_fence = False
    for line in lines:
        text = line[1]
        if _FENCE.match(text):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(text)
        if match:
            if current:
                sections.append((heading, current))
            level = len(match.group(1))
            stack = [entry for entry in stack if entry[0] < level]
            stack.append((level, match.group(2)))
            heading = " > ".join(title for _, title in stack)
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((heading, current))
    return sections


def chunk_text(name: str, text: str, size: int, overlap: int) -> list[Chunk]:
    """Zerlegt den Inhalt einer Datei; 'name' bestimmt die Strategie über die Endung."""
    lines: list[Line] = list(enumerate(text.splitlines(), 1))
    suffix = PurePath(name).suffix.lower()
    pieces: list[tuple[str | None, list[Line]]] = []
    if suffix in MARKDOWN_SUFFIXES:
        for heading, section in _markdown_sections(lines):
            section = _strip_blank_edges(section)
            if not section:
                continue
            if len(_join(section)) <= size:
                pieces.append((heading, section))
            else:
                blocks = _blocks_by_blank_lines(section, code=False)
                pieces += [(heading, part) for part in _pack(blocks, size, overlap)]
    elif suffix in CODE_SUFFIXES:
        blocks = _blocks_by_blank_lines(lines, code=True)
        pieces = [(None, part) for part in _pack(blocks, size, overlap)]
    else:
        content = _strip_blank_edges(lines)
        pieces = [(None, part) for part in split_lines(content, size, overlap)] if content else []

    chunks: list[Chunk] = []
    for heading, part in pieces:
        part = _strip_blank_edges(part)
        if not part:
            continue
        chunks.append(
            Chunk(
                ordinal=len(chunks),
                start_line=part[0][0],
                end_line=part[-1][0],
                text=_join(part),
                heading=heading,
            )
        )
    return chunks


def embedding_input(display_path: str, chunk: Chunk) -> str:
    """Text, der eingebettet wird: Dateiname + ggf. Überschrift + Chunk."""
    header = f"Datei: {display_path}\n"
    if chunk.heading:
        header += f"Abschnitt: {chunk.heading}\n"
    return header + chunk.text
