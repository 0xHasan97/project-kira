# -*- mode: python ; coding: utf-8 -*-
"""The desktop build: one folder, Kira.exe, no console window.

Build it with packaging/build.ps1 — it builds the chat bundle first, because this spec copies
kira-chat/dist into the bundle at the path the CLI's `_chat_dist()` reads in a frozen app.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ENGINE = Path(SPECPATH).resolve().parent
REPO = ENGINE.parent
CHAT_DIST = Path(os.environ.get("KIRA_CHAT_DIST", REPO / "kira-chat" / "dist")).resolve()

if not (CHAT_DIST / "index.html").exists():
    sys.exit(f"chat bundle missing at {CHAT_DIST} - build it first: npm --prefix kira-chat run build")

datas = [(str(CHAT_DIST), "kira-chat/dist")]
# pywebview ships the WebView2 loader and the .NET interop DLLs under webview/lib.
datas += collect_data_files("webview")

a = Analysis(
    ["entry.py"],
    pathex=[str(ENGINE / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "pystray._win32",
        "PIL.Image",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "yaml",
        "keyring.backends.Windows",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kira",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Kira",
)
