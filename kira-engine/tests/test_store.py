from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

from kira.errors import ConfigError
from kira.store import Store, month_bounds


def ts(year: int, month: int, day: int, hour: int = 12) -> float:
    return datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp()


def october() -> tuple[float, float]:
    _, start, end = month_bounds("2026-10")
    return start, end


def test_month_bounds_is_a_half_open_utc_window():
    label, start, end = month_bounds("2026-10")
    assert label == "2026-10"
    assert start == ts(2026, 10, 1, 0)
    assert end == ts(2026, 11, 1, 0)
    assert end - start == 31 * 86400


def test_month_bounds_rolls_the_year_over():
    _, start, end = month_bounds("2026-12")
    assert datetime.fromtimestamp(end, timezone.utc).year == 2027


def test_month_bounds_rejects_nonsense():
    for bad in ("2026-13", "10-2026", "2026-1", "next month", ""):
        try:
            month_bounds(bad)
        except ConfigError:
            pass
        else:
            raise AssertionError(f"{bad!r} should not parse as a month")


def test_month_bounds_defaults_to_the_current_month():
    label, _, _ = month_bounds()
    assert label == datetime.now(timezone.utc).strftime("%Y-%m")


def test_spend_counts_turns_that_did_not_finish(tmp_path):
    """An interrupted answer still consumed tokens; skipping it understates the bill."""
    store = Store(tmp_path / "kira.db")
    store.create_session("AUTO", "sess-1")
    start, end = october()
    rows = (("complete", 60, 40), ("interrupted", 25, 5), ("failed", 0, 0))
    for offset, (status, tokens_in, tokens_out) in enumerate(rows):
        store._conn.execute(  # noqa: SLF001 - one window, three statuses, no clock drift
            """INSERT INTO messages(session_id, role, content, provider, model, status,
                                     tool_calls, usage, chain, created_at)
               VALUES('sess-1','assistant','a','groq','mini',?,'[]',?,'[]',?)""",
            (status, f'{{"input_tokens": {tokens_in}, "output_tokens": {tokens_out}}}', start + offset),
        )
        # The cap reads the ledger, so a raw row is only half a turn: charge it too.
        store.record_usage("groq", {"input_tokens": tokens_in, "output_tokens": tokens_out}, when=start + offset)
    store._conn.commit()
    assert store.monthly_spend(start, end) == {"groq": 130}
    store.close()


def test_spend_is_scoped_to_one_month(tmp_path):
    store = Store(tmp_path / "kira.db")
    store.create_session("AUTO", "sess-1")
    # Two rows in October, one in September: only the window may count.
    for when, tokens in ((ts(2026, 10, 5), 15), (ts(2026, 10, 20), 15), (ts(2026, 9, 30), 999)):
        store._conn.execute(  # noqa: SLF001 - seeding an exact timestamp
            """INSERT INTO messages(session_id, role, content, provider, model, status,
                                     tool_calls, usage, chain, created_at)
               VALUES('sess-1','assistant','a','groq','mini','complete','[]',?, '[]', ?)""",
            (f'{{"input_tokens": {tokens // 2}, "output_tokens": {tokens - tokens // 2}}}', when),
        )
        store.record_usage("groq", {"input_tokens": tokens // 2, "output_tokens": tokens - tokens // 2}, when=when)
    store._conn.commit()
    start, end = october()
    assert store.monthly_spend(start, end) == {"groq": 30}
    _, sep_start, sep_end = month_bounds("2026-09")
    assert store.monthly_spend(sep_start, sep_end) == {"groq": 999}
    store.close()


def seed_at(store: Store, first_created: float, day: float) -> str:
    """Three assistant rows in one day: one served, one interrupted, one failed."""
    sid = store.create_session("AUTO", "sess-1")
    rows = [
        ("a1", "groq", "mini", "complete", 10, 5, [{"provider": "groq", "event": "served"}]),
        ("half", "groq", "mini", "interrupted", 8, 2, [{"provider": "groq", "event": "aborted_mid_stream", "reason": "client saw text"}]),
        ("", "ant", "claude", "failed", 0, 0, [{"provider": "ant", "event": "failed", "reason": "provider_5xx status=503 down"}]),
    ]
    for offset, (content, provider, model, status, tokens_in, tokens_out, chain) in enumerate(rows):
        store._conn.execute(  # noqa: SLF001 - a test needs timestamps it controls
            """INSERT INTO messages(session_id, role, content, provider, model, finish_reason,
                                     status, tool_calls, usage, chain, created_at)
               VALUES(?, 'assistant', ?,?,?,NULL,?,'[]',?,?,?)""",
            (sid, content, provider, model, status,
             f'{{"input_tokens": {tokens_in}, "output_tokens": {tokens_out}}}',
             json.dumps(chain), day + offset),
        )
        store.record_usage(provider, {"input_tokens": tokens_in, "output_tokens": tokens_out}, when=day + offset)
    store._conn.execute(
        "INSERT INTO messages(session_id, role, content, created_at) VALUES(?, 'user', 'q1', ?)",
        (sid, first_created),
    )
    store._conn.commit()
    return sid


def test_overview_aggregates_split_the_way_the_spec_defines_them(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    sid = seed_at(store, start + 3600 * 24 * 4, ts(2026, 10, 5))
    view = store.overview(start, end)
    assert view["month"] == "2026-10"
    assert view["turns"] == 3
    assert view["tokens"] == {"input": 18, "output": 7}
    assert view["interrupted"] == 1 and view["failed"] == 1
    assert view["success_rate"] == round(1 / 3, 3)
    assert view["by_provider"] == [{"provider": "ant", "turns": 1, "tokens": 0},
                                   {"provider": "groq", "turns": 2, "tokens": 25}]
    assert view["by_model"][0] == {"provider": "groq", "model": "mini", "turns": 2, "tokens": 25}
    assert view["daily"] == [{"date": "2026-10-05", "turns": 3, "tokens": 25}]
    assert [r["status"] for r in view["recent_issues"]] == ["failed", "interrupted"]
    assert view["recent_issues"][1]["session_id"] == sid
    store.close()


def test_success_rate_is_null_not_zero_when_nothing_was_served(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    assert store.overview(start, end)["success_rate"] is None
    assert store.overview(start, end)["turns"] == 0
    store.close()


def test_recent_issues_reports_the_reason_the_chain_already_holds(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    issue = store.overview(start, end)["recent_issues"][0]
    assert issue["provider"] == "ant"
    assert "provider_5xx" in issue["reason"]
    store.close()


def test_empty_chain_row_reports_an_empty_reason_not_a_crash(tmp_path):
    store = Store(tmp_path / "kira.db")
    sid = store.create_session("AUTO")
    store.add_message(sid, "assistant", "", provider="groq", status="failed")
    start, end = month_bounds()[1:]
    assert store.overview(start, end)["recent_issues"][0]["reason"] == ""
    store.close()


def test_session_rows_carry_counts_and_the_last_activity(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, _ = october()
    busy = seed_at(store, start + 3600, start + 3600 * 24 * 4)
    quiet = store.create_session("FAST", "sess-empty")
    # create_session stamps the real clock, which is later than any seeded month; the
    # ordering below is about COALESCE(last_used_at, created_at), so pin both ends.
    store._conn.execute("UPDATE sessions SET created_at=? WHERE id=?", (start, quiet))  # noqa: SLF001
    store._conn.commit()
    rows = {row["id"]: row for row in store.session_rows()}
    assert rows[busy]["message_count"] == 4
    assert rows[busy]["tokens"] == 25
    assert rows[busy]["last_used_at"] >= start + 3600 * 24 * 4
    assert rows[quiet]["message_count"] == 0
    assert rows[quiet]["tokens"] == 0
    assert rows[quiet]["last_used_at"] is None
    assert [row["id"] for row in store.session_rows()] == [busy, quiet], "most recently used first"
    store.close()


def test_delete_one_session_cascades_its_messages(tmp_path):
    store = Store(tmp_path / "kira.db")
    seed_at(store, 1.0, 1.0)
    assert store.delete_session("sess-1") == (1, 4)
    assert store.list_sessions() == []
    assert store.messages("sess-1") == []
    assert store.delete_session("sess-1") == (0, 0), "deleting what is already gone is not an error"
    store.close()


def test_clear_all_removes_everything_and_says_how_much(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, end = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    store.create_session("AUTO", "other")
    assert store.monthly_spend(start, end) != {}, "the rows are inside the window before the delete"
    sessions, messages = store.clear_sessions()
    assert (sessions, messages) == (2, 4)
    assert store.list_sessions() == []
    # The ledger is not history: what was already billed stays billed, or clearing the
    # transcript would be a free reset of the monthly cap.
    assert store.monthly_spend(start, end) == {"groq": 25, "ant": 0}
    store.close()


def test_disabling_a_provider_never_forgets_what_it_already_spent(tmp_path):
    # The spec's point: a stand-down must not rewrite history.
    store = Store(tmp_path / "kira.db")
    start, end = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    assert store.monthly_spend(start, end)["groq"] == 25
    store.set_setting("groq", "enabled", False)
    assert store.monthly_spend(start, end)["groq"] == 25
    store.close()


def test_usage_for_month_returns_the_label_it_used(tmp_path):
    store = Store(tmp_path / "kira.db")
    start, _ = october()
    seed_at(store, start + 3600, start + 3600 * 24 * 4)
    label, spend = store.usage_for_month("2026-10")
    assert label == "2026-10"
    assert spend == {"groq": 25, "ant": 0}
    store.close()


def test_one_store_serves_four_threads_without_colliding(tmp_path):
    # FastAPI runs a sync route in a threadpool, and unit 12 put a database read *and* a write
    # (the device lookup and its `last_seen_at`) on every authenticated request. Two parallel
    # requests then used this one connection at once and sqlite answered with `InterfaceError:
    # bad parameter or other API misuse` - a 500 on a screen that reads fine. The store owns the
    # serialisation; this storm is what proves it.
    store = Store(tmp_path / "kira.db")
    device = store.add_device("phone", "hash-phone")
    errors: list[str] = []
    gate = threading.Barrier(4)

    def hammer() -> None:
        gate.wait()
        try:
            for _ in range(120):
                store.device_by_token_hash("hash-phone")
                store.touch_device(device["id"])
                store.create_session("AUTO")
                store.list_sessions()
        except Exception as exc:  # noqa: BLE001 - any failure at all is the finding
            errors.append(repr(exc))

    threads = [threading.Thread(target=hammer) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    store.close()
    assert errors == []
