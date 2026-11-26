"""
Exploration burst and redundant read streak extraction for TranscriptGraphHarvester.
"""

from typing import Any, Dict, List, Optional, Tuple

from tools.distill.harvester_nav_cmds import _extract_tool_file_path, _is_read_or_search_call
from tools.distill.harvester_signals import MUTATION_TOOLS, READ_ONLY_TOOLS
from tools.distill.models import NavigationFrictionSignal


def _scan_pre_edit_reads(steps: List[Dict[str, Any]]) -> Tuple[int, Optional[int], int, List[str]]:
    read_count = 0
    last_read_step = 0
    unique_paths: List[str] = []
    for idx, step in enumerate(steps):
        s_idx = int(step.get("step_index", idx))
        for tc in step.get("tool_calls", []):
            if tc.get("name", "") in MUTATION_TOOLS:
                return read_count, s_idx, last_read_step, unique_paths
            if not _is_read_or_search_call(tc):
                continue
            read_count += 1
            last_read_step = s_idx
            fp = _extract_tool_file_path(tc.get("args", {}))
            if fp and fp not in unique_paths:
                unique_paths.append(fp)
    return read_count, None, last_read_step, unique_paths


def _extract_exploration_burst(cid: str, steps: List[Dict[str, Any]], role: str) -> Optional[NavigationFrictionSignal]:
    read_count, first_mut_step, last_read_step, unique_paths = _scan_pre_edit_reads(steps)
    if first_mut_step is not None and read_count >= 8:
        return NavigationFrictionSignal(
            signal_type="EXPLORATION_BURST",
            session_id=cid,
            role=role,
            step_index=first_mut_step,
            file_paths=unique_paths[:5],
            count=read_count,
            metric_value=read_count,
            summary=f"{read_count} read/search calls before first edit",
        )
    if first_mut_step is None and read_count >= 10:
        return NavigationFrictionSignal(
            signal_type="EXPLORATION_BURST",
            session_id=cid,
            role=role,
            step_index=last_read_step,
            file_paths=unique_paths[:5],
            count=read_count,
            metric_value=read_count,
            summary=f"{read_count} read/search calls with zero edits",
        )
    return None


def _reset_path_read_streaks(streaks: Dict[Tuple[str, Any, Any], int], norm_path: str) -> None:
    for key in list(streaks.keys()):
        if key[0] == norm_path:
            streaks[key] = 0


def _record_read_streak(
    key: Tuple[str, Any, Any],
    s_idx: int,
    streaks: Dict[Tuple[str, Any, Any], int],
    max_streaks: Dict[Tuple[str, Any, Any], int],
    second_step: Dict[Tuple[str, Any, Any], int],
) -> None:
    cnt = streaks.get(key, 0) + 1
    streaks[key] = cnt
    if cnt == 2 and key not in second_step:
        second_step[key] = s_idx
    if cnt > max_streaks.get(key, 0):
        max_streaks[key] = cnt


def _build_redundant_read_signals(
    cid: str,
    role: str,
    max_streaks: Dict[Tuple[str, Any, Any], int],
    second_step: Dict[Tuple[str, Any, Any], int],
) -> List[NavigationFrictionSignal]:
    return [
        NavigationFrictionSignal(
            signal_type="REDUNDANT_READ",
            session_id=cid,
            role=role,
            step_index=second_step[key],
            file_paths=[key[0]],
            count=max_cnt,
            metric_value=max_cnt,
            summary=f"Read {key[0]} ({key[1]}..{key[2]}) {max_cnt}x without edit",
        )
        for key, max_cnt in max_streaks.items()
        if max_cnt >= 2
    ]


def _extract_redundant_reads(cid: str, steps: List[Dict[str, Any]], role: str) -> List[NavigationFrictionSignal]:
    streaks: Dict[Tuple[str, Any, Any], int] = {}
    max_streaks: Dict[Tuple[str, Any, Any], int] = {}
    second_step: Dict[Tuple[str, Any, Any], int] = {}
    for idx, step in enumerate(steps):
        s_idx = int(step.get("step_index", idx))
        for tc in step.get("tool_calls", []):
            tname = tc.get("name", "")
            args = tc.get("args", {})
            fpath = _extract_tool_file_path(args)
            if not fpath:
                continue
            if tname in READ_ONLY_TOOLS:
                _record_read_streak((fpath, args.get("StartLine"), args.get("EndLine")), s_idx, streaks, max_streaks, second_step)
            elif tname in MUTATION_TOOLS:
                _reset_path_read_streaks(streaks, fpath)
    return _build_redundant_read_signals(cid, role, max_streaks, second_step)
