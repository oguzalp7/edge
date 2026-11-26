"""Submodule: validate."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.security.constants import _AUDIT_EXTS, _IGNORED_DIRS, _JS_TS_EXTS, _USE_SERVER_DIRECTIVE_RE, _VALID_LEDGER_STATUSES, _VALID_SEVERITIES, _VALID_VERDICTS
from tools.brigade.security.models import CoverageLedger, SecurityFinding

def _validate_single_finding(f: SecurityFinding) -> List[str]:
    errs: List[str] = []
    if f.verdict not in _VALID_VERDICTS:
        errs.append(f"{f.finding_id}: invalid verdict '{f.verdict}'")
    if f.verdict == "confirmed":
        if f.severity not in _VALID_SEVERITIES:
            errs.append(f"{f.finding_id}: confirmed finding missing valid severity")
        if not f.trace.get("entrypoint") or not f.trace.get("sink"):
            errs.append(f"{f.finding_id}: confirmed finding requires trace.entrypoint and trace.sink")
        return errs
    if f.severity is not None:
        errs.append(f"{f.finding_id}: unconfirmed finding ({f.verdict}) must have severity=None")
    if f.verdict == "rejected" and not (f.rejection_reason or "").strip():
        errs.append(f"{f.finding_id}: rejected finding requires rejection_reason")
    return errs


def validate_security_artifacts(
    ledger: CoverageLedger,
    findings: List[SecurityFinding],
) -> Tuple[bool, List[str]]:
    """Enforces Cloudflare 3-verdict invariants (non-confirmed => severity=None) and ledger schema."""
    errors: List[str] = []
    for unit in ledger.units:
        if unit.status not in _VALID_LEDGER_STATUSES:
            errors.append(f"{unit.coverage_id}: invalid status '{unit.status}'")
        if unit.status == "covered" and not (unit.file_sha256 or "").strip():
            errors.append(f"{unit.coverage_id}: covered unit missing file_sha256")
    for finding in findings:
        errors.extend(_validate_single_finding(finding))
    return (len(errors) == 0), errors
