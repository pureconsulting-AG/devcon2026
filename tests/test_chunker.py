from __future__ import annotations

import itertools

import pytest

from lcc.rag.chunker import Chunk, chunk_text, embedding_input, split_lines


def lines_of(text: str) -> list[str]:
    return text.splitlines()


def assert_ranges_match(text: str, chunks: list[Chunk]) -> None:
    """Jeder Chunk-Text muss exakt den Zeilen start_line..end_line entsprechen."""
    source = lines_of(text)
    for chunk in chunks:
        expected = "\n".join(source[chunk.start_line - 1 : chunk.end_line])
        assert chunk.text == expected, chunk


MARKDOWN = """# Handbuch

Einleitung zum Projekt.

## Installation

pip install lcc

## Nutzung

### REPL

Starte mit lcc.

```bash
# kein Heading, sondern Kommentar im Code
lcc run "x"
```

## Lizenz
MIT
"""


def test_markdown_splits_at_headings_with_line_ranges() -> None:
    chunks = chunk_text("README.md", MARKDOWN, size=1500, overlap=200)
    assert [(c.start_line, c.end_line) for c in chunks] == [
        (1, 3),
        (5, 7),
        (9, 9),
        (11, 18),
        (20, 21),
    ]
    assert [c.heading for c in chunks] == [
        "Handbuch",
        "Handbuch > Installation",
        "Handbuch > Nutzung",
        "Handbuch > Nutzung > REPL",
        "Handbuch > Lizenz",
    ]
    assert "# kein Heading" in chunks[3].text
    assert_ranges_match(MARKDOWN, chunks)
    assert [c.ordinal for c in chunks] == list(range(5))


def test_large_markdown_section_is_split_with_ranges() -> None:
    paragraphs = "\n\n".join(f"Absatz {i}: " + "wort " * 40 for i in range(10))
    text = "# Groß\n\n" + paragraphs + "\n"
    chunks = chunk_text("doc.md", text, size=500, overlap=50)
    assert len(chunks) > 2
    assert all(len(c.text) <= 500 for c in chunks)
    assert all(c.heading == "Groß" for c in chunks)
    assert_ranges_match(text, chunks)
    assert chunks[-1].end_line == len(lines_of(text))


PYTHON = """import os


def eins():
    return 1


def zwei():
    x = 2

    return x


class Drei:
    def methode(self):
        return 3
"""


def test_code_packs_blocks_and_keeps_ranges() -> None:
    chunks = chunk_text("mod.py", PYTHON, size=1500, overlap=200)
    assert len(chunks) == 1
    assert (chunks[0].start_line, chunks[0].end_line) == (1, 16)
    assert_ranges_match(PYTHON, chunks)


def test_code_splits_at_function_boundaries_when_small() -> None:
    chunks = chunk_text("mod.py", PYTHON, size=30, overlap=0)
    assert_ranges_match(PYTHON, chunks)
    starts = [lines_of(PYTHON)[c.start_line - 1] for c in chunks]
    assert "def eins():" in starts
    assert "class Drei:" in starts
    # Nie mitten in einer Zeile aufgeteilt, nie leere Ränder.
    assert all(not c.text.startswith("\n") and not c.text.endswith("\n") for c in chunks)


def test_abap_boundaries() -> None:
    abap = (
        "REPORT z_test.\n\nCLASS lcl DEFINITION.\nENDCLASS.\n"
        "METHOD run.\n  WRITE 'x'.\nENDMETHOD.\n"
    )
    chunks = chunk_text("z.abap", abap, size=30, overlap=0)
    starts = [lines_of(abap)[c.start_line - 1] for c in chunks]
    assert "CLASS lcl DEFINITION." in starts
    assert "METHOD run." in starts
    assert_ranges_match(abap, chunks)


def test_plain_text_overlap() -> None:
    text = "\n".join(f"Zeile {i:03d} " + "x" * 20 for i in range(1, 41)) + "\n"
    chunks = chunk_text("notes.txt", text, size=300, overlap=70)
    assert len(chunks) > 3
    assert_ranges_match(text, chunks)
    for previous, current in itertools.pairwise(chunks):
        assert current.start_line <= previous.end_line, "Chunks sollen sich überlappen"
        assert current.start_line > previous.start_line
    assert chunks[0].start_line == 1
    assert chunks[-1].end_line == 40


def test_overlong_line_is_hard_split_with_same_line_number() -> None:
    text = "kurz\n" + "a" * 1000 + "\nende\n"
    chunks = chunk_text("x.txt", text, size=300, overlap=0)
    long_chunks = [c for c in chunks if c.start_line == 2]
    assert len(long_chunks) >= 3
    assert all(c.end_line == 2 for c in long_chunks)
    assert "".join(c.text for c in long_chunks) == "a" * 1000


def test_empty_and_blank_files() -> None:
    assert chunk_text("a.md", "", 100, 10) == []
    assert chunk_text("a.txt", "\n\n  \n", 100, 10) == []
    assert chunk_text("a.py", "\n\n", 100, 10) == []


def test_toml_uses_plain_strategy() -> None:
    text = "[a]\nx = 1\n\n[b]\ny = 2\n"
    chunks = chunk_text("c.toml", text, 1500, 200)
    assert [(c.start_line, c.end_line) for c in chunks] == [(1, 5)]


@pytest.mark.parametrize("size", [50, 120, 400])
def test_split_lines_covers_all_lines(size: int) -> None:
    lines = [(i, f"zeile {i}") for i in range(1, 60)]
    windows = split_lines(lines, size, overlap=20)
    covered = {number for window in windows for number, _ in window}
    assert covered == set(range(1, 60))


def test_embedding_input_has_file_and_heading() -> None:
    chunk = Chunk(0, 5, 7, "pip install lcc", heading="Handbuch > Installation")
    assert embedding_input("docs/README.md", chunk) == (
        "Datei: docs/README.md\nAbschnitt: Handbuch > Installation\npip install lcc"
    )
    assert embedding_input("a.py", Chunk(0, 1, 1, "x")) == "Datei: a.py\nx"
