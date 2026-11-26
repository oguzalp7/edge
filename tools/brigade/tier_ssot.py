"""Station model SSOT configuration loading and updates (stdlib-only)."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Optional, Tuple

from tools.brigade.tier_models import (
    EFFORT_CAPABLE_FAMILIES,
    PRO_STATION_MODELS,
    ULTRA_STATION_MODELS,
    VALID_EFFORT_LEVELS,
    atomic_write_json,
    get_tier_state_path,
    parse_models,
)


_NATIVE_SUBAGENT_MODELS = frozenset({"inherit", "flash", "flash_lite", "pro"})


def resolve_subagent_model(model_name: str) -> str:
    """Map an arbitrary station or custom model name to Antigravity's invoke_subagent Model enum."""
    clean = (model_name or "").strip().lower()
    if clean in _NATIVE_SUBAGENT_MODELS:
        return clean
    if "lite" in clean:
        return "flash_lite"
    if "flash" in clean:
        return "flash"
    if any(tok in clean for tok in ("opus", "sonnet", "xhigh", "high", "pro")):
        return "pro"
    return "flash"


def get_station_models_ssot_path() -> Path:
    """Resolve path for station_models.json SSOT template."""
    env_override = os.environ.get("EDGE_STATION_MODELS_PATH")
    return Path(env_override) if env_override else Path(__file__).resolve().parent / "station_models.json"


def apply_effort_to_model(model: str, effort: Optional[str] = None) -> str:
    """Normalize or append reasoning effort suffix on effort-capable model identifiers."""
    if not effort:
        return model
    clean_effort = effort.strip().lower()
    if clean_effort not in VALID_EFFORT_LEVELS:
        return model
    suffix_match = re.search(r"-(low|medium|high|xhigh)$", model)
    if suffix_match:
        return model[: suffix_match.start()] + f"-{clean_effort}"
    return f"{model}-{clean_effort}" if any(fam in model for fam in EFFORT_CAPABLE_FAMILIES) else model


def _fallback_station_config(tier: str = "ultra") -> Dict[str, Dict[str, Any]]:
    source_models = ULTRA_STATION_MODELS if tier == "ultra" else PRO_STATION_MODELS
    out: Dict[str, Dict[str, Any]] = {}
    for role, model in source_models.items():
        effort = "xhigh" if "xhigh" in model else ("high" if "high" in model else None)
        out[role] = {"model": model, "effort": effort, "fork": "spec_writer" if role == "examiner" else None}
    return out


def _parse_stations_dict(stations_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for role, cfg in stations_data.items():
        if isinstance(cfg, dict):
            effort = cfg.get("effort")
            out[role] = {"model": apply_effort_to_model(cfg.get("model", ""), effort), "effort": effort, "fork": cfg.get("fork")}
    return out


def _parse_ssot_file_stations(path: Path, tier: str) -> Optional[Dict[str, Dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    tiers = data.get("tiers") if isinstance(data, dict) else None
    tier_entry = tiers.get(tier) if isinstance(tiers, dict) else None
    stations_data = tier_entry.get("stations") if isinstance(tier_entry, dict) else None
    return _parse_stations_dict(stations_data) if (isinstance(stations_data, dict) and stations_data) else None


def load_ssot_station_config(tier: str = "ultra", ssot_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Load per-station configuration from station_models.json SSOT with fallback defaults."""
    path = ssot_path if ssot_path is not None else get_station_models_ssot_path()
    parsed = _parse_ssot_file_stations(path, tier) if path.is_file() else None
    return parsed if parsed else _fallback_station_config(tier)


def resolve_ssot_tier_models(tier_clean: str) -> Dict[str, str]:
    """Resolve station -> model mapping from SSOT config with static defaults."""
    ssot_cfg = load_ssot_station_config(tier_clean)
    models = {r: str(cfg["model"]) for r, cfg in ssot_cfg.items() if isinstance(cfg, dict) and cfg.get("model")}
    return models if models else parse_models(None, tier_clean)


def _update_active_edge_tier_file(state_path: Path, role: str, model: str, tier: str) -> None:
    if not state_path.is_file():
        return
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if isinstance(data, dict) and data.get("tier") == tier and isinstance(data.get("station_models"), dict):
        data["station_models"][role] = model
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        atomic_write_json(state_path, data)


def _validate_role_and_effort(role: str, effort: Optional[str]) -> Tuple[bool, str]:
    if role not in PRO_STATION_MODELS:
        return False, f"❌ Invalid station role '{role}'. Canonical roles: {', '.join(sorted(PRO_STATION_MODELS.keys()))}"
    if effort and effort.strip().lower() not in VALID_EFFORT_LEVELS:
        return False, f"❌ Invalid effort level '{effort}'. Valid levels: {', '.join(VALID_EFFORT_LEVELS)}"
    return True, ""


def set_station_model(
    role: str, model: str, effort: Optional[str] = None, tier: str = "ultra",
    ssot_path: Optional[Path] = None, state_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Validate and persist a station model override in station_models.json and edge_tier.json."""
    clean_role, clean_tier = role.strip().lower(), tier.strip().lower()
    valid, err_msg = _validate_role_and_effort(clean_role, effort)
    if not valid:
        return False, err_msg
    final_model = apply_effort_to_model(model, effort)
    ssot_file = ssot_path if ssot_path is not None else get_station_models_ssot_path()
    try:
        ssot_data = json.loads(ssot_file.read_text(encoding="utf-8")) if ssot_file.is_file() else {}
    except Exception:
        ssot_data = {}
    tiers = ssot_data.get("tiers") if isinstance(ssot_data, dict) else None
    tier_entry = tiers.get(clean_tier) if isinstance(tiers, dict) else None
    stations = tier_entry.get("stations") if isinstance(tier_entry, dict) else None
    if not isinstance(stations, dict):
        return False, f"❌ Tier '{clean_tier}' not found in station_models.json"
    entry = stations.setdefault(clean_role, {})
    entry["model"], entry["effort"] = final_model, effort
    atomic_write_json(ssot_file, ssot_data)
    _update_active_edge_tier_file(state_path if state_path is not None else get_tier_state_path(), clean_role, final_model, clean_tier)
    return True, f"✅ Updated station '{clean_role}' to model '{final_model}' (effort: {effort or 'none'}) for tier '{clean_tier}'"
