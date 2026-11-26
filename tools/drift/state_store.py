"""
Drift contract dataclasses and atomic DriftStateStore persistence.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


@dataclass
class DomainContract:
    """Canonical domain contract ("Tapu") loaded from docs/domains/<domain>.md."""
    domain: str
    doc_path: str
    tracked_paths: List[str] = field(default_factory=list)
    body: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainContract":
        return cls(
            domain=data.get("domain", ""),
            doc_path=data.get("doc_path", ""),
            tracked_paths=data.get("tracked_paths", []) or [],
            body=data.get("body", ""),
        )


@dataclass
class DomainDriftRecord:
    """State record of a domain contract's last verified git commit SHA."""
    domain: str
    doc_path: str
    last_checked_sha: str
    last_checked_at: str
    tracked_paths: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainDriftRecord":
        return cls(
            domain=data.get("domain", ""),
            doc_path=data.get("doc_path", ""),
            last_checked_sha=data.get("last_checked_sha", ""),
            last_checked_at=data.get("last_checked_at", ""),
            tracked_paths=data.get("tracked_paths", []) or [],
        )


@dataclass
class DriftCheckResult:
    """Outcome of checking a domain contract against live code."""
    domain: str
    status: str
    changed_files: List[str] = field(default_factory=list)
    llm_invoked: bool = False
    summary: str = ""
    findings_markdown: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DriftCheckResult":
        return cls(
            domain=data.get("domain", ""),
            status=data.get("status", "CLEAN"),
            changed_files=data.get("changed_files", []) or [],
            llm_invoked=bool(data.get("llm_invoked", False)),
            summary=data.get("summary", ""),
            findings_markdown=data.get("findings_markdown", ""),
        )


@dataclass
class SpecDiscoveryReport:
    """Report distinguishing canonical domain deeds from ephemeral slice specs."""
    domain_contracts: List[str] = field(default_factory=list)
    ephemeral_candidates: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecDiscoveryReport":
        return cls(
            domain_contracts=data.get("domain_contracts", []) or [],
            ephemeral_candidates=data.get("ephemeral_candidates", []) or [],
        )


@dataclass
class DriftStateStore:
    """Manages loading and atomic saving of <repo>/.edge/drift_state.json."""
    repo_path: Path
    records: Dict[str, DomainDriftRecord] = field(default_factory=dict)
    version: int = 1

    @classmethod
    def load_from_repo(cls, repo_path: Union[Path, str]) -> "DriftStateStore":
        norm_repo = Path(repo_path).resolve()
        state_file = norm_repo / ".edge" / "drift_state.json"
        if not state_file.exists():
            return cls(repo_path=norm_repo, records={})
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return cls.from_dict(data, norm_repo)
        except Exception:
            return cls(repo_path=norm_repo, records={})

    def get_record(self, domain: str) -> Optional[DomainDriftRecord]:
        return self.records.get(domain)

    def update_record(
        self,
        domain: str,
        sha: str,
        doc_path: str,
        tracked_paths: List[str],
    ) -> DomainDriftRecord:
        now_iso = datetime.now(timezone.utc).isoformat()
        rec = DomainDriftRecord(
            domain=domain,
            doc_path=doc_path,
            last_checked_sha=sha,
            last_checked_at=now_iso,
            tracked_paths=tracked_paths,
        )
        self.records[domain] = rec
        self.save()
        return rec

    def save(self) -> None:
        edge_dir = self.repo_path / ".edge"
        edge_dir.mkdir(parents=True, exist_ok=True)
        state_file = edge_dir / "drift_state.json"
        tmp_file = edge_dir / f"drift_state.json.tmp.{os.getpid()}"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, state_file)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "domains": {k: v.to_dict() for k, v in self.records.items()},
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], repo_path: Path) -> "DriftStateStore":
        version = data.get("version", 1)
        raw_domains = data.get("domains", {})
        records = {
            k: DomainDriftRecord.from_dict(v)
            for k, v in raw_domains.items()
            if isinstance(v, dict)
        }
        return cls(repo_path=repo_path, records=records, version=version)
