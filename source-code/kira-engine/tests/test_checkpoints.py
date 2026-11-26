from __future__ import annotations

import hashlib

import pytest

from kira.checkpoints import CheckpointConflict, CheckpointManager
from kira.store import Store
from kira.workspace import Workspace


@pytest.fixture
def cp(tmp_path):
    ws = Workspace(tmp_path / "ws")
    store = Store(tmp_path / "k.db")
    manager = CheckpointManager(ws, tmp_path / "checkpoints", store, retention=3)
    return ws, store, manager


def write(ws, path, text):
    ws.write_text(path, text)


def test_take_captures_before_state_and_finalize_records_after(cp):
    ws, store, manager = cp
    write(ws, "a.txt", "before")
    row = manager.take(session_id="s1", tool="write_file", call_id="c1", paths=["a.txt"])
    assert row["status"] == "open"
    write(ws, "a.txt", "after")
    done = manager.finalize(row["id"])
    assert done["status"] == "complete"
    assert done["files"][0]["sha256_before"] == hashlib.sha256(b"before").hexdigest()
    assert done["files"][0]["sha256_after"] == hashlib.sha256(b"after").hexdigest()


def test_diff_shows_the_change(cp):
    ws, store, manager = cp
    write(ws, "a.txt", "one\n")
    row = manager.take(session_id="s1", tool="write_file", call_id="c1", paths=["a.txt"])
    write(ws, "a.txt", "two\n")
    manager.finalize(row["id"])
    payload = manager.diff(row["id"])
    assert payload["files"][0]["changed"] is True
    assert "-one" in payload["files"][0]["diff"]
    assert "+two" in payload["files"][0]["diff"]


def test_restore_round_trip(cp):
    ws, store, manager = cp
    write(ws, "a.txt", "before")
    row = manager.take(session_id="s1", tool="write_file", call_id="c1", paths=["a.txt"])
    write(ws, "a.txt", "after")
    manager.finalize(row["id"])
    manager.restore(row["id"])
    assert ws.read_text("a.txt") == "before"
    assert manager.get(row["id"])["status"] == "restored"


def test_restore_conflicts_when_the_file_moved_on(cp):
    ws, store, manager = cp
    write(ws, "a.txt", "before")
    row = manager.take(session_id="s1", tool="write_file", call_id="c1", paths=["a.txt"])
    write(ws, "a.txt", "after")
    manager.finalize(row["id"])
    write(ws, "a.txt", "later")
    with pytest.raises(CheckpointConflict) as caught:
        manager.restore(row["id"])
    assert caught.value.conflicts[0]["path"] == "a.txt"
    manager.restore(row["id"], force=True)
    assert ws.read_text("a.txt") == "before"


def test_a_created_at_tie_lists_and_prunes_by_insertion_order(cp):
    # Windows' clock is coarse enough that two checkpoints land in one tick, and the id is random:
    # ordering the tie by `id` let the older row read newest and let prune delete the newer one.
    _, store, _ = cp
    for checkpoint_id in ("zzz-old", "aaa-new"):
        store._conn.execute(  # noqa: SLF001 - the tie needs timestamps a real clock will not give
            """INSERT INTO checkpoints(id, session_id, tool, call_id, scope, files, status, created_at)
               VALUES(?, NULL, 'write_file', 'c1', 'files', '[]', 'complete', 100.0)""",
            (checkpoint_id,),
        )
    store._conn.commit()

    assert [row["id"] for row in store.list_checkpoints(limit=5)] == ["aaa-new", "zzz-old"]
    assert store.prune_checkpoints(keep=1) == ["zzz-old"]
    assert [row["id"] for row in store.list_checkpoints(limit=5)] == ["aaa-new"]


def test_restore_takes_a_safety_checkpoint(cp):
    ws, store, manager = cp
    write(ws, "a.txt", "before")
    row = manager.take(session_id="s1", tool="write_file", call_id="c1", paths=["a.txt"])
    write(ws, "a.txt", "after")
    manager.finalize(row["id"])
    before_count = len(manager.list(limit=50))
    manager.restore(row["id"])
    rows = manager.list(limit=50)
    assert len(rows) == before_count + 1
    assert rows[0]["tool"] == "restore"


def test_take_of_a_new_file_restore_deletes_it(cp):
    ws, store, manager = cp
    row = manager.take(session_id="s1", tool="write_file", call_id="c1", paths=["new.txt"])
    write(ws, "new.txt", "created")
    manager.finalize(row["id"])
    manager.restore(row["id"])
    assert not (ws.root / "new.txt").exists()


def test_retention_prunes_old_rows_and_dirs(cp, tmp_path):
    ws, store, manager = cp
    for index in range(5):
        write(ws, "a.txt", f"v{index}")
        row = manager.take(session_id="s1", tool="write_file", call_id=f"c{index}", paths=["a.txt"])
        manager.finalize(row["id"])
    rows = manager.list(limit=50)
    assert len(rows) == 3
    for row in rows:
        assert (tmp_path / "checkpoints" / row["id"]).is_dir()
