"""Windows entry smoke test with real tools, local HTTP and no Studio files.

Run with a global Python. Git Bash checks are separate and do not validate macOS.
"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading


ROOT = Path(__file__).resolve().parents[1]


def main():
    if os.name != 'nt':
        raise SystemExit('This integration checks Windows entries; run the Mac entry on a Mac separately.')
    environment = {key: value for key, value in os.environ.items()
                   if key not in ('WORKBENCH_PYTHON', 'DOWNLOADER_PYTHON', 'PROXY_URL')}
    sys.path.insert(0, str(ROOT / 'scripts'))
    from windows_environment import configure_tools
    configure_tools()
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'Install FFmpeg before this integration.'
    with tempfile.TemporaryDirectory(prefix='downloader-shell-integration-') as temporary:
        base = Path(temporary)
        standalone = base / '独立 下载 ไทย'
        (standalone / 'scripts').mkdir(parents=True)
        for name in ('youtube_download.ps1', 'youtube_download.cmd', 'workbench.ps1', 'workbench.cmd',
                     'scripts/downloader.py', 'scripts/windows_environment.py'):
            shutil.copy2(ROOT / name, standalone / name)
        media = base / 'clip.mp4'
        subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=128x72:r=10:d=2',
                        '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', '2',
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(media)], check=True)
        requests = []

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                super().do_GET()

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(base)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            query = '/clip.mp4?source=one&keep=two'
            url = f'http://127.0.0.1:{server.server_port}{query}'
            environment.update(WORKBENCH_NO_PAUSE='1', DOWNLOAD_SUBS='yes', PYTHONUTF8='1',
                               PYTHONIOENCODING='utf-8', NO_PROXY='127.0.0.1,localhost',
                               no_proxy='127.0.0.1,localhost')
            for filename, action in (('youtube_download.ps1', ''), ('youtube_download.cmd', ''),
                                     ('workbench.ps1', 'download'), ('workbench.cmd', 'download')):
                output = base / ('字幕 输出 ไทย ' + filename)
                environment['YOUTUBE_DOWNLOAD_DIR'] = str(output)
                target = str(standalone / filename)

                def run(arguments, expected=0):
                    if filename.endswith('.ps1'):
                        command = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                   '-File', target, *([action] if action else []), *arguments]
                    else:
                        tail = ' '.join([action, *('"' + arg + '"' for arg in arguments)])
                        command = '"' + os.environ['COMSPEC'] + '" /d /s /c ""' + target + '" ' + tail + '"'
                    result = subprocess.run(command, cwd=base, env=environment, capture_output=True,
                                            text=True, encoding='utf-8', errors='replace', timeout=60)
                    assert result.returncode == expected, (filename, result.stdout, result.stderr)
                    return result

                run(['--check'])
                assert not output.exists(), 'Dependency checks must not create downloads.'
                run(['--simulate'], 2)
                run([url])
                manifests = list(output.rglob('*.sources.json'))
                assert len(manifests) == 1, (filename, manifests)
                record = json.loads(manifests[0].read_text(encoding='utf-8'))
                assert record['download']['status'] == 'completed', record
                assert record['subtitles']['status'] == 'no_matching_subtitles', record
                assert Path(record['media']['path']).is_file(), record
                assert Path(record['media']['path']).is_relative_to(output), record
                run([f'http://127.0.0.1:{server.server_port}/missing.mp4?source=one&keep=two'], 1)
                print(f'PASS {filename}: independent check/download, Unicode paths, quoted & URL, exit 0/1/2')
            relevant = [path for path in requests if path.startswith('/clip.mp4')]
            assert relevant and all(path == query for path in relevant), relevant
            assert not (standalone / '.venv').exists()
            assert not (standalone / 'backend').exists()
            assert not (standalone / 'frontend').exists()
            print('PASS minimal file set: no Studio environment, backend, frontend or dispatcher')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    main()
