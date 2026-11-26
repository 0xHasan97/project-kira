"""The built chat bundle is a static mount with exactly three opinions.

A manifest has to arrive as a manifest, not as an octet stream. The worker, the shell document and
the manifest must revalidate — a cached `sw.js` is a browser serving yesterday's cache logic
forever, a cached `index.html` points at assets a rebuild has already deleted, and a cached
manifest pins an old start URL. Hashed assets are the opposite: they are cached for a year as
immutable, because their name changes when their content does.
"""

from __future__ import annotations

import json

import pytest

from kira.app import create_app
from kira.config import Config


def bundle(tmp_path, manifest: bool = True):
    dist = tmp_path / "kira-chat" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<html><head><link rel="manifest" href="manifest.webmanifest"></head>'
        '<body><div id="root"></div><script src="/chat/assets/index-abc123.js"></script></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)\n", encoding="utf-8")
    (dist / "sw.js").write_text("self.addEventListener('fetch', () => {});\n", encoding="utf-8")
    if manifest:
        (dist / "manifest.webmanifest").write_text(
            json.dumps({"name": "Kira", "start_url": "/chat/#/chat", "scope": "/chat/"}),
            encoding="utf-8",
        )
    return dist


def make(tmp_path, **kwargs):
    import httpx

    from kira.app import Engine
    from kira.vault import Vault

    bundle(tmp_path, **kwargs)
    config = Config(data_dir=tmp_path / ".kira-data", providers=[])
    config.data_dir.mkdir(parents=True, exist_ok=True)
    vault = Vault("memory")
    engine = Engine(config, vault=vault)
    app = create_app(config, engine=engine)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kira.test")


@pytest.mark.anyio
async def test_the_manifest_is_served_as_a_manifest(tmp_path):
    async with make(tmp_path) as api:
        response = await api.get("/chat/manifest.webmanifest")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert "no-cache" in response.headers.get("cache-control", "")
    assert response.json()["scope"] == "/chat/"


@pytest.mark.anyio
async def test_the_worker_is_never_cached(tmp_path):
    async with make(tmp_path) as api:
        response = await api.get("/chat/sw.js")
    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "")


@pytest.mark.anyio
async def test_the_shell_document_is_never_cached(tmp_path):
    async with make(tmp_path) as api:
        response = await api.get("/chat/")
    assert response.status_code == 200
    assert "no-cache" in response.headers.get("cache-control", "")


@pytest.mark.anyio
async def test_a_hashed_asset_is_cached_for_a_year(tmp_path):
    async with make(tmp_path) as api:
        response = await api.get("/chat/assets/index-abc123.js")
    assert response.status_code == 200
    cache = response.headers.get("cache-control", "")
    assert "public" in cache
    assert "max-age=31536000" in cache
    assert "immutable" in cache


@pytest.mark.anyio
async def test_a_bundle_without_a_manifest_still_serves_the_shell(tmp_path):
    # An older dist predates unit 8; the mount must not care, and the page must still load.
    async with make(tmp_path, manifest=False) as api:
        assert (await api.get("/chat/")).status_code == 200
        assert (await api.get("/chat/manifest.webmanifest")).status_code == 404


@pytest.mark.anyio
async def test_the_bundle_still_refuses_to_climb_out_of_its_directory(tmp_path):
    async with make(tmp_path) as api:
        assert (await api.get("/chat/../.kira-data/config.yaml")).status_code == 404
