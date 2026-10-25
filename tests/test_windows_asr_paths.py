"""ASR path precedence; no downloads, installation, or model execution."""
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from windows_environment import asr_directory, configure_tools


@unittest.skipUnless(os.name == 'nt', 'Windows ASR installation paths')
class WindowsAsrPathTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.runtime'
        scratch.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='asr-path-', dir=scratch)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def resolved_installer_path(self):
        return runpy.run_path(str(ROOT / 'scripts/setup_asr.py'), run_name='asr_configuration_test')['BASE']

    def assert_consistent(self, expected):
        self.assertEqual(asr_directory(), expected)
        # Importing the standalone installer must use the same location before
        # the Windows entry point has populated any inferred environment value.
        self.assertEqual(self.resolved_installer_path(), expected)
        configure_tools()
        self.assertEqual(Path(os.environ['SUBTITLE_ASR_DIR']), expected)
        self.assertEqual(self.resolved_installer_path(), expected)
        self.assertFalse(expected.exists(), 'Path discovery must not install or create directories')

    def test_new_custom_tools_directory_applies_before_asr_exists(self):
        root = self.root / '新工具 ไทย'
        with patch.dict(os.environ, {'WORKBENCH_TOOLS_DIR': str(root)}, clear=True):
            self.assert_consistent(root / 'asr')

    def test_explicit_asr_directory_takes_precedence_over_tools_directory(self):
        explicit = self.root / '独立 models'
        with patch.dict(os.environ, {'WORKBENCH_TOOLS_DIR': str(self.root / 'tools'),
                                    'SUBTITLE_ASR_DIR': str(explicit)}, clear=True):
            self.assert_consistent(explicit)

    def test_default_uses_user_local_appdata(self):
        local_appdata = self.root / 'Local'
        with patch.dict(os.environ, {'LOCALAPPDATA': str(local_appdata),
                                    'USERPROFILE': str(self.root)}, clear=True):
            self.assert_consistent(local_appdata / 'Programs/SubtitleWorkbench/asr')


if __name__ == '__main__':
    unittest.main()
