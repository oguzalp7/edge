"""
Unit tests for Edge Common utilities (paths, console, runner).
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path, PosixPath
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common.paths import normalize_target_path, to_wsl_path, is_wsl_path, WSL_DISTRO
from tools.common.console import setup_utf8_console
from tools.common import runner
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


class TestCommonRunner(unittest.TestCase):
    def test_build_wsl_bash_command_quotes_multiline_prompts_and_spaced_paths(self):
        self.assertTrue(
            hasattr(runner, "_build_wsl_bash_command"),
            "tools.common.runner must define _build_wsl_bash_command",
        )

        multiline_prompt = (
            "Line 1: review 'single' and \"double\" quotes\n"
            "Line 2: keep $HOME, (parens), & | ; intact"
        )
        cmd = ["agy", "--mode", "plan", "--model", "claude-opus-5-5-high", "-p", multiline_prompt]
        wsl_cwd = "/home/oguz/my spaced project"

        bash_cmd = runner._build_wsl_bash_command(cmd, wsl_cwd)
        expected_cd = f"cd {shlex.quote(wsl_cwd)} && "
        self.assertTrue(bash_cmd.startswith(expected_cd), f"Unexpected prefix: {bash_cmd}")

        inner_cmd = bash_cmd[len(expected_cd):]
        self.assertEqual(shlex.split(inner_cmd), cmd)

        # String commands preserve raw command body while quoting spaced wsl_cwd
        str_bash_cmd = runner._build_wsl_bash_command("echo 'ok'", wsl_cwd)
        self.assertEqual(str_bash_cmd, f"cd {shlex.quote(wsl_cwd)} && echo 'ok'")

        if os.name != "nt" and shutil.which("bash"):
            with tempfile.TemporaryDirectory(prefix="edge spaced ") as spaced_dir:
                probe = [
                    sys.executable,
                    "-c",
                    "import os, sys, json; print(json.dumps([os.getcwd()] + sys.argv[1:]))",
                    multiline_prompt,
                ]
                shell_str = runner._build_wsl_bash_command(probe, spaced_dir)
                proc = subprocess.run(["bash", "-c", shell_str], capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                import json
                parsed = json.loads(proc.stdout)
                self.assertEqual(os.path.realpath(parsed[0]), os.path.realpath(spaced_dir))
                self.assertEqual(parsed[1], multiline_prompt)

    def test_run_command_wsl_dispatch_uses_shlex_quoted_bash_command(self):
        self.assertTrue(
            hasattr(runner, "_build_wsl_bash_command"),
            "tools.common.runner must define _build_wsl_bash_command",
        )
        multiline_prompt = "Line 1 'quoted'\nLine 2 \"double\" & (parens)"
        cmd = ["agy", "--mode", "plan", "--model", "gemini-3.8-flash-high", "-p", multiline_prompt]
        spaced_wsl_cwd = "/home/oguz/repo with spaces"

        mock_proc = MagicMock(returncode=0, stdout="OK", stderr="")
        with patch.object(runner.os, "name", "nt"), \
             patch.object(runner, "Path", PosixPath), \
             patch("tools.common.runner.subprocess.run", return_value=mock_proc) as mock_sub:
            code, out, err = run_command(cmd, cwd=spaced_wsl_cwd, timeout=30)

        self.assertEqual((code, out, err), (0, "OK", ""))
        exec_cmd = mock_sub.call_args[0][0]
        self.assertEqual(exec_cmd[:4], ["wsl", "-d", WSL_DISTRO, "bash"])
        self.assertEqual(exec_cmd[4], "-c")
        self.assertEqual(exec_cmd[5], runner._build_wsl_bash_command(cmd, spaced_wsl_cwd))


if __name__ == "__main__":
    unittest.main()
