"""
Empty search chains and token bloat extraction for TranscriptGraphHarvester.
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from tools.distill.harvester_nav_cmds import _extract_tool_file_path, _is_search_only_call
from tools.distill.harvester_nav_reads import _extract_exploration_burst, _extract_redundant_reads
from tools.distill.harvester_signals import _gather_subsequent_result_list, _has_explicit_runtime_error
from tools.distill.models import NavigationFrictionSignal


def _is_empty_search_output(text: str) -> bool:
    stripped = re.sub(
        r"^(?:Created At:|Completed At:|Command exited with code\s+\d+\.?).*$",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    if _has_explicit_runtime_error(stripped):
        return False
    body = stripped.strip()
    if not body:
        return True
    return bool(re.search(r"\b(?:no results found|0 matches|no matches found|0 files)\b", body, re.IGNORECASE))


def _search_call_query(tc: Dict[str, Any]) -> str:
    args = tc.get("args", {})
    return str(args.get("Query") or args.get("Pattern") or args.get("CommandLine") or tc.get("name", ""))[:40]


def _turn_search_status(steps: List[Dict[str, Any]], idx: int) -> Tuple[bool, bool, List[str]]:
    tool_calls = steps[idx].get("tool_calls", [])
    search_indices = [i for i, tc in enumerate(tool_calls) if _is_search_only_call(tc)]
    if not search_indices:
        return False, False, []
    results = _gather_subsequent_result_list(steps, idx)
    fallback = "\n".join(results)
    for i in search_indices:
        res_text = results[i] if i < len(results) else fallback
        if not _is_empty_search_output(res_text):
            return True, False, []
    return True, True, [_search_call_query(tool_calls[i]) for i in search_indices]


def _build_empty_search_signal(cid: str, role: str, start_idx: int, streak: int, queries: List[str]) -> NavigationFrictionSignal:
    return NavigationFrictionSignal(
        signal_type="EMPTY_SEARCH_CHAIN",
        session_id=cid,
        role=role,
        step_index=start_idx,
        file_paths=[],
        count=streak,
        metric_value=streak,
        summary=f"{streak} consecutive empty searches: {', '.join(queries[:3])}",
    )


def _extract_empty_search_chains(cid: str, steps: List[Dict[str, Any]], role: str) -> List[NavigationFrictionSignal]:
    signals: List[NavigationFrictionSignal] = []
    streak = 0
    streak_start = 0
    queries: List[str] = []

    for idx, step in enumerate(steps):
        has_search, all_empty, turn_queries = _turn_search_status(steps, idx)
        if not has_search:
            continue
        if all_empty:
            if streak == 0:
                streak_start = int(step.get("step_index", idx))
            streak += 1
            queries.extend(turn_queries)
        else:
            if streak >= 2:
                signals.append(_build_empty_search_signal(cid, role, streak_start, streak, queries))
            streak = 0
            queries = []

    if streak >= 2:
        signals.append(_build_empty_search_signal(cid, role, streak_start, streak, queries))
    return signals


def _describe_tool_call_source(step: Dict[str, Any], idx: int) -> Tuple[int, str, List[str]]:
    s_idx = int(step.get("step_index", idx))
    tool_calls = step.get("tool_calls", [])
    if len(tool_calls) == 1:
        tname = str(tool_calls[0].get("name", "tool"))
        fp = _extract_tool_file_path(tool_calls[0].get("args", {}))
        return s_idx, tname, ([fp] if fp else [])
    return s_idx, "parallel_tools", []


def _extract_token_bloat_signals(cid: str, steps: List[Dict[str, Any]], role: str) -> List[NavigationFrictionSignal]:
    signals: List[NavigationFrictionSignal] = []
    last_tool: Optional[Tuple[int, str, List[str]]] = None
    for idx, step in enumerate(steps):
        if step.get("tool_calls"):
            last_tool = _describe_tool_call_source(step, idx)
            continue
        if step.get("type") not in ("TOOL_RESULT", "GENERIC") and step.get("source") != "GENERIC":
            continue
        content = str(step.get("content", ""))
        if len(content) < 12000:
            continue
        attr_idx, attr_tool, attr_paths = last_tool or (int(step.get("step_index", idx)), "unknown", [])
        signals.append(
            NavigationFrictionSignal(
                signal_type="TOKEN_BLOAT",
                session_id=cid,
                role=role,
                step_index=attr_idx,
                file_paths=attr_paths,
                count=1,
                metric_value=len(content),
                summary=f"{attr_tool} returned {len(content)} chars (~{len(content) // 4} est. tokens)",
            )
        )
    return signals


def _extract_navigation_frictions_from_steps(
    cid: str,
    steps: List[Dict[str, Any]],
    role: str = "unknown",
) -> List[NavigationFrictionSignal]:
    """Deterministically extracts exploration bursts, redundant reads, empty search chains, and token bloat."""
    signals: List[NavigationFrictionSignal] = []
    burst = _extract_exploration_burst(cid, steps, role)
    if burst:
        signals.append(burst)
    signals.extend(_extract_redundant_reads(cid, steps, role))
    signals.extend(_extract_empty_search_chains(cid, steps, role))
    signals.extend(_extract_token_bloat_signals(cid, steps, role))
    return signals
