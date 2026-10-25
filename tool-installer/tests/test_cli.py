import os
import tempfile
import unittest
from pathlib import Path

from tool_installer.cli import locate_tools_config
from tool_installer.errors import ConfigError


class LocateToolsConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name).resolve()
        self.orig_cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self.orig_cwd)
        self.tmp.cleanup()

    def test_explicit_path_found(self):
        target = self.tmp_path / "tools.toml"
        target.write_text("[tool-installer]\nmanifest='./manifest.toml'\n")
        located = locate_tools_config(str(target))
        self.assertEqual(located, target)

    def test_explicit_path_missing(self):
        with self.assertRaises(ConfigError):
            locate_tools_config(str(self.tmp_path / "nonexistent.toml"))

    def test_env_var_override(self):
        target = self.tmp_path / "tools.toml"
        target.write_text("[tool-installer]\nmanifest='./manifest.toml'\n")
        os.environ["TOOL_INSTALLER_ROOT"] = str(self.tmp_path)
        try:
            located = locate_tools_config()
            self.assertEqual(located, target)
        finally:
            del os.environ["TOOL_INSTALLER_ROOT"]

    def test_upward_traversal(self):
        target = self.tmp_path / "tools.toml"
        target.write_text("[tool-installer]\nmanifest='./manifest.toml'\n")
        subdir = self.tmp_path / "a" / "b" / "c"
        subdir.mkdir(parents=True)
        os.chdir(subdir)

        located = locate_tools_config()
        self.assertEqual(located, target)


if __name__ == "__main__":
    unittest.main()
