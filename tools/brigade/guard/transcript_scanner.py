"""Transcript scanning, token heat measurement, and repo brigade sync (stdlib-only)."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from tools.brigade.guard.role_detection import extract_requested_roles, normalize_role, to_wsl_path
from tools.brigade.guard.station_models import GREEN_HEAT_THRESHOLD, YELLOW_HEAT_THRESHOLD, TokenHeatRecord

_CID_FALLBACK_RE = re.compile(r'\\?["\']conversation(?:Id|_id)\\?["\']\s*:\s*\\?["\']([a-f0-9\-]+)\\?["\']')


def _safe_json(line_str: str) -> Dict[str, Any]:
    try:
        obj = json.loads(line_str)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _extract_step_tokens(step: Dict[str, Any]) -> Optional[int]:
    inp, cache = step.get("input_tokens"), step.get("cache_read_tokens")
    tok = step.get("total_tokens") or step.get("tokens")
    if inp is None and cache is None and tok is None:
        return None
    step_tokens = (inp or 0) + (cache or 0)
    return int(step_tokens if step_tokens or not tok else tok)


def _scan_parent_line(line_str: str, pending_roles: List[str], pairs: List[Tuple[str, str]]) -> None:
    if not line_str.strip():
        return
    step = _safe_json(line_str)
    for tc in step.get("tool_calls", []):
        if tc.get("name") == "invoke_subagent":
            pending_roles.extend(normalize_role(r) or r for r in extract_requested_roles(tc.get("args", {})))
    content = step.get("content", "")
    blob = content if ("conversationId" in content or "conversation_id" in content) else line_str
    if "conversationId" in blob or "conversation_id" in blob:
        for cid in _CID_FALLBACK_RE.findall(blob):
            pairs.append((cid, pending_roles.pop(0) if pending_roles else "STATION_WORKER"))


def _sum_transcript_heat(transcript: Path) -> Tuple[int, bool]:
    total_tokens, total_chars, found_explicit = 0, 0, False
    try:
        lines = transcript.read_text(encoding="utf-8-sig", errors="ignore").splitlines(keepends=True)
    except Exception:
        return 0, False
    for line in lines:
        total_chars += len(line)
        step = _safe_json(line.strip())
        val = _extract_step_tokens(step) if step else None
        if val is not None:
            found_explicit, total_tokens = True, val
    return (total_tokens if found_explicit else total_chars // 4), found_explicit


class TranscriptStationScanner:
    """Scans Antigravity transcripts for station conversation IDs and token heat."""

    def __init__(self, brain_root: Path):
        self.brain_root = to_wsl_path(str(brain_root))

    def discover_session_stations(self, parent_transcript_path: Path) -> List[Tuple[str, str]]:
        parent_path = to_wsl_path(str(parent_transcript_path))
        if not parent_path.exists():
            return []
        pairs: List[Tuple[str, str]] = []
        pending_roles: List[str] = []
        try:
            for line_str in parent_path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                _scan_parent_line(line_str, pending_roles, pairs)
        except Exception:
            pass
        return pairs

    def calculate_subagent_heat(self, conversation_id: str) -> TokenHeatRecord:
        brain_root = to_wsl_path(str(self.brain_root))
        transcript = brain_root / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"
        now_iso = datetime.now(timezone.utc).isoformat()
        if not transcript.exists():
            return TokenHeatRecord(tokens=0, heat_zone="GREEN", last_calculated_at=now_iso)
        total_tokens, _ = _sum_transcript_heat(transcript)
        zone = "GREEN" if total_tokens < GREEN_HEAT_THRESHOLD else ("YELLOW" if total_tokens <= YELLOW_HEAT_THRESHOLD else "RED")
        return TokenHeatRecord(tokens=total_tokens, heat_zone=zone, last_calculated_at=now_iso)


def _load_repo_brigade_data(brigade_json_path: Path) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if brigade_json_path.exists():
        loaded = _safe_json(brigade_json_path.read_text(encoding="utf-8"))
        if loaded:
            data = loaded
    if not isinstance(data.get("stations"), dict):
        data["stations"] = {}
    return data


def _build_station_entry(canonical: str, conversation_id: str, now_iso: str, existing: Any = None, model: Optional[str] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"role": canonical, "conversation_id": conversation_id, "conversationId": conversation_id, "updated_at": now_iso}
    eff_model = model or (existing.get("model") if isinstance(existing, dict) else None)
    if eff_model:
        entry["model"] = str(eff_model)
    return entry


def sync_repo_brigade_station(repo_path: Union[Path, str], role: str, conversation_id: str, model: Optional[str] = None) -> bool:
    """Atomically record a persistent station mapping into <repo>/.edge/brigade.json."""
    try:
        edge_dir = Path(repo_path) / ".edge"
        edge_dir.mkdir(parents=True, exist_ok=True)
        brigade_json = edge_dir / "brigade.json"
        data = _load_repo_brigade_data(brigade_json)
        canonical = normalize_role(role) or role.strip().upper()
        data["stations"][canonical] = _build_station_entry(canonical, conversation_id, datetime.now(timezone.utc).isoformat(), data["stations"].get(canonical), model)
        tmp_path = edge_dir / f"brigade.json.tmp.{os.getpid()}"
        tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_path, brigade_json)
        return True
    except Exception:
        return False
