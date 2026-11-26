"""Station reuse/rotation selector and invoke_subagent guard (stdlib-only)."""

from pathlib import Path
from typing import Any, Dict, Optional, Union

from tools.brigade.guard.role_detection import EPHEMERAL_GOLDFISH_ROLES, extract_requested_roles, normalize_role
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


def _handle_invoke_subagent_guard(args: Dict[str, Any], parent_cid: str) -> Dict[str, Any]:
    if is_browser_invocation(args):
        return {"decision": "allow", "reason": "AUXILIARY_TOOL_AGENT: Browser subagent invocation permitted"}
    st_file = effective_stations_file()
    store, scanner = StationStore(st_file), TranscriptStationScanner(st_file.parent / "brain")
    for req_role in extract_requested_roles(args):
        res = StationSelector.evaluate_spawn_request(store=store, scanner=scanner, parent_cid=parent_cid, requested_role=req_role)
        if res.get("decision") == "deny":
            return res
    return {"decision": "allow"}
