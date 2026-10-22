from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from lcc.agent import fuzzy
from lcc.agent.sandbox import Confirmer, Sandbox
from lcc.agent.tools import ToolContext, ToolResult, available_tool_names, default_registry
from lcc.config import default_config
from lcc.ollama_client import ToolCall

SOURCE = """class Rechner:
    def add(self, a, b):
        return a - b

    def sub(self, a, b):
        return a - b
"""


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "calc.py").write_text(SOURCE, encoding="utf-8")
    return root


def make_ctx(workspace: Path, *, small: bool = True) -> ToolContext:
    config = default_config(workspace)
    return ToolContext(
        config=config,
        sandbox=Sandbox(workspace, config.workspace.ignore),
        confirmer=Confirmer(interactive=False, assume_yes=True),
        small_mode=small,
    )


def call(ctx: ToolContext, name: str, **arguments: Any) -> ToolResult:
    return default_registry().execute(ToolCall(name, arguments), ctx)


def calc(workspace: Path) -> str:
    return (workspace / "calc.py").read_text(encoding="utf-8")


# -- fuzzy_edit --------------------------------------------------------------


@pytest.mark.parametrize(
    "old",
    [
        "def add(self, a, b):\n    return a - b",  # Einrückung fehlt komplett
        "  def add(self, a, b):  \n      return a - b",  # falsche Einrückung + Leerzeichen am Ende
        "\tdef add(self, a, b):\n\t\treturn a  -  b",  # Tabs + doppelte Leerzeichen
        "    def add(self, a, b):\r\n        return a - b\r\n",  # Windows-Zeilenenden
    ],
)
def test_fuzzy_edit_whitespace_variants(workspace: Path, old: str) -> None:
    new = old.replace("a - b", "a + b").replace("a  -  b", "a + b")
    result = call(make_ctx(workspace), "edit_file", path="calc.py", old_str=old, new_str=new)
    assert result.ok, result.content
    assert "angeglichen" in result.content
    text = calc(workspace)
    assert "    def add(self, a, b):\n        return a + b\n" in text
    assert "    def sub(self, a, b):\n        return a - b\n" in text


def test_fuzzy_edit_only_in_small_mode(workspace: Path) -> None:
    result = call(
        make_ctx(workspace, small=False),
        "edit_file",
        path="calc.py",
        old_str="def add(self, a, b):\nreturn a - b",
        new_str="x",
    )
    assert not result.ok
    assert "Ähnlichsten" not in result.content


def test_fuzzy_disabled_by_config(workspace: Path) -> None:
    import dataclasses

    ctx = make_ctx(workspace)
    ctx.config = dataclasses.replace(
        ctx.config, small_model=dataclasses.replace(ctx.config.small_model, fuzzy_edit=False)
    )
    result = call(ctx, "edit_file", path="calc.py", old_str="def add(self,a,b):", new_str="x")
    assert not result.ok


def test_fuzzy_no_match_lists_similar_locations(workspace: Path) -> None:
    result = call(
        make_ctx(workspace),
        "edit_file",
        path="calc.py",
        old_str="def add(self, x, y):\n    return x - y",
        new_str="x",
    )
    assert not result.ok
    assert "nicht vor" in result.content
    assert "Die ähnlichsten Stellen:" in result.content
    assert "Zeilen 2-3 (Ähnlichkeit" in result.content
    assert "2|     def add(self, a, b):" in result.content
    assert calc(workspace) == SOURCE


def test_fuzzy_ambiguous_lists_locations(workspace: Path) -> None:
    result = call(
        make_ctx(workspace), "edit_file", path="calc.py", old_str="  return a - b  ", new_str="x"
    )
    assert not result.ok
    assert "2-mal" in result.content
    assert "Zeilen 3, 6" in result.content
    assert "Die ähnlichsten Stellen:" in result.content
    assert calc(workspace) == SOURCE


def test_exact_ambiguous_in_small_mode_shows_locations(workspace: Path) -> None:
    result = call(
        make_ctx(workspace), "edit_file", path="calc.py", old_str="return a - b", new_str="x"
    )
    assert "Zeilen 3, 6" in result.content
    assert "3|         return a - b" in result.content


def test_similar_locations_are_distinct_and_sorted() -> None:
    lines = SOURCE.splitlines()
    locations = fuzzy.similar_locations(lines, "def add(self, a, b):\n    return a + b", count=3)
    assert locations[0].start_line == 2
    assert locations[0].ratio > locations[-1].ratio
    starts = [loc.start_line for loc in locations]
    assert len(set(starts)) == len(starts)


def test_reindent() -> None:
    assert fuzzy.reindent("def f():\n    return 1", "    def f():") == (
        "    def f():\n        return 1"
    )
    assert fuzzy.reindent("x", "  x") == "  x"
    # Echter Fall mit qwen3.5:9b: old_str hat ein Leerzeichen zu viel, new_str ist korrekt
    new = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b"
    assert fuzzy.reindent(new, "def add(a, b):") == new


# -- replace_lines -----------------------------------------------------------


def test_replace_lines_after_read(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    call(ctx, "read_file", path="calc.py")
    result = call(
        ctx,
        "replace_lines",
        path="calc.py",
        start_line=3,
        end_line=3,
        content="        return a + b",
    )
    assert result.ok, result.content
    assert calc(workspace).splitlines()[2] == "        return a + b"
    assert calc(workspace).splitlines()[5] == "        return a - b"


def test_replace_lines_requires_read(workspace: Path) -> None:
    result = call(
        make_ctx(workspace), "replace_lines", path="calc.py", start_line=1, end_line=1, content="x"
    )
    assert not result.ok
    assert "neu mit read_file" in result.content


def test_replace_lines_rejects_changed_file(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    call(ctx, "read_file", path="calc.py")
    (workspace / "calc.py").write_text("# geändert\n" + SOURCE, encoding="utf-8")
    result = call(ctx, "replace_lines", path="calc.py", start_line=3, end_line=3, content="x")
    assert not result.ok
    assert "seit dem letzten read_file geändert" in result.content
    assert calc(workspace).startswith("# geändert")


def test_replace_lines_twice_needs_reread(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    call(ctx, "read_file", path="calc.py")
    assert call(ctx, "replace_lines", path="calc.py", start_line=1, end_line=1, content="a\nb").ok
    second = call(ctx, "replace_lines", path="calc.py", start_line=1, end_line=1, content="c")
    assert not second.ok
    call(ctx, "read_file", path="calc.py")
    assert call(ctx, "replace_lines", path="calc.py", start_line=1, end_line=1, content="c").ok


def test_replace_lines_bad_range(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    call(ctx, "read_file", path="calc.py")
    result = call(ctx, "replace_lines", path="calc.py", start_line=5, end_line=99, content="x")
    assert not result.ok
    assert "6 Zeilen" in result.content


def test_replace_lines_only_in_small_mode(workspace: Path) -> None:
    registry = default_registry()
    assert "replace_lines" in available_tool_names(registry, make_ctx(workspace))
    assert "replace_lines" not in available_tool_names(registry, make_ctx(workspace, small=False))


# -- write_file-Sperre -------------------------------------------------------


def test_write_file_blocked_for_large_existing_files(workspace: Path) -> None:
    big = "\n".join(f"zeile {i}" for i in range(250)) + "\n"
    (workspace / "big.py").write_text(big, encoding="utf-8")
    result = call(make_ctx(workspace), "write_file", path="big.py", content="kurz")
    assert not result.ok
    assert "edit_file oder replace_lines" in result.content
    assert (workspace / "big.py").read_text(encoding="utf-8") == big

    assert call(make_ctx(workspace, small=False), "write_file", path="big.py", content="x").ok


def test_write_file_allowed_for_new_and_small_files(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    assert call(ctx, "write_file", path="neu.py", content="\n".join(["x"] * 500)).ok
    assert call(ctx, "write_file", path="calc.py", content="x = 1").ok


def test_fuzzy_edit_stray_space_in_old_str(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    result = call(
        make_ctx(tmp_path),
        "edit_file",
        path="calc.py",
        old_str=" def add(a, b):\n     return a - b",
        new_str="def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b",
    )
    assert result.ok, result.content
    assert (tmp_path / "calc.py").read_text() == (
        "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
    )
