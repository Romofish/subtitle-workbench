"""Locate optional Windows tools without changing the user's global PATH."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import uuid


def _read_manifest(path: Path) -> dict:
    document = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or not isinstance(document.get('tools'), dict):
        raise ValueError('expected an object containing a tools object')
    for item in document['tools'].values():
        if not isinstance(item, dict) or not isinstance(item.get('executable'), str):
            raise ValueError('invalid tool entry')
    return document


def read_installed_manifest(path: Path, *, warn=True) -> dict:
    """Optional metadata must not prevent startup after an interrupted write."""
    if not path.exists():
        return {'tools': {}}
    try:
        return _read_manifest(path)
    except (OSError, ValueError, UnicodeError) as error:
        if warn:
            print(f'Warning: cannot read tool manifest {path}: {error}. '
                  'The file is preserved; checking known tool directories instead.', file=sys.stderr)
        return {'tools': {}}


def write_installed_manifest(path: Path, document: dict):
    """Publish a complete file atomically, retaining any damaged previous file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            _read_manifest(path)
        except (ValueError, UnicodeError):
            backup = path.with_name(f'{path.name}.damaged-{uuid.uuid4().hex}')
            shutil.copy2(path, backup)
            print(f'Preserved damaged tool manifest: {backup}', file=sys.stderr)
    temporary = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    # Same-directory replacement leaves the previous complete file available if
    # the process stops before this point. Failed temporary files are retained.
    temporary.replace(path)


def tools_root() -> Path:
    return Path(os.environ.get('WORKBENCH_TOOLS_DIR') or
                str(Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData/Local')) /
                    'Programs' / 'SubtitleWorkbench')).expanduser().resolve()


def asr_directory() -> Path:
    """Resolve installation and runtime paths before any directory exists."""
    return Path(os.environ.get('SUBTITLE_ASR_DIR') or str(tools_root() / 'asr')).expanduser().resolve()


def configure_tools() -> Path:
    root = tools_root()
    if os.name != 'nt':
        return root
    paths = []
    for name in ('ffmpeg', 'yt-dlp', 'deno'):
        folder = root / name
        if folder.is_dir():
            paths.extend([folder, folder / 'bin'])
            paths.extend(folder.glob('*/bin'))
    manifest = read_installed_manifest(root / 'installed.json')
    for item in manifest['tools'].values():
        exe = Path(item['executable'])
        if exe.is_file() and exe.name.lower() in ('ffmpeg.exe', 'yt-dlp.exe', 'deno.exe'):
            paths.append(exe.parent)
    # Keep an existing PATH installation ahead of our optional portable packages.
    additions = list(dict.fromkeys(str(path) for path in paths if path.is_dir()))
    os.environ['PATH'] = os.environ.get('PATH', '') + os.pathsep + os.pathsep.join(additions)
    os.environ.setdefault('PYTHONUTF8', '1')
    if not os.environ.get('SUBTITLE_ASR_DIR'):
        os.environ['SUBTITLE_ASR_DIR'] = str(asr_directory())
    return root
