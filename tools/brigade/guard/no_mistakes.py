"""Headless no-mistakes worker exemption detector (stdlib-only)."""

import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_NO_MISTAKES_ENV_VARS: Tuple[str, ...] = ("NO_MISTAKES", "NO_MISTAKES_RUN", "NO_MISTAKES_STEP")
_NO_MISTAKES_MARKERS: Tuple[str, ...] = ("no-mistakes", "pipeline-attestation", "return json only", "## what changed", "scenariocontract")


def _find_marker_in_text(text: str) -> Optional[str]:
    low = text.lower()
    return next((m for m in _NO_MISTAKES_MARKERS if m in low), None)


def _check_no_mistakes_env() -> Optional[str]:
    for key in _NO_MISTAKES_ENV_VARS:
        val = str(os.environ.get(key, "")).strip().lower()
        if val and val not in ("0", "false", "no"):
            return f"env:{key}"
    return None


def _check_no_mistakes_payload_text(payload: Dict[str, Any]) -> Optional[str]:
    parts: List[str] = [str(payload[k]) for k in ("prompt", "userMessage", "message") if payload.get(k)]
    tc = payload.get("toolCall")
    if isinstance(tc, dict) and tc.get("args"):
        parts.append(str(tc["args"]))
    if not parts:
        return None
    marker = _find_marker_in_text("\n".join(parts))
    return f"payload:{marker}" if marker else None


def _check_no_mistakes_transcript(payload: Dict[str, Any]) -> Optional[str]:
    t_path_raw = payload.get("transcriptPath")
    if not t_path_raw:
        return None
    facade = sys.modules.get("tools.brigade.orchestrator_guard")
    resolver = getattr(facade, "to_wsl_path", None) if facade else None
    if resolver is None:
        from tools.brigade.guard.tool_args import to_wsl_path as resolver
    t_path = resolver(str(t_path_raw))
    if not t_path or not t_path.is_file():
        return None
    try:
        with open(t_path, "r", encoding="utf-8", errors="ignore") as f:
            head = "".join(line for idx, line in enumerate(f) if idx < 25)
        marker = _find_marker_in_text(head)
        return f"transcript:{marker}" if marker else None
    except Exception:
        return None


def is_no_mistakes_invocation(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Detect headless no-mistakes worker invocations via env, payload, or transcript."""
    env_hit = _check_no_mistakes_env()
    if env_hit:
        return True, env_hit
    if not isinstance(payload, dict):
        return False, ""
    hit = _check_no_mistakes_payload_text(payload) or _check_no_mistakes_transcript(payload)
    return (True, hit) if hit else (False, "")
