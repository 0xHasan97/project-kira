"""The local image workspace: status, generation, gallery, and the gates on each.

The engine here is a fake runner, not stable-diffusion.cpp. That is deliberate: the workspace's own
claims are about what it writes and what it refuses, and a multi-gigabyte checkpoint on a test machine
would prove neither. The one thing the fake keeps real is the bytes' shape — a returned blob that is
not a PNG is refused, so a broken backend cannot leave a `.png` that no viewer can open.
"""

from __future__ import annotations

import json
import os

import pytest

from kira.config import Config
from kira.images import (
    ImageBackendMissing,
    ImageRequestInvalid,
    ImageStudio,
    register_image_tool,
)
from kira.tools import ToolRegistry

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00" * 8


def fake_studio(tmp_path, png: bytes = PNG) -> ImageStudio:
    config = Config(data_dir=tmp_path / "data")
    return ImageStudio(config, runner=lambda argv, timeout: png)


def install_engine_and_model(studio: ImageStudio) -> None:
    """Put an executable and a checkpoint where the folder scan looks, without any real bytes."""
    studio.engine_dir.mkdir(parents=True, exist_ok=True)
    engine = studio.engine_dir / ("sd.exe" if os.name == "nt" else "sd")
    engine.write_bytes(b"fake engine")
    if os.name != "nt":
        engine.chmod(0o755)
    studio.model_dir.mkdir(parents=True, exist_ok=True)
    (studio.model_dir / "sd15.safetensors").write_bytes(b"not a real checkpoint")


def test_status_says_which_folder_is_empty(tmp_path) -> None:
    studio = fake_studio(tmp_path)
    status = studio.status()
    assert status["ready"] is False
    assert status["backend"] is None
    assert "no image engine" in status["reason"]
    assert status["engine_dir"].endswith("engines")
    assert status["models"] == []


def test_a_model_and_an_engine_make_it_ready(tmp_path) -> None:
    studio = fake_studio(tmp_path)
    install_engine_and_model(studio)
    status = studio.status()
    assert status["ready"] is True
    assert status["reason"] is None
    assert status["backend"] == "local"
    assert [m["filename"] for m in status["models"]] == ["sd15.safetensors"]


def test_generation_writes_the_png_and_a_sidecar_the_gallery_reads(tmp_path) -> None:
    studio = fake_studio(tmp_path)
    install_engine_and_model(studio)
    record = studio.generate(
        prompt="a lighthouse", steps=8, seed=42, width=256, height=256
    )

    png = studio.output_dir / record.name
    sidecar = png.with_suffix(".json")
    assert png.read_bytes() == PNG
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    assert saved["prompt"] == "a lighthouse"
    assert saved["seed"] == 42
    assert saved["steps"] == 8
    assert saved["model"] == "sd15.safetensors"

    listed = studio.status()["outputs"][0]
    assert listed["name"] == record.name
    assert listed["prompt"] == "a lighthouse"
    assert listed["seed"] == 42
    assert listed["width"] == 256
    assert listed["url"] == f"/v1/kira/images/file/{record.name}"


def test_negative_prompt_reaches_the_engine_and_the_sidecar(tmp_path) -> None:
    seen: list[list[str]] = []

    def runner(argv: list[str], timeout: float) -> bytes:
        seen.append(argv)
        return PNG

    studio = ImageStudio(Config(data_dir=tmp_path / "data"), runner=runner)
    install_engine_and_model(studio)
    studio.generate(prompt="a fox", negative_prompt="blurry", steps=4, seed=7)
    assert seen[0][seen[0].index("-n") + 1] == "blurry"
    assert studio.status()["outputs"][0]["negative_prompt"] == "blurry"


def test_a_non_png_answer_is_refused_and_leaves_no_file(tmp_path) -> None:
    studio = fake_studio(tmp_path, png=b"<html>not an image</html>")
    install_engine_and_model(studio)
    with pytest.raises(Exception, match="not a PNG"):
        studio.generate(prompt="a fox")
    assert list(studio.output_dir.glob("*.png")) == []


def test_a_prompt_that_is_empty_or_a_size_that_is_not_a_multiple_of_eight_is_a_400(
    tmp_path,
) -> None:
    studio = fake_studio(tmp_path)
    with pytest.raises(ImageRequestInvalid, match="prompt"):
        studio.generate(prompt="   ")
    with pytest.raises(ImageRequestInvalid, match="multiple of 8"):
        studio.generate(prompt="a fox", width=500)
    with pytest.raises(ImageRequestInvalid, match="steps"):
        studio.generate(prompt="a fox", steps=0)


def test_generation_without_an_engine_names_the_missing_folder(tmp_path) -> None:
    studio = fake_studio(tmp_path)
    studio.model_dir.mkdir(parents=True)
    (studio.model_dir / "sd15.safetensors").write_bytes(b"x")
    with pytest.raises(ImageBackendMissing, match="engines"):
        studio.generate(prompt="a fox")


async def test_the_routes_serve_the_gallery_and_guard_the_delete(harness) -> None:
    studio = fake_studio(harness.config.data_dir)
    install_engine_and_model(studio)
    harness.engine.images = studio

    status = await harness.api.get("/v1/kira/images", headers=harness.auth)
    assert status.status_code == 200
    assert status.json()["ready"] is True

    generated = await harness.api.post(
        "/v1/kira/images/generate",
        headers=harness.signed,
        json={
            "prompt": "a lighthouse",
            "steps": 4,
            "seed": 5,
            "width": 128,
            "height": 128,
        },
    )
    assert generated.status_code == 200, generated.text
    row = generated.json()
    assert row["prompt"] == "a lighthouse"
    assert row["seed"] == 5

    bare = await harness.api.get("/v1/kira/images")
    assert bare.status_code == 401

    image = await harness.api.get(
        f"/v1/kira/images/file/{row['name']}", headers=harness.auth
    )
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")

    refused = await harness.api.delete(
        f"/v1/kira/images/{row['name']}", headers=harness.auth
    )
    assert refused.status_code == 401

    deleted = await harness.api.delete(
        f"/v1/kira/images/{row['name']}", headers=harness.signed
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": row["name"]}
    assert not (studio.output_dir / row["name"]).exists()

    gone = await harness.api.get(
        f"/v1/kira/images/file/{row['name']}", headers=harness.auth
    )
    assert gone.status_code == 404


async def test_a_generation_body_the_route_cannot_validate_is_a_400(harness) -> None:
    response = await harness.api.post(
        "/v1/kira/images/generate",
        headers=harness.signed,
        json={"prompt": "a fox", "width": "wide"},
    )
    # The app's one validation handler answers 400 with the offending field names rather than FastAPI's
    # 422 body, which can echo the input back.
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "config_error"


def test_the_agent_tool_returns_the_same_row_the_screen_would_show(tmp_path) -> None:
    studio = fake_studio(tmp_path)
    install_engine_and_model(studio)
    registry = ToolRegistry()
    register_image_tool(registry, studio)
    assert "image_generate" in registry.names

    outcome = registry.execute("image_generate", {"prompt": "a fox", "seed": 3})
    import asyncio

    result = asyncio.run(outcome)
    assert result.ok is True
    payload = json.loads(result.content)
    assert payload["prompt"] == "a fox"
    assert payload["seed"] == 3
    assert payload["url"].endswith(payload["name"])
