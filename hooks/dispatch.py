#!/usr/bin/env python3
"""
Session-gated, fail-open lifecycle hook dispatcher for Edge.
@intent Gate lifecycle hooks to active Edge sessions with stdlib-only fast-path and fail-open boundary
@concepts zero-handoff-guard
@invariants [INV-ORCH-HOOK-LATENCY]
"""

import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

_ORCHESTRATOR_TRIGGER_RE = re.compile(
    r"(?i)(?:^|\s)/edge-orchestrator(?:\s|$|\b)|<skill_name>\s*edge-orchestrator\s*</skill_name>|\[edge_orchestrator\]"
)
_STATION_TOKEN_RE = re.compile(r"\[edge-station:[A-Za-z0-9_-]+\]", re.IGNORECASE)

_NO_MISTAKES_ENV_VARS = ("NO_MISTAKES", "NO_MISTAKES_RUN", "NO_MISTAKES_STEP")
_NO_MISTAKES_MARKERS = (
    "no-mistakes",
    "pipeline-attestation",
    "return json only",
    "## what changed",
    "scenariocontract",
)
_MAX_HEAD_LINES = 25
_MAX_TAIL_BYTES = 65536
_MAX_TAIL_LINES = 200
_MAX_SYSTEM_STEPS = 4


def _get_plugin_root() -> Path:
    for env_key in ("PLUGIN_ROOT", "EDGE_PLUGIN_ROOT"):
        val = os.environ.get(env_key, "").strip()
        if val:
            return Path(val)
    return Path(__file__).resolve().parents[1]


def _load_env_module() -> Any:
    loaded = sys.modules.get("tools.common.env")
    if loaded is not None:
        return loaded
    cached = sys.modules.get("_edge_dispatch_env")
    if cached is not None:
        return cached
    env_path = _get_plugin_root() / "tools" / "common" / "env.py"
    spec = importlib.util.spec_from_file_location("_edge_dispatch_env", env_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load env module from {env_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_edge_dispatch_env"] = mod
    spec.loader.exec_module(mod)
    return mod


def _fail_open_response(mode: str) -> Dict[str, Any]:
    if mode == "pre_tool":
        return {"decision": "allow"}
    if mode == "pre_invocation":
        return {"injectSteps": []}
    return {}


def _safe_cid_filename(cid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", cid).strip("_")


def _persist_session_marker(env_mod: Any, cid: str, reason: str) -> None:
    safe_cid = _safe_cid_filename(cid)
    if not safe_cid:
        return
    sessions_dir = env_mod.get_active_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    target = sessions_dir / f"{safe_cid}.json"
    if target.is_file():
        return
    body = json.dumps({"conversationId": cid, "reason": reason}, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{safe_cid}.", suffix=".tmp", dir=str(sessions_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp_name, target)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _read_bounded_transcript(env_mod: Any, payload: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    raw_path = payload.get("transcriptPath")
    if not raw_path:
        return [], []
    tp = env_mod.resolve_host_path(str(raw_path))
    if not tp.is_file():
        return [], []
    try:
        head_lines: List[str] = []
        with open(tp, "r", encoding="utf-8", errors="ignore") as fh:
            for idx, line in enumerate(fh):
                if idx >= _MAX_HEAD_LINES:
                    break
                head_lines.append(line)
        file_size = tp.stat().st_size
        if file_size <= _MAX_TAIL_BYTES:
            all_lines = tp.read_text(encoding="utf-8", errors="ignore").splitlines()
            return head_lines, all_lines[-_MAX_TAIL_LINES:] if len(all_lines) > _MAX_TAIL_LINES else all_lines
        with open(tp, "rb") as fb:
            fb.seek(max(0, file_size - _MAX_TAIL_BYTES))
            tail_text = fb.read().decode("utf-8", errors="ignore")
        tail_lines = tail_text.splitlines()[1:][-_MAX_TAIL_LINES:]
        return head_lines, head_lines + tail_lines
    except Exception:
        return [], []


def _text_has_no_mistakes_marker(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _NO_MISTAKES_MARKERS)


def _collect_payload_text(payload: Dict[str, Any]) -> str:
    parts = [str(payload[k]) for k in ("prompt", "userMessage", "message", "lastUserInput") if payload.get(k)]
    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict) and tool_call.get("args"):
        parts.append(str(tool_call.get("args")))
    return "\n".join(parts)


def _is_no_mistakes_exempt(payload: Dict[str, Any], head_lines: List[str]) -> bool:
    for key in _NO_MISTAKES_ENV_VARS:
        val = str(os.environ.get(key, "")).strip().lower()
        if val and val not in ("0", "false", "no"):
            return True
    payload_text = _collect_payload_text(payload)
    if payload_text and _text_has_no_mistakes_marker(payload_text):
        return True
    return bool(head_lines and _text_has_no_mistakes_marker("\n".join(head_lines)))


def _is_afk_active(head_lines: List[str]) -> bool:
    if os.environ.get("EDGE_AFK", "").strip() == "1":
        return True
    return any("[edge_afk" in line.lower() for line in head_lines[:_MAX_HEAD_LINES])


def _is_registered_station(env_mod: Any, cid: str) -> bool:
    if not cid:
        return False
    stations_path = env_mod.get_active_stations_path()
    if not stations_path.is_file():
        return False
    try:
        data = json.loads(stations_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    stations = data.get("stations")
    if isinstance(stations, dict):
        return cid in stations
    return cid in data and cid not in ("version", "initializedAt", "sessions", "stations")


def _has_session_marker(env_mod: Any, cid: str) -> bool:
    safe_cid = _safe_cid_filename(cid)
    if not safe_cid:
        return False
    return (env_mod.get_active_sessions_dir() / f"{safe_cid}.json").is_file()


def _parse_jsonl_dict(line: str) -> Optional[Dict[str, Any]]:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _is_user_orchestrator_step(obj: Dict[str, Any]) -> bool:
    if obj.get("type") != "USER_INPUT" or obj.get("source") != "USER_EXPLICIT":
        return False
    return bool(_ORCHESTRATOR_TRIGGER_RE.search(str(obj.get("content") or "")))


def _is_system_step(obj: Dict[str, Any]) -> bool:
    return obj.get("source") == "SYSTEM" or obj.get("type") == "SYSTEM_MESSAGE"


def _scan_transcript_for_activation(scan_lines: List[str]) -> Optional[str]:
    system_steps = 0
    for line in scan_lines:
        obj = _parse_jsonl_dict(line)
        if obj is None:
            continue
        if _is_user_orchestrator_step(obj):
            return "transcript_user_trigger"
        if _is_system_step(obj):
            system_steps += 1
            if system_steps <= _MAX_SYSTEM_STEPS and _STATION_TOKEN_RE.search(str(obj.get("content") or "")):
                return "station_token"
    return None


def _evaluate_session_gate(
    env_mod: Any, payload: Dict[str, Any], scan_lines: List[str]
) -> Tuple[bool, str]:
    cid = str(payload.get("conversationId") or "").strip()
    if _is_registered_station(env_mod, cid):
        return True, "active_station"
    if _has_session_marker(env_mod, cid):
        return True, "session_marker"

    last_user_input = str(payload.get("lastUserInput") or "")
    if last_user_input and _ORCHESTRATOR_TRIGGER_RE.search(last_user_input):
        _persist_session_marker(env_mod, cid, "explicit_trigger")
        return True, "explicit_trigger"

    transcript_hit = _scan_transcript_for_activation(scan_lines)
    if transcript_hit == "transcript_user_trigger":
        _persist_session_marker(env_mod, cid, "transcript_user_trigger")
        return True, "transcript_user_trigger"
    if transcript_hit == "station_token":
        return True, "station_token"

    return False, "vanilla_session"


def should_enforce_hooks(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Evaluate kill switch, exemptions, strict/AFK overrides, and session gating."""
    env_mod = _load_env_module()
    if os.environ.get("EDGE_HOOKS", "").strip().lower() == "off":
        return False, "hooks_off"
    cfg = env_mod.load_machine_config()
    if str(cfg.hooks_mode).strip().lower() == "off":
        return False, "hooks_off"

    head_lines, scan_lines = _read_bounded_transcript(env_mod, payload)
    if _is_no_mistakes_exempt(payload, head_lines):
        return False, "no_mistakes_exempt"
    if str(cfg.hooks_mode).strip().lower() == "strict":
        return True, "machine_config_strict"
    if _is_afk_active(head_lines):
        return True, "afk_session"

    return _evaluate_session_gate(env_mod, payload, scan_lines)


def _delegate_to_guard(mode: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    root_str = str(_get_plugin_root())
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    from tools.brigade import orchestrator_guard

    if mode == "pre_invocation":
        return orchestrator_guard.handle_pre_invocation(payload)
    if mode == "post_tool":
        return orchestrator_guard.handle_post_tool(payload)
    return orchestrator_guard.handle_pre_tool(payload)


def _read_stdin_payload() -> Dict[str, Any]:
    raw_input = sys.stdin.read()
    if not raw_input or not raw_input.strip():
        return {}
    try:
        parsed = json.loads(raw_input)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre_tool"
    try:
        payload = _read_stdin_payload()
        enforced, _ = should_enforce_hooks(payload)
        result = _delegate_to_guard(mode, payload) if enforced else _fail_open_response(mode)
    except Exception:
        result = _fail_open_response(mode)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
