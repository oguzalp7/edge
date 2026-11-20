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
import re
import sys
import json
import subprocess

TierMode = Literal["pro", "ultra"]
VALID_TIERS: Tuple[str, str] = ("pro", "ultra")

VALID_EFFORT_LEVELS: Tuple[str, ...] = ("low", "medium", "high", "xhigh")
EFFORT_CAPABLE_FAMILIES: Tuple[str, ...] = (
    "gemini-4-hydrogen",
    "gemini-4-carbon",
    "gemini-4-argon",
    "claude-opus-5-5",
    "claude-sonnet-5-5",
    "gemini-3.8-flash",
)

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


def _atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """
    Atomically writes dictionary to destination path using <path>.tmp.<pid> and os.replace.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _atomic_write_tier_state(state: TierState, path: Path) -> None:
    """
    Atomically writes TierState to destination path by delegating to _atomic_write_json.
    """
    _atomic_write_json(path, state.to_dict())


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


def _resolve_ssot_tier_models(tier_clean: str) -> Dict[str, str]:
    """Resolves active station model map from SSOT config with fallback to static defaults."""
    ssot_cfg = load_ssot_station_config(tier_clean)
    models = {
        r: str(cfg["model"])
        for r, cfg in ssot_cfg.items()
        if isinstance(cfg, dict) and cfg.get("model")
    }
    return models if models else _parse_models(None, tier_clean)


def _resolve_switch_branch(repo: Path, tier_clean: str, checkout: bool) -> Tuple[bool, str, str]:
    """Resolves target branch for switch_tier; skips git checkout when checkout=False."""
    if not checkout:
        return True, _get_current_git_branch(repo), ""

    is_clean, dirty_files = _check_tracked_cleanliness(repo)
    if not is_clean:
        err = f"Cannot switch tier: Working tree has uncommitted tracked changes outside .edge/ ({', '.join(dirty_files)})"
        return False, "", err
    return _prepare_target_branch(repo, tier_clean)


def switch_tier(
    repo_path: Union[Path, str],
    target_tier: str,
    state_path: Optional[Path] = None,
    checkout: bool = False,
) -> Tuple[bool, str, TierState]:
    """
    Switches Edge Brigade execution tier.
    Default (checkout=False) preserves the active git branch and updates state from station_models.json SSOT.
    Opt-in legacy mode (checkout=True) validates cleanliness and runs git checkout (main|ultra).
    Persists state atomically. Returns (success, message_or_card, final_state).
    """
    repo = Path(repo_path)
    state_file = state_path or get_tier_state_path()
    current_state = get_tier_status(repo, state_file)

    tier_clean = target_tier.strip().lower()
    if tier_clean not in VALID_TIERS:
        err = f"❌ Invalid tier '{target_tier}'. Supported tiers: {', '.join(VALID_TIERS)}"
        return False, err, current_state

    ok, target_branch, checkout_err = _resolve_switch_branch(repo, tier_clean, checkout)
    if not ok:
        return False, f"❌ {checkout_err}", current_state

    new_state = TierState(
        tier=tier_clean,
        branch=target_branch,
        transport=_default_transport(tier_clean),
        station_models=_resolve_ssot_tier_models(tier_clean),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
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


def get_station_models_ssot_path() -> Path:
    """
    Resolves the filesystem path for station_models.json SSOT template.
    Supports EDGE_STATION_MODELS_PATH environment variable for hermetic testing.
    """
    env_override = os.environ.get("EDGE_STATION_MODELS_PATH")
    if env_override:
        return Path(env_override)
    return Path(__file__).resolve().parent / "station_models.json"


def apply_effort_to_model(model: str, effort: Optional[str] = None) -> str:
    """
    Normalizes or appends reasoning effort level to a model identifier.
    If model ends with an existing effort suffix (-low, -medium, -high, -xhigh), replaces it.
    If model is in a known effort-capable family without suffix, appends -{effort}.
    """
    if not effort:
        return model
    clean_effort = effort.strip().lower()
    if clean_effort not in VALID_EFFORT_LEVELS:
        return model

    suffix_match = re.search(r"-(low|medium|high|xhigh)$", model)
    if suffix_match:
        return model[:suffix_match.start()] + f"-{clean_effort}"

    if any(family in model for family in EFFORT_CAPABLE_FAMILIES):
        return f"{model}-{clean_effort}"

    return model


def _fallback_station_config(tier: str = "ultra") -> Dict[str, Dict[str, Any]]:
    """Fallback station config if station_models.json is missing or corrupted."""
    source_models = ULTRA_STATION_MODELS if tier == "ultra" else PRO_STATION_MODELS
    result: Dict[str, Dict[str, Any]] = {}
    for role, model in source_models.items():
        effort = "xhigh" if "xhigh" in model else ("high" if "high" in model else None)
        result[role] = {
            "model": model,
            "effort": effort,
            "fork": "spec_writer" if role == "examiner" else None,
        }
    return result


def _parse_stations_dict(stations_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Parses raw stations dictionary resolving effort."""
    result: Dict[str, Dict[str, Any]] = {}
    for role, cfg in stations_data.items():
        if isinstance(cfg, dict):
            raw_model = cfg.get("model", "")
            effort = cfg.get("effort")
            fork = cfg.get("fork")
            final_model = apply_effort_to_model(raw_model, effort)
            result[role] = {
                "model": final_model,
                "effort": effort,
                "fork": fork,
            }
    return result


def _parse_ssot_file_stations(path: Path, tier: str) -> Optional[Dict[str, Dict[str, Any]]]:
    """Reads and parses stations from SSOT file path."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        tiers = data.get("tiers")
        if isinstance(tiers, dict):
            tier_entry = tiers.get(tier)
            if isinstance(tier_entry, dict):
                stations_data = tier_entry.get("stations")
                if isinstance(stations_data, dict) and stations_data:
                    return _parse_stations_dict(stations_data)
    except Exception:
        pass
    return None


def load_ssot_station_config(
    tier: str = "ultra",
    ssot_path: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Loads per-station configuration from declarative station_models.json SSOT template.
    Resolves apply_effort_to_model on each station entry.
    """
    path = ssot_path if ssot_path is not None else get_station_models_ssot_path()
    if path.is_file():
        parsed = _parse_ssot_file_stations(path, tier)
        if parsed:
            return parsed
    return _fallback_station_config(tier)


def _update_active_edge_tier_file(state_path: Path, role: str, model: str, tier: str) -> None:
    """Updates model entry in active edge_tier.json only if file exists and active tier matches."""
    if not state_path.is_file():
        return
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("tier") == tier and isinstance(data.get("station_models"), dict):
            data["station_models"][role] = model
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            _atomic_write_json(state_path, data)
    except Exception:
        pass


def _load_or_create_ssot_dict(ssot_file: Path) -> Dict[str, Any]:
    """Loads existing SSOT JSON or returns empty dict."""
    if ssot_file.is_file():
        try:
            with open(ssot_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _validate_role_and_effort(role: str, effort: Optional[str]) -> Tuple[bool, str]:
    """Validates station role and effort level."""
    if role not in PRO_STATION_MODELS:
        return False, f"❌ Invalid station role '{role}'. Canonical roles: {', '.join(sorted(PRO_STATION_MODELS.keys()))}"
    if effort and effort.strip().lower() not in VALID_EFFORT_LEVELS:
        return False, f"❌ Invalid effort level '{effort}'. Valid levels: {', '.join(VALID_EFFORT_LEVELS)}"
    return True, ""


def _get_ssot_tier_stations(ssot_data: Dict[str, Any], tier: str) -> Optional[Dict[str, Any]]:
    """Retrieves stations dict for tier from ssot_data if present."""
    tiers = ssot_data.get("tiers")
    if not isinstance(tiers, dict):
        return None
    tier_entry = tiers.get(tier)
    if not isinstance(tier_entry, dict):
        return None
    stations = tier_entry.get("stations")
    return stations if isinstance(stations, dict) else None


def set_station_model(
    role: str,
    model: str,
    effort: Optional[str] = None,
    tier: str = "ultra",
    ssot_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """
    Validates role and effort, computes final model via apply_effort_to_model,
    atomically updates station_models.json, and syncs active edge_tier.json when tier matches.
    """
    clean_role = role.strip().lower()
    clean_tier = tier.strip().lower()
    valid, err_msg = _validate_role_and_effort(clean_role, effort)
    if not valid:
        return False, err_msg

    final_model = apply_effort_to_model(model, effort)
    ssot_file = ssot_path if ssot_path is not None else get_station_models_ssot_path()
    ssot_data = _load_or_create_ssot_dict(ssot_file)

    stations = _get_ssot_tier_stations(ssot_data, clean_tier)
    if stations is None:
        return False, f"❌ Tier '{clean_tier}' not found in station_models.json"

    station_entry = stations.setdefault(clean_role, {})
    station_entry["model"] = final_model
    station_entry["effort"] = effort
    _atomic_write_json(ssot_file, ssot_data)

    target_state = state_path if state_path is not None else get_tier_state_path()
    _update_active_edge_tier_file(target_state, clean_role, final_model, clean_tier)

    effort_label = effort if effort else "none"
    msg = f"✅ Updated station '{clean_role}' to model '{final_model}' (effort: {effort_label}) for tier '{clean_tier}'"
    return True, msg


def _parse_cli_set_model_args(args: List[str]) -> Tuple[Optional[str], str]:
    """Parses optional --effort and --tier from CLI arguments."""
    effort = None
    tier = "ultra"
    for idx, arg in enumerate(args):
        if arg == "--effort" and idx + 1 < len(args):
            effort = args[idx + 1]
        elif arg == "--tier" and idx + 1 < len(args):
            tier = args[idx + 1]
    return effort, tier


def _cli_set_model() -> int:
    """Helper for CLI set-model command."""
    if len(sys.argv) < 4:
        print("Usage: tier.py set-model <role> <model> [--effort <low|medium|high|xhigh>] [--tier <pro|ultra>]")
        return 1

    role = sys.argv[2]
    model = sys.argv[3]
    effort, tier = _parse_cli_set_model_args(sys.argv[4:])

    ok, msg = set_station_model(role, model, effort=effort, tier=tier)
    print(msg)
    return 0 if ok else 1


def _parse_cli_switch_args(args: List[str]) -> Tuple[str, bool]:
    """Extracts optional repository path and --checkout flag for CLI switch."""
    checkout = "--checkout" in args
    positional = [a for a in args if a != "--checkout"]
    repo = positional[0] if positional else "."
    return repo, checkout


def _cli_switch() -> int:
    """Helper for CLI switch action to keep main() CC low."""
    if len(sys.argv) < 3:
        print("Error: switch requires target tier ('pro' or 'ultra')")
        return 1
    target_tier = sys.argv[2]
    repo, checkout = _parse_cli_switch_args(sys.argv[3:])
    success, msg, _ = switch_tier(repo, target_tier, checkout=checkout)
    print(msg)
    return 0 if success else 1


def main() -> int:
    """
    CLI interface for tier.py.
    Usage:
        python3 tools/brigade/tier.py status [repo]
        python3 tools/brigade/tier.py switch <pro|ultra> [repo] [--checkout]
        python3 tools/brigade/tier.py set-model <role> <model> [--effort <low|medium|high|xhigh>] [--tier <pro|ultra>]
    """
    if len(sys.argv) < 2:
        print("Usage: tier.py status [repo] | tier.py switch <pro|ultra> [repo] [--checkout] | tier.py set-model <role> <model>")
        return 1

    action = sys.argv[1].lower()
    if action == "status":
        repo = sys.argv[2] if len(sys.argv) > 2 else "."
        state = get_tier_status(repo)
        print(format_tier_card(state))
        return 0

    if action == "switch":
        return _cli_switch()

    if action == "set-model":
        return _cli_set_model()

    print(f"Unknown action '{action}'. Use 'status', 'switch', or 'set-model'.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
