# Open Jarvis in the terminal with the keys from .env loaded.
# Usage:  .\jarvis-terminal.ps1            (chat)
#         .\jarvis-terminal.ps1 ask "hello"   (any jarvis subcommand)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

Get-Content (Join-Path $PSScriptRoot '.env') | ForEach-Object {
    if ($_ -match '^\s*([A-Z0-9_]+)\s*=\s*(.+?)\s*$') {
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim('"'), 'Process')
    }
}

& (Join-Path $PSScriptRoot '.venv\Scripts\jarvis.exe') @args
