"""
Execution helpers for TranscriptGraphHarvester orchestration methods.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from tools.distill.harvester_artifacts import extract_critiques, extract_flight_recorder, extract_git_churn
from tools.distill.harvester_discovery import link_parent_sender, link_step_invoke_roles, load_active_stations_map
from tools.distill.harvester_escapes import (
    _estimate_sessions_tokens,
    _extract_repeated_escalations,
    _extract_station_escapes_from_steps,
)
from tools.distill.harvester_graph import _append_unique_child, _expand_connected_session_graph, _load_jsonl_steps
from tools.distill.harvester_guardrails import _extract_guardrail_gaps, _extract_rule_inventory
from tools.distill.harvester_harness import _enqueue_harness_signals, _split_single_signal_list
from tools.distill.harvester_matching import _collect_worktree_aliases, _session_matches_project
from tools.distill.harvester_nav_search import _extract_navigation_frictions_from_steps
from tools.distill.harvester_roles import _CID_RE
from tools.distill.harvester_signals import _extract_tool_frictions_from_steps
from tools.distill.harvester_tasks import _extract_background_task_hangs
from tools.distill.models import (
    DistillWatermarkState,
    FrictionDigest,
    NavigationFrictionSignal,
    RepeatedEscalation,
    StationEscapeSignal,
    ToolFrictionSignal,
)
from tools.distill.state import FactoryInbox


def link_content_cids(
    step: Dict[str, Any], cid: str, child_to_parent: Dict[str, str], parent_to_children: Dict[str, List[str]]
) -> None:
    for m in _CID_RE.finditer(str(step.get("content", ""))):
        child_cid = m.group(1)
        if child_cid and child_cid != cid:
            child_to_parent[child_cid] = cid
            _append_unique_child(parent_to_children, cid, child_cid)


def inspect_step_relations(
    steps: List[Dict[str, Any]],
    cid: str,
    child_to_parent: Dict[str, str],
    parent_to_children: Dict[str, List[str]],
    set_role_fn: Callable[[str, str, int], None],
    discovered_sessions: Optional[Set[str]] = None,
) -> None:
    for idx, step in enumerate(steps):
        link_step_invoke_roles(steps, idx, cid, child_to_parent, parent_to_children, set_role_fn)
        link_content_cids(step, cid, child_to_parent, parent_to_children)
    link_parent_sender(steps, cid, child_to_parent, parent_to_children, discovered_sessions, set_role_fn)


def load_transcripts_graph(
    session_transcripts: Dict[str, Path],
    active_stations_file: Optional[Path],
    set_role_fn: Callable[[str, str, int], None],
) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], Dict[str, List[str]]]:
    sessions_steps: Dict[str, List[Dict[str, Any]]] = {}
    child_to_parent = load_active_stations_map(active_stations_file, set_role_fn)
    parent_to_children: Dict[str, List[str]] = {}
    for child_cid, parent_cid in child_to_parent.items():
        _append_unique_child(parent_to_children, parent_cid, child_cid)
    discovered = set(session_transcripts.keys())
    for cid, tpath in session_transcripts.items():
        steps = _load_jsonl_steps(tpath)
        sessions_steps[cid] = steps
        inspect_step_relations(steps, cid, child_to_parent, parent_to_children, set_role_fn, discovered)
    return sessions_steps, child_to_parent, parent_to_children


def find_matched_sessions(
    sessions_steps: Dict[str, List[Dict[str, Any]]],
    target_path: Path,
    parent_to_children: Dict[str, List[str]],
    child_to_parent: Dict[str, str],
) -> Set[str]:
    aliases = _collect_worktree_aliases(target_path)
    matched = {cid for cid, steps in sessions_steps.items() if _session_matches_project(steps, target_path, extra_project_paths=aliases)}
    return _expand_connected_session_graph(matched, parent_to_children, child_to_parent)


def is_session_skipped(
    watermark_state: DistillWatermarkState,
    cid: str,
    current_session_id: Optional[str],
    reprocess: bool,
    mode: str,
    target_path: Optional[Path],
) -> bool:
    if reprocess or current_session_id == cid:
        return False
    if mode == "factory":
        return cid in watermark_state.factory_processed_sessions
    if mode == "project":
        p_sessions = watermark_state.project_sessions.get(str(target_path), []) if target_path else []
        return cid in p_sessions or cid in watermark_state.processed_sessions
    return cid in watermark_state.processed_sessions


def filter_sessions(
    watermark_state: DistillWatermarkState,
    matched: Set[str],
    current_session_id: Optional[str],
    reprocess: bool,
    max_sessions: int,
    available: Set[str],
    mode: str = "all",
    target_path: Optional[Path] = None,
) -> List[str]:
    analyzed = [
        cid for cid in sorted(matched)
        if not is_session_skipped(watermark_state, cid, current_session_id, reprocess, mode, target_path)
    ][:max_sessions]
    if current_session_id and current_session_id not in analyzed and current_session_id in available:
        analyzed.append(current_session_id)
    return analyzed


def collect_signals(
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
    session_dirs: Dict[str, Path],
) -> Tuple[List[ToolFrictionSignal], List[StationEscapeSignal], List[RepeatedEscalation]]:
    tool_frictions: List[ToolFrictionSignal] = []
    station_escapes: List[StationEscapeSignal] = []
    flattened_steps: List[Dict[str, Any]] = []
    for cid in analyzed_sessions:
        steps = sessions_steps.get(cid, [])
        tool_frictions.extend(_extract_tool_frictions_from_steps(cid, steps))
        tool_frictions.extend(_extract_background_task_hangs(steps, session_dirs.get(cid), cid))
        station_escapes.extend(_extract_station_escapes_from_steps(cid, steps))
        flattened_steps.extend({"cid": cid, "step": s} for s in steps)
    return tool_frictions, station_escapes, _extract_repeated_escalations(flattened_steps)


def collect_navigation_signals(
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
    session_roles: Dict[str, str],
) -> List[NavigationFrictionSignal]:
    nav_signals: List[NavigationFrictionSignal] = []
    for cid in analyzed_sessions:
        nav_signals.extend(_extract_navigation_frictions_from_steps(cid, sessions_steps.get(cid, []), role=session_roles.get(cid, "unknown")))
    return nav_signals


def build_friction_digest(
    target_path: Path,
    analyzed: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
    frictions: List[ToolFrictionSignal],
    escapes: List[StationEscapeSignal],
    escalations: List[RepeatedEscalation],
    nav_frictions: List[NavigationFrictionSignal],
    harness_queued: int,
    inbox_signals: List[Dict[str, Any]],
    mode: str,
) -> FrictionDigest:
    return FrictionDigest(
        digest_id=f"DIGEST-{target_path.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        project_path=str(target_path),
        project_name=target_path.name,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sessions_analyzed=analyzed,
        station_escapes=escapes,
        tool_frictions=frictions,
        repeated_escalations=escalations,
        flight_recorder_insights=extract_flight_recorder(target_path),
        git_churn=extract_git_churn(target_path),
        critique_findings=extract_critiques(target_path),
        total_tokens_estimate=_estimate_sessions_tokens(analyzed, sessions_steps),
        harness_signals_queued=harness_queued,
        factory_inbox_signals=inbox_signals,
        navigation_frictions=nav_frictions,
        guardrail_gaps=_extract_guardrail_gaps(target_path),
        rule_inventory=_extract_rule_inventory(target_path, analyzed, sessions_steps, mode=mode),
    )
