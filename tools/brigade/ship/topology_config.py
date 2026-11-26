"""Ship-prep submodule: topology_config."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.constants import DEFAULT_STAGE_BRANCHES

def _read_stage_branches_config(repo_path: Optional[Path]) -> Dict[str, str]:
    if repo_path is None:
        return {}
    cfg_file = Path(repo_path) / ".edge" / "brigade.json"
    if not cfg_file.is_file():
        return {}
    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw_stages = data.get("stage_branches") if isinstance(data, dict) else None
    if not isinstance(raw_stages, dict):
        return {}
    return {
        str(k).strip(): str(v).strip()
        for k, v in raw_stages.items()
        if str(k).strip() and str(v or "").strip()
    }


def resolve_stage_branches(
    repo_path: Optional[Path] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Resolves integration/staging/production branch names from defaults, active profile, .edge/brigade.json, and overrides."""
    resolved = dict(DEFAULT_STAGE_BRANCHES)
    if repo_path is not None:
        from tools.common.profiles import resolve_active_profiles

        profiles = resolve_active_profiles(Path(repo_path))
        if profiles.source != "missing_root":
            prof_branches = profiles.delivery.get("default_stage_branches") or {}
            resolved.update({str(k): str(v) for k, v in prof_branches.items() if str(v).strip()})
    resolved.update(_read_stage_branches_config(repo_path))
    for k, v in (overrides or {}).items():
        clean_k = str(k).strip()
        clean_v = str(v or "").strip()
        if clean_k and clean_v:
            resolved[clean_k] = clean_v
    return resolved


def _get_head_branch(repo: Path) -> str:
    code, out, _ = call_run_command(["git", "branch", "--show-current"], cwd=repo)
    return (out.strip() or "HEAD") if code == 0 else "HEAD"


def _base_commit_timestamp(repo: Path, eff_base: str) -> int:
    code, out, _ = call_run_command(["git", "show", "-s", "--format=%ct", eff_base], cwd=repo)
    if code == 0 and out.strip().isdigit():
        return int(out.strip())
    return 0
