"""Install missing, verified Windows tools into the current user's Programs folder.

This script is an explicit installer. Normal workbench startup never downloads tools.
Run with --only python/core/gui/all. Existing tools are reused; data is never deleted.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import zipfile

from windows_environment import configure_tools, read_installed_manifest, write_installed_manifest

PACKAGES = {
    'python': dict(version='3.13.17', file='python-3.13.17-amd64.exe',
        url='https://www.python.org/ftp/python/3.13.17/python-3.13.17-amd64.exe', exe='python.exe'),
    'ffmpeg': dict(version='9.0.2', file='ffmpeg-9.0.2-essentials_build.zip',
        url='https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip',
        sha256='60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba', exe='ffmpeg.exe'),
    'yt-dlp': dict(version='2026.10.21', file='yt-dlp.exe',
        url='https://github.com/yt-dlp/yt-dlp/releases/download/2026.10.21/yt-dlp.exe',
        sha256='33121d192d706e62f684a06f80918e3f3a8ba52ac3a65213b6951c39c7d9f555', exe='yt-dlp.exe'),
    'deno': dict(version='2.9.8', file='deno-x86_64-pc-windows-msvc.zip',
        url='https://github.com/denoland/deno/releases/download/v2.9.8/deno-x86_64-pc-windows-msvc.zip',
        sha256='cba84b26e0df5ae7f74fc66b86a95b866872a86292ebd84fa1e959927edd93bf', exe='deno.exe'),
    'SubtitleEdit': dict(version='5.3.0', file='SubtitleEdit-Windows-x64.zip',
        url='https://github.com/SubtitleEdit/subtitleedit/releases/download/v5.3.0/SubtitleEdit-Windows-x64.zip',
        sha256='ea37eb670df040e7b606f87b602bbb727ab3170541190cab7803fb564921ffb1', exe='SubtitleEdit.exe'),
    'Aegisub': dict(version='3.5.1', file='Aegisub-3.5.1-x64-portable.zip',
        url='https://github.com/TypesettingTools/Aegisub/releases/download/v3.5.1/Aegisub-3.5.1-x64-portable.zip',
        sha256='e8349f18e1bcd4d57e3361683a1289d8ce3f3baebad30228752a41414b444403', exe='aegisub.exe'),
    'LosslessCut': dict(version='3.70.1', file='LosslessCut-win-x64.7z',
        url='https://github.com/mifi/lossless-cut/releases/download/v3.70.1/LosslessCut-win-x64.7z',
        sha256='a504ce3f2a8908b5ca8fb937eadd8c5677e2a1d33913506b33bd8276525e2066', exe='LosslessCut.exe'),
    'VLC': dict(version='3.0.24', file='vlc-3.0.24-win64.zip',
        url='https://download.videolan.org/pub/videolan/vlc/3.0.24/win64/vlc-3.0.24-win64.zip',
        sha256='fcf30850371ad10c9373cc4f0f4501e7dee49e3e9ae9f20c72fb2661a1ca6323', exe='vlc.exe'),
}


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


INSTALL_MARKER = '.workbench-install.json'


def within(path, directory):
    return path.resolve().is_relative_to(directory.resolve())


def managed_existing(name, package, root, manifest):
    folder = root / name
    marker = folder / INSTALL_MARKER
    if marker.is_file():
        try:
            receipt = json.loads(marker.read_text(encoding='utf-8'))
            if receipt['version'] != package['version'] or receipt['archive_sha256'] != package['sha256']:
                return None
            executable = folder / receipt['executable']
            if not within(executable, folder) or not executable.is_file():
                return None
            files = receipt['files']
            if not isinstance(files, list) or not files:
                return None
            for item in files:
                path = folder / item['path']
                if not within(path, folder) or not path.is_file() or path.stat().st_size != item['bytes']:
                    return None
            return executable
        except (OSError, ValueError, KeyError, TypeError):
            return None
    # Older installations wrote the global record only after extraction had
    # finished. Accept that evidence so this update reuses existing complete tools.
    record = manifest.get('tools', {}).get(name, {})
    executable = Path(record.get('executable', ''))
    if (record.get('archive_sha256') == package.get('sha256') and
            record.get('version') == package['version'] and within(executable, folder) and executable.is_file()):
        if name != 'ffmpeg' or (executable.parent / 'ffprobe.exe').is_file():
            return executable
    return None


def existing(name, package, root, manifest=None):
    if name == 'python':
        candidates = [Path(os.environ['LOCALAPPDATA']) / 'Programs/Python/Python313/python.exe']
        for candidate in candidates:
            if candidate.is_file():
                result = subprocess.run([str(candidate), '-c', 'import sys;sys.exit(sys.version_info[:2] not in ((3,12),(3,13)))'])
                if result.returncode == 0:
                    return candidate
        return None
    manifest = manifest if manifest is not None else read_installed_manifest(root / 'installed.json')
    found = shutil.which(package['exe'])
    if found and not within(Path(found), root):
        return Path(found)
    managed = managed_existing(name, package, root, manifest)
    if managed:
        return managed
    for base in (Path(os.environ['LOCALAPPDATA']) / 'Programs' / name,
                 Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / name,
                 Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'VideoLAN' / name):
        if base.is_dir() and not within(base, root):
            matches = list(base.rglob(package['exe']))
            if matches:
                return matches[0]
    return None


def fetch(name, root):
    package = PACKAGES[name]
    destination = root / 'downloads' / package['file']
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file():
        partial = destination.with_suffix(destination.suffix + '.partial')
        print(f'Downloading {name} {package["version"]}...', flush=True)
        subprocess.run(['curl.exe', '--fail', '--location', '--retry', '3', '--connect-timeout', '30',
                        '--silent', '--show-error', '--continue-at', '-', '--output', str(partial), package['url']], check=True)
        partial.replace(destination)
    actual = digest(destination)
    if package.get('sha256') and actual != package['sha256']:
        raise RuntimeError(f'SHA-256 mismatch: {destination}; retained for inspection, not installed')
    if name == 'python':
        # Python's official installer is Authenticode signed by the PSF.
        signature_env = dict(os.environ, SUBTITLE_INSTALLER_VERIFY_PATH=str(destination))
        signature_env.pop('PSModulePath', None)
        signature = subprocess.check_output([shutil.which('pwsh.exe') or 'powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            "$s=Get-AuthenticodeSignature -LiteralPath $env:SUBTITLE_INSTALLER_VERIFY_PATH; [pscustomobject]@{status=[string]$s.Status;subject=$s.SignerCertificate.Subject}|ConvertTo-Json -Compress"], text=True, encoding='utf-8', env=signature_env)
        signed = json.loads(signature)
        if signed['status'] != 'Valid' or 'Python Software Foundation' not in signed['subject']:
            raise RuntimeError('Python installer signature not verified; refusing installation')
    print(f'Verified {name}: {actual}', flush=True)
    return destination, actual


def extract(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    if archive.suffix == '.zip':
        with zipfile.ZipFile(archive) as bundle:
            for item in bundle.infolist():
                target = (destination / item.filename).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise RuntimeError('Unsafe archive path')
            bundle.extractall(destination)
    else:
        names = subprocess.check_output(['tar.exe', '-tf', str(archive)], text=True, encoding='utf-8')
        for name in names.splitlines():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError('Unsafe archive path')
        subprocess.run(['tar.exe', '-xf', str(archive), '-C', str(destination)], check=True)


def install_portable(name, package, archive, archive_sha256, root):
    """Stage a full package, then promote it without losing an older directory."""
    if name not in PACKAGES:
        raise ValueError('Unknown tool name')
    folder = root / name
    stage = root / '.staging' / f'{name}-{uuid.uuid4().hex}'
    backup = root / 'backups' / f'{name}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex}'
    # Check every resolved move target before creating or moving directories.
    if not all(within(path, root) and path.resolve() != root.resolve() for path in (folder, stage, backup)):
        raise RuntimeError('Tool installation paths escape the configured tools directory')
    stage.mkdir(parents=True)
    try:
        if archive.suffix == '.exe':
            shutil.copy2(archive, stage / package['exe'])
        else:
            extract(archive, stage)
        matches = [path for path in stage.rglob(package['exe']) if path.is_file() and path.stat().st_size]
        if len(matches) != 1:
            raise RuntimeError(f'{name}: expected one non-empty {package["exe"]}, found {len(matches)}')
        executable = matches[0]
        if name == 'ffmpeg' and not (executable.parent / 'ffprobe.exe').is_file():
            raise RuntimeError('FFmpeg package is missing ffprobe.exe')
        receipt = dict(version=package['version'], archive_sha256=archive_sha256,
                       executable=executable.relative_to(stage).as_posix(),
                       files=[{'path': path.relative_to(stage).as_posix(), 'bytes': path.stat().st_size}
                              for path in sorted(stage.rglob('*')) if path.is_file()])
        (stage / INSTALL_MARKER).write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        relative_executable = executable.relative_to(stage)
        moved_old = False
        if folder.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            folder.replace(backup)
            moved_old = True
            print(f'Preserved previous {name} directory: {backup}', flush=True)
        try:
            stage.replace(folder)
        except OSError:
            if moved_old and not folder.exists():
                backup.replace(folder)
            raise
        return folder / relative_executable
    except BaseException:
        print(f'{name}: installation was not completed; staging files retained at {stage}', file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['python', 'core', 'gui', 'all'], default='all')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Windows only')
    root = configure_tools()
    names = ['python'] if args.only == 'python' else (
        ['ffmpeg', 'yt-dlp', 'deno'] if args.only == 'core' else
        ['SubtitleEdit', 'Aegisub', 'LosslessCut', 'VLC'] if args.only == 'gui' else list(PACKAGES))
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / 'installed.json'
    manifest = read_installed_manifest(manifest_path)
    missing = []
    for name in names:
        located = existing(name, PACKAGES[name], root, manifest)
        if located:
            print(f'Reuse {name}: {located}', flush=True)
            if manifest['tools'].get(name, {}).get('executable') != str(located):
                manifest['tools'][name] = {'executable': str(located), 'reused': True}
        else:
            missing.append(name)
    # Downloads are independent; installation and manifest updates are sequential.
    with ThreadPoolExecutor(max_workers=4) as pool:
        downloads = {name: pool.submit(fetch, name, root) for name in missing}
        for name in missing:
            archive, actual = downloads[name].result()
            if name == 'python':
                folder = Path(os.environ['LOCALAPPDATA']) / 'Programs/Python/Python313'
                result = subprocess.run([str(archive), '/quiet', 'InstallAllUsers=0',
                    f'TargetDir={folder}', 'PrependPath=0', 'Include_launcher=0', 'Include_test=0',
                    '/log', str(root / 'downloads/python-install.log')])
                if result.returncode not in (0, 3010):
                    raise RuntimeError(f'Python installer returned {result.returncode}')
                located = existing(name, PACKAGES[name], root, manifest)
            else:
                located = install_portable(name, PACKAGES[name], archive, actual, root)
            if not located:
                raise RuntimeError(f'{name}: expected executable missing after installation')
            manifest['tools'][name] = dict(version=PACKAGES[name]['version'], executable=str(located),
                source=PACKAGES[name]['url'], archive_sha256=actual, installed_at=datetime.now(timezone.utc).isoformat())
            write_installed_manifest(manifest_path, manifest)
            print(f'Installed {name}: {located}', flush=True)
    write_installed_manifest(manifest_path, manifest)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
