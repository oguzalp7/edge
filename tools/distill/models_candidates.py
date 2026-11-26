"""Candidate rule and watermark state dataclasses for edge-distill."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class CandidateRule:
    candidate_id: str
    fingerprint: str
    rule_text: str
    target_role: str
    scope_class: str
    stack_tokens_matched: List[str] = field(default_factory=list)
    first_seen_at: str = ""
    last_seen_at: str = ""
    source_projects: List[str] = field(default_factory=list)
    occurrence_count: int = 1
    status: str = "INCUBATING"
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateRule":
        return cls(**data)

    def to_toon(self) -> str:
        return f"- [CANDIDATE:{self.candidate_id}] role={self.target_role} status={self.status} projects={len(self.source_projects)}: {self.rule_text}"


@dataclass
class DistillWatermarkState:
    version: str = "2.1"
    last_harvested_at: str = ""
    processed_sessions: List[str] = field(default_factory=list)
    project_sessions: Dict[str, List[str]] = field(default_factory=dict)
    factory_processed_sessions: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "last_harvested_at": self.last_harvested_at,
            "processed_sessions": list(self.processed_sessions),
            "project_sessions": {k: list(v) for k, v in self.project_sessions.items()},
            "factory_processed_sessions": list(self.factory_processed_sessions),
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillWatermarkState":
        raw = dict(data)
        raw.setdefault("factory_processed_sessions", [])
        raw.setdefault("project_sessions", {})
        raw.setdefault("processed_sessions", [])
        raw.setdefault("metrics", {})
        return cls(**raw)
