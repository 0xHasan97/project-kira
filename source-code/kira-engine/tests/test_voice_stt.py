from __future__ import annotations

import asyncio
import importlib.util
import io
import wave

import httpx
import pytest

from kira.voice.errors import VoiceError
from kira.voice.stt import LocalStt, OffStt, RemoteStt, UnavailableStt
from kira.voice.wav import pcm_to_wav

PCM = b"\x00\x01" * 1600


@pytest.fixture
def without_faster_whisper(monkeypatch):
    """Force the "extra not installed" branch even on a machine that has it.

    `available` is a `find_spec` probe, so stubbing the probe is the difference the test is about -
    not whether this particular venv happens to carry a 100 MB speech stack.
    """
    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *args, **kwargs: None
        if name == "faster_whisper"
        else real(name, *args, **kwargs),
    )


def test_pcm_to_wav_roundtrip():
    data = pcm_to_wav(PCM)
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.readframes(10**9) == PCM


def test_local_reports_the_install_line_when_missing(tmp_path, without_faster_whisper):
    stt = LocalStt("base.en", tmp_path)
    assert stt.available is False
    assert 'pip install -e ".[voice]"' in stt.detail
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(pcm_to_wav(PCM)))
    assert caught.value.code == "stt_unavailable"


def test_local_leaves_no_temp_wav_behind(tmp_path, without_faster_whisper):
    stt = LocalStt("base.en", tmp_path)
    with pytest.raises(VoiceError):
        asyncio.run(stt.transcribe(pcm_to_wav(PCM)))
    assert list((tmp_path / "tmp").iterdir()) == []


def test_local_reports_the_model_when_faster_whisper_is_installed(tmp_path):
    pytest.importorskip("faster_whisper")
    stt = LocalStt("base.en", tmp_path)
    assert stt.available is True
    assert stt.detail == "faster-whisper · base.en"


def test_off_says_so():
    with pytest.raises(VoiceError) as caught:
        asyncio.run(OffStt().transcribe(b""))
    assert caught.value.code == "stt_off"


def test_remote_posts_multipart_and_reads_text():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " hello there "})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    stt = RemoteStt("openai", "https://openai.invalid/v1", "whisper-1", "sk-test", client)
    assert asyncio.run(stt.transcribe(pcm_to_wav(PCM))) == "hello there"
    assert seen["url"] == "https://openai.invalid/v1/audio/transcriptions"
    assert seen["auth"] == "Bearer sk-test"
    assert b'name="model"' in seen["body"] and b"whisper-1" in seen["body"]
    assert b"audio/wav" in seen["body"] or b'filename="utterance.wav"' in seen["body"]


def test_remote_failure_is_a_voice_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={})))
    stt = RemoteStt("openai", "https://openai.invalid/v1", "whisper-1", "sk-test", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(b"RIFF"))
    assert caught.value.code == "stt_failed"
    assert "401" in caught.value.message


def test_a_failure_message_never_carries_the_key():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500, json={})))
    stt = RemoteStt("openai", "https://openai.invalid/v1", "whisper-1", "sk-secret-value", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(b"RIFF"))
    assert "sk-secret-value" not in caught.value.message


def test_unavailable_carries_its_reason():
    stt = UnavailableStt("remote", "provider 'openai' has no key in the Locker")
    assert stt.available is False
    with pytest.raises(VoiceError) as caught:
        asyncio.run(stt.transcribe(b""))
    assert caught.value.code == "stt_unavailable"
