# Connect Google (Gmail, Calendar, Tasks) using the settings from .env.
# With JARVIS_GOOGLE_SCOPES=readonly in .env, Jarvis only gets read access.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Get-Content (Join-Path $PSScriptRoot '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), 'Process')
    }
}

Write-Host "Scopes mode: $($env:JARVIS_GOOGLE_SCOPES)" -ForegroundColor Cyan
& (Join-Path $PSScriptRoot '.venv\Scripts\jarvis.exe') connect gmail
