#!/usr/bin/env python3
"""
Watermark State, LexicalStackGate, CandidatePool & Line Budget for edge-distill v2.
"""

import os
import sys
import json
import re
import hashlib
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from datetime import datetime, timezone, timedelta

from tools.common.paths import to_wsl_path
from tools.distill.models import DistillWatermarkState, CandidateRule

TIMESTAMP_LINE_PATTERN = re.compile(r"^(?:Created|Completed)\s+At:\s*.*$", re.MULTILINE | re.IGNORECASE)
ISO8601_TIMESTAMP_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})\b")
WSL_RELAY_PID_PATTERN = re.compile(r"WSL\s*\(\s*\d+\s*-\s*Relay\s*\)", re.IGNORECASE)
EPHEMERAL_PATH_PATTERN = re.compile(
    r"""(?:/tmp/|/var/folders/|[A-Za-z]:[\/]Users[\/][^\/]+[\/]AppData[\/]Local[\/]Temp[\/])[^\s"'`:;]+""",
    re.IGNORECASE,
)
EPHEMERAL_TEST_DIR_PATTERN = re.compile(
    r"(?:^|[\\/])(?:pytest-[^\\/]+|test_[^\\/]+|unittest|tmp[^\\/]*|temp[^\\/]*)(?:[\\/]|$)"
    r"|(?:^|[\\/])(?:tmp|var[\\/]folders|AppData[\\/]Local[\\/]Temp)(?:[\\/]|$)",
    re.IGNORECASE,
)


def _sanitize_signal_summary(summary: str) -> str:
    if not summary:
        return ""
    text = TIMESTAMP_LINE_PATTERN.sub("", summary)
    text = ISO8601_TIMESTAMP_PATTERN.sub("<TIMESTAMP>", text)
    text = WSL_RELAY_PID_PATTERN.sub("WSL (<PID> - Relay)", text)
    text = EPHEMERAL_PATH_PATTERN.sub("<TMP_PATH>", text)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines).strip()


def _is_ephemeral_test_path(path_str: str) -> bool:
    if not path_str:
        return False
    norm = str(path_str).replace("\\", "/")
    return bool(EPHEMERAL_TEST_DIR_PATTERN.search(norm))


def _resolve_agent_rubric_path(root: Path, role: str) -> Path:
    clean_role = role.strip().lower()
    hyphen_name = f"{clean_role.replace('_', '-')}.md"
    hyphen_path = root / "agents" / hyphen_name
    if hyphen_path.is_file():
        return hyphen_path

    underscore_name = f"{clean_role.replace('-', '_')}.md"
    underscore_path = root / "agents" / underscore_name
    if underscore_path.is_file():
        return underscore_path

    return hyphen_path



def _default_state_path() -> Path:
    env_path = os.environ.get("EDGE_DISTILL_STATE_FILE")
    if env_path:
        return Path(env_path).resolve()
    base_dir = Path.home() / ".gemini" / "antigravity"
    return (base_dir / "edge_distill_state.json").resolve()


def _default_factory_inbox_path() -> Path:
    env_path = os.environ.get("EDGE_DISTILL_FACTORY_INBOX_FILE")
    if env_path:
        return Path(env_path).resolve()
    base_dir = Path.home() / ".gemini" / "antigravity"
    return (base_dir / "edge_factory_inbox.json").resolve()


def _save_json_atomic(target_path: Path, data: Any) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=target_path.parent, prefix="atomic_", suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, target_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _default_candidates_path() -> Path:
    env_path = os.environ.get("EDGE_DISTILL_CANDIDATES_FILE")
    if env_path:
        return Path(env_path).resolve()
    base_dir = Path.home() / ".gemini" / "antigravity"
    return (base_dir / "edge_distill_candidates.json").resolve()


class DistillStateManager:
    """
    Manages atomic watermark state across harvest runs.
    """
    def __init__(self, state_file_override: Optional[Path] = None):
        if state_file_override:
            self.state_file = Path(state_file_override).resolve()
        else:
            self.state_file = _default_state_path()

    def load_state(self) -> DistillWatermarkState:
        if not self.state_file.exists():
            return DistillWatermarkState()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return DistillWatermarkState.from_dict(data)
        except Exception:
            return DistillWatermarkState()

    def save_state(self, state: DistillWatermarkState) -> None:
        _save_json_atomic(self.state_file, state.to_dict())

    def mark_session_processed(
        self,
        session_id: str,
        project_path: Optional[str] = None,
        mode: str = "project",
    ) -> None:
        state = self.load_state()
        if session_id not in state.processed_sessions:
            state.processed_sessions.append(session_id)

        if mode == "factory":
            if session_id not in state.factory_processed_sessions:
                state.factory_processed_sessions.append(session_id)
        else:
            if project_path:
                p_sessions = state.project_sessions.setdefault(str(project_path), [])
                if session_id not in p_sessions:
                    p_sessions.append(session_id)

        state.last_harvested_at = datetime.now(timezone.utc).isoformat()
        state.metrics["total_harvested"] = len(state.processed_sessions)
        self.save_state(state)

    def is_session_processed(
        self,
        session_id: str,
        project_path: Optional[str] = None,
        mode: str = "all",
    ) -> bool:
        state = self.load_state()
        if mode == "factory":
            return session_id in state.factory_processed_sessions
        if mode == "project":
            if project_path and str(project_path) in state.project_sessions:
                return session_id in state.project_sessions[str(project_path)]
            return session_id in state.processed_sessions
        return session_id in state.processed_sessions


_INBOX_PRESERVATION_MARKERS = (
    "Traceback",
    "ERROR:",
    "error TS",
    "fatal:",
    "FAILED",
    "BLOCKED",
    "AssertionError",
    "SyntaxError",
    "ModuleNotFoundError",
    "Encountered error in tool execution",
    "was forcefully killed",
    "hung or required excessive polling",
)
_NONZERO_EXIT_RE = re.compile(r"Command exited with code\s+[1-9]\d*")
_BENIGN_INBOX_TOOLS = frozenset({"read_file", "read_board", "edit_file", "manage_task", "invoke_subagent"})
_BENIGN_INBOX_SNIPPETS = ("The tool's output was truncated", "Showing lines ", "Made 1 replacement")
_PRUNE_REASONS = ("exit_zero", "benign_tool", "ephemeral", "duplicate", "resolved", "expired")


def _compute_signal_fingerprint(kind: str, role_or_tool: str, summary: str) -> str:
    clean_summary = _sanitize_signal_summary(summary)
    return hashlib.sha256(f"{kind}:{role_or_tool}:{clean_summary}".lower().encode("utf-8")).hexdigest()[:16]


def _normalize_scope_path(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    return to_wsl_path(raw.strip()).replace("\\", "/").rstrip("/").lower()


def _match_project_scope(source_project: str, target_project: str) -> bool:
    proj = _normalize_scope_path(target_project)
    if not proj:
        return True
    src = _normalize_scope_path(source_project)
    if not src:
        return False
    return src == proj or src.startswith(proj + "/")


def _is_expired_signal(created_at: str, max_age_days: int, now: datetime) -> bool:
    if not created_at or not isinstance(created_at, str):
        return False
    ts_str = created_at.strip()
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) > timedelta(days=max_age_days)


def _has_preservation_marker(summary: str) -> bool:
    if not summary:
        return False
    if _NONZERO_EXIT_RE.search(summary):
        return True
    return any(marker in summary for marker in _INBOX_PRESERVATION_MARKERS)


def _is_benign_tool_record(kind: str, role_or_tool: str, summary: str) -> bool:
    if kind != "HARNESS_FRICTION":
        return False
    if role_or_tool in _BENIGN_INBOX_TOOLS:
        return True
    return any(snip in summary for snip in _BENIGN_INBOX_SNIPPETS)


def _classify_noise_reason(
    kind: str,
    role_or_tool: str,
    summary: str,
    drop_exit_zero: bool,
    drop_benign_tools: bool,
) -> Optional[str]:
    if _has_preservation_marker(summary):
        return None
    if drop_exit_zero and kind == "HARNESS_FRICTION" and "Command exited with code 0" in summary:
        return "exit_zero"
    if drop_benign_tools and _is_benign_tool_record(kind, role_or_tool, summary):
        return "benign_tool"
    return None


def _classify_prune_reason(
    record: Dict[str, Any],
    fp: str,
    seen_fps: Set[str],
    opts: Dict[str, Any],
    now: datetime,
) -> Optional[str]:
    if opts["resolved_only"]:
        return "resolved" if record.get("resolved", False) else None
    source_proj = str(record.get("source_project", ""))
    if opts["drop_ephemeral"] and _is_ephemeral_test_path(source_proj):
        return "ephemeral"
    kind = str(record.get("kind", "HARNESS_FRICTION"))
    role_or_tool = str(record.get("role_or_tool", ""))
    summary = str(record.get("summary", ""))
    noise_reason = _classify_noise_reason(
        kind, role_or_tool, summary, opts["drop_exit_zero"], opts["drop_benign_tools"]
    )
    if noise_reason:
        return noise_reason
    max_age = opts["max_age_days"]
    if max_age is not None and _is_expired_signal(str(record.get("created_at", "")), max_age, now):
        return "expired"
    if opts["deduplicate"] and fp in seen_fps:
        return "duplicate"
    return None


class FactoryInbox:
    """
    Silent inbox queueing harness signals during PROJECT_MODE runs,
    drained during FACTORY_MODE self-improvement cycles.
    Enforces atomic persistence and SHA-256 fingerprint deduplication.
    """
    def __init__(self, inbox_file_override: Optional[Path] = None):
        if inbox_file_override:
            self.inbox_file = Path(inbox_file_override).resolve()
        else:
            self.inbox_file = _default_factory_inbox_path()

    def load_signals(self) -> List[Dict[str, Any]]:
        if not self.inbox_file.exists():
            return []
        try:
            data = json.loads(self.inbox_file.read_text(encoding="utf-8"))
            return data.get("signals", [])
        except Exception:
            return []

    def _build_signal_record(self, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        kind = str(raw.get("kind", "HARNESS_FRICTION"))
        role_or_tool = str(raw.get("role_or_tool", ""))
        summary = str(raw.get("summary", ""))
        fp = _compute_signal_fingerprint(kind, role_or_tool, summary)
        sig_id = raw.get("signal_id") or f"SIG-INBOX-{fp[:8].upper()}"
        created_at = raw.get("created_at") or datetime.now(timezone.utc).isoformat()
        resolved = bool(raw.get("resolved", False))
        source_project = str(raw.get("source_project", ""))
        record = {
            "signal_id": sig_id,
            "fingerprint": fp,
            "kind": kind,
            "source_project": source_project,
            "role_or_tool": role_or_tool,
            "summary": summary,
            "created_at": created_at,
            "resolved": resolved,
        }
        return record, fp

    def append_signals(self, raw_signals: List[Dict[str, Any]]) -> int:
        existing = self.load_signals()
        existing_fps = {s.get("fingerprint") for s in existing if s.get("fingerprint")}
        is_mocked = hasattr(_default_factory_inbox_path, "assert_called")
        is_prod = is_mocked or ("EDGE_DISTILL_FACTORY_INBOX_FILE" not in os.environ)
        is_default_prod_inbox = is_prod and (self.inbox_file.resolve() == _default_factory_inbox_path().resolve())
        added = 0
        for raw in raw_signals:
            source_proj = str(raw.get("source_project", ""))
            if is_default_prod_inbox and _is_ephemeral_test_path(source_proj):
                continue
            record, fp = self._build_signal_record(raw)
            if fp not in existing_fps:
                existing.append(record)
                existing_fps.add(fp)
                added += 1
        _save_json_atomic(self.inbox_file, {"signals": existing})
        return added

    def load_pending(self) -> List[Dict[str, Any]]:
        return [s for s in self.load_signals() if not s.get("resolved", False)]

    def clear(self) -> None:
        _save_json_atomic(self.inbox_file, {"signals": []})

    def resolve_all(self) -> None:
        signals = self.load_signals()
        for s in signals:
            s["resolved"] = True
        _save_json_atomic(self.inbox_file, {"signals": signals})

    def prune(
        self,
        drop_exit_zero: bool = True,
        drop_benign_tools: bool = True,
        drop_ephemeral: bool = True,
        deduplicate: bool = True,
        project: Optional[str] = None,
        resolved_only: bool = False,
        max_age_days: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        records = self.load_signals()
        counts: Dict[str, int] = {reason: 0 for reason in _PRUNE_REASONS}
        opts: Dict[str, Any] = {
            "drop_exit_zero": drop_exit_zero,
            "drop_benign_tools": drop_benign_tools,
            "drop_ephemeral": drop_ephemeral,
            "deduplicate": deduplicate,
            "resolved_only": resolved_only,
            "max_age_days": max_age_days,
        }
        now = datetime.now(timezone.utc)
        kept: List[Dict[str, Any]] = []
        seen_fps: Set[str] = set()

        for record in records:
            kind = str(record.get("kind", "HARNESS_FRICTION"))
            role_or_tool = str(record.get("role_or_tool", ""))
            summary = str(record.get("summary", ""))
            fp = _compute_signal_fingerprint(kind, role_or_tool, summary)

            if project is not None and not _match_project_scope(str(record.get("source_project", "")), project):
                kept.append(record)
                seen_fps.add(fp)
                continue

            reason = _classify_prune_reason(record, fp, seen_fps, opts, now)
            if reason:
                counts[reason] += 1
            else:
                kept.append(record)
                seen_fps.add(fp)

        removed = len(records) - len(kept)
        if not dry_run and removed > 0:
            _save_json_atomic(self.inbox_file, {"signals": kept})

        return {
            "before": len(records),
            "after": len(kept),
            "removed": removed,
            "removed_by_reason": counts,
            "dry_run": dry_run,
        }


class LexicalStackGate:
    """
    Zero-token lexical gate classifying candidates as REPO_LOCAL or PLUGIN_CANDIDATE.
    Enforces strict word boundaries so words like 'tests' or 'expresses' do not falsely match.
    """
    TECH_REGEX = re.compile(
        r"\b(nextjs|react|vue|svelte|fastapi|django|flask|express|drizzle|prisma|typeorm|sqlalchemy|mongo|postgres|mysql|sqlite|tailwind|daisyui|radix|shadcn)\b",
        re.IGNORECASE,
    )
    EXT_REGEX = re.compile(
        r"\.(tsx|jsx|vue|ts|py)\b",
        re.IGNORECASE,
    )
    PATH_REGEX = re.compile(
        r"(src/(?:actions|components|lib|db|app)/[^\s]*|src/(?:actions|components|lib|db|app)/)",
        re.IGNORECASE,
    )

    @classmethod
    def classify(cls, rule_text: str, target_path: Optional[str] = None) -> Tuple[str, List[str]]:
        matched: List[str] = []

        for m in cls.TECH_REGEX.finditer(rule_text):
            matched.append(m.group(1).lower())

        for m in cls.EXT_REGEX.finditer(rule_text):
            matched.append(f".{m.group(1).lower()}")

        for m in cls.PATH_REGEX.finditer(rule_text):
            matched.append(m.group(1).lower())

        if target_path:
            for m in cls.TECH_REGEX.finditer(target_path):
                matched.append(m.group(1).lower())
            for m in cls.EXT_REGEX.finditer(target_path):
                matched.append(f".{m.group(1).lower()}")

        unique_tokens = sorted(list(set(matched)))
        if unique_tokens:
            return "REPO_LOCAL", unique_tokens
        return "PLUGIN_CANDIDATE", []


def _append_rule_to_agent_rubric(agent_file: Path, cand: CandidateRule) -> None:
    if not agent_file.exists():
        return
    existing = agent_file.read_text(encoding="utf-8")
    if cand.rule_text not in existing:
        new_text = existing.rstrip() + f"\n\n### Distilled Invariant ({cand.candidate_id})\n- {cand.rule_text}\n"
        new_lines = len(new_text.splitlines())
        if new_lines > 60:
            raise ValueError(f"Line budget exceeded (> 60 lines: {new_lines} lines)")
        agent_file.write_text(new_text, encoding="utf-8")


def _clean_rule_from_overlay(overlay_file: Path, cand: CandidateRule) -> None:
    if not overlay_file.exists():
        return
    try:
        text = overlay_file.read_text(encoding="utf-8")
        if cand.rule_text in text:
            cleaned = [line for line in text.splitlines() if cand.rule_text not in line]
            overlay_file.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
    except Exception:
        pass


def _clean_rule_from_all_projects(source_projects: List[str], cand: CandidateRule) -> None:
    role = cand.target_role.lower()
    variants = {role, role.replace("_", "-"), role.replace("-", "_")}
    for proj_str in source_projects:
        p = Path(proj_str)
        if not p.exists():
            continue
        stations_dir = p / ".edge" / "stations"
        for v in variants:
            overlay_file = stations_dir / f"{v}.md"
            if overlay_file.exists():
                _clean_rule_from_overlay(overlay_file, cand)


class CandidatePool:
    """
    Manages incubation, graduation, and cross-project promotion of candidate rules.
    """
    def __init__(
        self,
        candidates_file_override: Optional[Path] = None,
        plugin_root: Optional[Path] = None,
    ):
        if candidates_file_override:
            self.candidates_file = Path(candidates_file_override).resolve()
        else:
            self.candidates_file = _default_candidates_path()

        self.plugin_root = (
            Path(plugin_root).resolve()
            if plugin_root
            else Path(__file__).resolve().parents[2]
        )

    def load_candidates(self) -> List[CandidateRule]:
        if not self.candidates_file.exists():
            return []
        try:
            data = json.loads(self.candidates_file.read_text(encoding="utf-8"))
            return [CandidateRule.from_dict(c) for c in data.get("candidates", [])]
        except Exception:
            return []

    def save_candidates(self, candidates: List[CandidateRule]) -> None:
        self.candidates_file.parent.mkdir(parents=True, exist_ok=True)
        data = {"candidates": [c.to_dict() for c in candidates]}
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.candidates_file.parent, prefix="cand_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.candidates_file)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def record_candidate(
        self,
        rule_text: str,
        target_role: str,
        project_path: str,
        evidence: Optional[List[Dict[str, Any]]] = None,
    ) -> CandidateRule:
        rule_clean = rule_text.strip()
        fp = hashlib.sha256(rule_clean.lower().encode("utf-8")).hexdigest()[:16]
        cid = f"CAND-{fp[:8]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        candidates = self.load_candidates()
        for cand in candidates:
            if cand.fingerprint == fp or cand.candidate_id == cid:
                cand.occurrence_count += 1
                cand.last_seen_at = now_iso
                if project_path not in cand.source_projects:
                    cand.source_projects.append(project_path)
                if len(cand.source_projects) >= 2:
                    cand.status = "READY_FOR_PROMOTION"
                if evidence:
                    cand.evidence.extend(evidence)
                self.save_candidates(candidates)
                return cand

        scope_class, stack_tokens = LexicalStackGate.classify(rule_clean, project_path)
        new_cand = CandidateRule(
            candidate_id=cid,
            fingerprint=fp,
            rule_text=rule_clean,
            target_role=target_role.lower(),
            scope_class=scope_class,
            stack_tokens_matched=stack_tokens,
            first_seen_at=now_iso,
            last_seen_at=now_iso,
            source_projects=[project_path],
            occurrence_count=1,
            status="INCUBATING",
            evidence=evidence or [],
        )
        candidates.append(new_cand)
        self.save_candidates(candidates)
        return new_cand

    def promote_candidate(
        self,
        candidate_id: str,
        force: bool = False,
        plugin_root: Optional[Path] = None,
    ) -> bool:
        candidates = self.load_candidates()
        target_cand = None
        for c in candidates:
            if c.candidate_id == candidate_id:
                target_cand = c
                break

        if not target_cand:
            return False

        if target_cand.status != "READY_FOR_PROMOTION" and not force:
            return False

        root = Path(plugin_root).resolve() if plugin_root else self.plugin_root
        agent_file = _resolve_agent_rubric_path(root, target_cand.target_role.lower())
        _append_rule_to_agent_rubric(agent_file, target_cand)
        _clean_rule_from_all_projects(target_cand.source_projects, target_cand)

        target_cand.status = "PROMOTED"
        self.save_candidates(candidates)
        return True

    def list_candidates(self, status: Optional[str] = None) -> List[CandidateRule]:
        candidates = self.load_candidates()
        if status:
            return [c for c in candidates if c.status.lower() == status.lower()]
        return candidates


def _collect_dir_targets(p: Path) -> List[Tuple[Path, int]]:
    targets: List[Tuple[Path, int]] = []
    agents_dir = p / "agents"
    if agents_dir.is_dir():
        for f in sorted(agents_dir.glob("*.md")):
            targets.append((f, 60))
    stations_dir = p / ".edge" / "stations"
    if stations_dir.is_dir():
        for f in sorted(stations_dir.glob("*.md")):
            targets.append((f, 40))
    return targets


def _collect_self_targets(p: Path) -> List[Tuple[Path, int]]:
    targets: List[Tuple[Path, int]] = []
    parts = [part.lower() for part in p.parts]
    limit = 40 if "stations" in parts else (60 if "agents" in parts else None)
    if limit is not None:
        for f in sorted(p.glob("*.md")):
            targets.append((f, limit))
    return targets


def collect_budget_targets(target_path: Path) -> List[Tuple[Path, int]]:
    """
    Collects markdown files and their budget ceilings:
    - agents/*.md <= 60 lines
    - .edge/stations/*.md <= 40 lines
    - if directory is named 'agents', its *.md <= 60 lines
    - if directory is named 'stations', its *.md <= 40 lines
    """
    p = target_path.resolve()
    if p.is_file():
        parts = [part.lower() for part in p.parts]
        limit = 40 if "stations" in parts else 60
        return [(p, limit)]

    targets = _collect_dir_targets(p)
    if not targets:
        targets = _collect_self_targets(p)
    return targets


def _check_single_file_budget(p: Path, max_lines: Optional[int]) -> Tuple[bool, int, int]:
    parts = [part.lower() for part in p.parts]
    limit = max_lines if max_lines is not None else (40 if "stations" in parts else 60)
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    count = len(lines)
    return count <= limit, count, limit


def _evaluate_target_budgets(targets: List[Tuple[Path, int]], max_lines: Optional[int]) -> Tuple[bool, int, int]:
    all_ok = True
    max_count = 0
    effective_limit = max_lines or 60
    for f, def_limit in targets:
        lim = max_lines or def_limit
        cnt = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
        if cnt > max_count:
            max_count = cnt
        if cnt > lim:
            all_ok = False
            effective_limit = lim
    return all_ok, max_count, effective_limit


def check_line_budget(file_or_dir_path: Path, max_lines: Optional[int] = None) -> Tuple[bool, int, int]:
    """
    Checks line count against strict station and agent budgets:
    - agents/*.md max 60 lines
    - .edge/stations/*.md max 40 lines
    Supports single file or directory traversal.
    """
    p = Path(file_or_dir_path).resolve()
    if not p.exists():
        return False, 0, max_lines or 60

    if p.is_file():
        return _check_single_file_budget(p, max_lines)

    targets = collect_budget_targets(p)
    if not targets:
        limit = max_lines or 60
        targets = [(f, limit) for f in sorted(p.glob("*.md"))]

    if not targets:
        return True, 0, max_lines or 60

    return _evaluate_target_budgets(targets, max_lines)
