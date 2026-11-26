"""Tier constants, TierState dataclass, and atomic JSON helpers (stdlib-only)."""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any, Dict, Literal, Tuple

TierMode = Literal["pro", "ultra"]
VALID_TIERS: Tuple[str, str] = ("pro", "ultra")
VALID_EFFORT_LEVELS: Tuple[str, ...] = ("low", "medium", "high", "xhigh")
EFFORT_CAPABLE_FAMILIES: Tuple[str, ...] = (
    "gemini-4-hydrogen", "gemini-4-carbon", "gemini-4-argon",
    "claude-opus-5-5", "claude-sonnet-5-5", "gemini-3.8-flash",
)
PRO_BRANCH: str = "main"
ULTRA_BRANCH: str = "ultra"
PRO_TRANSPORT: str = "invoke_subagent"
ULTRA_TRANSPORT: str = "swarm"

PRO_STATION_MODELS: Dict[str, str] = {
    "spec_writer": "flash", "researcher": "flash", "spec_critic": "gemini-3.8-flash-high",
    "seam_architect": "flash", "coder": "flash", "surgeon": "flash",
    "examiner": "flash", "qa_engineer": "flash",
}
ULTRA_STATION_MODELS: Dict[str, str] = {
    "spec_writer": "gemini-4-hydrogen-high", "researcher": "gemini-4-hydrogen-high",
    "spec_critic": "claude-opus-5-5-high", "seam_architect": "gemini-4-hydrogen-xhigh",
    "coder": "gemini-4-hydrogen-high", "surgeon": "gemini-4-hydrogen-high",
    "examiner": "gemini-4-hydrogen-high", "qa_engineer": "gemini-4-hydrogen-medium",
}
STATION_DESCRIPTIONS: Dict[str, str] = {
    "spec_writer": "Specification Author & Slicer", "researcher": "Root Cause & Deep Explorer",
    "spec_critic": "Cross-Provider Spec Reviewer", "seam_architect": "Contract & RED Test Author",
    "coder": "GREEN Implementation Coder", "surgeon": "Refactoring Specialist",
    "examiner": "Standards & Invariants Examiner", "qa_engineer": "Visual & E2E Quality Assurance",
}


def default_branch(tier: str) -> str:
    """Return default git branch name for the given tier."""
    return ULTRA_BRANCH if tier == "ultra" else PRO_BRANCH


def default_transport(tier: str) -> str:
    """Return default agent transport for the given tier."""
    return ULTRA_TRANSPORT if tier == "ultra" else PRO_TRANSPORT


def parse_models(raw_models: Any, tier: str) -> Dict[str, str]:
    """Resolve station models dictionary with fallback to tier defaults."""
    if isinstance(raw_models, dict):
        return dict(raw_models)
    return dict(ULTRA_STATION_MODELS if tier == "ultra" else PRO_STATION_MODELS)


@dataclass
class TierState:
    """Serialized state snapshot for the active Edge execution tier."""

    tier: str
    branch: str
    transport: str
    station_models: Dict[str, str]
    updated_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TierState":
        tier = str(data.get("tier") or "pro")
        return cls(
            tier=tier,
            branch=str(data.get("branch") or default_branch(tier)),
            transport=str(data.get("transport") or default_transport(tier)),
            station_models=parse_models(data.get("station_models"), tier),
            updated_at=str(data.get("updated_at") or datetime.now(timezone.utc).isoformat()),
        )


def create_tier_state(tier: str, branch: str) -> TierState:
    """Construct a fresh TierState for tier and branch."""
    eff_tier = "ultra" if tier == "ultra" else "pro"
    return TierState(
        tier=eff_tier, branch=branch, transport=default_transport(eff_tier),
        station_models=parse_models(None, eff_tier), updated_at=datetime.now(timezone.utc).isoformat(),
    )


def get_tier_state_path() -> Path:
    """Resolve persistent tier state path (supports EDGE_TIER_STATE_PATH override)."""
    env_override = os.environ.get("EDGE_TIER_STATE_PATH")
    return Path(env_override) if env_override else Path.home() / ".gemini" / "antigravity" / "edge_tier.json"


def atomic_write_json(path: Path, data: Dict[str, Any]) -> None:
    """Atomically write JSON dict using <path>.tmp.<pid> + fsync + os.replace."""
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
