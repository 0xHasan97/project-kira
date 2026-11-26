from __future__ import annotations

import pytest

from kira.config import ProviderConfig
from kira.providers import anthropic, gemini, openai_compat
from kira.providers.base import split_data_url
from kira.types import GenRequest, Message

DATA = "data:image/jpeg;base64,/9j/AAAA"


def test_split_data_url():
    assert split_data_url(DATA) == ("image/jpeg", "/9j/AAAA")


def test_split_data_url_rejects_anything_that_is_not_base64_data():
    with pytest.raises(ValueError):
        split_data_url("https://example.invalid/a.jpg")
    with pytest.raises(ValueError):
        split_data_url("data:image/jpeg;base64,")


def test_openai_text_only_stays_a_string():
    wire = openai_compat.to_wire([Message(role="user", content="hi")])
    assert wire == [{"role": "user", "content": "hi"}]


def test_openai_attaches_image_parts():
    wire = openai_compat.to_wire([Message(role="user", content="look", images=[DATA])])
    assert wire[0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image_url", "image_url": {"url": DATA}},
    ]


def test_anthropic_attaches_image_blocks():
    wire = anthropic.to_wire([Message(role="user", content="look", images=[DATA])])
    assert wire[0]["content"] == [
        {"type": "text", "text": "look"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "/9j/AAAA"}},
    ]


def test_gemini_attaches_inline_data():
    payload = gemini.to_payload(
        GenRequest(model="gemini-mock", messages=[Message(role="user", content="look", images=[DATA])])
    )
    assert payload["contents"][0]["parts"] == [
        {"text": "look"},
        {"inlineData": {"mimeType": "image/jpeg", "data": "/9j/AAAA"}},
    ]


def test_vision_defaults_off():
    provider = ProviderConfig(name="p", kind="openai_compat", base_url="https://p.invalid/v1", models=["m"])
    assert provider.vision is False


def test_vision_reads_from_the_yaml_stanza():
    from kira.config import _provider_from

    provider = _provider_from({"name": "p", "kind": "openai_compat", "base_url": "https://p.invalid/v1", "models": ["m"], "vision": True})
    assert provider.vision is True
