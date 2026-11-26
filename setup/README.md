# Setup

Double-click **`Kira-Setup.cmd`**. One file checks the machine, installs missing
Python or Node with `winget` when available, installs both halves of Kira,
builds the UI, writes a desktop shortcut, and starts the app.

## First run

- When this folder sits next to `run_kira.py`, that checkout is used.
- When only `setup/` is present, it downloads the repository first. The default
  target is `%USERPROFILE%\Kira`; pass `-InstallDir` to choose another folder.
- The engine install includes the native-window extras, so `run-kira.bat --window`
  works without another pip command.

Prerequisites: **Python 3.12+** and **Node.js 20.19+ or 22.12+**. If either is
missing, setup installs it with `winget`; approve the Windows prompt if one
appears. Pass `-NoPrereqInstall` to manage them yourself. Manual fallback:

```powershell
winget install -e --id Python.Python.3.12
winget install -e --id OpenJS.NodeJS.LTS
```

The first Kira start prints a browser token and a confirm secret once. Provider
keys are entered in **Providers**, not in a console.

## Using it from GitHub

On the repository page choose **Code -> Download ZIP**, extract it, and
double-click `setup\Kira-Setup.cmd` inside the extracted folder. That ZIP is
the whole source tree at its root; the setup folder is ordinary source, not a
binary installer.

To make a copied `setup/` folder bootstrap the project by itself, put the
repository URL on one line in `repository.txt`:

```text
https://github.com/OWNER/REPO
```

The script uses `-RepoUrl`, `$env:KIRA_REPO_URL`, `repository.txt`, or the
`origin` remote of a checkout beside it, in that order. Without any of those it
asks once.

## Options

| Option | Effect |
| --- | --- |
| `-CheckOnly` | Print the source and tool versions; change nothing. |
| `-DownloadOnly` | Download the source tree, then stop (even beside a checkout). |
| `-InstallDir PATH` | Where a downloaded source tree goes. |
| `-RepoUrl URL` | Repository or direct ZIP URL for a standalone download. |
| `-Branch NAME` | Branch to download; default tries `main`, then `master`. |
| `-SkipBuild` | Install the engine only; skip UI packages and the build. |
| `-SkipModels` | Do not import the local `kira-3dmodels/` folder. |
| `-ModelsOnly` | Re-import local models into an existing install; no pip, npm, build, or shortcut. |
| `-NoPrereqInstall` | Do not install missing Python/Node with `winget`. |
| `-NoLaunch` | Install and make the shortcut without starting Kira. |
| `-NoShortcut` | Do not write `Kira.lnk` to the desktop. |
| `-NoPrompt` | Never ask for a repository URL; fail instead. |

Examples:

```powershell
.\Kira-Setup.cmd -CheckOnly
.\Kira-Setup.cmd -NoLaunch -NoShortcut
.\Kira-Setup.cmd -RepoUrl https://github.com/OWNER/REPO -InstallDir D:\Apps\Kira
.\Kira-Setup.cmd -ModelsOnly
```

## Local 3D models

Put `.zip` or `.pmx` files you are licensed to use in `kira-3dmodels/` beside
`run_kira.py`. Setup detects the folder, imports every archive into
`<install>\.kira-data\characters`, and leaves the source files where they are.
The import is idempotent, so running setup again reports duplicates instead of
copying them twice. `-SkipModels` opts out; `-ModelsOnly` re-imports without
reinstalling packages. The repository publishes no model archives; each
archive's own readme or `使用规则` file still governs what you may do with it.

## Publishing this as source

Everything in `setup/` is text and belongs in the repository. The root
`.gitignore` already keeps credentials, `.kira-data/`, `node_modules/`,
virtual environments, build output, and logs out of Git.

```powershell
git remote add origin https://github.com/OWNER/REPO.git
git push -u origin main
```

After the first push, edit `setup/repository.txt` with that URL and commit it,
so a copied setup folder can download the project without asking. Do not commit
a generated ZIP; GitHub creates the source archive for every repository and
release automatically.

## Troubleshooting

- **Python or Node not found:** let setup install it with `winget`, or install
  the version above and open a new terminal. The current window does not see a
  PATH change.
- **`npm run build` fails:** delete `kira-chat\node_modules` and run the setup
  again; it will use `npm ci` from the lockfile.
- **Port 8901 is busy:** start later with `run-kira.bat --port 8905`.
- **No desktop shortcut:** the app still starts from `run-kira.bat`; shortcut
  creation is the only optional step that can fail silently.
