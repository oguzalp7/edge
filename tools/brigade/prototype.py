"""
Cross-OS Interactive UI Prototype Bridge for Edge Brigade.
@intent Provide cross-OS lavish-axi prototype bridge, Windows-safe node shim resolution, and HTML artifact fallback
@concepts cross-os-visual-bridge, cross-os-runtime-env
@invariants [INV-BRIGADE-CROSS-OS-ENV]
"""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from tools.common import normalize_target_path
from tools.common.env import detect_os_mode
from tools.common.paths import is_wsl_path, to_wsl_path

_CMD_SCRIPT_RE = re.compile(r'(?:%~dp0|%dp0%)[\\/]([^"\'\s]+\.(?:js|mjs|cjs))', re.IGNORECASE)


def resolve_safe_node_argv(
    cmd_path: str, which_fn: Callable[[str], Optional[str]] = shutil.which
) -> List[str]:
    """Unwrap Windows .cmd/.bat npm shims into [node.exe, script.js] to bypass cmd.exe."""
    lower_cmd = cmd_path.lower()
    if os.name != "nt" or not (lower_cmd.endswith(".cmd") or lower_cmd.endswith(".bat")):
        return [cmd_path]
    try:
        with open(cmd_path, "r", encoding="utf-8", errors="ignore") as fh:
            shim_text = fh.read()
    except OSError:
        return [cmd_path]
    match = _CMD_SCRIPT_RE.search(shim_text)
    if not match:
        return [cmd_path]
    cmd_dir = os.path.dirname(cmd_path)
    rel_parts = [part for part in match.group(1).replace("\\", "/").split("/") if part]
    target_js = os.path.join(cmd_dir, *rel_parts)
    sibling_node = os.path.join(cmd_dir, "node.exe")
    node_exe = sibling_node if os.path.isfile(sibling_node) else which_fn("node")
    if node_exe and os.path.isfile(target_js):
        return [node_exe, target_js]
    return [cmd_path]


def resolve_lavish_command(
    which_fn: Callable[[str], Optional[str]] = shutil.which,
) -> Tuple[str, List[str]]:
    """Resolve prototype runner precedence: lavish-axi -> npx --yes lavish-axi -> artifact."""
    cli_bin = which_fn("lavish-axi")
    if cli_bin:
        return "cli", resolve_safe_node_argv(cli_bin, which_fn)
    npx_bin = which_fn("npx")
    if npx_bin:
        return "npx", [*resolve_safe_node_argv(npx_bin, which_fn), "--yes", "lavish-axi"]
    return "artifact", []


def format_prototype_cli_arg(html_file: Union[Path, str]) -> str:
    """Format HTML path natively across OSes, translating WSL UNC paths only on Windows."""
    if detect_os_mode() == "windows" and is_wsl_path(html_file):
        return to_wsl_path(html_file)
    return str(html_file)


def resolve_prototype_file(
    repo_path: Path, raw_file: Optional[str], must_exist: bool
) -> Tuple[Optional[str], Optional[str]]:
    """Validate and resolve the target .lavish HTML prototype path."""
    if not raw_file:
        return None, "❌ --file is required. Example: --file .lavish/feature.html"
    is_abs = os.path.isabs(raw_file) or (len(raw_file) >= 2 and raw_file[1] == ":")
    html_file = raw_file if is_abs else os.path.join(str(repo_path), raw_file)
    if must_exist and not os.path.exists(html_file):
        return None, f"❌ HTML file not found: {html_file}"
    return html_file, None


def read_lavish_sessions(state_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read ~/.lavish-axi/state.json sessions in pure Python without spawning subprocesses."""
    target = state_path or (Path.home() / ".lavish-axi" / "state.json")
    if not target.is_file():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    sessions = data.get("sessions", {}) if isinstance(data, dict) else {}
    if not isinstance(sessions, dict):
        return []
    return [
        {
            "id": sid,
            "file": info.get("file"),
            "status": info.get("status"),
            "endedAt": info.get("endedAt"),
            "endedBy": info.get("endedBy"),
        }
        for sid, info in sessions.items()
        if isinstance(info, dict)
    ]


def _artifact_fallback_response(action: str, html_file: Optional[str]) -> Tuple[int, str, str]:
    if action == "stop":
        payload = {"mode": "artifact", "action": "stop", "message": "No external lavish-axi server running in artifact mode."}
        return 0, json.dumps(payload, indent=2), ""
    file_uri = Path(os.path.abspath(html_file)).as_uri() if html_file else ""
    payload = {
        "mode": "artifact",
        "action": action,
        "file_uri": file_uri,
        "instruction": "lavish-axi and npx are unavailable. Present this file:// URI for visual review and use ask_question to confirm approval before coding.",
    }
    return 0, json.dumps(payload, indent=2), ""


def _build_lavish_argv(
    base_argv: List[str], action: str, html_file: Optional[str], agent_reply: Optional[str]
) -> Optional[List[str]]:
    if action == "serve" and html_file is not None:
        return [*base_argv, format_prototype_cli_arg(html_file)]
    if action == "poll" and html_file is not None:
        extra = ["--agent-reply", agent_reply] if agent_reply else []
        return [*base_argv, "poll", format_prototype_cli_arg(html_file), *extra]
    if action == "stop":
        return [*base_argv, "stop"]
    return None


def _run_prototype_subprocess(
    cmd_argv: List[str], norm_repo: Path, action: str, timeout: int
) -> Tuple[int, str, str]:
    cwd_arg = str(norm_repo) if norm_repo.exists() else None
    eff_timeout = timeout if action == "poll" else 60
    try:
        proc = subprocess.run(
            cmd_argv,
            cwd=cwd_arg,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            timeout=eff_timeout,
        )
        return proc.returncode, (proc.stdout or "").strip(), (proc.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return 124, "", f"Prototype action '{action}' timed out."
    except Exception as exc:
        return 1, "", f"Failed to run prototype action '{action}': {exc}"


def execute_prototype_action(
    repo_path: Path,
    action: str,
    raw_file: Optional[str] = None,
    agent_reply: Optional[str] = None,
    timeout: int = 3600,
) -> Tuple[int, str, str]:
    """Execute lavish-axi serve/poll/stop/status with shell=False and HTML artifact fallback."""
    norm_repo = normalize_target_path(repo_path)
    if action == "status":
        return 0, json.dumps(read_lavish_sessions(), indent=2), ""
    html_file: Optional[str] = None
    if action in ("serve", "poll"):
        html_file, err = resolve_prototype_file(norm_repo, raw_file, must_exist=(action == "serve"))
        if err:
            return 1, "", err
    mode, base_argv = resolve_lavish_command(shutil.which)
    if mode == "artifact":
        return _artifact_fallback_response(action, html_file)
    cmd_argv = _build_lavish_argv(base_argv, action, html_file, agent_reply)
    if cmd_argv is None:
        return 0, "", ""
    return _run_prototype_subprocess(cmd_argv, norm_repo, action, timeout)
