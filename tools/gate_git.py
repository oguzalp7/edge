"""Git diff, navigation, and ghost-root helpers for Edge Verification Gate."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.gate_static import GateResult, is_eligible_prod_path


def _collect_norm_paths(stdout: str, seen: Dict[str, None]) -> None:
    for line in stdout.splitlines():
        norm = line.strip().replace("\\", "/")
        if norm.startswith("./"):
            norm = norm[2:]
        if norm:
            seen[norm] = None


def get_changed_rel_paths(target_repo: Path, run_cmd: Any, base_ref: str = "HEAD~1") -> Tuple[Optional[List[str]], str, str]:
    """Return (rel_paths, effective_base_ref, error_message) including untracked files."""
    eff_base = base_ref
    code, stdout, stderr = run_cmd(["git", "diff", "--name-only", base_ref])
    if code != 0:
        eff_base = "HEAD"
        code, stdout, stderr = run_cmd(["git", "diff", "--name-only", "HEAD"])
        if code != 0:
            code, stdout, stderr = run_cmd(["git", "diff", "--name-only"])
            if code != 0:
                return None, eff_base, stderr.strip()
    seen: Dict[str, None] = {}
    _collect_norm_paths(stdout, seen)
    if (target_repo / ".git").exists():
        u_code, u_out, _ = run_cmd(["git", "ls-files", "--others", "--exclude-standard"])
        if u_code == 0 and u_out:
            _collect_norm_paths(u_out, seen)
    return list(seen.keys()), eff_base, ""


def get_modified_files(target_repo: Path, run_cmd: Any, base_ref: Optional[str] = None) -> Optional[List[Path]]:
    """Return existing modified Path objects between base_ref and HEAD/worktree."""
    if not base_ref:
        return None
    code, stdout, _ = run_cmd(["git", "diff", "--name-only", base_ref])
    if code != 0:
        code, stdout, _ = run_cmd(["git", "diff", "--name-only", base_ref, "HEAD"])
        if code != 0:
            return None
    files: List[Path] = []
    for line in stdout.splitlines():
        clean = line.strip().replace("\\", "/")
        if clean and (target_repo / clean).exists():
            files.append(target_repo / clean)
    return files


def read_changed_prod_files(
    target_repo: Path, run_cmd: Any, base_ref: Optional[str], suffixes: Tuple[str, ...], require_src_prefix: bool = False
) -> Tuple[Optional[List[Tuple[str, str]]], str]:
    """Read changed eligible production source files."""
    rel_paths, _, err = get_changed_rel_paths(target_repo, run_cmd, base_ref or "HEAD~1")
    if rel_paths is None:
        return None, err
    items: List[Tuple[str, str]] = []
    for rel_path in rel_paths:
        if is_eligible_prod_path(rel_path, suffixes, require_src_prefix) and (target_repo / rel_path).is_file():
            items.append((rel_path, (target_repo / rel_path).read_text(encoding="utf-8", errors="replace")))
    return items, ""


def get_head_commit_sha(run_cmd: Any) -> str:
    """Return current git HEAD SHA or empty string."""
    code, stdout, _ = run_cmd(["git", "rev-parse", "HEAD"])
    return stdout.strip() if code == 0 and stdout.strip() else ""


def check_ghost_root_directories(target_repo: Path, ghost_dirs: Tuple[str, ...]) -> GateResult:
    """Detect truncated ghost root directories (e.g., 'rc', 'pecs', 'ests')."""
    detected = [name for name in ghost_dirs if (target_repo / name).is_dir()]
    if detected:
        details = [f"Found invalid ghost directory: {target_repo / d}" for d in detected]
        msg = (
            f"Truncated ghost root directories detected: {', '.join(detected)}. "
            "These indicate path-slicing defects (e.g. 'rc' instead of 'src'). Clean up or remove these directories before proceeding."
        )
        return GateResult(0, "Ghost Root Directory Sanitizer Gate", False, msg, details)
    return GateResult(0, "Ghost Root Directory Sanitizer Gate", True, "No truncated ghost root directories detected in repository root.")


def has_navigation_check_script(target_repo: Path) -> bool:
    """Return True when target package.json defines a non-empty check:navigation script."""
    pkg_path = target_repo / "package.json"
    if not pkg_path.is_file():
        return False
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    scripts = data.get("scripts") if isinstance(data, dict) else None
    nav = scripts.get("check:navigation") if isinstance(scripts, dict) else None
    return isinstance(nav, str) and bool(nav.strip())


def check_navigation_gate(target_repo: Path, run_cmd: Any) -> GateResult:
    """Run npm run check:navigation unconditionally when configured in package.json."""
    if not has_navigation_check_script(target_repo):
        return GateResult(1, "Navigation Check Gate", True, "No check:navigation script configured; skipped.")
    if not (target_repo / "node_modules").exists():
        return GateResult(1, "Navigation Check Gate", False, "Missing node_modules for check:navigation — symlink or run npm ci before running gate.")
    code, stdout, stderr = run_cmd(["npm", "run", "check:navigation"], timeout=60)
    if code == 0:
        return GateResult(1, "Navigation Check Gate", True, "Navigation integrity check (check:navigation) passed.")
    details = [ln.strip() for ln in (stdout + "\n" + stderr).splitlines() if ln.strip()][:8]
    return GateResult(1, "Navigation Check Gate", False, f"Navigation integrity check (check:navigation) failed (exit code {code}).", details)
