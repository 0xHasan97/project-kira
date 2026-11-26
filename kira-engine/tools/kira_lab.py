"""Everything a browser pass needs, in one command, with nothing real at stake.

A fresh temp data directory, a memory vault seeded with two fake provider keys, the
mock provider on loopback, and the engine serving the built chat bundle. Both secrets
are printed, because the whole point is that they are disposable. Ctrl+C removes the
temp directory; --data-dir keeps a run so you can come back to the same history - or
change --models and see what the Models screen does with a model that is gone.

Run: .venv/Scripts/python.exe tools/kira_lab.py [--port 8912] [--mock-port 8999]
                                        [--models mini,small] [--data-dir PATH]
                                        [--local [--local-model qwen3:4b]]
                                        [--models-two solo] [--vision mock_two]

`--models-two` gives the second provider a catalogue the first does not carry, which is
the only way a browser pass can see what `AUTO` does with a pinned model. `--vision`
marks named providers `vision: true`, the flag `#/call` reads before it sends a frame.
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mock_openai  # noqa: E402  (same directory, by design: neither is a package)

from kira.app import Engine, create_app  # noqa: E402
from kira.config import load_config  # noqa: E402
from kira.vault import Vault  # noqa: E402

CONFIG = """\
host: 127.0.0.1
port: {port}
default_mode: FAST
max_agent_steps: 6
request_timeout_s: 30

providers:
  - name: mock_one
    kind: openai_compat
    base_url: http://127.0.0.1:{mock_port}/v1
    tier: fast
    key_ref: provider/mock_one
    priority: 10
{vision_one}    models: [{models_one}]
  - name: mock_two
    kind: openai_compat
    base_url: http://127.0.0.1:{mock_port}/v1
    tier: fast
    key_ref: provider/mock_two
    priority: 20
{vision_two}    models: [{models_two}]
"""

#: Appended with `--local`. No `key_ref` and a loopback base_url: the same shape a user's
#: config gets from `ollama pull`, and the one provider here that answers with a real model.
LOCAL_STANZA = """\
  - name: ollama
    kind: openai_compat
    base_url: http://127.0.0.1:11434/v1
    tier: fast
    priority: 140
{vision}    models: [{model}]
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Kira dashboard lab (mock provider + scratch engine)")
    parser.add_argument("--port", type=int, default=8912)
    parser.add_argument("--mock-port", type=int, default=8999)
    parser.add_argument("--models", default="mini,small", help="comma-separated model ids offered by the providers")
    parser.add_argument(
        "--models-two",
        help="model ids for mock_two alone; a pass that names a model only mock_one carries needs this",
    )
    parser.add_argument(
        "--vision",
        default="",
        help="comma-separated provider names to mark `vision: true` (mock_one, mock_two, ollama)",
    )
    parser.add_argument("--data-dir", help="reuse this directory instead of a temp one, and keep it")
    parser.add_argument(
        "--local",
        action="store_true",
        help="also add a keyless stanza for Ollama on 127.0.0.1:11434, so a browser pass can use a real local model",
    )
    parser.add_argument("--local-model", default="qwen3:4b", help="model id for --local")
    args = parser.parse_args()

    dist = Path(os.environ.get("KIRA_CHAT_DIST") or ROOT / "kira-chat" / "dist")
    if not (dist / "index.html").exists():
        print(f"[lab] no chat bundle at {dist} - run: cd kira-chat && npm run build", file=sys.stderr)
        return 2
    os.environ["KIRA_CHAT_DIST"] = str(dist)

    if args.data_dir:
        data_dir = Path(args.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        keeps = "kept - it is yours to delete"
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="kira-lab-"))
        atexit.register(shutil.rmtree, data_dir, True)
        keeps = "temp, deleted on exit"

    models_one = ", ".join(args.models.split(","))
    models_two = ", ".join((args.models_two or args.models).split(","))
    vision = {name.strip() for name in args.vision.split(",") if name.strip()}
    marked = lambda name: "    vision: true\n" if name in vision else ""  # noqa: E731 (one line, local to the build)

    text = CONFIG.format(
        port=args.port,
        mock_port=args.mock_port,
        models_one=models_one,
        models_two=models_two,
        vision_one=marked("mock_one"),
        vision_two=marked("mock_two"),
    )
    if args.local:
        text += LOCAL_STANZA.format(model=args.local_model, vision=marked("ollama"))
    (data_dir / "config.yaml").write_text(text, encoding="utf-8")

    mock_openai.serve(args.mock_port)

    vault = Vault("memory")
    vault.set("provider/mock_one", "lab-key-one")
    vault.set("provider/mock_two", "lab-key-two")
    config = load_config(data_dir)
    engine = Engine(config, vault=vault)
    app = create_app(config, engine=engine)

    def note(line: str) -> None:
        # stderr, so stdout stays free for anything that pipes the lab later.
        print(f"[lab] {line}", file=sys.stderr, flush=True)

    note(
        f"mock    http://127.0.0.1:{args.mock_port}/v1 "
        f"mock_one=[{models_one}] mock_two=[{models_two}] vision={sorted(vision) or 'none'} usage={mock_openai.USAGE}"
    )
    note(f"data    {data_dir} ({keeps})")
    note(f"chat    http://127.0.0.1:{args.port}/chat/")
    note(f"token   {engine.token}")
    note(f"confirm {engine.confirm}")
    if args.local:
        try:
            rows = httpx.get("http://127.0.0.1:11434/v1/models", timeout=2).json().get("data") or []
            note(f"local   http://127.0.0.1:11434/v1 models={', '.join(str(r['id']) for r in rows) or 'none'}")
        except httpx.HTTPError as exc:
            note(f"local   unreachable ({type(exc).__name__}) - the mock models still work")
    note("every secret here is disposable; a memory vault is per-process and shares nothing with your Locker")

    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
