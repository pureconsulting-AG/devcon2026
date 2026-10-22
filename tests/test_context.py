from __future__ import annotations

from pathlib import Path

import pytest

from lcc.agent.context import (
    build_auto_context,
    mentioned_files,
    repo_map,
    symbols,
    workspace_files,
)
from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import ToolContext
from lcc.config import default_config


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src" / "app").mkdir(parents=True)
    (root / "abap").mkdir()
    (root / ".git").mkdir()
    (root / "utils.py").write_text(
        "import re\n\n\ndef slugify(text):\n    return text\n\n\nclass Helper:\n"
        "    def inner(self):\n        pass\n",
        encoding="utf-8",
    )
    (root / "src" / "app" / "main.ts").write_text(
        "export function start() {}\nexport default class App {}\n", encoding="utf-8"
    )
    (root / "abap" / "zcl_x.clas.abap").write_text(
        "CLASS zcl_x DEFINITION PUBLIC.\nENDCLASS.\nCLASS zcl_x IMPLEMENTATION.\n"
        "  METHOD run.\n  ENDMETHOD.\nENDCLASS.\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Projekt\n", encoding="utf-8")
    (root / "bild.png").write_bytes(b"\x89PNG")
    return root


def make_ctx(project: Path) -> ToolContext:
    config = default_config(project)
    return ToolContext(config=config, sandbox=Sandbox(project, config.workspace.ignore))


def test_symbols_per_language(project: Path) -> None:
    assert symbols(project / "utils.py", (project / "utils.py").read_text()) == [
        "slugify",
        "Helper",
    ]
    ts = project / "src" / "app" / "main.ts"
    assert symbols(ts, ts.read_text()) == ["start", "App"]
    abap = project / "abap" / "zcl_x.clas.abap"
    assert symbols(abap, abap.read_text()) == ["zcl_x", "run"]


def test_repo_map_and_limit(project: Path) -> None:
    sandbox = Sandbox(project, [".git"])
    files = workspace_files(sandbox)
    text = repo_map(sandbox, files, 3000)
    assert "utils.py: slugify, Helper" in text
    assert "src/app/main.ts: start, App" in text
    assert "abap/zcl_x.clas.abap: zcl_x, run" in text
    assert "README.md" in text
    assert "bild.png" not in text
    short = repo_map(sandbox, files, 40)
    assert len(short) < 100
    assert "weitere Dateien" in short


def test_workspace_files_flat_first_and_ignored(project: Path) -> None:
    sandbox = Sandbox(project, [".git"])
    rels = [sandbox.relpath(p) for p in workspace_files(sandbox)]
    assert rels[0] in ("README.md", "bild.png", "utils.py")
    assert rels.index("utils.py") < rels.index("src/app/main.ts")
    assert not any(r.startswith(".git") for r in rels)


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("füge in utils.py eine Funktion hinzu", ["utils.py"]),
        ("schau in ./utils.py und src/app/main.ts", ["utils.py", "src/app/main.ts"]),
        ("ändere main.ts", ["src/app/main.ts"]),
        ("Tests für zcl_x.clas.abap", ["abap/zcl_x.clas.abap"]),
        ("gibt es foo.py?", []),
        ("z.B. eine Idee", []),
    ],
)
def test_mentioned_files(project: Path, task: str, expected: list[str]) -> None:
    sandbox = Sandbox(project, [".git"])
    found = mentioned_files(task, sandbox, workspace_files(sandbox))
    assert [sandbox.relpath(p) for p in found] == expected


def test_build_auto_context_order_and_hashes(project: Path) -> None:
    ctx = make_ctx(project)
    auto = build_auto_context(ctx, "füge in utils.py eine Funktion hinzu")
    assert auto.file_names == ["utils.py"]
    messages = auto.messages()
    assert [m["role"] for m in messages] == ["system", "system"]
    assert messages[0]["content"].startswith("Projektübersicht")
    assert "4| def slugify(text):" in messages[1]["content"]
    assert str((project / "utils.py").resolve()) in ctx.read_hashes  # replace_lines möglich


def test_build_auto_context_extra_files_and_no_map(project: Path) -> None:
    auto = build_auto_context(
        make_ctx(project), "mach was", extra_files=["main.ts"], include_map=False
    )
    assert auto.repo_map == ""
    assert auto.file_names == ["src/app/main.ts"]


def test_long_file_is_truncated(project: Path) -> None:
    (project / "lang.py").write_text(
        "\n".join(f"x{i} = {i}" for i in range(3000)), encoding="utf-8"
    )
    auto = build_auto_context(make_ctx(project), "lies lang.py", include_map=False)
    text = auto.files[0][1]
    assert len(text) < 4200
    assert "3000 Zeilen" in text
