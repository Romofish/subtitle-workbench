"""Offline interruption checks; no downloads or real applications are executed."""
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import install_windows_tools as installer
from windows_environment import configure_tools, read_installed_manifest, write_installed_manifest


class WindowsInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary_root = ROOT / '.runtime'
        temporary_root.mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(prefix='installer-test-', dir=temporary_root)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.package = installer.PACKAGES['yt-dlp']
        self.archive = self.root / 'fixture.zip'
        with zipfile.ZipFile(self.archive, 'w') as bundle:
            bundle.writestr('yt-dlp.exe', b'new test executable')
            bundle.writestr('dependency.dll', b'required test dependency')

    def install_fixture(self):
        return installer.install_portable('yt-dlp', self.package, self.archive,
                                          self.package['sha256'], self.root)

    def test_interrupted_extraction_keeps_previous_directory_and_is_not_reused(self):
        previous = self.root / 'yt-dlp'
        previous.mkdir()
        (previous / 'yt-dlp.exe').write_bytes(b'previous incomplete executable')
        def fail_extract(archive, destination):
            (destination / 'yt-dlp.exe').write_bytes(b'partial new executable')
            raise RuntimeError('simulated interruption before DLL extraction')
        with patch.object(installer, 'extract', side_effect=fail_extract):
            with self.assertRaises(RuntimeError):
                self.install_fixture()
        self.assertEqual((previous / 'yt-dlp.exe').read_bytes(), b'previous incomplete executable')
        with patch.object(installer.shutil, 'which', return_value=str(previous / 'yt-dlp.exe')):
            self.assertIsNone(installer.existing('yt-dlp', self.package, self.root, {'tools': {}}))
        self.assertEqual(len(list((self.root / '.staging').iterdir())), 1)

    def test_complete_package_replaces_partial_directory_and_keeps_recovery_copy(self):
        previous = self.root / 'yt-dlp'
        previous.mkdir()
        (previous / 'yt-dlp.exe').write_bytes(b'old incomplete')
        executable = self.install_fixture()
        self.assertEqual(executable.read_bytes(), b'new test executable')
        self.assertEqual(installer.managed_existing('yt-dlp', self.package, self.root, {'tools': {}}), executable)
        backups = list((self.root / 'backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'yt-dlp.exe').read_bytes(), b'old incomplete')
        (executable.parent / 'dependency.dll').unlink()
        self.assertIsNone(installer.managed_existing('yt-dlp', self.package, self.root, {'tools': {}}))

    def test_failed_promotion_restores_previous_directory(self):
        previous = self.root / 'yt-dlp'
        previous.mkdir()
        (previous / 'yt-dlp.exe').write_bytes(b'old preserved')
        original_replace = Path.replace
        def fail_promotion(path, target):
            if path.parent.name == '.staging':
                raise OSError('simulated promotion failure')
            return original_replace(path, target)
        with patch.object(Path, 'replace', fail_promotion):
            with self.assertRaises(OSError):
                self.install_fixture()
        self.assertEqual((previous / 'yt-dlp.exe').read_bytes(), b'old preserved')

    def test_existing_success_record_from_older_installer_is_accepted(self):
        folder = self.root / 'yt-dlp'
        folder.mkdir()
        executable = folder / 'yt-dlp.exe'
        executable.write_bytes(b'legacy successful install')
        manifest = {'tools': {'yt-dlp': dict(executable=str(executable),
                    version=self.package['version'], archive_sha256=self.package['sha256'])}}
        self.assertEqual(installer.managed_existing('yt-dlp', self.package, self.root, manifest), executable)

    @unittest.skipUnless(os.name == 'nt', 'Windows tool path discovery')
    def test_corrupt_manifest_does_not_prevent_path_discovery_and_is_preserved(self):
        manifest = self.root / 'installed.json'
        broken = b'{"tools": {"ffmpeg": '
        manifest.write_bytes(broken)
        binary = self.root / 'ffmpeg/bin'
        binary.mkdir(parents=True)
        with patch.dict(os.environ, {'WORKBENCH_TOOLS_DIR': str(self.root)}), redirect_stderr(io.StringIO()) as warnings:
            self.assertEqual(configure_tools(), self.root)
            self.assertIn(str(binary), os.environ['PATH'].split(os.pathsep))
        self.assertIn('preserved', warnings.getvalue())
        self.assertEqual(manifest.read_bytes(), broken)
        write_installed_manifest(manifest, {'tools': {}})
        self.assertEqual(read_installed_manifest(manifest), {'tools': {}})
        backups = list(self.root.glob('installed.json.damaged-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), broken)

    def test_failed_manifest_publication_keeps_previous_complete_json(self):
        path = self.root / 'installed.json'
        previous = {'tools': {'external': {'executable': 'C:/existing/tool.exe', 'reused': True}}}
        write_installed_manifest(path, previous)
        with patch.object(Path, 'replace', side_effect=OSError('simulated interrupted publication')):
            with self.assertRaises(OSError):
                write_installed_manifest(path, {'tools': {}})
        self.assertEqual(read_installed_manifest(path), previous)
        self.assertEqual(len(list(self.root.glob('.installed.json.*.tmp'))), 1)


if __name__ == '__main__':
    unittest.main()
