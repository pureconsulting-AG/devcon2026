from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any

import pytest

from lcc.agent.sandbox import (
    Confirmer,
    Sandbox,
    SandboxError,
    is_allowlisted,
    split_command,
)
from lcc.agent.tools import ToolContext, ToolResult, default_registry
from lcc.config import default_config
from lcc.ollama_client import ToolCall

PY = sys.executable


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src").mkdir(parents=True)
    (root / "src" / "calc.py").write_text(
        "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    (root / ".git").mkdir()
    return root


class Answers:
    """Simulierte Nutzereingaben für den Bestätigungsdialog."""

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.prompts = 0

    def __call__(self, prompt: str) -> str:
        self.prompts += 1
        return self.answers.pop(0)


def make_ctx(
    workspace: Path,
    *,
    interactive: bool = True,
    assume_yes: bool = False,
    answers: Answers | None = None,
    allowlist: tuple[str, ...] | None = None,
    shell_timeout: float | None = None,
    confirm_writes: bool = True,
) -> ToolContext:
    config = default_config(workspace)
    agent = config.agent
    if allowlist is not None:
        agent = dataclasses.replace(agent, shell_allowlist=allowlist)
    if shell_timeout is not None:
        agent = dataclasses.replace(agent, shell_timeout_seconds=shell_timeout)
    config = dataclasses.replace(config, agent=agent)
    confirmer = Confirmer(
        interactive=interactive,
        assume_yes=assume_yes,
        confirm_writes=confirm_writes,
        ask=answers or Answers(),
    )
    return ToolContext(
        config=config, sandbox=Sandbox(workspace, config.workspace.ignore), confirmer=confirmer
    )


def call(ctx: ToolContext, name: str, **arguments: Any) -> ToolResult:
    return default_registry().execute(ToolCall(name, arguments), ctx)


def calc(workspace: Path) -> str:
    return (workspace / "src" / "calc.py").read_text(encoding="utf-8")


# -- resolve_write -----------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("../x.py", "außerhalb"),
        ("/tmp/x.py", "außerhalb"),
        (".git/config", ".git"),
        ("sub/.git/hooks/pre-commit", ".git"),
        (".lcc/undo/x", "Backups"),
        (".", "außerhalb"),
        ("src", "Keine Datei"),
    ],
)
def test_resolve_write_rejects(workspace: Path, path: str, message: str) -> None:
    with pytest.raises(SandboxError, match=message):
        Sandbox(workspace).resolve_write(path)


def test_resolve_write_symlink_outside(workspace: Path, tmp_path: Path) -> None:
    (workspace / "out").symlink_to(tmp_path)
    with pytest.raises(SandboxError, match="außerhalb"):
        Sandbox(workspace).resolve_write("out/evil.py")


def test_resolve_write_new_nested_file(workspace: Path) -> None:
    target = Sandbox(workspace).resolve_write("new/dir/file.py")
    assert target == workspace.resolve() / "new" / "dir" / "file.py"


# -- write_file --------------------------------------------------------------


def test_write_new_file_with_confirmation(workspace: Path) -> None:
    answers = Answers("j")
    result = call(
        make_ctx(workspace, answers=answers), "write_file", path="pkg/new.py", content="x = 1"
    )
    assert result.ok, result.content
    assert result.content == "Neu angelegt: pkg/new.py (1 Zeilen)"
    assert (workspace / "pkg" / "new.py").read_text(encoding="utf-8") == "x = 1\n"
    assert answers.prompts == 1


def test_write_denied_by_user(workspace: Path) -> None:
    result = call(make_ctx(workspace, answers=Answers("n")), "write_file", path="a.py", content="x")
    assert not result.ok
    assert "nicht bestätigt" in result.content
    assert not (workspace / "a.py").exists()


def test_write_denied_without_tty(workspace: Path) -> None:
    result = call(make_ctx(workspace, interactive=False), "write_file", path="a.py", content="x")
    assert not result.ok
    assert "--yes" in result.content
    assert not (workspace / "a.py").exists()


def test_write_with_yes_needs_no_prompt(workspace: Path) -> None:
    answers = Answers()
    ctx = make_ctx(workspace, interactive=False, assume_yes=True, answers=answers)
    assert call(ctx, "write_file", path="a.py", content="x").ok
    assert answers.prompts == 0


def test_write_confirm_writes_disabled(workspace: Path) -> None:
    ctx = make_ctx(workspace, interactive=False, confirm_writes=False)
    assert call(ctx, "write_file", path="a.py", content="x").ok


def test_always_answer_skips_later_prompts(workspace: Path) -> None:
    answers = Answers("i")
    ctx = make_ctx(workspace, answers=answers)
    assert call(ctx, "write_file", path="a.py", content="1").ok
    assert call(ctx, "write_file", path="b.py", content="2").ok
    assert answers.prompts == 1


def test_invalid_answer_asks_again(workspace: Path) -> None:
    answers = Answers("vielleicht", "j")
    assert call(make_ctx(workspace, answers=answers), "write_file", path="a.py", content="x").ok
    assert answers.prompts == 2


def test_write_unchanged_content(workspace: Path) -> None:
    answers = Answers()
    result = call(
        make_ctx(workspace, answers=answers),
        "write_file",
        path="src/calc.py",
        content=calc(workspace),
    )
    assert "Keine Änderung" in result.content
    assert answers.prompts == 0


def test_write_into_git_rejected(workspace: Path) -> None:
    result = call(make_ctx(workspace, assume_yes=True), "write_file", path=".git/HEAD", content="x")
    assert not result.ok
    assert ".git" in result.content


# -- edit_file ---------------------------------------------------------------


def test_edit_file_single_match(workspace: Path) -> None:
    ctx = make_ctx(workspace, answers=Answers("j"))
    result = call(
        ctx,
        "edit_file",
        path="src/calc.py",
        old_str="def add(a, b):\n    return a - b",
        new_str="def add(a, b):\n    return a + b",
    )
    assert result.ok, result.content
    assert result.content == "Geändert: src/calc.py (Zeilen 1-2)"
    assert calc(workspace).startswith("def add(a, b):\n    return a + b\n")
    assert calc(workspace).endswith("def sub(a, b):\n    return a - b\n")


def test_edit_file_no_match(workspace: Path) -> None:
    result = call(
        make_ctx(workspace), "edit_file", path="src/calc.py", old_str="return a * b", new_str="x"
    )
    assert not result.ok
    assert "nicht vor" in result.content
    assert "read_file" in result.content


def test_edit_file_two_matches(workspace: Path) -> None:
    before = calc(workspace)
    result = call(
        make_ctx(workspace, answers=Answers("j")),
        "edit_file",
        path="src/calc.py",
        old_str="return a - b",
        new_str="return a + b",
    )
    assert not result.ok
    assert "2-mal" in result.content
    assert "Zeilen 2, 6" in result.content
    assert calc(workspace) == before


def test_edit_file_errors(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    assert "nicht gefunden" in call(ctx, "edit_file", path="x.py", old_str="a", new_str="b").content
    assert "leer" in call(ctx, "edit_file", path="src/calc.py", old_str="", new_str="b").content
    assert (
        "identisch"
        in call(ctx, "edit_file", path="src/calc.py", old_str="add", new_str="add").content
    )


def test_edit_denied_keeps_file(workspace: Path) -> None:
    before = calc(workspace)
    result = call(
        make_ctx(workspace, answers=Answers("n")),
        "edit_file",
        path="src/calc.py",
        old_str="def add",
        new_str="def plus",
    )
    assert not result.ok
    assert calc(workspace) == before
    assert Sandbox(workspace).backups() == []


# -- Undo / Diff -------------------------------------------------------------


def test_undo_restores_and_deletes_in_reverse_order(workspace: Path) -> None:
    ctx = make_ctx(workspace, assume_yes=True)
    original = calc(workspace)
    call(ctx, "edit_file", path="src/calc.py", old_str="def add", new_str="def plus")
    call(ctx, "write_file", path="new.py", content="neu")
    assert len(ctx.sandbox.backups()) == 2

    change = ctx.sandbox.undo_last()
    assert change is not None and not change.existed
    assert not (workspace / "new.py").exists()

    change = ctx.sandbox.undo_last()
    assert change is not None and change.existed
    assert calc(workspace) == original
    assert ctx.sandbox.undo_last() is None


def test_undo_works_across_sessions(workspace: Path) -> None:
    ctx = make_ctx(workspace, assume_yes=True)
    call(ctx, "write_file", path="src/calc.py", content="neu")
    fresh = Sandbox(workspace)
    assert fresh.undo_last() is not None
    assert "def add" in calc(workspace)


def test_session_diff(workspace: Path) -> None:
    ctx = make_ctx(workspace, assume_yes=True)
    call(ctx, "edit_file", path="src/calc.py", old_str="def add", new_str="def plus")
    call(ctx, "edit_file", path="src/calc.py", old_str="def sub", new_str="def minus")
    call(ctx, "write_file", path="new.py", content="neu")
    diff = ctx.sandbox.session_diff()
    assert "--- a/src/calc.py" in diff
    assert "-def add(a, b):" in diff
    assert "+def plus(a, b):" in diff
    assert "+def minus(a, b):" in diff
    assert "+++ b/new.py" in diff
    assert diff.count("--- a/src/calc.py") == 1


def test_undo_dir_hidden_from_listing(workspace: Path) -> None:
    ctx = make_ctx(workspace, assume_yes=True)
    call(ctx, "write_file", path="a.py", content="x")
    listing = call(ctx, "list_dir", path=".", depth=3).content
    assert "undo" not in listing


# -- Shell -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("ls", True),
        ("ls -la src", True),
        ("git status", True),
        ("git status -s", True),
        ("git push", False),
        ("git", False),
        ("python -m pytest -q", True),
        ("python -m pip install x", False),
        ("python script.py", False),
        ("lsblk", False),
        ("ls; rm -rf /", False),
        ("rm -rf .", False),
    ],
)
def test_allowlist_token_prefix(command: str, allowed: bool) -> None:
    allowlist = default_config().agent.shell_allowlist
    assert is_allowlisted(split_command(command), allowlist) is allowed


def test_split_command_errors() -> None:
    with pytest.raises(SandboxError, match="zerlegt"):
        split_command('echo "offen')
    with pytest.raises(SandboxError, match="Leer"):
        split_command("   ")


def test_allowlisted_command_runs_without_prompt(workspace: Path) -> None:
    answers = Answers()
    ctx = make_ctx(workspace, interactive=False, answers=answers, allowlist=(f"{PY} -c",))
    result = call(ctx, "run_shell", command=f"{PY} -c \"print('hallo'); import sys; sys.exit(3)\"")
    assert result.ok, result.content
    assert result.content.startswith("exit code: 3\n--- stdout ---\nhallo")
    assert answers.prompts == 0


def test_stderr_captured_and_cwd_is_workspace(workspace: Path) -> None:
    ctx = make_ctx(workspace, allowlist=(PY,))
    code = "import os, sys; print(os.getcwd()); print('fehler', file=sys.stderr)"
    result = call(ctx, "run_shell", command=f'{PY} -c "{code}"')
    assert str(workspace.resolve()) in result.content
    assert "--- stderr ---\nfehler" in result.content


def test_command_outside_allowlist_needs_confirmation(workspace: Path) -> None:
    answers = Answers("j")
    ctx = make_ctx(workspace, answers=answers, allowlist=())
    result = call(ctx, "run_shell", command=f'{PY} -c "print(1)"')
    assert result.ok
    assert answers.prompts == 1


def test_command_denied_by_user(workspace: Path) -> None:
    ctx = make_ctx(workspace, answers=Answers("n"), allowlist=())
    result = call(ctx, "run_shell", command=f"{PY} -c \"open('x', 'w')\"")
    assert not result.ok
    assert "nicht bestätigt" in result.content
    assert not (workspace / "x").exists()


def test_command_denied_without_tty_even_with_yes(workspace: Path) -> None:
    ctx = make_ctx(workspace, interactive=False, assume_yes=True, allowlist=("ls",))
    result = call(ctx, "run_shell", command="touch x")
    assert not result.ok
    assert "Allowlist" in result.content
    assert "ls" in result.content
    assert not (workspace / "x").exists()


def test_always_for_same_command_only(workspace: Path) -> None:
    answers = Answers("i", "n")
    ctx = make_ctx(workspace, answers=answers, allowlist=())
    command = f'{PY} -c "print(1)"'
    assert call(ctx, "run_shell", command=command).ok
    assert call(ctx, "run_shell", command=command).ok
    assert not call(ctx, "run_shell", command=f'{PY} -c "print(2)"').ok
    assert answers.prompts == 2


def test_shell_timeout(workspace: Path) -> None:
    ctx = make_ctx(workspace, allowlist=(PY,), shell_timeout=0.5)
    result = call(ctx, "run_shell", command=f'{PY} -c "import time; time.sleep(5)"')
    assert not result.ok
    assert "Zeitüberschreitung" in result.content


def test_shell_program_not_found(workspace: Path) -> None:
    ctx = make_ctx(workspace, allowlist=("gibtsnicht-xyz",))
    result = call(ctx, "run_shell", command="gibtsnicht-xyz --version")
    assert not result.ok
    assert "nicht gefunden" in result.content


def test_shell_no_shell_interpretation(workspace: Path) -> None:
    ctx = make_ctx(workspace, allowlist=("ls",))
    result = call(ctx, "run_shell", command="ls ; touch hacked")
    assert not (workspace / "hacked").exists()
    assert "exit code" in result.content


def test_default_prompt_shows_brackets(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    from rich.console import Console

    out = io.StringIO()
    monkeypatch.setattr("builtins.input", lambda *args: "j")
    confirmer = Confirmer(interactive=True, console=Console(file=out, force_terminal=False))
    assert confirmer.confirm_command("touch x")
    assert "[j]a / [n]ein / [i]mmer für diese Session" in out.getvalue()


def test_python_falls_back_to_running_interpreter(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "python" else real_which(name)
    )
    ctx = make_ctx(workspace, interactive=False, allowlist=("python -c",))
    result = call(ctx, "run_shell", command='python -c "import sys; print(sys.executable)"')
    assert result.ok, result.content
    assert sys.executable in result.content
