from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional
import hashlib
from datetime import datetime, timezone


class StationRole(str, Enum):
    SPEC_WRITER = "spec_writer"               # Translator & N-Spec Slicer (with lavish-axi UI approval)
    RESEARCHER = "researcher"                 # Deep Research & Root Cause Analyzer
    SEAM_ARCHITECT = "seam_architect"         # Contract & Red Test Author (TDD anchor)
    CODER = "coder"                           # Coding Worker (Turns red tests green)
    SURGEON = "surgeon"                       # Chef de Partie: Code refactoring & DB leak extraction
    EXAMINER = "examiner"                     # Sous Chef / Maître d': Unified standards & spec verification
    QA_ENGINEER = "qa_engineer"               # Sommelier: E2E Browser QA & Visual QA


class CycleState(str, Enum):
    IDLE = "IDLE"                             # Ready for next ticket
    TRIAGE = "TRIAGE"                         # Ticket prepared from radar debt ledger
    SURGERY = "SURGERY"                       # Refactor branch active, surgeon operating
    VERIFY = "VERIFY"                         # Characterization test & compiler verification
    REVIEW = "REVIEW"                         # Dual-axis review by standards & spec examiners
    POLISH = "POLISH"                         # Targeted remediation of review findings
    GATE = "GATE"                             # Edge Verification Gate (gate.py)
    STAGING = "STAGING"                       # Squash-merge to base branch & radar ledger update
    COMPLETED = "COMPLETED"                   # Hillclimbing micro-slice verified and delivered
    BLOCKED = "BLOCKED"                       # Guard failed; manual triage or fix needed
    STAGNATED = "STAGNATED"                   # Max retries exceeded without health improvement, rolled back
    PAUSED = "PAUSED"                         # Safely paused with durable checkpoint


class ContextHeatZone(str, Enum):
    GREEN = "GREEN"                           # < 180k tokens: Normal execution
    YELLOW = "YELLOW"                         # 180k - 250k tokens: Drain active ticket, freeze triage
    RED = "RED"                               # > 250k tokens: Emergency checkpoint, stop immediately


@dataclass
class Station:
    role: str
    conversation_id: str
    name: str
    status: str = "IDLE"                      # IDLE, BUSY, ERROR
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Station":
        return cls(**data)


@dataclass
class ReviewFinding:
    axis: str                                 # "standards" | "spec"
    severity: str                             # "CRITICAL" | "WARNING" | "ADVISORY"
    file_path: str
    rule: str
    description: str
    suggested_fix: str
    line_number: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReviewFinding":
        return cls(**data)


@dataclass
class Ticket:
    ticket_id: str
    track: str                                # "core" | "ui"
    domain: str                               # e.g. "customers", "bookings"
    rule_id: str
    severity: str
    target_file: str
    line_number: int
    fingerprint: str
    description: str
    suggested_fix: str
    branch_name: str
    test_seam_command: str
    scaffolding_allowance: int = 0
    target_symbol: Optional[str] = None
    negative_constraints: List[str] = field(default_factory=list)
    worktree_path: Optional[str] = None
    escalation_reason: Optional[str] = None
    escalation_at: Optional[str] = None
    captain_decision: Optional[str] = None
    health_before: Optional[float] = None
    health_after: Optional[float] = None
    sloc_before: Optional[int] = None
    sloc_after: Optional[int] = None
    attempt_count: int = 1
    max_attempts: int = 2
    status: str = "OPEN"                      # "OPEN" | "RESOLVED" | "STAGNATED" | "ESCALATED"
    enforce_contraction: bool = False         # Decoupled from hard line reduction requirement
    allow_schema_migration: bool = False      # Allowed for feature track or schema expansion
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @staticmethod
    def generate_id(track: str, domain: str, rule_id: str, line_number: int) -> str:
        raw = f"{track}:{domain}:{rule_id}:{line_number}"
        return f"TICK-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8].upper()}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Ticket":
        return cls(**data)


@dataclass
class TransitionLog:
    from_state: str
    to_state: str
    timestamp: str
    success: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TransitionLog":
        return cls(**data)


@dataclass
class BrigadeState:
    version: str = "1.0.0"
    repo_path: str = "."
    base_branch: str = "development"
    current_state: CycleState = CycleState.IDLE
    active_ticket: Optional[Ticket] = None
    active_branch: Optional[str] = None
    active_worktree: Optional[str] = None
    stations: Dict[str, Station] = field(default_factory=dict)
    review_findings: List[ReviewFinding] = field(default_factory=list)
    history: List[TransitionLog] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "repo_path": self.repo_path,
            "base_branch": self.base_branch,
            "current_state": self.current_state.value if isinstance(self.current_state, CycleState) else str(self.current_state),
            "active_ticket": self.active_ticket.to_dict() if self.active_ticket else None,
            "active_branch": self.active_branch,
            "active_worktree": self.active_worktree,
            "stations": {k: v.to_dict() for k, v in self.stations.items()},
            "review_findings": [f.to_dict() for f in self.review_findings],
            "history": [h.to_dict() for h in self.history],
            "blocked_reason": self.blocked_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrigadeState":
        raw = dict(data)
        if "current_state" in raw and raw["current_state"]:
            raw["current_state"] = CycleState(raw["current_state"])
        if "active_ticket" in raw and raw["active_ticket"]:
            raw["active_ticket"] = Ticket.from_dict(raw["active_ticket"])
        if "stations" in raw and isinstance(raw["stations"], dict):
            migrated_stations: Dict[str, Station] = {}
            for k, v in raw["stations"].items():
                if k == "expediter":
                    continue
                if k in ("standards_examiner", "spec_examiner"):
                    if "examiner" not in migrated_stations:
                        v_copy = dict(v) if isinstance(v, dict) else (v.to_dict() if hasattr(v, "to_dict") else dict(v))
                        v_copy["role"] = StationRole.EXAMINER.value
                        migrated_stations["examiner"] = Station.from_dict(v_copy)
                    continue
                migrated_stations[k] = Station.from_dict(v) if isinstance(v, dict) else v
            raw["stations"] = migrated_stations
        if "review_findings" in raw and isinstance(raw["review_findings"], list):
            raw["review_findings"] = [ReviewFinding.from_dict(f) for f in raw["review_findings"]]
        if "history" in raw and isinstance(raw["history"], list):
            raw["history"] = [TransitionLog.from_dict(h) for h in raw["history"]]
        return cls(**raw)


@dataclass
class Checkpoint:
    version: str = "1.0.0"
    paused_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = "MANUAL_PAUSE"               # CONTEXT_LIMIT | YELLOW_ZONE_DRAIN | RED_ZONE_EMERGENCY | HUMAN_PAUSE | ESCALATED
    base_branch: str = "development"
    active_branch: Optional[str] = None
    worktree_path: Optional[str] = None
    active_ticket: Optional[Ticket] = None
    fsm_state: str = "IDLE"                   # State machine state prior to pause
    completed_substeps: List[str] = field(default_factory=list)
    pending_substeps: List[str] = field(default_factory=list)
    wip_commit_sha: Optional[str] = None
    has_uncommitted_work: bool = False
    next_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "paused_at": self.paused_at,
            "reason": self.reason,
            "base_branch": self.base_branch,
            "active_branch": self.active_branch,
            "worktree_path": self.worktree_path,
            "active_ticket": self.active_ticket.to_dict() if self.active_ticket else None,
            "fsm_state": self.fsm_state,
            "completed_substeps": list(self.completed_substeps),
            "pending_substeps": list(self.pending_substeps),
            "wip_commit_sha": self.wip_commit_sha,
            "has_uncommitted_work": self.has_uncommitted_work,
            "next_action": self.next_action,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        raw = dict(data)
        if "active_ticket" in raw and raw["active_ticket"]:
            raw["active_ticket"] = Ticket.from_dict(raw["active_ticket"])
        return cls(**raw)


