"""
Station escapes, repeated user escalations, and token estimation for TranscriptGraphHarvester.
"""

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools.distill.harvester_signals import READ_SEARCH_TOOLS
from tools.distill.models import RepeatedEscalation, StationEscapeSignal


def _is_examiner_pass_step(step: Dict[str, Any]) -> bool:
    source = step.get("source")
    stype = step.get("type")
    if source in ("SYSTEM", "USER_EXPLICIT", "GENERIC"):
        return False
    if stype in ("USER_INPUT", "SYSTEM_MESSAGE", "TOOL_RESULT", "GENERIC"):
        return False
    if source != "MODEL" and stype != "PLANNER_RESPONSE":
        return False
    content = str(step.get("content", ""))
    return "EXAMINER" in content and ("PASS" in content or "PASSED" in content)


def _is_read_search_only_result(next_step: Dict[str, Any], last_tool_names: List[str]) -> bool:
    stype = next_step.get("type")
    source = next_step.get("source")
    is_res = stype in ("TOOL_RESULT", "GENERIC") or source == "GENERIC"
    if not is_res or not last_tool_names:
        return False
    return all(tn in READ_SEARCH_TOOLS for tn in last_tool_names)


def _check_examiner_escape(steps: List[Dict[str, Any]], idx: int, cid: str) -> Optional[StationEscapeSignal]:
    step = steps[idx]
    if not _is_examiner_pass_step(step):
        return None
    last_tool_names = [tc.get("name", "") for tc in step.get("tool_calls", [])]
    for next_step in steps[idx + 1 : idx + 4]:
        if next_step.get("tool_calls"):
            last_tool_names = [tc.get("name", "") for tc in next_step.get("tool_calls", [])]
            continue
        if _is_read_search_only_result(next_step, last_tool_names):
            continue
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
    error_sigs = ("Traceback (most recent call last)", "Error TS", "FAIL ", "npm ERR!", "Here is the terminal", "output:")

    for idx, step in enumerate(steps):
        exam_esc = _check_examiner_escape(steps, idx, cid)
        if exam_esc:
            escapes.append(exam_esc)
        if step.get("source") == "USER_EXPLICIT" or step.get("type") == "USER_INPUT":
            if any(sig in str(step.get("content", "")) for sig in error_sigs):
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
    roles = (
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
    )
    for token, role in roles:
        if token in lowered:
            return role
    return "coder"


def _extract_repeated_escalations(all_steps: List[Dict[str, Any]]) -> List[RepeatedEscalation]:
    pattern_corrective = re.compile(
        r"(hayır|yanlış|öyle\s+değil|dokunma|bozma|yapma|tekrar|hatalı|don'?t|wrong|stop|revert|broken|testi\s+bozma|kırmızı\s+test|assertionları\s+silme|never\s+modify\s+tests|never\s+loosen\s+tests)",
        re.IGNORECASE,
    )
    occurrences_by_role: Dict[str, List[Dict[str, Any]]] = {}
    for item in all_steps:
        cid = item.get("cid", "")
        step = item.get("step", {})
        if step.get("source") != "USER_EXPLICIT" and step.get("type") != "USER_INPUT":
            continue
        text = str(step.get("content", ""))
        if pattern_corrective.search(text):
            role = _detect_escalation_role(text)
            occurrences_by_role.setdefault(role, []).append({
                "cid": cid,
                "step_index": step.get("step_index", 0),
                "text": text,
                "timestamp": step.get("created_at", ""),
            })

    return [
        RepeatedEscalation(
            escalation_id=f"ESC-{role.upper()}-001",
            category="USER_INSTRUCTION_REPETITION",
            pattern_key=f"user corrective directive for {role}",
            occurrence_count=len(occurrences),
            occurrences=occurrences,
            rule_recommendation=f"{role.capitalize()} Invariant: Adhere to station rules and user corrective directives",
            target_role=role,
        )
        for role, occurrences in occurrences_by_role.items()
        if len(occurrences) >= 2
    ]


def _estimate_sessions_tokens(
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
) -> int:
    """Computes total character volume // 4 across all analyzed session steps and tool_calls."""
    total_chars = 0
    for cid in analyzed_sessions:
        for step in sessions_steps.get(cid, []):
            total_chars += len(str(step.get("content", "")))
            for tc in step.get("tool_calls", []):
                total_chars += len(json.dumps(tc.get("args", {}), default=str)) + len(str(tc.get("name", "")))
    return total_chars // 4
