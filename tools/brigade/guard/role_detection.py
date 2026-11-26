"""Session role normalization and transcript role detection (stdlib-only)."""

import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.guard.tool_args import extract_requested_roles, get_target_file, parse_subagents, to_wsl_path
from tools.brigade.guard.transcript_roles import detect_transcript_role

CANONICAL_ROLES: Dict[str, List[str]] = {
    "SPEC_WRITER": ["spec_writer", "spec writer", "spec-writer", "translator", "slicer", "n-spec"],
    "RESEARCHER": ["researcher", "research", "recon", "reconnaissance", "investigator", "rca", "root cause"],
    "SEAM_ARCHITECT": ["seam_architect", "seam architect", "seam-architect", "contract", "test author", "red test", "tdd"],
    "CODER": ["coder", "programmer", "worker", "implementer", "production worker"],
    "SURGEON": ["surgeon", "refactor", "refactorer", "chef de partie", "decoupling"],
    "EXAMINER": [
        "examiner", "reviewer", "code reviewer", "standards_examiner", "standards examiner",
        "standards-examiner", "spec_examiner", "spec examiner", "spec-examiner", "sous chef", "maitre d",
    ],
    "QA_ENGINEER": ["qa_engineer", "qa", "e2e", "e2e_tester", "sommelier", "inspector", "test_agent", "qa agent"],
    "SPEC_CRITIC": ["spec_critic", "spec critic", "spec-critic", "goldfish_critic", "goldfish critic"],
}
PERSISTENT_ELEPHANT_ROLES = frozenset({"SPEC_WRITER", "RESEARCHER", "SEAM_ARCHITECT", "CODER", "SURGEON", "QA_ENGINEER"})
EPHEMERAL_GOLDFISH_ROLES = frozenset({"EXAMINER", "SPEC_CRITIC"})


def _compile_role_tiers() -> Tuple[List[Tuple[str, re.Pattern[str]]], List[Tuple[str, re.Pattern[str]]]]:
    tier1, tier2 = [], []
    for canonical, aliases in CANONICAL_ROLES.items():
        slug = canonical.lower()
        t1_vars = {slug, slug.replace("_", " "), slug.replace("_", "-")}
        t1_union = "|".join(re.escape(v) for v in sorted(t1_vars, key=len, reverse=True))
        tier1.append((canonical, re.compile(rf"(?<![a-z0-9_])(?:{t1_union})(?![a-z0-9_])", re.IGNORECASE)))
        t2_vars = [a.lower() for a in aliases if a.lower() not in t1_vars]
        if t2_vars:
            t2_union = "|".join(re.escape(v) for v in sorted(set(t2_vars), key=len, reverse=True))
            tier2.append((canonical, re.compile(rf"(?<![a-z0-9_])(?:{t2_union})(?![a-z0-9_])", re.IGNORECASE)))
    return tier1, tier2


_ROLE_TIER1_PATTERNS, _ROLE_TIER2_PATTERNS = _compile_role_tiers()


def _find_earliest_tier_match(text: str, tier_patterns: List[Tuple[str, re.Pattern[str]]]) -> Optional[str]:
    best_pos: Optional[int] = None
    best_role: Optional[str] = None
    for canonical, pat in tier_patterns:
        m = pat.search(text)
        if m and (best_pos is None or m.start() < best_pos):
            best_pos, best_role = m.start(), canonical
    return best_role


def normalize_role(raw_role: str) -> Optional[str]:
    """Normalize any role alias into a canonical uppercase station role."""
    if not raw_role:
        return None
    raw_lower = raw_role.strip().lower()
    if raw_lower.upper() in CANONICAL_ROLES:
        return raw_lower.upper()
    return _find_earliest_tier_match(raw_lower, _ROLE_TIER1_PATTERNS) or _find_earliest_tier_match(raw_lower, _ROLE_TIER2_PATTERNS)


def _scan_role_in_text(text: str) -> Optional[Tuple[str, str]]:
    t1 = _find_earliest_tier_match(text, _ROLE_TIER1_PATTERNS)
    if t1:
        return t1, "transcript_subagent_keyword"
    t2 = _find_earliest_tier_match(text, _ROLE_TIER2_PATTERNS)
    return (t2, "transcript_subagent_alias") if t2 else None


def detect_session_role(payload: dict) -> Tuple[str, str]:
    """Detect active Brigade station role from active registry or transcript head."""
    from tools.brigade.guard.station_store import load_active_stations

    facade = sys.modules.get("tools.brigade.orchestrator_guard")
    loader = getattr(facade, "load_active_stations", load_active_stations) if facade else load_active_stations
    cid = payload.get("conversationId", "")
    active_data = loader()
    if cid and cid in active_data:
        return active_data[cid].get("role", "UNKNOWN"), "active_registry"
    tp = to_wsl_path(payload.get("transcriptPath", ""))
    if payload.get("transcriptPath") and tp.exists():
        try:
            with open(tp, "r", encoding="utf-8-sig", errors="ignore") as f:
                first_lines = [line for idx, line in enumerate(f) if idx <= 25]
            if first_lines:
                return detect_transcript_role(first_lines, normalize_role, _scan_role_in_text)
        except Exception:
            pass
    return "UNKNOWN", "default"


def attach_station_token(text: str, role: str) -> str:
    """Prefix spawn prompts or briefs with [edge-station:<ROLE>] idempotently."""
    token = f"[edge-station:{role}]"
    if "[edge-station:" in text.lower():
        return text
    return f"{token} {text}".strip()
