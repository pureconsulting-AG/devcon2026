"""Skills zur Laufzeit: Vorauswahl + Auto-Load je Auftrag, load_skill, aktive Einschränkungen.

Solange ein Skill aktiv ist, gilt seine tools-Liste (Schnittmenge) und ggf. sein Modell;
der Skill-Ordner ist zusätzlich zum Workspace nur lesbar.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from lcc import texts
from lcc.agent.prompts import SkillListing
from lcc.agent.tools import ToolContext, ToolError, read_text, truncate_middle
from lcc.agent.verify import CheckOutcome, changed_files, run_checks
from lcc.config import Config
from lcc.ollama_client import Message, OllamaClient, OllamaError
from lcc.rag.store import Store
from lcc.skills.loader import LoadResult, Skill, load_skills
from lcc.skills.selector import SkillMatch, SkillSelector

CONTEXT_FILE_MAX_CHARS = 3000
CONTEXT_FILES_MAX = 5


def discover(config: Config) -> LoadResult:
    """Alle Skills aus skills.paths (Projekt vor Benutzer)."""
    return load_skills(config.skills.paths, config.workspace.root)


def loader_messages(result: LoadResult, verbose: bool) -> list[str]:
    """Warnungen des Loaders; verdeckte Skills nur mit -v."""
    messages = list(result.warnings)
    if verbose:
        messages += [
            texts.SKILL_SHADOWED.format(name=loser.name, loser=loser.path, winner=winner.path)
            for loser, winner in result.shadowed
        ]
    return messages


def resolve_model(config: Config, value: str | None) -> str | None:
    if not value:
        return None
    return {"code": config.models.code, "chat": config.models.chat}.get(value, value)


@dataclass
class SkillSession:
    """Verfügbare und geladene Skills einer Session (REPL) bzw. eines Laufs."""

    config: Config
    available: dict[str, Skill]
    loaded: list[Skill] = field(default_factory=list)

    def is_loaded(self, name: str) -> bool:
        return any(skill.name == name for skill in self.loaded)

    def load(self, name: str, ctx: ToolContext) -> str:
        """Aktiviert einen Skill und liefert Body + Ordner + Kontextdateien."""
        skill = self.available.get(name.strip())
        if skill is None:
            raise ToolError(
                texts.SKILL_UNKNOWN.format(name=name, available=", ".join(sorted(self.available)))
            )
        if self.is_loaded(skill.name):
            return texts.SKILL_ALREADY_LOADED.format(name=skill.name)
        self.loaded.append(skill)
        ctx.sandbox.add_read_root(skill.directory)
        return self.content(skill, ctx)

    def content(self, skill: Skill, ctx: ToolContext) -> str:
        header = texts.SKILL_CONTENT_HEADER.format(name=skill.name, directory=skill.directory)
        parts = [header, skill.body]
        files = self._context_files(skill, ctx)
        if files:
            parts.append(texts.SKILL_CONTEXT_FILES)
            for rel, text in files:
                parts.append(f"--- {rel} ---\n{truncate_middle(text, CONTEXT_FILE_MAX_CHARS)}")
        return "\n\n".join(part for part in parts if part)

    def _context_files(self, skill: Skill, ctx: ToolContext) -> list[tuple[str, str]]:
        root = ctx.sandbox.root
        found: list[tuple[str, str]] = []
        for pattern in skill.context_files:
            for path in sorted(root.glob(pattern)) if pattern else []:
                if len(found) >= CONTEXT_FILES_MAX:
                    return found
                try:
                    resolved = ctx.sandbox.resolve_read(path)
                    if resolved.is_file() and not ctx.sandbox.is_ignored(resolved):
                        found.append((ctx.sandbox.relpath(resolved), read_text(resolved)))
                except Exception:  # Kontextdateien sind optional
                    continue
        return found

    def allowed_tools(self, base: Sequence[str]) -> list[str]:
        """Schnittmenge mit den tools-Listen aktiver Skills (Vereinigung, falls mehrere)."""
        restrictions = [skill.tools for skill in self.loaded if skill.tools is not None]
        if not restrictions:
            return list(base)
        allowed = {tool for tools in restrictions for tool in tools}
        return [name for name in base if name in allowed]

    def model(self) -> str | None:
        """Modell des zuletzt geladenen Skills mit model-Angabe."""
        for skill in reversed(self.loaded):
            resolved = resolve_model(self.config, skill.model)
            if resolved:
                return resolved
        return None

    def checks(self) -> list[str]:
        commands: dict[str, None] = {}
        for skill in self.loaded:
            for command in skill.checks:
                commands[command] = None
        return list(commands)


@dataclass
class PreparedTask:
    listing: list[SkillListing]
    preface: list[Message]
    matches: list[SkillMatch]
    auto_loaded: list[str]


def prepare_task(
    session: SkillSession,
    ctx: ToolContext,
    task: str,
    client: OllamaClient | None,
    on_info: Callable[[str], None] | None = None,
) -> PreparedTask:
    """Vorauswahl für den Systemprompt + Auto-Load (Body als Systemnachricht vor dem Auftrag)."""
    config = session.config
    store = skill_cache(config)
    task_vector = None
    if ctx.rag is not None and config.skills.preselect == "triggers+embed":
        try:
            # Gleicher Embedding-Aufruf wie für die RAG-Suche zum Auftrag (wird gecacht).
            task_vector = ctx.rag.query_vector(task)
        except OllamaError:
            task_vector = None
    try:
        selector = SkillSelector(
            config, list(session.available.values()), client, store, task_vector=task_vector
        )
        matches = selector.select(task)
    finally:
        if store is not None:
            store.close()
    listing = [SkillListing(m.skill.name, m.skill.description) for m in matches]
    preface: list[Message] = []
    auto_loaded: list[str] = []
    for match in matches:
        if not match.auto_load or session.is_loaded(match.skill.name):
            continue
        content = session.load(match.skill.name, ctx)
        preface.append({"role": "system", "content": content})
        auto_loaded.append(match.skill.name)
        if on_info is not None:
            on_info(texts.SKILL_LOADED.format(name=match.skill.name))
    return PreparedTask(listing, preface, matches, auto_loaded)


def skill_cache(config: Config) -> Store | None:
    """Cache für Beschreibungs-Embeddings in der RAG-DB (nur wenn Embeddings genutzt werden)."""
    if config.skills.preselect != "triggers+embed" or not config.models.embed:
        return None
    try:
        return Store(config.rag.index_path)
    except Exception:  # Cache ist optional (z. B. schreibgeschützt)
        return None


def run_skill_checks(
    session: SkillSession,
    ctx: ToolContext,
    changes_before: int,
    on_outcome: Callable[[CheckOutcome], None] | None = None,
    on_start: Callable[[str], None] | None = None,
) -> list[CheckOutcome]:
    """Checks der aktiven Skills – nur, wenn in diesem Lauf Dateien geändert wurden."""
    commands = session.checks()
    changed = changed_files(ctx.sandbox, changes_before)
    if not commands or not changed:
        return []
    return run_checks(ctx, commands, changed, on_outcome, on_start)
