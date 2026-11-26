"""Station reuse/rotation selector and invoke_subagent guard (stdlib-only)."""

from pathlib import Path
from typing import Any, Dict, Optional, Union

from tools.brigade.guard.role_detection import EPHEMERAL_GOLDFISH_ROLES, attach_station_token, extract_requested_roles, normalize_role
from tools.brigade.guard.station_candidates import (
    collect_repo_candidates,
    collect_session_candidates,
    is_active_station_for_role as _is_active_station_for_role,
    is_auxiliary_tool_agent,
    is_browser_invocation,
)
from tools.brigade.guard.station_models import GREEN_HEAT_THRESHOLD
from tools.brigade.guard.station_store import StationStore, effective_stations_file
from tools.brigade.guard.transcript_scanner import TranscriptStationScanner

_VALID_SUBAGENT_ENUMS = frozenset({"inherit", "flash", "flash_lite", "pro"})


def _format_reuse_deny(canonical: str, gcid: str, gtok: int) -> Dict[str, str]:
    return {
        "decision": "deny",
        "reason": (
            f"❌ [PERSISTENT STATION REUSE REQUIRED]: An active, healthy station worker for role '{canonical}' "
            f"already exists in this session (conversationId: '{gcid}', heat: GREEN, {gtok} tokens).\n\n"
            f"🛑 ANTI-GRAVEYARD PROTOCOL ENFORCED:\n"
            f"Do NOT call `invoke_subagent` to spawn duplicate subagents!\n"
            f"You must reuse the existing persistent station worker by sending your task package via:\n"
            f'`send_message(Recipient: "{gcid}", Message: ...)`'
        ),
    }


def _rotate_ephemeral_stations(store: StationStore, stations: Dict[str, Any], canonical: str, parent_cid: str) -> None:
    for cid, info in stations.items():
        if _is_active_station_for_role(info, canonical, parent_cid):
            store.mark_rotated(cid)


class StationSelector:
    """Evaluates whether an invoke_subagent call can spawn or must reuse a station."""

    @staticmethod
    def evaluate_spawn_request(
        store: StationStore, scanner: TranscriptStationScanner, parent_cid: str,
        requested_role: str, repo_path: Optional[Union[Path, str]] = None,
    ) -> Dict[str, str]:
        if is_auxiliary_tool_agent(requested_role):
            return {"decision": "allow", "reason": "AUXILIARY_TOOL_AGENT: Browser subagent invocation permitted"}
        canonical = normalize_role(requested_role) or requested_role.strip().upper()
        stations = store.load().get_stations()
        if canonical in EPHEMERAL_GOLDFISH_ROLES:
            _rotate_ephemeral_stations(store, stations, canonical, parent_cid)
            return {"decision": "allow", "reason": f"GOLDFISH_EPHEMERAL: Fresh zero-context {canonical} spawn permitted"}
        candidates = collect_session_candidates(stations, canonical, parent_cid, scanner) or collect_repo_candidates(repo_path, canonical, scanner)
        if not candidates:
            return {"decision": "allow"}
        green = [c for c in candidates if c[2] < GREEN_HEAT_THRESHOLD and c[3] == "GREEN"]
        if green:
            gcid, _, gtok, _ = min(green, key=lambda c: c[2])
            return _format_reuse_deny(canonical, gcid, gtok)
        for cid, _, _, _ in candidates:
            store.mark_exhausted(cid)
        return {"decision": "allow", "reason": "ROTATION: Worker saturated"}


def _normalize_subagent_model(args: Dict[str, Any], role: str, overwritten: Dict[str, Any]) -> bool:
    model_key = "model" if ("model" in args and "Model" not in args) else "Model"
    raw_model = str(args.get(model_key) or "").strip()
    if raw_model.lower() in _VALID_SUBAGENT_ENUMS:
        return False
    from tools.brigade.station_dispatch import resolve_default_station_model
    from tools.brigade.tier_ssot import resolve_subagent_model

    fallback_model = raw_model or resolve_default_station_model(role, tier="pro")
    overwritten[model_key] = resolve_subagent_model(fallback_model)
    return True


def _normalize_subagent_overwrite(args: Dict[str, Any], roles: list[str]) -> Optional[Dict[str, Any]]:
    if not roles:
        return None
    overwritten = dict(args)
    changed = False
    if "Prompt" in args or "prompt" in args:
        prompt_key = "Prompt" if "Prompt" in args else "prompt"
        canonical = normalize_role(roles[0]) or roles[0].strip().upper()
        overwritten[prompt_key] = attach_station_token(str(args.get(prompt_key) or ""), canonical)
        changed = True
    if _normalize_subagent_model(args, roles[0], overwritten):
        changed = True
    return overwritten if changed else None


def _handle_invoke_subagent_guard(args: Dict[str, Any], parent_cid: str) -> Dict[str, Any]:
    if is_browser_invocation(args):
        return {"decision": "allow", "reason": "AUXILIARY_TOOL_AGENT: Browser subagent invocation permitted"}
    st_file = effective_stations_file()
    store, scanner = StationStore(st_file), TranscriptStationScanner(st_file.parent / "brain")
    roles = extract_requested_roles(args)
    for req_role in roles:
        res = StationSelector.evaluate_spawn_request(store=store, scanner=scanner, parent_cid=parent_cid, requested_role=req_role)
        if res.get("decision") == "deny":
            return res
    overwritten = _normalize_subagent_overwrite(args, roles)
    return {"decision": "allow", "overwrite": overwritten} if overwritten is not None else {"decision": "allow"}
