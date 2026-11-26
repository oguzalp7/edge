#!/usr/bin/env python3
"""
Deterministic TranscriptGraphHarvester for edge-distill v2.
Traverses Antigravity session transcripts, reconstructs parent-child station graphs,
and extracts zero-token signals (station escapes, tool friction, user escalations, flight recorder).
"""

import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.distill.harvester_discovery import default_brain_roots, discover_candidates
from tools.distill.harvester_harness import _enqueue_harness_signals, _split_single_signal_list
from tools.distill.harvester_runner import (
    build_friction_digest,
    collect_navigation_signals,
    collect_signals,
    filter_sessions,
    find_matched_sessions,
    inspect_step_relations,
    is_session_skipped,
    load_transcripts_graph,
)
from tools.distill.models import (
    DistillWatermarkState,
    FrictionDigest,
    NavigationFrictionSignal,
    RepeatedEscalation,
    StationEscapeSignal,
    ToolFrictionSignal,
)
from tools.distill.state import FactoryInbox

_HELPER_MODULES = (
    "tools.distill.harvester_signals",
    "tools.distill.harvester_escapes",
    "tools.distill.harvester_nav_cmds",
    "tools.distill.harvester_nav_reads",
    "tools.distill.harvester_nav_search",
    "tools.distill.harvester_guardrails",
    "tools.distill.harvester_matching",
    "tools.distill.harvester_tasks",
    "tools.distill.harvester_graph",
    "tools.distill.harvester_harness",
    "tools.distill.harvester_roles",
)


def __getattr__(name: str) -> Any:
    for mod_name in _HELPER_MODULES:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, name):
            val = getattr(mod, name)
            globals()[name] = val
            return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class TranscriptGraphHarvester:
    """Deterministic Harvester extracting zero-token friction and signals from transcripts."""

    def __init__(
        self,
        repo_path: Optional[Path] = None,
        brain_roots: Optional[List[Path]] = None,
        active_stations_file: Optional[Path] = None,
        watermark_state: Optional[DistillWatermarkState] = None,
        since_hours: Optional[int] = None,
    ):
        self.repo_path = repo_path.resolve() if repo_path else None
        self.brain_roots = [p.resolve() for p in brain_roots] if brain_roots else default_brain_roots()
        self.active_stations_file = active_stations_file.resolve() if active_stations_file else None
        self.watermark_state = watermark_state or DistillWatermarkState()
        self.since_hours = since_hours
        self._session_dirs: Dict[str, Path] = {}
        self._session_roles: Dict[str, str] = {}
        self._session_role_priority: Dict[str, int] = {}

    def _set_session_role(self, cid: str, role: str, priority: int) -> None:
        if cid and role and role != "unknown" and priority >= self._session_role_priority.get(cid, 0):
            self._session_roles[cid] = role
            self._session_role_priority[cid] = priority

    def _discover_candidates(self) -> List[Path]:
        return discover_candidates(self.brain_roots, self.since_hours)

    def _discover_transcripts(self) -> Dict[str, Path]:
        session_transcripts: Dict[str, Path] = {}
        for sess_dir in self._discover_candidates():
            tfile = sess_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if tfile.exists():
                session_transcripts[sess_dir.name] = tfile
                self._session_dirs[sess_dir.name] = sess_dir
        return session_transcripts

    def _inspect_step_relations(
        self,
        steps: List[Dict[str, Any]],
        cid: str,
        child_to_parent: Dict[str, str],
        parent_to_children: Dict[str, List[str]],
        discovered_sessions: Optional[Set[str]] = None,
    ) -> None:
        inspect_step_relations(steps, cid, child_to_parent, parent_to_children, self._set_session_role, discovered_sessions)

    def _load_transcripts(
        self, session_transcripts: Dict[str, Path]
    ) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], Dict[str, List[str]]]:
        return load_transcripts_graph(session_transcripts, self.active_stations_file, self._set_session_role)

    def _find_matched_sessions(
        self, sessions_steps: Dict[str, List[Dict[str, Any]]], target_path: Path,
        parent_to_children: Dict[str, List[str]], child_to_parent: Dict[str, str],
    ) -> Set[str]:
        return find_matched_sessions(sessions_steps, target_path, parent_to_children, child_to_parent)

    def _is_session_skipped(self, cid: str, current_session_id: Optional[str], reprocess: bool, mode: str, target_path: Optional[Path]) -> bool:
        return is_session_skipped(self.watermark_state, cid, current_session_id, reprocess, mode, target_path)

    def _filter_sessions(
        self, matched: Set[str], current_session_id: Optional[str], reprocess: bool,
        max_sessions: int, available: Set[str], mode: str = "all", target_path: Optional[Path] = None,
    ) -> List[str]:
        return filter_sessions(self.watermark_state, matched, current_session_id, reprocess, max_sessions, available, mode, target_path)

    def _collect_signals(
        self, analyzed_sessions: List[str], sessions_steps: Dict[str, List[Dict[str, Any]]]
    ) -> Tuple[List[ToolFrictionSignal], List[StationEscapeSignal], List[RepeatedEscalation]]:
        return collect_signals(analyzed_sessions, sessions_steps, self._session_dirs)

    def _collect_navigation_signals(
        self, analyzed_sessions: List[str], sessions_steps: Dict[str, List[Dict[str, Any]]]
    ) -> List[NavigationFrictionSignal]:
        return collect_navigation_signals(analyzed_sessions, sessions_steps, self._session_roles)

    def _split_project_signals(
        self, frictions_or_signals: Any, escapes: Optional[List[StationEscapeSignal]] = None,
        target_path: Optional[Path] = None, project_name: Optional[str] = None,
    ) -> Any:
        if escapes is None:
            return _split_single_signal_list(frictions_or_signals)
        proj_f, harness_f = _split_single_signal_list(frictions_or_signals)
        proj_e, harness_e = _split_single_signal_list(escapes)
        return proj_f, proj_e, _enqueue_harness_signals(harness_f, harness_e, target_path)

    def harvest(
        self, project_path: Optional[Path] = None, reprocess: bool = False,
        current_session_id: Optional[str] = None, max_sessions: int = 50, mode: str = "all",
    ) -> FrictionDigest:
        target_path = (project_path or self.repo_path or Path.cwd()).resolve()
        transcripts = self._discover_transcripts()
        sessions_steps, c2p, p2c = self._load_transcripts(transcripts)
        matched = self._find_matched_sessions(sessions_steps, target_path, p2c, c2p)
        analyzed = self._filter_sessions(matched, current_session_id, reprocess, max_sessions, set(transcripts.keys()), mode=mode, target_path=target_path)
        frictions, escapes, escalations = self._collect_signals(analyzed, sessions_steps)
        nav_frictions = self._collect_navigation_signals(analyzed, sessions_steps)
        harness_queued, inbox_signals = 0, []
        if mode == "project":
            frictions, escapes, harness_queued = self._split_project_signals(frictions, escapes, target_path)
        elif mode == "factory":
            inbox_signals = FactoryInbox().load_pending()
        return build_friction_digest(target_path, analyzed, sessions_steps, frictions, escapes, escalations, nav_frictions, harness_queued, inbox_signals, mode)
