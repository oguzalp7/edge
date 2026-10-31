#!/usr/bin/env python3
"""
Hermetic Unit and Contract Tests for Edge-GNHF Subsystems (SPEC-EDGE-GNHF-001).

Tests coverage:
1. tools.gnhf.shim: Ephemeral agy wrapper, model injection, PATH management, guaranteed cleanup.
2. tools.gnhf.prompt: Deterministic AFK prompt builder, [EDGE_AFK:<mode>] headers, absolute gate.py paths.
3. tools.gnhf.runner: WSLENV injection, subprocess flag composition, dry-run safety.
4. tools.gnhf.harvest: Porcelain worktree parsing, blocker triage extraction, gate-verified merge and teardown.
5. tools.gnhf.cli: CLI argument parsing for run, status, and harvest.
"""

import os
import sys
import json
import shutil
import tempfile
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))


class TestGnhfShim(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.orig_env = os.environ.copy()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        self.temp_dir.cleanup()

    def test_create_agy_shim_lifecycle_and_path_injection(self):
        from tools.gnhf.shim import create_agy_shim

        orig_path = os.environ.get("PATH", "")
        with create_agy_shim("gemini-3.8-flash-medium") as shim_dir:
            shim_path = Path(shim_dir)
            self.assertTrue(shim_path.is_dir(), "Shim directory must exist during context")
            agy_script = shim_path / "agy"
            self.assertTrue(agy_script.is_file(), "Executable agy wrapper must exist in shim dir")
            self.assertTrue(os.access(str(agy_script), os.X_OK), "agy wrapper must be executable (0755 or 0700)")

            # PATH must have shim_dir as the very first entry
            current_path_entries = os.environ.get("PATH", "").split(os.pathsep)
            self.assertEqual(current_path_entries[0], str(shim_path), "Shim directory must be prepended to PATH")

        # After context exit, shim dir must be deleted and PATH restored
        self.assertFalse(shim_path.exists(), "Shim directory must be deleted after context exit")
        self.assertEqual(os.environ.get("PATH"), orig_path, "PATH must be restored after context exit")

    def test_create_agy_shim_cleanup_on_exception(self):
        from tools.gnhf.shim import create_agy_shim

        shim_captured_path = None
        try:
            with create_agy_shim("gemini-3.8-flash-medium") as shim_dir:
                shim_captured_path = Path(shim_dir)
                self.assertTrue(shim_captured_path.exists())
                raise RuntimeError("Simulated failure inside runner")
        except RuntimeError:
            pass

        self.assertIsNotNone(shim_captured_path)
        self.assertFalse(shim_captured_path.exists(), "Shim directory must be deleted even if exception occurs")

    def test_shim_execution_injects_default_model(self):
        from tools.gnhf.shim import create_agy_shim

        # Create a mock real_agy executable that records received arguments
        log_file = self.temp_path / "real_agy_calls.log"
        mock_real_agy = self.temp_path / "real_agy_bin"
        with open(mock_real_agy, "w", encoding="utf-8") as f:
            f.write(f"#!/usr/bin/env bash\necho \"$@\" >> '{log_file}'\n")
        mock_real_agy.chmod(0o755)

        with patch("shutil.which", return_value=str(mock_real_agy)):
            with create_agy_shim("gemini-3.8-flash-medium") as shim_dir:
                agy_script = Path(shim_dir) / "agy"
                # Call shim without --model
                res = subprocess.run([str(agy_script), "run", "--prompt", "test prompt"], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0)

        with open(log_file, "r", encoding="utf-8") as f:
            calls = f.read()
        self.assertIn("--model gemini-3.8-flash-medium", calls)
        self.assertIn("run --prompt test prompt", calls)

    def test_shim_execution_preserves_explicit_custom_model(self):
        from tools.gnhf.shim import create_agy_shim

        log_file = self.temp_path / "real_agy_calls.log"
        mock_real_agy = self.temp_path / "real_agy_bin"
        with open(mock_real_agy, "w", encoding="utf-8") as f:
            f.write(f"#!/usr/bin/env bash\necho \"$@\" >> '{log_file}'\n")
        mock_real_agy.chmod(0o755)

        with patch("shutil.which", return_value=str(mock_real_agy)):
            with create_agy_shim("gemini-3.8-flash-medium") as shim_dir:
                agy_script = Path(shim_dir) / "agy"
                # Call shim with explicit --model custom-model
                res = subprocess.run([str(agy_script), "--model", "custom-model", "run"], capture_output=True, text=True)
                self.assertEqual(res.returncode, 0)

        with open(log_file, "r", encoding="utf-8") as f:
            calls = f.read()
        self.assertIn("--model custom-model", calls)
        self.assertNotIn("gemini-3.8-flash-medium", calls)


class TestGnhfPrompt(unittest.TestCase):
    def test_build_gnhf_prompt_strict_mode(self):
        from tools.gnhf.prompt import build_gnhf_prompt

        objective = "Decouple legacy Stripe webhook handlers into repository pattern"
        prompt = build_gnhf_prompt(objective=objective, mode="strict", track="core")

        # 1. Deterministic Signal B Header
        self.assertTrue(prompt.startswith("[EDGE_AFK:strict]"), "Prompt must start with [EDGE_AFK:strict]")

        # 2. Objective presence
        self.assertIn("OBJECTIVE:", prompt)
        self.assertIn(objective, prompt)

        # 3. Single Atomic Step Mandate
        self.assertIn("ATOMIC", prompt)

        # 4. Blocker Triage format
        self.assertIn("[SKIPPED-NEEDS-HITL]", prompt)
        self.assertIn(".gnhf/notes.md", prompt)

        # 5. Physical Strict Boundaries
        self.assertIn("STRICT MODE", prompt)
        self.assertIn("invoke_subagent", prompt)

        # 6. Embedded Quality Gate WSL Absolute Path
        # Target project won't have tools/gate.py, so prompt must refer to Edge's absolute gate.py path
        self.assertIn("/tools/gate.py", prompt)
        self.assertIn("--track core", prompt)
        self.assertIn("--skip-verify", prompt)

        # Must NOT use relative 'python3 tools/gate.py'
        self.assertNotIn("python3 tools/gate.py .", prompt)
        self.assertNotIn("python tools/gate.py .", prompt)

    def test_build_gnhf_prompt_yolo_mode(self):
        from tools.gnhf.prompt import build_gnhf_prompt

        objective = "Refactor schema and add integration tests"
        prompt = build_gnhf_prompt(objective=objective, mode="yolo", track="ui")

        self.assertTrue(prompt.startswith("[EDGE_AFK:yolo]"), "Prompt must start with [EDGE_AFK:yolo]")
        self.assertIn("YOLO MODE", prompt)
        self.assertIn("/tools/gate.py", prompt)
        self.assertIn("--track ui", prompt)

    def test_build_gnhf_prompt_with_custom_test_cmd(self):
        from tools.gnhf.prompt import build_gnhf_prompt

        test_cmd = "npx vitest run src/billing.test.ts"
        prompt = build_gnhf_prompt(objective="Fix billing", test_cmd=test_cmd)
        self.assertIn(test_cmd, prompt)


class TestGnhfRunner(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create a mock git repository
        self.mock_repo = self.temp_path / "test_repo"
        self.mock_repo.mkdir()
        subprocess.run(["git", "init"], cwd=self.mock_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=self.mock_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.mock_repo, check=True, capture_output=True)
        (self.mock_repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.mock_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.mock_repo, check=True, capture_output=True)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        self.temp_dir.cleanup()

    def test_execute_gnhf_run_dry_run(self):
        from tools.gnhf.runner import execute_gnhf_run, GnhfRunOptions, AfkMode

        options = GnhfRunOptions(
            repo_path=self.mock_repo,
            objective="Refactor auth",
            mode=AfkMode.STRICT,
            dry_run=True,
        )
        exit_code = execute_gnhf_run(options)
        self.assertEqual(exit_code, 0, "dry-run must return 0 without spawning subprocesses")

    def test_execute_gnhf_run_env_and_flags_injection(self):
        from tools.gnhf.runner import execute_gnhf_run, GnhfRunOptions, AfkMode

        options = GnhfRunOptions(
            repo_path=self.mock_repo,
            objective="Refactor billing",
            mode=AfkMode.YOLO,
            agent="agy",
            model="gemini-3.8-flash-medium",
            track="core",
            max_iterations=10,
            max_tokens=250000,
            stop_when="all tests pass",
        )

        with patch("subprocess.run") as mock_subproc, \
             patch("tools.gnhf.shim.create_agy_shim") as mock_shim:

            mock_subproc.return_value.returncode = 0
            exit_code = execute_gnhf_run(options)
            self.assertEqual(exit_code, 0)

            # 1. Verify create_agy_shim was invoked with the target model
            mock_shim.assert_called_once_with(model="gemini-3.8-flash-medium")

            # 2. Verify subprocess.run arguments
            mock_subproc.assert_called_once()
            called_args, called_kwargs = mock_subproc.call_args
            cmd = called_args[0]

            self.assertIn("gnhf", cmd[0])
            self.assertIn("--worktree", cmd)
            self.assertIn("--agent", cmd)
            self.assertIn("agy", cmd)

            # 3. Verify environment variables injected to subprocess
            env = called_kwargs.get("env", {})
            self.assertEqual(env.get("EDGE_AFK"), "1")
            self.assertEqual(env.get("EDGE_AFK_MODE"), "yolo")

            wslenv = env.get("WSLENV", "")
            self.assertIn("EDGE_AFK", wslenv)
            self.assertIn("EDGE_AFK_MODE", wslenv)

    def test_execute_gnhf_run_rejects_dirty_or_non_git_repo(self):
        from tools.gnhf.runner import execute_gnhf_run, GnhfRunOptions

        non_git = self.temp_path / "not_git"
        non_git.mkdir()
        options = GnhfRunOptions(repo_path=non_git, objective="test")
        exit_code = execute_gnhf_run(options)
        self.assertNotEqual(exit_code, 0, "Non-git directory must return non-zero exit code")


class TestGnhfHarvest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Create base git repo
        self.mock_repo = self.temp_path / "primary_repo"
        self.mock_repo.mkdir()
        subprocess.run(["git", "init", "-b", "development"], cwd=self.mock_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=self.mock_repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=self.mock_repo, check=True, capture_output=True)
        (self.mock_repo / "main.ts").write_text("console.log('init');\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.mock_repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=self.mock_repo, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_gnhf_status_discovers_worktrees_and_blockers(self):
        from tools.gnhf.harvest import get_gnhf_status

        # Create a worktree for gnhf/refactor-1
        wt_path = self.temp_path / "worktree_1"
        subprocess.run(
            ["git", "worktree", "add", "-b", "gnhf/refactor-1", str(wt_path), "development"],
            cwd=self.mock_repo,
            check=True,
            capture_output=True
        )

        # Make 2 commits in the worktree
        (wt_path / "main.ts").write_text("console.log('step 1');\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "Step 1 in worktree"], cwd=wt_path, check=True, capture_output=True)
        (wt_path / "main.ts").write_text("console.log('step 2');\n", encoding="utf-8")
        subprocess.run(["git", "commit", "-am", "Step 2 in worktree"], cwd=wt_path, check=True, capture_output=True)

        # Add blockers to .gnhf/notes.md
        gnhf_dir = wt_path / ".gnhf"
        gnhf_dir.mkdir(parents=True, exist_ok=True)
        (gnhf_dir / "notes.md").write_text(
            "# Overnight progress\n"
            "- Step 1 done\n"
            "[SKIPPED-NEEDS-HITL] src/server/auth.ts: Circular dependency with user-session repository.\n"
            "[SKIPPED-NEEDS-HITL] src/db/schema/org.ts: Schema locked in strict mode; requires migration.\n",
            encoding="utf-8"
        )

        statuses = get_gnhf_status(self.mock_repo)
        self.assertEqual(len(statuses), 1)
        st = statuses[0]
        self.assertEqual(st.branch_name, "gnhf/refactor-1")
        self.assertEqual(st.base_branch, "development")
        self.assertEqual(st.commits_ahead, 2)
        self.assertIn("Step 2", st.last_commit_subject)

        # Verify triaged blockers
        self.assertEqual(len(st.blockers), 2)
        self.assertEqual(st.blockers[0].file_path, "src/server/auth.ts")
        self.assertIn("Circular dependency", st.blockers[0].reason)
        self.assertEqual(st.blockers[1].file_path, "src/db/schema/org.ts")
        self.assertIn("Schema locked", st.blockers[1].reason)

    def test_harvest_aborts_when_gate_fails(self):
        from tools.gnhf.harvest import harvest_worktree

        wt_path = self.temp_path / "worktree_failing"
        subprocess.run(
            ["git", "worktree", "add", "-b", "gnhf/failing-branch", str(wt_path), "development"],
            cwd=self.mock_repo,
            check=True,
            capture_output=True
        )

        # Mock gate.py returning exit code 1 (failure)
        orig_run = subprocess.run

        def subproc_side_effect(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "gate.py" in cmd_str:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="GATE VIOLATIONS FOUND")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=subproc_side_effect):
            result = harvest_worktree(
                repo_path=self.mock_repo,
                branch_name="gnhf/failing-branch",
                base_branch="development",
                merge=True,
                cleanup=True
            )

            self.assertFalse(result.gate_passed)
            self.assertEqual(result.gate_exit_code, 1)
            self.assertFalse(result.merged, "Must NOT merge when gate fails")
            self.assertFalse(result.cleaned_up, "Must NOT delete worktree when gate fails")
            self.assertTrue(wt_path.exists(), "Worktree must remain intact for inspection")

    def test_harvest_clean_fast_forward_merge_and_cleanup(self):
        from tools.gnhf.harvest import harvest_worktree

        wt_path = self.temp_path / "worktree_passing"
        subprocess.run(
            ["git", "worktree", "add", "-b", "gnhf/passing-branch", str(wt_path), "development"],
            cwd=self.mock_repo,
            check=True,
            capture_output=True
        )
        (wt_path / "feature.ts").write_text("export const feat = true;\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=wt_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Verified feature implementation"], cwd=wt_path, check=True, capture_output=True)

        orig_run = subprocess.run

        def subproc_side_effect(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "gate.py" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="All Quality Gates Passed", stderr="")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=subproc_side_effect):
            result = harvest_worktree(
                repo_path=self.mock_repo,
                branch_name="gnhf/passing-branch",
                base_branch="development",
                merge=True,
                cleanup=True
            )

            self.assertTrue(result.gate_passed)
            self.assertEqual(result.gate_exit_code, 0)
            self.assertTrue(result.merged)
            self.assertTrue(result.cleaned_up)

            # Development branch in main repo must now have feature.ts
            feature_file = self.mock_repo / "feature.ts"
            self.assertTrue(feature_file.exists(), "Development branch must contain fast-forward merged changes")

            # Worktree directory must be removed
            self.assertFalse(wt_path.exists(), "Worktree directory must be removed after cleanup")

    def test_harvest_dry_run_does_not_mutate(self):
        from tools.gnhf.harvest import harvest_worktree

        wt_path = self.temp_path / "worktree_dry"
        subprocess.run(
            ["git", "worktree", "add", "-b", "gnhf/dry-branch", str(wt_path), "development"],
            cwd=self.mock_repo,
            check=True,
            capture_output=True
        )

        orig_run = subprocess.run

        def subproc_side_effect(cmd, *args, **kwargs):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "gate.py" in cmd_str:
                return subprocess.CompletedProcess(cmd, 0, stdout="Gate OK", stderr="")
            return orig_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=subproc_side_effect):
            result = harvest_worktree(
                repo_path=self.mock_repo,
                branch_name="gnhf/dry-branch",
                merge=True,
                cleanup=True,
                dry_run=True
            )

            self.assertTrue(result.gate_passed)
            self.assertFalse(result.merged)
            self.assertFalse(result.cleaned_up)
            self.assertTrue(wt_path.exists(), "Worktree must not be removed in dry-run mode")


class TestGnhfCLI(unittest.TestCase):
    def test_cli_run_argument_parsing(self):
        from tools.gnhf.cli import parse_args

        args = parse_args([
            "run", "/home/oguz/my_project", "Refactor user authentication service",
            "--mode", "yolo",
            "--agent", "custom-agent",
            "--model", "gemini-2.5-pro",
            "--track", "core",
            "--max-iterations", "25",
            "--max-tokens", "500000",
            "--stop-when", "all unit tests pass",
            "--test-cmd", "npx vitest run",
            "--dry-run"
        ])

        self.assertEqual(args.command, "run")
        self.assertEqual(args.repo, "/home/oguz/my_project")
        self.assertEqual(args.objective, "Refactor user authentication service")
        self.assertEqual(args.mode, "yolo")
        self.assertEqual(args.agent, "custom-agent")
        self.assertEqual(args.model, "gemini-2.5-pro")
        self.assertEqual(args.track, "core")
        self.assertEqual(args.max_iterations, 25)
        self.assertEqual(args.max_tokens, 500000)
        self.assertEqual(args.stop_when, "all unit tests pass")
        self.assertEqual(args.test_cmd, "npx vitest run")
        self.assertTrue(args.dry_run)

    def test_cli_run_yolo_alias(self):
        from tools.gnhf.cli import parse_args

        args = parse_args(["run", "/home/oguz/project", "Do work", "--yolo"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.mode, "yolo")

    def test_cli_status_argument_parsing(self):
        from tools.gnhf.cli import parse_args

        args = parse_args(["status", "/home/oguz/my_project"])
        self.assertEqual(args.command, "status")
        self.assertEqual(args.repo, "/home/oguz/my_project")

    def test_cli_harvest_argument_parsing(self):
        from tools.gnhf.cli import parse_args

        args = parse_args([
            "harvest", "/home/oguz/my_project", "gnhf/user-refactor",
            "--base", "main",
            "--track", "ui",
            "--merge",
            "--cleanup",
            "--dry-run"
        ])

        self.assertEqual(args.command, "harvest")
        self.assertEqual(args.repo, "/home/oguz/my_project")
        self.assertEqual(args.branch, "gnhf/user-refactor")
        self.assertEqual(args.base, "main")
        self.assertEqual(args.track, "ui")
        self.assertTrue(args.merge)
        self.assertTrue(args.cleanup)
        self.assertTrue(args.dry_run)


if __name__ == "__main__":
    unittest.main()
