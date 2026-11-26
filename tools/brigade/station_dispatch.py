"""Station model resolution and swarm dispatch directive builder."""

from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from tools.brigade.models import StationRole, Ticket
from tools.brigade.tier_ssot import resolve_subagent_model
from tools.common.fs import atomic_write_text

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


def build_subagent_dispatch_directive(
    role: Union[StationRole, str],
    prompt: str,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Construct an invoke_subagent directive with a normalized Antigravity Model enum."""
    role_slug = role.value if isinstance(role, StationRole) else str(role).strip().lower()
    role_title = role_slug.replace("_", " ").title()
    raw_model = model or resolve_default_station_model(role_slug, tier="pro")
    return {
        "tool": "invoke_subagent",
        "TypeName": "self",
        "Model": resolve_subagent_model(raw_model),
        "Role": role_title,
        "Prompt": prompt,
    }


def build_spec_critic_dispatch(
    repo_path: Path,
    spec_path: Path,
    prompt: str,
    tier: Optional[str] = None,
    issue_number: Optional[int] = None,
) -> Tuple[str, Dict[str, Any], Path]:
    """Persist critic prompt to disk and build Ultra Swarm or Pro Subagent dispatch directive."""
    eff_tier = _resolve_effective_tier(tier)
    if issue_number is not None:
        prompt_file = repo_path / ".edge" / "cache" / "issues" / f"{int(issue_number)}-critic-prompt.md"
        report_hint = f".edge/cache/issues/{int(issue_number)}-critique.md"
    else:
        prompt_file = repo_path / ".edge" / "specs" / f"{spec_path.stem}-critic-prompt.md"
        report_hint = f".edge/specs/{spec_path.stem}-critique.md"
    atomic_write_text(prompt_file, prompt)
    brief = (
        f"Execute zero-context Spec Critic review for `{spec_path.name}`. "
        f"Read full rubric and specification prompt at `{prompt_file}` and write your <400-word critique to `{report_hint}`."
    )
    if eff_tier == "ultra":
        return "native_swarm", build_swarm_dispatch_directive("spec_critic", brief), prompt_file
    return "native_subagent", build_subagent_dispatch_directive("spec_critic", brief), prompt_file
