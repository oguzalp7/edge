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
from typing import Dict, Iterable, List, Optional, Tuple

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


def _resolve_binary_path(name: str) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    if name == "python":
        return shutil.which("python3")
    return None


def probe_binary(name: str, timeout: int = 3) -> ToolProbeResult:
    """Probe a single binary using shutil.which and a bounded version check."""
    resolved = _resolve_binary_path(name)
    if not resolved:
        return ToolProbeResult(name=name, available=False)
    try:
        proc = subprocess.run(
            [resolved, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        version = _extract_version_line(proc.stdout, proc.stderr)
        return ToolProbeResult(name=name, available=True, path=resolved, version=version)
    except subprocess.TimeoutExpired:
        return ToolProbeResult(name=name, available=True, path=resolved, error="timeout")
    except Exception as exc:
        return ToolProbeResult(name=name, available=True, path=resolved, error=str(exc))


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
    for key in ("PreToolUse", "PostToolUse", "PreInvocation"):
        if key not in guard_cfg:
            issues.append(f"hooks.json missing '{key}' hook configuration")


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


def build_capability_matrix(probes: Dict[str, ToolProbeResult]) -> Tuple[List[CapabilityEntry], str]:
    """Compute Edge capability statuses and recommended install profile."""
    py_ok = _has(probes, "python")
    git_ok = _has(probes, "git")
    specs = (
        ("core_hooks", "native" if (py_ok and git_ok) else "unavailable", "Session-gated lifecycle hooks and git operations", ["python", "git"]),
        ("github_tracker", _status_for_tools(probes, ("gh-axi", "gh")), "GitHub Issues SSOT (falls back to local .edge/issues/)", ["gh-axi", "gh"]),
        ("isolated_worktrees", "native" if _has(probes, "treehouse") else ("passive" if git_ok else "unavailable"), "Treehouse worktree pool (falls back to git worktree)", ["treehouse", "git"]),
        ("visual_gate", _status_for_tools(probes, ("lavish-axi",)), "UI mockup gate via lavish-axi (skipped passively when absent)", ["lavish-axi"]),
        ("browser_qa", _status_for_tools(probes, ("chrome-devtools-axi", "chrome-dev-tools-axi")), "Headless Chrome verification via chrome-devtools-axi", ["chrome-devtools-axi", "chrome-dev-tools-axi"]),
        ("python_tooling", _status_for_tools(probes, ("uv",)), "Ephemeral Python runner via uv", ["uv"]),
        ("node_runtime", _status_for_tools(probes, ("node",)), "Node.js tooling support", ["node"]),
        ("wsl_bridge", _status_for_tools(probes, ("wsl",)), "Optional Windows-to-WSL2 path/command bridge", ["wsl"]),
    )
    entries = [CapabilityEntry(name=n, status=s, detail=d, required_tools=r) for n, s, d, r in specs]
    return entries, _recommend_profile(probes)
