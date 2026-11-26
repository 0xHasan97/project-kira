from __future__ import annotations


class VoiceError(Exception):
    """A voice-stage failure with a code the call screen can show. Never carries audio or keys."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
