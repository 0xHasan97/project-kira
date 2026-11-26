from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest

from kira.voice.errors import VoiceError
from kira.voice.tts import LocalTts, OffTts, RemoteTts, UnavailableTts, split_sentences


def test_split_sentences_keeps_the_tail():
    complete, rest = split_sentences("Hi. How are you? I am fine")
    assert complete == ["Hi.", "How are you?"]
    assert rest == " I am fine"


def test_split_long_run_without_punctuation():
    complete, rest = split_sentences("x" * 500)
    assert [len(chunk) for chunk in complete] == [240, 240]
    assert rest == "x" * 20


def test_local_reports_missing_piper(tmp_path):
    tts = LocalTts(tmp_path / "piper.exe", tmp_path / "voice.onnx", tmp_path)
    assert tts.available is False
    assert "piper" in tts.detail


def test_local_runs_the_binary_and_reads_the_wav(tmp_path):
    script = tmp_path / "fake_piper.py"
    script.write_text(
        "import sys, wave\n"
        "out = sys.argv[sys.argv.index('--output_file') + 1]\n"
        "sys.stdin.read()\n"
        "with wave.open(out, 'wb') as w:\n"
        "    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)\n"
        "    w.writeframes(b'\\x00\\x01' * 160)\n"
    )
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not-a-real-voice")
    tts = LocalTts(script, model, tmp_path, prefix=(sys.executable,))
    # The argv shape is Piper's: <bin> --model <voice> --output_file <tmp>, with the text on stdin.
    wav = asyncio.run(tts.speak("hello"))
    assert wav.startswith(b"RIFF")
    assert not list(tmp_path.glob("*.wav"))


def test_local_failure_reports_the_binarys_own_words(tmp_path):
    script = tmp_path / "broken_piper.py"
    script.write_text("import sys\nsys.stderr.write('model file is corrupt')\nsys.exit(3)\n")
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"not-a-real-voice")
    tts = LocalTts(script, model, tmp_path, prefix=(sys.executable,))
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hello"))
    assert caught.value.code == "tts_failed"
    assert "corrupt" in caught.value.message
    assert not list(tmp_path.glob("*.wav"))


def test_remote_posts_json_and_reads_wav():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["json"] = request.read()
        return httpx.Response(200, content=b"RIFFxxxx", headers={"content-type": "audio/wav"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tts = RemoteTts("openai", "https://openai.invalid/v1", "tts-1", "alloy", "sk-test", client)
    assert asyncio.run(tts.speak("hello")) == b"RIFFxxxx"
    assert seen["url"].endswith("/audio/speech")
    assert seen["auth"] == "Bearer sk-test"
    assert json.loads(seen["json"]) == {
        "model": "tts-1",
        "voice": "alloy",
        "input": "hello",
        "response_format": "wav",
    }


def test_remote_failure_is_a_voice_error():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(500, json={})))
    tts = RemoteTts("openai", "https://openai.invalid/v1", "tts-1", "alloy", "sk-test", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hello"))
    assert caught.value.code == "tts_failed"


def test_a_failure_message_never_carries_the_key():
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403, json={})))
    tts = RemoteTts("openai", "https://openai.invalid/v1", "tts-1", "alloy", "sk-secret-value", client)
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hello"))
    assert "sk-secret-value" not in caught.value.message


def test_unavailable_carries_its_reason():
    tts = UnavailableTts("remote", "provider 'openai' has no key in the Locker")
    assert tts.available is False
    with pytest.raises(VoiceError) as caught:
        asyncio.run(tts.speak("hi"))
    assert caught.value.code == "tts_unavailable"


def test_off_says_so():
    with pytest.raises(VoiceError) as caught:
        asyncio.run(OffTts().speak("hi"))
    assert caught.value.code == "tts_off"
