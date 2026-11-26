# Local 3D character models

This folder is a local drop point, not part of Kira's shipped assets. Kira's
repository does not contain character models: character archives are usually
fan work or game assets with their own licences, and many of them explicitly
forbid redistribution. Only put a file here when you are allowed to use it on
this machine.

## What setup does

`setup\Kira-Setup.cmd` detects this folder when it exists and imports every
`.zip` or `.pmx` in it into `<Kira>\.kira-data\characters`. The source files
stay where they are; the engine copies them into its own library and never
downloads anything.

- `-SkipModels` installs Kira without touching this folder.
- `-ModelsOnly` re-imports after you add a file, without rebuilding the UI.
- Imports are idempotent: an archive already in the library is reported as
  `already_imported`, decided by its SHA-256, and is not copied twice.
- A refused archive is named in the setup summary and does not stop the rest
  of the install.

The same import can be run by hand from `kira-engine`:

```powershell
.venv\Scripts\python.exe -m kira characters import-dir ..\kira-3dmodels
```

Then choose a character in **Avatar**, or with
`kira-engine characters use <id>`. Removing a character in the app deletes
only Kira's imported copy, never the archive here.

## Keep it local

The root `.gitignore` excludes model media in this folder. Do not commit the
archives, attach them to a release, or publish them from this repository unless
you have explicit permission from every rights holder. Read the `readme` or
`使用规则` file inside each archive before using it.
