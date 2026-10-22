"""Inkrementelles Indexieren der RAG-Quellen (Hash + mtime), Batch-Embedding."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from lcc import texts
from lcc.config import Config
from lcc.ollama_client import OllamaClient
from lcc.rag.chunker import Chunk, chunk_text, embedding_input
from lcc.rag.store import DocumentRow, Matrix, RagError, Store

EMBED_BATCH_SIZE = 32
MAX_FILE_BYTES = 2_000_000

Progress = Callable[[int, int, str], None]


@dataclass
class IndexReport:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    skipped: int = 0
    chunks_embedded: int = 0
    missing_sources: list[Path] = field(default_factory=list)


def display_path(path: Path, base: Path) -> str:
    """Pfad für Anzeige und Embedding: relativ zum Projekt, sonst mit ~ abgekürzt."""
    if path.is_relative_to(base):
        return path.relative_to(base).as_posix()
    home = Path.home()
    if path.is_relative_to(home):
        return "~/" + path.relative_to(home).as_posix()
    return path.as_posix()


def _is_ignored(path: Path, root: Path, ignore: Sequence[str]) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        rel = path.as_posix()
    parts = rel.split("/")
    for pattern in ignore:
        pattern = pattern.strip("/")
        if "/" in pattern:
            if fnmatch.fnmatch(rel, pattern) or rel.endswith("/" + pattern) or rel == pattern:
                return True
        elif any(fnmatch.fnmatch(part, pattern) for part in parts):
            return True
    return False


def iter_source_files(
    sources: Sequence[Path], include: Sequence[str], ignore: Sequence[str]
) -> Iterator[Path]:
    """Alle Dateien aus den Quellen, die auf include passen und nicht ignoriert sind."""
    seen: set[Path] = set()
    for source in sources:
        if source.is_file():
            candidates: Iterator[Path] = iter([source])
            root = source.parent
        elif source.is_dir():
            root = source
            candidates = _walk(source, ignore)
        else:
            continue
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen or not any(fnmatch.fnmatch(path.name, p) for p in include):
                continue
            if _is_ignored(path, root, ignore):
                continue
            seen.add(resolved)
            yield resolved


def _walk(root: Path, ignore: Sequence[str]) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = sorted(d for d in dirnames if not _is_ignored(current / d, root, ignore))
        for name in sorted(filenames):
            yield current / name


def embed_texts(client: OllamaClient, model: str, inputs: Sequence[str]) -> Matrix:
    """Embeddings in Batches à 32."""
    vectors: list[list[float]] = []
    for start in range(0, len(inputs), EMBED_BATCH_SIZE):
        vectors += client.embed(model, list(inputs[start : start + EMBED_BATCH_SIZE]))
    return np.asarray(vectors, dtype=np.float32).reshape(len(vectors), -1)


class Indexer:
    def __init__(
        self, config: Config, client: OllamaClient, store: Store, base: Path | None = None
    ) -> None:
        self.config = config
        self.client = client
        self.store = store
        self.base = base or config.workspace.root
        self.model = config.models.embed
        if not self.model:
            raise RagError(texts.RAG_NO_EMBED_MODEL)

    def run(self, *, rebuild: bool = False, progress: Progress | None = None) -> IndexReport:
        rag = self.config.rag
        report = IndexReport(missing_sources=[s for s in rag.sources if not s.exists()])
        if rebuild:
            self.store.clear()
        else:
            self.store.check_model(self.model)

        files = list(iter_source_files(rag.sources, rag.include, self.config.workspace.ignore))
        known = self.store.documents()
        seen: set[str] = set()
        for number, path in enumerate(files, 1):
            key = str(path)
            seen.add(key)
            if progress is not None:
                progress(number, len(files), display_path(path, self.base))
            self._index_file(path, known.get(key), report)

        for key in set(known) - seen:
            self.store.delete_document(key)
            report.removed += 1
        return report

    def _index_file(self, path: Path, row: DocumentRow | None, report: IndexReport) -> None:
        try:
            stat = path.stat()
        except OSError:
            report.skipped += 1
            return
        if row is not None and row.mtime == stat.st_mtime and row.size == stat.st_size:
            report.unchanged += 1
            return
        if stat.st_size > MAX_FILE_BYTES:
            report.skipped += 1
            return
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            report.skipped += 1
            return
        sha = hashlib.sha256(data).hexdigest()
        if row is not None and row.sha256 == sha:
            self.store.touch_document(str(path), stat.st_mtime, stat.st_size)
            report.unchanged += 1
            return

        rag = self.config.rag
        shown = display_path(path, self.base)
        chunks = chunk_text(
            path.name,
            data.decode("utf-8", errors="replace"),
            rag.chunk_size_chars,
            rag.chunk_overlap_chars,
        )
        embeddings = self._embed(shown, chunks)
        self.store.upsert_document(str(path), sha, stat.st_mtime, stat.st_size, chunks, embeddings)
        report.chunks_embedded += len(chunks)
        if row is None:
            report.added += 1
        else:
            report.updated += 1

    def _embed(self, shown: str, chunks: Sequence[Chunk]) -> Matrix:
        if not chunks:
            return np.zeros((0, self.store.dimension or 0), dtype=np.float32)
        inputs = [embedding_input(shown, chunk) for chunk in chunks]
        vectors = embed_texts(self.client, self.model, inputs)
        dimension = int(vectors.shape[1])
        if self.store.embed_model is None:
            self.store.init_model(self.model, dimension)
        else:
            self.store.check_model(self.model, dimension)
        return vectors
