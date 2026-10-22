"""Sessions: Verlauf als JSONL (eine Datei je Session) unter session.sessions_dir.

Jede Zeile: role, content, tool_calls (optional), tool_name (optional), ts.
Thinking wird nie gespeichert (ChatResult.as_message lässt es weg).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lcc import texts
from lcc.ollama_client import Message

SUFFIX = ".jsonl"
_STORED_KEYS = ("role", "content", "tool_calls", "tool_name")


class SessionError(Exception):
    pass


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    path: Path
    modified: datetime
    messages: int


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class Session:
    def __init__(self, directory: Path, *, autosave: bool, session_id: str | None = None) -> None:
        self.directory = directory
        self.autosave = autosave
        self.session_id = session_id or new_session_id()
        self.records: list[dict[str, Any]] = []

    @property
    def path(self) -> Path:
        return self.directory / f"{self.session_id}{SUFFIX}"

    def history(self) -> list[Message]:
        """Nachrichten für das Modell (ohne Zeitstempel)."""
        return [{k: v for k, v in record.items() if k != "ts"} for record in self.records]

    def _ensure_dir(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)

    def add(self, message: Message) -> None:
        record = {k: message[k] for k in _STORED_KEYS if message.get(k) is not None}
        record.setdefault("content", "")
        record["ts"] = datetime.now().isoformat(timespec="seconds")
        self.records.append(record)
        if self.autosave:
            self._ensure_dir()
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def extend(self, messages: Iterable[Message]) -> None:
        for message in messages:
            self.add(message)

    def clear(self) -> None:
        """Verlauf leeren; danach beginnt eine neue Session-Datei."""
        self.records = []
        self.session_id = new_session_id()

    def save(self, name: str | None = None) -> Path:
        """Gesamten Verlauf schreiben (optional unter eigenem Namen)."""
        if name:
            _check_name(name)
            self.session_id = name
        self._ensure_dir()
        lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.records)
        self.path.write_text(lines, encoding="utf-8")
        return self.path

    @classmethod
    def load(cls, directory: Path, ref: str, *, autosave: bool) -> Session:
        """Lädt eine Session über ID, eindeutiges ID-Präfix oder Pfad."""
        path = resolve_session(directory, ref)
        session = cls(directory, autosave=autosave, session_id=path.stem)
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SessionError(texts.SESSION_BROKEN.format(path=path, line=line_no)) from exc
            if isinstance(record, dict) and "role" in record:
                session.records.append(record)
        if path.parent != directory:
            # Fremde Datei: weitere Nachrichten in eine neue Session im Standardordner.
            session.session_id = new_session_id()
            if autosave:
                session.save()
        return session


def _check_name(name: str) -> None:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise SessionError(texts.SESSION_BAD_NAME.format(name=name))


def list_sessions(directory: Path) -> list[SessionInfo]:
    """Gespeicherte Sessions, neueste zuerst."""
    if not directory.is_dir():
        return []
    infos: list[SessionInfo] = []
    for path in directory.glob(f"*{SUFFIX}"):
        try:
            count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
        except OSError:
            continue
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        infos.append(SessionInfo(path.stem, path, modified, count))
    return sorted(infos, key=lambda info: info.modified, reverse=True)


def resolve_session(directory: Path, ref: str) -> Path:
    candidate = Path(ref).expanduser()
    if candidate.suffix == SUFFIX and candidate.is_file():
        return candidate
    exact = directory / f"{ref}{SUFFIX}"
    if exact.is_file():
        return exact
    matches = [info.path for info in list_sessions(directory) if info.session_id.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SessionError(texts.SESSION_NOT_FOUND.format(ref=ref))
    raise SessionError(texts.SESSION_AMBIGUOUS.format(ref=ref, count=len(matches)))
