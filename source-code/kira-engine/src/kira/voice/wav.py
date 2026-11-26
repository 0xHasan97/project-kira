from __future__ import annotations

import io
import wave


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap 16-bit mono PCM in a RIFF header, the only container the audio stages exchange."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(pcm)
    return buffer.getvalue()
