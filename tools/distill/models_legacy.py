"""Legacy v1 distill data models retained for backward compatibility."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class JournalEntry:
    entry_id: str
    timestamp: str
    step: str
    tag: str = "OBSERVATION"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JournalEntry":
        return cls(**data)


@dataclass
class DistillSession:
    session_id: str
    repo_path: str
    started_at: str
    status: str = "RECORDING"
    goal: str = ""
    operational_domain: str = "reconcile"
    baseline_commit: Optional[str] = None
    final_commit: Optional[str] = None
    resolved_at: Optional[str] = None
    journal_entries: List[JournalEntry] = field(default_factory=list)
    initial_metrics: Dict[str, Any] = field(default_factory=dict)
    resolution_notes: Optional[str] = None
    proposal_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["journal_entries"] = [j.to_dict() for j in self.journal_entries]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillSession":
        raw = dict(data)
        if "journal_entries" in raw:
            raw["journal_entries"] = [JournalEntry.from_dict(j) for j in raw["journal_entries"]]
        return cls(**raw)


@dataclass
class RescueLoop:
    loop_id: str
    stage: str
    symptom: str
    root_cause: str
    remediation: str
    rule_enforced: str
    verification_cmd: str
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
    constraint_id: str
    rule_id: str
    title: str
    anti_pattern: str
    risk: str
    required_pattern: str
    severity: str = "CRITICAL"
    source: str = "ledger"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NegativeConstraint":
        return cls(**data)
