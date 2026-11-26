"""Navigation economy, guardrail gap, and rule inventory dataclasses."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NavigationFrictionSignal:
    """Deterministic navigation friction and token-economy signal."""

    signal_type: str
    session_id: str
    role: str = "unknown"
    step_index: int = 0
    file_paths: List[str] = field(default_factory=list)
    count: int = 0
    metric_value: int = 0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NavigationFrictionSignal":
        return cls(
            signal_type=str(data["signal_type"]), session_id=str(data["session_id"]),
            role=str(data.get("role", "unknown")), step_index=int(data.get("step_index", 0)),
            file_paths=list(data.get("file_paths") or []), count=int(data.get("count", 0)),
            metric_value=int(data.get("metric_value", 0)), summary=str(data.get("summary", "")),
        )

    def to_toon(self) -> str:
        sid = self.session_id[:8] if self.session_id else "unknown"
        clean_summary = " ".join(self.summary.split())
        return f"- [NAV:{self.signal_type}] session={sid} role={self.role} step={self.step_index} count={self.count} metric={self.metric_value}: {clean_summary}"


@dataclass
class GuardrailGapSignal:
    """Deterministic unwired or missing CI/pre-commit guardrail signal."""

    gap_type: str
    source_file: str
    script_or_check: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuardrailGapSignal":
        return cls(
            gap_type=str(data["gap_type"]), source_file=str(data.get("source_file", "")),
            script_or_check=str(data.get("script_or_check", "")), summary=str(data.get("summary", "")),
        )

    def to_toon(self) -> str:
        return f"- [GUARDRAIL:{self.gap_type}] {self.source_file} ({self.script_or_check}): {self.summary}"


@dataclass
class RuleInventoryItem:
    """Line budget and session citation telemetry for a station/agent rubric file."""

    file_path: str
    line_count: int
    budget_limit: Optional[int] = None
    citation_count: int = 0
    status: str = "OK"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleInventoryItem":
        return cls(
            file_path=str(data["file_path"]), line_count=int(data.get("line_count", 0)),
            budget_limit=data.get("budget_limit"), citation_count=int(data.get("citation_count", 0)),
            status=str(data.get("status", "OK")),
        )

    def to_toon(self) -> str:
        lim = str(self.budget_limit) if self.budget_limit is not None else "none"
        return f"- [RULE:{self.status}] {self.file_path} lines={self.line_count}/{lim} citations={self.citation_count}"
