from __future__ import annotations

import dataclasses
import itertools
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from lcc.agent.sandbox import Sandbox
from lcc.agent.tools import ToolContext, available_tool_names, default_registry
from lcc.config import Config, default_config
from lcc.ollama_client import OllamaClient, ToolCall
from lcc.rag.indexer import Indexer, display_path, iter_source_files
from lcc.rag.search import RagSearcher, format_hits, open_searcher, require_searcher
from lcc.rag.store import RagError, Store
from tests.fake_ollama import FakeOllama, keyword_embedding


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    docs = root / "docs"
    (docs / "sub").mkdir(parents=True)
    (root / ".git").mkdir()
    (docs / "config.md").write_text(
        "# Config\n\nDie config steht in einer toml Datei.\n\n## Server\n\nDer ollama server.\n",
        encoding="utf-8",
    )
    (docs / "tiere.txt").write_text("Die katze und der hund.\n", encoding="utf-8")
    (docs / "sub" / "rag.md").write_text("# RAG\n\nDer rag index.\n", encoding="utf-8")
    (docs / "bild.png").write_bytes(b"\x89PNG\0\0")
    (docs / "__pycache__").mkdir()
    (docs / "__pycache__" / "x.md").write_text("config", encoding="utf-8")
    return root


def make_config(project: Path, **rag: Any) -> Config:
    config = default_config(project)
    rag_config = dataclasses.replace(
        config.rag,
        sources=(project / "docs",),
        index_path=project / ".lcc" / "index.db",
        min_score=0.1,
        **rag,
    )
    return dataclasses.replace(config, rag=rag_config)


def fake_server(embed_model: str = "bge-m3") -> FakeOllama:
    fake = FakeOllama(embed_fn=keyword_embedding)
    fake.add_model(f"{embed_model}:latest", capabilities=("embedding",))
    return fake


def client_for(fake: FakeOllama) -> OllamaClient:
    return OllamaClient("http://x:1", transport=fake.transport())


def index(project: Path, fake: FakeOllama, config: Config | None = None, **kwargs: Any) -> Any:
    config = config or make_config(project)
    with Store(config.rag.index_path) as store:
        return Indexer(config, client_for(fake), store).run(**kwargs)


def embed_calls(fake: FakeOllama) -> list[list[str]]:
    return [body["input"] for path, body in fake.requests if path == "/api/embed"]


# -- Dateiauswahl ------------------------------------------------------------


def test_iter_source_files_include_and_ignore(project: Path) -> None:
    config = make_config(project)
    files = list(iter_source_files(config.rag.sources, config.rag.include, config.workspace.ignore))
    names = sorted(p.relative_to(project / "docs").as_posix() for p in files)
    assert names == ["config.md", "sub/rag.md", "tiere.txt"]


def test_display_path(project: Path) -> None:
    assert display_path(project / "docs" / "a.md", project) == "docs/a.md"
    assert display_path(Path.home() / "rag-docs" / "x.md", project) == "~/rag-docs/x.md"


# -- Inkrementelles Indexing (Pflicht-Test) ----------------------------------


def test_incremental_indexing(project: Path) -> None:
    fake = fake_server()
    report = index(project, fake)
    assert (report.added, report.updated, report.unchanged, report.removed) == (3, 0, 0, 0)
    first_embeds = len(embed_calls(fake))
    assert first_embeds == 3

    # Nichts geändert → keine Embeddings
    report = index(project, fake)
    assert (report.added, report.unchanged) == (0, 3)
    assert len(embed_calls(fake)) == first_embeds

    # Nur mtime geändert, Inhalt gleich → Hash gleich, kein Embedding
    tiere = project / "docs" / "tiere.txt"
    os.utime(tiere, (1_000_000, 1_000_000))
    report = index(project, fake)
    assert report.unchanged == 3
    assert len(embed_calls(fake)) == first_embeds

    # Inhalt geändert → nur diese Datei neu
    tiere.write_text("Nur noch die katze.\n", encoding="utf-8")
    report = index(project, fake)
    assert (report.updated, report.unchanged) == (1, 2)
    assert embed_calls(fake)[-1] == ["Datei: docs/tiere.txt\nNur noch die katze."]

    # Datei gelöscht → aus dem Index entfernt
    (project / "docs" / "sub" / "rag.md").unlink()
    report = index(project, fake)
    assert report.removed == 1
    with Store(project / ".lcc" / "index.db") as store:
        assert store.stats() == (2, 3)
        assert all("rag.md" not in path for path in store.documents())


def test_index_stores_meta_and_normalized_vectors(project: Path) -> None:
    index(project, fake_server())
    with Store(project / ".lcc" / "index.db") as store:
        assert store.embed_model == "bge-m3"
        assert store.dimension == 10
        _, matrix = store.matrix()
        assert matrix.dtype == np.float32
        assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0, atol=1e-5)


def test_embedding_input_contains_file_and_heading(project: Path) -> None:
    fake = fake_server()
    index(project, fake)
    inputs = [text for batch in embed_calls(fake) for text in batch]
    assert (
        "Datei: docs/config.md\nAbschnitt: Config > Server\n## Server\n\nDer ollama server."
        in inputs
    )


def test_batches_of_32(project: Path) -> None:
    big = "\n\n".join(f"Absatz {i} " + "wort " * 10 for i in range(80))
    (project / "docs" / "gross.txt").write_text(big, encoding="utf-8")
    fake = fake_server()
    config = make_config(project, chunk_size_chars=60, chunk_overlap_chars=0)
    index(project, fake, config)
    sizes = [len(batch) for batch in embed_calls(fake)]
    assert max(sizes) == 32
    assert sum(sizes) > 64


def test_skips_binary_files(project: Path) -> None:
    (project / "docs" / "binär.txt").write_bytes(b"abc\0def")
    report = index(project, fake_server())
    assert report.skipped == 1


def test_model_change_requires_rebuild(project: Path) -> None:
    index(project, fake_server("bge-m3"))
    config = make_config(project)
    other = dataclasses.replace(config, models=dataclasses.replace(config.models, embed="nomic"))
    fake = fake_server("nomic")
    with pytest.raises(RagError, match="--rebuild"):
        index(project, fake, other)
    report = index(project, fake, other, rebuild=True)
    assert report.added == 3
    with Store(project / ".lcc" / "index.db") as store:
        assert store.embed_model == "nomic"


def test_dimension_change_requires_rebuild(project: Path) -> None:
    index(project, fake_server())
    fake = fake_server()
    fake.embed_fn = lambda text: [1.0, 2.0]
    (project / "docs" / "neu.md").write_text("neu", encoding="utf-8")
    with pytest.raises(RagError, match="Dimension"):
        index(project, fake)


def test_missing_sources_reported(project: Path) -> None:
    config = make_config(project)
    config = dataclasses.replace(
        config, rag=dataclasses.replace(config.rag, sources=(project / "docs", project / "nope"))
    )
    report = index(project, fake_server(), config)
    assert report.missing_sources == [project / "nope"]


# -- Suche -------------------------------------------------------------------


def searcher(project: Path, fake: FakeOllama, config: Config | None = None) -> RagSearcher:
    config = config or make_config(project)
    found = open_searcher(config, client_for(fake))
    assert found is not None
    return found


def test_search_ranks_by_similarity(project: Path) -> None:
    fake = fake_server()
    index(project, fake)
    hits = searcher(project, fake).search("Wo ist die katze?")
    assert hits[0].path == "docs/tiere.txt"
    assert hits[0].rank == 1
    assert (hits[0].start_line, hits[0].end_line) == (1, 1)
    assert all(a.score >= b.score for a, b in itertools.pairwise(hits))


def test_search_min_score_and_top_k(project: Path) -> None:
    fake = fake_server()
    index(project, fake)
    config = make_config(project)
    high = dataclasses.replace(config, rag=dataclasses.replace(config.rag, min_score=0.9))
    assert [h.path for h in searcher(project, fake, high).search("katze hund")] == [
        "docs/tiere.txt"
    ]
    assert len(searcher(project, fake).search("config", top_k=1)) == 1


def test_query_embeddings_are_cached_and_batched(project: Path) -> None:
    fake = fake_server()
    index(project, fake)
    rag = searcher(project, fake)
    before = len(embed_calls(fake))
    rag.embed_queries(["katze", "config"])
    rag.search("katze")
    rag.search("config")
    assert embed_calls(fake)[before:] == [["katze", "config"]]


def test_format_hits(project: Path) -> None:
    fake = fake_server()
    index(project, fake)
    text = format_hits(searcher(project, fake).search("katze", top_k=1))
    assert text.startswith("[1] docs/tiere.txt:1-1 (score ")
    assert text.endswith("Die katze und der hund.")


def test_open_searcher_none_without_index(project: Path) -> None:
    config = make_config(project)
    assert open_searcher(config, client_for(fake_server())) is None
    with pytest.raises(RagError, match="lcc rag index"):
        require_searcher(config, client_for(fake_server()))
    disabled = dataclasses.replace(config, rag=dataclasses.replace(config.rag, enabled=False))
    with pytest.raises(RagError, match="abgeschaltet"):
        require_searcher(disabled, client_for(fake_server()))


def test_search_with_wrong_model_fails(project: Path) -> None:
    fake = fake_server()
    index(project, fake)
    config = make_config(project)
    other = dataclasses.replace(config, models=dataclasses.replace(config.models, embed="nomic"))
    with pytest.raises(RagError, match="--rebuild"):
        searcher(project, fake, other).search("katze")


def test_rerank_reorders(project: Path) -> None:
    fake = fake_server()
    fake.add_model("reranker:1b")
    index(project, fake)
    config = make_config(project)
    config = dataclasses.replace(
        config, models=dataclasses.replace(config.models, rerank="reranker:1b")
    )
    rag = searcher(project, fake, config)
    plain = rag.search("katze config", top_k=3)
    assert len(plain) >= 2
    # Fake-Antwort: dem bisher letzten Treffer die höchste Bewertung geben
    scores = [0.0] * len(plain)
    scores[-1] = 10.0
    fake.chat_replies.append(
        [
            {
                "message": {"role": "assistant", "content": json.dumps({"scores": scores})},
                "done": True,
            }
        ]
    )
    reranked = rag.search("katze config", top_k=3)
    assert reranked[0].path == plain[-1].path
    assert reranked[0].rerank_score == 10.0
    chat = [body for path, body in fake.requests if path == "/api/chat"][-1]
    assert chat["model"] == "reranker:1b"
    assert chat["format"]["required"] == ["scores"]


def test_rerank_failure_keeps_cosine_order(project: Path) -> None:
    fake = fake_server()
    fake.add_model("reranker:1b")
    index(project, fake)
    config = make_config(project)
    config = dataclasses.replace(
        config, models=dataclasses.replace(config.models, rerank="reranker:1b")
    )
    fake.chat_replies.append(
        [{"message": {"role": "assistant", "content": "kein json"}, "done": True}]
    )
    rag = searcher(project, fake, config)
    hits = rag.search("katze config", top_k=3)
    assert [h.rerank_score for h in hits] == [None] * len(hits)


# -- Tool rag_search ---------------------------------------------------------


def test_rag_search_tool_only_with_index(project: Path) -> None:
    fake = fake_server()
    config = make_config(project)
    ctx = ToolContext(config=config, sandbox=Sandbox(project))
    registry = default_registry()
    assert "rag_search" not in available_tool_names(registry, ctx)
    result = registry.execute(ToolCall("rag_search", {"query": "x"}), ctx)
    assert not result.ok

    index(project, fake)
    ctx.rag = searcher(project, fake)
    assert "rag_search" in available_tool_names(registry, ctx)
    result = registry.execute(ToolCall("rag_search", {"query": "katze", "top_k": 1}), ctx)
    assert result.ok
    assert result.content.startswith("[1] docs/tiere.txt:1-1")
    none = registry.execute(ToolCall("rag_search", {"query": "zebra"}), ctx)
    assert "Keine Treffer" in none.content
