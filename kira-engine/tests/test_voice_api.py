from __future__ import annotations

import asyncio


def test_voice_status_needs_the_token(harness):
    response = asyncio.run(harness.api.get("/v1/kira/voice"))
    assert response.status_code == 401


def test_voice_status_shape(harness):
    response = asyncio.run(harness.api.get("/v1/kira/voice", headers=harness.auth))
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"stt", "tts", "vision", "limits"}
    assert body["stt"]["mode"] == "local"
    assert body["tts"]["mode"] == "local"
    assert body["vision"] is None
    assert body["limits"] == {"max_utterance_s": 30, "silence_ms": 700}
    assert "key-" not in response.text


def test_the_engine_carries_the_stack(harness):
    assert harness.engine.voice.status() == asyncio.run(
        harness.api.get("/v1/kira/voice", headers=harness.auth)
    ).json()


async def test_providers_publish_their_vision_flag(harness):
    # `/call` says whether the camera can be seen; Providers says which provider that answer came
    # from. A row without the flag would leave the UI guessing from the provider's name.
    rows = (await harness.api.get("/v1/kira/providers", headers=harness.auth)).json()["providers"]
    assert rows, "the harness has no providers to publish"
    assert all("vision" in row for row in rows)
    assert all(row["vision"] is False for row in rows), "no harness provider declares vision"

    harness.engine.config.providers[0].vision = True
    rows = (await harness.api.get("/v1/kira/providers", headers=harness.auth)).json()["providers"]
    assert [row["vision"] for row in rows][0] is True


async def test_the_vision_flag_is_config_only(harness):
    # Vision is not a dashboard override: it describes what the endpoint accepts, which is a fact
    # about the model rather than a preference. It lives in config.yaml and has no settings row.
    response = await harness.api.put(
        "/v1/kira/providers/fast_one/settings", json={"vision": True}, headers=harness.signed
    )
    assert response.status_code == 400, response.text
    assert "vision" in response.json()["error"]["message"]
    assert harness.store.settings_map() == {}, "refusing the field must store nothing"
