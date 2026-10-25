"""Windows setup, diagnostics and thin command dispatch for the shared workbench."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import sys

from windows_environment import configure_tools

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv/Scripts/python.exe'


def run(command, cwd=ROOT):
    return subprocess.run([str(part) for part in command], cwd=cwd, check=True)


def setup():
    if sys.version_info[:2] not in ((3, 12), (3, 13)):
        raise RuntimeError('Install Python 3.13 x64, or set WORKBENCH_PYTHON to a Python 3.12/3.13 executable.')
    if PYTHON.exists():
        run([PYTHON, '-c', 'import sys;sys.exit(sys.version_info[:2] not in ((3,12),(3,13)))'])
    else:
        if PYTHON.parent.parent.exists():
            raise RuntimeError('Existing .venv is not a Windows environment. Keep and rename it before setup.')
        run([sys.executable, '-m', 'venv', ROOT / '.venv'])
    node = shutil.which('node.exe')
    npm = shutil.which('npm.cmd')
    if not node or not npm:
        raise RuntimeError('Node.js and npm are required. Install Node.js LTS first.')
    run([node, '-e', 'const [a,b]=process.versions.node.split(".").map(Number);process.exit((a===20&&b>=19)||(a===22&&b>=12)||a>22?0:1)'])
    missing = [name for name in ('ffmpeg', 'ffprobe') if not shutil.which(name)]
    if missing:
        raise RuntimeError('Missing tools: ' + ', '.join(missing) + '. Run install_windows_tools.py --only core.')
    os.environ.setdefault('PIP_CACHE_DIR', str(ROOT / '.cache/pip'))
    os.environ.setdefault('npm_config_cache', str(ROOT / '.cache/npm'))
    lock = ROOT / 'backend/requirements.lock'
    run([PYTHON, '-m', 'pip', 'install', '-r', lock if lock.exists() else ROOT / 'backend/requirements.txt'])
    run([PYTHON, '-m', 'pip', 'check'])
    run([npm, 'ci'], ROOT / 'frontend')
    run([npm, 'run', 'build'], ROOT / 'frontend')
    if not (ROOT / '.env').exists():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
    print('Setup complete. Double-click start.cmd to open the workbench. AI translation remains opt-in.')


def check(as_json=False):
    report = {'python': sys.version.split()[0], 'python_path': sys.executable,
              'python_supported': sys.version_info[:2] in ((3, 12), (3, 13)),
              'virtual_environment': PYTHON.is_file(), 'frontend_built': (ROOT / 'frontend/dist/index.html').is_file(),
              'tools_root': str(configure_tools()), 'tools': {}, 'port_8765_free': True}
    for name in ('node', 'npm.cmd', 'ffmpeg', 'ffprobe', 'yt-dlp', 'deno'):
        path = shutil.which(name)
        version = None
        if path:
            flag = '-version' if name in ('ffmpeg', 'ffprobe') else '--version'
            result = subprocess.run([path, flag], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
            version = (result.stdout or result.stderr).splitlines()[0] if (result.stdout or result.stderr) else None
        report['tools'][name] = {'path': path, 'version': version}
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', 8765))
        except OSError:
            report['port_8765_free'] = False
    asr = Path(os.environ.get('SUBTITLE_ASR_DIR', ROOT / 'tools/asr'))
    report['asr'] = {'directory': str(asr), 'engine': (asr / 'bin/whisper-cli.exe').is_file(),
                     'model': (asr / 'models/ggml-large-v3-turbo-q5_0.bin').is_file()}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['python_supported'] and all(report['tools'][name]['path'] for name in ('node', 'npm.cmd', 'ffmpeg', 'ffprobe')) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['setup', 'check', 'start', 'setup-asr', 'download'])
    args, remainder = parser.parse_known_args()
    if os.name != 'nt':
        parser.error('Use the .command entry points on macOS.')
    if args.action == 'download':
        # Legacy direct callers also bypass Studio's .env and virtual environment.
        target = ROOT / 'scripts' / 'downloader.py'
        sys.argv = [str(target), *remainder]
        runpy.run_path(str(target), run_name='__main__')
        return 0
    # Explicit local settings must be read before tool discovery supplies defaults.
    # A first-time setup has not installed python-dotenv yet.
    if importlib.util.find_spec('dotenv'):
        from dotenv import load_dotenv
        load_dotenv(ROOT / '.env', override=False)
    configure_tools()
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    try:
        if args.action == 'setup':
            setup()
            return 0
        if args.action == 'check':
            return check('--json' in remainder)
        script = {'start': 'launch.py', 'setup-asr': 'setup_asr.py', 'download': 'downloader.py'}[args.action]
        python = PYTHON if PYTHON.is_file() else Path(sys.executable)
        if args.action == 'start' and (not PYTHON.is_file() or not (ROOT / 'frontend/dist/index.html').is_file()):
            raise RuntimeError('Run setup.cmd first to install dependencies and build the interface.')
        target = ROOT / 'scripts' / script
        if python.resolve() == Path(sys.executable).resolve():
            # Windows os.execv returns early to the calling .cmd and loses the
            # eventual exit status. Execute in-process to preserve console life.
            sys.argv = [str(target), *remainder]
            runpy.run_path(str(target), run_name='__main__')
            return 0
        process = subprocess.Popen([str(python), '-X', 'utf8', str(target), *remainder], cwd=ROOT)
        while True:
            try:
                return process.wait()
            except KeyboardInterrupt:
                # The attached console delivered the same Ctrl+C to the service;
                # let its supervisor finish closing its owned processes.
                continue
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
