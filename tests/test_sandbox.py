from __future__ import annotations

from pathlib import Path

import pytest

from lcc.agent.sandbox import Sandbox, SandboxError


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("geheim\n", encoding="utf-8")
    return root


def test_relative_path_inside(workspace: Path) -> None:
    sandbox = Sandbox(workspace)
    assert sandbox.resolve_read("src/a.py") == (workspace / "src" / "a.py").resolve()
    assert sandbox.resolve_read(".") == workspace.resolve()
    assert sandbox.resolve_read("") == workspace.resolve()


def test_absolute_path_inside(workspace: Path) -> None:
    sandbox = Sandbox(workspace)
    assert sandbox.resolve_read(str(workspace / "src")) == (workspace / "src").resolve()


@pytest.mark.parametrize("path", ["../secret.txt", "src/../../secret.txt", "/etc/passwd", "~"])
def test_paths_outside_are_rejected(workspace: Path, path: str) -> None:
    with pytest.raises(SandboxError, match="außerhalb"):
        Sandbox(workspace).resolve_read(path)


def test_dotdot_staying_inside_is_allowed(workspace: Path) -> None:
    sandbox = Sandbox(workspace)
    assert sandbox.resolve_read("src/../src/a.py") == (workspace / "src" / "a.py").resolve()


def test_symlink_pointing_outside_is_rejected(workspace: Path) -> None:
    (workspace / "link.txt").symlink_to(workspace.parent / "secret.txt")
    (workspace / "linkdir").symlink_to(workspace.parent)
    sandbox = Sandbox(workspace)
    with pytest.raises(SandboxError):
        sandbox.resolve_read("link.txt")
    with pytest.raises(SandboxError):
        sandbox.resolve_read("linkdir/secret.txt")


def test_symlink_inside_is_allowed(workspace: Path) -> None:
    (workspace / "alias.py").symlink_to(workspace / "src" / "a.py")
    assert Sandbox(workspace).resolve_read("alias.py") == (workspace / "src" / "a.py").resolve()


def test_extra_read_roots(workspace: Path, tmp_path: Path) -> None:
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "SKILL.md").write_text("x", encoding="utf-8")
    sandbox = Sandbox(workspace, extra_read_roots=[skills])
    assert sandbox.resolve_read(str(skills / "SKILL.md")) == (skills / "SKILL.md").resolve()


def test_relpath(workspace: Path) -> None:
    sandbox = Sandbox(workspace)
    assert sandbox.relpath(workspace / "src" / "a.py") == "src/a.py"
    assert sandbox.relpath(workspace) == "."


@pytest.mark.parametrize(
    ("relpath", "ignored"),
    [
        (".git", True),
        (".git/config", True),
        ("src/__pycache__/a.pyc", True),
        ("node_modules/x/index.js", True),
        (".lcc/index.db", True),
        (".lcc/config.toml", False),
        ("src/a.py", False),
        ("src/a.pyc", True),
        ("gitignore.txt", False),
    ],
)
def test_is_ignored(workspace: Path, relpath: str, ignored: bool) -> None:
    sandbox = Sandbox(
        workspace, [".git", ".venv", "node_modules", "__pycache__", ".lcc/index.db", "*.pyc"]
    )
    assert sandbox.is_ignored(workspace / relpath) is ignored
