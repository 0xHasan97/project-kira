#requires -Version 5.1
<#
.SYNOPSIS
  Download Kira when needed, install it, build the UI, and start it.

.DESCRIPTION
  Double-click Kira-Setup.cmd. When this folder sits inside a checkout, the
  checkout is used. When only setup/ was copied, the repository archive is
  downloaded first, into %USERPROFILE%\Kira unless -InstallDir says otherwise.

  The script checks for Python 3.12+ and Node 20.19+/22.12+, installs a missing
  one with winget when available, creates the engine virtual environment, installs
  the engine, installs the UI packages, builds the UI, writes a desktop shortcut,
  and starts run-kira.bat.
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [string]$RepoUrl = "",
    [string]$Branch = "",
    [switch]$DownloadOnly,
    [switch]$CheckOnly,
    [switch]$NoLaunch,
    [switch]$NoShortcut,
    [switch]$SkipBuild,
    [switch]$SkipModels,
    [switch]$ModelsOnly,
    [switch]$NoPrereqInstall,
    [switch]$NoPrompt
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# Windows PowerShell 5.1 on older builds still defaults to TLS 1.0 for web calls.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch { }
$Prefix = "[kira]"
$Here = $PSScriptRoot
$LocalRoot = Split-Path -Parent $Here
Set-Location -LiteralPath $Here

function Say([string]$Message) {
    Write-Host ("{0} {1}" -f $Prefix, $Message)
}

function Fail([string]$Message) {
    throw $Message
}

function Test-Checkout([string]$Path) {
    return ((Test-Path (Join-Path $Path "run_kira.py")) -and
            (Test-Path (Join-Path $Path "kira-engine")) -and
            (Test-Path (Join-Path $Path "kira-chat")))
}

function Format-RepoUrl([string]$Url) {
    $value = $Url.Trim()
    if ($value -match "\.zip($|\?)") { return $value }
    $value = $value.TrimEnd("/")
    $value = $value -replace "^git@github\.com:", "https://github.com/"
    $value = $value -replace "^ssh://git@github\.com/", "https://github.com/"
    $value = $value -replace "\.git$", ""
    return $value
}

function Get-RepoUrl {
    if ($RepoUrl -and $RepoUrl.Trim().Length -gt 0) { return $RepoUrl.Trim() }
    if ($env:KIRA_REPO_URL) { return $env:KIRA_REPO_URL.Trim() }

    $file = Join-Path $Here "repository.txt"
    if (Test-Path -LiteralPath $file) {
        foreach ($line in Get-Content -LiteralPath $file) {
            $clean = $line.Trim()
            if ($clean.Length -gt 0 -and -not $clean.StartsWith("#")) { return $clean }
        }
    }

    if (Test-Path -LiteralPath (Join-Path $LocalRoot ".git")) {
        $git = Get-Command git -ErrorAction SilentlyContinue
        if ($git) {
            Push-Location $LocalRoot
            try {
                $remote = (& git remote get-url origin 2>$null)
                if ($LASTEXITCODE -eq 0 -and $remote) { return $remote.Trim() }
            } finally {
                Pop-Location
            }
        }
    }

    if (-not $NoPrompt -and $Host.Name -eq "ConsoleHost") {
        $answer = Read-Host ("{0} GitHub repository URL (https://github.com/OWNER/REPO)" -f $Prefix)
        if ($null -ne $answer -and $answer.Trim().Length -gt 0) { return $answer.Trim() }
    }

    Fail "No source checkout beside setup/ and no repository URL. Put the URL on one line in setup\repository.txt, or pass -RepoUrl https://github.com/OWNER/REPO"
}

function Get-PythonInstalls {
    $roots = @()
    foreach ($base in @($env:LOCALAPPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ($base) { $roots += (Join-Path $base "Python") }
    }
    foreach ($root in $roots) {
        if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
        Get-ChildItem -LiteralPath $root -Directory -Filter "Python3*" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object {
                $exe = Join-Path $_.FullName "python.exe"
                if (Test-Path -LiteralPath $exe) { @{ Exe = $exe; Args = @() } }
            }
    }
}

function Find-Python {
    $candidates = @(
        @{ Exe = "py"; Args = @("-3.12") },
        @{ Exe = "py"; Args = @("-3") }
    )
    $candidates += @(Get-PythonInstalls)
    $candidates += @{ Exe = "python"; Args = @() }
    foreach ($candidate in $candidates) {
        if ($null -eq $candidate) { continue }
        if (-not (Get-Command $candidate.Exe -ErrorAction SilentlyContinue)) { continue }
        $arguments = @($candidate.Args) + @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
        try {
            $output = & $candidate.Exe @arguments 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) {
                $version = [version](($output | Select-Object -Last 1).Trim())
                if ($version -ge [version]"3.12") { return $candidate }
            }
        } catch {
            continue
        }
    }
    return $null
}

function Get-NodeVersion {
    $nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
    if (-not $nodeExe) {
        $paths = @()
        if ($env:ProgramFiles) { $paths += (Join-Path $env:ProgramFiles "nodejs\node.exe") }
        if ($env:LOCALAPPDATA) { $paths += (Join-Path $env:LOCALAPPDATA "Programs\nodejs\node.exe") }
        foreach ($path in $paths) {
            if ($path -and (Test-Path -LiteralPath $path)) { $nodeExe = $path; break }
        }
    }
    if (-not $nodeExe) { return $null }
    $nodeDir = Split-Path -Parent $nodeExe
    if (($env:Path -split ";") -notcontains $nodeDir) { $env:Path = "$nodeDir;$env:Path" }
    try {
        $text = (& $nodeExe --version 2>$null | Select-Object -First 1)
        if (-not $text) { return $null }
        $version = [version]($text.Trim().TrimStart("v"))
        $ok = (($version -ge [version]"20.19.0") -and ($version -lt [version]"21.0.0")) -or
              ($version -ge [version]"22.12.0")
        if ($ok) { return $version }
    } catch {
        return $null
    }
    return $null
}

function Update-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $parts = @($env:Path, $machine, $user) | Where-Object { $_ }
    $env:Path = ($parts -join ";")
}

function Install-Prerequisite([string]$Id, [string]$Name) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        Say ("winget is not available; cannot install {0} automatically." -f $Name)
        return $false
    }
    Say ("Installing {0} with winget. Approve the Windows prompt if it appears..." -f $Name)
    & winget install --id $Id -e --silent --accept-package-agreements --accept-source-agreements 2>&1 |
        ForEach-Object { Write-Host ("  {0}" -f $_) }
    $code = $LASTEXITCODE
    Update-ProcessPath
    if ($code -ne 0) {
        Say ("winget could not install {0} (exit {1})." -f $Name, $code)
        return $false
    }
    Start-Sleep -Seconds 1
    return $true
}

function Ensure-Prerequisites {
    $python = Find-Python
    $node = Get-NodeVersion

    if (-not $CheckOnly -and -not $NoPrereqInstall) {
        if ($null -eq $python) {
            Install-Prerequisite "Python.Python.3.12" "Python 3.12" | Out-Null
            $python = Find-Python
        }
        if ($null -eq $node) {
            Install-Prerequisite "OpenJS.NodeJS.LTS" "Node.js LTS" | Out-Null
            $node = Get-NodeVersion
        }
    }

    if ($null -eq $python) {
        Fail "Python 3.12+ is required. Install it from https://www.python.org/downloads/ (tick Add python.exe to PATH), or run 'winget install -e --id Python.Python.3.12', then run this file again."
    }
    if ($null -eq $node) {
        Fail "Node.js 20.19+ (or 22.12+) is required to build the UI. Install the LTS from https://nodejs.org/, or run 'winget install -e --id OpenJS.NodeJS.LTS', then run this file again."
    }
    return @{ Python = $python; Node = $node }
}

function Download-Source([string]$Url, [string]$Destination) {
    $base = Format-RepoUrl $Url
    $Destination = [System.IO.Path]::GetFullPath($Destination)
    $branches = @()
    if ($Branch -and $Branch.Trim().Length -gt 0) { $branches += $Branch.Trim() }
    else { $branches = @("main", "master") }

    $temp = Join-Path $env:TEMP ("kira-setup-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $temp | Out-Null
    $zip = Join-Path $temp "source.zip"
    try {
        $downloaded = $false
        if ($base -match "\.zip($|\?)") {
            Say ("Downloading {0}" -f $base)
            Invoke-WebRequest -Uri $base -OutFile $zip -UseBasicParsing
            $downloaded = $true
        } else {
            foreach ($candidate in $branches) {
                $archive = "{0}/archive/refs/heads/{1}.zip" -f $base, $candidate
                try {
                    Say ("Downloading {0}" -f $archive)
                    Invoke-WebRequest -Uri $archive -OutFile $zip -UseBasicParsing
                    $downloaded = $true
                    break
                } catch {
                    Say ("No archive at branch {0}." -f $candidate)
                }
            }
        }
        if (-not $downloaded) {
            Fail ("Could not download {0}. Check the URL, or pass -Branch." -f $base)
        }

        $expanded = Join-Path $temp "expanded"
        Expand-Archive -LiteralPath $zip -DestinationPath $expanded -Force

        $source = $null
        if (Test-Path (Join-Path $expanded "run_kira.py")) {
            $source = Get-Item -LiteralPath $expanded
        } else {
            $source = Get-ChildItem -LiteralPath $expanded -Directory |
                      Where-Object { Test-Path (Join-Path $_.FullName "run_kira.py") } |
                      Select-Object -First 1
            if ($null -eq $source) {
                # GitHub adds one wrapper folder; accept one extra level for older archives.
                $source = Get-ChildItem -LiteralPath $expanded -Directory |
                          ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Directory } |
                          Where-Object { Test-Path (Join-Path $_.FullName "run_kira.py") } |
                          Select-Object -First 1
            }
        }
        if ($null -eq $source) { Fail "The archive does not contain a Kira checkout." }

        if (Test-Path -LiteralPath $Destination) {
            if (Test-Checkout $Destination) {
                Say ("{0} already has Kira; keeping it." -f $Destination)
                return $Destination
            }
            if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
                Fail ("{0} already exists as a file. Choose another -InstallDir." -f $Destination)
            }
            if (@(Get-ChildItem -LiteralPath $Destination -Force).Count -gt 0) {
                Fail ("{0} already exists and is not empty. Choose another -InstallDir." -f $Destination)
            }
            Remove-Item -LiteralPath $Destination -Force
        }

        $parent = Split-Path -Parent $Destination
        if (-not (Test-Path -LiteralPath $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        if (-not (Test-Path -LiteralPath $Destination)) {
            New-Item -ItemType Directory -Path $Destination -Force | Out-Null
        }
        Get-ChildItem -LiteralPath $source.FullName -Force | Move-Item -Destination $Destination
        if (-not (Test-Checkout $Destination)) { Fail "Could not unpack the Kira checkout." }
        Say ("Source downloaded to {0}" -f $Destination)
        return $Destination
    } finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Install-Kira($Tools, [string]$Root) {
    $venv = Join-Path $Root "kira-engine\.venv"
    $venvPython = Join-Path $venv "Scripts\python.exe"

    if (-not (Test-Path -LiteralPath $venvPython)) {
        Say "Creating the Python environment..."
        $arguments = @($Tools.Python.Args) + @("-m", "venv", $venv)
        & $Tools.Python.Exe @arguments
        if ($LASTEXITCODE -ne 0) { Fail "Could not create the Python environment." }
    }

    Say "Installing the engine..."
    Push-Location (Join-Path $Root "kira-engine")
    try {
        & $venvPython -m pip install --disable-pip-version-check -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { Fail "pip install failed." }

        Say "Installing native-window support..."
        & $venvPython -m pip install --disable-pip-version-check -e ".[desktop]"
        if ($LASTEXITCODE -ne 0) {
            Say "Native-window extras were not installed; browser mode still works."
        }
    } finally {
        Pop-Location
    }

    if ($SkipBuild) {
        Say "Skipping the UI build (-SkipBuild)."
        return
    }

    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) { $npmCommand = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npmCommand) { Fail "npm was not found beside Node. Reinstall Node.js with npm included." }
    $npm = $npmCommand.Source
    if (-not $npm) { $npm = $npmCommand.Path }

    $chat = Join-Path $Root "kira-chat"
    Push-Location $chat
    try {
        if (-not (Test-Path (Join-Path $chat "node_modules"))) {
            Say "Installing UI dependencies..."
            & $npm ci --no-audit --no-fund
        } else {
            Say "Updating UI dependencies..."
            & $npm install --no-audit --no-fund
        }
        if ($LASTEXITCODE -ne 0) { Fail "npm install failed." }

        Say "Building the UI..."
        & $npm run build
        if ($LASTEXITCODE -ne 0) { Fail "npm run build failed." }
    } finally {
        Pop-Location
    }
}

function Install-LocalModels([string]$Root) {
    $folder = Join-Path $Root "kira-3dmodels"
    if (-not (Test-Path -LiteralPath $folder -PathType Container)) {
        Say "No local 3D models folder; skipping model import."
        return
    }

    $archives = @(Get-ChildItem -LiteralPath $folder -File |
        Where-Object { $_.Extension -in @(".zip", ".pmx") })
    if ($archives.Count -eq 0) {
        Say "No local 3D model archives found; the avatar library stays as it is."
        return
    }
    if ($SkipModels) {
        Say ("Skipping {0} local 3D model archive(s) (-SkipModels)." -f $archives.Count)
        return
    }

    $venvPython = Join-Path $Root "kira-engine\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Say "The engine environment is missing; run setup once before importing models."
        return
    }

    Say ("Importing {0} local 3D model archive(s)..." -f $archives.Count)
    $previousDataDir = $env:KIRA_DATA_DIR
    $previousErrorAction = $ErrorActionPreference
    $errorFile = [System.IO.Path]::GetTempFileName()
    try {
        $env:KIRA_DATA_DIR = Join-Path $Root ".kira-data"
        # A refused archive writes to stderr and exits 1 by design. With EAP=Stop a native
        # stderr redirect would turn that report into a terminating error and abort the
        # whole install, so the child's stream is data here, not a PowerShell failure.
        $ErrorActionPreference = "Continue"
        $raw = & $venvPython -m kira characters import-dir $folder 2> $errorFile
        $code = $LASTEXITCODE
        $errors = [string](Get-Content -LiteralPath $errorFile -Raw -ErrorAction SilentlyContinue)
    } finally {
        $ErrorActionPreference = $previousErrorAction
        if ($null -eq $previousDataDir) {
            Remove-Item Env:KIRA_DATA_DIR -ErrorAction SilentlyContinue
        } else {
            $env:KIRA_DATA_DIR = $previousDataDir
        }
        Remove-Item -LiteralPath $errorFile -Force -ErrorAction SilentlyContinue
    }

    $text = (($raw | ForEach-Object { [string]$_ }) -join "`n").Trim()
    if (-not $text) {
        Say ("Could not import the local models. {0}" -f $errors.Trim())
        return
    }
    try {
        $summary = $text | ConvertFrom-Json
    } catch {
        Say "Could not read the model import report; the app still starts."
        return
    }

    $counts = $summary.counts
    Say ("3D models: {0} imported, {1} already present, {2} refused." -f
        $counts.imported, $counts.already_imported, $counts.failed)
    foreach ($row in @($summary.failed)) {
        $detail = [string]$row.error
        if ($detail.Length -gt 180) { $detail = $detail.Substring(0, 177) + "..." }
        Say ("  refused {0}: {1}" -f $row.file, $detail)
    }
    if ($code -ne 0) {
        Say "Some local models were refused; Kira still starts."
    }
}

function New-Shortcut([string]$Root) {
    try {
        $desktop = [Environment]::GetFolderPath("Desktop")
        if (-not $desktop) { return }
        $path = Join-Path $desktop "Kira.lnk"
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut($path)
        $link.TargetPath = Join-Path $Root "run-kira.bat"
        $link.WorkingDirectory = $Root
        $link.Description = "Start Kira"
        $link.Save()
        Say ("Desktop shortcut: {0}" -f $path)
    } catch {
        Say ("Could not create the desktop shortcut: {0}" -f $_.Exception.Message)
    }
}

try {
    Say "Kira setup"
    $root = $LocalRoot
    $hasLocal = Test-Checkout $root

    if ($CheckOnly) {
        if ($hasLocal) { Say ("Source: {0}" -f $root) }
        else {
            $preview = Format-RepoUrl (Get-RepoUrl)
            Say ("Would download: {0}" -f $preview)
        }
        $tools = Ensure-Prerequisites
        Say ("Python: {0} {1}" -f $tools.Python.Exe, ($tools.Python.Args -join " "))
        Say ("Node: v{0}" -f $tools.Node)
        $modelFolder = Join-Path $root "kira-3dmodels"
        if (Test-Path -LiteralPath $modelFolder -PathType Container) {
            $modelCount = @(Get-ChildItem -LiteralPath $modelFolder -File |
                Where-Object { $_.Extension -in @(".zip", ".pmx") }).Count
            Say ("Local 3D models: {0} archive(s) ready to import." -f $modelCount)
        }
        Say "Check passed. Nothing was installed."
        exit 0
    }

    if ($DownloadOnly) { $hasLocal = $false }

    if (-not $hasLocal) {
        $url = Get-RepoUrl
        $target = $InstallDir
        if (-not $target -or $target.Trim().Length -eq 0) { $target = Join-Path $env:USERPROFILE "Kira" }
        $root = Download-Source $url $target
    } else {
        Say ("Using the checkout at {0}" -f $root)
    }

    if ($DownloadOnly) {
        Say ("Source ready: {0}" -f $root)
        Say ("Start it with {0}" -f (Join-Path $root "setup\Kira-Setup.cmd"))
        exit 0
    }

    if ($ModelsOnly) {
        $venvPython = Join-Path $root "kira-engine\.venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            Fail "No engine environment yet. Run Kira-Setup.cmd once without -ModelsOnly first."
        }
        Install-LocalModels $root
        exit 0
    }

    $tools = Ensure-Prerequisites
    Install-Kira $tools $root
    Install-LocalModels $root
    if (-not $NoShortcut) { New-Shortcut $root }

    if ($NoLaunch) {
        Say ("Ready. Double-click {0} to start." -f (Join-Path $root "run-kira.bat"))
    } else {
        Say "Starting Kira..."
        Start-Process -FilePath (Join-Path $root "run-kira.bat") -WorkingDirectory $root
    }
    exit 0
} catch {
    Write-Host ("{0} ERROR: {1}" -f $Prefix, $_.Exception.Message) -ForegroundColor Red
    exit 1
}
