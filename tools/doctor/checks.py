#!/usr/bin/env python3
"""
Read-only environment probes, hook health checks, and capability matrix builder.
@intent Probe installed toolchain binaries, validate hook integrity, and classify install tier
@concepts doctor-preflight, cross-os-runtime-env
@invariants [INV-BRIGADE-CROSS-OS-ENV]
"""

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tools.common.env import detect_os_mode
from .models import CapabilityEntry, HooksHealthResult, ToolProbeResult

PROBE_BINARIES: Tuple[str, ...] = (
    "python",
    "git",
    "node",
    "uv",
    "gh",
    "gh-axi",
    "treehouse",
    "lavish-axi",
    "npx",
    "chrome-devtools-axi",
    "chrome-dev-tools-axi",
    "wsl",
)


def _extract_version_line(stdout: str, stderr: str) -> str:
    for stream in (stdout, stderr):
        for line in (stream or "").splitlines():
            stripped = line.replace("\x00", "").strip()
            if stripped:
                return stripped[:120]
    return ""


def _is_windows_store_stub(path_str: str) -> bool:
    norm = path_str.replace("\\", "/").lower()
    return "/microsoft/windowsapps/" in norm or "/windowsapps/" in norm


def _resolve_binary_path(name: str) -> Optional[str]:
    candidates = ("python", "python3") if name == "python" else (name,)
    for candidate in candidates:
        found = shutil.which(candidate)
        if found and not (name == "python" and _is_windows_store_stub(found)):
            return found
    return None


def _fallback_sys_python() -> ToolProbeResult:
    exe = sys.executable or ""
    if exe and Path(exe).is_file() and sys.version:
        ver = sys.version.split()[0]
        return ToolProbeResult(name="python", available=True, path=exe, version=f"Python {ver}")
    return ToolProbeResult(name="python", available=False)


def _run_version_probe(name: str, resolved: str, timeout: int) -> ToolProbeResult:
    try:
        proc = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if name == "python" and proc.returncode != 0:
            fallback = _fallback_sys_python()
            if fallback.available:
                return fallback
        version = _extract_version_line(proc.stdout, proc.stderr)
        return ToolProbeResult(name=name, available=True, path=resolved, version=version)
    except subprocess.TimeoutExpired:
        return ToolProbeResult(name=name, available=True, path=resolved, error="timeout")
    except Exception as exc:
        return ToolProbeResult(name=name, available=True, path=resolved, error=str(exc))


def probe_binary(name: str, timeout: int = 3) -> ToolProbeResult:
    """Probe a single binary using shutil.which, sys.executable fallback, and --version."""
    resolved = _resolve_binary_path(name)
    if not resolved:
        return _fallback_sys_python() if name == "python" else ToolProbeResult(name=name, available=False)
    return _run_version_probe(name, resolved, timeout)


def probe_all_tools(names: Iterable[str] = PROBE_BINARIES) -> Dict[str, ToolProbeResult]:
    """Probe all standard Edge toolchain binaries."""
    os_mode = detect_os_mode()
    results: Dict[str, ToolProbeResult] = {}
    for name in names:
        if name == "wsl" and os_mode not in ("windows", "wsl"):
            results[name] = ToolProbeResult(name=name, available=False)
            continue
        results[name] = probe_binary(name)
    return results


def _iter_hook_commands(guard_cfg: Dict[str, Any], key: str) -> List[str]:
    entries = guard_cfg.get(key)
    if not isinstance(entries, list):
        return []
    cmds: List[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        cmd = entry.get("command")
        if isinstance(cmd, str):
            cmds.append(cmd)
        for nested in entry.get("hooks") or ():
            if isinstance(nested, dict) and isinstance(nested.get("command"), str):
                cmds.append(nested["command"])
    return cmds


def _validate_hooks_json(hooks_json_path: Path, issues: List[str]) -> None:
    if not hooks_json_path.is_file():
        issues.append(f"Missing {hooks_json_path}")
        return
    try:
        raw = hooks_json_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        issues.append(f"Invalid JSON in hooks.json: {exc}")
        return
    if not isinstance(data, dict) or "edge-orchestrator-guard" not in data:
        issues.append("hooks.json missing 'edge-orchestrator-guard' section")
        return
    guard_cfg = data["edge-orchestrator-guard"]
    if not isinstance(guard_cfg, dict):
        issues.append("hooks.json 'edge-orchestrator-guard' must be an object")
        return
    for key in ("PreToolUse", "PostToolUse", "PreInvocation"):
        if key not in guard_cfg:
            issues.append(f"hooks.json missing '{key}' hook configuration")
            continue
        cmds = _iter_hook_commands(guard_cfg, key)
        if not any("hooks/dispatch.cmd" in cmd and 'cd . && "hooks/dispatch.cmd"' in cmd for cmd in cmds):
            issues.append(
                f"hooks.json '{key}' must invoke 'cd . && \"hooks/dispatch.cmd\"' "
                "(prevents Windows cmd /c quote stripping)"
            )


def _validate_dispatch_cmd(cmd_path: Path, issues: List[str]) -> None:
    if not cmd_path.is_file():
        issues.append(f"Missing {cmd_path}")
        return
    raw_bytes = cmd_path.read_bytes()
    if b"\r" in raw_bytes:
        issues.append("hooks/dispatch.cmd must use LF-only line endings")
    if os.name == "posix" and not (os.stat(cmd_path).st_mode & stat.S_IXUSR):
        issues.append("hooks/dispatch.cmd is not executable (+x missing)")


def check_hooks_health(plugin_root: Path) -> HooksHealthResult:
    """Validate hooks.json, hooks/dispatch.cmd, and hooks/dispatch.py under plugin_root."""
    root = Path(plugin_root)
    issues: List[str] = []
    _validate_hooks_json(root / "hooks.json", issues)
    _validate_dispatch_cmd(root / "hooks" / "dispatch.cmd", issues)
    if not (root / "hooks" / "dispatch.py").is_file():
        issues.append("Missing hooks/dispatch.py")
    return HooksHealthResult(ok=(len(issues) == 0), issues=issues, plugin_root=str(root))


def _has(probes: Dict[str, ToolProbeResult], *names: str) -> bool:
    return any(bool(probes.get(n) and probes[n].available) for n in names)


def _recommend_profile(probes: Dict[str, ToolProbeResult]) -> str:
    has_core = (
        _has(probes, "python")
        and _has(probes, "git")
        and _has(probes, "uv")
        and _has(probes, "node")
        and _has(probes, "gh", "gh-axi")
    )
    if not has_core:
        return "lite"
    has_full = (
        _has(probes, "treehouse")
        and _has(probes, "lavish-axi")
        and _has(probes, "chrome-devtools-axi", "chrome-dev-tools-axi")
    )
    return "full" if has_full else "core"


def _status_for_tools(
    probes: Dict[str, ToolProbeResult],
    tools: Tuple[str, ...],
    missing_status: str = "passive",
) -> str:
    return "native" if _has(probes, *tools) else missing_status


def _worktree_capability(probes: Dict[str, ToolProbeResult]) -> Tuple[str, str]:
    if _has(probes, "treehouse"):
        return "native", "Treehouse worktree pool (native git worktree fallback available)"
    if _has(probes, "git"):
        return "native", "Native git worktree fallback (Treehouse optional)"
    return "unavailable", "Requires git (or Treehouse) for isolated worktrees"


def _visual_capability(probes: Dict[str, ToolProbeResult]) -> Tuple[str, str]:
    if _has(probes, "lavish-axi"):
        return "native", "UI mockup gate via lavish-axi"
    if _has(probes, "npx"):
        return "passive", "npx --yes lavish-axi fallback (HTML artifact preview available)"
    return "passive", "HTML artifact fallback (lavish-axi/npx absent)"


def _browser_capability(probes: Dict[str, ToolProbeResult]) -> Tuple[str, str]:
    if _has(probes, "chrome-devtools-axi", "chrome-dev-tools-axi"):
        return "native", "Headless Chrome verification via chrome-devtools-axi"
    return "passive", "Built-in browser subagent / chrome-devtools-mcp fallback"


def build_capability_matrix(probes: Dict[str, ToolProbeResult]) -> Tuple[List[CapabilityEntry], str]:
    """Compute Edge capability statuses and recommended install profile."""
    py_ok = _has(probes, "python")
    git_ok = _has(probes, "git")
    wt_status, wt_detail = _worktree_capability(probes)
    vis_status, vis_detail = _visual_capability(probes)
    br_status, br_detail = _browser_capability(probes)
    specs = (
        ("core_hooks", "native" if (py_ok and git_ok) else "unavailable", "Session-gated lifecycle hooks and git operations", ["python", "git"]),
        ("github_tracker", _status_for_tools(probes, ("gh-axi", "gh")), "GitHub Issues SSOT (falls back to local .edge/issues/)", ["gh-axi", "gh"]),
        ("isolated_worktrees", wt_status, wt_detail, ["treehouse", "git"]),
        ("visual_gate", vis_status, vis_detail, ["lavish-axi", "npx"]),
        ("browser_qa", br_status, br_detail, ["chrome-devtools-axi", "chrome-dev-tools-axi"]),
        ("python_tooling", _status_for_tools(probes, ("uv",)), "Ephemeral Python runner via uv", ["uv"]),
        ("node_runtime", _status_for_tools(probes, ("node",)), "Node.js tooling support", ["node"]),
        ("wsl_bridge", _status_for_tools(probes, ("wsl",)), "Optional Windows-to-WSL2 path/command bridge", ["wsl"]),
    )
    entries = [CapabilityEntry(name=n, status=s, detail=d, required_tools=r) for n, s, d, r in specs]
    return entries, _recommend_profile(probes)
