# Native PowerShell entry preserves URLs containing &, quotes and Unicode.
param(
    [Parameter(Position=0, Mandatory=$true)]
    [ValidateSet('setup', 'check', 'start', 'setup-asr', 'download')]
    [string]$Action,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
if ($Action -eq 'download') {
    & (Join-Path $PSScriptRoot 'youtube_download.ps1') @Arguments
    exit $LASTEXITCODE
}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$candidates = @(
    $env:WORKBENCH_PYTHON,
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
)
$workbenchPython = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $workbenchPython) { throw 'Install Python 3.13, or set WORKBENCH_PYTHON to its executable.' }
& $workbenchPython -X utf8 (Join-Path $PSScriptRoot 'scripts\windows_entry.py') $Action @Arguments
exit $LASTEXITCODE
