from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path
from typing import Any

import pytest

from lcc.agent import tools
from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import (
    ToolContext,
    ToolRegistry,
    ToolSpec,
    default_registry,
    truncate_middle,
    validate_arguments,
)
from lcc.config import default_config
from lcc.ollama_client import ToolCall


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "src" / "pkg" / "util.py").write_text(
        "def slugify(text):\n    return text.lower()\n\n\nclass Helper:\n    pass\n",
        encoding="utf-8",
    )
    (root / "src" / "main.py").write_text("from pkg.util import slugify\n", encoding="utf-8")
    (root / "README.md").write_text("# Projekt\nslugify erklärt\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("slugify im git\n", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\0\1slugify")
    (root / "image.bin").write_bytes(b"\0\0\0slugify")
    return root


def make_ctx(workspace: Path, max_chars: int = 12000) -> ToolContext:
    config = default_config(workspace)
    config = dataclasses.replace(
        config, agent=dataclasses.replace(config.agent, max_tool_output_chars=max_chars)
    )
    sandbox = Sandbox(workspace, config.workspace.ignore)
    return ToolContext(config=config, sandbox=sandbox)


def call(ctx: ToolContext, name: str, **arguments: Any) -> tools.ToolResult:
    return default_registry().execute(ToolCall(name, arguments), ctx)


@pytest.fixture(params=["python", "rg"])
def search_backend(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """search_code mit Python-Fallback und – falls installiert – mit rg testen."""
    if request.param == "python":
        monkeypatch.setattr(shutil, "which", lambda name: None)
    elif shutil.which("rg") is None:
        pytest.skip("rg nicht installiert")
    return str(request.param)


# -- list_dir ----------------------------------------------------------------


def test_list_dir_root_ignores_patterns(workspace: Path) -> None:
    result = call(make_ctx(workspace), "list_dir")
    assert result.ok
    assert result.content.splitlines() == [
        "./",
        "  src/",
        "  image.bin",
        "  README.md",
    ]


def test_list_dir_depth(workspace: Path) -> None:
    result = call(make_ctx(workspace), "list_dir", path="src", depth=3)
    assert result.content.splitlines() == ["src/", "  pkg/", "    util.py", "  main.py"]


def test_list_dir_errors(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    assert not call(ctx, "list_dir", path="nope").ok
    assert "Kein Ordner" in call(ctx, "list_dir", path="README.md").content
    assert "außerhalb" in call(ctx, "list_dir", path="..").content


# -- read_file ---------------------------------------------------------------


def test_read_file_with_line_numbers(workspace: Path) -> None:
    result = call(make_ctx(workspace), "read_file", path="src/pkg/util.py")
    assert result.ok
    lines = result.content.splitlines()
    assert lines[0] == "src/pkg/util.py (Zeilen 1-6 von 6)"
    assert lines[1] == "1| def slugify(text):"
    assert lines[6] == "6|     pass"


def test_read_file_range(workspace: Path) -> None:
    result = call(
        make_ctx(workspace), "read_file", path="src/pkg/util.py", start_line=5, end_line=9
    )
    assert result.content.splitlines() == [
        "src/pkg/util.py (Zeilen 5-6 von 6)",
        "5| class Helper:",
        "6|     pass",
    ]


def test_read_file_range_as_strings_is_coerced(workspace: Path) -> None:
    result = call(make_ctx(workspace), "read_file", path="src/pkg/util.py", start_line="2")
    assert result.ok
    assert result.content.splitlines()[1] == "2|     return text.lower()"


def test_read_file_range_outside(workspace: Path) -> None:
    result = call(make_ctx(workspace), "read_file", path="src/pkg/util.py", start_line=50)
    assert not result.ok
    assert "außerhalb der Datei" in result.content


def test_read_file_errors(workspace: Path) -> None:
    ctx = make_ctx(workspace)
    assert "nicht gefunden" in call(ctx, "read_file", path="missing.py").content
    assert "Binärdatei" in call(ctx, "read_file", path="image.bin").content
    assert "Keine Datei" in call(ctx, "read_file", path="src").content
    assert "außerhalb" in call(ctx, "read_file", path="../x").content


def test_read_file_truncates_at_line_boundary(workspace: Path) -> None:
    big = "\n".join(f"zeile {i:04d} " + "x" * 40 for i in range(1, 501))
    (workspace / "big.txt").write_text(big, encoding="utf-8")
    result = call(make_ctx(workspace, max_chars=2000), "read_file", path="big.txt")
    assert len(result.content) <= 2000
    lines = result.content.splitlines()
    assert lines[0].startswith("big.txt (Zeilen 1-")
    assert "start_line" in lines[-1]
    last_shown = int(lines[-2].split("|")[0])
    assert lines[0] == f"big.txt (Zeilen 1-{last_shown} von 500)"


# -- search_code -------------------------------------------------------------


def test_search_code_finds_matches(workspace: Path, search_backend: str) -> None:
    result = call(make_ctx(workspace), "search_code", pattern="slugify")
    assert result.ok
    assert result.content.splitlines() == [
        "README.md:2: slugify erklärt",
        "src/main.py:1: from pkg.util import slugify",
        "src/pkg/util.py:1: def slugify(text):",
    ]


def test_search_code_glob_and_path(workspace: Path, search_backend: str) -> None:
    ctx = make_ctx(workspace)
    assert call(ctx, "search_code", pattern="slugify", glob="*.md").content == (
        "README.md:2: slugify erklärt"
    )
    assert call(ctx, "search_code", pattern=r"class \w+", path="src/pkg").content == (
        "src/pkg/util.py:5: class Helper:"
    )


def test_search_code_no_match(workspace: Path, search_backend: str) -> None:
    result = call(make_ctx(workspace), "search_code", pattern="gibtsnicht")
    assert result.ok
    assert "Keine Treffer" in result.content


def test_search_code_bad_regex(workspace: Path, search_backend: str) -> None:
    result = call(make_ctx(workspace), "search_code", pattern="(")
    assert not result.ok
    assert "regulärer Ausdruck" in result.content


def test_search_code_outside(workspace: Path) -> None:
    assert "außerhalb" in call(make_ctx(workspace), "search_code", pattern="x", path="/").content


# -- Registry / Validierung --------------------------------------------------


def test_unknown_tool(workspace: Path) -> None:
    result = call(make_ctx(workspace), "delete_everything")
    assert not result.ok
    assert "unbekanntes Tool" in result.content
    assert "read_file" in result.content


def test_tool_not_allowed_is_unknown(workspace: Path) -> None:
    result = default_registry().execute(
        ToolCall("read_file", {"path": "README.md"}), make_ctx(workspace), allowed=["list_dir"]
    )
    assert not result.ok
    assert "unbekanntes Tool" in result.content


def test_missing_argument_returns_example(workspace: Path) -> None:
    result = call(make_ctx(workspace), "read_file")
    assert not result.ok
    assert "'path' fehlt" in result.content
    assert '"tool": "read_file"' in result.content


def test_validate_arguments_types() -> None:
    spec = tools.READ_FILE
    assert validate_arguments(spec, {"path": "a", "start_line": 1}) == []
    assert validate_arguments(spec, {"path": 3}) == ["'path' muss string sein"]
    assert validate_arguments(spec, {"path": "a", "start_line": True}) == [
        "'start_line' muss integer sein"
    ]
    assert validate_arguments(spec, {"path": "a", "foo": 1}) == ["'foo' ist unbekannt"]


def test_unexpected_exception_becomes_tool_error(workspace: Path) -> None:
    def boom(ctx: ToolContext, args: dict[str, Any]) -> str:
        raise RuntimeError("kaputt")

    registry = ToolRegistry([ToolSpec("boom", "x", {"type": "object", "properties": {}}, boom)])
    result = registry.execute(ToolCall("boom", {}), make_ctx(workspace))
    assert not result.ok
    assert "RuntimeError: kaputt" in result.content


def test_output_is_truncated(workspace: Path) -> None:
    def big(ctx: ToolContext, args: dict[str, Any]) -> str:
        return "A" * 5000 + "B" * 5000

    registry = ToolRegistry([ToolSpec("big", "x", {"type": "object", "properties": {}}, big)])
    result = registry.execute(ToolCall("big", {}), make_ctx(workspace, max_chars=1000))
    assert len(result.content) <= 1000
    assert result.content.startswith("A")
    assert result.content.endswith("B")
    assert "gekürzt" in result.content


def test_truncate_middle_short_text_unchanged() -> None:
    assert truncate_middle("abc", 10) == "abc"


def test_schemas_in_ollama_format() -> None:
    schemas = default_registry().schemas(["read_file", "nope"])
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "read_file"
    assert schemas[0]["function"]["parameters"]["required"] == ["path"]
