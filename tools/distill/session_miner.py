#!/usr/bin/env python3
"""
Antigravity Transcript Miner & Architectural Intent Analyzer.
Part of the edge-distill toolset (tools/distill/session_miner.py).
"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from tools.distill.session_paths import (
    BRAIN_REGEX,
    DEFAULT_BRAIN_ROOTS,
    INTENT_DEFINITIONS,
    MCP_REGEX,
    extract_clean_quote,
    extract_conversation_id,
    extract_paths_from_command,
    extract_project_from_path,
    normalize_path_string,
    parse_timestamp,
)
from tools.distill.session_reports import format_intents_report, format_sessions_report
from tools.distill.session_step_parser import (
    extract_tool_proj_candidates,
    extract_workspace_proj,
    iter_transcript_dicts,
    resolve_root_transcript,
    scan_step_intents,
)


def _safe_is_dir(p: Path) -> Optional[str]:
    try:
        return str(p.resolve()).lower() if p.is_dir() else None
    except Exception:
        return None


def _scan_brain_root(root: Path) -> List[Path]:
    if not root.is_dir():
        return []
    try:
        return [found for entry in root.iterdir() if (found := resolve_root_transcript(entry))]
    except Exception:
        return []


class SessionMiner:
    """Deterministic streaming analyzer for Antigravity conversation transcripts."""

    def __init__(
        self,
        brain_roots: Optional[List[Union[str, Path]]] = None,
        repo_path: Optional[Union[str, Path]] = None,
    ):
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        self.brain_roots = [Path(r) for r in brain_roots] if brain_roots else self._resolve_default_roots()

    @staticmethod
    def _resolve_default_roots() -> List[Path]:
        valid_roots: List[Path] = []
        seen: Set[str] = set()
        for r in DEFAULT_BRAIN_ROOTS:
            norm = _safe_is_dir(r)
            if norm and norm not in seen:
                seen.add(norm)
                valid_roots.append(r)
        return valid_roots

    def discover_transcript_files(self) -> List[Path]:
        """Discovers all transcript.jsonl files within configured brain roots."""
        found = [tf for root in self.brain_roots for tf in _scan_brain_root(root)]
        return sorted(found, key=lambda p: str(p))

    def parse_transcript(self, transcript_path: Path) -> Optional[Dict[str, Any]]:
        """Streams a single transcript.jsonl line-by-line with zero-crash resilience."""
        if not transcript_path.is_file():
            return None
        steps = iter_transcript_dicts(transcript_path)
        if not steps:
            return None

        human_turns = 0
        min_dt: Optional[datetime] = None
        max_dt: Optional[datetime] = None
        first_raw_ts: Optional[str] = None
        workspace_project: Optional[str] = None
        tool_candidates: List[str] = []
        session_intents: Set[str] = set()
        session_quotes: Dict[str, str] = {}

        for step_data in steps:
            ts_str = step_data.get("created_at")
            if isinstance(ts_str, str) and ts_str:
                first_raw_ts = first_raw_ts or ts_str
                if (dt := parse_timestamp(ts_str)):
                    min_dt = dt if (min_dt is None or dt < min_dt) else min_dt
                    max_dt = dt if (max_dt is None or dt > max_dt) else max_dt
            workspace_project = workspace_project or extract_workspace_proj(step_data)
            tool_candidates.extend(extract_tool_proj_candidates(step_data))
            if scan_step_intents(step_data, session_intents, session_quotes):
                human_turns += 1

        final_project = (
            workspace_project
            or (Counter(tool_candidates).most_common(1)[0][0] if tool_candidates else "UNASSIGNED / SCRATCH")
        )
        start_time = min_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if min_dt else (first_raw_ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        dur = max(0, int(round((max_dt - min_dt).total_seconds() / 60.0))) if (min_dt and max_dt) else 0
        return {
            "conversation_id": extract_conversation_id(transcript_path),
            "project": final_project,
            "start_time": start_time,
            "duration_minutes": dur,
            "total_steps": len(steps),
            "human_turns": human_turns,
            "detected_intents": sorted(session_intents),
            "quotes_by_intent": session_quotes,
        }

    def mine_sessions(self) -> Dict[str, Any]:
        """Discovers and processes all transcripts, grouped chronologically by project."""
        all_parsed = [p for tf in self.discover_transcript_files() if (p := self.parse_transcript(tf))]
        projects_dict: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"session_count": 0, "sessions": []})
        intent_counts: Counter = Counter()
        intent_sample_quotes: Dict[str, str] = {}

        for s in all_parsed:
            projects_dict[s["project"]]["sessions"].append({
                k: s[k] for k in ("conversation_id", "start_time", "duration_minutes", "total_steps", "human_turns", "detected_intents")
            })
            for intent in s["detected_intents"]:
                intent_counts[intent] += 1
                intent_sample_quotes.setdefault(intent, s["quotes_by_intent"].get(intent, ""))

        for pdata in projects_dict.values():
            pdata["sessions"].sort(key=lambda s: s["start_time"])
            pdata["session_count"] = len(pdata["sessions"])

        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_sessions": len(all_parsed),
            "projects": dict(projects_dict),
            "intent_summary": {
                name: {"session_frequency": intent_counts.get(name, 0), "sample_quote": intent_sample_quotes.get(name, "")}
                for name in INTENT_DEFINITIONS
            },
        }

    def save_sessions_json(self, data: Dict[str, Any], output_path: Optional[Union[str, Path]] = None) -> Path:
        """Persists mined session data to .edge/distilled/sessions.json or custom path."""
        out_file = Path(output_path) if output_path else (self.repo_path / ".edge" / "distilled" / "sessions.json")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return out_file

    def format_sessions_report(self, data: Dict[str, Any], by_project: bool = False) -> str:
        return format_sessions_report(data, by_project=by_project)

    def format_intents_report(self, data: Dict[str, Any]) -> str:
        return format_intents_report(data)
