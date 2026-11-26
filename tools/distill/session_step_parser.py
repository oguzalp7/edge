"""
Transcript JSONL reading and step-level project/intent extraction for SessionMiner.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from tools.distill.session_paths import (
    INTENT_DEFINITIONS,
    extract_clean_quote,
    extract_paths_from_command,
    extract_project_from_path,
)


def extract_workspace_proj(step_data: Dict[str, Any]) -> Optional[str]:
    ws_uris = step_data.get("workspaceUris")
    if not ws_uris:
        return None
    if isinstance(ws_uris, str):
        return extract_project_from_path(ws_uris)
    if isinstance(ws_uris, list):
        for u in ws_uris:
            proj = extract_project_from_path(str(u))
            if proj:
                return proj
    return None


def extract_tool_proj_candidates(step_data: Dict[str, Any]) -> List[str]:
    tool_calls = step_data.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    candidates: List[str] = []
    for tc in tool_calls:
        args = tc.get("args") if isinstance(tc, dict) else None
        if not isinstance(args, dict):
            continue
        for arg_key in ("Cwd", "AbsolutePath", "TargetFile"):
            val = args.get(arg_key)
            if isinstance(val, str) and val and (p := extract_project_from_path(val)):
                candidates.append(p)
        cmd_val = args.get("CommandLine")
        if isinstance(cmd_val, str) and cmd_val:
            candidates.extend(p for cp in extract_paths_from_command(cmd_val) if (p := extract_project_from_path(cp)))
    return candidates


def scan_step_intents(
    step_data: Dict[str, Any],
    session_intents: Set[str],
    session_quotes: Dict[str, str],
) -> bool:
    if step_data.get("source") != "USER_EXPLICIT" and step_data.get("type") != "USER_INPUT":
        return False
    content = step_data.get("content")
    if not (isinstance(content, str) and content):
        return True
    content_norm = content.lower().replace("İ", "i").replace("I", "ı")
    for intent_name, defn in INTENT_DEFINITIONS.items():
        matched_pat = next((pat for pat in defn["patterns"] if pat in content_norm), None)
        if not matched_pat:
            continue
        session_intents.add(intent_name)
        if intent_name not in session_quotes:
            quote = extract_clean_quote(content, matched_pat)
            if quote:
                session_quotes[intent_name] = quote
    return True


def resolve_root_transcript(entry: Path) -> Optional[Path]:
    if not entry.is_dir():
        return None
    primary = entry / ".system_generated" / "logs" / "transcript.jsonl"
    if primary.is_file():
        return primary
    alt = entry / "transcript.jsonl"
    return alt if alt.is_file() else None


def _parse_json_dict(raw_line: str) -> Optional[Dict[str, Any]]:
    line = raw_line.strip()
    if not line:
        return None
    try:
        item = json.loads(line)
        return item if isinstance(item, dict) else None
    except Exception:
        return None


def iter_transcript_dicts(transcript_path: Path) -> Optional[List[Dict[str, Any]]]:
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            return [d for raw in f if (d := _parse_json_dict(raw)) is not None]
    except Exception:
        return None
