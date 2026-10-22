"""Suche im RAG-Index: Query embedden → Kosinus (numpy) → min_score → top_k → optional Rerank."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from lcc import texts
from lcc.config import Config
from lcc.ollama_client import OllamaClient, OllamaError
from lcc.rag.indexer import display_path
from lcc.rag.store import Matrix, RagError, Store

RERANK_CANDIDATE_FACTOR = 3
RERANK_TEXT_CHARS = 600

RERANK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["scores"],
    "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
}


@dataclass(frozen=True)
class Hit:
    rank: int
    score: float
    path: str
    start_line: int
    end_line: int
    text: str
    rerank_score: float | None = None


def format_hits(hits: Sequence[Hit]) -> str:
    """Ausgabe an das Modell: [n] pfad:start-end (score 0.xx) + Text."""
    return "\n\n".join(
        f"[{hit.rank}] {hit.path}:{hit.start_line}-{hit.end_line} (score {hit.score:.2f})\n"
        f"{hit.text}"
        for hit in hits
    )


class RagSearcher:
    """Kapselt Store + Client; Query-Embeddings werden pro Prozess gecacht."""

    def __init__(self, config: Config, client: OllamaClient, store: Store, base: Path) -> None:
        self.config = config
        self.client = client
        self.store = store
        self.base = base
        self._query_cache: dict[str, Matrix] = {}

    def embed_queries(self, queries: Sequence[str]) -> None:
        """Mehrere Queries in einer Anfrage vorab embedden (spart Modellwechsel)."""
        missing = [q for q in dict.fromkeys(queries) if q not in self._query_cache]
        if not missing:
            return
        vectors = self.client.embed(self.config.models.embed, missing)
        for query, vector in zip(missing, vectors, strict=True):
            array = np.asarray(vector, dtype=np.float32)
            norm = float(np.linalg.norm(array)) or 1.0
            self._query_cache[query] = (array / norm).reshape(1, -1)

    def query_vector(self, query: str) -> Matrix:
        self.embed_queries([query])
        return self._query_cache[query]

    def search(
        self, query: str, top_k: int | None = None, min_score: float | None = None
    ) -> list[Hit]:
        rag = self.config.rag
        top_k = top_k or rag.top_k
        min_score = rag.min_score if min_score is None else min_score
        self.store.check_model(self.config.models.embed)
        ids, matrix = self.store.matrix()
        if not ids:
            return []
        query_vector = self.query_vector(query)
        self.store.check_model(self.config.models.embed, int(query_vector.shape[1]))
        scores = (matrix @ query_vector.T).ravel()
        rerank = bool(self.config.models.rerank)
        limit = top_k * RERANK_CANDIDATE_FACTOR if rerank else top_k
        order = [i for i in np.argsort(-scores) if scores[i] >= min_score][:limit]
        rows = self.store.get_chunks([ids[i] for i in order])
        hits = [
            Hit(
                rank=0,
                score=float(scores[i]),
                path=display_path(Path(rows[ids[i]].path), self.base),
                start_line=rows[ids[i]].start_line,
                end_line=rows[ids[i]].end_line,
                text=rows[ids[i]].text,
            )
            for i in order
        ]
        if rerank and len(hits) > 1:
            hits = self._rerank(query, hits)
        return [replace(hit, rank=n) for n, hit in enumerate(hits[:top_k], 1)]

    def _rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        """Rerank über das Modell models.rerank (strukturierte Ausgabe: ein Score je Treffer)."""
        passages = "\n\n".join(
            f"[{n}] {hit.text[:RERANK_TEXT_CHARS]}" for n, hit in enumerate(hits, 1)
        )
        prompt = texts.RAG_RERANK_PROMPT.format(query=query, count=len(hits), passages=passages)
        try:
            result = self.client.chat(
                self.config.models.rerank,
                [{"role": "user", "content": prompt}],
                format=RERANK_SCHEMA,
                options={"temperature": 0},
            )
            scores = json.loads(result.content)["scores"]
        except (OllamaError, ValueError, KeyError, TypeError):
            return hits  # Rerank ist optional – bei Problemen Kosinus-Reihenfolge behalten
        if not isinstance(scores, list) or len(scores) != len(hits):
            return hits
        rescored = [
            replace(hit, rerank_score=float(score))
            for hit, score in zip(hits, scores, strict=True)
            if isinstance(score, int | float)
        ]
        if len(rescored) != len(hits):
            return hits
        return sorted(rescored, key=lambda h: (-(h.rerank_score or 0.0), -h.score))


def open_searcher(
    config: Config, client: OllamaClient, *, enabled: bool = True
) -> RagSearcher | None:
    """Searcher, wenn RAG aktiv ist und ein Index existiert – sonst None."""
    if not (enabled and config.rag.enabled and config.models.embed):
        return None
    if not config.rag.index_path.is_file():
        return None
    store = Store(config.rag.index_path)
    if store.stats()[1] == 0:
        store.close()
        return None
    return RagSearcher(config, client, store, config.workspace.root)


def require_searcher(config: Config, client: OllamaClient) -> RagSearcher:
    """Wie open_searcher, aber mit verständlichem Fehler statt None."""
    if not config.rag.enabled:
        raise RagError(texts.RAG_DISABLED)
    searcher = open_searcher(config, client)
    if searcher is None:
        raise RagError(texts.RAG_NO_INDEX.format(path=config.rag.index_path))
    return searcher
