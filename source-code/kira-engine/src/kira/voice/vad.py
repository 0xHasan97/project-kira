from __future__ import annotations

import math
from array import array
from collections import deque
from dataclasses import dataclass

FRAME_MS = 20
SAMPLE_RATE = 16000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 320
FRAME_BYTES = FRAME_SAMPLES * 2                 # 640
ONSET_FRAMES = 3
FLOOR_WINDOW = 3000 // FRAME_MS                 # keep three seconds of listening audio


@dataclass
class VadConfig:
    threshold: float = 0.02
    silence_ms: int = 700
    max_utterance_s: int = 30
    min_speech_ms: int = 300


@dataclass
class VadEvent:
    kind: str                    # start | end
    discarded: bool = False
    duration_ms: int = 0


def _rms(frame: bytes) -> float:
    samples = array("h")
    samples.frombytes(frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    total = sum(sample * sample for sample in samples)
    return math.sqrt(total / len(samples)) / 32768.0


class EnergyVad:
    """RMS gate over 20 ms frames. Every decision is a frame count so the tests can read them."""

    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self._floor: deque[float] = deque(maxlen=FLOOR_WINDOW)
        self.speaking = False
        self._above = 0
        self._below = 0
        self._speech_frames = 0
        self._open_frames = 0

    def push(self, frame: bytes) -> list[VadEvent]:
        value = _rms(frame)
        if self.speaking:
            return self._push_speaking(value)
        # The floor is the quietest recent frame, so a hissy room lifts its own bar. A full 3 s
        # window is not required: an empty deque means "use the config threshold".
        self._floor.append(value)
        if value >= self._bar(value):
            self._above += 1
        else:
            self._above = 0
        if self._above < ONSET_FRAMES:
            return []
        self.speaking = True
        self._above = 0
        self._below = 0
        self._speech_frames = ONSET_FRAMES
        self._open_frames = ONSET_FRAMES
        return [VadEvent("start")]

    def _bar(self, value: float) -> float:
        floor = min(self._floor) if self._floor else value
        return max(self.config.threshold, floor * 4)

    def _push_speaking(self, value: float) -> list[VadEvent]:
        # Speech duration counts frames at or above the bar only; a pause inside a sentence is not
        # part of the utterance, which is what the transcription stage is handed. The open duration
        # counts every frame, and it is the one the cap runs on — see the comment below.
        self._open_frames += 1
        if value >= self._bar(value):
            self._speech_frames += 1
            self._below = 0
        else:
            self._below += 1
        duration_ms = self._speech_frames * FRAME_MS
        if self._open_frames * FRAME_MS >= self.config.max_utterance_s * 1000:
            # A fan, music through a headset, a keyboard: audio that keeps crossing the bar without
            # ever holding 700 ms of silence. Counting only the loud frames makes `max_utterance_s` a
            # cap on speech rather than on the call, and such a sound holds an utterance open forever
            # — the browser pass fed Chromium's fake microphone for 25 s and never got an answer.
            # What was captured is every frame since the start, so the wall clock is also the honest
            # length to report.
            return [self._end(self._open_frames * FRAME_MS)]
        if self._below >= self.config.silence_ms // FRAME_MS:
            return [self._end(duration_ms)]
        return []

    def _end(self, duration_ms: int) -> VadEvent:
        self.speaking = False
        self._below = 0
        self._open_frames = 0
        self._floor.clear()
        return VadEvent("end", discarded=duration_ms < self.config.min_speech_ms, duration_ms=duration_ms)

    def reset(self) -> None:
        self.speaking = False
        self._above = self._below = self._speech_frames = self._open_frames = 0
        self._floor.clear()
