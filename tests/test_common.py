"""
Unit tests for Edge Common utilities (paths, console, runner).
"""

import unittest
from pathlib import Path
import os
import sys

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common.paths import normalize_target_path, to_wsl_path, is_wsl_path
from tools.common.console import setup_utf8_console
from tools.common.runner import run_command


class TestCommonPaths(unittest.TestCase):
    def test_to_wsl_path(self):
        # UNC path translation
        unc_path = r"\\wsl.localhost\Ubuntu-24.04\home\oguz\MS-Randevu-monolith"
        self.assertEqual(to_wsl_path(unc_path), "/home/oguz/MS-Randevu-monolith")

        # Windows drive path translation
        win_path = r"C:\Users\oguz_\project"
        self.assertEqual(to_wsl_path(win_path), "/mnt/c/Users/oguz_/project")

        # Linux path remains unchanged
        self.assertEqual(to_wsl_path("/home/oguz/repo"), "/home/oguz/repo")

    def test_is_wsl_path(self):
        self.assertTrue(is_wsl_path(r"\\wsl.localhost\Ubuntu-24.04\home\oguz"))
        self.assertTrue(is_wsl_path("/home/oguz/repo"))
        self.assertFalse(is_wsl_path(r"C:\Windows\System32"))

    def test_normalize_target_path_local(self):
        cur = Path.cwd()
        norm = normalize_target_path(cur)
        self.assertTrue(norm.exists())


class TestCommonConsole(unittest.TestCase):
    def test_setup_utf8_console_does_not_throw(self):
        try:
            setup_utf8_console()
        except Exception as e:
            self.fail(f"setup_utf8_console raised an exception: {e}")


if __name__ == "__main__":
    unittest.main()
