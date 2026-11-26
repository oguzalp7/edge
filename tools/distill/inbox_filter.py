"""Signal fingerprinting, noise classification, and prune filtering for FactoryInbox."""

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Dict, Optional, Set

from tools.common.paths import to_wsl_path
from tools.distill.state_io import _is_ephemeral_test_path, _sanitize_signal_summary

_INBOX_PRESERVATION_MARKERS = (
    "Traceback", "ERROR:", "error TS", "fatal:", "FAILED", "BLOCKED",
    "AssertionError", "SyntaxError", "ModuleNotFoundError",
    "Encountered error in tool execution", "was forcefully killed", "hung or required excessive polling",
)
_NONZERO_EXIT_RE = re.compile(r"Command exited with code\s+[1-9]\d*")
BENIGN_WSL_RELAY_BANNER_RE = re.compile(
    r"(?:<3>)?WSL[ \t]*\([ \t]*\d+[ \t]*-[ \t]*Relay[ \t]*\)[ \t]*ERROR:[ \t]*CreateProcessParseCommon[^\r\n]*",
    re.IGNORECASE,
)
_BENIGN_INBOX_TOOLS = frozenset({"read_file", "read_board", "edit_file", "manage_task", "invoke_subagent"})
_BENIGN_INBOX_SNIPPETS = ("The tool's output was truncated", "Showing lines ", "Made 1 replacement")
PRUNE_REASONS = ("exit_zero", "benign_tool", "ephemeral", "duplicate", "resolved", "expired")


def compute_signal_fingerprint(kind: str, role_or_tool: str, summary: str) -> str:
    """Compute deterministic 16-char SHA-256 fingerprint for deduplicating inbox signals."""
    clean_summary = _sanitize_signal_summary(summary)
    return hashlib.sha256(f"{kind}:{role_or_tool}:{clean_summary}".lower().encode("utf-8")).hexdigest()[:16]


def _normalize_scope_path(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    return to_wsl_path(raw.strip()).replace("\\", "/").rstrip("/").lower()


def match_project_scope(source_project: str, target_project: str) -> bool:
    """Return True when source_project equals or lives under target_project."""
    proj = _normalize_scope_path(target_project)
    if not proj:
        return True
    src = _normalize_scope_path(source_project)
    return bool(src) and (src == proj or src.startswith(proj + "/"))


def _is_expired_signal(created_at: str, max_age_days: int, now: datetime) -> bool:
    if not created_at or not isinstance(created_at, str):
        return False
    ts_str = created_at.strip()
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) > timedelta(days=max_age_days)


def _has_preservation_marker(summary: str) -> bool:
    if not summary:
        return False
    if _NONZERO_EXIT_RE.search(summary):
        return True
    cleaned = BENIGN_WSL_RELAY_BANNER_RE.sub("", summary)
    return any(marker in cleaned for marker in _INBOX_PRESERVATION_MARKERS)


def _classify_noise_reason(kind: str, role_or_tool: str, summary: str, drop_exit_zero: bool, drop_benign_tools: bool) -> Optional[str]:
    if _has_preservation_marker(summary):
        return None
    if drop_exit_zero and kind == "HARNESS_FRICTION" and "Command exited with code 0" in summary:
        return "exit_zero"
    if drop_benign_tools and kind == "HARNESS_FRICTION" and (role_or_tool in _BENIGN_INBOX_TOOLS or any(snip in summary for snip in _BENIGN_INBOX_SNIPPETS)):
        return "benign_tool"
    return None


def classify_prune_reason(record: Dict[str, Any], fp: str, seen_fps: Set[str], opts: Dict[str, Any], now: datetime) -> Optional[str]:
    """Return prune reason key for an inbox record or None to retain."""
    if opts["resolved_only"]:
        return "resolved" if record.get("resolved", False) else None
    if opts["drop_ephemeral"] and _is_ephemeral_test_path(str(record.get("source_project", ""))):
        return "ephemeral"
    kind, role_or_tool, summary = str(record.get("kind", "HARNESS_FRICTION")), str(record.get("role_or_tool", "")), str(record.get("summary", ""))
    noise = _classify_noise_reason(kind, role_or_tool, summary, opts["drop_exit_zero"], opts["drop_benign_tools"])
    if noise:
        return noise
    if opts["max_age_days"] is not None and _is_expired_signal(str(record.get("created_at", "")), opts["max_age_days"], now):
        return "expired"
    return "duplicate" if (opts["deduplicate"] and fp in seen_fps) else None
