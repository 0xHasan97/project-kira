"""One WebSocket, one live call: audio in, turns out, speech that can be interrupted.

The whole module is a state machine around three stages that are not theirs to know about:
`engine.voice.stt` turns a WAV into text, `engine.router` decides who answers, and
`engine.voice.tts` turns each sentence back into audio as it arrives. Everything here is the
sequencing — and the rule that a call is a *conversation*, not a command: one turn in flight, a
barge-in that keeps what was already said, and a webcam frame that is attached to exactly one turn
and never stored.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
from dataclasses import dataclass
from typing import Any

from ..errors import KiraError
from ..loop import AgentRun
from ..memory import build_block, inject
from ..tools import ToolRegistry
from ..types import Delta, Message
from .errors import VoiceError
from .tts import split_sentences
from .vad import FRAME_BYTES, EnergyVad, SAMPLE_RATE, VadConfig
from .wav import pcm_to_wav

#: A call is spoken, so the answer has to sound like one. This is the only system prompt a call uses.
VOICE_SYSTEM_PROMPT = (
    "You are on a live voice call. Your reply is read aloud: keep it to one to three short "
    "sentences, no markdown, no lists, and write numbers the way they are spoken. Tools are not "
    "available on a call; if asked to do something that needs one, say so briefly."
)
MAX_FRAME_BYTES = 512 * 1024          # decoded JPEG, per the spec's frame limit
MAX_AUDIO_BYTES = 64 * 1024           # one packet is 100 ms = 3.2 KB; 64 KB is 2 s of slack, not a stream
MAX_HISTORY = 20                      # turns kept in memory; the store keeps everything
HISTORY_TURNS = 12                    # how far back a call remembers when it builds a request
SAMPLE_BYTES_PER_SECOND = 2 * SAMPLE_RATE  # PCM16 mono at the rate the client captures at


def max_utterance_bytes(seconds: int) -> int:
    """The most audio one utterance may hold: exactly `seconds` of it, plus the frame that overflowed.

    `MAX_AUDIO_BYTES` caps what arrives at once, not the pile it joins, and the VAD's cap is what
    normally closes the pile. This is the backstop for a call that never gets one — the number the
    browser pass reached was 786 KB after 25 s of a sound that never went quiet.
    """
    return seconds * SAMPLE_BYTES_PER_SECOND + FRAME_BYTES


@dataclass
class Hello:
    token: str
    model: str | None = None
    mode: str | None = None
    session_id: str | None = None


class VoiceCall:
    def __init__(self, engine, socket, hello: Hello) -> None:
        self.engine = engine
        self.socket = socket
        self.hello = hello
        cfg = engine.config.voice
        self.vad = EnergyVad(
            VadConfig(
                threshold=cfg.vad_threshold,
                silence_ms=cfg.silence_ms,
                max_utterance_s=cfg.max_utterance_s,
            )
        )
        self.session_id: str | None = None
        self.history: list[Message] = []
        self.memory_used: list[str] = []
        self.pending_frame: str | None = None
        self.turn: asyncio.Task | None = None
        self.active_run: AgentRun | None = None
        self.phase = "listening"          # listening | thinking | speaking
        self.max_utterance_bytes = max_utterance_bytes(cfg.max_utterance_s)
        self._utterance = bytearray()
        self._send_lock = asyncio.Lock()

    # -- plumbing ---------------------------------------------------------

    async def _send(self, payload: dict) -> None:
        """Fire and forget: a dead socket is a finished call, not an exception to explain."""
        try:
            async with self._send_lock:
                await self.socket.send_json(payload)
        except Exception:  # noqa: BLE001 - the reader loop notices the disconnect on its own
            pass

    async def run(self) -> None:
        cfg = self.engine.config.voice
        mode = (self.hello.mode or self.engine.config.default_mode).upper()
        self.session_id = self.engine.store.create_session(mode, self.hello.session_id)
        if self.hello.session_id:
            # Resuming a chat by id: text only, because a call has no way to replay a frame it never saw.
            for row in self.engine.store.messages(self.session_id, limit=HISTORY_TURNS):
                if row["role"] in ("user", "assistant") and row["content"]:
                    self.history.append(Message(role=row["role"], content=row["content"]))
        await self._send(
            {
                "type": "ready",
                "session_id": self.session_id,
                "voice": self.engine.voice.status(),
                "limits": {"max_utterance_s": cfg.max_utterance_s, "silence_ms": cfg.silence_ms},
            }
        )
        try:
            while True:
                message = await self.socket.receive_json()
                if not isinstance(message, dict):
                    continue
                if message.get("type") == "close":
                    break
                await self._dispatch(message)
        except Exception:  # noqa: BLE001 - disconnect, malformed frame: any of them ends the call
            pass
        finally:
            await self._shutdown()

    async def _dispatch(self, message: dict) -> None:
        kind = message.get("type")
        if kind == "audio":
            await self._on_audio(message)
        elif kind == "frame":
            await self._on_frame(message)
        elif kind == "text":
            await self._on_text(message)
        elif kind == "barge":
            await self._on_barge()

    # -- listening --------------------------------------------------------

    def _feed(self, frame: bytes) -> list:
        """Audio only counts while the call is listening: a thinking or speaking engine is deaf on purpose.

        Interruption is the client's job (`barge`), because the only honest microphone during playback
        is one that heard the user over the speaker — the server cannot know what the browser played.
        """
        if self.phase != "listening":
            return []
        events = self.vad.push(frame)
        if any(event.kind == "start" for event in events):
            self._utterance = bytearray()
        if self.vad.speaking:
            room = self.max_utterance_bytes - len(self._utterance)
            if room > 0:
                self._utterance.extend(frame[:room])
        return events

    async def _on_audio(self, message: dict) -> None:
        try:
            pcm = base64.b64decode(str(message.get("pcm") or ""), validate=True)
        except (ValueError, binascii.Error):
            await self._send({"type": "error", "code": "bad_audio", "message": "audio must be base64 PCM"})
            return
        if len(pcm) > MAX_AUDIO_BYTES:
            # A call is 100 ms at a time. Anything larger is a client bug or an attempt to make the
            # engine hold a room full of audio in memory, and neither belongs in a live turn.
            await self._send(
                {"type": "error", "code": "bad_audio", "message": f"audio packets are capped at {MAX_AUDIO_BYTES} bytes"}
            )
            return
        events = []
        for offset in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES):
            events.extend(self._feed(pcm[offset : offset + FRAME_BYTES]))
        for event in events:
            if event.kind == "start":
                await self._send({"type": "speech_start"})
            else:
                await self._send({"type": "speech_end", "discarded": event.discarded})
                if not event.discarded:
                    await self._commit_utterance()

    async def _commit_utterance(self) -> None:
        wav = pcm_to_wav(bytes(self._utterance))
        self._utterance = bytearray()
        try:
            text = (await self.engine.voice.stt.transcribe(wav)).strip()
        except VoiceError as exc:
            await self._send({"type": "error", "code": exc.code, "message": exc.message})
            # `speech_end` already told the client work had begun. Nothing is coming, so say so in the
            # one message the call screen reads as "back to listening" — otherwise it shows "thinking"
            # over a call that is, in fact, deaf until the user hangs up.
            await self._send({"type": "cancelled", "reason": "transcription failed"})
            return
        if not text:
            # The VAD heard something and Whisper heard nothing: a cough, a door, a speaker playing
            # into a mic. Same contract as above — the attempt is over, the call is not.
            await self._send({"type": "cancelled", "reason": "nothing said"})
            return
        await self._send({"type": "transcript", "text": text, "final": True})
        self._start_turn(text)

    # -- the other two inputs ---------------------------------------------

    async def _on_text(self, message: dict) -> None:
        text = str(message.get("text") or "").strip()
        if not text:
            return
        if self.turn is not None:
            await self._cancel_turn("the user typed over the answer")
        await self._send({"type": "transcript", "text": text, "final": True})
        self._start_turn(text)

    async def _on_frame(self, message: dict) -> None:
        """Keep the newest frame for the next turn. Nothing is sent, stored or logged here."""
        mime = str(message.get("mime") or "image/jpeg")
        raw = str(message.get("jpeg") or "")
        try:
            data = base64.b64decode(raw, validate=True)
        except (ValueError, binascii.Error):
            data = b""
        if mime != "image/jpeg" or not data or len(data) > MAX_FRAME_BYTES:
            await self._send(
                {"type": "error", "code": "frame_rejected", "message": "frames must be JPEG under 512 KB"}
            )
            return
        self.pending_frame = f"data:image/jpeg;base64,{raw}"

    async def _on_barge(self) -> None:
        if self.turn is not None:
            await self._cancel_turn("the user spoke over the answer")
        self.vad.reset()
        self._utterance = bytearray()
        self.phase = "listening"

    # -- one turn ---------------------------------------------------------

    def _start_turn(self, text: str) -> None:
        self.turn = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str) -> None:
        engine = self.engine
        cfg = engine.config.voice
        self.phase = "thinking"
        await self._send({"type": "thinking"})
        frame, self.pending_frame = self.pending_frame, None
        user = Message(role="user", content=text, images=[frame] if frame else [])
        run: AgentRun | None = None
        try:
            plan = engine.router.plan(model=self.hello.model, mode=self.hello.mode)
            note: dict[str, Any] | None = None
            if frame:
                vision = [choice for choice in plan.choices if engine.view().by_name[choice.provider].base.vision]
                if vision:
                    # Only providers that were told they take frames stay candidates for this turn.
                    plan.choices = vision
                    note = {"provider": vision[0].provider, "event": "images_attached", "reason": "1 frame attached"}
                else:
                    user.images = []
                    note = {"event": "images_dropped", "reason": "no provider in this mode declares vision"}
            engine.store.add_message(self.session_id, "user", text)
            block, self.memory_used = build_block(engine.memory, [user])
            # The frame belongs to this request alone. `user` carries it, the history entry after it
            # does not: a JPEG described the moment it was taken, and replaying it every turn would
            # tell the model the room has not changed.
            request_messages = inject(
                [
                    Message(role="system", content=VOICE_SYSTEM_PROMPT),
                    *self.history[-HISTORY_TURNS:],
                    user,
                ],
                block,
            )
            self.history.append(Message(role="user", content=text))
            run = AgentRun(
                router=engine.router,
                tools=ToolRegistry(),
                plan=plan,
                messages=request_messages,
                max_steps=1,
                temperature=cfg.temperature,
                approvals=None,
                checkpoints=None,
                policies={},
                session_id=self.session_id,
            )
            if note:
                run.attempt.chain.append(note)
            self.active_run = run
            await self._stream(run)
            self.history.append(Message(role="assistant", content=run.state.text))
            self.history = self.history[-MAX_HISTORY:]
            engine.persist_assistant_row(self.session_id, run, run.state.status)
            engine.memory.mark_used(self.memory_used)
            await self._send(
                {
                    "type": "turn_done",
                    "session_id": self.session_id,
                    "usage": {
                        "prompt_tokens": run.state.usage.input_tokens,
                        "completion_tokens": run.state.usage.output_tokens,
                    },
                    "chain": run.attempt.chain,
                }
            )
        except asyncio.CancelledError:
            if run is not None:
                run.attempt.chain.append(
                    {
                        "provider": run.attempt.served_by,
                        "event": "aborted_mid_stream",
                        "reason": "the user spoke over the answer",
                    }
                )
                self.history.append(Message(role="assistant", content=run.state.text))
                engine.persist_assistant_row(self.session_id, run, "interrupted")
            await self._send({"type": "cancelled", "reason": "barge"})
        except (VoiceError, KiraError) as exc:
            await self._send({"type": "error", "code": getattr(exc, "code", "voice_failed"), "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one bad turn must not end the call
            await self._send({"type": "error", "code": "voice_failed", "message": str(exc)})
        finally:
            self.active_run = None
            self.phase = "listening"
            self.turn = None

    async def _stream(self, run: AgentRun) -> None:
        """Speak while the answer is still arriving: each finished sentence goes to TTS immediately."""
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        worker = asyncio.create_task(self._speak(queue))
        buffer = ""
        try:
            async for event in run.events():
                if not isinstance(event, Delta):
                    continue
                self.phase = "speaking"
                buffer += event.text
                await self._send({"type": "answer_delta", "text": event.text})
                complete, buffer = split_sentences(buffer)
                for sentence in complete:
                    queue.put_nowait(sentence)
            if buffer.strip():
                queue.put_nowait(buffer.strip())
            queue.put_nowait(None)
            await worker
        finally:
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    async def _speak(self, queue: asyncio.Queue[str | None]) -> None:
        seq = 0
        while True:
            sentence = await queue.get()
            if sentence is None:
                return
            try:
                wav = await self.engine.voice.tts.speak(sentence)
            except VoiceError as exc:
                # One sentence the voice cannot say is not a reason to stop the turn: the caption and
                # the transcript already carry it, and the rest of the answer may still speak.
                await self._send({"type": "error", "code": exc.code, "message": exc.message})
                continue
            seq += 1
            await self._send(
                {
                    "type": "audio_out",
                    "pcm": base64.b64encode(wav).decode("ascii"),
                    "seq": seq,
                    "text": sentence,
                }
            )

    async def _cancel_turn(self, reason: str) -> None:
        task = self.turn
        self.turn = None
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def _shutdown(self) -> None:
        task = self.turn
        self.turn = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
