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
    ):
        self.repo_path = repo_path.resolve() if repo_path else None
        self.brain_roots = [p.resolve() for p in brain_roots] if brain_roots else self._default_brain_roots()
        self.active_stations_file = active_stations_file.resolve() if active_stations_file else None
        self.watermark_state = watermark_state or DistillWatermarkState()

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
        for root in self.brain_roots:
            if not root.exists():
                continue
            try:
                for entry in root.iterdir():
                    if entry.is_dir():
                        candidate_dirs.append(entry)
            except Exception:
                pass
        candidate_dirs.sort(key=lambda d: d.stat().st_mtime if d.exists() else 0, reverse=True)
        if len(candidate_dirs) > 100:
            candidate_dirs = candidate_dirs[:100]
        return candidate_dirs

    def _discover_transcripts(self) -> Dict[str, Path]:
        session_transcripts: Dict[str, Path] = {}
        for sess_dir in self._discover_candidates():
            tfile = sess_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if tfile.exists():
                session_transcripts[sess_dir.name] = tfile
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
            if _matches_project(steps, target_path):
                matched.add(cid)
                for child_cid in parent_to_children.get(cid, []):
                    matched.add(child_cid)
                if cid in child_to_parent:
                    matched.add(child_to_parent[cid])
        return matched

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
            tool_frictions.extend(_extract_tool_frictions_from_steps(cid, steps))
            station_escapes.extend(_extract_station_escapes_from_steps(cid, steps))
            for s in steps:
                flattened_steps.append({"cid": cid, "step": s})

        escalations = _extract_repeated_escalations(flattened_steps)
        return tool_frictions, station_escapes, escalations

    def _split_project_signals(
        self,
        frictions: List[ToolFrictionSignal],
        escapes: List[StationEscapeSignal],
        target_path: Path,
    ) -> Tuple[List[ToolFrictionSignal], List[StationEscapeSignal], int]:
        harness_keywords = (
            "brigade",
            "treehouse",
            "orchestrator_guard",
            "wsl (",
            "tools/distill",
            "tasks-axi",
            "frontier-axi",
            "aborted in state",
            "examiner review: pass",
        )
        proj_frictions: List[ToolFrictionSignal] = []
        proj_escapes: List[StationEscapeSignal] = []
        harness_queue: List[Dict[str, Any]] = []

        for f in frictions:
            comb = (f.command_or_args + " " + f.error_output + " " + f.tool_name).lower()
            if any(kw in comb for kw in harness_keywords):
                harness_queue.append({
                    "kind": "HARNESS_FRICTION",
                    "source_project": str(target_path),
                    "role_or_tool": f.tool_name or "run_command",
                    "summary": f.error_output.strip() or f.command_or_args,
                })
            else:
                proj_frictions.append(f)

        for esc in escapes:
            comb = (esc.description + " " + esc.evidence + " " + esc.station_role).lower()
            if any(kw in comb for kw in harness_keywords):
                harness_queue.append({
                    "kind": "STATION_ESCAPE",
                    "source_project": str(target_path),
                    "role_or_tool": esc.station_role.lower(),
                    "summary": esc.description or esc.evidence,
                })
            else:
                proj_escapes.append(esc)

        if harness_queue:
            inbox = FactoryInbox()
            inbox.append_signals(harness_queue)

        return proj_frictions, proj_escapes, len(harness_queue)

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
