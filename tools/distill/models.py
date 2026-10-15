#!/usr/bin/env python3
"""
Data models for edge-distill: Pattern & Playbook Miner & Incident Journaler.
Encapsulates:
- Live flight recorder sessions (DistillSession, JournalEntry)
- Extracted rescue loops & negative constraints
- AST / code diff patterns
- Playbook proposals for emerging operational domains (e.g. reconcile / harmonize).
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import hashlib


@dataclass
class JournalEntry:
    """
    A single chronological event recorded during a live crisis / refactor session.
    """
    entry_id: str
    timestamp: str
    step: str
    tag: str = "OBSERVATION"                   # OBSERVATION | SEAM_CREATION | BEHAVIOR_SYNC | BUG_FIX | RESCUE_MOVE | GATE_CHECK
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JournalEntry":
        return cls(**data)


@dataclass
class DistillSession:
    """
    A durable Flight Recorder (Kara Kutu) session tracking an operation from start to resolution.
    """
    session_id: str
    repo_path: str
    started_at: str
    status: str = "RECORDING"                  # RECORDING | RESOLVED | ABORTED
    goal: str = ""
    operational_domain: str = "reconcile"      # feature | refactor | reconcile | custom
    baseline_commit: Optional[str] = None
    final_commit: Optional[str] = None
    resolved_at: Optional[str] = None
    journal_entries: List[JournalEntry] = field(default_factory=list)
    initial_metrics: Dict[str, Any] = field(default_factory=dict)
    resolution_notes: Optional[str] = None
    proposal_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "repo_path": self.repo_path,
            "started_at": self.started_at,
            "status": self.status,
            "goal": self.goal,
            "operational_domain": self.operational_domain,
            "baseline_commit": self.baseline_commit,
            "final_commit": self.final_commit,
            "resolved_at": self.resolved_at,
            "journal_entries": [j.to_dict() for j in self.journal_entries],
            "initial_metrics": self.initial_metrics,
            "resolution_notes": self.resolution_notes,
            "proposal_path": self.proposal_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillSession":
        raw = dict(data)
        if "journal_entries" in raw:
            raw["journal_entries"] = [JournalEntry.from_dict(j) for j in raw["journal_entries"]]
        return cls(**raw)


@dataclass
class RescueLoop:
    """
    A deterministic recipe extracted from a failed guard or error that was subsequently cured.
    """
    loop_id: str
    stage: str                                 # SURGERY, VERIFY, REVIEW, GATE, POLISH
    symptom: str                               # Failure signature or error log excerpt
    root_cause: str                            # Why the guard/test/compiler failed
    remediation: str                           # The deterministic rescue move that greened the state
    rule_enforced: str                         # The underlying rule or invariant
    verification_cmd: str                      # OS command used to verify the fix
    occurred_at: Optional[str] = None
    resolved_at: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RescueLoop":
        return cls(**data)


@dataclass
class NegativeConstraint:
    """
    A forbidden anti-pattern discovered during execution, dual-axis review,
    or ledger debt analysis.
    """
    constraint_id: str
    rule_id: str
    title: str
    anti_pattern: str                          # Description of what not to do
    risk: str                                  # Why it fails (ACID race, compiler break, gate reject)
    required_pattern: str                      # The required positive replacement
    severity: str = "CRITICAL"                 # CRITICAL | WARNING | ADVISORY
    source: str = "ledger"                     # ledger | review_finding | guard_failure | git_commit

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NegativeConstraint":
        return cls(**data)


@dataclass
class DiffPattern:
    """
    An AST / Code diff pattern contrasting old monolithic code against
    new modular, clean-architecture code.
    """
    domain: str
    target_file: str
    scaffolded_files: List[str] = field(default_factory=list)
    before_code: str = ""
    after_code: str = ""
    description: str = ""
    net_lines: int = 0
    target_delta: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiffPattern":
        return cls(**data)


@dataclass
class PlaybookProposal:
    """
    An evidence-based operational proposal for a discovered or existing domain.
    """
    proposal_id: str
    domain_name: str                           # feature | refactor | reconcile | harmonize
    title: str
    summary: str
    crisis_context: Dict[str, Any] = field(default_factory=dict)
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
            "proposal_id": self.proposal_id,
            "domain_name": self.domain_name,
            "title": self.title,
            "summary": self.summary,
            "crisis_context": self.crisis_context,
            "chronological_steps": [c.to_dict() for c in self.chronological_steps],
            "two_headed_divergence_analysis": self.two_headed_divergence_analysis,
            "seam_establishment_recipes": list(self.seam_establishment_recipes),
            "rescue_loops": [r.to_dict() for r in self.rescue_loops],
            "negative_constraints": [n.to_dict() for n in self.negative_constraints],
            "diff_patterns": [d.to_dict() for d in self.diff_patterns],
            "proposed_rules": list(self.proposed_rules),
            "verification_checklist": list(self.verification_checklist),
            "created_at": self.created_at,
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
    """
    Aggregate distillation artifact containing all mined evidence, patterns,
    and references for generating a domain playbook.
    """
    domain: str
    track: str = "core"                        # core | ui
    target_file: str = ""
    scaffolded_files: List[str] = field(default_factory=list)
    base_branch: str = "feat/nextjs-clean-monolith"
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
            "domain": self.domain,
            "track": self.track,
            "target_file": self.target_file,
            "scaffolded_files": list(self.scaffolded_files),
            "base_branch": self.base_branch,
            "active_branch": self.active_branch,
            "ticket_id": self.ticket_id,
            "rescue_loops": [r.to_dict() for r in self.rescue_loops],
            "negative_constraints": [n.to_dict() for n in self.negative_constraints],
            "diff_patterns": [d.to_dict() for d in self.diff_patterns],
            "compiler_fixes": list(self.compiler_fixes),
            "test_seams": list(self.test_seams),
            "resolved_debt_items": list(self.resolved_debt_items),
            "session": self.session.to_dict() if self.session else None,
            "created_at": self.created_at,
            "playbook_path": self.playbook_path,
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
