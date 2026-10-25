"""Exercise shell argument/exit contracts without Studio or external downloads."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe')
BASH = ('C:/Program Files/Git/bin/bash.exe' if
        Path('C:/Program Files/Git/bin/bash.exe').is_file() else shutil.which('bash'))


class DownloaderEntryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='downloader-entry-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / '中文 ไทย space'
        self.root.mkdir()
        (self.root / 'scripts').mkdir()
        for name in ('youtube_download.ps1', 'youtube_download.cmd', 'youtube_download.command',
                     'workbench.ps1', 'workbench.cmd'):
            shutil.copy2(ROOT / name, self.root / name)
        (self.root / 'scripts/downloader.py').write_text(
            "import json, os, sys\n"
            "from pathlib import Path\n"
            "Path(os.environ['ENTRY_CAPTURE']).write_text(json.dumps({"
            "'args':sys.argv[1:], 'python':sys.executable, 'prefix':sys.prefix,"
            "'base_prefix':sys.base_prefix},ensure_ascii=False),encoding='utf-8')\n"
            "sys.exit(int(os.environ.get('ENTRY_EXIT','0')))\n", encoding='utf-8')
        # Any fallback to the old environment must fail before writing evidence.
        for relative in ('.venv/Scripts/python.exe', '.venv/bin/python'):
            poison = self.root / relative
            poison.parent.mkdir(parents=True, exist_ok=True)
            poison.write_bytes(b'not an interpreter')
            poison.chmod(0o755)
        self.capture = self.root / 'capture.json'
        self.env = {key: value for key, value in os.environ.items()
                    if key not in ('WORKBENCH_PYTHON', 'DOWNLOADER_PYTHON')}
        self.env.update(ENTRY_CAPTURE=str(self.capture), WORKBENCH_NO_PAUSE='1',
                        PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        self.url = 'https://www.youtube.com/watch?v=entry001&t=657s&name=中文ไทย'

    def run_entry(self, command, code=0):
        result = subprocess.run(command, cwd=self.root, env=self.env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=40)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return result

    def assert_capture(self):
        captured = json.loads(self.capture.read_text(encoding='utf-8'))
        self.assertEqual(captured['args'], ['--simulate', self.url])
        self.assertEqual(captured['prefix'], captured['base_prefix'])
        self.assertNotIn('.venv', captured['python'])

    @unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Windows shells required')
    def test_windows_entries_preserve_url_and_nonzero_status_without_studio(self):
        for filename, action in (('youtube_download.ps1', []), ('workbench.ps1', ['download']),
                                 ('youtube_download.cmd', []), ('workbench.cmd', ['download'])):
            with self.subTest(filename=filename):
                self.env['ENTRY_EXIT'] = '7'
                target = str(self.root / filename)
                if filename.endswith('.ps1'):
                    command = [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                               '-File', target, *action, '--simulate', self.url]
                else:
                    # cmd requires explicit quoting for URLs containing ampersands.
                    tail = ' '.join([*action, '--simulate', '"' + self.url + '"'])
                    command = '"' + os.environ['COMSPEC'] + '" /d /s /c ""' + target + '" ' + tail + '"'
                self.run_entry(command, 7)
                self.assert_capture()
                self.capture.unlink()

    @unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Windows shell required')
    def test_invalid_explicit_python_fails_without_automatic_fallback(self):
        self.env['DOWNLOADER_PYTHON'] = str(self.root / 'missing python.exe')
        result = self.run_entry([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass',
                                 '-File', str(self.root / 'youtube_download.ps1'), '--check'], 1)
        self.assertIn('DOWNLOADER_PYTHON', result.stdout)
        self.assertFalse(self.capture.exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows dispatcher required')
    def test_legacy_dispatcher_runs_downloader_script_without_studio_environment(self):
        for name in ('windows_entry.py', 'windows_environment.py'):
            shutil.copy2(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        self.env['ENTRY_EXIT'] = '7'
        self.run_entry([sys.executable, '-X', 'utf8', str(self.root / 'scripts/windows_entry.py'),
                        'download', '--simulate', self.url], 7)
        self.assert_capture()

    @unittest.skipUnless(BASH, 'Bash required; Git Bash is not macOS validation')
    def test_bash_entry_preserves_url_and_exit_status_without_studio(self):
        self.env.update(DOWNLOADER_PYTHON=sys.executable, ENTRY_EXIT='9')
        self.run_entry([BASH, str(self.root / 'youtube_download.command'),
                        '--simulate', self.url], 9)
        self.assert_capture()

    @unittest.skipUnless(BASH, 'Bash required; Git Bash is not macOS validation')
    def test_bash_entry_rejects_invalid_explicit_python(self):
        self.env['DOWNLOADER_PYTHON'] = str(self.root / 'missing python')
        self.run_entry([BASH, str(self.root / 'youtube_download.command'), '--check'], 1)
        self.assertFalse(self.capture.exists())


if __name__ == '__main__':
    unittest.main()
