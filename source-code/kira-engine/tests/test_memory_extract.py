from __future__ import annotations

import json
import sqlite3

import pytest

from conftest import openai_text_chunks, ok


def facts_turn(text: str):
    return ok(openai_text_chunks(text, usage=True))


@pytest.mark.anyio
async def test_extraction_is_off_by_default_and_sends_no_second_call(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert sum(1 for call in harness.script.calls if "chat/completions" in call) == 1
    assert harness.engine.memory.list()[1] == 0


@pytest.mark.anyio
async def test_extraction_on_writes_labelled_facts_and_ledgers_the_call(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue(
        "https://fast1.invalid/v1", facts_turn("I prefer pnpm.\n- Works on Windows.")
    )
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm and I am on Windows"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    rows, total = harness.engine.memory.list()
    assert total == 2
    assert {row["origin"] for row in rows} == {"auto"}
    assert all(row["tokens_spent"] > 0 for row in rows)
    month = harness.store.usage_for_month()[1]
    assert month["fast_one"] > 22  # the turn's 11+5 plus the extraction's own tokens


@pytest.mark.anyio
async def test_extraction_dedupes_and_caps_at_three(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.engine.memory.add("I prefer pnpm")
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue(
        "https://fast1.invalid/v1",
        facts_turn("i prefer pnpm.\ndelta\necho\nfoxtrot\ngolf"),
    )
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hello"}]},
        headers=harness.auth,
    )
    texts = [row["text"] for row in harness.engine.memory.list(limit=50)[0]]
    assert len(texts) == 4  # the pre-existing one plus three new, never four
    assert "i prefer pnpm." not in texts


@pytest.mark.anyio
async def test_an_extraction_failure_never_fails_the_turn(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    # No second scripted response: the script answers 500 "no scripted response for fast1".
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I like tea"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    assert harness.engine.memory.list()[1] == 0


@pytest.mark.anyio
async def test_none_and_short_lines_are_dropped(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("NONE"))
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "just chatting"}]},
        headers=harness.auth,
    )
    assert harness.engine.memory.list()[1] == 0


@pytest.mark.anyio
async def test_a_streamed_turn_is_mined_after_its_done_frame(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("I prefer pnpm."))
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm"}], "stream": True},
        headers=harness.auth,
    )
    assert response.status_code == 200
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert frames[-1]["type"] == "done"  # the answer is finished before the second call starts
    rows, total = harness.engine.memory.list()
    assert total == 1 and rows[0]["text"] == "I prefer pnpm."


@pytest.mark.anyio
async def test_an_empty_user_text_is_not_worth_a_call(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("I prefer pnpm."))
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": ""}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert sum(1 for call in harness.script.calls if "chat/completions" in call) == 1
    assert harness.engine.memory.list()[1] == 0


def test_parse_drops_bullets_numbering_and_none():
    from kira.memory import _parse_facts

    assert _parse_facts("NONE") == []
    assert _parse_facts("  - one fact\n2. another fact\n•third fact") == [
        "one fact", "another fact", "third fact",
    ]
    assert _parse_facts("a\nbb\nccc\nddd") == ["ccc", "ddd"]


@pytest.mark.anyio
async def test_a_none_reply_is_still_ledgered(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("NONE"))
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "just chatting"}]},
        headers=harness.auth,
    )
    assert harness.engine.memory.list()[1] == 0
    # The turn's own 11+5, plus the second call's 11+4: a reply of NONE is still a purchase.
    assert harness.store.usage_for_month()[1]["fast_one"] == 31


@pytest.mark.anyio
async def test_a_provider_that_reports_no_usage_gets_a_labelled_estimate(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("I prefer pnpm.", usage=False)))
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm"}]},
        headers=harness.auth,
    )
    rows, total = harness.engine.memory.list()
    assert total == 1
    assert rows[0]["tokens_spent"] > 0  # estimated, never a silent zero
    assert harness.store.usage_for_month()[1]["fast_one"] > 16


@pytest.mark.anyio
async def test_the_second_call_is_capped_and_carries_no_memory_or_tools(harness):
    harness.engine.memory.set_settings({"extract": True})
    harness.engine.memory.add("the user prefers pnpm", pinned=True)
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("I prefer pnpm."))
    await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "which package manager"}]},
        headers=harness.auth,
    )
    assert len(harness.script.bodies) == 2
    extraction = harness.script.bodies[1][1]
    assert extraction["max_tokens"] == 200
    assert extraction["temperature"] == 0.0
    assert "tools" not in extraction
    assert extraction["messages"][0]["role"] == "system"
    assert "the user prefers pnpm" not in extraction["messages"][0]["content"]


@pytest.mark.anyio
async def test_the_streamed_answer_is_not_held_back_by_a_slow_extraction(harness, monkeypatch):
    import kira.app as app_module

    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("I prefer pnpm."))
    order: list[str] = []
    real_sse = app_module.sse

    def recording_sse(payload):
        order.append(str(payload.get("type")))
        return real_sse(payload)

    async def stub_extraction(engine, **kwargs):
        order.append("extract")
        return []

    monkeypatch.setattr(app_module, "sse", recording_sse)
    monkeypatch.setattr(app_module, "extract_facts", stub_extraction)
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I prefer pnpm"}], "stream": True},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert "done" in order and "extract" in order
    assert order.index("extract") > order.index("done")


def test_parse_drops_a_decorated_none():
    from kira.memory import _parse_facts

    assert _parse_facts("NONE\nnone.\n**NONE**\n`NONE`") == []
    assert _parse_facts("None of the time") == ["None of the time"]


@pytest.mark.anyio
async def test_a_storage_failure_while_writing_facts_never_fails_the_turn(harness, monkeypatch):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("I like tea"))

    def boom(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(harness.engine.memory, "add_auto", boom)
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I like tea"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello"


@pytest.mark.anyio
async def test_a_ledger_failure_during_extraction_never_fails_the_turn(harness, monkeypatch):
    harness.engine.memory.set_settings({"extract": True})
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hello")))
    harness.script.queue("https://fast1.invalid/v1", facts_turn("I like tea"))

    real_record_usage = harness.store.record_usage

    def boom_on_extraction(*args, **kwargs):
        # The turn's assistant row is ledgered before extraction starts (`when=` comes from
        # `add_message`); let that write land so only extraction's ledger write fails.
        if "when" in kwargs:
            return real_record_usage(*args, **kwargs)
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(harness.store, "record_usage", boom_on_extraction)
    response = await harness.api.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "I like tea"}]},
        headers=harness.auth,
    )
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "hello"
    assert harness.engine.memory.list()[1] == 0  # nothing written after a failed ledger write
