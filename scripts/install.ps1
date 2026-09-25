$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvPath = Join-Path $RepoRoot ".venv"
if (-not (Test-Path -LiteralPath $VenvPath)) { py -m venv $VenvPath }
$PythonPath = Join-Path $VenvPath "Scripts\python.exe"
& $PythonPath -m pip install --upgrade pip
& $PythonPath -m pip install -e "$RepoRoot[google,windows,dev]"
& (Join-Path $VenvPath "Scripts\gideon.exe") install-vosk-model
Write-Host "Installed. Run: .\.venv\Scripts\gideon.exe setup"
