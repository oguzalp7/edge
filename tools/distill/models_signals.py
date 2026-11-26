"""Core v2 signal dataclasses for station escapes, tool friction, and escalations."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StationEscapeSignal:
    signal_id: str
    station_role: str
    escape_type: str
    description: str
    evidence: str
    timestamp: str
    conversation_id: str
    step_index: Optional[int] = None
    ticket_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StationEscapeSignal":
        return cls(**data)

    def to_toon(self) -> str:
        cid_short = self.conversation_id[:8] if self.conversation_id else "unknown"
        step_str = f"step {self.step_index}" if self.step_index is not None else "step ?"
        return f"- [ESCAPE:{self.station_role}] {self.escape_type}: {self.description} ({step_str}, {cid_short})"


def _extract_meaningful_error_snippet(error_output: str, max_len: int = 80) -> str:
    if "Log tail:\n" not in error_output:
        return " ".join(error_output.strip().splitlines())[:max_len]
    tail = error_output.split("Log tail:\n", 1)[1]
    lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
    if not lines:
        return " ".join(error_output.strip().splitlines())[:max_len]
    markers = ("error", "exception", "traceback", "fail", "fatal", "killed", "panic")
    hit = next((ln[:max_len] for ln in reversed(lines) if any(m in ln.lower() for m in markers)), None)
    return hit or lines[-1][:max_len]


@dataclass
class ToolFrictionSignal:
    signal_id: str
    tool_name: str
    command_or_args: str
    error_output: str
    conversation_id: str
    step_index: int
    timestamp: str
    exit_code: Optional[int] = None
    error_type: str = "COMMAND_FAILURE"
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolFrictionSignal":
        return cls(**data)

    @property
    def command(self) -> str:
        return self.command_or_args

    def to_toon(self) -> str:
        cmd_short = self.command_or_args.strip().replace("\n", " ")[:60]
        err_short = _extract_meaningful_error_snippet(self.error_output, max_len=80)
        return f"- [TOOL:{self.tool_name}] exit={self.exit_code} retries={self.retry_count}: {cmd_short} -> {err_short}"


def _format_escalation_quotes(occurrences: List[Dict[str, Any]], max_quotes: int = 2) -> str:
    quotes: List[str] = []
    for occ in occurrences:
        raw = str(occ.get("text", "")).strip() if isinstance(occ, dict) else ""
        if raw:
            quotes.append(f'"{" ".join(raw.split())[:80]}"')
            if len(quotes) >= max_quotes:
                break
    return f" | quotes: {'; '.join(quotes)}" if quotes else ""


@dataclass
class RepeatedEscalation:
    escalation_id: str
    category: str
    pattern_key: str
    occurrence_count: int
    occurrences: List[Dict[str, Any]] = field(default_factory=list)
    rule_recommendation: Optional[str] = None
    target_role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepeatedEscalation":
        return cls(**data)

    def to_toon(self) -> str:
        target = f"target={self.target_role}" if self.target_role else "target=all"
        rec = f" -> {self.rule_recommendation}" if self.rule_recommendation else ""
        return f"- [ESCALATION:{self.category}] count={self.occurrence_count} {target}: {self.pattern_key}{rec}{_format_escalation_quotes(self.occurrences)}"
