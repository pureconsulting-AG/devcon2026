from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from lcc.config import (
    DEFAULTS,
    CliOverrides,
    ConfigError,
    LoadedConfig,
    default_config,
    effective_as_json,
    example_config_text,
    find_project_root,
    format_effective,
    init_user_config,
    load_config,
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


@pytest.fixture
def user_config(tmp_path: Path) -> Path:
    return tmp_path / "home" / ".config" / "lcc" / "config.toml"


def write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def load(
    project: Path,
    user_config: Path,
    *,
    env: dict[str, str] | None = None,
    config_path: Path | None = None,
    overrides: CliOverrides | None = None,
    cwd: Path | None = None,
) -> LoadedConfig:
    return load_config(
        cwd=cwd or project,
        env=env or {},
        user_config_path=user_config,
        config_path=config_path,
        overrides=overrides,
    )


def test_defaults_without_files(project: Path, user_config: Path) -> None:
    loaded = load(project, user_config)
    assert loaded.files == []
    assert loaded.warnings == []
    assert loaded.config.ollama.base_url == "http://192.168.178.79:11434"
    assert loaded.config.models.code == "qwen3.5:9b"
    assert loaded.config.models.options == {"num_ctx": 16384, "temperature": 0.2}
    assert loaded.config.agent.shell_allowlist[0] == "ls"
    assert set(loaded.sources.values()) == {"Default"}


def test_example_file_matches_defaults() -> None:
    assert tomllib.loads(example_config_text()) == DEFAULTS


def test_merge_order_key_by_key(project: Path, user_config: Path, tmp_path: Path) -> None:
    write(
        user_config,
        '[ollama]\nbase_url = "http://user:1"\nkeep_alive = "1m"\n[models]\nchat = "user-chat"\n',
    )
    write(
        project / ".lcc" / "config.toml",
        '[ollama]\nbase_url = "http://project:2"\n[models]\ncode = "project-code"\n',
    )
    extra = write(tmp_path / "extra.toml", '[models]\ncode = "extra-code"\nembed = "extra-embed"\n')

    loaded = load(
        project,
        user_config,
        config_path=extra,
        env={"LCC_OLLAMA_URL": "http://env:3"},
    )
    cfg = loaded.config
    assert cfg.ollama.base_url == "http://env:3"
    assert cfg.ollama.keep_alive == "1m"  # nur User setzt das
    assert cfg.models.chat == "user-chat"
    assert cfg.models.code == "extra-code"
    assert cfg.models.embed == "extra-embed"
    assert cfg.ollama.timeout_seconds == 300.0  # Default bleibt
    assert loaded.sources["ollama.base_url"] == "Umgebung LCC_OLLAMA_URL"
    assert loaded.sources["ollama.keep_alive"] == str(user_config)
    assert loaded.sources["models.code"] == str(extra.resolve())
    assert loaded.files == [user_config, project / ".lcc" / "config.toml", extra.resolve()]


def test_cli_overrides_env(project: Path, user_config: Path) -> None:
    loaded = load(
        project,
        user_config,
        env={"LCC_OLLAMA_URL": "http://env:3", "LCC_CODE_MODEL": "env-model"},
        overrides=CliOverrides(url="http://cli:4/", model="cli-model"),
    )
    assert loaded.config.ollama.base_url == "http://cli:4"
    assert loaded.config.models.code == "cli-model"
    assert loaded.config.models.chat == "cli-model"
    assert loaded.sources["models.code"] == "CLI --model"


def test_env_code_model(project: Path, user_config: Path) -> None:
    loaded = load(project, user_config, env={"LCC_CODE_MODEL": "env-model"})
    assert loaded.config.models.code == "env-model"
    assert loaded.config.models.chat == "qwen3.5:9b"


def test_options_merge_key_by_key(project: Path, user_config: Path) -> None:
    write(user_config, "[models.options]\nnum_ctx = 8192\ntop_p = 0.9\n")
    loaded = load(project, user_config)
    assert loaded.config.models.options == {"num_ctx": 8192, "temperature": 0.2, "top_p": 0.9}
    assert loaded.warnings == []


def test_project_config_found_from_subdirectory(project: Path, user_config: Path) -> None:
    write(project / ".lcc" / "config.toml", '[models]\ncode = "proj"\n')
    sub = project / "src" / "pkg"
    sub.mkdir(parents=True)
    loaded = load(project, user_config, cwd=sub)
    assert loaded.config.models.code == "proj"


def test_find_project_root_without_git(tmp_path: Path) -> None:
    assert find_project_root(tmp_path) == tmp_path.resolve()


def test_unknown_key_warns_with_suggestion(project: Path, user_config: Path) -> None:
    write(user_config, '[ollama]\nbase_ulr = "http://x:1"\n[modles]\ncode = "x"\n')
    loaded = load(project, user_config)
    assert len(loaded.warnings) == 2
    assert "ollama.base_ulr" in loaded.warnings[0]
    assert "ollama.base_url" in loaded.warnings[0]
    assert "'models'" in loaded.warnings[1]
    assert loaded.config.ollama.base_url == "http://192.168.178.79:11434"


@pytest.mark.parametrize(
    ("content", "key", "expected"),
    [
        ('[agent]\nmax_steps = "viele"\n', "agent.max_steps", "int"),
        ("[agent]\nconfirm_writes = 1\n", "agent.confirm_writes", "bool"),
        ("[agent]\nmax_steps = true\n", "agent.max_steps", "int"),
        ('[rag]\nsources = "docs"\n', "rag.sources", "Liste"),
        ("[rag]\nsources = [1, 2]\n", "rag.sources", "Liste"),
        ('[rag]\nmin_score = "hoch"\n', "rag.min_score", "Zahl"),
        ('ollama = "x"\n', "ollama", "Tabelle"),
        ("[models]\noptions = 3\n", "models.options", "Tabelle"),
    ],
)
def test_wrong_type_is_error(
    project: Path, user_config: Path, content: str, key: str, expected: str
) -> None:
    write(user_config, content)
    with pytest.raises(ConfigError) as info:
        load(project, user_config)
    message = str(info.value)
    assert str(user_config) in message
    assert f"'{key}'" in message
    assert expected in message


def test_int_accepted_for_float(project: Path, user_config: Path) -> None:
    write(user_config, "[rag]\nmin_score = 1\n")
    assert load(project, user_config).config.rag.min_score == 1.0


def test_enum_validation(project: Path, user_config: Path) -> None:
    write(user_config, '[small_model]\nmode = "maybe"\n')
    with pytest.raises(ConfigError, match=r"small_model\.mode"):
        load(project, user_config)


@pytest.mark.parametrize("url", ["192.168.178.79:11434", "localhost", "ftp://host"])
def test_base_url_without_scheme_is_error(project: Path, user_config: Path, url: str) -> None:
    write(user_config, f'[ollama]\nbase_url = "{url}"\n')
    with pytest.raises(ConfigError, match="Schema"):
        load(project, user_config)


def test_env_url_without_scheme_is_error(project: Path, user_config: Path) -> None:
    with pytest.raises(ConfigError, match="LCC_OLLAMA_URL"):
        load(project, user_config, env={"LCC_OLLAMA_URL": "host:11434"})


def test_invalid_toml_is_error(project: Path, user_config: Path) -> None:
    write(user_config, "[ollama\n")
    with pytest.raises(ConfigError, match="TOML"):
        load(project, user_config)


def test_missing_explicit_config_is_error(project: Path, user_config: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nicht gefunden"):
        load(project, user_config, config_path=tmp_path / "nope.toml")


def test_paths_resolved_relative_to_file(
    project: Path, user_config: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    write(
        project / ".lcc" / "config.toml",
        '[rag]\nsources = ["../docs", "~/notes"]\nindex_path = "index.db"\n',
    )
    write(user_config, '[workspace]\nroot = "work"\n')
    cfg = load(project, user_config).config
    assert cfg.rag.sources == (project / "docs", tmp_path / "home" / "notes")
    assert cfg.rag.index_path == project / ".lcc" / "index.db"
    assert cfg.workspace.root == user_config.parent / "work"


def test_default_paths_relative_to_project_root(project: Path, user_config: Path) -> None:
    sub = project / "sub"
    sub.mkdir()
    cfg = load(project, user_config, cwd=sub).config
    assert cfg.workspace.root == project.resolve()
    assert cfg.rag.index_path == project.resolve() / ".lcc" / "index.db"
    assert cfg.session.sessions_dir == Path("~/.local/state/lcc/sessions").expanduser()


def test_config_is_frozen(tmp_path: Path) -> None:
    cfg = default_config(tmp_path)
    with pytest.raises(AttributeError):
        cfg.models.code = "x"  # type: ignore[misc]


def test_format_effective_contains_sources(project: Path, user_config: Path) -> None:
    write(user_config, '[models]\ncode = "mine"\n')
    loaded = load(project, user_config)
    text = format_effective(loaded)
    assert f'code = "mine"  # {user_config}' in text
    assert "[models.options]" in text
    assert "num_ctx = 16384  # Default" in text
    # Ausgabe ist (ohne Kommentare) wieder gültiges TOML
    assert tomllib.loads(text)["models"]["code"] == "mine"


def test_effective_as_json(project: Path, user_config: Path) -> None:
    data = effective_as_json(load(project, user_config))
    assert data["models.code"] == {"value": "qwen3.5:9b", "source": "Default"}
    assert isinstance(data["workspace.root"]["value"], str)
    assert all(isinstance(item, str) for item in data["rag.sources"]["value"])


def test_init_user_config_no_overwrite(tmp_path: Path) -> None:
    target = tmp_path / "cfg" / "config.toml"
    assert init_user_config(target) == target
    assert tomllib.loads(target.read_text(encoding="utf-8")) == DEFAULTS
    target.write_text("# eigene\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        init_user_config(target)
    assert target.read_text(encoding="utf-8") == "# eigene\n"
    init_user_config(target, force=True)
    assert "[ollama]" in target.read_text(encoding="utf-8")
