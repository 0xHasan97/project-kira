from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from .app import create_app
from .characters import (
    CharacterError,
    get_active,
    get_character,
    import_character,
    list_characters,
    read_source_capped,
    remove_character,
    set_active,
)
from .config import load_config, write_sample_config
from .contracts import export_contracts
from .errors import KiraError
from .overrides import build_view
from .skills import builtin_dir, discovery_mode, install_pack, load_skills
from .store import Store
from .vault import Vault, ENGINE_CONFIRM_REF, ENGINE_TOKEN_REF


def _data_dir(args: argparse.Namespace) -> Path | None:
    return Path(args.data_dir) if getattr(args, "data_dir", None) else None


def _chat_dist() -> Path:
    """The built chat bundle: an explicit env var, then the frozen bundle, then the checkout."""
    explicit = os.environ.get("KIRA_CHAT_DIST")
    if explicit:
        return Path(explicit)
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle / "kira-chat" / "dist"
    return Path(__file__).resolve().parents[3] / "kira-chat" / "dist"


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    config = load_config(_data_dir(args))
    if not config.providers:
        print(
            f"[kira] no providers configured in {config.config_path}\n"
            "       run: kira-engine config --sample  then add keys: kira-engine keys set provider/<name> --from-stdin",
            file=sys.stderr,
        )
    # The bundle path is read when `create_app` mounts /chat/, so it has to be exported first. Without
    # this a frozen `Kira.exe serve` looked for `<localappdata>/kira-chat/dist` instead of the copy
    # PyInstaller put beside the executable, and every browser request answered 404.
    dist = _chat_dist()
    if (dist / "index.html").exists():
        os.environ.setdefault("KIRA_CHAT_DIST", str(dist))
    # The vault has to come from the flag: `create_app` would otherwise build a keyring Vault and
    # mint both engine secrets into the Locker on a run the caller asked to keep in memory.
    app = create_app(config, vault=Vault(args.backend))
    port = args.port or config.port
    uvicorn.run(app, host=config.host, port=port, log_level=args.log_level)
    return 0


def cmd_desktop(args: argparse.Namespace) -> int:
    config = load_config(_data_dir(args))
    if not config.providers:
        print(
            f"[kira] no providers configured in {config.config_path}\n"
            "       run: kira-engine config --sample  then add keys: kira-engine keys set provider/<name> --from-stdin",
            file=sys.stderr,
        )
    # The bundle path is read when `create_app` mounts /chat/, so it has to be exported first.
    dist = _chat_dist()
    if not (dist / "index.html").exists():
        print(
            f"[kira] chat bundle missing at {dist} - build it once with `python run_kira.py --rebuild`, then start the window again",
            file=sys.stderr,
        )
        return 2
    os.environ.setdefault("KIRA_CHAT_DIST", str(dist))

    try:
        import pystray  # noqa: F401
        import webview  # noqa: F401
        from PIL import Image  # noqa: F401

        from .desktop import run
    except ImportError as exc:
        print(f'[kira] desktop extras are not installed ({exc}) - pip install -e ".[desktop]"', file=sys.stderr)
        return 2

    vault = Vault(args.backend)
    app = create_app(config, vault=vault)
    token, _ = vault.get_or_create_engine_token()
    return run(
        app,
        host=config.host,
        port=args.port or config.port,
        token=token,
        data_dir=config.data_dir,
        companion=args.companion,
    )


def cmd_keys(args: argparse.Namespace) -> int:
    config = load_config(_data_dir(args))
    vault = Vault(args.backend)

    if args.op == "set":
        if args.from_env:
            import os

            value = os.environ.get(args.from_env)
            if not value:
                print(f"[kira] env var {args.from_env} is empty", file=sys.stderr)
                return 2
        elif args.from_stdin:
            value = sys.stdin.read().strip()
            if not value:
                print("[kira] stdin was empty", file=sys.stderr)
                return 2
        else:
            print("[kira] keys set requires --from-env VAR or --from-stdin (avoid secrets in shell history)", file=sys.stderr)
            return 2
        vault.set(args.ref, value)
        print(f"[kira] stored '{args.ref}' in the {vault.backend} credential store")
        return 0

    if args.op == "rm":
        vault.delete(args.ref)
        print(f"[kira] deleted '{args.ref}'")
        return 0

    # list: presence only, never values
    refs = {
        ENGINE_TOKEN_REF: "engine bearer token",
        ENGINE_CONFIRM_REF: "write-confirm secret (dashboard writes)",
    }
    for provider in config.providers:
        if provider.key_ref:
            refs[provider.key_ref] = f"provider '{provider.name}' key"
    rows = [{"ref": ref, "purpose": purpose, "present": vault.has(ref)} for ref, purpose in sorted(refs.items())]
    print(json.dumps({"backend": vault.backend, "secrets": rows}, indent=2))
    return 0


def cmd_settings(args: argparse.Namespace) -> int:
    config = load_config(_data_dir(args))
    store = Store(config.db_path)

    if args.op == "list":
        view = build_view(config, store)
        rows = [
            {
                "provider": provider,
                "key": key,
                "value": raw,
                "orphan": f"{provider}.{key}" in view.orphan_settings,
            }
            for provider, stored in sorted(store.settings_map().items())
            for key, raw in sorted(stored.items())
        ]
        print(json.dumps({"orphans": view.orphan_settings, "rows": rows}, indent=2))
        return 0

    if not getattr(args, "yes", False):
        print(
            "[kira] settings clear needs --yes: it forgets an override, and the merged value that"
            " would replace it is not shown back to you first",
            file=sys.stderr,
        )
        return 2

    if getattr(args, "key", None):
        if not store.clear_setting(args.provider, args.key):
            print(f"[kira] no settings row for '{args.provider}.{args.key}'", file=sys.stderr)
            return 1
        print(f"[kira] cleared '{args.provider}.{args.key}' - the config.yaml baseline applies again")
        return 0

    removed = store.delete_settings(args.provider)
    print(f"[kira] cleared {removed} settings row(s) for '{args.provider}'")
    return 0 if removed else 1


def cmd_characters(args: argparse.Namespace) -> int:
    """The character library, from a terminal.

    Every verb here calls the same function the routes call, so `characters import` and the dashboard's
    Import button cannot grow different rules — and a refusal on one is a refusal on the other.
    """
    config = load_config(_data_dir(args))
    directory = config.characters_dir
    store = Store(config.db_path)

    if args.op == "import":
        source = Path(args.path)
        try:
            data = read_source_capped(source)
        except OSError as exc:
            print(
                f"[kira] no file to import at '{args.path}' ({exc.strerror or exc.__class__.__name__})",
                file=sys.stderr,
            )
            return 2
        entry = import_character(directory, data, source_name=source.name)
        #: The row the library itself prints, not a second shape invented here: what a user sees after an
        #: import is what the list, and later the routes, will answer with.
        row = next(item for item in list_characters(directory) if item["id"] == entry.id)
        print(json.dumps(row, indent=2))
        return 0

    if args.op == "list":
        print(json.dumps({"active": get_active(directory, store), "characters": list_characters(directory)}, indent=2))
        return 0

    if args.op == "show":
        print(json.dumps(get_character(directory, args.id), indent=2))
        return 0

    if args.op == "use":
        if bool(args.id) == bool(args.off):
            print("[kira] characters use needs one id, or --off to take everyone off stage", file=sys.stderr)
            return 2
        active = set_active(directory, None if args.off else args.id, store)
        print(json.dumps({"active": active}, indent=2))
        return 0

    if not getattr(args, "yes", False):
        print(
            "[kira] characters remove needs --yes: it deletes the imported copy of someone's download, "
            "and the archive it came from may not still be where it was",
            file=sys.stderr,
        )
        return 2
    on_stage = get_active(directory, store)
    profile = remove_character(directory, args.id, store)
    took_off = ", and took it off stage" if on_stage == args.id else ""
    print(f"[kira] removed '{args.id}' ({profile['display_name']}){took_off}")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    """The skill pack, from a terminal: install one someone else wrote, and read what the engine sees.

    `list` answers with the same `load_skills` the engine runs at startup, and `install` writes into the
    same `data_dir/skills` — so a pack added without a browser is a pack the next turn can actually use,
    rather than a file in a place only this command would look.
    """
    config = load_config(_data_dir(args))
    pack = config.skills_dir

    if args.op == "install":
        try:
            report = install_pack(pack, Path(args.path), force=args.force, dry_run=args.dry_run)
        except ValueError as exc:
            print(f"[kira] {exc}", file=sys.stderr)
            return 2
        print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))
        # A row that says `installed` and nothing else is not worth a line when there are 300 of them;
        # a refusal, or an installed skill that came with files Kira cannot load, is.
        for row in report["rows"]:
            if row["status"] == "installed" and not row.get("reason"):
                continue
            detail = f" ({row['reason']})" if row.get("reason") else ""
            status = row["status"]
            # A dry run writes nothing, so a line that reads "installed: tdd" is a line about a file
            # that does not exist. The refusal rows are still refusals either way.
            if report["dry_run"] and status == "installed":
                status = "would install"
            print(f"[kira] {status}: {row['name']}{detail}", file=sys.stderr)
        counts = report["counts"]
        return 0 if counts.get("installed") or counts.get("unchanged") else 1

    skills, statuses = load_skills(builtin_dir(), pack)
    print(
        json.dumps(
            {
                "pack_dir": str(pack),
                "builtin_dir": str(builtin_dir()),
                "skills": [skill.to_wire() for skill in skills],
                "discovery": discovery_mode(skills),
                "refusals": [status.to_wire() for status in statuses if status.status != "loaded"],
            },
            indent=2,
        )
    )
    return 0


def cmd_token(args: argparse.Namespace) -> int:
    vault = Vault(args.backend)
    token, _ = vault.get_or_create_engine_token()
    confirm, _ = vault.get_or_create_confirm()
    # stdout stays exactly the bearer token so `TOKEN=$(kira-engine token)` keeps working; the
    # confirm secret is for a human pasting it into the dashboard, so it goes to stderr.
    print(token)
    print(f"[kira] confirm secret for dashboard writes: {confirm}", file=sys.stderr)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    if args.sample:
        path = write_sample_config(_data_dir(args))
        print(f"[kira] wrote sample config to {path}")
        return 0
    config = load_config(_data_dir(args))
    print(
        json.dumps(
            {
                "data_dir": str(config.data_dir),
                "host": config.host,
                "port": config.port,
                "default_mode": config.default_mode,
                "max_agent_steps": config.max_agent_steps,
                "providers": [
                    {"name": p.name, "kind": p.kind, "tier": p.tier, "base_url": p.base_url, "models": p.models}
                    for p in config.providers
                ],
            },
            indent=2,
        )
    )
    return 0


def cmd_contracts(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else (_data_dir(args) or Path.cwd()).parent / "kira-contracts"
    path = export_contracts(out)
    print(f"[kira] wrote {path}")
    return 0


def cmd_models(args: argparse.Namespace) -> int:
    import httpx

    from .probe import probe_models
    from .providers.registry import ProviderRegistry

    config = load_config(_data_dir(args))
    vault = Vault(args.backend)

    async def probe() -> list[dict]:
        async with httpx.AsyncClient(timeout=config.request_timeout_s) as client:
            registry = ProviderRegistry(config, vault, client)
            return [(await probe_models(registry, p.name)).to_wire() for p in config.providers]

    rows = asyncio.run(probe())
    print(json.dumps(rows, indent=2))
    return 0 if all(row["ok"] for row in rows) else 1


def cmd_voice(args: argparse.Namespace) -> int:
    """Report the speech stack the way `/call` sees it, plus the exact paths it looked for."""
    import httpx

    from .providers.registry import ProviderRegistry
    from .voice.stack import build_voice_stack

    config = load_config(_data_dir(args))
    vault = Vault(args.backend)

    async def check() -> dict:
        async with httpx.AsyncClient(timeout=5.0) as client:
            registry = ProviderRegistry(config, vault, client)
            return build_voice_stack(config, registry, lambda: build_view(config, None)).status()

    status = asyncio.run(check())
    print(
        json.dumps(
            {
                "status": status,
                "paths": {
                    "config": str(config.config_path),
                    "piper_bin": str(config.data_dir / config.voice.piper_bin),
                    "piper_model": str(config.data_dir / config.voice.piper_model),
                    "whisper_models": str(config.data_dir / "voice" / "models"),
                },
                "install": [
                    'pip install -e ".[voice]"  # faster-whisper, for local listening',
                    "Piper: download a release build to <data>/voice/piper/piper.exe "
                    "and a voice to <data>/voice/piper/voice.onnx (see README, Voice section)",
                ],
            },
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kira-engine", description="Kira spine engine")
    parser.add_argument("--data-dir", help="override .kira-data location (default: KIRA_DATA_DIR or <repo>/.kira-data)")
    parser.add_argument("--backend", choices=["keyring", "memory"], help="credential store backend")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Repeat the global flags on every subcommand so both orders work:
    # `kira --backend memory keys list` and `kira keys list --backend memory`.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data-dir", default=argparse.SUPPRESS)
    common.add_argument("--backend", choices=["keyring", "memory"], default=argparse.SUPPRESS)

    serve = sub.add_parser("serve", parents=[common], help="run the engine (loopback only)")
    serve.add_argument("--log-level", default="info")
    serve.add_argument("--port", type=int, help="override the config port (loopback only)")
    serve.set_defaults(func=cmd_serve)

    desk = sub.add_parser("desktop", parents=[common], help="run the engine inside a native window (pywebview)")
    desk.add_argument("--port", type=int, help="override the config port (loopback only)")
    desk.add_argument(
        "--companion",
        action="store_true",
        help="also open the desktop card window: frameless, on top, click-through when the toolkit allows it",
    )
    desk.set_defaults(func=cmd_desktop)

    keys = sub.add_parser("keys", parents=[common], help="manage provider keys")
    ksub = keys.add_subparsers(dest="op", required=True)
    kset = ksub.add_parser("set", parents=[common])
    kset.add_argument("ref")
    kset.add_argument("--from-env")
    kset.add_argument("--from-stdin", action="store_true")
    kset.set_defaults(func=cmd_keys)
    krm = ksub.add_parser("rm", parents=[common])
    krm.add_argument("ref")
    krm.set_defaults(func=cmd_keys)
    ksub.add_parser("list", parents=[common]).set_defaults(func=cmd_keys)

    st = sub.add_parser("settings", parents=[common], help="list or clear merged settings rows")
    ssub = st.add_subparsers(dest="op", required=True)
    ssub.add_parser("list", parents=[common]).set_defaults(func=cmd_settings)
    sclear = ssub.add_parser("clear", parents=[common], help="forget one override row, or a provider's whole set")
    sclear.add_argument("provider")
    sclear.add_argument("key", nargs="?", default=None)
    sclear.add_argument("--yes", action="store_true")
    sclear.set_defaults(func=cmd_settings)

    sub.add_parser("token", parents=[common], help="print (or create) the engine bearer token").set_defaults(func=cmd_token)

    ch = sub.add_parser("characters", parents=[common], help="the 3D character library Kira can wear")
    csub = ch.add_subparsers(dest="op", required=True)
    cimp = csub.add_parser("import", parents=[common], help="copy a .pmx or .zip into the library")
    cimp.add_argument("path")
    cimp.set_defaults(func=cmd_characters)
    csub.add_parser("list", parents=[common], help="every character, with the one on stage").set_defaults(func=cmd_characters)
    cshow = csub.add_parser("show", parents=[common], help="one character's whole profile, report included")
    cshow.add_argument("id")
    cshow.set_defaults(func=cmd_characters)
    cuse = csub.add_parser("use", parents=[common], help="put a character on stage")
    cuse.add_argument("id", nargs="?")
    cuse.add_argument("--off", action="store_true", help="take everyone off stage")
    cuse.set_defaults(func=cmd_characters)
    crm = csub.add_parser("remove", parents=[common], help="delete an imported character and clear the stage if it was on it")
    crm.add_argument("id")
    crm.add_argument("--yes", action="store_true")
    crm.set_defaults(func=cmd_characters)

    sk = sub.add_parser("skills", parents=[common], help="the procedures and voices the engine can pull from")
    ksub = sk.add_subparsers(dest="op", required=True)
    kimp = ksub.add_parser("install", parents=[common], help="copy a skill pack into the user's pack directory")
    kimp.add_argument("path", help="a .zip or a folder holding skills/<name>/SKILL.md")
    kimp.add_argument("--force", action="store_true", help="overwrite a file this pack already installed")
    kimp.add_argument("--dry-run", action="store_true", help="report what would be written, write nothing")
    kimp.set_defaults(func=cmd_skills)
    ksub.add_parser("list", parents=[common], help="what the engine loads, with every refusal").set_defaults(
        func=cmd_skills
    )

    cfg = sub.add_parser("config", parents=[common], help="show or scaffold config.yaml")
    cfg.add_argument("--sample", action="store_true", help="write a starter config.yaml")
    cfg.set_defaults(func=cmd_config)

    con = sub.add_parser("contracts", parents=[common], help="export the OpenAPI contract for the TS client")
    con.add_argument("--out", help="output directory (default: ../kira-contracts)")
    con.set_defaults(func=cmd_contracts)

    sub.add_parser("models", parents=[common], help="probe each provider live and report the truth").set_defaults(func=cmd_models)

    voice = sub.add_parser("voice", parents=[common], help="report the speech stack a real-time call gets")
    vsub = voice.add_subparsers(dest="op", required=True)
    vsub.add_parser("doctor", parents=[common], help="print stage availability, expected paths and install lines").set_defaults(
        func=cmd_voice
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KiraError as exc:
        print(f"[kira] {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except CharacterError as exc:
        #: The characters verbs are the first surface that can refuse with an entry name, so the entry is
        #: printed too — a user told `unsafe_entry` without being told *which* entry has nothing to fix.
        #: T8 moves this family onto the wire and the two handlers become one.
        where = f" [{exc.entry}]" if exc.entry else ""
        print(f"[kira] {exc.code}: {exc.message}{where}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
