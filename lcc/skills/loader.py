"""Findet und parst Mini-Skills (Ordner mit SKILL.md).

Frontmatter: eigener, einfacher 'key: value'-Parser (keine YAML-Abhängigkeit).
Listen sind kommagetrennt, optional in [ … ].
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from lcc import texts

SKILL_FILE = "SKILL.md"
KNOWN_KEYS = frozenset(
    {"name", "description", "triggers", "tools", "checks", "context_files", "model", "version"}
)
REQUIRED_KEYS = ("name", "description")

Source = Literal["project", "user"]


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    source: Source
    triggers: tuple[str, ...] = ()
    tools: tuple[str, ...] | None = None
    checks: tuple[str, ...] = ()
    context_files: tuple[str, ...] = ()
    model: str | None = None
    version: int | None = None
    frontmatter: dict[str, str] = field(default_factory=dict)

    @property
    def directory(self) -> Path:
        return self.path.parent


@dataclass
class LoadResult:
    skills: dict[str, Skill] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    # (verdrängter Skill, gewinnender Skill) bei doppelten Namen
    shadowed: list[tuple[Skill, Skill]] = field(default_factory=list)
    # Alle gültig geparsten Skills (auch verdrängte) – für den Linter
    all_skills: list[Skill] = field(default_factory=list)


class SkillParseError(Exception):
    pass


def parse_list(value: str) -> tuple[str, ...]:
    """'a, b' oder '[a, "b"]' → ('a', 'b')."""
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = (_unquote(item.strip()) for item in value.split(","))
    return tuple(item for item in items if item)


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def split_frontmatter(text: str) -> tuple[list[tuple[int, str]], str]:
    """Trennt Frontmatter-Zeilen (mit Zeilennummer) und Body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillParseError(texts.SKILL_NO_FRONTMATTER)
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            front = [(number, lines[number - 1]) for number in range(2, index + 1)]
            body = "\n".join(lines[index + 1 :]).strip("\n")
            return front, body
    raise SkillParseError(texts.SKILL_UNCLOSED_FRONTMATTER)


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, list[str]]:
    """Liefert (Felder, Body, Warnungen). Wirft SkillParseError ohne Frontmatter."""
    front, body = split_frontmatter(text)
    fields: dict[str, str] = {}
    warnings: list[str] = []
    for number, line in front:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, value = stripped.partition(":")
        if not sep:
            warnings.append(texts.SKILL_BAD_LINE.format(line=number, text=stripped))
            continue
        key = key.strip().lower()
        if key not in KNOWN_KEYS:
            warnings.append(texts.SKILL_UNKNOWN_KEY.format(key=key, line=number))
            continue
        fields[key] = _unquote(value.strip())
    return fields, body, warnings


def load_skill_file(path: Path, source: Source) -> tuple[Skill | None, list[str]]:
    """Parst eine SKILL.md; fehlen Pflichtfelder, wird der Skill ignoriert (+ Warnung)."""
    try:
        text = path.read_text(encoding="utf-8")
        fields, body, warnings = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError, SkillParseError) as exc:
        return None, [texts.SKILL_IGNORED.format(path=path, reason=exc)]
    warnings = [texts.SKILL_WARNING.format(path=path, warning=w) for w in warnings]
    missing = [key for key in REQUIRED_KEYS if not fields.get(key)]
    if missing:
        reason = texts.SKILL_MISSING_FIELDS.format(fields=", ".join(missing))
        return None, [*warnings, texts.SKILL_IGNORED.format(path=path, reason=reason)]

    version: int | None = None
    if fields.get("version"):
        try:
            version = int(fields["version"])
        except ValueError:
            warnings.append(
                texts.SKILL_WARNING.format(
                    path=path, warning=texts.SKILL_BAD_VERSION.format(value=fields["version"])
                )
            )
    skill = Skill(
        name=fields["name"],
        description=fields["description"],
        body=body,
        path=path,
        source=source,
        triggers=parse_list(fields.get("triggers", "")),
        tools=parse_list(fields["tools"]) if fields.get("tools") else None,
        checks=parse_list(fields.get("checks", "")),
        context_files=parse_list(fields.get("context_files", "")),
        model=fields.get("model") or None,
        version=version,
        frontmatter=fields,
    )
    return skill, warnings


def classify_source(path: Path, project_root: Path) -> Source:
    return "project" if path.resolve().is_relative_to(project_root.resolve()) else "user"


def load_skills(paths: Sequence[Path], project_root: Path) -> LoadResult:
    """Liest alle Skill-Ordner. Bei doppelten Namen gewinnt der Projekt-Skill."""
    result = LoadResult()
    ordered = sorted(paths, key=lambda p: classify_source(p, project_root) != "project")
    for base in ordered:
        if not base.is_dir():
            continue
        source = classify_source(base, project_root)
        for skill_file in sorted(base.glob(f"*/{SKILL_FILE}")):
            skill, warnings = load_skill_file(skill_file, source)
            result.warnings += warnings
            if skill is None:
                continue
            result.all_skills.append(skill)
            existing = result.skills.get(skill.name)
            if existing is None:
                result.skills[skill.name] = skill
            else:
                result.shadowed.append((skill, existing))
    return result
