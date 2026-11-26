"""
Tool friction extraction helpers for TranscriptGraphHarvester.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from tools.distill.models import ToolFrictionSignal
from tools.distill.state import BENIGN_WSL_RELAY_BANNER_RE

READ_SEARCH_TOOLS = {"read_file", "view_file", "find_by_name", "grep_search", "list_dir"}
SEARCH_ONLY_TOOLS = {"grep_search", "find_by_name"}
READ_ONLY_TOOLS = {"read_file", "view_file"}
MUTATION_TOOLS = {"edit_file", "write_file", "replace_file_content", "multi_replace_file_content"}


def _gather_subsequent_result_list(steps: List[Dict[str, Any]], start_idx: int) -> List[str]:
    results: List[str] = []
    for next_step in steps[start_idx + 1:]:
        stype = next_step.get("type")
        source = next_step.get("source")
        if stype in ("PLANNER_RESPONSE", "USER_INPUT") or source == "USER_EXPLICIT":
            break
        if stype in ("TOOL_RESULT", "GENERIC") or source == "GENERIC":
            results.append(str(next_step.get("content", "")))
    return results


def _gather_subsequent_results(steps: List[Dict[str, Any]], start_idx: int) -> str:
    results = _gather_subsequent_result_list(steps, start_idx)
    return (" " + " ".join(results)) if results else ""


def _has_explicit_runtime_error(text: str) -> bool:
    cleaned_text = BENIGN_WSL_RELAY_BANNER_RE.sub("", text)
    markers = (
        "Encountered error in tool execution",
        "Traceback (most recent call last)",
        "AssertionError",
        "SyntaxError",
        "ModuleNotFoundError",
    )
    if any(m in cleaned_text for m in markers):
        return True
    if re.search(r"\berror TS\d+\b", cleaned_text, re.IGNORECASE):
        return True
    return bool(re.search(r"WSL\s*\(\s*\d+\s*-\s*Relay\s*\)\s*ERROR:", cleaned_text, re.IGNORECASE))


def _detect_read_search_tool_error(result_text: str) -> Tuple[bool, Optional[int]]:
    is_zero_exit = bool(re.search(r"(?:Command exited with code\s+0\b|exit(?: code|=)\s*0\b)", result_text))
    if is_zero_exit and "Encountered error in tool execution" not in result_text:
        return False, None
    m_code = re.search(r"Command exited with code\s+([1-9]\d*)\b", result_text)
    if m_code:
        return True, int(m_code.group(1))
    if "Encountered error in tool execution" in result_text:
        return True, None
    return False, None


def _detect_error_and_exit_code(result_text: str) -> Tuple[bool, Optional[int]]:
    is_zero_exit = bool(re.search(r"(?:Command exited with code\s+0\b|exit(?: code|=)\s*0\b)", result_text))
    if is_zero_exit and not _has_explicit_runtime_error(result_text):
        return False, None
    m_code = re.search(r"(?:Command exited with code\s+([1-9]\d*)\b|exit(?: code|=)\s*([1-9]\d*)\b)", result_text)
    if m_code:
        return True, int(m_code.group(1) or m_code.group(2))
    if _has_explicit_runtime_error(result_text):
        return True, None
    if "fatal:" in result_text:
        return True, 128
    if any(m in result_text for m in ("FAIL ", "FAILED", "npm ERR!", "Command failed")):
        return True, 1
    return False, None


def _evaluate_tool_call_friction(
    tc: Dict[str, Any],
    tc_text: str,
    multi_unaligned: bool,
) -> Tuple[bool, Optional[int]]:
    if tc.get("name", "") in READ_SEARCH_TOOLS:
        if multi_unaligned:
            return ("Encountered error in tool execution" in tc_text), None
        return _detect_read_search_tool_error(tc_text)
    return _detect_error_and_exit_code(tc_text)


def _build_tool_friction_signal(
    cid: str,
    step: Dict[str, Any],
    idx: int,
    tc: Dict[str, Any],
    result_text: str,
    exit_code: Optional[int],
) -> ToolFrictionSignal:
    args = tc.get("args", {})
    return ToolFrictionSignal(
        signal_id=f"SIG-TOOL-{cid[:8]}-{idx}",
        tool_name=tc.get("name", "tool"),
        command_or_args=args.get("CommandLine", str(args)),
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
        results_list = _gather_subsequent_result_list(steps, idx)
        aligned = len(results_list) == len(tool_calls)
        multi_unaligned = (not aligned) and len(tool_calls) > 1
        joined_text = (" " + " ".join(results_list)) if not aligned else ""
        for i, tc in enumerate(tool_calls):
            tc_text = results_list[i] if aligned else joined_text
            has_error, exit_code = _evaluate_tool_call_friction(tc, tc_text, multi_unaligned)
            if has_error:
                signals.append(_build_tool_friction_signal(cid, step, idx, tc, tc_text, exit_code))
    return signals
