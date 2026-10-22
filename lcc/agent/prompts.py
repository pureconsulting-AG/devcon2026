"""Systemprompts (normal + kompakt), Deutsch oder Englisch über agent.prompt_language."""

from __future__ import annotations

import platform
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

AGENT_MD_RELPATH = Path(".lcc/AGENT.md")
AGENT_MD_MAX_CHARS = 4000


@dataclass(frozen=True)
class SkillListing:
    name: str
    description: str


_ROLE = {
    "de": (
        "Du bist lcc, ein Coding-Agent im Terminal. Du arbeitest im Projekt des Nutzers "
        "und nutzt Tools, um Dateien zu lesen und zu durchsuchen."
    ),
    "en": (
        "You are lcc, a coding agent in the terminal. You work in the user's project "
        "and use tools to read and search files."
    ),
}

_RULES = {
    "de": [
        "Lies relevante Dateien, bevor du Aussagen über den Code machst. Rate nicht.",
        "Nutze Pfade relativ zum Arbeitsverzeichnis.",
        "Rufe Tools nur auf, wenn sie nötig sind; wiederhole keinen identischen Aufruf.",
        "Wenn ein Tool einen Fehler meldet, korrigiere den Aufruf statt aufzugeben.",
        "Antworte am Ende knapp auf Deutsch und nenne betroffene Dateien mit Zeilennummern.",
    ],
    "en": [
        "Read relevant files before making claims about the code. Do not guess.",
        "Use paths relative to the working directory.",
        "Call tools only when needed; never repeat an identical call.",
        "If a tool reports an error, fix the call instead of giving up.",
        "Finish with a short answer and cite affected files with line numbers.",
    ],
}

_COMPACT_RULES = {
    "de": [
        "Lies Dateien, bevor du sie bewertest.",
        "Ein Tool-Aufruf pro Schritt, Pfade relativ.",
        "Bei Tool-Fehler: Aufruf korrigieren.",
        "Kurz antworten.",
    ],
    "en": [
        "Read files before judging them.",
        "One tool call per step, relative paths.",
        "On tool error: fix the call.",
        "Answer briefly.",
    ],
}

_LABELS = {
    "de": {
        "rules": "Regeln",
        "env": "Umgebung",
        "cwd": "Arbeitsverzeichnis",
        "os": "Betriebssystem",
        "tools": "Verfügbare Tools",
        "skills": "Skills (bei Bedarf mit load_skill laden)",
        "rag": ("Für Fragen zur Projektdokumentation nutze rag_search und nenne Quellen als [n]."),
        "project": "Projektregeln (.lcc/AGENT.md)",
        "example": "Beispiel-Aufruf",
    },
    "en": {
        "rules": "Rules",
        "env": "Environment",
        "cwd": "Working directory",
        "os": "OS",
        "tools": "Available tools",
        "skills": "Skills (load with load_skill when relevant)",
        "rag": "For questions about project docs use rag_search and cite sources as [n].",
        "project": "Project rules (.lcc/AGENT.md)",
        "example": "Example call",
    },
}


_TEXT_TOOLS = {
    "de": (
        "Tools rufst du auf, indem du NUR einen JSON-Block ausgibst, z. B.\n"
        '{"tool": "read_file", "arguments": {"path": "main.py"}}\n'
        "Danach bekommst du das Ergebnis. Verfügbare Tools:"
    ),
    "en": (
        "Call a tool by replying with ONLY a JSON block, e.g.\n"
        '{"tool": "read_file", "arguments": {"path": "main.py"}}\n'
        "You will then receive the result. Available tools:"
    ),
}


def load_agent_md(workspace_root: Path) -> str | None:
    """Projektspezifische Regeln aus ./.lcc/AGENT.md (gekürzt)."""
    path = workspace_root / AGENT_MD_RELPATH
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[:AGENT_MD_MAX_CHARS] or None


def build_system_prompt(
    *,
    language: str,
    workspace_root: Path,
    tool_names: Sequence[str],
    rag_enabled: bool = False,
    skills: Sequence[SkillListing] = (),
    agent_md: str | None = None,
    compact: bool = False,
    example_call: str | None = None,
    tool_text: str | None = None,
) -> str:
    """Setzt den Systemprompt zusammen (Rolle, Regeln, Umgebung, Tools, Skills, AGENT.md).

    Skills erscheinen nur als Name + eine Zeile Beschreibung, nie mit Body.
    """
    lang = language if language in _ROLE else "de"
    labels = _LABELS[lang]
    rules = _COMPACT_RULES[lang] if compact else _RULES[lang]

    parts = [_ROLE[lang]]
    parts.append(f"{labels['rules']}:\n" + "\n".join(f"{i}. {r}" for i, r in enumerate(rules, 1)))
    parts.append(
        f"{labels['env']}:\n- {labels['cwd']}: {workspace_root}\n"
        f"- {labels['os']}: {platform.system()}"
    )
    if tool_text:
        parts.append(_TEXT_TOOLS[lang] + "\n" + tool_text)
    elif tool_names:
        parts.append(f"{labels['tools']}: {', '.join(tool_names)}")
    if compact and example_call:
        parts.append(f"{labels['example']}: {example_call}")
    if skills:
        lines = "\n".join(f"- {s.name}: {s.description}" for s in skills)
        parts.append(f"{labels['skills']}:\n{lines}")
    if rag_enabled and "rag_search" in tool_names:
        parts.append(labels["rag"])
    if agent_md:
        parts.append(f"{labels['project']}:\n{agent_md}")
    return "\n\n".join(parts)
