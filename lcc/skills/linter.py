"""'lcc skills check': prüft Frontmatter, Längen, doppelte Namen und überlappende Trigger."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lcc import texts
from lcc.agent.tools import default_registry
from lcc.skills.loader import SKILL_FILE, Skill, load_skill_file, load_skills
from lcc.skills.scaffold import NAME_PATTERN

Severity = Literal["error", "warning"]

MAX_DESCRIPTION_CHARS = 200
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
KNOWN_PLACEHOLDERS = frozenset({"changed", "test_file"})


@dataclass(frozen=True)
class Finding:
    severity: Severity
    path: Path
    message: str


def lint_skill(skill: Skill, max_body_chars: int) -> list[Finding]:
    findings: list[Finding] = []

    def add(severity: Severity, message: str) -> None:
        findings.append(Finding(severity, skill.path, message))

    if not NAME_PATTERN.match(skill.name):
        add("error", texts.LINT_NAME_CASE.format(name=skill.name))
    if skill.name != skill.directory.name:
        add("error", texts.LINT_NAME_FOLDER.format(name=skill.name, folder=skill.directory.name))
    if len(skill.description) > MAX_DESCRIPTION_CHARS:
        add(
            "warning",
            texts.LINT_DESCRIPTION_LONG.format(
                length=len(skill.description), limit=MAX_DESCRIPTION_CHARS
            ),
        )
    if not skill.body.strip():
        add("error", texts.LINT_BODY_EMPTY)
    elif len(skill.body) > max_body_chars:
        add("warning", texts.LINT_BODY_LONG.format(length=len(skill.body), limit=max_body_chars))
    if not skill.triggers:
        add("warning", texts.LINT_NO_TRIGGERS)
    known_tools = set(default_registry().names()) | {"replace_lines"}
    for tool in skill.tools or ():
        if tool not in known_tools:
            add("error", texts.LINT_UNKNOWN_TOOL.format(tool=tool))
    for command in skill.checks:
        for placeholder in _PLACEHOLDER.findall(command):
            if placeholder not in KNOWN_PLACEHOLDERS:
                add("error", texts.LINT_UNKNOWN_PLACEHOLDER.format(placeholder=placeholder))
    if skill.model and skill.model not in ("code", "chat") and ":" not in skill.model:
        add("warning", texts.LINT_MODEL_HINT.format(model=skill.model))
    return findings


def lint_overlaps(skills: Sequence[Skill]) -> list[Finding]:
    """Gleicher Trigger in mehreren Skills → Warnung (Vorauswahl wird mehrdeutig)."""
    owners: dict[str, list[Skill]] = {}
    for skill in skills:
        for trigger in {t.lower() for t in skill.triggers}:
            owners.setdefault(trigger, []).append(skill)
    findings: list[Finding] = []
    for trigger, group in sorted(owners.items()):
        if len(group) > 1:
            names = ", ".join(sorted(s.name for s in group))
            findings.append(
                Finding(
                    "warning",
                    group[0].path,
                    texts.LINT_TRIGGER_OVERLAP.format(trigger=trigger, skills=names),
                )
            )
    return findings


def lint_paths(paths: Sequence[Path], project_root: Path, max_body_chars: int) -> list[Finding]:
    """Alle Skills prüfen – auch solche, die der Loader wegen Fehlern ignoriert."""
    findings: list[Finding] = []
    result = load_skills(paths, project_root)
    # Parserfehler und ignorierte Skills (Loader-Warnungen) erneut je Datei erfassen
    for base in paths:
        if not base.is_dir():
            continue
        for skill_file in sorted(base.glob(f"*/{SKILL_FILE}")):
            skill, warnings = load_skill_file(skill_file, "project")
            severity: Severity = "error" if skill is None else "warning"
            for warning in warnings:
                is_ignore = skill is None and warning == warnings[-1]
                findings.append(Finding(severity if is_ignore else "warning", skill_file, warning))
    for skill in result.all_skills:
        findings += lint_skill(skill, max_body_chars)
    seen: dict[tuple[str, str], Skill] = {}
    for skill in result.all_skills:
        key = (skill.name, skill.source)
        if key in seen:
            findings.append(
                Finding(
                    "error",
                    skill.path,
                    texts.LINT_DUPLICATE.format(name=skill.name, other=seen[key].path),
                )
            )
        else:
            seen[key] = skill
    for loser, winner in result.shadowed:
        if loser.source != winner.source:
            findings.append(
                Finding(
                    "warning",
                    loser.path,
                    texts.SKILL_SHADOWED.format(
                        name=loser.name, loser=loser.path, winner=winner.path
                    ),
                )
            )
    findings += lint_overlaps(list(result.skills.values()))
    return findings
