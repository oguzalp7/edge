from dataclasses import dataclass, field, asdict, fields
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
    SPEC_CRITIC = "spec_critic"               # Goldfish Spec Critic: Cross-provider advisory spec auditor


class CycleState(str, Enum):
    IDLE = "IDLE"                             # Ready for next ticket
    TRIAGE = "TRIAGE"                         # Ticket prepared from radar debt ledger
    RED_TEST = "RED_TEST"                     # Seam Architect establishing failing TDD anchor
    SURGERY = "SURGERY"                       # Refactor branch active, surgeon operating
    VERIFY = "VERIFY"                         # Characterization test & compiler verification
    REVIEW = "REVIEW"                         # Dual-axis review by standards & spec examiners
    POLISH = "POLISH"                         # Targeted remediation of review findings
    GATE = "GATE"                             # Edge Verification Gate (gate.py)
    QA = "QA"                                 # End-to-End Browser & Visual QA Verification
    STAGING = "STAGING"                       # Squash-merge to base branch & radar ledger update
    AWAITING_MERGE = "AWAITING_MERGE"         # PR opened with --auto merge queued; waiting for merge confirmation
    COMPLETED = "COMPLETED"                   # Hillclimbing micro-slice verified and delivered
    BLOCKED = "BLOCKED"                       # Guard failed; manual triage or fix needed
    STAGNATED = "STAGNATED"                   # Max retries exceeded without health improvement, rolled back
    PAUSED = "PAUSED"                         # Safely paused with durable checkpoint


class ContextHeatZone(str, Enum):
    GREEN = "GREEN"                           # < 45k tokens: Normal execution
    YELLOW = "YELLOW"                         # 45k - 75k tokens: Drain active ticket, freeze triage
    RED = "RED"                               # >= 75k tokens: Emergency checkpoint, stop immediately


@dataclass
class Station:
    role: str = ""
    conversation_id: str = ""
    name: str = ""
    status: str = "IDLE"                      # IDLE, BUSY, ERROR
    model: str = "flash"                      # Model pinned to station (default: flash)
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Station":
        raw = dict(data)
        if "conversation_id" not in raw and "conversationId" in raw:
            raw["conversation_id"] = raw["conversationId"]
        role_val = raw.get("role", "")
        if not raw.get("name"):
            raw["name"] = f"{role_val.replace('_', ' ').title()} Station" if role_val else "Station Worker"
        if not raw.get("model"):
            raw["model"] = "flash"
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in raw.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class ReviewFinding:
    axis: str                                 # "standards" | "spec" | "evidence" | "qa"
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
class ExaminerReceipt:
    verdict: str                              # "PASS" | "FAIL"
    summary: str
    ticket_id: Optional[str] = None
    evidence_reviewed: List[str] = field(default_factory=list)
    sealed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    examiner_cid: Optional[str] = None
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExaminerReceipt":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class Ticket:
    ticket_id: str
    track: str                                # "core" | "ui"
    domain: Optional[str]                     # e.g. "customers", "bookings"
    rule_id: str
    severity: str
    target_file: str
    line_number: int
    fingerprint: str
    description: str
    suggested_fix: str
    branch_name: Optional[str] = None
    test_seam_command: str = ""
    scaffolding_allowance: int = 0            # Deprecated/legacy: retained strictly for backward JSON schema compatibility
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
    enforce_contraction: bool = False         # Deprecated/legacy: retained strictly for backward JSON schema compatibility
    allow_schema_migration: bool = False      # Allowed for feature track or schema expansion
    expected_files: List[str] = field(default_factory=list)
    spec_path: Optional[str] = None
    lavish_path: Optional[str] = None         # Path to associated Lavish prototype HTML
    require_qa: Optional[bool] = None         # Explicit override: True=force QA, False=skip QA
    tasks_axi_id: Optional[str] = None        # Optional linked tasks-axi task ID
    issue_number: Optional[int] = None        # Linked tracker issue number (closed on finish)
    parent_issue: Optional[int] = None        # Linked parent Frontier/Spec issue (never auto-closed)
    tracker_offline: bool = False             # Persisted offline tracker preference
    metric_targets: Optional[Dict[str, Any]] = None
    refactor_ticket_path: Optional[str] = None
    before_metrics: Optional[Dict[str, Any]] = None
    surgeon_cid: Optional[str] = None         # Station conversation_id of Surgeon who performed surgery
    pr_url: Optional[str] = None              # Opened PR URL (for AWAITING_MERGE confirmation)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @staticmethod
    def generate_id(track: str, domain: str, rule_id: str, line_number: int) -> str:
        raw = f"{track}:{domain}:{rule_id}:{line_number}"
        return f"TICK-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8].upper()}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Ticket":
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


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
    examiner_receipt: Optional[ExaminerReceipt] = None
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
            "examiner_receipt": self.examiner_receipt.to_dict() if self.examiner_receipt else None,
            "history": [h.to_dict() for h in self.history],
            "blocked_reason": self.blocked_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def _migrate_stations(raw_stations: Dict[str, Any]) -> Dict[str, Station]:
        migrated: Dict[str, Station] = {}
        for k, v in raw_stations.items():
            if k == "expediter":
                continue
            if k in ("standards_examiner", "spec_examiner"):
                if "examiner" not in migrated:
                    v_copy = dict(v) if isinstance(v, dict) else (v.to_dict() if hasattr(v, "to_dict") else dict(v))
                    v_copy["role"] = StationRole.EXAMINER.value
                    migrated["examiner"] = Station.from_dict(v_copy)
                continue
            migrated[k] = Station.from_dict(v) if isinstance(v, dict) else v
        return migrated

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrigadeState":
        raw = dict(data)
        if raw.get("current_state"):
            raw["current_state"] = CycleState(raw["current_state"])
        if raw.get("active_ticket"):
            raw["active_ticket"] = Ticket.from_dict(raw["active_ticket"])
        if isinstance(raw.get("stations"), dict):
            raw["stations"] = cls._migrate_stations(raw["stations"])
        if isinstance(raw.get("review_findings"), list):
            raw["review_findings"] = [ReviewFinding.from_dict(f) for f in raw["review_findings"]]
        receipt_raw = raw.get("examiner_receipt")
        raw["examiner_receipt"] = ExaminerReceipt.from_dict(receipt_raw) if isinstance(receipt_raw, dict) else None
        if isinstance(raw.get("history"), list):
            raw["history"] = [TransitionLog.from_dict(h) for h in raw["history"]]
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in raw.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class Checkpoint:
    version: str = "1.0.0"
    paused_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: str = "MANUAL_PAUSE"               # CONTEXT_LIMIT | YELLOW_ZONE_DRAIN | RED_ZONE_EMERGENCY | HUMAN_PAUSE | ESCALATED
    base_branch: str = "development"
    active_branch: Optional[str] = None
    worktree_path: Optional[str] = None
    active_worktree: Optional[str] = None
    active_ticket: Optional[Ticket] = None
    stashed_ticket: Optional[Dict[str, Any]] = None
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
            "active_worktree": self.active_worktree,
            "active_ticket": self.active_ticket.to_dict() if self.active_ticket else None,
            "stashed_ticket": self.stashed_ticket or (self.active_ticket.to_dict() if self.active_ticket else None),
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
        elif "stashed_ticket" in raw and raw["stashed_ticket"]:
            raw["active_ticket"] = Ticket.from_dict(raw["stashed_ticket"])
        if "active_worktree" not in raw or raw["active_worktree"] is None:
            raw["active_worktree"] = raw.get("worktree_path")
        return cls(**raw)

@dataclass
class QAProofReceipt:
    slug: str
    visited_urls: List[str]
    user_actions_executed: List[str]
    persistence_verified: bool
    console_clean: bool
    screenshot_paths: List[str]
    ticket_id: Optional[str] = None
    timestamp: Optional[str] = None
    browser_cid: Optional[str] = None
    host_facts_verified: bool = True
    db_crosscheck: Dict[str, Any] = field(default_factory=dict)
    ux_defects_logged: int = 0
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QAProofReceipt":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

