from __future__ import annotations

import httpx
import pytest

from kira.memory import BLOCK_HEADER, MemoryStore, build_block, inject
from kira.store import Store
from kira.types import Message
from conftest import ok, openai_text_chunks


@pytest.fixture
def memory(tmp_path):
    return MemoryStore(Store(tmp_path / "kira.db"))


# A block shaped like the real one, for the merge tests that care about placement, not content.
BLOCK = BLOCK_HEADER + "\n- [fact] the user is left-handed"


def user(text):
    return [Message(role="user", content=text)]


def test_nothing_in_memory_adds_nothing(memory):
    block, used = build_block(memory, user("hello"))
    assert (block, used) == ("", [])


def test_inject_with_an_empty_block_is_a_copy(memory):
    messages = user("hello")
    out = inject(messages, "")
    assert [m.content for m in out] == ["hello"] and out is not messages


def test_inject_merges_into_an_existing_system_message_and_prepends_one_otherwise():
    merge = inject([Message(role="system", content="be brief"), Message(role="user", content="hi")], BLOCK)
    assert merge[0].role == "system" and merge[0].content.startswith("be brief\n\n")
    assert len(merge) == 2
    prepend = inject([Message(role="user", content="hi")], BLOCK)
    assert prepend[0].role == "system" and prepend[0].content == BLOCK
    assert len(prepend) == 2


def test_inject_into_an_empty_system_message_is_just_the_block():
    merged = inject([Message(role="system", content=""), Message(role="user", content="hi")], BLOCK)
    assert merged[0].content == BLOCK and len(merged) == 2


def test_pinned_come_first_then_bm25_then_recent(memory):
    pinned = memory.add("the user is left-handed", pinned=True)
    memory.add("the user prefers pnpm for package management")
    memory.add("an unrelated note about coffee")
    block, used = build_block(memory, user("which package manager do I use"))
    assert used[0] == pinned["id"]
    assert "pnpm" in block and BLOCK_HEADER in block
    assert block.index("pnpm") < block.index("coffee")  # BM25 matches rank above the recently-used remainder


def test_the_item_cap_and_the_character_budget_both_hold(memory):
    for index in range(20):
        memory.add(f"fact number {index} " + "x" * 200)
    block, used = build_block(memory, user("fact"), budget=500, max_items=3)
    assert len(used) <= 3 and len(block) <= 500


def test_the_item_cap_binds_when_the_budget_does_not(memory):
    # Short facts and the default budget, so only `max_items` can stop the block growing.
    for index in range(30):
        memory.add(f"fact {index}")
    block, used = build_block(memory, user("which fact"), max_items=3)
    assert len(used) == 3
    assert block.count("\n- [") == 3


def test_an_oversized_single_memory_is_truncated_and_marked(memory):
    memory.add("x" * 900, pinned=True)
    block, used = build_block(memory, user("hi"), budget=200)
    assert used and "…" in block and len(block) <= 200
    # This is the space-free case: the only space in the line is the one in the `- [fact] ` prefix,
    # so a cut that honoured that space would throw the whole memory away and leave `- [fact]…`.
    line = block.split("\n", 1)[1]
    assert line.startswith("- [fact] xxxx") and line.endswith("…")


def test_a_memory_that_does_not_fit_whole_is_skipped_not_mangled(memory):
    memory.add("x" * 120, pinned=True)  # longer than what remains once the header is paid for
    small = memory.add("short fact", pinned=True)  # pinned newest-first, so this one is offered first
    block, used = build_block(memory, user("hi"), budget=200)
    assert used == [small["id"]]
    assert "xxxx" not in block and "…" not in block


def test_an_oversized_memory_is_cut_at_a_word_boundary(memory):
    # `"words " * 120`, not `"word " * 120`: at budget 200 the latter's cut lands *on* a space by
    # arithmetic coincidence and passes even against a naive slice.
    memory.add("words " * 120, pinned=True)
    block, used = build_block(memory, user("hi"), budget=200)
    (line,) = block.split("\n", 1)[1:]
    assert used and line.endswith("words…") and len(block) <= 200


def test_inject_is_off_adds_nothing(memory):
    memory.add("a fact")
    memory.set_settings({"inject": False})
    assert build_block(memory, user("fact")) == ("", [])


def test_the_conversation_list_is_not_mutated(memory):
    memory.add("a fact")
    conversation = [Message(role="user", content="fact")]
    before = list(conversation)
    block, _ = build_block(memory, conversation)
    inject(conversation, block)
    assert conversation == before and conversation[0].content == "fact"


def test_a_memory_selected_twice_appears_once(memory):
    fact = memory.add("the user prefers pnpm for package management", pinned=True)
    block, used = build_block(memory, user("which package manager"))
    # Pinned and BM25 both see this fact; the block (and dead reckoning of what was used) must not.
    assert used == [fact["id"]] and block.count("pnpm") == 1


def test_a_recent_fact_that_also_matched_is_not_repeated(memory):
    memory.add("the user prefers pnpm for package management")
    memory.add("an unrelated note about coffee")
    block, used = build_block(memory, user("pnpm"))
    assert len(used) == 2  # matched in the BM25 tier, then offered again by `recent`
    assert block.count("pnpm") == 1


def test_merging_leaves_the_callers_system_message_alone():
    system = Message(role="system", content="be brief", name="core")
    conversation = [system, Message(role="user", content="hi")]
    out = inject(conversation, BLOCK)
    assert system.content == "be brief"
    assert out[0] is not system and out[0].name == "core"
    assert out[1] is conversation[1]


def test_a_budget_smaller_than_the_header_yields_no_block(memory):
    memory.add("a fact", pinned=True)
    assert build_block(memory, user("fact"), budget=10) == ("", [])


@pytest.mark.anyio
async def test_the_turn_sent_to_the_provider_carries_the_block_and_the_stored_user_row_does_not(
    harness,
):
    harness.engine.memory.add("the user prefers pnpm", pinned=True)
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("ok")))

    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "which package manager"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    sent = harness.script.body_for("fast1")
    assert sent["messages"][0]["role"] == "system"
    assert "the user prefers pnpm" in sent["messages"][0]["content"]

    session_id = response.json()["session_id"]
    stored = harness.store.messages(session_id)
    assert [row["role"] for row in stored] == ["user", "assistant"]
    assert "prefers pnpm" not in str([row["content"] for row in stored])


@pytest.mark.anyio
async def test_a_served_turn_marks_what_it_used_and_a_failed_one_does_not(harness):
    memory = harness.engine.memory
    item = memory.add("the user prefers pnpm", pinned=True)

    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("ok")))
    ok_turn = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=harness.auth,
    )
    assert ok_turn.status_code == 200
    assert memory.get(item["id"])["use_count"] == 1

    harness.script.queue(
        "https://fast1.invalid/v1", httpx.Response(500, json={"error": {"message": "boom"}})
    )
    harness.script.queue(
        "https://fast2.invalid/v1", httpx.Response(500, json={"error": {"message": "boom"}})
    )
    harness.script.queue("https://big.invalid/v1", httpx.Response(500, json={"error": {"message": "boom"}}))
    harness.script.queue("https://ant.invalid", httpx.Response(500, json={"message": "boom"}))
    harness.script.queue("https://gem.invalid", httpx.Response(500, json={"message": "boom"}))
    # `Scripted` answers any unqueued host with a 500, so these queues are belt-and-braces; the turn
    # must fail at every candidate either way.
    failed = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers=harness.auth,
    )
    assert failed.status_code in (502, 503)
    assert memory.get(item["id"])["use_count"] == 1  # unchanged
