"""SQLite-Store für RAG: Dokumente, Chunks (Embeddings als float32-BLOB) und Meta-Daten."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from lcc import texts
from lcc.rag.chunker import Chunk

Matrix = npt.NDArray[np.float32]

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    text TEXT NOT NULL,
    embedding BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_embeddings (
    name TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    embedding BLOB NOT NULL
);
"""


class RagError(Exception):
    """RAG-Fehler mit Nutzertext (Exit-Code 1)."""


@dataclass(frozen=True)
class DocumentRow:
    id: int
    path: str
    sha256: str
    mtime: float
    size: int


@dataclass(frozen=True)
class ChunkRow:
    id: int
    path: str
    start_line: int
    end_line: int
    text: str


def normalize(vectors: Matrix) -> Matrix:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        self._matrix: Matrix | None = None
        self._chunk_ids: list[int] = []

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- Meta ---------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.db.commit()

    @property
    def embed_model(self) -> str | None:
        return self.get_meta("embed_model")

    @property
    def dimension(self) -> int | None:
        value = self.get_meta("dimension")
        return None if value is None else int(value)

    def check_model(self, embed_model: str, dimension: int | None = None) -> None:
        """Abbruch, wenn der Index mit einem anderen Modell/einer anderen Dimension gebaut wurde."""
        stored = self.embed_model
        if stored is not None and stored != embed_model:
            raise RagError(texts.RAG_MODEL_MISMATCH.format(stored=stored, current=embed_model))
        stored_dim = self.dimension
        if dimension is not None and stored_dim is not None and stored_dim != dimension:
            raise RagError(
                texts.RAG_DIMENSION_MISMATCH.format(stored=stored_dim, current=dimension)
            )

    def init_model(self, embed_model: str, dimension: int) -> None:
        self.check_model(embed_model, dimension)
        self.set_meta("embed_model", embed_model)
        self.set_meta("dimension", str(dimension))

    def clear(self) -> None:
        """Alles löschen (für --rebuild)."""
        self.db.executescript(
            "DELETE FROM chunks; DELETE FROM documents; DELETE FROM meta; "
            "DELETE FROM skill_embeddings;"
        )
        self.db.commit()
        self._matrix = None

    # -- Dokumente ----------------------------------------------------------

    def documents(self) -> dict[str, DocumentRow]:
        rows = self.db.execute("SELECT id, path, sha256, mtime, size FROM documents")
        return {row[1]: DocumentRow(*row) for row in rows}

    def upsert_document(
        self,
        path: str,
        sha256: str,
        mtime: float,
        size: int,
        chunks: Sequence[Chunk],
        embeddings: Matrix,
    ) -> None:
        """Ersetzt ein Dokument samt Chunks in einer Transaktion."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks und embeddings passen nicht zusammen")
        vectors = normalize(np.asarray(embeddings, dtype=np.float32)) if len(chunks) else embeddings
        with self.db:
            self.db.execute("DELETE FROM documents WHERE path = ?", (path,))
            cursor = self.db.execute(
                "INSERT INTO documents(path, sha256, mtime, size) VALUES(?, ?, ?, ?)",
                (path, sha256, mtime, size),
            )
            document_id = cursor.lastrowid
            self.db.executemany(
                "INSERT INTO chunks(document_id, ordinal, start_line, end_line, text, embedding) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [
                    (
                        document_id,
                        chunk.ordinal,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.text,
                        vectors[index].tobytes(),
                    )
                    for index, chunk in enumerate(chunks)
                ],
            )
        self._matrix = None

    def touch_document(self, path: str, mtime: float, size: int) -> None:
        """Inhalt unverändert (gleicher Hash) – nur mtime/size aktualisieren."""
        with self.db:
            self.db.execute(
                "UPDATE documents SET mtime = ?, size = ? WHERE path = ?", (mtime, size, path)
            )

    def delete_document(self, path: str) -> None:
        with self.db:
            self.db.execute("DELETE FROM documents WHERE path = ?", (path,))
        self._matrix = None

    # -- Suche --------------------------------------------------------------

    def matrix(self) -> tuple[list[int], Matrix]:
        """Alle Embeddings als Matrix (gecacht bis zur nächsten Änderung)."""
        if self._matrix is None:
            rows = self.db.execute("SELECT id, embedding FROM chunks ORDER BY id").fetchall()
            self._chunk_ids = [int(row[0]) for row in rows]
            if rows:
                self._matrix = np.vstack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
            else:
                self._matrix = np.zeros((0, self.dimension or 0), dtype=np.float32)
        return self._chunk_ids, self._matrix

    def get_chunks(self, ids: Sequence[int]) -> dict[int, ChunkRow]:
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        rows = self.db.execute(
            "SELECT c.id, d.path, c.start_line, c.end_line, c.text FROM chunks c "
            f"JOIN documents d ON d.id = c.document_id WHERE c.id IN ({placeholders})",
            list(ids),
        )
        return {row[0]: ChunkRow(*row) for row in rows}

    # -- Skill-Embeddings (Cache für die Skill-Vorauswahl) -------------------

    def get_skill_embedding(self, name: str, sha256: str) -> Matrix | None:
        row = self.db.execute(
            "SELECT embedding FROM skill_embeddings WHERE name = ? AND sha256 = ?", (name, sha256)
        ).fetchone()
        return None if row is None else np.frombuffer(row[0], dtype=np.float32).reshape(1, -1)

    def set_skill_embedding(self, name: str, sha256: str, vector: Matrix) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO skill_embeddings(name, sha256, embedding) VALUES(?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET sha256 = excluded.sha256, "
                "embedding = excluded.embedding",
                (name, sha256, normalize(vector.reshape(1, -1)).tobytes()),
            )

    def stats(self) -> tuple[int, int]:
        documents = self.db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunks = self.db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        return int(documents), int(chunks)
