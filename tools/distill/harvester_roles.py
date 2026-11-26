"""
Station role normalization and step-0/step-1 cue extraction for TranscriptGraphHarvester.
"""

import re
from typing import Any, Dict, List, Optional

_CANONICAL_STATION_ROLES = (
    "spec_writer",
    "seam_architect",
    "spec_critic",
    "qa_engineer",
    "researcher",
    "coder",
    "surgeon",
    "examiner",
)
_CID_RE = re.compile(r'"conversation(?:Id|_id)":\s*"([^"]+)"')
_ACCEPTED_STEP0_ROLES = frozenset(_CANONICAL_STATION_ROLES) | {"orchestrator"}
_STEP0_WORKER_PATTERNS = (
    (re.compile(r"agents/([a-zA-Z0-9_-]+)\.md"), 1),
    (re.compile(r"\bYou are (?:the )?(?:persistent |ephemeral )?([A-Za-z_ -]+?) (?:station|worker|agent|subagent)\b", re.IGNORECASE), 1),
    (re.compile(r"\bYou are (?:the )?([A-Z][A-Z0-9_]{1,})(?![a-z])"), 1),
    (re.compile(r"\bPersona:\s*([A-Za-z_ ]+)", re.IGNORECASE), 1),
)
_ORCHESTRATOR_CUES = (
    re.compile(r"\bYou are (?:the )?(?:Sovereign Commander|Orchestrator)\b", re.IGNORECASE),
    re.compile(r"\[EDGE ORCHESTRATOR ENFORCED\]", re.IGNORECASE),
    re.compile(r"\bPersona:\s*(?:Sovereign Commander|Orchestrator)\b", re.IGNORECASE),
)


def _normalize_station_role(raw_role: str) -> str:
    raw = raw_role.strip()
    if not raw:
        return "unknown"
    lowered_space = raw.lower()
    if "orchestrator" in lowered_space or "sovereign commander" in lowered_space:
        return "orchestrator"
    lowered_under = lowered_space.replace("-", "_").replace(" ", "_")
    for canon in _CANONICAL_STATION_ROLES:
        if canon in lowered_under or canon.replace("_", " ") in lowered_space:
            return canon
    slug = re.sub(r"[^a-z0-9]+", "_", lowered_space).strip("_")
    return slug or "unknown"


def _match_step0_worker_role(text: str) -> Optional[str]:
    for pat, grp in _STEP0_WORKER_PATTERNS:
        m = pat.search(text)
        if m:
            norm = _normalize_station_role(m.group(grp))
            if norm in _ACCEPTED_STEP0_ROLES and norm != "orchestrator":
                return norm
    return None


def _match_step0_orchestrator_cue(text: str) -> Optional[str]:
    for pat in _ORCHESTRATOR_CUES:
        if pat.search(text):
            return "orchestrator"
    return None


def _extract_step0_role_cue(steps: List[Dict[str, Any]]) -> Optional[str]:
    step_by_idx = {s.get("step_index"): str(s.get("content", "")) for s in steps}
    for s_idx in (0, 1):
        text = step_by_idx.get(s_idx, "")
        if not text:
            continue
        worker_role = _match_step0_worker_role(text)
        if worker_role:
            return worker_role
        orch_role = _match_step0_orchestrator_cue(text)
        if orch_role:
            return orch_role
    return None
