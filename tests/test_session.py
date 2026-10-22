from __future__ import annotations

import json
from pathlib import Path

import pytest

from lcc.session import Session, SessionError, list_sessions, resolve_session


def test_autosave_appends_jsonl(tmp_path: Path) -> None:
    session = Session(tmp_path / "s", autosave=True, session_id="a")
    session.add({"role": "user", "content": "hallo"})
    session.add(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "list_dir", "arguments": {}}}],
        }
    )
    session.add({"role": "tool", "content": "x", "tool_name": "list_dir", "thinking": "geheim"})
    lines = (tmp_path / "s" / "a.jsonl").read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines]
    assert [r["role"] for r in records] == ["user", "assistant", "tool"]
    assert all("ts" in r for r in records)
    assert records[1]["tool_calls"][0]["function"]["name"] == "list_dir"
    assert records[2]["tool_name"] == "list_dir"
    assert "thinking" not in records[2]
    assert (tmp_path / "s").stat().st_mode & 0o777 == 0o700


def test_history_has_no_timestamps(tmp_path: Path) -> None:
    session = Session(tmp_path, autosave=False)
    session.add({"role": "user", "content": "x"})
    assert session.history() == [{"role": "user", "content": "x"}]


def test_no_file_without_autosave(tmp_path: Path) -> None:
    session = Session(tmp_path / "s", autosave=False)
    session.add({"role": "user", "content": "x"})
    assert not (tmp_path / "s").exists()
    path = session.save()
    assert path.is_file()


def test_save_with_name_and_load_roundtrip(tmp_path: Path) -> None:
    session = Session(tmp_path, autosave=False)
    session.extend([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
    path = session.save("projekt-x")
    assert path == tmp_path / "projekt-x.jsonl"
    loaded = Session.load(tmp_path, "projekt-x", autosave=False)
    assert loaded.history() == session.history()
    assert loaded.session_id == "projekt-x"


@pytest.mark.parametrize("name", ["../x", "a/b", ".hidden", "/"])
def test_save_rejects_bad_names(tmp_path: Path, name: str) -> None:
    session = Session(tmp_path, autosave=False)
    with pytest.raises(SessionError):
        session.save(name)


def test_load_by_prefix_and_ambiguity(tmp_path: Path) -> None:
    for session_id in ("20261012-100000", "20261012-110000", "20261013-090000"):
        Session(tmp_path, autosave=False, session_id=session_id).save()
    assert resolve_session(tmp_path, "20261013").stem == "20261013-090000"
    with pytest.raises(SessionError, match="2 Sessions"):
        resolve_session(tmp_path, "20261012")
    with pytest.raises(SessionError, match="nicht gefunden"):
        resolve_session(tmp_path, "1999")


def test_load_external_file_continues_in_new_session(tmp_path: Path) -> None:
    external = tmp_path / "elsewhere" / "alt.jsonl"
    external.parent.mkdir()
    external.write_text('{"role": "user", "content": "x", "ts": "t"}\n\n', encoding="utf-8")
    sessions = tmp_path / "sessions"
    loaded = Session.load(sessions, str(external), autosave=True)
    assert loaded.history() == [{"role": "user", "content": "x"}]
    assert loaded.path.parent == sessions
    assert loaded.path.is_file()


def test_load_broken_file(tmp_path: Path) -> None:
    (tmp_path / "kaputt.jsonl").write_text("{nope\n", encoding="utf-8")
    with pytest.raises(SessionError, match="Zeile 1"):
        Session.load(tmp_path, "kaputt", autosave=False)


def test_clear_starts_new_session(tmp_path: Path) -> None:
    session = Session(tmp_path, autosave=False, session_id="alt")
    session.add({"role": "user", "content": "x"})
    session.clear()
    assert session.records == []
    assert session.session_id != "alt"


def test_list_sessions_newest_first(tmp_path: Path) -> None:
    import os

    for index, session_id in enumerate(("a", "b")):
        session = Session(tmp_path, autosave=False, session_id=session_id)
        session.add({"role": "user", "content": "x"})
        path = session.save()
        os.utime(path, (1000 + index, 1000 + index))
    infos = list_sessions(tmp_path)
    assert [info.session_id for info in infos] == ["b", "a"]
    assert infos[0].messages == 1
    assert list_sessions(tmp_path / "missing") == []
