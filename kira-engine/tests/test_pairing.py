from __future__ import annotations

import pytest

from kira.pairing import CODE_LEN, Pairing, PairingRefused


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_a_code_pairs_exactly_once():
    pairing = Pairing(clock=Clock())
    code, expires_at = pairing.mint()
    assert len(code) == CODE_LEN
    assert expires_at > 0

    pairing.exchange(code)
    with pytest.raises(PairingRefused):
        pairing.exchange(code)


def test_a_code_is_refused_after_its_ttl():
    clock = Clock()
    pairing = Pairing(clock=clock)
    code, _ = pairing.mint()

    clock.advance(121)
    with pytest.raises(PairingRefused):
        pairing.exchange(code)


def test_the_refusal_does_not_say_which_of_expired_used_or_unknown_it_was():
    clock = Clock()
    pairing = Pairing(clock=clock)
    expired, _ = pairing.mint()
    clock.advance(200)

    messages = set()
    for code in (expired, "ZZZZZZZZ"):
        with pytest.raises(PairingRefused) as caught:
            pairing.exchange(code)
        messages.add(caught.value.message)
    assert len(messages) == 1
    assert "expired" not in next(iter(messages)).lower()


def test_attempts_are_rate_limited_by_a_window_not_per_code():
    clock = Clock()
    pairing = Pairing(clock=clock, rate_limit=3, rate_window=60)
    for _ in range(3):
        with pytest.raises(PairingRefused):
            pairing.exchange("AAAAAAA2")

    with pytest.raises(PairingRefused) as caught:
        pairing.exchange("AAAAAAA3")
    assert caught.value.status == 429

    clock.advance(61)
    with pytest.raises(PairingRefused) as caught:
        pairing.exchange("AAAAAAA3")
    assert caught.value.status == 400


def test_a_code_is_compared_without_case_or_spacing():
    pairing = Pairing(clock=Clock())
    code, _ = pairing.mint()
    spaced = f" {code[:4].lower()}-{code[4:].lower()} "
    pairing.exchange(spaced)


def test_only_a_bounded_number_of_codes_stay_live():
    pairing = Pairing(clock=Clock(), max_codes=2)
    first, _ = pairing.mint()
    pairing.mint()
    pairing.mint()
    with pytest.raises(PairingRefused):
        pairing.exchange(first)
