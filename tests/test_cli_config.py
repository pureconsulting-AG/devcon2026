from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc.cli import EXIT_CONFIG_ERROR, app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("LCC_OLLAMA_URL", raising=False)
    monkeypatch.delenv("LCC_CODE_MODEL", raising=False)
    monkeypatch.chdir(work)
    return home


def test_config_show_defaults() -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0, result.output
    assert 'base_url = "http://192.168.178.79:11434"  # Default' in result.stdout


def test_config_show_with_flags_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LCC_CODE_MODEL", "env-model")
    result = runner.invoke(app, ["--url", "http://x:1", "config", "show"])
    assert result.exit_code == 0, result.output
    assert 'base_url = "http://x:1"  # CLI --url' in result.stdout
    assert 'code = "env-model"  # Umgebung LCC_CODE_MODEL' in result.stdout


def test_config_show_json(tmp_path: Path) -> None:
    extra = tmp_path / "extra.toml"
    extra.write_text('[models]\nembed = "e"\n', encoding="utf-8")
    result = runner.invoke(app, ["--json", "--config", str(extra), "config", "show"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["files"] == [str(extra.resolve())]
    assert data["values"]["models.embed"] == {"value": "e", "source": str(extra.resolve())}


def test_config_error_exit_code(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[agent]\nmax_steps = "x"\n', encoding="utf-8")
    result = runner.invoke(app, ["--config", str(bad), "config", "show"])
    assert result.exit_code == EXIT_CONFIG_ERROR
    assert "agent.max_steps" in result.output


def test_bad_url_flag_exit_code() -> None:
    result = runner.invoke(app, ["--url", "nohost", "config", "show"])
    assert result.exit_code == EXIT_CONFIG_ERROR


def test_unknown_key_warning_on_stderr(tmp_path: Path) -> None:
    extra = tmp_path / "extra.toml"
    extra.write_text("[ui]\nmarkdwn = false\n", encoding="utf-8")
    result = runner.invoke(app, ["--config", str(extra), "config", "show"])
    assert result.exit_code == 0
    assert "ui.markdown" in result.stderr
    assert "markdwn" not in result.stdout


def test_config_init(isolated: Path) -> None:
    target = isolated / ".config" / "lcc" / "config.toml"
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0, result.output
    assert target.is_file()

    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 1
    assert "--force" in result.stderr

    result = runner.invoke(app, ["config", "init", "--force"])
    assert result.exit_code == 0
