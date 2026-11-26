"""Ultra Swarm daemon ban and post-tool station sync (stdlib-only)."""

from datetime import datetime, timezone
import re
import sys
from typing import Any, Dict, Optional

from tools.brigade.guard.role_detection import attach_station_token, normalize_role
from tools.brigade.guard.station_candidates import is_active_station_for_role
from tools.brigade.guard.station_store import load_active_stations, register_station, save_active_stations
from tools.brigade.guard.swarm_ssot import (
    resolve_swarm_canonical_role,
    resolve_swarm_default_model,
    resolve_swarm_ssot_preload as _resolve_swarm_ssot_preload,
)
from tools.brigade.guard.transcript_scanner import sync_repo_brigade_station


def _handle_swarm_guard(args: Dict[str, Any], parent_cid: str) -> Optional[Dict[str, Any]]:
    """Deny narrator/monitor daemons and auto-preload SSOT station config."""
    if str(args.get("action", "")).strip().lower() != "add":
        return {"decision": "allow"}
    raw_name = str(args.get("name", "")).strip().lower()
    base_name = re.sub(r"-\d+$", "", raw_name)
    if base_name in ("narrator", "monitor"):
        return {"decision": "deny", "reason": "❌ [EDGE SWARM DAEMON BAN]: Spawning narrator or monitor daemons is strictly prohibited to conserve quota."}
    overwritten = _resolve_swarm_ssot_preload(raw_name, args)
    canonical = normalize_role(base_name) or base_name.upper()
    if "brief" in args and canonical:
        merged = dict(overwritten) if overwritten is not None else dict(args)
        merged["brief"] = attach_station_token(str(merged.get("brief") or ""), canonical)
        return {"decision": "allow", "overwrite": merged}
    return {"decision": "allow", "overwrite": overwritten} if overwritten is not None else {"decision": "allow"}


def _update_swarm_station_records(raw_name: str, parent_cid: str, field_name: str, field_value: str) -> Optional[str]:
    facade = sys.modules.get("tools.brigade.orchestrator_guard")
    loader = getattr(facade, "load_active_stations", load_active_stations) if facade else load_active_stations
    saver = getattr(facade, "save_active_stations", save_active_stations) if facade else save_active_stations
    canonical = resolve_swarm_canonical_role(raw_name)
    envelope = loader()
    now_iso = datetime.now(timezone.utc).isoformat()
    matched_cid: Optional[str] = None
    for cid, info in envelope.get_stations().items():
        if is_active_station_for_role(info, canonical, parent_cid):
            info[field_name], info["lastActiveAt"] = field_value, now_iso
            matched_cid = matched_cid or cid
    if matched_cid is not None:
        saver(envelope)
    return matched_cid


def _handle_swarm_post_tool(
    payload: Dict[str, Any], args: Dict[str, Any], parent_cid: str,
    extract_cid_fn: Any = None, fallback_cid_fn: Any = None, resolve_repo_fn: Any = None,
) -> None:
    if extract_cid_fn is None or fallback_cid_fn is None or resolve_repo_fn is None:
        from tools.brigade.guard.transcript_cid import extract_cid_from_payload, extract_cid_from_transcript_fallback
        from tools.brigade.guard.post_tool import _resolve_repo_candidate
        extract_cid_fn = extract_cid_fn or extract_cid_from_payload
        fallback_cid_fn = fallback_cid_fn or extract_cid_from_transcript_fallback
        resolve_repo_fn = resolve_repo_fn or _resolve_repo_candidate
    action, raw_name = str(args.get("action", "")).strip().lower(), str(args.get("name", "")).strip().lower()
    if not raw_name:
        return
    rp = resolve_repo_fn(payload)
    if action == "add":
        cid = extract_cid_fn(payload) or (fallback_cid_fn(payload["transcriptPath"], expected_tool="swarm") if payload.get("transcriptPath") else None) or f"swarm:{raw_name}"
        model = str(args.get("model") or resolve_swarm_default_model(raw_name))
        register_station(cid, raw_name, parent_cid, model=model)
        if rp:
            sync_repo_brigade_station(rp, raw_name, cid, model=model)
    elif action == "model":
        new_model = str(args.get("model") or "").strip()
        matched = _update_swarm_station_records(raw_name, parent_cid, "model", new_model) if new_model else None
        if rp and matched:
            sync_repo_brigade_station(rp, raw_name, matched, model=new_model)
    elif action == "kill":
        _update_swarm_station_records(raw_name, parent_cid, "status", "TERMINATED")
