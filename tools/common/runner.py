"""
Subprocess execution runner for Edge Tools.
Handles transparent dispatching between Windows host and WSL Linux environment.
"""

import os
import shlex
import subprocess
from pathlib import Path
from typing import List, Tuple, Optional, Union

from .env import get_wsl_distro
from .paths import is_wsl_path, to_wsl_path

WSL_DISTRO: str = get_wsl_distro()


def _build_wsl_bash_command(cmd: Union[List[str], str], wsl_cwd: str) -> str:
    """Builds a safely shlex-quoted bash command anchored to wsl_cwd."""
    inner_cmd = shlex.join(cmd) if isinstance(cmd, list) else cmd
    return f"cd {shlex.quote(wsl_cwd)} && {inner_cmd}"


def run_command(
    cmd: Union[List[str], str],
    cwd: Optional[Union[Path, str]] = None,
    timeout: int = 300,
) -> Tuple[int, str, str]:
    """
    Executes a command cleanly.
    If the working directory is in WSL on Windows, routes via `wsl [-d <distro>] bash -c`.
    Returns (exit_code, stdout, stderr).
    """
    work_dir = Path(cwd) if cwd else Path.cwd()
    needs_wsl = is_wsl_path(work_dir) and os.name == "nt"

    if needs_wsl:
        wsl_cwd = to_wsl_path(work_dir)
        full_bash = _build_wsl_bash_command(cmd, wsl_cwd)
        distro = get_wsl_distro() or WSL_DISTRO
        wsl_prefix = ["wsl", "-d", distro] if distro else ["wsl"]
        exec_cmd = [*wsl_prefix, "bash", "-c", full_bash]
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
