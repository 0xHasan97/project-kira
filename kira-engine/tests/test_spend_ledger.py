from __future__ import annotations

import time

from kira.store import Store


def add_turn(store, provider="fast_one", usage=None, when=None):
    sid = store.create_session("AUTO")
    store.add_message(
        sid, "assistant", "hi",
        provider=provider, model="mini",
        usage=usage or {"input_tokens": 10, "output_tokens": 5},
    )
    if when is not None:
        store._conn.execute("UPDATE messages SET created_at=? WHERE session_id=?", (when, sid))
        store._conn.commit()
    return sid


def test_ledger_is_written_with_the_message(tmp_path):
    store = Store(tmp_path / "k.db")
    add_turn(store)
    _, spend = store.usage_for_month()
    assert spend == {"fast_one": 15}
    store.close()


def test_deleting_every_session_does_not_rearm_the_cap(tmp_path):
    # The cap reads money, and money outlives the transcript: clearing history is not a refund.
    store = Store(tmp_path / "k.db")
    add_turn(store)
    store.clear_sessions()
    _, spend = store.usage_for_month()
    assert spend == {"fast_one": 15}
    store.close()


def test_deleting_one_session_keeps_its_spend(tmp_path):
    store = Store(tmp_path / "k.db")
    sid = add_turn(store)
    store.delete_session(sid)
    assert store.usage_for_month()[1] == {"fast_one": 15}
    store.close()


def test_migration_backfills_existing_messages(tmp_path):
    path = tmp_path / "k.db"
    store = Store(path)
    sid = store.create_session("AUTO")
    # Simulate a pre-ledger database: drop the ledger row, reset the version.
    store.add_message(sid, "assistant", "old", provider="big", model="max", usage={"input_tokens": 7, "output_tokens": 3})
    store._conn.execute("DELETE FROM usage_ledger")
    store._conn.execute("PRAGMA user_version=0")
    store._conn.commit()
    store.close()

    reopened = Store(path)
    assert reopened.usage_for_month()[1] == {"big": 10}
    reopened.close()


def test_month_boundaries_use_utc(tmp_path):
    store = Store(tmp_path / "k.db")
    add_turn(store)
    january = time.mktime((2020, 1, 15, 12, 0, 0, 0, 0, -1))
    store._conn.execute("UPDATE messages SET created_at=?", (january,))
    store._conn.execute("UPDATE usage_ledger SET month='2020-01'")
    store._conn.commit()
    assert store.usage_for_month("2020-01")[1] == {"fast_one": 15}
    assert store.usage_for_month("2020-02")[1] == {}
    store.close()
