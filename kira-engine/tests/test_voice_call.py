"""One call, start to finish, with every real medium replaced by a seam.

The socket is a queue, the speech stages are fakes, and the provider is the same scripted HTTP
transport the chat tests use — so what is under test here is only the state machine: the VAD opening
and closing an utterance, one turn in flight, sentence-by-sentence speech out, barge-in that persists
what was already said, and a webcam frame that is attached or dropped with a reason in the chain.
"""

from __future__ import annotations

import asyncio
import base64
import struct

from conftest import TEST_TOKEN, ok, openai_text_chunks

from kira.voice.call import Hello, VoiceCall

# A packet is the client's 100 ms cadence: 1600 Int16 samples, five 20 ms VAD frames.
LOUD = base64.b64encode(struct.pack("<1600h", *([8192] * 1600))).decode()
QUIET = base64.b64encode(struct.pack("<1600h", *([0] * 1600))).decode()


def speech():
    """Frames the VAD actually opens an utterance on: a quiet room, 300 ms of voice, 700 ms of silence.

    The floor is the quietest recent frame, so a call that starts mid-sentence is not speech yet — the
    same rule that stops a hissy room from talking to itself.
    """
    return (
        [{"type": "audio", "pcm": QUIET}] * 5
        + [{"type": "audio", "pcm": LOUD}] * 3
        + [{"type": "audio", "pcm": QUIET}] * 7
    )


class FakeSocket:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.closed = None

    async def receive_json(self):
        item = await self.inbox.get()
        if item is None:
            raise RuntimeError("closed")
        return item

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code: int = 1000):
        self.closed = code


class FakeStt:
    mode = "local"
    available = True
    detail = "fake"

    def __init__(self, text="hello kira"):
        self.text = text
        self.wavs = []

    async def transcribe(self, wav):
        self.wavs.append(wav)
        return self.text


class FakeTts:
    mode = "local"
    available = True
    detail = "fake"

    def __init__(self):
        self.spoken = []
        self.gate = None                     # set to an Event to hold the worker mid-speech
        self.started = asyncio.Event()       # so a test knows when speech really began

    async def speak(self, text):
        self.spoken.append(text)
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        return b"RIFF" + text.encode()


class Stack:
    def __init__(self, stt, tts):
        self.stt = stt
        self.tts = tts

    def status(self):
        return {
            "stt": {"mode": "local", "available": True, "detail": "fake"},
            "tts": {"mode": "local", "available": True, "detail": "fake"},
            "vision": None,
            "limits": {"max_utterance_s": 30, "silence_ms": 700},
        }


async def wait_for(socket, kind, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        for message in socket.sent:
            if message["type"] == kind:
                return message
        await asyncio.sleep(0.01)
    raise AssertionError(f"no {kind} in {[m['type'] for m in socket.sent]}")


async def wait_for_count(socket, kind, count, timeout=2.0):
    for _ in range(int(timeout / 0.01)):
        if sum(1 for message in socket.sent if message["type"] == kind) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"wanted {count} {kind}, saw {[m['type'] for m in socket.sent]}")


def opened(harness, frames, *, stt=None, tts=None):
    """The turn harness every scenario below shares: fake stages, a scripted provider, one call."""
    socket = FakeSocket()
    for payload in frames:
        socket.inbox.put_nowait(payload)
    call = VoiceCall(harness.engine, socket, Hello(token=TEST_TOKEN))
    return socket, call


def test_utterance_runs_a_turn(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Hi. How are you?")))
    stt = FakeStt()
    tts = FakeTts()
    harness.engine.voice = Stack(stt, tts)

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for frame in speech():
            socket.inbox.put_nowait(frame)
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    kinds = [m["type"] for m in socket.sent]
    assert kinds[:4] == ["ready", "speech_start", "speech_end", "transcript"]
    assert "thinking" in kinds and "turn_done" in kinds
    assert [m["text"] for m in socket.sent if m["type"] == "audio_out"] == ["Hi.", "How are you?"]
    assert stt.wavs and stt.wavs[0].startswith(b"RIFF")
    assert tts.spoken == ["Hi.", "How are you?"]
    rows = harness.store.messages(socket.sent[0]["session_id"])
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "hello kira"
    assert rows[1]["content"] == "Hi. How are you?"
    chain_events = [record["event"] for record in rows[1]["chain"]]
    assert "served" in chain_events
    # Nothing about the call is audio: the store holds text, and the WAV never reached it.
    assert all("RIFF" not in str(row) for row in rows)


def test_a_discarded_utterance_never_reaches_the_provider(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("should not run")))
    stt = FakeStt()
    harness.engine.voice = Stack(stt, FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        # 40 ms of voice then 700 ms of silence: under the 300 ms floor, so it is a cough, not a turn.
        for _ in range(5):
            socket.inbox.put_nowait({"type": "audio", "pcm": QUIET})
        socket.inbox.put_nowait({"type": "audio", "pcm": LOUD})
        for _ in range(7):
            socket.inbox.put_nowait({"type": "audio", "pcm": QUIET})
        end = await wait_for(socket, "speech_end")
        assert end["discarded"] is True
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    assert stt.wavs == []
    assert [m["type"] for m in socket.sent if m["type"] in ("transcript", "thinking", "turn_done")] == []
    assert harness.script.bodies == []


def test_a_room_that_never_quiets_still_gets_an_answer(harness):
    """The browser pass ran exactly this against Chromium's fake microphone and never got a turn.

    A packet is five 20 ms frames, so alternating whole packets is a sound that flickers across the
    bar without ever holding 700 ms of silence — a fan, music bleeding in, a keyboard. The cap has to
    close it on the clock, or the call holds audio and the user waits for an answer that never comes.
    """
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Got it.")))
    harness.engine.config.voice.max_utterance_s = 2
    stt = FakeStt()
    harness.engine.voice = Stack(stt, FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for _ in range(5):                                    # a quiet room sets the floor
            socket.inbox.put_nowait({"type": "audio", "pcm": QUIET})
        for _ in range(12):                                   # 4.8 s of flicker, past the 2 s cap
            socket.inbox.put_nowait({"type": "audio", "pcm": LOUD})
            socket.inbox.put_nowait({"type": "audio", "pcm": QUIET})
        end = await wait_for(socket, "speech_end")
        assert end["discarded"] is False
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    kinds = [m["type"] for m in socket.sent]
    assert kinds.count("speech_end") == 1
    assert stt.wavs, "the capped utterance reached transcription instead of sitting in a buffer"
    assert "transcript" in kinds and "turn_done" in kinds


def test_a_transcription_that_fails_ends_the_attempt(harness):
    """The lab has no whisper, so this is the exact path the browser pass walked.

    `speech_end` tells the client work has started. If STT then fails — or hears nothing — nothing
    else ever arrives, and the screen sits on "thinking" until the user gives up. The engine has to
    say the attempt is over, in the one message the client already reads as "back to listening".
    """
    from kira.voice.errors import VoiceError

    class BrokenStt(FakeStt):
        async def transcribe(self, wav):
            raise VoiceError("stt_unavailable", "faster-whisper is not installed")

    harness.engine.voice = Stack(BrokenStt(), FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for frame in speech():
            socket.inbox.put_nowait(frame)
        await wait_for(socket, "cancelled")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket, call

    socket, call = asyncio.run(scenario())
    kinds = [m["type"] for m in socket.sent]
    assert kinds == ["ready", "speech_start", "speech_end", "error", "cancelled"]
    assert call.phase == "listening"
    assert socket.sent[3]["code"] == "stt_unavailable"


def test_an_utterance_that_transcribes_to_nothing_ends_the_attempt(harness):
    stt = FakeStt(text="")
    harness.engine.voice = Stack(stt, FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for frame in speech():
            socket.inbox.put_nowait(frame)
        await wait_for(socket, "cancelled")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket, call

    socket, call = asyncio.run(scenario())
    kinds = [m["type"] for m in socket.sent]
    assert kinds == ["ready", "speech_start", "speech_end", "cancelled"]
    assert call.phase == "listening"


def test_the_utterance_buffer_stops_at_its_cap(harness):
    # The per-packet cap limits what arrives at once, not the pile it joins. With a VAD that never
    # closes, that pile was 786 KB after 25 s — the buffer is bounded on its own terms instead.
    from kira.voice.vad import FRAME_BYTES

    harness.engine.config.voice.max_utterance_s = 1

    class NeverCloses:
        speaking = True

        def push(self, frame):
            return []

    socket, call = opened(harness, [])
    call.vad = NeverCloses()
    loud = base64.b64decode(LOUD)[:FRAME_BYTES]
    for _ in range(2000):                                     # 40 s of voice, nothing to close it
        call._feed(loud)
    assert call.max_utterance_bytes == 1 * 2 * 16000 + FRAME_BYTES
    assert len(call._utterance) == call.max_utterance_bytes


def test_barge_persists_an_interrupted_answer(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("One. Two.")))
    stt = FakeStt()
    tts = FakeTts()
    tts.gate = asyncio.Event()
    harness.engine.voice = Stack(stt, tts)

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for frame in speech():
            socket.inbox.put_nowait(frame)
        await asyncio.wait_for(tts.started.wait(), 2.0)   # speech is now blocked inside speak()
        socket.inbox.put_nowait({"type": "barge"})
        await wait_for(socket, "cancelled")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    session_id = socket.sent[0]["session_id"]
    rows = harness.store.messages(session_id)
    assert [row["role"] for row in rows] == ["user", "assistant"]
    assert rows[1]["status"] == "interrupted"
    assert any(record["event"] == "aborted_mid_stream" for record in rows[1]["chain"])
    # The first sentence was already spoken aloud, so the history says so rather than losing it.
    assert rows[1]["content"].startswith("One.")
    assert tts.spoken == ["One."]


def test_typed_turn_needs_no_audio(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Just text.")))
    stt = FakeStt()
    harness.engine.voice = Stack(stt, FakeTts())

    async def scenario():
        socket, call = opened(harness, [{"type": "text", "text": "hello by hand"}])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    assert any(m["type"] == "transcript" and m["text"] == "hello by hand" for m in socket.sent)
    assert [m["text"] for m in socket.sent if m["type"] == "audio_out"] == ["Just text."]
    assert stt.wavs == []                      # a typed turn never asks the microphone


def test_one_turn_at_a_time(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("First.")))
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Second.")))
    tts = FakeTts()
    tts.gate = asyncio.Event()                # hold turn one mid-speech so turn two is genuinely overlapping
    harness.engine.voice = Stack(FakeStt(), tts)

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        socket.inbox.put_nowait({"type": "text", "text": "one"})
        await asyncio.wait_for(tts.started.wait(), 2.0)
        socket.inbox.put_nowait({"type": "text", "text": "two"})
        await wait_for(socket, "cancelled")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    # Typing over an answer cancels it and starts the new turn; the call never runs two at once.
    texts = [m["text"] for m in socket.sent if m["type"] == "transcript"]
    assert texts == ["one", "two"]
    assert len([m for m in socket.sent if m["type"] == "turn_done"]) <= 1


def test_frame_is_attached_once_or_dropped_with_a_reason(harness):
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("I see.")))
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Still text.")))
    harness.engine.voice = Stack(FakeStt(), FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        jpeg = base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg").decode()
        socket.inbox.put_nowait({"type": "frame", "jpeg": jpeg, "mime": "image/jpeg"})
        socket.inbox.put_nowait({"type": "text", "text": "what is this"})
        await wait_for_count(socket, "turn_done", 1)
        socket.inbox.put_nowait({"type": "text", "text": "and now"})
        await wait_for_count(socket, "turn_done", 2)
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    session_id = socket.sent[0]["session_id"]
    rows = harness.store.messages(session_id)
    # Default providers declare no vision: the frame never leaves the device and the chain says so.
    events = [record["event"] for row in rows if row["role"] == "assistant" for record in row["chain"]]
    assert events.count("images_dropped") == 1
    assert events.count("images_attached") == 0
    assert all("fakejpeg" not in str(row) for row in rows), "a dropped frame must not be stored"
    # Both turns reached the provider with plain string content: the frame never left the device.
    assert harness.script.bodies
    assert all(
        not isinstance(message["content"], list)
        for _, payload in harness.script.bodies
        for message in payload["messages"]
    )


def test_a_frame_to_a_vision_provider_is_attached_and_sent_once(harness):
    # `vision: true` is a config.yaml stanza, so the fastest way to stand one up here is to declare
    # it on the provider AUTO already picks — the same flag a real user would have written by hand.
    harness.engine.config.providers[0].vision = True
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("A red cup.")))
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("Still here.")))
    harness.engine.voice = Stack(FakeStt(), FakeTts())
    jpeg = base64.b64encode(b"\xff\xd8\xff\xe0fakejpeg").decode()

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        socket.inbox.put_nowait({"type": "frame", "jpeg": jpeg, "mime": "image/jpeg"})
        socket.inbox.put_nowait({"type": "text", "text": "what do you see"})
        await wait_for_count(socket, "turn_done", 1)
        socket.inbox.put_nowait({"type": "text", "text": "and now"})
        await wait_for_count(socket, "turn_done", 2)
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)
        return socket

    socket = asyncio.run(scenario())
    rows = harness.store.messages(socket.sent[0]["session_id"])
    first = [record["event"] for record in rows[1]["chain"]]
    second = [record["event"] for record in rows[3]["chain"]]
    assert "images_attached" in first
    assert "images_dropped" not in first
    # One frame, one turn: the next turn has nothing to say about vision at all.
    assert "images_attached" not in second and "images_dropped" not in second
    assert all(jpeg not in str(row) for row in rows), "a frame is never stored"

    payloads = [payload for _, payload in harness.script.bodies]
    seeing = [m for _, payload in harness.script.bodies for m in payload["messages"] if m["role"] == "user"]
    assert isinstance(seeing[0]["content"], list), "a declared-vision provider gets the multimodal shape"
    assert any(part.get("type") == "image_url" for part in seeing[0]["content"])
    assert isinstance(seeing[-1]["content"], str), "the second turn is text again"
    assert payloads, "the provider was actually called"
    # Sent once means once: the history the next turn replays is text only, so the frame does not
    # ride along every turn after the one it described.
    assert all(jpeg not in str(payload) for payload in payloads[1:])


def test_bad_audio_and_bad_frames_are_answered_not_fatal(harness):
    from kira.voice.call import MAX_AUDIO_BYTES

    harness.engine.voice = Stack(FakeStt(), FakeTts())

    async def scenario():
        socket, call = opened(
            harness,
            [
                {"type": "audio", "pcm": "not base64 at all!!"},
                {"type": "audio", "pcm": base64.b64encode(b"\x00" * (MAX_AUDIO_BYTES + 2)).decode()},
                {"type": "frame", "jpeg": base64.b64encode(b"PNG!").decode(), "mime": "image/png"},
                {"type": "frame", "jpeg": base64.b64encode(b"\xff\xd8\xff\xe0tiny").decode(), "mime": "image/jpeg"},
            ],
        )
        task = asyncio.create_task(call.run())
        await wait_for(socket, "error")
        await wait_for(socket, "ready")
        codes = [m["code"] for m in socket.sent if m["type"] == "error"]
        assert codes == ["bad_audio", "bad_audio", "frame_rejected"]
        assert call.pending_frame is not None, "the good frame after the bad one still counts"
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)

    asyncio.run(scenario())


def test_a_call_turn_carries_the_memory_block(harness):
    harness.engine.memory.add("the user is learning Spanish", pinned=True)
    harness.script.queue("https://fast1.invalid/v1", ok(openai_text_chunks("hola")))
    harness.engine.voice = Stack(FakeStt(), FakeTts())

    async def scenario():
        socket, call = opened(harness, [])
        task = asyncio.create_task(call.run())
        await wait_for(socket, "ready")
        for frame in speech():
            socket.inbox.put_nowait(frame)
        await wait_for(socket, "turn_done")
        socket.inbox.put_nowait({"type": "close"})
        await asyncio.wait_for(task, 2.0)

    asyncio.run(scenario())
    sent = harness.script.body_for("fast1")
    assert sent["messages"][0]["role"] == "system"  # merged into the call's own system prompt
    assert "learning Spanish" in sent["messages"][0]["content"]
