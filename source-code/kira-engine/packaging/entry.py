"""PyInstaller's entry point: the same CLI as `python -m kira`, in a windowed process."""

from kira.__main__ import main

raise SystemExit(main())
