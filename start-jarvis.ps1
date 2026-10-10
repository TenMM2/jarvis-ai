# Start Jarvis with the keys from .env loaded into the process environment.
# The server does not read .env by itself. Keys are never printed.
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$envFile = Join-Path $PSScriptRoot '.env'
if (-not (Test-Path $envFile)) {
    Write-Host 'Missing .env - copy .env.example to .env and add your keys.' -ForegroundColor Red
    exit 1
}

Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), 'Process')
    }
}

if (-not $env:GEMINI_API_KEY) {
    Write-Host 'GEMINI_API_KEY is empty in .env' -ForegroundColor Yellow
}

$jarvisArgs = @('gui')
if ($NoBrowser) { $jarvisArgs += '--no-browser' }
& (Join-Path $PSScriptRoot '.venv\Scripts\jarvis.exe') @jarvisArgs
