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

from tools.common.paths import to_wsl_path
from tools.distill.state import FactoryInbox, collect_budget_targets
from tools.distill.models import (
    FrictionDigest,
    StationEscapeSignal,
    ToolFrictionSignal,
    RepeatedEscalation,
    DistillWatermarkState,
    NavigationFrictionSignal,
    GuardrailGapSignal,
    RuleInventoryItem,
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


def _read_json_safe(fpath: Path) -> Optional[Dict[str, Any]]:
    if not fpath.is_file():
        return None
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_match_path(raw: Optional[str]) -> str:
    """Symmetrically normalizes file:// URIs, Windows UNC paths, and WSL paths."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    low = s.lower()
    if low.startswith("file:///\\"):
        s = s[8:]
    elif low.startswith("file://wsl.localhost/") or low.startswith("file://wsl$/"):
        s = "//" + s[7:]
    elif low.startswith("file://"):
        s = s[7:]
        if re.match(r"^/[a-zA-Z]:/", s):
            s = s[1:]
    return to_wsl_path(s).replace("\\", "/").rstrip("/").lower()


def _collect_worktree_aliases(project_path: Path) -> List[str]:
    """Collects active worktree aliases from .edge/brigade.json and .edge/checkpoint.json."""
    aliases: List[str] = []
    for rel in (".edge/brigade.json", ".edge/checkpoint.json"):
        data = _read_json_safe(project_path / rel)
        if not data:
            continue
        ticket = data.get("active_ticket")
        wt_ticket = ticket.get("worktree_path") if isinstance(ticket, dict) else None
        for raw in (data.get("active_worktree"), wt_ticket):
            norm = _normalize_match_path(raw)
            if norm and norm not in aliases:
                aliases.append(norm)
    return aliases


def _matches_treehouse_slot(text: str, project_name: str) -> bool:
    if not text or not project_name:
        return False
    norm = _normalize_match_path(text) or text.replace("\\", "/").lower()
    pname = project_name.strip().lower()
    return bool(re.search(rf"/\.treehouse/pool/[^/]+/{re.escape(pname)}(?:/|$)", norm))


def _collect_workspace_uris(steps: List[Dict[str, Any]]) -> Set[str]:
    all_uris: Set[str] = set()
    for step in steps:
        uris = step.get("workspaceUris") or step.get("workspace_uris") or []
        for u in uris:
            norm = _normalize_match_path(str(u))
            if norm:
                all_uris.add(norm)
    return all_uris


def _text_matches_targets(raw_text: str, target_strs: List[str], proj_name: str) -> bool:
    norm = _normalize_match_path(raw_text) or raw_text.replace("\\", "/").lower()
    if any(t in norm for t in target_strs):
        return True
    return _matches_treehouse_slot(norm, proj_name)


def _step_references_project(step: Dict[str, Any], target_strs: List[str], proj_name: str = "") -> bool:
    for tc in step.get("tool_calls", []):
        for val in tc.get("args", {}).values():
            if _text_matches_targets(str(val), target_strs, proj_name):
                return True
    return False


def _calculate_tool_match_ratio(steps: List[Dict[str, Any]], target_strs: List[str], proj_name: str = "") -> float:
    total = 0
    matched = 0
    for step in steps:
        if step.get("tool_calls"):
            total += 1
            if _step_references_project(step, target_strs, proj_name):
                matched += 1
    return (matched / total) if total > 0 else 0.0


def _session_matches_project(
    steps: List[Dict[str, Any]],
    project_path: Path,
    extra_project_paths: Optional[List[str]] = None,
) -> bool:
    target_strs: List[str] = []
    for raw in [str(project_path)] + list(extra_project_paths or []):
        norm = _normalize_match_path(raw)
        if norm and norm not in target_strs:
            target_strs.append(norm)
    proj_name = project_path.name.lower()

    all_uris = _collect_workspace_uris(steps)
    if all_uris:
        return any(_text_matches_targets(u, target_strs, proj_name) for u in all_uris)
    return _calculate_tool_match_ratio(steps, target_strs, proj_name) >= 0.30


def _matches_project(steps: List[Dict[str, Any]], project_path: Path) -> bool:
    return _session_matches_project(steps, project_path)


READ_SEARCH_TOOLS = {"read_file", "view_file", "find_by_name", "grep_search", "list_dir"}
SEARCH_ONLY_TOOLS = {"grep_search", "find_by_name"}
READ_ONLY_TOOLS = {"read_file", "view_file"}
MUTATION_TOOLS = {"edit_file", "write_file", "replace_file_content", "multi_replace_file_content"}
READ_SEARCH_CMDS = {"rg", "grep", "find", "git grep", "ls", "tree"}
SEARCH_ONLY_CMDS = {"rg", "grep", "find", "git grep"}
_WSL_VALUE_FLAGS = {"--cd", "-d", "--distribution", "-u", "--user"}


def _extract_tool_file_path(args: Dict[str, Any]) -> str:
    if not isinstance(args, dict):
        return ""
    raw = args.get("Path") or args.get("AbsolutePath") or args.get("TargetFile") or ""
    return str(raw).replace("\\", "/").strip()


def _peel_wsl_prefix(tokens: List[str]) -> List[str]:
    idx = 1
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in _WSL_VALUE_FLAGS:
            idx += 2
        elif tok.startswith("-"):
            idx += 1
        else:
            break
    return tokens[idx:]


def _peel_command_wrappers(tokens: List[str]) -> List[str]:
    while tokens:
        head = Path(tokens[0].strip("'\"")).name.lower()
        if head == "wsl":
            tokens = _peel_wsl_prefix(tokens)
        elif head in ("bash", "sh", "zsh") and len(tokens) >= 2 and tokens[1] in ("-c", "-lc"):
            tokens = [tokens[2].lstrip("'\"")] + tokens[3:] if len(tokens) > 2 else []
        elif head == "env":
            tokens = [t for t in tokens[1:] if "=" not in t]
        else:
            break
    return tokens


def _segment_command_verb(segment: str) -> Optional[str]:
    tokens = _peel_command_wrappers(segment.strip().split())
    if not tokens:
        return None
    verb0 = Path(tokens[0].strip("'\"")).name.lower()
    if verb0 == "git" and len(tokens) > 1:
        verb1 = tokens[1].strip("'\"").lower()
        return "git grep" if verb1 == "grep" else f"git {verb1}"
    return verb0


def _classify_run_command(cmd: str) -> Tuple[bool, bool]:
    if not cmd:
        return False, False
    is_read = False
    is_search = False
    for seg in re.split(r"\s*(?:&&|\|\||[;|])\s*", cmd):
        verb = _segment_command_verb(seg)
        if verb in READ_SEARCH_CMDS:
            is_read = True
        if verb in SEARCH_ONLY_CMDS:
            is_search = True
    return is_read, is_search


def _is_read_or_search_call(tc: Dict[str, Any]) -> bool:
    tname = tc.get("name", "")
    if tname in READ_SEARCH_TOOLS:
        return True
    if tname == "run_command":
        return _classify_run_command(str(tc.get("args", {}).get("CommandLine", "")))[0]
    return False


def _is_search_only_call(tc: Dict[str, Any]) -> bool:
    tname = tc.get("name", "")
    if tname in SEARCH_ONLY_TOOLS:
        return True
    if tname == "run_command":
        return _classify_run_command(str(tc.get("args", {}).get("CommandLine", "")))[1]
    return False


def _scan_pre_edit_reads(steps: List[Dict[str, Any]]) -> Tuple[int, Optional[int], int, List[str]]:
    read_count = 0
    first_mut_step: Optional[int] = None
    last_read_step = 0
    unique_paths: List[str] = []
    for idx, step in enumerate(steps):
        s_idx = int(step.get("step_index", idx))
        for tc in step.get("tool_calls", []):
            if tc.get("name", "") in MUTATION_TOOLS:
                return read_count, s_idx, last_read_step, unique_paths
            if _is_read_or_search_call(tc):
                read_count += 1
                last_read_step = s_idx
                fp = _extract_tool_file_path(tc.get("args", {}))
                if fp and fp not in unique_paths:
                    unique_paths.append(fp)
    return read_count, first_mut_step, last_read_step, unique_paths


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
    signals: List[NavigationFrictionSignal] = []
    for key, max_cnt in max_streaks.items():
        if max_cnt >= 2:
            signals.append(
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
            )
    return signals


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
                key = (fpath, args.get("StartLine"), args.get("EndLine"))
                _record_read_streak(key, s_idx, streaks, max_streaks, second_step)
            elif tname in MUTATION_TOOLS:
                _reset_path_read_streaks(streaks, fpath)

    return _build_redundant_read_signals(cid, role, max_streaks, second_step)


def _gather_subsequent_result_list(steps: List[Dict[str, Any]], start_idx: int) -> List[str]:
    results: List[str] = []
    for next_step in steps[start_idx + 1 :]:
        stype = next_step.get("type")
        source = next_step.get("source")
        if stype in ("PLANNER_RESPONSE", "USER_INPUT") or source == "USER_EXPLICIT":
            break
        if stype in ("TOOL_RESULT", "GENERIC") or source == "GENERIC":
            results.append(str(next_step.get("content", "")))
    return results


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
    queries = [_search_call_query(tool_calls[i]) for i in search_indices]
    return True, True, queries


def _build_empty_search_signal(cid: str, role: str, start_idx: int, streak: int, queries: List[str]) -> NavigationFrictionSignal:
    q_str = ", ".join(queries[:3])
    return NavigationFrictionSignal(
        signal_type="EMPTY_SEARCH_CHAIN",
        session_id=cid,
        role=role,
        step_index=start_idx,
        file_paths=[],
        count=streak,
        metric_value=streak,
        summary=f"{streak} consecutive empty searches: {q_str}",
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
        stype = step.get("type")
        source = step.get("source")
        if stype in ("TOOL_RESULT", "GENERIC") or source == "GENERIC":
            content = str(step.get("content", ""))
            if len(content) >= 12000:
                attr_idx, attr_tool, attr_paths = last_tool or (int(step.get("step_index", idx)), "unknown", [])
                est_tok = len(content) // 4
                signals.append(
                    NavigationFrictionSignal(
                        signal_type="TOKEN_BLOAT",
                        session_id=cid,
                        role=role,
                        step_index=attr_idx,
                        file_paths=attr_paths,
                        count=1,
                        metric_value=len(content),
                        summary=f"{attr_tool} returned {len(content)} chars (~{est_tok} est. tokens)",
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


def _collect_ci_and_hook_files(project_path: Path) -> Tuple[List[Path], List[Path]]:
    ci_files: List[Path] = []
    wf_dir = project_path / ".github" / "workflows"
    if wf_dir.is_dir():
        ci_files.extend(sorted(wf_dir.glob("*.yml")))
        ci_files.extend(sorted(wf_dir.glob("*.yaml")))

    hook_files: List[Path] = []
    husky_dir = project_path / ".husky"
    if husky_dir.is_dir():
        hook_files.extend(sorted(p for p in husky_dir.iterdir() if p.is_file()))
    pre_commit = project_path / ".git" / "hooks" / "pre-commit"
    if pre_commit.is_file():
        hook_files.append(pre_commit)
    return ci_files, hook_files


def _read_concatenated_text(paths: List[Path]) -> str:
    chunks: List[str] = []
    for p in paths:
        try:
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(chunks)


def _discover_repo_checks(project_path: Path) -> List[Tuple[str, str]]:
    checks: List[Tuple[str, str]] = []
    pkg = _read_json_safe(project_path / "package.json")
    if pkg and isinstance(pkg.get("scripts"), dict):
        scripts = pkg["scripts"]
        for name in ("lint", "typecheck", "check", "test"):
            if name in scripts:
                checks.append(("package.json", name))

    pyproj = project_path / "pyproject.toml"
    if pyproj.is_file():
        try:
            text = pyproj.read_text(encoding="utf-8", errors="replace")
            for pat, name in ((r"\[tool\.pytest\b", "pytest"), (r"\[tool\.ruff\b", "ruff"), (r"\[tool\.mypy\b", "mypy")):
                if re.search(pat, text):
                    checks.append(("pyproject.toml", name))
        except Exception:
            pass
    return checks


def _extract_guardrail_gaps(project_path: Path) -> List[GuardrailGapSignal]:
    """Deterministically discovers missing CI/hooks and unwired lint/typecheck/test scripts."""
    if not project_path.exists() or not project_path.is_dir():
        return []
    _read_json_safe(project_path / ".edge" / "brigade.json")
    ci_files, hook_files = _collect_ci_and_hook_files(project_path)
    gaps: List[GuardrailGapSignal] = []
    if not ci_files and not hook_files:
        gaps.append(
            GuardrailGapSignal(
                gap_type="MISSING_GUARDRAIL",
                source_file=".github/workflows",
                script_or_check="ci_and_precommit",
                summary="No CI workflows (.github/workflows/*.yml|yaml) or pre-commit hooks (.husky/*, .git/hooks/pre-commit) configured",
            )
        )

    ci_and_hook_text = _read_concatenated_text(ci_files + hook_files)
    for source_file, check_name in _discover_repo_checks(project_path):
        if not re.search(rf"\b{re.escape(check_name)}\b", ci_and_hook_text):
            gaps.append(
                GuardrailGapSignal(
                    gap_type="UNWIRED_GUARDRAIL",
                    source_file=source_file,
                    script_or_check=check_name,
                    summary=f"Check '{check_name}' defined in {source_file} is not wired into CI workflows or pre-commit hooks",
                )
            )
    return gaps


def _collect_rule_inventory_targets(project_path: Path) -> List[Tuple[Path, Optional[int]]]:
    has_agents_dir = (project_path / "agents").is_dir()
    agents_resolved = (project_path / "agents").resolve()
    targets: List[Tuple[Path, Optional[int]]] = []
    for fpath, limit in collect_budget_targets(project_path):
        if fpath.resolve().parent == agents_resolved and not has_agents_dir:
            continue
        targets.append((fpath, limit))
    cs_path = project_path / "coding_standards.md"
    if cs_path.is_file():
        targets.append((cs_path.resolve(), None))
    return targets


def _build_session_citation_blobs(
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    blobs: List[str] = []
    for cid in analyzed_sessions:
        for step in sessions_steps.get(cid, []):
            parts = [str(step.get("content", ""))]
            for tc in step.get("tool_calls", []):
                parts.append(json.dumps(tc.get("args", {}), default=str))
            blobs.append(" ".join(parts).replace("\\", "/"))
    return blobs


def _count_file_citations(rel_path: str, fname: str, file_text: str, blobs: List[str]) -> int:
    cand_ids = set(re.findall(r"\bCAND-[A-Za-z0-9]+\b", file_text))
    count = 0
    for blob in blobs:
        if rel_path in blob:
            count += blob.count(rel_path)
        elif fname in blob:
            count += blob.count(fname)
        for cand_id in cand_ids:
            if cand_id in blob:
                count += blob.count(cand_id)
    return count


def _compute_rule_status(line_count: int, budget_limit: Optional[int], citation_count: int) -> str:
    if budget_limit is not None and line_count > budget_limit:
        return "OVER_BUDGET"
    if citation_count == 0:
        return "ZERO_CITATIONS"
    return "OK"


def _extract_rule_inventory(
    project_path: Path,
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
    mode: str = "project",
) -> List[RuleInventoryItem]:
    """Inventories station/agent rubrics and coding_standards.md with line budgets and session citations."""
    if not project_path.exists() or not project_path.is_dir():
        return []
    resolved_root = project_path.resolve()
    blobs = _build_session_citation_blobs(analyzed_sessions, sessions_steps)
    items: List[RuleInventoryItem] = []
    for fpath, limit in _collect_rule_inventory_targets(project_path):
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            rel_path = fpath.resolve().relative_to(resolved_root).as_posix()
        except Exception:
            continue
        line_count = len(text.splitlines())
        citations = _count_file_citations(rel_path, fpath.name, text, blobs)
        status = _compute_rule_status(line_count, limit, citations)
        items.append(
            RuleInventoryItem(
                file_path=rel_path,
                line_count=line_count,
                budget_limit=limit,
                citation_count=citations,
                status=status,
            )
        )
    return items


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


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_GENERIC_SENDERS = {"coordinator", "system", "user", "unknown", "parent"}


def _is_valid_sender_session(sender_id: str, discovered_sessions: Optional[Set[str]], is_swarm: bool) -> bool:
    if not sender_id or sender_id.lower() in _GENERIC_SENDERS:
        return False
    if discovered_sessions and sender_id in discovered_sessions:
        return True
    if _UUID_RE.match(sender_id):
        return True
    return not is_swarm and ("-" in sender_id or len(sender_id) >= 12)


def _append_unique_child(parent_to_children: Dict[str, List[str]], parent: str, child: str) -> None:
    children = parent_to_children.setdefault(parent, [])
    if child not in children:
        children.append(child)


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
        self._session_roles: Dict[str, str] = {}

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
                    role = info.get("role")
                    if role and child_cid not in self._session_roles:
                        self._session_roles[child_cid] = str(role).lower()
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

    def _link_spawned_children(
        self,
        steps: List[Dict[str, Any]],
        cid: str,
        child_to_parent: Dict[str, str],
        parent_to_children: Dict[str, List[str]],
    ) -> None:
        for step in steps:
            content = str(step.get("content", ""))
            for m in re.finditer(r'"conversation(?:Id|_id)":\s*"([^"]+)"', content):
                child_cid = m.group(1)
                if child_cid and child_cid != cid:
                    child_to_parent[child_cid] = cid
                    _append_unique_child(parent_to_children, cid, child_cid)

    def _link_parent_sender(
        self,
        steps: List[Dict[str, Any]],
        cid: str,
        child_to_parent: Dict[str, str],
        parent_to_children: Dict[str, List[str]],
        discovered_sessions: Optional[Set[str]],
    ) -> None:
        step_by_idx = {s.get("step_index"): str(s.get("content", "")) for s in steps}
        s0 = step_by_idx.get(0, "")
        s1 = step_by_idx.get(1, "")
        is_swarm = "[swarm] new board message" in s0.lower()

        if is_swarm and s1:
            m_role = re.search(r'for\s+(?:\*\*|\[)?@([a-zA-Z0-9_\-]+)(?:\*\*|\])?\s*:', s1)
            if m_role:
                self._session_roles[cid] = m_role.group(1).lower()

        search_text = f"{s0}\n{s1}" if is_swarm else s0
        m_snd = re.search(r"sender=([a-zA-Z0-9_\-]+)", search_text)
        if m_snd:
            p_cid = m_snd.group(1)
            if p_cid != cid and _is_valid_sender_session(p_cid, discovered_sessions, is_swarm):
                child_to_parent[cid] = p_cid
                _append_unique_child(parent_to_children, p_cid, cid)

    def _inspect_step_relations(
        self,
        steps: List[Dict[str, Any]],
        cid: str,
        child_to_parent: Dict[str, str],
        parent_to_children: Dict[str, List[str]],
        discovered_sessions: Optional[Set[str]] = None,
    ) -> None:
        self._link_spawned_children(steps, cid, child_to_parent, parent_to_children)
        self._link_parent_sender(steps, cid, child_to_parent, parent_to_children, discovered_sessions)

    def _load_transcripts(self, session_transcripts: Dict[str, Path]) -> Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, str], Dict[str, List[str]]]:
        sessions_steps: Dict[str, List[Dict[str, Any]]] = {}
        child_to_parent: Dict[str, str] = dict(self._load_active_stations_map())
        parent_to_children: Dict[str, List[str]] = {}
        discovered = set(session_transcripts.keys())

        for cid, tpath in session_transcripts.items():
            steps = _load_jsonl_steps(tpath)
            sessions_steps[cid] = steps
            self._inspect_step_relations(steps, cid, child_to_parent, parent_to_children, discovered_sessions=discovered)

        return sessions_steps, child_to_parent, parent_to_children

    def _find_matched_sessions(self, sessions_steps: Dict[str, List[Dict[str, Any]]], target_path: Path, parent_to_children: Dict[str, List[str]], child_to_parent: Dict[str, str]) -> Set[str]:
        matched: Set[str] = set()
        aliases = _collect_worktree_aliases(target_path)
        for cid, steps in sessions_steps.items():
            if _session_matches_project(steps, target_path, extra_project_paths=aliases):
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

    def _collect_navigation_signals(
        self,
        analyzed_sessions: List[str],
        sessions_steps: Dict[str, List[Dict[str, Any]]],
    ) -> List[NavigationFrictionSignal]:
        nav_signals: List[NavigationFrictionSignal] = []
        for cid in analyzed_sessions:
            role = self._session_roles.get(cid, "unknown")
            nav_signals.extend(
                _extract_navigation_frictions_from_steps(cid, sessions_steps.get(cid, []), role=role)
            )
        return nav_signals

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
        nav_frictions = self._collect_navigation_signals(analyzed, sessions_steps)
        total_tokens = _estimate_sessions_tokens(analyzed, sessions_steps)
        guardrail_gaps = _extract_guardrail_gaps(target_path)
        rule_inventory = _extract_rule_inventory(target_path, analyzed, sessions_steps, mode=mode)

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
            total_tokens_estimate=total_tokens,
            harness_signals_queued=harness_queued,
            factory_inbox_signals=inbox_signals,
            navigation_frictions=nav_frictions,
            guardrail_gaps=guardrail_gaps,
            rule_inventory=rule_inventory,
        )

    def _extract_flight_recorder(self, project_path: Path) -> List[Dict[str, Any]]:
        insights: List[Dict[str, Any]] = []
        fr_dir = project_path / ".edge" / "flight-recorder"
        if not fr_dir.exists():
            return insights
        for f in sorted(fr_dir.glob("*.json")):
            data = _read_json_safe(f)
            if not data:
                continue
            for dead in data.get("dead_ends", []):
                insights.append(_parse_dead_end_entry(dead))
            for gfail in data.get("guard_failures", []):
                insights.append(_parse_guard_failure_entry(gfail))
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
