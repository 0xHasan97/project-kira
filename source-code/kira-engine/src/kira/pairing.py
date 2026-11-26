from __future__ import annotations

import secrets
import time
from collections import deque
from typing import Callable

from .errors import KiraError

#: Crockford-ish: no I, L, O or U, so a code read aloud or off a screen cannot become another code.
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LEN = 8
CODE_TTL_S = 120.0
MAX_CODES = 8
RATE_LIMIT = 10
RATE_WINDOW_S = 60.0

#: A device token carries this prefix so the engine can tell the two principals apart before
#: it hashes anything — and so a token pasted into the wrong field is recognisably not the owner's.
DEVICE_TOKEN_PREFIX = "kd_"
DEVICE_NAME_MAX = 40


class PairingRefused(KiraError):
    """One refusal for every reason a code did not work.

    Which of expired, spent or unknown it was is not the caller's business: a phone that
    typed a code deserves one sentence, and a stranger probing codes deserves nothing that
    tells them they were close.
    """

    code = "pairing_refused"
    status = 400


class PairingRateLimited(PairingRefused):
    """The same refusal, but waiting is the fix, so it says so with a status that means it."""

    code = "rate_limited"
    status = 429


class Pairing:
    def __init__(
        self,
        *,
        ttl: float = CODE_TTL_S,
        max_codes: int = MAX_CODES,
        rate_limit: int = RATE_LIMIT,
        rate_window: float = RATE_WINDOW_S,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.ttl = ttl
        self.max_codes = max_codes
        self.rate_limit = rate_limit
        self.rate_window = rate_window
        self._clock = clock
        self._codes: dict[str, float] = {}
        self._attempts: deque[float] = deque()

    def mint(self) -> tuple[str, float]:
        now = self._clock()
        self._prune(now)
        if len(self._codes) >= self.max_codes:
            # The oldest live code goes, not the newest: a user who pressed the button once too
            # often wants the code in front of them, and a stranger cannot mint without the owner.
            oldest = min(self._codes, key=self._codes.__getitem__)
            del self._codes[oldest]
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        expires_at = now + self.ttl
        self._codes[code] = expires_at
        return code, expires_at

    def exchange(self, code: str) -> None:
        now = self._clock()
        self._prune(now)
        self._note_attempt(now)
        wanted = self.normalise(code)
        if wanted in self._codes:
            del self._codes[wanted]
            return
        raise PairingRefused(
            "that pairing code is not valid any more - make a new one on the desktop"
        )

    @staticmethod
    def normalise(code: str) -> str:
        return "".join(ch for ch in code.upper() if ch.isalnum())

    def _prune(self, now: float) -> None:
        for code in [code for code, expires in self._codes.items() if expires <= now]:
            del self._codes[code]

    def _note_attempt(self, now: float) -> None:
        while self._attempts and now - self._attempts[0] >= self.rate_window:
            self._attempts.popleft()
        if len(self._attempts) >= self.rate_limit:
            raise PairingRateLimited(
                f"too many pairing attempts - wait {int(self.rate_window)} seconds and try again"
            )
        self._attempts.append(now)
