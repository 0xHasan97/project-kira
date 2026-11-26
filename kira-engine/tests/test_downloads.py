"""The download door: allowlist, filename and ceiling checked before a socket opens."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kira.downloads import DownloadRefused, check_url, download_model


class Handler(BaseHTTPRequestHandler):
    payload = b"GGUF" + b"\0" * 1024

    def do_GET(self):
        body = self.payload
        self.send_response(200)
        self.send_header("content-type", "application/octet-stream")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # silence the test output
        pass


@pytest.fixture
def mirror():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_a_loopback_file_is_streamed_into_the_llm_folder(tmp_path, mirror) -> None:
    result = download_model(tmp_path, "llm", f"{mirror}/tiny.gguf")
    saved = tmp_path / "llm" / "models" / "tiny.gguf"
    assert saved.read_bytes() == Handler.payload
    assert result["bytes"] == len(Handler.payload)
    assert result["kind"] == "llm"
    assert result["path"] == str(saved)
    assert not saved.with_suffix(".gguf.part").exists()


def test_the_host_allowlist_refuses_a_random_server() -> None:
    with pytest.raises(DownloadRefused, match="huggingface"):
        check_url("llm", "https://example.com/model.gguf")


def test_a_remote_http_url_is_refused_but_loopback_http_is_not() -> None:
    with pytest.raises(DownloadRefused, match="https"):
        check_url("llm", "http://huggingface.co/model.gguf")
    assert check_url("llm", "http://127.0.0.1:9/model.gguf")[0] == "model.gguf"


def test_the_extension_must_match_the_kind() -> None:
    with pytest.raises(DownloadRefused, match="safetensors"):
        check_url("llm", "https://huggingface.co/x/model.safetensors")
    with pytest.raises(DownloadRefused, match="bin"):
        check_url("image", "https://huggingface.co/x/model.bin")


def test_the_filename_must_be_the_url_s_last_segment() -> None:
    with pytest.raises(DownloadRefused, match="last segment"):
        check_url("llm", "https://huggingface.co/x/real.gguf", "other.gguf")


def test_a_path_in_the_filename_is_refused() -> None:
    with pytest.raises(DownloadRefused, match="plain file name"):
        check_url("llm", "https://huggingface.co/x/real.gguf", "../escape.gguf")
    # An encoded separator in the URL is decoded to its last segment, which is a plain name; the
    # traversal is gone rather than followed.
    assert (
        check_url("llm", "https://huggingface.co/x/..%2Fescape.gguf")[0]
        == "escape.gguf"
    )


def test_the_byte_ceiling_stops_a_download_and_leaves_no_part_file(
    tmp_path, mirror, monkeypatch
) -> None:
    monkeypatch.setenv("KIRA_DOWNLOAD_MAX_BYTES", "100")
    with pytest.raises(DownloadRefused, match="ceiling"):
        download_model(tmp_path, "llm", f"{mirror}/tiny.gguf")
    directory = tmp_path / "llm" / "models"
    assert not (directory / "tiny.gguf").exists()
    assert list(directory.glob("*.part")) == []
