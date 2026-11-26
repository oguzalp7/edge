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

from tools.common import env as env_mod
from tools.common import paths as paths_mod
from tools.common.paths import normalize_target_path, to_wsl_path, is_wsl_path, WSL_DISTRO
from tools.common.console import setup_utf8_console
from tools.common import runner
from tools.common.runner import run_command


class TestCommonPaths(unittest.TestCase):
    def test_to_wsl_path(self):
        # UNC path translation (Ubuntu-24.04 and arbitrary distros)
        unc_path = r"\\wsl.localhost\Ubuntu-24.04\home\oguz\MS-Randevu-monolith"
        self.assertEqual(to_wsl_path(unc_path), "/home/oguz/MS-Randevu-monolith")
        self.assertEqual(
            to_wsl_path(r"\\wsl.localhost\Debian\home\alice\repo"),
            "/home/alice/repo",
        )
        self.assertEqual(
            to_wsl_path(r"\\wsl$\Arch\home\alice\repo"),
            "/home/alice/repo",
        )

        # Windows drive path translation (multi-drive)
        win_path = r"C:\Users\oguz_\project"
        self.assertEqual(to_wsl_path(win_path), "/mnt/c/Users/oguz_/project")
        self.assertEqual(to_wsl_path(r"D:\Work\repo"), "/mnt/d/Work/repo")

        # Linux path remains unchanged
        self.assertEqual(to_wsl_path("/home/oguz/repo"), "/home/oguz/repo")

    def test_is_wsl_path(self):
        self.assertTrue(is_wsl_path(r"\\wsl.localhost\Ubuntu-24.04\home\oguz"))
        self.assertTrue(is_wsl_path(r"\\wsl.localhost\Debian\home\alice\repo"))
        self.assertTrue(is_wsl_path(r"\\wsl$\Ubuntu-22.04\home\alice\repo"))
        self.assertFalse(is_wsl_path(r"C:\Windows\System32"))

        # /home/<user>/... is WSL only when running on Windows or inside WSL, NEVER on native Linux
        with patch.object(paths_mod.os, "name", "nt"):
            self.assertTrue(is_wsl_path("/home/alice/repo"))

        with patch.object(paths_mod.os, "name", "posix"), \
             patch.object(env_mod, "is_wsl", return_value=True), \
             patch.object(paths_mod, "is_wsl", return_value=True, create=True):
            self.assertTrue(is_wsl_path("/home/alice/repo"))

        with patch.object(paths_mod.os, "name", "posix"), \
             patch.object(env_mod, "is_wsl", return_value=False), \
             patch.object(paths_mod, "is_wsl", return_value=False, create=True):
            self.assertFalse(is_wsl_path("/home/alice/repo"))

    def test_normalize_target_path_local(self):
        cur = Path.cwd()
        norm = normalize_target_path(cur)
        self.assertTrue(norm.exists())

        # Multi-drive /mnt/<letter>/... normalization under Windows
        with patch.object(paths_mod.os, "name", "nt"), \
             patch.object(paths_mod, "Path", PosixPath):
            norm_d = normalize_target_path("/mnt/d/nonexistent_work_dir/project")
            self.assertEqual(str(norm_d).replace("\\", "/").lower(), "d:/nonexistent_work_dir/project")


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
        spaced_wsl_cwd = "/home/alice/repo with spaces"

        mock_proc = MagicMock(returncode=0, stdout="OK", stderr="")

        # 1. Empty distro omits -d flag
        with patch.dict(os.environ, {"EDGE_WSL_DISTRO": ""}, clear=False), \
             patch.object(runner.os, "name", "nt"), \
             patch.object(runner, "Path", PosixPath), \
             patch.object(runner, "WSL_DISTRO", "", create=True), \
             patch.object(paths_mod, "WSL_DISTRO", "", create=True), \
             patch.object(env_mod, "get_wsl_distro", return_value=""), \
             patch.object(runner, "get_wsl_distro", return_value="", create=True), \
             patch("tools.common.runner.subprocess.run", return_value=mock_proc) as mock_sub_empty:
            code, out, err = run_command(cmd, cwd=spaced_wsl_cwd, timeout=30)

        self.assertEqual((code, out, err), (0, "OK", ""))
        exec_empty = mock_sub_empty.call_args[0][0]
        self.assertEqual(exec_empty[:3], ["wsl", "bash", "-c"])
        self.assertEqual(exec_empty[3], runner._build_wsl_bash_command(cmd, spaced_wsl_cwd))

        # 2. Explicit distro includes -d <distro>
        with patch.dict(os.environ, {"EDGE_WSL_DISTRO": "Debian"}, clear=False), \
             patch.object(runner.os, "name", "nt"), \
             patch.object(runner, "Path", PosixPath), \
             patch.object(runner, "WSL_DISTRO", "Debian", create=True), \
             patch.object(paths_mod, "WSL_DISTRO", "Debian", create=True), \
             patch.object(env_mod, "get_wsl_distro", return_value="Debian"), \
             patch.object(runner, "get_wsl_distro", return_value="Debian", create=True), \
             patch("tools.common.runner.subprocess.run", return_value=mock_proc) as mock_sub_distro:
            code, out, err = run_command(cmd, cwd=spaced_wsl_cwd, timeout=30)

        self.assertEqual((code, out, err), (0, "OK", ""))
        exec_distro = mock_sub_distro.call_args[0][0]
        self.assertEqual(exec_distro[:5], ["wsl", "-d", "Debian", "bash", "-c"])
        self.assertEqual(exec_distro[5], runner._build_wsl_bash_command(cmd, spaced_wsl_cwd))


if __name__ == "__main__":
    unittest.main()
