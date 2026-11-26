"""Station model resolution and swarm dispatch directive builder."""

from pathlib import Path
from typing import Any, Dict, Union, Optional

from tools.brigade.models import StationRole, Ticket

_GENERIC_DOMAINS = frozenset({"general", "core", "ui", "feature"})


def _resolve_target_label(ticket: Ticket) -> str:
    if ticket.target_file:
        return ticket.target_file
    if getattr(ticket, "expected_files", None):
        return ", ".join(ticket.expected_files)
    return "(dynamic-slice)"


def _resolve_stage_target(ticket: Ticket) -> str:
    if ticket.target_file:
        return ticket.target_file
    if getattr(ticket, "expected_files", None):
        return " ".join(ticket.expected_files)
    return "-u"


def _resolve_effective_tier(tier: Optional[str]) -> str:
    """Resolves active brigade tier via explicit parameter or edge_tier.json status."""
    if tier and str(tier).strip():
        return str(tier).strip().lower()
    try:
        from tools.brigade.tier import get_tier_status
        return str(get_tier_status(Path.cwd()).tier).strip().lower() or "pro"
    except Exception:
        return "pro"


def _lookup_ssot_entry(role_slug: str, eff_tier: str) -> Dict[str, Any]:
    """Queries station_models.json SSOT entry for role_slug and tier."""
    try:
        from tools.brigade.tier import load_ssot_station_config
        cfg = load_ssot_station_config(eff_tier)
        entry = cfg.get(role_slug)
        if isinstance(entry, dict):
            return entry
    except Exception:
        pass
    return {}


def resolve_default_station_model(
    role: Union[StationRole, str],
    tier: Optional[str] = None,
) -> str:
    """
    Resolves the default model for a station role using station_models.json SSOT
    and tier.py's static station model tables (zero duplicate fallback dict).
    """
    role_slug = role.value if isinstance(role, StationRole) else str(role).strip().lower()
    eff_tier = _resolve_effective_tier(tier)

    entry = _lookup_ssot_entry(role_slug, eff_tier)
    if entry.get("model"):
        return str(entry["model"])

    try:
        from tools.brigade.tier import PRO_STATION_MODELS, ULTRA_STATION_MODELS
        models = ULTRA_STATION_MODELS if eff_tier == "ultra" else PRO_STATION_MODELS
        default_model = "gemini-4-hydrogen-high" if eff_tier == "ultra" else "flash"
        return models.get(role_slug, default_model)
    except ImportError:
        return "gemini-4-hydrogen-high" if eff_tier == "ultra" else "flash"


def build_swarm_dispatch_directive(
    role: Union[StationRole, str],
    brief: str,
    fork: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Constructs a ready-to-call swarm tool directive dictionary for station addition,
    attaching SSOT model and fork metadata (e.g. examiner -> spec_writer).
    """
    role_slug = role.value if isinstance(role, StationRole) else str(role).strip().lower()
    resolved_model = model or resolve_default_station_model(role_slug, tier="ultra")

    eff_fork = fork
    if eff_fork is None:
        ssot_fork = _lookup_ssot_entry(role_slug, "ultra").get("fork")
        eff_fork = str(ssot_fork) if ssot_fork else None

    directive: Dict[str, Any] = {
        "action": "add",
        "name": role_slug,
        "model": resolved_model,
        "brief": brief,
    }
    if eff_fork:
        directive["fork"] = eff_fork
    return directive
