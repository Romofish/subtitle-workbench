# Create SE workflow shortcuts; preserve every existing shortcut and legacy group.
param([switch]$Desktop)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$toolsRoot = if ($env:WORKBENCH_TOOLS_DIR) { $env:WORKBENCH_TOOLS_DIR } else { Join-Path $env:LOCALAPPDATA 'Programs\SubtitleWorkbench' }
$seCandidates = @()
$manifestPath = Join-Path $toolsRoot 'installed.json'
if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $seCandidates += $manifest.tools.SubtitleEdit.executable
    } catch {
        Write-Warning 'Cannot read installed.json; checking the existing Subtitle Edit directory and PATH.'
    }
}
$seCandidates += Join-Path $toolsRoot 'SubtitleEdit\SubtitleEdit.exe'
$seCandidates += @(Get-Command SubtitleEdit.exe -CommandType Application -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })
$subtitleEdit = $seCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $subtitleEdit) { throw 'Subtitle Edit was not found. Reuse an installed copy before creating shortcuts.' }
$subtitleEdit = (Resolve-Path -LiteralPath $subtitleEdit).Path
$downloader = Join-Path $projectRoot 'youtube_download.cmd'
# Check the complete standalone entry before creating any shortcuts.
foreach ($relative in @('youtube_download.cmd', 'youtube_download.ps1', 'scripts\downloader.py', 'scripts\windows_environment.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relative) -PathType Leaf)) {
        throw "Missing standalone downloader file: $relative"
    }
}
$items = @(
    @{Name='Subtitle Edit - SE Workflow'; Target=$subtitleEdit; WorkingDirectory=(Split-Path $subtitleEdit -Parent)},
    @{Name='YouTube Downloader - SE Workflow'; Target=$downloader; WorkingDirectory=$projectRoot}
)
$folders = @(Join-Path ([Environment]::GetFolderPath('Programs')) 'Subtitle Workflow')
if ($Desktop) { $folders += [Environment]::GetFolderPath('Desktop') }
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in ($folders | Select-Object -Unique)) {
    if (-not $folder) { throw 'Windows did not provide a current-user shortcut folder.' }
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    foreach ($item in $items) {
        $shortcutPath = $null
        $status = 'created'
        for ($suffix = 0; $suffix -lt 100; $suffix++) {
            $name = if ($suffix -eq 0) { $item.Name } else { "$($item.Name) ($suffix)" }
            $candidate = Join-Path $folder ($name + '.lnk')
            if (-not (Test-Path -LiteralPath $candidate)) { $shortcutPath = $candidate; break }
            # Reuse identical links without saving them; unrelated names are never overwritten.
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                $existing = $shell.CreateShortcut($candidate)
                if ($existing.TargetPath -eq $item.Target -and
                    $existing.Arguments -eq '' -and
                    $existing.WorkingDirectory -eq $item.WorkingDirectory) {
                    $shortcutPath = $candidate
                    $status = 'reused'
                    break
                }
            }
        }
        if (-not $shortcutPath) { throw "No unused shortcut name for $($item.Name)" }
        if ($status -eq 'created') {
            $link = $shell.CreateShortcut($shortcutPath)
            $link.TargetPath = $item.Target
            $link.Arguments = ''
            $link.WorkingDirectory = $item.WorkingDirectory
            $link.Description = 'SE workflow: subtitle editing and standalone downloading'
            $link.Save()
        }
        $verified = $shell.CreateShortcut($shortcutPath)
        if ($verified.TargetPath -ne $item.Target -or $verified.Arguments -ne '' -or
            $verified.WorkingDirectory -ne $item.WorkingDirectory) {
            throw "Shortcut verification failed: $shortcutPath"
        }
        [pscustomobject]@{
            Path=$shortcutPath; Target=$verified.TargetPath; Arguments=$verified.Arguments
            WorkingDirectory=$verified.WorkingDirectory; Status=$status
        }
    }
}
