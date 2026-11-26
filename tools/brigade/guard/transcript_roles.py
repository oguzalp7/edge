"""Transcript header role parsing helpers (stdlib-only)."""

import json
import re
from typing import Callable, List, Optional, Tuple

_MESSAGE_BODY_RE = re.compile(r"\bcontent=(.*)$", re.DOTALL)
_SWARM_TAG_RE = re.compile(r"(?:^|\s)(?:for\s+@|content=@|\[Swarm\]\s*@)([a-z0-9_-]+)|^@([a-z0-9_-]+)", re.IGNORECASE | re.MULTILINE)
_EXPLICIT_ROLE_PATTERNS = (
    re.compile(r"\bYou are (?:the )?(?:persistent |ephemeral )?([A-Za-z_ -]+?) (?:station|worker|agent|subagent)\b", re.IGNORECASE),
    re.compile(r"\bYou are (?:the )?(SPEC_WRITER|RESEARCHER|SEAM_ARCHITECT|CODER|SURGEON|EXAMINER|QA_ENGINEER|SPEC_CRITIC)\b", re.IGNORECASE),
    re.compile(r"\bPersona:\s*([A-Za-z_ -]+)\b", re.IGNORECASE),
    re.compile(r"\bcanonical ([A-Za-z_ -]+?) station\b", re.IGNORECASE),
    re.compile(r"\b(?:read|follow)\s+agents/([a-zA-Z0-9_-]+)\.md\b", re.IGNORECASE),
)


def extract_message_body(content: str) -> str:
    """Extract content=... body from structured [Message] headers."""
    if "[Message]" not in content:
        return content
    m = _MESSAGE_BODY_RE.search(content)
    return m.group(1) if m else content


def match_explicit_role(text: str, normalize_fn: Callable[[str], Optional[str]]) -> Optional[str]:
    """Match explicit station identity statements in message text."""
    for pat in _EXPLICIT_ROLE_PATTERNS:
        m = pat.search(text)
        if not m or "sovereign commander" in m.group(1).lower():
            continue
        role = normalize_fn(m.group(1).strip())
        if role:
            return role
    return None


def _collect_system_contents(first_lines: List[str]) -> str:
    parts: List[str] = []
    for line in first_lines[:4]:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict) and obj.get("source") == "SYSTEM":
            parts.append(extract_message_body(str(obj.get("content", ""))))
    return "\n".join(parts)


def _detect_swarm_role(
    joined: str,
    normalize_fn: Callable[[str], Optional[str]],
    scan_fn: Callable[[str], Optional[Tuple[str, str]]],
) -> Tuple[str, str]:
    for m in _SWARM_TAG_RE.finditer(joined):
        role = normalize_fn(m.group(1) or m.group(2) or "")
        if role:
            return role, "transcript_swarm_keyword"
    exp = match_explicit_role(joined, normalize_fn) or (scan_fn(joined) or (None,))[0]
    return (exp, "transcript_swarm_keyword") if exp else ("SUBAGENT_GENERIC", "transcript_subagent")


def detect_transcript_role(
    first_lines: List[str],
    normalize_fn: Callable[[str], Optional[str]],
    scan_fn: Callable[[str], Optional[Tuple[str, str]]],
) -> Tuple[str, str]:
    """Detect station role from initial transcript JSONL lines."""
    first_obj = json.loads(first_lines[0])
    first_content = str(first_obj.get("content", ""))
    if first_obj.get("source") == "SYSTEM":
        joined = _collect_system_contents(first_lines)
        if "[swarm]" in joined.lower() or _SWARM_TAG_RE.search(joined):
            return _detect_swarm_role(joined, normalize_fn, scan_fn)
        if "[Message]" in first_content:
            body = extract_message_body(first_content)
            exp = match_explicit_role(body, normalize_fn)
            return (exp, "transcript_subagent_explicit") if exp else (scan_fn(body) or ("SUBAGENT_GENERIC", "transcript_subagent"))
    if first_obj.get("source") == "USER_EXPLICIT" or any("edge-orchestrator" in ln for ln in first_lines):
        return "ORCHESTRATOR", "transcript_root"
    return "UNKNOWN", "default"
