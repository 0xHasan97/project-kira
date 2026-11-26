from __future__ import annotations

import struct

from kira.voice.vad import EnergyVad, VadConfig

LOUD = struct.pack("<320h", *([8192] * 320))
QUIET = struct.pack("<320h", *([0] * 320))


def feed(vad, frame, times):
    events = []
    for _ in range(times):
        events.extend(vad.push(frame))
    return events


def test_onset_needs_three_frames_and_offset_needs_seven_hundred_ms():
    vad = EnergyVad(VadConfig(threshold=0.02, silence_ms=700))
    assert feed(vad, QUIET, 150) == []          # 3 s of floor
    assert [e.kind for e in feed(vad, LOUD, 2)] == []
    assert [e.kind for e in feed(vad, LOUD, 1)] == ["start"]
    assert vad.speaking
    assert feed(vad, LOUD, 14) == []            # 300 ms of speech
    events = feed(vad, QUIET, 35)               # 700 ms of silence
    assert [e.kind for e in events] == ["end"]
    assert events[0].discarded is False
    assert events[0].duration_ms == 17 * 20     # 3 onset frames + 14 loud; silence is not speech


def test_a_short_burst_is_discarded():
    vad = EnergyVad(VadConfig(threshold=0.02, silence_ms=700))
    feed(vad, QUIET, 150)
    feed(vad, LOUD, 3)
    feed(vad, QUIET, 34)
    events = feed(vad, QUIET, 1)
    assert [e.kind for e in events] == ["end"]
    assert events[0].discarded is True


def test_max_utterance_ends_on_its_own():
    vad = EnergyVad(VadConfig(threshold=0.02, max_utterance_s=1))
    feed(vad, QUIET, 150)
    feed(vad, LOUD, 3)
    events = feed(vad, LOUD, 47)
    assert [e.kind for e in events] == ["end"]
    assert events[0].duration_ms == 1000


def test_a_sound_that_never_quiets_closes_on_the_wall_clock():
    # The browser pass finding: a fan, a music bleed, Chromium's fake mic. Frames drift above and
    # below the bar in the same breath, so 700 ms of silence never arrives. The cap has to be a
    # clock, not a count of the frames that happened to be loud — otherwise the call holds audio
    # forever and never commits an answer.
    vad = EnergyVad(VadConfig(threshold=0.02, silence_ms=700, max_utterance_s=2))
    feed(vad, QUIET, 150)
    assert [e.kind for e in feed(vad, LOUD, 3)] == ["start"]
    events = []
    for _ in range(60):                    # 6 s of alternating frames, well past the 2 s cap
        events.extend(vad.push(LOUD))
        events.extend(vad.push(QUIET))
    assert [e.kind for e in events] == ["end"]
    assert events[0].duration_ms == 2000   # when it closed, in wall clock, not how much of it was speech
    assert events[0].discarded is False
    assert not vad.speaking


def test_a_closed_utterance_waits_for_a_quieter_frame_before_it_reopens():
    # `_end` clears the floor, so the first frame back is its own floor and the bar is four times it.
    # A source that is exactly as loud as the one that just ended therefore does not reopen until
    # something genuinely quieter is heard: the engine will not re-run STT over the same drone every
    # 30 s, which is the safer of the two readings of a wall-clock cap.
    vad = EnergyVad(VadConfig(threshold=0.02, silence_ms=700, max_utterance_s=1))
    feed(vad, QUIET, 150)
    assert [e.kind for e in feed(vad, LOUD, 60)] == ["start", "end"]
    assert feed(vad, LOUD, 20) == []
    assert [e.kind for e in feed(vad, QUIET, 3) + feed(vad, LOUD, 3)] == ["start"]


def test_noise_floor_raises_the_bar():
    vad = EnergyVad(VadConfig(threshold=0.02))
    hiss = struct.pack("<320h", *([1000] * 320))    # rms ~0.03, so the bar lifts to ~0.12
    louder = struct.pack("<320h", *([2500] * 320))  # rms ~0.08: over the config floor, under the room
    feed(vad, hiss, 150)
    assert feed(vad, louder, 10) == []
    assert not vad.speaking
    assert [e.kind for e in feed(vad, LOUD, 3)] == ["start"]


def test_reset_clears_the_utterance():
    vad = EnergyVad(VadConfig(threshold=0.02))
    feed(vad, QUIET, 150)
    feed(vad, LOUD, 3)
    assert vad.speaking
    vad.reset()
    assert not vad.speaking
    assert feed(vad, QUIET, 1) == []
