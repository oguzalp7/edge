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
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from tools.distill.models import DistillWatermarkState, CandidateRule


class DistillStateManager:
    """
    Manages atomic watermark state across harvest runs.
    """
    def __init__(self, state_file_override: Optional[Path] = None):
        if state_file_override:
            self.state_file = Path(state_file_override).resolve()
        else:
            env_path = os.environ.get("EDGE_DISTILL_STATE_FILE")
            if env_path:
                self.state_file = Path(env_path).resolve()
            else:
                self.state_file = (Path.home() / ".edge" / "distill_watermark.json").resolve()

    def load_state(self) -> DistillWatermarkState:
        if not self.state_file.exists():
            return DistillWatermarkState()
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            return DistillWatermarkState.from_dict(data)
        except Exception:
            return DistillWatermarkState()

    def save_state(self, state: DistillWatermarkState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        data = state.to_dict()
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.state_file.parent, prefix="state_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.state_file)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def mark_session_processed(self, session_id: str, project_path: Optional[str] = None) -> None:
        state = self.load_state()
        if session_id not in state.processed_sessions:
            state.processed_sessions.append(session_id)

        if project_path:
            p_sessions = state.project_sessions.setdefault(str(project_path), [])
            if session_id not in p_sessions:
                p_sessions.append(session_id)

        state.last_harvested_at = datetime.now(timezone.utc).isoformat()
        state.metrics["total_harvested"] = len(state.processed_sessions)
        self.save_state(state)


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
    for proj_str in source_projects:
        p = Path(proj_str)
        if not p.exists():
            continue
        overlay_file = p / ".edge" / "stations" / f"{cand.target_role.lower()}.md"
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
            env_path = os.environ.get("EDGE_DISTILL_CANDIDATES_FILE")
            if env_path:
                self.candidates_file = Path(env_path).resolve()
            else:
                self.candidates_file = (Path.home() / ".edge" / "candidates.json").resolve()

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
        agent_file = root / "agents" / f"{target_cand.target_role.lower()}.md"
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


def check_line_budget(file_path: Path, max_lines: Optional[int] = None) -> Tuple[bool, int, int]:
    """
    Checks line count against strict station and agent budgets:
    - agents/*.md max 60 lines
    - .edge/stations/*.md max 40 lines
    """
    p = Path(file_path).resolve()
    if not p.exists():
        return False, 0, max_lines or 60

    if max_lines is None:
        parts = [part.lower() for part in p.parts]
        if "stations" in parts:
            max_lines = 40
        elif "agents" in parts:
            max_lines = 60
        else:
            max_lines = 60

    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        count = len(lines)
        return count <= max_lines, count, max_lines
    except Exception:
        return False, 0, max_lines
