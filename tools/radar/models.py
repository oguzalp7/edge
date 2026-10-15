from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Dict, Any, Optional
import hashlib
from datetime import datetime, timezone


class Track(str, Enum):
    UI = "ui"
    CORE = "core"
    GOVERNANCE = "governance"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"   # Must fix before merge / architectural violation
    WARNING = "WARNING"     # Bad smell, debt accumulating
    ADVISORY = "ADVISORY"   # Improvement opportunity


@dataclass
class LedgerItem:
    fingerprint: str
    track: str
    rule_id: str
    title: str
    file_path: str
    line_number: int
    symbol: Optional[str]
    severity: str
    status: str
    details: Dict[str, Any]
    suggested_fix: str
    first_seen_at: str
    last_seen_at: str
    resolved_at: Optional[str] = None

    @staticmethod
    def generate_fingerprint(rule_id: str, file_path: str, symbol: Optional[str] = None, signature: Optional[str] = None) -> str:
        """Deterministically generates a 12-char SHA256 hex fingerprint for idempotency."""
        raw = f"{rule_id}:{file_path}:{symbol or ''}:{signature or ''}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LedgerItem":
        return cls(**data)


@dataclass
class ChannelSummary:
    track: str
    health_score: float
    total_open: int
    critical_count: int
    warning_count: int
    advisory_count: int
    resolved_count: int
    macro_patterns: List[str] = field(default_factory=list)
    items: List[LedgerItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track": self.track,
            "health_score": round(self.health_score, 1),
            "total_open": self.total_open,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "advisory_count": self.advisory_count,
            "resolved_count": self.resolved_count,
            "macro_patterns": self.macro_patterns,
            "items": [item.to_dict() for item in self.items],
        }
