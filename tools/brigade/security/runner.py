"""Submodule: runner."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import hashlib

from tools.brigade.security.models import CoverageLedger, SecurityAuditReport, _write_json_atomic
from tools.brigade.security.validate import _discover_repo_sources
from tools.brigade.security.ledger_select import _build_scope_label, _load_prior_findings, _load_prior_ledger, _select_active_targets
from tools.brigade.security.ledger import _ensure_security_dir_excluded, _merge_ledger_and_findings

def run_security_audit(
    repo_path: Path, scopes: Optional[List[str]] = None, diff_only: bool = False,
    base_ref: Optional[str] = None, recursive: bool = False, changed_files: Optional[List[str]] = None,
    profile: str = "standard", out_dir: Optional[Path] = None,
) -> SecurityAuditReport:
    """Runs incremental 4-class security audit with automated refutation and shared ledger updates."""
    from tools.common.profiles import has_profile_capability, resolve_active_profiles

    repo = Path(repo_path).resolve()
    sec_dir = Path(out_dir) if out_dir else (repo / ".edge" / "security")
    now_iso = datetime.now(timezone.utc).isoformat()
    if out_dir is None:
        _ensure_security_dir_excluded(repo)
    sources = _discover_repo_sources(repo)
    shas = {rel: hashlib.sha256(p.read_bytes()).hexdigest() for rel, p in sources.items()}
    profiles = resolve_active_profiles(repo)
    allow_sa = profiles.source not in ("explicit", "explicit_none") or has_profile_capability(profiles, "server_actions")
    active = _select_active_targets(sources, shas, _load_prior_ledger(sec_dir), scopes, diff_only, base_ref, recursive, changed_files, repo)
    units, merged = _merge_ledger_and_findings(sources, shas, active, _load_prior_ledger(sec_dir), _load_prior_findings(sec_dir), now_iso, allow_server_actions=allow_sa)
    _write_json_atomic(sec_dir / "coverage-ledger.json", CoverageLedger(version="1.0.0", updated_at=now_iso, units=units).to_dict())
    _write_json_atomic(sec_dir / "findings.json", {"version": "1.0.0", "updated_at": now_iso, "findings": [f.to_dict() for f in merged]})
    confirmed = sum(1 for f in merged if f.verdict == "confirmed")
    return SecurityAuditReport(
        scope_label=_build_scope_label(scopes, diff_only, changed_files), audited_at=now_iso, profile=profile,
        confirmed_count=confirmed, needs_validation_count=sum(1 for f in merged if f.verdict == "needs_validation"),
        rejected_count=sum(1 for f in merged if f.verdict == "rejected"), ledger_covered=sum(1 for u in units if u.status == "covered"),
        ledger_total=len(units), passed=(confirmed == 0), findings=merged,
    )
