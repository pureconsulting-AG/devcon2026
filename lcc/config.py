"""Laden, Mergen und Validieren der TOML-Config.

Reihenfolge (spätere überschreiben frühere, Key für Key):
Defaults → Benutzer-Config → Projekt-Config → --config → Umgebung → CLI-Flags.
"""

from __future__ import annotations

import difflib
import os
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from lcc import texts

# Eingebaute Defaults. Muss mit config.example.toml übereinstimmen (siehe Tests).
DEFAULTS: dict[str, Any] = {
    "ollama": {
        "base_url": "http://192.168.178.79:11434",
        "timeout_seconds": 300,
        "connect_timeout_seconds": 5,
        "keep_alive": "10m",
    },
    "models": {
        "code": "qwen3.5:9b",
        "chat": "qwen3.5:9b",
        "embed": "bge-m3",
        "rerank": "",
        "options": {"num_ctx": 16384, "temperature": 0.2},
        "thinking": {"enabled": False},
    },
    "agent": {
        "max_steps": 25,
        "confirm_writes": True,
        "confirm_shell": True,
        "shell_allowlist": [
            "ls",
            "cat",
            "rg",
            "grep",
            "git status",
            "git diff",
            "pytest",
            "python -m pytest",
            "python -m py_compile",
        ],
        "shell_timeout_seconds": 120,
        "max_tool_output_chars": 12000,
        "prompt_language": "de",
    },
    "workspace": {
        "root": ".",
        "ignore": [".git", ".venv", "node_modules", "__pycache__", ".lcc/index.db"],
    },
    "rag": {
        "enabled": True,
        "sources": ["./docs", "~/rag-docs"],
        "include": ["*.md", "*.txt", "*.py", "*.abap", "*.toml"],
        "index_path": ".lcc/index.db",
        "chunk_size_chars": 1500,
        "chunk_overlap_chars": 200,
        "top_k": 5,
        "min_score": 0.35,
    },
    "skills": {
        "enabled": True,
        "paths": ["./.lcc/skills", "~/.config/lcc/skills"],
        "preselect": "triggers+embed",
        "max_listed": 8,
        "max_auto_load": 1,
        "auto_load_min_score": 0.55,
        "max_body_chars": 6000,
    },
    "small_model": {
        "mode": "auto",
        "auto_max_params_b": 14,
        "plan_first": True,
        "think_on_plan": True,
        "max_tools_per_step": 5,
        "max_steps_per_plan_step": 8,
        "max_repair_attempts": 2,
        "fuzzy_edit": True,
        "auto_context": True,
        "repo_map_max_chars": 3000,
        "verify_commands": [],
        "temperature": 0.1,
        "escalate_model": "",
    },
    "session": {
        "history_path": "~/.local/state/lcc/history",
        "save_sessions": True,
        "sessions_dir": "~/.local/state/lcc/sessions",
    },
    "ui": {
        "markdown": True,
        "show_tool_calls": True,
    },
}

# Tabellen mit freien Keys (werden 1:1 an Ollama durchgereicht).
FREEFORM_TABLES = frozenset({"models.options"})

# Keys mit Pfaden: '~' und relative Pfade werden relativ zur Quelldatei aufgelöst.
PATH_KEYS = frozenset(
    {
        "workspace.root",
        "rag.sources",
        "rag.index_path",
        "skills.paths",
        "session.history_path",
        "session.sessions_dir",
    }
)

ENUM_KEYS: dict[str, tuple[str, ...]] = {
    "agent.prompt_language": ("de", "en"),
    "skills.preselect": ("off", "triggers", "triggers+embed"),
    "small_model.mode": ("auto", "on", "off"),
}

URL_KEYS = frozenset({"ollama.base_url"})

ENV_VARS: dict[str, str] = {
    "LCC_OLLAMA_URL": "ollama.base_url",
    "LCC_CODE_MODEL": "models.code",
}

USER_CONFIG_PATH = Path("~/.config/lcc/config.toml")
PROJECT_CONFIG_RELPATH = Path(".lcc/config.toml")


class ConfigError(Exception):
    """Ungültige Config (führt zu Exit-Code 2)."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str
    timeout_seconds: float
    connect_timeout_seconds: float
    keep_alive: str


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool


@dataclass(frozen=True)
class ModelsConfig:
    code: str
    chat: str
    embed: str
    rerank: str
    options: Mapping[str, Any]
    thinking: ThinkingConfig


@dataclass(frozen=True)
class AgentConfig:
    max_steps: int
    confirm_writes: bool
    confirm_shell: bool
    shell_allowlist: tuple[str, ...]
    shell_timeout_seconds: float
    max_tool_output_chars: int
    prompt_language: str


@dataclass(frozen=True)
class WorkspaceConfig:
    root: Path
    ignore: tuple[str, ...]


@dataclass(frozen=True)
class RagConfig:
    enabled: bool
    sources: tuple[Path, ...]
    include: tuple[str, ...]
    index_path: Path
    chunk_size_chars: int
    chunk_overlap_chars: int
    top_k: int
    min_score: float


@dataclass(frozen=True)
class SkillsConfig:
    enabled: bool
    paths: tuple[Path, ...]
    preselect: str
    max_listed: int
    max_auto_load: int
    auto_load_min_score: float
    max_body_chars: int


@dataclass(frozen=True)
class SmallModelConfig:
    mode: str
    auto_max_params_b: float
    plan_first: bool
    think_on_plan: bool
    max_tools_per_step: int
    max_steps_per_plan_step: int
    max_repair_attempts: int
    fuzzy_edit: bool
    auto_context: bool
    repo_map_max_chars: int
    verify_commands: tuple[str, ...]
    temperature: float
    escalate_model: str


@dataclass(frozen=True)
class SessionConfig:
    history_path: Path
    save_sessions: bool
    sessions_dir: Path


@dataclass(frozen=True)
class UiConfig:
    markdown: bool
    show_tool_calls: bool


@dataclass(frozen=True)
class Config:
    ollama: OllamaConfig
    models: ModelsConfig
    agent: AgentConfig
    workspace: WorkspaceConfig
    rag: RagConfig
    skills: SkillsConfig
    small_model: SmallModelConfig
    session: SessionConfig
    ui: UiConfig


@dataclass(frozen=True)
class CliOverrides:
    """Werte aus globalen CLI-Flags (höchste Priorität)."""

    url: str | None = None
    model: str | None = None


@dataclass
class LoadedConfig:
    """Ergebnis von load_config: Config plus Herkunft jedes Werts."""

    config: Config
    values: dict[str, Any]
    sources: dict[str, str]
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _iter_leaves(table: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    for key, value in table.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and dotted not in FREEFORM_TABLES:
            yield from _iter_leaves(value, f"{dotted}.")
        else:
            yield dotted, value


def _type_name(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "table"
    return type(value).__name__


# Erwarteter Typ je Key, abgeleitet aus den Defaults. Floats akzeptieren auch ints.
_LEAF_TYPES: dict[str, str] = {key: _type_name(value) for key, value in _iter_leaves(DEFAULTS)}
_LEAF_TYPES["ollama.timeout_seconds"] = "float"
_LEAF_TYPES["ollama.connect_timeout_seconds"] = "float"
_LEAF_TYPES["agent.shell_timeout_seconds"] = "float"
_LEAF_TYPES["small_model.auto_max_params_b"] = "float"

_TABLES: frozenset[str] = frozenset(
    key.rsplit(".", n)[0] for key in _LEAF_TYPES for n in range(1, key.count(".") + 1)
)

_EXPECTED_LABEL = {
    "bool": "bool (true/false)",
    "int": "int",
    "float": "Zahl",
    "string": "string",
    "list": "Liste von strings",
    "table": "Tabelle",
}


def _check_type(key: str, value: Any, source: str) -> Any:
    expected = _LEAF_TYPES[key]
    ok: bool
    if expected == "bool":
        ok = isinstance(value, bool)
    elif expected == "int":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "float":
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        if ok:
            value = float(value)
    elif expected == "string":
        ok = isinstance(value, str)
    elif expected == "list":
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif expected == "table":
        ok = isinstance(value, dict)
    else:  # pragma: no cover - Schema-Fehler
        raise AssertionError(expected)
    if not ok:
        raise ConfigError(
            texts.CONFIG_TYPE_ERROR.format(
                source=source,
                key=key,
                expected=_EXPECTED_LABEL[expected],
                actual=_type_name(value),
            )
        )
    if key in ENUM_KEYS and value not in ENUM_KEYS[key]:
        raise ConfigError(
            texts.CONFIG_ENUM_ERROR.format(
                source=source, key=key, allowed=", ".join(ENUM_KEYS[key]), value=value
            )
        )
    if key in URL_KEYS:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ConfigError(texts.CONFIG_URL_ERROR.format(source=source, key=key, value=value))
        value = value.rstrip("/")
    return value


def _resolve_path(value: str, base_dir: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return Path(os.path.normpath(path))


def _resolve_paths(key: str, value: Any, base_dir: Path) -> Any:
    if key not in PATH_KEYS:
        return value
    if isinstance(value, list):
        return [_resolve_path(item, base_dir) for item in value]
    return _resolve_path(value, base_dir)


def _suggest(key: str) -> str:
    candidates = [*_LEAF_TYPES, *_TABLES]
    matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
    if not matches:
        # Tippfehler im letzten Teil: nur mit Geschwistern vergleichen.
        parent, _, leaf = key.rpartition(".")
        siblings = [c.rpartition(".")[2] for c in candidates if c.rpartition(".")[0] == parent]
        leaf_matches = difflib.get_close_matches(leaf, siblings, n=1, cutoff=0.6)
        matches = [f"{parent}.{m}" if parent else m for m in leaf_matches]
    return texts.CONFIG_UNKNOWN_KEY_HINT.format(suggestion=matches[0]) if matches else ""


def _flatten_layer(
    table: Mapping[str, Any],
    source: str,
    base_dir: Path,
    warnings: list[str],
    prefix: str = "",
) -> dict[str, Any]:
    """Wandelt eine TOML-Tabelle in validierte 'a.b.c'-Keys um."""
    flat: dict[str, Any] = {}
    for key, value in table.items():
        dotted = f"{prefix}{key}"
        if dotted in FREEFORM_TABLES:
            if not isinstance(value, dict):
                raise ConfigError(
                    texts.CONFIG_TYPE_ERROR.format(
                        source=source,
                        key=dotted,
                        expected=_EXPECTED_LABEL["table"],
                        actual=_type_name(value),
                    )
                )
            for sub_key, sub_value in value.items():
                flat[f"{dotted}.{sub_key}"] = sub_value
        elif dotted in _TABLES:
            if not isinstance(value, dict):
                raise ConfigError(
                    texts.CONFIG_TYPE_ERROR.format(
                        source=source,
                        key=dotted,
                        expected=_EXPECTED_LABEL["table"],
                        actual=_type_name(value),
                    )
                )
            flat.update(_flatten_layer(value, source, base_dir, warnings, f"{dotted}."))
        elif dotted in _LEAF_TYPES:
            checked = _check_type(dotted, value, source)
            flat[dotted] = _resolve_paths(dotted, checked, base_dir)
        else:
            warnings.append(
                texts.CONFIG_UNKNOWN_KEY.format(key=dotted, source=source) + _suggest(dotted)
            )
    return flat


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------


def find_project_root(cwd: Path) -> Path:
    """Git-Root oberhalb von cwd, sonst cwd selbst."""
    cwd = cwd.resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".git").exists():
            return candidate
    return cwd


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(texts.CONFIG_TOML_ERROR.format(path=path, error=exc)) from exc
    except OSError as exc:
        raise ConfigError(texts.CONFIG_FILE_MISSING.format(path=path)) from exc


def load_config(
    *,
    config_path: Path | None = None,
    overrides: CliOverrides | None = None,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    user_config_path: Path | None = None,
) -> LoadedConfig:
    """Lädt alle Ebenen, merged Key für Key und baut die Config.

    Wirft ConfigError bei ungültigen Werten; unbekannte Keys landen in .warnings.
    """
    cwd = (cwd or Path.cwd()).resolve()
    env = os.environ if env is None else env
    overrides = overrides or CliOverrides()
    project_root = find_project_root(cwd)
    warnings: list[str] = []

    values: dict[str, Any] = {}
    sources: dict[str, str] = {}

    def apply(layer: dict[str, Any], source: str) -> None:
        for key, value in layer.items():
            values[key] = value
            sources[key] = source

    apply(
        _flatten_layer(DEFAULTS, texts.CONFIG_SOURCE_DEFAULT, project_root, warnings),
        texts.CONFIG_SOURCE_DEFAULT,
    )

    files: list[Path] = []
    user_path = (user_config_path or USER_CONFIG_PATH).expanduser()
    candidates: list[tuple[Path, bool]] = [
        (user_path, False),
        (project_root / PROJECT_CONFIG_RELPATH, False),
    ]
    if config_path is not None:
        candidates.append((config_path.expanduser().resolve(), True))
    for path, required in candidates:
        if not path.is_file():
            if required:
                raise ConfigError(texts.CONFIG_FILE_MISSING.format(path=path))
            continue
        source = str(path)
        apply(_flatten_layer(_read_toml(path), source, path.parent, warnings), source)
        files.append(path)

    for name, key in ENV_VARS.items():
        if env.get(name):
            source = texts.CONFIG_SOURCE_ENV.format(name=name)
            apply({key: _check_type(key, env[name], source)}, source)

    cli_layer: list[tuple[str, str, str | None]] = [
        ("ollama.base_url", "--url", overrides.url),
        ("models.code", "--model", overrides.model),
        ("models.chat", "--model", overrides.model),
    ]
    for key, flag, cli_value in cli_layer:
        if cli_value is not None:
            source = texts.CONFIG_SOURCE_CLI.format(flag=flag)
            apply({key: _check_type(key, cli_value, source)}, source)

    return LoadedConfig(
        config=build_config(values),
        values=values,
        sources=sources,
        files=files,
        warnings=warnings,
    )


def build_config(values: Mapping[str, Any]) -> Config:
    """Baut die Dataclasses aus den flachen, bereits validierten Werten."""

    def get(key: str) -> Any:
        value = values[key]
        return tuple(value) if isinstance(value, list) else value

    def section[T](cls: type[T], prefix: str, **extra: Any) -> T:
        names = cls.__dataclass_fields__  # type: ignore[attr-defined]
        kwargs = {name: get(f"{prefix}.{name}") for name in names if name not in extra}
        return cls(**kwargs, **extra)

    options = {
        key.removeprefix("models.options."): value
        for key, value in values.items()
        if key.startswith("models.options.")
    }
    return Config(
        ollama=section(OllamaConfig, "ollama"),
        models=section(
            ModelsConfig,
            "models",
            options=options,
            thinking=section(ThinkingConfig, "models.thinking"),
        ),
        agent=section(AgentConfig, "agent"),
        workspace=section(WorkspaceConfig, "workspace"),
        rag=section(RagConfig, "rag"),
        skills=section(SkillsConfig, "skills"),
        small_model=section(SmallModelConfig, "small_model"),
        session=section(SessionConfig, "session"),
        ui=section(UiConfig, "ui"),
    )


def default_config(cwd: Path | None = None) -> Config:
    """Nur die eingebauten Defaults (für Tests und als Fallback)."""
    root = find_project_root((cwd or Path.cwd()).resolve())
    values = _flatten_layer(DEFAULTS, texts.CONFIG_SOURCE_DEFAULT, root, [])
    return build_config(values)


# ---------------------------------------------------------------------------
# Anzeige und Init
# ---------------------------------------------------------------------------


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, Path):
        return _toml_value(str(value))
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def format_effective(loaded: LoadedConfig) -> str:
    """Effektive Config als TOML, jeder Wert mit Quelle als Kommentar."""
    lines: list[str] = []
    current_table = ""
    for key, value in loaded.values.items():
        table, _, leaf = key.rpartition(".")
        if table != current_table:
            if lines:
                lines.append("")
            lines.append(f"[{table}]")
            current_table = table
        lines.append(f"{leaf} = {_toml_value(value)}  # {loaded.sources[key]}")
    return "\n".join(lines) + "\n"


def effective_as_json(loaded: LoadedConfig) -> dict[str, dict[str, Any]]:
    """Effektive Config für --json: {key: {value, source}}."""
    result: dict[str, dict[str, Any]] = {}
    for key, value in loaded.values.items():
        if isinstance(value, Path):
            value = str(value)
        elif isinstance(value, list):
            value = [str(item) if isinstance(item, Path) else item for item in value]
        result[key] = {"value": value, "source": loaded.sources[key]}
    return result


def example_config_text() -> str:
    """Inhalt von config.example.toml (Paketdaten, Repo-Root oder aus den Defaults)."""
    package_dir = Path(__file__).resolve().parent
    for candidate in (
        package_dir / "config.example.toml",
        package_dir.parent / "config.example.toml",
    ):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    import tomli_w

    return tomli_w.dumps(DEFAULTS)


def init_user_config(target: Path | None = None, *, force: bool = False) -> Path:
    """Schreibt die Beispiel-Config. Überschreibt nur mit force=True."""
    path = (target or USER_CONFIG_PATH).expanduser()
    if path.exists() and not force:
        raise FileExistsError(texts.CONFIG_INIT_EXISTS.format(path=path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_config_text(), encoding="utf-8")
    return path
