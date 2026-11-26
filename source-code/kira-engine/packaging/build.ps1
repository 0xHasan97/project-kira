<# Build the desktop app: the chat bundle, then Kira.exe (one folder, no console window).

   .\packaging\build.ps1              # client build + exe
   .\packaging\build.ps1 -SkipClient  # reuse kira-chat\dist
#>
param([switch]$SkipClient)
$ErrorActionPreference = "Stop"

$engine = Split-Path -Parent $PSScriptRoot
$repo = Split-Path -Parent $engine
$python = Join-Path $engine ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "engine venv missing at $python - create it once with: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e `".[desktop,build]`""
}

if (-not $SkipClient) {
  Write-Host "building the chat bundle..."
  npm --prefix (Join-Path $repo "kira-chat") run build
  if ($LASTEXITCODE -ne 0) { throw "client build failed" }
}

$dist = Join-Path $repo "kira-chat\dist"
if (-not (Test-Path (Join-Path $dist "index.html"))) { throw "chat bundle missing at $dist" }

Push-Location $engine
try {
  & $python -m PyInstaller --noconfirm --clean --distpath packaging\dist --workpath build packaging\kira.spec
  if ($LASTEXITCODE -ne 0) { throw "pyinstaller failed" }
} finally {
  Pop-Location
}

Write-Host "built $engine\packaging\dist\Kira\Kira.exe"
