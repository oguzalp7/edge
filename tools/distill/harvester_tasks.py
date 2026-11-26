"""
Background task kill and polling hang detection helpers for TranscriptGraphHarvester.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.distill.models import ToolFrictionSignal


def _find_task_log_file(tasks_dir: Path, task_id: str) -> Optional[Path]:
    candidate = tasks_dir / f"{task_id}.log"
    if candidate.is_file():
        return candidate
    matches = list(tasks_dir.glob(f"*{task_id}*.log"))
    return matches[0] if matches else None


def _read_task_log_tail(session_dir: Optional[Path], task_id: str, max_lines: int = 10) -> str:
    if not task_id or not session_dir or not session_dir.is_dir():
        return ""
    tasks_dir = session_dir / ".system_generated" / "tasks"
    if not tasks_dir.is_dir():
        return ""
    candidate = _find_task_log_file(tasks_dir, task_id)
    if not candidate:
        return ""
    try:
        lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail).strip()
    except Exception:
        return ""


def _build_kill_signal(cid: str, idx: int, task_id: str, ts: str, session_dir: Optional[Path]) -> ToolFrictionSignal:
    log_tail = _read_task_log_tail(session_dir, task_id)
    err_msg = f"Task {task_id} was forcefully killed by agent."
    if log_tail:
        err_msg += f" Log tail:\n{log_tail}"
    return ToolFrictionSignal(
        signal_id=f"SIG-KILL-{cid[:8]}-{idx}",
        tool_name="manage_task",
        command_or_args=f"manage_task kill TaskId={task_id}",
        error_output=err_msg,
        conversation_id=cid,
        step_index=idx,
        timestamp=ts,
        exit_code=-9,
        error_type="TASK_KILLED",
    )


def _build_hang_signal(cid: str, idx: int, task_id: str, count: int, ts: str, session_dir: Optional[Path]) -> ToolFrictionSignal:
    log_tail = _read_task_log_tail(session_dir, task_id)
    err_msg = f"Background task {task_id} hung or required excessive polling ({count} consecutive checks)."
    if log_tail:
        err_msg += f" Log tail:\n{log_tail}"
    return ToolFrictionSignal(
        signal_id=f"SIG-HANG-{cid[:8]}-{idx}",
        tool_name="manage_task",
        command_or_args=f"manage_task status TaskId={task_id} (polled {count}x)",
        error_output=err_msg,
        conversation_id=cid,
        step_index=idx,
        timestamp=ts,
        exit_code=None,
        error_type="BACKGROUND_HANG",
        retry_count=count,
    )


def _process_manage_task_call(
    tc: Dict[str, Any],
    step: Dict[str, Any],
    idx: int,
    cid: str,
    session_dir: Optional[Path],
    status_counts: Dict[str, int],
    last_polled_task: List[Optional[str]],
) -> Optional[ToolFrictionSignal]:
    args = tc.get("args", {})
    action = str(args.get("Action", "")).lower()
    task_id = str(args.get("TaskId", ""))
    ts = step.get("created_at") or datetime.now(timezone.utc).isoformat()

    if action == "kill":
        status_counts.pop(task_id, None)
        return _build_kill_signal(cid, idx, task_id, ts, session_dir)

    if action == "status":
        if last_polled_task[0] == task_id:
            status_counts[task_id] = status_counts.get(task_id, 1) + 1
        else:
            status_counts.clear()
            status_counts[task_id] = 1
        last_polled_task[0] = task_id
        count = status_counts[task_id]
        return _build_hang_signal(cid, idx, task_id, count, ts, session_dir) if count == 3 else None

    status_counts.pop(task_id, None)
    return None


def _extract_background_task_hangs(
    steps: List[Dict[str, Any]],
    session_dir: Optional[Path],
    cid: str,
) -> List[ToolFrictionSignal]:
    signals: List[ToolFrictionSignal] = []
    status_counts: Dict[str, int] = {}
    last_polled_task: List[Optional[str]] = [None]

    for idx, step in enumerate(steps):
        for tc in step.get("tool_calls", []):
            if tc.get("name") != "manage_task":
                status_counts.clear()
                last_polled_task[0] = None
                continue
            sig = _process_manage_task_call(tc, step, idx, cid, session_dir, status_counts, last_polled_task)
            if sig:
                signals.append(sig)
    return signals
