"""
Subprocess execution runner for Edge Tools.
Handles transparent dispatching between Windows host and WSL Linux environment.
"""

import os
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Union

from .paths import is_wsl_path, to_wsl_path, WSL_DISTRO


def run_command(
    cmd: Union[List[str], str],
    cwd: Optional[Union[Path, str]] = None,
    timeout: int = 120,
) -> Tuple[int, str, str]:
    """
    Executes a command cleanly.
    If the working directory is in WSL, routes the command through `wsl -d <distro> bash -c`.
    Returns (exit_code, stdout, stderr).
    """
    work_dir = Path(cwd) if cwd else Path.cwd()
    needs_wsl = is_wsl_path(work_dir) and os.name == "nt"

    if needs_wsl:
        wsl_cwd = to_wsl_path(work_dir)
        if isinstance(cmd, list):
            # Escape inner single quotes if needed
            inner_cmd = " ".join(cmd)
        else:
            inner_cmd = cmd

        full_bash = f"cd {wsl_cwd} && {inner_cmd}"
        exec_cmd = ["wsl", "-d", WSL_DISTRO, "bash", "-c", full_bash]
        exec_cwd = None
    else:
        exec_cmd = cmd
        exec_cwd = str(work_dir) if work_dir.exists() else None

    try:
        res = subprocess.run(
            exec_cmd,
            cwd=exec_cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=isinstance(exec_cmd, str),
            timeout=timeout,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return 1, "", f"Execution error: {str(e)}"
