#!/usr/bin/env python3
"""
Edge Brigade Tier Switcher & Model Matrix Controller.
Deterministic toggling between Pro (flash/invoke_subagent/main) and Ultra (gemini-4/opus/swarm/ultra).
Standard library only: sys, os, json, subprocess, dataclasses, datetime, pathlib, typing.
"""

from typing import Dict, List, Optional, Tuple, Union, Any, Literal
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import os
import sys
import json
import subprocess

TierMode = Literal["pro", "ultra"]
VALID_TIERS: Tuple[str, str] = ("pro", "ultra")

PRO_BRANCH: str = "main"
ULTRA_BRANCH: str = "ultra"

PRO_TRANSPORT: str = "invoke_subagent"
ULTRA_TRANSPORT: str = "swarm"

PRO_STATION_MODELS: Dict[str, str] = {
    "spec_writer": "flash",
    "researcher": "flash",
    "spec_critic": "gemini-3.8-flash-high",
    "seam_architect": "flash",
    "coder": "flash",
    "surgeon": "flash",
    "examiner": "flash",
    "qa_engineer": "flash",
}

ULTRA_STATION_MODELS: Dict[str, str] = {
    "spec_writer": "gemini-4-hydrogen-high",
    "researcher": "gemini-4-hydrogen-high",
    "spec_critic": "claude-opus-5-5-high",
    "seam_architect": "gemini-4-hydrogen-xhigh",
    "coder": "gemini-4-hydrogen-high",
    "surgeon": "gemini-4-hydrogen-high",
    "examiner": "gemini-4-hydrogen-high",
    "qa_engineer": "gemini-4-hydrogen-medium",
}

STATION_DESCRIPTIONS: Dict[str, str] = {
    "spec_writer": "Specification Author & Slicer",
    "researcher": "Root Cause & Deep Explorer",
    "spec_critic": "Cross-Provider Spec Reviewer",
    "seam_architect": "Contract & RED Test Author",
    "coder": "GREEN Implementation Coder",
    "surgeon": "Refactoring Specialist",
    "examiner": "Standards & Invariants Examiner",
    "qa_engineer": "Visual & E2E Quality Assurance",
}


@dataclass
class TierState:
    tier: str
    branch: str
    transport: str
    station_models: Dict[str, str]
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        """Serializes dataclass to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TierState":
        """Instantiates TierState from a dictionary with backward compatibility."""
        tier = str(data.get("tier") or "pro")
        branch = str(data.get("branch") or _default_branch(tier))
        transport = str(data.get("transport") or _default_transport(tier))
        models = _parse_models(data.get("station_models"), tier)
        updated_at = str(data.get("updated_at") or datetime.now(timezone.utc).isoformat())
        return cls(
            tier=tier,
            branch=branch,
            transport=transport,
            station_models=models,
            updated_at=updated_at,
        )


def _default_branch(tier: str) -> str:
    """Returns default branch name for the given tier."""
    if tier == "ultra":
        return ULTRA_BRANCH
    return PRO_BRANCH


def _default_transport(tier: str) -> str:
    """Returns default transport mechanism for the given tier."""
    if tier == "ultra":
        return ULTRA_TRANSPORT
    return PRO_TRANSPORT


def _parse_models(raw_models: Any, tier: str) -> Dict[str, str]:
    """Resolves station models dictionary with fallback to default tier models."""
    if isinstance(raw_models, dict):
        return dict(raw_models)
    if tier == "ultra":
        return dict(ULTRA_STATION_MODELS)
    return dict(PRO_STATION_MODELS)


def _create_tier_state(tier: str, branch: str) -> TierState:
    """Constructs a new TierState for the given tier and branch."""
    if tier == "ultra":
        return TierState(
            tier="ultra",
            branch=branch,
            transport=ULTRA_TRANSPORT,
            station_models=dict(ULTRA_STATION_MODELS),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
    return TierState(
        tier="pro",
        branch=branch,
        transport=PRO_TRANSPORT,
        station_models=dict(PRO_STATION_MODELS),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def get_tier_state_path() -> Path:
    """
    Resolves the persistent state path for the active tier.
    Respects EDGE_TIER_STATE_PATH environment variable for hermetic testing.
    Default: ~/.gemini/antigravity/edge_tier.json
    """
    env_override = os.environ.get("EDGE_TIER_STATE_PATH")
    if env_override:
        return Path(env_override)
    return Path.home() / ".gemini" / "antigravity" / "edge_tier.json"


def _atomic_write_tier_state(state: TierState, path: Path) -> None:
    """
    Atomically writes TierState to destination path using <path>.tmp.<pid> and os.replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    payload = json.dumps(state.to_dict(), indent=2)
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _run_git(args: List[str], cwd: Path) -> Tuple[int, str, str]:
    """Runs a git command in cwd, returning (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode, proc.stdout.rstrip("\r\n"), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


def _get_current_git_branch(repo: Path) -> str:
    """Determines the current git branch of repo."""
    code, out, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    if code == 0 and out.strip():
        return out.strip()
    return "main"


def _extract_dirty_path(line: str) -> Optional[str]:
    """Extracts path if the status line indicates a dirty tracked file outside .edge/."""
    if len(line) < 3 or line.startswith("??"):
        return None
    path_part = line[2:].strip()
    if " -> " in path_part:
        path_part = path_part.split(" -> ")[1].strip()
    if path_part.startswith((".edge/", ".edge\\", ".edge")):
        return None
    return path_part


def _check_tracked_cleanliness(repo: Path) -> Tuple[bool, List[str]]:
    """
    Checks if repo working tree has uncommitted tracked modifications outside .edge/.
    Untracked files (??) and files inside .edge/ are ignored.
    """
    code, out, _ = _run_git(["status", "--porcelain"], repo)
    if code != 0 or not out:
        return True, []

    dirty_files: List[str] = []
    for line in out.splitlines():
        extracted = _extract_dirty_path(line)
        if extracted:
            dirty_files.append(extracted)

    return len(dirty_files) == 0, dirty_files


def _ensure_branch_exists(repo: Path, branch: str) -> Tuple[bool, str]:
    """Ensures branch exists; creates it from HEAD if missing."""
    code, _, _ = _run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], repo)
    if code == 0:
        return True, ""
    create_code, _, create_err = _run_git(["branch", branch], repo)
    if create_code != 0:
        return False, f"Failed to create branch '{branch}': {create_err}"
    return True, ""


def _checkout_git_branch(repo: Path, branch: str) -> Tuple[bool, str]:
    """Checks out the requested branch."""
    code, _, err = _run_git(["checkout", branch], repo)
    if code != 0:
        return False, f"Git checkout '{branch}' failed: {err}"
    return True, ""


def get_tier_status(repo_path: Union[Path, str], state_path: Optional[Path] = None) -> TierState:
    """
    Inspects current git branch and persisted state file.
    If state file exists and valid, returns it.
    Otherwise, inspects current git branch of repo_path and returns default TierState.
    """
    path = state_path or get_tier_state_path()
    if path.is_file():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TierState.from_dict(data)
        except Exception:
            pass  # Fall through to branch inspection

    repo = Path(repo_path)
    branch = _get_current_git_branch(repo)
    tier_name = "ultra" if branch == ULTRA_BRANCH else "pro"
    return _create_tier_state(tier_name, branch)


def _prepare_target_branch(repo: Path, target_tier: str) -> Tuple[bool, str, str]:
    """Ensures target branch exists and is checked out. Returns (ok, branch, err)."""
    target_branch = ULTRA_BRANCH if target_tier == "ultra" else PRO_BRANCH
    if target_tier == "ultra":
        ok, err = _ensure_branch_exists(repo, ULTRA_BRANCH)
        if not ok:
            return False, target_branch, err
    ok, err = _checkout_git_branch(repo, target_branch)
    if not ok:
        return False, target_branch, err
    return True, target_branch, ""


def switch_tier(
    repo_path: Union[Path, str],
    target_tier: str,
    state_path: Optional[Path] = None,
) -> Tuple[bool, str, TierState]:
    """
    Switches Edge Brigade execution tier.
    Validates tier mode ('pro' or 'ultra').
    Checks git cleanliness on tracked non-.edge/ files.
    Switches git branch ('main' for pro, 'ultra' for ultra).
    Persists state atomically.
    Returns (success, message_or_card, final_state).
    """
    repo = Path(repo_path)
    state_file = state_path or get_tier_state_path()
    current_state = get_tier_status(repo, state_file)

    tier_clean = target_tier.strip().lower()
    if tier_clean not in VALID_TIERS:
        err = f"❌ Invalid tier '{target_tier}'. Supported tiers: {', '.join(VALID_TIERS)}"
        return False, err, current_state

    is_clean, dirty_files = _check_tracked_cleanliness(repo)
    if not is_clean:
        err = f"❌ Cannot switch tier: Working tree has uncommitted tracked changes outside .edge/ ({', '.join(dirty_files)})"
        return False, err, current_state

    ok, target_branch, checkout_err = _prepare_target_branch(repo, tier_clean)
    if not ok:
        return False, f"❌ {checkout_err}", current_state

    new_state = _create_tier_state(tier_clean, target_branch)
    _atomic_write_tier_state(new_state, state_file)
    card = format_tier_card(new_state)
    return True, card, new_state


def format_tier_card(state: TierState) -> str:
    """
    Renders a crisp, user-facing Markdown card summarizing active tier,
    transport, target branch, and the 8-station model allocation matrix.
    """
    tier_upper = state.tier.upper()
    icon = "🚀" if state.tier == "ultra" else "⚡"
    transport_label = "swarm (Shared message board)" if state.transport == "swarm" else "invoke_subagent (Isolated subagents)"

    lines = [
        f"### {icon} Edge Execution Tier: {tier_upper}",
        "",
        f"- **Tier:** `{state.tier}`",
        f"- **Active Branch:** `{state.branch}`",
        f"- **Agent Transport:** `{transport_label}`",
        f"- **Updated:** `{state.updated_at}`",
        "",
        "#### 📋 Station Model Matrix",
        "",
        "| Station Role | Model | Description |",
        "| :--- | :--- | :--- |",
    ]

    for role, model in sorted(state.station_models.items()):
        desc = STATION_DESCRIPTIONS.get(role, "Brigade Station Worker")
        lines.append(f"| `{role}` | `{model}` | {desc} |")

    return "\n".join(lines)


def _cli_switch() -> int:
    """Helper for CLI switch action to keep main() CC low."""
    if len(sys.argv) < 3:
        print("Error: switch requires target tier ('pro' or 'ultra')")
        return 1
    target_tier = sys.argv[2]
    repo = sys.argv[3] if len(sys.argv) > 3 else "."
    success, msg, _ = switch_tier(repo, target_tier)
    print(msg)
    return 0 if success else 1


def main() -> int:
    """
    CLI interface for tier.py.
    Usage:
        python3 tools/brigade/tier.py status [repo]
        python3 tools/brigade/tier.py switch <pro|ultra> [repo]
    """
    if len(sys.argv) < 2:
        print("Usage: tier.py status [repo] | tier.py switch <pro|ultra> [repo]")
        return 1

    action = sys.argv[1].lower()
    if action == "status":
        repo = sys.argv[2] if len(sys.argv) > 2 else "."
        state = get_tier_status(repo)
        print(format_tier_card(state))
        return 0

    if action == "switch":
        return _cli_switch()

    print(f"Unknown action '{action}'. Use 'status' or 'switch'.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
