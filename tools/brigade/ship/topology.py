"""Ship-prep submodule: topology."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.constants import DEFAULT_STAGE_BRANCHES, _SLICE_BRANCH_PREFIXES
from tools.brigade.ship.topology_config import _get_head_branch

def _candidate_base_refs(
    raw: str,
    eff_head: str,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    clean_base = raw[7:] if raw.startswith("origin/") else raw
    if raw.startswith("origin/"):
        return raw, clean_base
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    protected_bases = {eff_stages.get("staging", "staging"), eff_stages.get("production", "production"), "staging"}
    if eff_head == clean_base or clean_base in protected_bases:
        return f"origin/{clean_base}", clean_base
    return clean_base, f"origin/{clean_base}"


def _resolve_base_ref(
    repo: Path,
    base_branch: str,
    head_branch: Optional[str] = None,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    raw = (base_branch or "").strip()
    if not raw:
        return None
    eff_head = head_branch if head_branch is not None else _get_head_branch(repo)
    for cand in _candidate_base_refs(raw, eff_head, stage_branches):
        code, _, _ = call_run_command(["git", "rev-parse", "--verify", cand], cwd=repo)
        if code == 0:
            return cand
    return None


def validate_branch_topology(
    base_branch: str,
    head_branch: str,
    split_branches: bool = False,
    allow_override: bool = False,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """Enforces development-first PR topology unless allow_override=True bypasses it."""
    if allow_override:
        return True, ""
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    integration_branch = eff_stages.get("integration", "development")
    staging_branch = eff_stages.get("staging", "staging")
    production_branch = eff_stages.get("production", "production")

    raw_base = (base_branch or "").strip()
    clean_base = raw_base[7:] if raw_base.startswith("origin/") else raw_base
    if clean_base not in (staging_branch, production_branch) or clean_base == integration_branch:
        return True, ""
    if split_branches:
        return (
            False,
            f"Branch topology violation: per-spec split branches (ship/<slug>) must target "
            f"'{integration_branch}' first (--base {integration_branch}), never '{clean_base}' directly.",
        )
    clean_head = (head_branch or "").strip()
    if clean_head.startswith(_SLICE_BRANCH_PREFIXES):
        return (
            False,
            f"Branch topology violation: slice branch '{clean_head}' cannot target '{clean_base}' directly. "
            f"Open per-spec PR to '{integration_branch}' first, then promote '{integration_branch}' -> '{clean_base}'.",
        )
    return True, ""


def _collect_git_diff_bundle(repo: Path, eff_base: str) -> Tuple[bool, str, List[str], str, str, str]:
    _, head_out, _ = call_run_command(["git", "branch", "--show-current"], cwd=repo)
    head_branch = head_out.strip() or "HEAD"

    d_code, diff_names_out, diff_err = call_run_command(["git", "diff", "--name-only", f"{eff_base}..HEAD"], cwd=repo)
    if d_code != 0:
        return False, head_branch, [], "", "", f"Git diff failed: {diff_err}"

    changed_files = [line.strip() for line in diff_names_out.splitlines() if line.strip()]
    _, diff_stat, _ = call_run_command(["git", "diff", "--stat", f"{eff_base}..HEAD"], cwd=repo)
    _, idx_diff, _ = call_run_command(["git", "diff", f"{eff_base}..HEAD", "--", "specs/INDEX.md"], cwd=repo)
    if not idx_diff.strip() and (repo / "specs" / "INDEX.md").is_file() and "specs/INDEX.md" in changed_files:
        idx_diff = (repo / "specs" / "INDEX.md").read_text(encoding="utf-8", errors="ignore")
    return True, head_branch, changed_files, diff_stat, idx_diff, ""
