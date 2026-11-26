"""Submodule: models."""

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import os
import tempfile


@dataclass
class CoverageUnit:
    coverage_id: str
    file_path: str
    file_sha256: str
    surface: str
    boundary: str
    attack_class: str
    status: str  # "covered" | "planned" | "out_of_scope"
    last_audited_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageUnit":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class CoverageLedger:
    version: str = "1.0.0"
    updated_at: str = ""
    units: List[CoverageUnit] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "units": [u.to_dict() for u in self.units],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageLedger":
        raw_units = data.get("units") or []
        units = [CoverageUnit.from_dict(u) if isinstance(u, dict) else u for u in raw_units]
        return cls(
            version=str(data.get("version") or "1.0.0"),
            updated_at=str(data.get("updated_at") or ""),
            units=units,
        )


@dataclass
class SecurityTrace:
    entrypoint: str
    propagation: List[str] = field(default_factory=list)
    sink: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityFinding:
    finding_id: str
    fingerprint: str
    verdict: str  # "confirmed" | "needs_validation" | "rejected"
    severity: Optional[str]
    attack_class: str
    boundary: str
    trace: Dict[str, Any]
    evidence: str
    rejection_reason: Optional[str] = None
    blocker: Optional[str] = None
    fix_target: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityFinding":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class SecurityAuditReport:
    scope_label: str
    audited_at: str
    profile: str
    confirmed_count: int
    needs_validation_count: int
    rejected_count: int
    ledger_covered: int
    ledger_total: int
    passed: bool
    findings: List[SecurityFinding] = field(default_factory=list)
    triage_tickets_created: List[str] = field(default_factory=list)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [f.to_dict() for f in self.findings]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityAuditReport":
        raw = dict(data)
        raw_findings = raw.get("findings") or []
        raw["findings"] = [
            SecurityFinding.from_dict(f) if isinstance(f, dict) else f for f in raw_findings
        ]
        valid = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


def _write_json_atomic(target: Path, payload: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
