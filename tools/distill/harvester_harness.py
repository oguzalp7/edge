"""
Harness vs project signal routing and flight-recorder entry parsing.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.distill.models import StationEscapeSignal, ToolFrictionSignal
from tools.distill.state import FactoryInbox

HARNESS_KEYWORDS = (
    "brigade",
    "treehouse",
    "orchestrator_guard",
    "wsl (",
    "tools/distill",
    "tasks-axi",
    "frontier-axi",
    "aborted in state",
    "examiner review: pass",
    "manage_task",
    "background_hang",
    "task_killed",
)


def _is_harness_signal(sig: Any) -> bool:
    if isinstance(sig, ToolFrictionSignal):
        err_type = str(getattr(sig, "error_type", "")).lower()
        if err_type in ("task_killed", "background_hang"):
            return True
        comb = f"{sig.command_or_args} {sig.error_output} {sig.tool_name} {err_type}".lower()
        return any(kw in comb for kw in HARNESS_KEYWORDS)
    if isinstance(sig, StationEscapeSignal):
        comb = f"{sig.description} {sig.evidence} {sig.station_role}".lower()
        return any(kw in comb for kw in HARNESS_KEYWORDS)
    return False


def _split_single_signal_list(signals: List[Any]) -> Tuple[List[Any], List[Any]]:
    return [s for s in signals if not _is_harness_signal(s)], [s for s in signals if _is_harness_signal(s)]


def _friction_to_inbox_dict(f: ToolFrictionSignal, target_path: Optional[Path]) -> Dict[str, Any]:
    return {
        "kind": "HARNESS_FRICTION",
        "source_project": str(target_path) if target_path else "",
        "role_or_tool": f.tool_name or "run_command",
        "summary": f.error_output.strip() or f.command_or_args,
    }


def _escape_to_inbox_dict(esc: StationEscapeSignal, target_path: Optional[Path]) -> Dict[str, Any]:
    return {
        "kind": "STATION_ESCAPE",
        "source_project": str(target_path) if target_path else "",
        "role_or_tool": esc.station_role.lower(),
        "summary": esc.description or esc.evidence,
    }


def _enqueue_harness_signals(
    harness_frictions: List[ToolFrictionSignal],
    harness_escapes: List[StationEscapeSignal],
    target_path: Optional[Path],
) -> int:
    queue = [_friction_to_inbox_dict(f, target_path) for f in harness_frictions]
    queue.extend(_escape_to_inbox_dict(esc, target_path) for esc in harness_escapes)
    if queue:
        FactoryInbox().append_signals(queue)
    return len(queue)


def _parse_dead_end_entry(dead: Any) -> Dict[str, Any]:
    if not isinstance(dead, dict):
        s = str(dead).strip()
        return {"kind": "dead_end", "title": s, "reason": "", "prohibited_rule": "", "dead_end": s, "details": dead}
    title = str(dead.get("title") or dead.get("approach") or "").strip()
    reason = str(dead.get("reason") or "").strip()
    prohibited_rule = str(dead.get("prohibited_rule") or "").strip()
    return {
        "kind": "dead_end",
        "title": title,
        "reason": reason,
        "prohibited_rule": prohibited_rule,
        "dead_end": title or reason or prohibited_rule,
        "details": dead,
    }


def _parse_guard_failure_entry(gfail: Any) -> Dict[str, Any]:
    if not isinstance(gfail, dict):
        return {"kind": "guard_failure", "state": "", "message": str(gfail).strip(), "details": {}, "guard_failure": gfail}
    return {
        "kind": "guard_failure",
        "state": str(gfail.get("state", "")).strip(),
        "message": str(gfail.get("message", "")).strip(),
        "details": gfail.get("details", {}),
        "guard_failure": gfail,
    }
