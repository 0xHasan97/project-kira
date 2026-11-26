from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_memory_reads_need_a_token_and_writes_need_the_confirm_secret(harness):
    assert (await harness.api.get("/v1/kira/memory")).status_code == 401
    assert (await harness.api.post("/v1/kira/memory", json={"text": "x"})).status_code == 401
    unconfirmed = await harness.api.post(
        "/v1/kira/memory", json={"text": "x"}, headers=harness.auth
    )
    assert unconfirmed.status_code == 401
    assert "confirm" in unconfirmed.json()["error"]["message"]


@pytest.mark.anyio
async def test_add_list_patch_and_delete_round_trip(harness):
    created = await harness.api.post(
        "/v1/kira/memory",
        json={"text": "I prefer pnpm", "kind": "preference", "pinned": True},
        headers=harness.signed,
    )
    assert created.status_code == 200
    item = created.json()
    assert item["kind"] == "preference" and item["pinned"] is True

    listed = await harness.api.get("/v1/kira/memory", headers=harness.auth)
    body = listed.json()
    assert body["total"] == 1 and body["memories"][0]["id"] == item["id"]
    # The store probes SQLite and falls back to `unicode61` when there is no trigram tokenizer, so the
    # route must echo whatever the store settled on rather than a name this test happened to type.
    tokenizer = body["settings"]["tokenizer"]
    assert tokenizer == harness.engine.memory.tokenizer
    assert tokenizer in ("trigram", "unicode61"), "a name outside the two the store can pick is a bug"

    patched = await harness.api.patch(
        f"/v1/kira/memory/{item['id']}", json={"text": "I prefer pnpm everywhere"}, headers=harness.signed
    )
    assert patched.status_code == 200 and patched.json()["text"].endswith("everywhere")

    # `pinned: false` is a real patch, not a missing field: `exclude_none` keeps False. The read-back
    # comes from the list route, because a response that echoes `false` while the column stays 1 is
    # exactly the failure an echo-only assertion cannot see.
    unpinned = await harness.api.patch(
        f"/v1/kira/memory/{item['id']}", json={"pinned": False}, headers=harness.signed
    )
    assert unpinned.status_code == 200 and unpinned.json()["pinned"] is False
    after_unpin = await harness.api.get("/v1/kira/memory", headers=harness.auth)
    assert after_unpin.json()["memories"][0]["pinned"] is False

    # An empty body is an empty patch: the row comes back unchanged, down to its `updated_at`.
    # Nothing was written, so a 400, a 404 or a bumped timestamp would all be wrong.
    empty = await harness.api.patch(
        f"/v1/kira/memory/{item['id']}", json={}, headers=harness.signed
    )
    assert empty.status_code == 200, empty.json()
    assert empty.json() == unpinned.json()

    deleted = await harness.api.delete(f"/v1/kira/memory/{item['id']}", headers=harness.signed)
    assert deleted.status_code == 200 and deleted.json() == {"deleted": item["id"]}
    assert (await harness.api.get("/v1/kira/memory", headers=harness.auth)).json()["total"] == 0


@pytest.mark.anyio
async def test_bad_bodies_are_config_error_400_and_unknown_ids_are_404(harness):
    for body in (
        {"text": ""},
        {"text": "   "},
        {"text": "x" * 2001},
        {"text": "fine", "kind": "gossip"},
        {"text": "fine", "surprise": 1},
    ):
        response = await harness.api.post("/v1/kira/memory", json=body, headers=harness.signed)
        assert response.status_code == 400, body
        assert response.json()["error"]["code"] == "config_error"
    missing = await harness.api.patch(
        "/v1/kira/memory/nope", json={"text": "x"}, headers=harness.signed
    )
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert (
        await harness.api.delete("/v1/kira/memory/nope", headers=harness.signed)
    ).status_code == 404


@pytest.mark.anyio
async def test_a_kind_filter_outside_the_published_enum_is_config_error_400(harness):
    # The contract publishes `enum: ["fact", "preference", "note"]` for this filter; a value off that
    # list is a malformed request, and this engine answers those with 400 config_error — the same
    # surface a bad body reaches. Silently returning an empty list would hide a typo as "no facts".
    await harness.api.post(
        "/v1/kira/memory", json={"text": "I use pnpm", "kind": "preference"}, headers=harness.signed
    )
    for kind in ("gossip", "FACT", "preference ", "note%20"):
        response = await harness.api.get(f"/v1/kira/memory?kind={kind}", headers=harness.auth)
        assert response.status_code == 400, kind
        assert response.json()["error"]["code"] == "config_error"

    # The three published kinds and the absent filter keep answering: the check is on the enum, not
    # on the parameter being present.
    preference = await harness.api.get("/v1/kira/memory?kind=preference", headers=harness.auth)
    assert preference.status_code == 200 and preference.json()["total"] == 1
    for kind in ("fact", "note"):
        empty_filter = await harness.api.get(f"/v1/kira/memory?kind={kind}", headers=harness.auth)
        assert empty_filter.status_code == 200 and empty_filter.json()["total"] == 0, kind
    unfiltered = await harness.api.get("/v1/kira/memory", headers=harness.auth)
    assert unfiltered.status_code == 200 and unfiltered.json()["total"] == 1

    # A present-but-empty (`?kind=`) or whitespace-only (`?kind=%20%20`) kind is the client saying
    # "no filter", the same way `query` already reads; the filter row cleared on first paint must not
    # 400. Validation stays exactly as strict for a non-blank value off the enum.
    for raw_kind in ("", "%20%20"):
        cleared = await harness.api.get(f"/v1/kira/memory?kind={raw_kind}", headers=harness.auth)
        assert cleared.status_code == 200, raw_kind
        assert cleared.json()["total"] == 1, raw_kind


@pytest.mark.anyio
async def test_search_never_500s_on_hostile_input(harness):
    harness.store.create_session("AUTO", "s1")
    harness.store.add_message("s1", "user", "a sentence about eggs")
    for query in ['"', "*", "NEAR(", "a OR b", "col:value", "' OR 1=1 --", "🚀"]:
        response = await harness.api.get("/v1/kira/memory/search", params={"q": query}, headers=harness.auth)
        assert response.status_code == 200, query
        assert isinstance(response.json()["hits"], list)
    hits = await harness.api.get("/v1/kira/memory/search", params={"q": "eggs"}, headers=harness.auth)
    (hit,) = hits.json()["hits"]
    # The brief asked `snippet.startswith("a sentence")`, but on a trigram build FTS5's snippet() centres
    # its window on the match and elides the head with an ellipsis, so the real row comes back as
    # `…nce about [eggs]` — the opening words never survive. The shipped store only guarantees the
    # bracket (tests/test_memory_history.py asserts `"[" in snippet`), so the build-agnostic form of
    # "the real query found this very sentence and marked the match" is the row's identity plus the
    # bracketed term. The hostile-input loop above — the point of this test — is untouched.
    assert hit["role"] == "user" and hit["session_id"] == "s1" and "[eggs]" in hit["snippet"]


@pytest.mark.anyio
async def test_an_empty_query_is_an_empty_list_not_an_error(harness):
    response = await harness.api.get("/v1/kira/memory/search", params={"q": ""}, headers=harness.auth)
    assert response.status_code == 200 and response.json() == {"hits": []}


@pytest.mark.anyio
async def test_export_round_trips_and_settings_read_back(harness):
    harness.engine.memory.add("a keepable fact")
    exported = await harness.api.get("/v1/kira/memory/export", headers=harness.auth)
    body = exported.json()
    assert body["version"] == 1 and body["memories"][0]["text"] == "a keepable fact"

    settings = await harness.api.get("/v1/kira/memory/settings", headers=harness.auth)
    assert settings.json() == {
        "inject": True, "capture": "explicit", "extract": False, "tokenizer": "trigram",
    }


@pytest.mark.anyio
async def test_settings_writes_are_gated_validated_and_flip_the_remember_tool(harness):
    assert (
        await harness.api.put("/v1/kira/memory/settings", json={"inject": False}, headers=harness.auth)
    ).status_code == 401
    off = await harness.api.put(
        "/v1/kira/memory/settings", json={"capture": "off"}, headers=harness.signed
    )
    assert off.status_code == 200 and off.json()["capture"] == "off"
    assert harness.engine.tools.get("remember") is None
    back = await harness.api.put(
        "/v1/kira/memory/settings", json={"capture": "explicit"}, headers=harness.signed
    )
    assert back.status_code == 200 and harness.engine.tools.get("remember") is not None

    for body in ({"capture": "sometimes"}, {"tokenizer": "trigram"}, {"inject": "yes"}):
        response = await harness.api.put("/v1/kira/memory/settings", json=body, headers=harness.signed)
        assert response.status_code == 400, body


@pytest.mark.anyio
async def test_the_search_limit_bound_the_contract_publishes_is_the_bound_the_route_keeps(harness):
    # Task 10's review found `/search`'s published `maximum: 50` unverified: widening the route's
    # `min(50, limit)` to `min(5000, limit)` kept every API test green. The reason is the fixture, not
    # the assertion — a handful of matching rows sits under *both* numbers, so `len(hits) <= 50` is
    # true either way and proves nothing. The pool has to overflow the published bound, and the
    # out-of-range limits have to come back *at* the clamp, not merely inside it: that is the one
    # assertion that makes `minimum: 1, maximum: 50` on the wire a statement about the route.
    harness.store.create_session("AUTO", "s1")
    for i in range(60):
        harness.store.add_message("s1", "user", f"note {i} about eggs")
    # The premise the ceiling needs: the store answers a large limit with all 60 rows, so 50 in the
    # response below is the route's clamp doing it and nothing else.
    assert len(harness.engine.memory.search_history("eggs", 9_999)) == 60

    for limit, expected in ((0, 1), (-1, 1), (9999, 50)):
        response = await harness.api.get(
            "/v1/kira/memory/search", params={"q": "eggs", "limit": limit}, headers=harness.auth
        )
        assert response.status_code == 200, limit
        assert len(response.json()["hits"]) == expected, (limit, len(response.json()["hits"]))
