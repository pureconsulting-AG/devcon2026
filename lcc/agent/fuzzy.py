"""Fuzzy-Abgleich für edit_file im Kleinmodell-Modus.

Kleine Modelle treffen Einrückung und Leerzeichen oft nicht exakt. Verglichen wird daher
zeilenweise mit normalisiertem Whitespace; passt genau eine Stelle, wird sie ersetzt und die
Einrückung von new_str an die Datei angepasst.
"""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from dataclasses import dataclass


def normalize_line(line: str) -> str:
    """Einrückung, Leerzeichen am Ende und mehrfache Leerzeichen spielen keine Rolle."""
    return " ".join(line.split())


def _strip_blank_edges(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def needle_lines(old: str) -> list[str]:
    return _strip_blank_edges(old.replace("\r\n", "\n").split("\n"))


def find_fuzzy(text_lines: Sequence[str], old: str) -> list[int]:
    """Startindizes (0-basiert) aller Fenster, die normalisiert mit old übereinstimmen."""
    needle = [normalize_line(line) for line in needle_lines(old)]
    if not needle or not any(needle):
        return []
    size = len(needle)
    normalized = [normalize_line(line) for line in text_lines]
    return [i for i in range(len(normalized) - size + 1) if normalized[i : i + size] == needle]


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def reindent(new: str, file_first_line: str) -> str:
    """Verankert die erste Zeile von new an der Einrückung der Datei.

    Die relative Einrückung innerhalb von new bleibt erhalten. Die Einrückung von old zählt
    nicht – kleine Modelle vertippen sich dort oft (z. B. ein Leerzeichen zu viel), während
    new in sich stimmig ist. Nutzt die Datei keine Tabs, werden Tabs zu 4 Leerzeichen;
    Leerzeichen am Zeilenende fallen weg.
    """
    file_indent = _indent(file_first_line)
    use_tabs = "\t" in file_indent

    def clean(line: str) -> str:
        return (line if use_tabs else line.expandtabs(4)).rstrip()

    new_lines = [clean(line) for line in new.replace("\r\n", "\n").split("\n")]
    first = next((line for line in new_lines if line.strip()), None)
    if first is None:
        return "\n".join(new_lines)
    base = _indent(first)
    result: list[str] = []
    for line in new_lines:
        if not line.strip():
            result.append("")
        elif line.startswith(base):
            result.append(file_indent + line[len(base) :])
        else:
            result.append(file_indent + line.lstrip())
    return "\n".join(result)


@dataclass(frozen=True)
class Location:
    start_line: int  # 1-basiert
    end_line: int
    ratio: float
    snippet: str


def similar_locations(text_lines: Sequence[str], old: str, count: int = 3) -> list[Location]:
    """Die ähnlichsten Stellen zu old (difflib), mit Zeilennummern – für Fehlermeldungen."""
    needle = needle_lines(old)
    if not needle or not text_lines:
        return []
    size = min(len(needle), len(text_lines))
    target = "\n".join(normalize_line(line) for line in needle)
    scored: list[tuple[float, int]] = []
    for start in range(len(text_lines) - size + 1):
        window = "\n".join(normalize_line(line) for line in text_lines[start : start + size])
        ratio = difflib.SequenceMatcher(None, target, window, autojunk=False).ratio()
        scored.append((ratio, start))
    scored.sort(key=lambda item: (-item[0], item[1]))
    locations: list[Location] = []
    for ratio, start in scored:
        if any(abs(start + 1 - loc.start_line) < size for loc in locations):
            continue  # überlappende Fenster nicht doppelt zeigen
        snippet = "\n".join(
            f"{number}| {text_lines[number - 1]}" for number in range(start + 1, start + size + 1)
        )
        locations.append(Location(start + 1, start + size, ratio, snippet))
        if len(locations) == count:
            break
    return locations


def format_locations(locations: Sequence[Location], header: str, line_template: str) -> str:
    parts = [header]
    for loc in locations:
        parts.append(
            line_template.format(start=loc.start_line, end=loc.end_line, ratio=loc.ratio)
            + "\n"
            + loc.snippet
        )
    return "\n".join(parts)
