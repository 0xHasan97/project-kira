from __future__ import annotations

from conftest import ok, openai_text_chunks
from kira.contracts import API_PREFIX


def seed_two_sessions(store) -> tuple[str, str]:
    first = store.create_session("AUTO")
    store.add_message(first, "user", "one")
    store.add_message(first, "assistant", "uno", provider="fast_one", model="mini")
    second = store.create_session("AUTO")
    store.add_message(second, "user", "two")
    return first, second


async def test_delete_one_session_reports_the_counts_and_spares_the_other(harness):
    first, second = seed_two_sessions(harness.store)
    resp = await harness.api.delete(f"{API_PREFIX}/kira/sessions/{first}", headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 1, "messages": 2}
    ids = {row["id"] for row in harness.store.session_rows(50)}
    assert ids == {second}, "the cascade takes messages, not neighbours"


async def test_deleting_an_unknown_session_is_a_200_of_zeros(harness):
    resp = await harness.api.delete(f"{API_PREFIX}/kira/sessions/deadbeefdeadbeef", headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "messages": 0}


async def test_clear_all_reports_how_much_it_removed(harness):
    seed_two_sessions(harness.store)
    resp = await harness.api.delete(f"{API_PREFIX}/kira/sessions", headers=harness.signed)
    assert resp.json() == {"deleted": 2, "messages": 3}
    assert harness.store.session_rows(50) == []


async def test_clear_all_on_an_empty_history_is_a_200_of_zeros(harness):
    resp = await harness.api.delete(f"{API_PREFIX}/kira/sessions", headers=harness.signed)
    assert resp.status_code == 200
    assert resp.json() == {"deleted": 0, "messages": 0}


async def test_both_session_deletes_need_the_confirm_secret(harness):
    session_id, _ = seed_two_sessions(harness.store)
    for path in (f"{API_PREFIX}/kira/sessions/{session_id}", f"{API_PREFIX}/kira/sessions"):
        resp = await harness.api.delete(path, headers=harness.auth)
        assert resp.status_code == 401, f"{path} deleted with only a bearer token"
    assert len(harness.store.session_rows(50)) == 2, "a refused delete deleted nothing"


async def test_the_transcript_of_a_deleted_session_answers_empty_not_404(harness):
    session_id, _ = seed_two_sessions(harness.store)
    await harness.api.delete(f"{API_PREFIX}/kira/sessions/{session_id}", headers=harness.signed)
    resp = await harness.api.get(f"{API_PREFIX}/kira/sessions/{session_id}/messages", headers=harness.auth)
    assert resp.status_code == 200
    assert resp.json()["messages"] == []


async def test_a_stale_session_id_restarts_the_thread_instead_of_failing(harness):
    # The UI keeps X-Kira-Session-Id in memory; clear-all must not strand a client that still has one.
    session_id, _ = seed_two_sessions(harness.store)
    await harness.api.delete(f"{API_PREFIX}/kira/sessions", headers=harness.signed)
    harness.script.queue("fast1", ok(openai_text_chunks("fresh")))
    resp = await harness.api.post(
        f"{API_PREFIX}/chat/completions",
        json={"messages": [{"role": "user", "content": "again"}], "session_id": session_id},
        headers=harness.auth,
    )
    assert resp.status_code == 200
    assert resp.json()["session_id"] == session_id
    assert [m["content"] for m in harness.store.messages(session_id)] == ["again", "fresh"]
