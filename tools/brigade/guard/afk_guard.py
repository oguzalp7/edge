"""AFK overnight guard and schema/test strict locks (stdlib-only)."""

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from tools.brigade.guard.role_detection import get_target_file, to_wsl_path

_MUTATION_TOOLS = ("write_file", "edit_file", "write_to_file", "replace_file_content")


def _scan_afk_file(tp: Path) -> Tuple[bool, str]:
    try:
        with open(tp, "r", encoding="utf-8-sig", errors="ignore") as f:
            head = [next(f, "") for _ in range(25)]
    except Exception:
        return False, ""
    for line in head:
        low = line.lower()
        if "[edge_afk" in low:
            mode = "yolo" if "[edge_afk:yolo]" in low else ("strict" if "[edge_afk:strict]" in low else "")
            return True, mode
    return False, ""


def _detect_transcript_afk_signal(transcript_path: Optional[str]) -> Tuple[bool, str]:
    tp = to_wsl_path(str(transcript_path)) if transcript_path else None
    if not tp or not tp.is_file():
        return False, ""
    return _scan_afk_file(tp)


def is_afk_session(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Evaluate dual-signal AFK mode detection (EDGE_AFK env or [EDGE_AFK] transcript tag)."""
    signal_a = os.environ.get("EDGE_AFK") == "1"
    env_mode = os.environ.get("EDGE_AFK_MODE", "").lower().strip()
    transcript_path = payload.get("transcriptPath") if isinstance(payload, dict) else None
    signal_b, transcript_mode = _detect_transcript_afk_signal(transcript_path)
    if not (signal_a or signal_b):
        return False, "strict"
    return True, ("yolo" if (env_mode == "yolo" or transcript_mode == "yolo") else "strict")


def _find_profile_repo_root(target_file: str) -> Optional[Path]:
    p = Path(target_file)
    if not p.is_absolute():
        return None
    return next((anc for anc in (p.parent, *p.parents) if (anc / ".edge" / "profile.json").is_file()), None)


def _is_schema_target(target_file: str) -> bool:
    repo_root = _find_profile_repo_root(target_file)
    if repo_root is not None:
        from tools.common.profiles import is_stack_gate_enabled, resolve_active_profiles

        profiles = resolve_active_profiles(repo_root)
        if profiles.source in ("explicit", "explicit_none") and not is_stack_gate_enabled(profiles, "migration_gate"):
            globs = [*(profiles.paths.get("schema_globs") or ()), *(profiles.paths.get("migration_globs") or ())]
            prefixes = tuple(g.rstrip("*").lstrip("/") for g in globs if g)
            return bool(prefixes) and any(p in target_file for p in prefixes)
    return any(p in target_file for p in ("db/schema/", "drizzle/")) or target_file.startswith(("db/schema/", "drizzle/"))


def _check_strict_afk_target(target_file: str) -> Optional[Dict[str, Any]]:
    if _is_schema_target(target_file):
        return {"decision": "deny", "reason": f"❌ [MIGRATIONGATE GUARD]: Target '{target_file}' is locked in strict mode. Autonomous overnight sessions cannot mutate database schemas or migrations."}
    if any(p in target_file for p in ("tests/", "test/", ".test.", ".spec.")) or target_file.startswith(("tests/", "test/")):
        return {"decision": "deny", "reason": f"❌ [TEST IMMUTABILITY GUARD]: Target '{target_file}' is a test file. In strict mode, tests cannot be modified or weakened by autonomous overnight sessions."}
    return None


def apply_afk_guard(payload: Dict[str, Any], afk_mode: str) -> Optional[Dict[str, Any]]:
    """Enforce AFK invariants (single-agent, HITL state lock, strict schema/test locks)."""
    tool_call = payload.get("toolCall", {}) if isinstance(payload, dict) else {}
    tool_name, args = tool_call.get("name", ""), tool_call.get("args", {})
    if tool_name in ("invoke_subagent", "swarm"):
        return {
            "decision": "deny",
            "reason": "❌ [EDGE AFK GUARD]: Autonomous overnight sessions run strictly as a single agent. Spawning child subagents or swarm workers (invoke_subagent / swarm) is strictly prohibited to prevent quota leaks and zombie loops.",
        }
    if tool_name not in _MUTATION_TOOLS:
        return None
    target_file = get_target_file(args)
    if any(p in target_file for p in (".edge/brigade.json", ".edge/checkpoint.json", "edge_active_stations.json")):
        return {"decision": "deny", "reason": "❌ [EDGE AFK STATE GUARD]: Autonomous overnight sessions cannot mutate human-in-the-loop coordination state (.edge/brigade.json, .edge/checkpoint.json, edge_active_stations.json)."}
    return _check_strict_afk_target(target_file) if afk_mode == "strict" else None
