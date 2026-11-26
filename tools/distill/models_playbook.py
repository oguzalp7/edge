"""Legacy playbook, distill report, and diff pattern models."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tools.distill.models_legacy import DistillSession, JournalEntry, NegativeConstraint, RescueLoop


@dataclass
class DiffPattern:
    domain: str
    target_file: str
    scaffolded_files: List[str] = field(default_factory=list)
    before_code: str = ""
    after_code: str = ""
    diff_hunks: List[str] = field(default_factory=list)
    pattern_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiffPattern":
        return cls(**data)


@dataclass
class PlaybookProposal:
    proposal_id: str
    domain_name: str
    title: str
    summary: str
    crisis_context: str
    chronological_steps: List[JournalEntry] = field(default_factory=list)
    two_headed_divergence_analysis: Dict[str, Any] = field(default_factory=dict)
    seam_establishment_recipes: List[str] = field(default_factory=list)
    rescue_loops: List[RescueLoop] = field(default_factory=list)
    negative_constraints: List[NegativeConstraint] = field(default_factory=list)
    diff_patterns: List[DiffPattern] = field(default_factory=list)
    proposed_rules: List[str] = field(default_factory=list)
    verification_checklist: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "chronological_steps": [c.to_dict() for c in self.chronological_steps],
            "rescue_loops": [r.to_dict() for r in self.rescue_loops],
            "negative_constraints": [n.to_dict() for n in self.negative_constraints],
            "diff_patterns": [d.to_dict() for d in self.diff_patterns],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlaybookProposal":
        raw = dict(data)
        if "chronological_steps" in raw:
            raw["chronological_steps"] = [JournalEntry.from_dict(c) for c in raw["chronological_steps"]]
        if "rescue_loops" in raw:
            raw["rescue_loops"] = [RescueLoop.from_dict(r) for r in raw["rescue_loops"]]
        if "negative_constraints" in raw:
            raw["negative_constraints"] = [NegativeConstraint.from_dict(n) for n in raw["negative_constraints"]]
        if "diff_patterns" in raw:
            raw["diff_patterns"] = [DiffPattern.from_dict(d) for d in raw["diff_patterns"]]
        return cls(**raw)


@dataclass
class DistillReport:
    domain: str
    track: str = "core"
    target_file: str = ""
    scaffolded_files: List[str] = field(default_factory=list)
    base_branch: str = "main"
    active_branch: Optional[str] = None
    ticket_id: Optional[str] = None
    rescue_loops: List[RescueLoop] = field(default_factory=list)
    negative_constraints: List[NegativeConstraint] = field(default_factory=list)
    diff_patterns: List[DiffPattern] = field(default_factory=list)
    compiler_fixes: List[Dict[str, Any]] = field(default_factory=list)
    test_seams: List[Dict[str, Any]] = field(default_factory=list)
    resolved_debt_items: List[Dict[str, Any]] = field(default_factory=list)
    session: Optional[DistillSession] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    playbook_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "rescue_loops": [r.to_dict() for r in self.rescue_loops],
            "negative_constraints": [n.to_dict() for n in self.negative_constraints],
            "diff_patterns": [d.to_dict() for d in self.diff_patterns],
            "session": self.session.to_dict() if self.session else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillReport":
        raw = dict(data)
        if "rescue_loops" in raw:
            raw["rescue_loops"] = [RescueLoop.from_dict(r) for r in raw["rescue_loops"]]
        if "negative_constraints" in raw:
            raw["negative_constraints"] = [NegativeConstraint.from_dict(n) for n in raw["negative_constraints"]]
        if "diff_patterns" in raw:
            raw["diff_patterns"] = [DiffPattern.from_dict(d) for d in raw["diff_patterns"]]
        if "session" in raw and raw["session"]:
            raw["session"] = DistillSession.from_dict(raw["session"])
        return cls(**raw)
