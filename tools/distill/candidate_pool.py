"""Cross-project CandidatePool incubation, graduation, and promotion engine."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Dict, List, Optional

from tools.distill.lexical_gate import LexicalStackGate, append_rule_to_agent_rubric, clean_rule_from_all_projects
from tools.distill.models import CandidateRule
from tools.distill.state_io import _default_candidates_path, _resolve_agent_rubric_path


def _unlink_if_exists(path: str) -> None:
    if os.path.exists(path):
        try:
            os.unlink(path)
        except Exception:
            pass


class CandidatePool:
    """Manages incubation, graduation, and cross-project promotion of candidate rules."""

    def __init__(self, candidates_file_override: Optional[Path] = None, plugin_root: Optional[Path] = None):
        if candidates_file_override:
            self.candidates_file = Path(candidates_file_override).resolve()
        else:
            facade = sys.modules.get("tools.distill.state")
            path_fn = getattr(facade, "_default_candidates_path", _default_candidates_path) if facade else _default_candidates_path
            self.candidates_file = path_fn()
        self.plugin_root = Path(plugin_root).resolve() if plugin_root else Path(__file__).resolve().parents[2]

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
        tmp_fd, tmp_path = tempfile.mkstemp(dir=self.candidates_file.parent, prefix="cand_", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump({"candidates": [c.to_dict() for c in candidates]}, f, indent=2)
            os.replace(tmp_path, self.candidates_file)
        finally:
            _unlink_if_exists(tmp_path)

    def _update_existing_candidate(self, cand: CandidateRule, project_path: str, now_iso: str, evidence: Optional[List[Dict[str, Any]]]) -> CandidateRule:
        cand.occurrence_count += 1
        cand.last_seen_at = now_iso
        if project_path not in cand.source_projects:
            cand.source_projects.append(project_path)
        if len(cand.source_projects) >= 2:
            cand.status = "READY_FOR_PROMOTION"
        if evidence:
            cand.evidence.extend(evidence)
        return cand

    def record_candidate(self, rule_text: str, target_role: str, project_path: str, evidence: Optional[List[Dict[str, Any]]] = None) -> CandidateRule:
        rule_clean = rule_text.strip()
        fp = hashlib.sha256(rule_clean.lower().encode("utf-8")).hexdigest()[:16]
        cid, now_iso = f"CAND-{fp[:8]}", datetime.now(timezone.utc).isoformat()
        candidates = self.load_candidates()
        existing = next((c for c in candidates if c.fingerprint == fp or c.candidate_id == cid), None)
        if existing is not None:
            updated = self._update_existing_candidate(existing, project_path, now_iso, evidence)
            self.save_candidates(candidates)
            return updated
        scope_class, stack_tokens = LexicalStackGate.classify(rule_clean, project_path)
        new_cand = CandidateRule(
            candidate_id=cid, fingerprint=fp, rule_text=rule_clean, target_role=target_role.lower(),
            scope_class=scope_class, stack_tokens_matched=stack_tokens, first_seen_at=now_iso,
            last_seen_at=now_iso, source_projects=[project_path], occurrence_count=1,
            status="INCUBATING", evidence=evidence or [],
        )
        candidates.append(new_cand)
        self.save_candidates(candidates)
        return new_cand

    def promote_candidate(self, candidate_id: str, force: bool = False, plugin_root: Optional[Path] = None) -> bool:
        candidates = self.load_candidates()
        target_cand = next((c for c in candidates if c.candidate_id == candidate_id), None)
        if not target_cand or (target_cand.status != "READY_FOR_PROMOTION" and not force):
            return False
        root = Path(plugin_root).resolve() if plugin_root else self.plugin_root
        append_rule_to_agent_rubric(_resolve_agent_rubric_path(root, target_cand.target_role.lower()), target_cand)
        clean_rule_from_all_projects(target_cand.source_projects, target_cand)
        target_cand.status = "PROMOTED"
        self.save_candidates(candidates)
        return True

    def list_candidates(self, status: Optional[str] = None) -> List[CandidateRule]:
        candidates = self.load_candidates()
        return [c for c in candidates if c.status.lower() == status.lower()] if status else candidates
