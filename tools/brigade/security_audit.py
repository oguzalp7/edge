"""Incremental Security Audit, Automated Refutation, Shared Coverage Ledger & Core Triage facade."""

from __future__ import annotations

import importlib
from typing import Any, Tuple

from tools.brigade.security.models import CoverageLedger, CoverageUnit, SecurityAuditReport, SecurityFinding, SecurityTrace
from tools.brigade.security.report import format_security_report
from tools.brigade.security.runner import run_security_audit
from tools.brigade.security.triage import triage_security_findings
from tools.brigade.security.artifacts import validate_security_artifacts

__all__ = [
    "CoverageUnit",
    "CoverageLedger",
    "SecurityTrace",
    "SecurityFinding",
    "SecurityAuditReport",
    "validate_security_artifacts",
    "run_security_audit",
    "triage_security_findings",
    "format_security_report",
]
_SECURITY_SUBMODULES: Tuple[str, ...] = (
    "constants", "models", "validate", "artifacts", "exclusions", "js_masker",
    "refutation", "call_args", "policies", "call_graph", "scanners_abac", "scanners_sinks",
    "ledger_select", "ledger", "runner", "triage", "report",
)


def __getattr__(name: str) -> Any:
    for sub in _SECURITY_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.security.{sub}")
        if name in mod.__dict__:
            return mod.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
