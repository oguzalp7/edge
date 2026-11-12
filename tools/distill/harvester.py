import time
#!/usr/bin/env python3
"""
Deterministic TranscriptGraphHarvester for edge-distill v2.
Traverses Antigravity session transcripts, reconstructs parent-child station graphs,
and extracts zero-token signals (station escapes, tool friction, user escalations, flight recorder).
"""

import os
import sys
import json
import re
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timezone
import hashlib

from tools.distill.state import FactoryInbox
from tools.distill.models import (
    FrictionDigest,
    StationEscapeSignal,
    ToolFrictionSignal,
    RepeatedEscalation,
    DistillWatermarkState,
)


def _load_jsonl_steps(transcript_path: Path) -> List[Dict[str, Any]]:
    steps = []
    if not transcript_path.exists():
        return steps
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        steps.append(data)
                except Exception:
                    continue
    except Exception:
        pass
    return steps


def _step_uris_match(step: Dict[str, Any], proj_str: str, proj_name: str) -> bool:
    uris = step.get("workspaceUris") or step.get("workspace_uris") or []
    for u in uris:
        u_str = str(u).replace("\\", "/").lower()
        if proj_str in u_str or proj_name in u_str:
            return True
    return False


def _step_tools_match(step: Dict[str, Any], proj_str: str, proj_name: str) -> bool:
    for tc in step.get("tool_calls", []):
        for val in tc.get("args", {}).values():
            val_str = str(val).replace("\\", "/").lower()
            if proj_str in val_str or proj_name in val_str:
                return True
    return False


def _matches_project(steps: List[Dict[str, Any]], project_path: Path) -> bool:
    proj_name = project_path.name.lower()
    proj_str = project_path.as_posix().lower()

    for step in steps:
        if _step_uris_match(step, proj_str, proj_name):
            return True
        if _step_tools_match(step, proj_str, proj_name):
            return True
    return False


def _gather_subsequent_results(steps: List[Dict[str, Any]], start_idx: int) -> str:
    result_text = ""
    for next_step in steps[start_idx + 1:]:
        stype = next_step.get("type")
        source = next_step.get("source")
        if stype in ("PLANNER_RESPONSE", "USER_INPUT") or source == "USER_EXPLICIT":
            break
        if stype in ("TOOL_RESULT", "GENERIC") or source == "GENERIC":
            result_text += " " + str(next_step.get("content", ""))
    return result_text


def _has_explicit_runtime_error(text: str) -> bool:
    markers = [
        "Encountered error in tool execution",
        "Traceback (most recent call last)",
        "AssertionError",
        "SyntaxError",
        "ModuleNotFoundError",
    ]
    if any(m in text for m in markers):
        return True
    if re.search(r"\berror TS\d+\b", text, re.IGNORECASE):
        return True
    return "WSL (" in text


def _detect_error_and_exit_code(result_text: str) -> Tuple[bool, Optional[int]]:
    is_zero_exit = bool(re.search(r"(?:Command exited with code\s+0\b|exit(?: code|=)\s*0\b)", result_text))
    if is_zero_exit and not _has_explicit_runtime_error(result_text):
        return False, None

    m_code = re.search(r"(?:Command exited with code\s+([1-9]\d*)\b|exit(?: code|=)\s*([1-9]\d*)\b)", result_text)
    if m_code:
        code_str = m_code.group(1) or m_code.group(2)
        return True, int(code_str)

    if _has_explicit_runtime_error(result_text):
        return True, None

    if "fatal:" in result_text:
        return True, 128

    if any(m in result_text for m in ("FAIL ", "FAILED", "npm ERR!", "Command failed")):
        return True, 1

    return False, None


def _build_tool_friction_signal(
    cid: str,
    step: Dict[str, Any],
    idx: int,
    tc: Dict[str, Any],
    result_text: str,
    exit_code: Optional[int],
) -> ToolFrictionSignal:
    tname = tc.get("name", "tool")
    args = tc.get("args", {})
    cmd = args.get("CommandLine", str(args))
    return ToolFrictionSignal(
        signal_id=f"SIG-TOOL-{cid[:8]}-{idx}",
        tool_name=tname,
        command_or_args=cmd,
        error_output=result_text.strip()[:300],
        conversation_id=cid,
        step_index=idx,
        timestamp=step.get("created_at", datetime.now(timezone.utc).isoformat()),
        exit_code=exit_code,
        error_type="COMMAND_FAILURE",
    )


def _extract_tool_frictions_from_steps(cid: str, steps: List[Dict[str, Any]]) -> List[ToolFrictionSignal]:
    signals: List[ToolFrictionSignal] = []
    for idx, step in enumerate(steps):
        tool_calls = step.get("tool_calls", [])
        if not tool_calls:
            continue

        result_text = _gather_subsequent_results(steps, idx)
        has_error, exit_code = _detect_error_and_exit_code(result_text)
        if not has_error:
            continue

        for tc in tool_calls:
            signals.append(_build_tool_friction_signal(cid, step, idx, tc, result_text, exit_code))
    return signals


def _check_examiner_escape(steps: List[Dict[str, Any]], idx: int, cid: str) -> Optional[StationEscapeSignal]:
    step = steps[idx]
    content = str(step.get("content", ""))
    if "EXAMINER" not in content or ("PASS" not in content and "PASSED" not in content):
        return None

    for next_step in steps[idx + 1: idx + 4]:
        nxt_content = str(next_step.get("content", ""))
        if "FAILED" in nxt_content or "exit code 1" in nxt_content or "FAIL" in nxt_content:
            return StationEscapeSignal(
                signal_id=f"SIG-ESC-EXAM-{cid[:8]}-{idx}",
                station_role="EXAMINER",
                escape_type="ESCAPED_DEFECT",
                description="Examiner passed code that failed verification gate",
                evidence=nxt_content[:200],
                timestamp=step.get("created_at", datetime.now(timezone.utc).isoformat()),
                conversation_id=cid,
                step_index=idx,
                metadata={"subsequent_error": nxt_content[:100]},
            )
    return None


def _extract_station_escapes_from_steps(cid: str, steps: List[Dict[str, Any]]) -> List[StationEscapeSignal]:
    escapes: List[StationEscapeSignal] = []
    user_terminal_error_count = 0

    for idx, step in enumerate(steps):
        exam_esc = _check_examiner_escape(steps, idx, cid)
        if exam_esc:
            escapes.append(exam_esc)

        content = str(step.get("content", ""))
        if step.get("source") == "USER_EXPLICIT" or step.get("type") == "USER_INPUT":
            if any(sig in content for sig in ["Traceback (most recent call last)", "Error TS", "FAIL ", "npm ERR!", "Here is the terminal", "output:"]):
                user_terminal_error_count += 1

    if user_terminal_error_count >= 3:
        escapes.append(
            StationEscapeSignal(
                signal_id=f"SIG-ESC-MEAT-{cid[:8]}",
                station_role="CODER",
                escape_type="MEAT_PROXY",
                description="User acting as meat-proxy pasting terminal errors 3+ times",
                evidence=f"User pasted terminal output {user_terminal_error_count} times",
                timestamp=datetime.now(timezone.utc).isoformat(),
                conversation_id=cid,
                step_index=None,
            )
        )

    return escapes


def _detect_escalation_role(text: str) -> str:
    lowered = text.lower()
    roles = [
        ("surgeon", "surgeon"),
        ("spec_writer", "spec_writer"),
        ("spec-writer", "spec_writer"),
        ("spec_critic", "spec_critic"),
        ("spec-critic", "spec_critic"),
        ("examiner", "examiner"),
        ("researcher", "researcher"),
        ("seam_architect", "seam_architect"),
        ("seam-architect", "seam_architect"),
        ("qa_engineer", "qa_engineer"),
        ("qa-engineer", "qa_engineer"),
        ("orchestrator", "orchestrator"),
    ]
    for token, role in roles:
        if token in lowered:
            return role
    return "coder"


def _extract_repeated_escalations(all_steps: List[Dict[str, Any]]) -> List[RepeatedEscalation]:
    escalations: List[RepeatedEscalation] = []
    pattern_corrective = re.compile(
        r"(hayır|yanlış|öyle\s+değil|dokunma|bozma|yapma|tekrar|hatalı|don'?t|wrong|stop|revert|broken|testi\s+bozma|kırmızı\s+test|assertionları\s+silme|never\s+modify\s+tests|never\s+loosen\s+tests)",
        re.IGNORECASE,
    )
    occurrences_by_role: Dict[str, List[Dict[str, Any]]] = {}

    for item in all_steps:
        cid = item.get("cid", "")
        step = item.get("step", {})
        if step.get("source") == "USER_EXPLICIT" or step.get("type") == "USER_INPUT":
            text = str(step.get("content", ""))
            if pattern_corrective.search(text):
                role = _detect_escalation_role(text)
                occurrences_by_role.setdefault(role, []).append({
                    "cid": cid,
                    "step_index": step.get("step_index", 0),
                    "text": text,
                    "timestamp": step.get("created_at", ""),
                })

    for role, occurrences in occurrences_by_role.items():
        if len(occurrences) >= 2:
            escalations.append(
                RepeatedEscalation(
                    escalation_id=f"ESC-{role.upper()}-001",
                    category="USER_INSTRUCTION_REPETITION",
                    pattern_key=f"user corrective directive for {role}",
                    occurrence_count=len(occurrences),
                    occurrences=occurrences,
                    rule_recommendation=f"{role.capitalize()} Invariant: Adhere to station rules and user corrective directives",
                    target_role=role,
                )
            )

    return escalations


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


def _collect_workspace_uris(steps: List[Dict[str, Any]]) -> Set[str]:
    all_uris: Set[str] = set()
    for step in steps:
        uris = step.get("workspaceUris") or step.get("workspace_uris") or []
        for u in uris:
            all_uris.add(str(u).replace("\\", "/").lower())
    return all_uris


def _step_references_project(step: Dict[str, Any], proj_str: str) -> bool:
    for tc in step.get("tool_calls", []):
        for val in tc.get("args", {}).values():
            if proj_str in str(val).replace("\\", "/").lower():
                return True
    return False


def _calculate_tool_match_ratio(steps: List[Dict[str, Any]], proj_str: str) -> float:
    total = 0
    matched = 0
    for step in steps:
        if step.get("tool_calls"):
            total += 1
            if _step_references_project(step, proj_str):
                matched += 1
    return (matched / total) if total > 0 else 0.0


def _session_matches_project(steps: List[Dict[str, Any]], project_path: Path) -> bool:
    proj_str = project_path.as_posix().lower()
    all_uris = _collect_workspace_uris(steps)
    if all_uris:
        return any(proj_str in u for u in all_uris)
    return _calculate_tool_match_ratio(steps, proj_str) >= 0.30


def _matches_project(steps: List[Dict[str, Any]], project_path: Path) -> bool:
    return _session_matches_project(steps, project_path)


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
        if count == 3:
            return _build_hang_signal(cid, idx, task_id, count, ts, session_dir)
        return None

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


def _expand_connected_session_graph(
    initial_cids: Set[str],
    parent_to_children: Dict[str, List[str]],
    child_to_parent: Dict[str, str],
) -> Set[str]:
    visited: Set[str] = set(initial_cids)
    queue: List[str] = list(initial_cids)

    while queue:
        curr = queue.pop(0)

        for child in parent_to_children.get(curr, []):
            if child and child not in visited:
                visited.add(child)
                queue.append(child)

        parent = child_to_parent.get(curr)
        if parent and parent not in visited:
            visited.add(parent)
            queue.append(parent)

    return visited


def _calculate_since_cutoff_sec(since_hours: Optional[int]) -> Optional[float]:
    if since_hours and since_hours > 0:
        return since_hours * 3600.0
    return None


def _get_dir_mtime(d: Path) -> float:
    try:
        return d.stat().st_mtime
    except Exception:
        return 0.0


def _collect_root_candidates(root: Path, now_ts: float, cutoff_sec: Optional[float]) -> List[Path]:
    if not root.exists():
        return []
    result: List[Path] = []
    try:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            if _is_entry_within_window(entry, now_ts, cutoff_sec):
                result.append(entry)
    except Exception:
        pass
    return result

def _is_entry_within_window(entry: Path, now_ts: float, cutoff_sec: Optional[float]) -> bool:
    if cutoff_sec is None:
        return True
    mtime = entry.stat().st_mtime if entry.exists() else 0
    return (now_ts - mtime) <= cutoff_sec


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
    proj = [s for s in signals if not _is_harness_signal(s)]
    harness = [s for s in signals if _is_harness_signal(s)]
    return proj, harness


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
    queue: List[Dict[str, Any]] = []
    for f in harness_frictions:
        queue.append(_friction_to_inbox_dict(f, target_path))
    for esc in harness_escapes:
        queue.append(_escape_to_inbox_dict(esc, target_path))
    if queue:
        inbox = FactoryInbox()
        inbox.append_signals(queue)
    return len(queue)


class TranscriptGraphHarvester:
    """
    Deterministic Harvester that extracts zero-token friction and signals from Antigravity session transcripts.
    """
    def __init__(
        self,
        repo_path: Optional[Path] = None,
        brain_roots: Optional[List[Path]] = None,
        active_stations_file: Optional[Path] = None,
        watermark_state: Optional[DistillWatermarkState] = None,
        since_hours: Optional[int] = None,
    ):
        self.repo_path = repo_path.resolve() if repo_path else None
        self.brain_roots = [p.resolve() for p in brain_roots] if brain_roots else self._default_brain_roots()
        self.active_stations_file = active_stations_file.resolve() if active_stations_file else None
        self.watermark_state = watermark_state or DistillWatermarkState()
        self.since_hours = since_hours
        self._session_dirs: Dict[str, Path] = {}

    def _default_brain_roots(self) -> List[Path]:
        roots = []
        home = Path.home()
        candidates = [
            home / ".gemini" / "antigravity" / "brain",
            Path("/mnt/c/Users/oguz_/.gemini/antigravity/brain"),
        ]
        env_root = os.environ.get("GEMINI_BRAIN_ROOT")
        if env_root:
            candidates.insert(0, Path(env_root))
        for c in candidates:
            if c.exists() and c not in roots:
                roots.append(c)
        return roots

    def _load_active_stations_map(self) -> Dict[str, str]:
        stations_map: Dict[str, str] = {}
        if self.active_stations_file and self.active_stations_file.exists():
            try:
                data = json.loads(self.active_stations_file.read_text(encoding="utf-8"))
                for child_cid, info in data.get("stations", {}).items():
                    parent_cid = info.get("parentConversationId")
                    if parent_cid:
                        stations_map[child_cid] = parent_cid
            except Exception:
                pass
        return stations_map

    def _discover_candidates(self) -> List[Path]:
        candidate_dirs: List[Path] = []
        now_ts = time.time()
        cutoff_sec = _calculate_since_cutoff_sec(self.since_hours)

        for root in self.brain_roots:
            candidate_dirs.extend(_collect_root_candidates(root, now_ts, cutoff_sec))

        candidate_dirs.sort(key=_get_dir_mtime, reverse=True)
        if len(candidate_dirs) > 100:
            return candidate_dirs[:100]
        return candidate_dirs

    def _discover_transcripts(self) -> Dict[str, Path]:
        session_transcripts: Dict[str, Path] = {}
        for sess_dir in self._discover_candidates():
            tfile = sess_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if tfile.exists():
                session_transcripts[sess_dir.name] = tfile
                self._session_dirs[sess_dir.name] = sess_dir
        return session_transcripts

    def _inspect_step_relations(self, steps: List[Dict[str, Any]], cid: str, child_to_parent: Dict[str, str], parent_to_children: Dict[str, List[str]]) -> None:
        for step in steps:
            content = str(step.get("content", ""))
            m = re.search(r'"conversationId":\s*"([^"]+)"', content)
            if m:
                child_cid = m.group(1)
                child_to_parent[child_cid] = cid
                parent_to_children.setdefault(cid, []).append(child_cid)

            if step.get("step_index") == 0:
                m_snd = re.search(r'sender=([a-zA-Z0-9_\-]+)', content)
                if m_snd:
                    p_cid = m_snd.group(1)
                    child_to_parent[cid] = p_cid
                    parent_to_children.setdefault(p_cid, []).append(cid)

    def _load_transcripts(self, session_transcripts: Dict[str, Path]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], Dict[str, List[str]]]:
        sessions_steps: Dict[str, List[Dict[str, Any]]] = {}
        child_to_parent: Dict[str, str] = dict(self._load_active_stations_map())
        parent_to_children: Dict[str, List[str]] = {}

        for cid, tpath in session_transcripts.items():
            steps = _load_jsonl_steps(tpath)
            sessions_steps[cid] = steps
            self._inspect_step_relations(steps, cid, child_to_parent, parent_to_children)

        return sessions_steps, child_to_parent, parent_to_children

    def _find_matched_sessions(self, sessions_steps: Dict[str, List[Dict[str, Any]]], target_path: Path, parent_to_children: Dict[str, List[str]], child_to_parent: Dict[str, str]) -> Set[str]:
        matched: Set[str] = set()
        for cid, steps in sessions_steps.items():
            if _session_matches_project(steps, target_path):
                matched.add(cid)
        return _expand_connected_session_graph(matched, parent_to_children, child_to_parent)

    def _is_session_skipped(
        self,
        cid: str,
        current_session_id: Optional[str],
        reprocess: bool,
        mode: str,
        target_path: Optional[Path],
    ) -> bool:
        if reprocess or current_session_id == cid:
            return False
        if mode == "factory":
            return cid in self.watermark_state.factory_processed_sessions
        if mode == "project":
            p_sessions = self.watermark_state.project_sessions.get(str(target_path), []) if target_path else []
            return cid in p_sessions or cid in self.watermark_state.processed_sessions
        return cid in self.watermark_state.processed_sessions

    def _filter_sessions(
        self,
        matched: Set[str],
        current_session_id: Optional[str],
        reprocess: bool,
        max_sessions: int,
        available: Set[str],
        mode: str = "all",
        target_path: Optional[Path] = None,
    ) -> List[str]:
        analyzed: List[str] = []
        for cid in sorted(matched):
            if self._is_session_skipped(cid, current_session_id, reprocess, mode, target_path):
                continue
            analyzed.append(cid)
            if len(analyzed) >= max_sessions:
                break

        if current_session_id and current_session_id not in analyzed and current_session_id in available:
            analyzed.append(current_session_id)
        return analyzed

    def _collect_signals(self, analyzed_sessions: List[str], sessions_steps: Dict[str, List[Dict[str, Any]]]) -> Tuple[List[ToolFrictionSignal], List[StationEscapeSignal], List[RepeatedEscalation]]:
        tool_frictions: List[ToolFrictionSignal] = []
        station_escapes: List[StationEscapeSignal] = []
        flattened_steps: List[Dict[str, Any]] = []

        for cid in analyzed_sessions:
            steps = sessions_steps.get(cid, [])
            sess_dir = self._session_dirs.get(cid)
            tool_frictions.extend(_extract_tool_frictions_from_steps(cid, steps))
            tool_frictions.extend(_extract_background_task_hangs(steps, sess_dir, cid))
            station_escapes.extend(_extract_station_escapes_from_steps(cid, steps))
            for s in steps:
                flattened_steps.append({"cid": cid, "step": s})

        escalations = _extract_repeated_escalations(flattened_steps)
        return tool_frictions, station_escapes, escalations

    def _split_project_signals(
        self,
        frictions_or_signals: Any,
        escapes: Optional[List[StationEscapeSignal]] = None,
        target_path: Optional[Path] = None,
        project_name: Optional[str] = None,
    ) -> Any:
        if escapes is None:
            return _split_single_signal_list(frictions_or_signals)
        proj_f, harness_f = _split_single_signal_list(frictions_or_signals)
        proj_e, harness_e = _split_single_signal_list(escapes)
        harness_queued = _enqueue_harness_signals(harness_f, harness_e, target_path)
        return proj_f, proj_e, harness_queued

    def harvest(
        self,
        project_path: Optional[Path] = None,
        reprocess: bool = False,
        current_session_id: Optional[str] = None,
        max_sessions: int = 50,
        mode: str = "all",
    ) -> FrictionDigest:
        target_path = (project_path or self.repo_path or Path.cwd()).resolve()
        transcripts = self._discover_transcripts()
        sessions_steps, c2p, p2c = self._load_transcripts(transcripts)
        matched = self._find_matched_sessions(sessions_steps, target_path, p2c, c2p)
        analyzed = self._filter_sessions(matched, current_session_id, reprocess, max_sessions, set(transcripts.keys()), mode=mode, target_path=target_path)
        frictions, escapes, escalations = self._collect_signals(analyzed, sessions_steps)

        harness_queued = 0
        inbox_signals: List[Dict[str, Any]] = []

        if mode == "project":
            frictions, escapes, harness_queued = self._split_project_signals(frictions, escapes, target_path)
        elif mode == "factory":
            inbox = FactoryInbox()
            inbox_signals = inbox.load_pending()

        return FrictionDigest(
            digest_id=f"DIGEST-{target_path.name}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            project_path=str(target_path),
            project_name=target_path.name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            sessions_analyzed=analyzed,
            station_escapes=escapes,
            tool_frictions=frictions,
            repeated_escalations=escalations,
            flight_recorder_insights=self._extract_flight_recorder(target_path),
            git_churn=self._extract_git_churn(target_path),
            critique_findings=self._extract_critiques(target_path),
            harness_signals_queued=harness_queued,
            factory_inbox_signals=inbox_signals,
        )

    def _extract_flight_recorder(self, project_path: Path) -> List[Dict[str, Any]]:
        insights: List[Dict[str, Any]] = []
        fr_dir = project_path / ".edge" / "flight-recorder"
        if fr_dir.exists():
            for f in fr_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    for dead in data.get("dead_ends", []):
                        insights.append({"dead_end": dead.get("approach", str(dead)), "details": dead})
                    for gfail in data.get("guard_failures", []):
                        insights.append({"guard_failure": gfail})
                except Exception:
                    pass
        return insights

    def _extract_critiques(self, project_path: Path) -> List[Dict[str, Any]]:
        critiques: List[Dict[str, Any]] = []
        specs_dir = project_path / ".edge" / "specs"
        if specs_dir.exists():
            for f in specs_dir.glob("*critique*.md"):
                try:
                    content = f.read_text(encoding="utf-8")
                    critiques.append({"spec": f.name, "finding": content[:200]})
                except Exception:
                    pass
        return critiques

    def _extract_git_churn(self, project_path: Path) -> List[Dict[str, Any]]:
        churn: List[Dict[str, Any]] = []
        if (project_path / ".git").exists():
            try:
                res = subprocess.run(
                    ["git", "log", "-n", "15", "--grep=revert", "--grep=fixup", "--oneline"],
                    cwd=str(project_path),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if res.returncode == 0 and res.stdout.strip():
                    for line in res.stdout.strip().splitlines():
                        parts = line.split(" ", 1)
                        churn.append({"commit": parts[0], "message": parts[1] if len(parts) > 1 else ""})
            except Exception:
                pass
        return churn
