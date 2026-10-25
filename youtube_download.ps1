# Standalone downloader: use a compatible installed Python, without Studio setup.
param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$explicitPython = if ($env:DOWNLOADER_PYTHON) { $env:DOWNLOADER_PYTHON } else { $env:WORKBENCH_PYTHON }
$candidates = @()
if ($explicitPython) {
    $candidates += $explicitPython
} else {
    # PATH may contain an activated environment; the probe below rejects it.
    foreach ($name in @('python.exe', 'python3.exe')) {
        $candidates += @(Get-Command $name -CommandType Application -All -ErrorAction SilentlyContinue |
            Where-Object { $_.Source -notlike '*\Microsoft\WindowsApps\*' } |
            ForEach-Object { $_.Source })
    }
    foreach ($version in @('314', '313', '312', '311', '310')) {
        $candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$version\python.exe"
    }
}
$downloaderPython = $null
foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    $probe = 'import sys; sys.exit(sys.version_info < (3, 10))'
    if (-not $explicitPython) { $probe += ' if sys.prefix == sys.base_prefix else sys.exit(1)' }
    try {
        & $candidate -X utf8 -c $probe 2>$null
        if ($LASTEXITCODE -eq 0) { $downloaderPython = $candidate; break }
    } catch { continue }
}
if (-not $downloaderPython) {
    Write-Host 'A working Python 3.10+ is required. Set DOWNLOADER_PYTHON to its full executable path.'
    exit 1
}
& $downloaderPython -X utf8 (Join-Path $PSScriptRoot 'scripts\downloader.py') @Arguments
exit $LASTEXITCODE
