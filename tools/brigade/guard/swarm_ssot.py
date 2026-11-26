"""Ultra Swarm SSOT model/fork preload configuration helpers (stdlib-only)."""

import re
from typing import Any, Dict, Optional

from tools.brigade.guard.role_detection import normalize_role


def load_ultra_ssot_config() -> Dict[str, Any]:
    """Load ultra-tier SSOT station defaults lazily from tools.brigade.tier."""
    try:
        from tools.brigade.tier import load_ssot_station_config
        return load_ssot_station_config("ultra")
    except Exception:
        return {}


def _resolve_preload_model(current_model: Any, target_effort: Any, entry: Dict[str, Any]) -> Optional[str]:
    from tools.brigade.tier import apply_effort_to_model
    ssot_model = entry.get("model")
    if not current_model and ssot_model:
        return apply_effort_to_model(ssot_model, target_effort) if target_effort else ssot_model
    if current_model and target_effort:
        applied = apply_effort_to_model(str(current_model), target_effort)
        return applied if applied != str(current_model) else None
    return None


def resolve_swarm_canonical_role(raw_name: str) -> str:
    """Normalize shard-suffixed swarm worker names (e.g. coder-1) to canonical roles."""
    base_name = re.sub(r"-\d+$", "", raw_name.strip().lower())
    return normalize_role(base_name) or base_name.upper()


def resolve_swarm_default_model(raw_name: str) -> str:
    """Resolve SSOT fallback model for a swarm worker name."""
    entry = load_ultra_ssot_config().get(resolve_swarm_canonical_role(raw_name).lower())
    return str(entry["model"]) if isinstance(entry, dict) and entry.get("model") else "gemini-4-hydrogen-high"


def resolve_swarm_ssot_preload(raw_name: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Auto-preload SSOT model, effort, and fork onto swarm add calls when omitted."""
    if not args.get("brief"):
        return None
    base_name = re.sub(r"-\d+$", "", raw_name.strip().lower())
    entry = load_ultra_ssot_config().get((normalize_role(base_name) or base_name).lower())
    if not entry:
        return None
    overwritten = dict(args)
    new_model = _resolve_preload_model(args.get("model"), args.get("effort"), entry)
    fork = entry.get("fork")
    modified = False
    if new_model:
        overwritten["model"], modified = new_model, True
    if fork and not args.get("fork"):
        overwritten["fork"], modified = fork, True
    return overwritten if modified else None
