"""
Subprocess execution engine for autonomous GNHF worktree runs.
"""

import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

import tools.gnhf.shim as shim
from tools.gnhf.prompt import build_gnhf_prompt
from tools.gnhf import GnhfRunOptions, AfkMode


def _validate_repo(repo_path: Path) -> bool:
    """Verifies that repo_path is a git repository."""
    if not repo_path.exists():
        return False
    git_dir = repo_path / ".git"
    return git_dir.exists()


def _build_command(options: GnhfRunOptions, prompt: str) -> List[str]:
    """Assembles the CLI argument list for the gnhf executable."""
    cmd: List[str] = ["gnhf", "--worktree", "--agent", options.agent]
    if options.max_iterations is not None:
        cmd.extend(["--max-iterations", str(options.max_iterations)])
    if options.max_tokens is not None:
        cmd.extend(["--max-tokens", str(options.max_tokens)])
    if options.stop_when:
        cmd.extend(["--stop-when", options.stop_when])
    cmd.append(prompt)
    return cmd


def _build_env(options: GnhfRunOptions) -> Dict[str, str]:
    """Configures process environment with EDGE_AFK signals and WSLENV."""
    env = os.environ.copy()
    env["EDGE_AFK"] = "1"
    mode_str = options.mode.value if isinstance(options.mode, AfkMode) else str(options.mode)
    env["EDGE_AFK_MODE"] = mode_str

    wslenv = env.get("WSLENV", "")
    for flag in ["EDGE_AFK/w", "EDGE_AFK_MODE/w"]:
        if flag not in wslenv:
            wslenv = f"{wslenv}:{flag}".lstrip(":")
    env["WSLENV"] = wslenv
    return env


def _print_dry_run_preview(options: GnhfRunOptions, cmd: List[str], prompt: str) -> None:
    """Outputs resolved configuration and synthesized prompt for dry-run inspection."""
    mode_str = options.mode.value if isinstance(options.mode, AfkMode) else str(options.mode)
    cmd_str = " ".join(cmd[:-1])
    print("🌙 [DRY-RUN] Edge-GNHF Autonomous Run Preview")
    print("━" * 60)
    print(f"Repository: {options.repo_path}")
    print(f"Agent:      {options.agent}")
    print(f"Model:      {options.model}")
    print(f"Mode:       {mode_str}")
    print(f"Track:      {options.track}")
    print(f"Command:    {cmd_str}")
    print("━" * 60)
    print(f"Synthesized Prompt:\n{prompt}")
    print("━" * 60)


def execute_gnhf_run(options: GnhfRunOptions) -> int:
    """
    Validates git repository, builds prompt, sets up ephemeral shim,
    injects EDGE_AFK / WSLENV variables, and runs 'gnhf --worktree'.
    Returns process exit code.
    """
    if not _validate_repo(options.repo_path):
        return 1

    mode_str = options.mode.value if isinstance(options.mode, AfkMode) else str(options.mode)
    prompt = build_gnhf_prompt(
        objective=options.objective,
        mode=mode_str,
        track=options.track,
        test_cmd=options.test_cmd,
    )

    cmd = _build_command(options, prompt)

    if options.dry_run:
        _print_dry_run_preview(options, cmd, prompt)
        return 0

    env = _build_env(options)

    if options.agent in ("agy", "antigravity"):
        with shim.create_agy_shim(model=options.model):
            proc = subprocess.run(cmd, cwd=options.repo_path, env=env)
            return proc.returncode

    proc = subprocess.run(cmd, cwd=options.repo_path, env=env)
    return proc.returncode
