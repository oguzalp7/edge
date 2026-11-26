#!/usr/bin/env python3
"""
Scanner and Gated Auditor facade for edge-drift:
Detects architectural and invariant drift between canonical domain contracts
and live code implementation via git diff gating and read-only LLM audit.
@intent Audit domain contracts, resolve CONTEXT.md globs, and validate code/doc ontology
@concepts zero-token-drift-gate, domain-deed, atomic-state-store
@invariants [INV-DRIFT-ZERO-TOKEN], [INV-DRIFT-NO-FAKE-CLEAN], [INV-DRIFT-ARCHIVE-SAFE]
"""

from pathlib import Path
from typing import List, Optional, Tuple, Union

from tools.common.runner import run_command
from tools.drift import consolidator as _consolidator
from tools.drift import diff_checks as _diff_checks
from tools.drift.diff_checks import DRIFT_MODEL
from tools.drift.models import DriftCheckResult
from tools.drift.ontology_validator import validate_ontology
from tools.drift.spec_discovery import (
    EXCLUDED_SPEC_NAMES,
    _discover_domain_contract_files,
    archive_ephemeral_spec,
    discover_specs,
)


def get_head_sha(repo_path: Path) -> str:
    """Gets current git HEAD SHA."""
    return _diff_checks.get_head_sha(repo_path, runner=run_command)


def get_changed_files_since(repo_path: Path, base_sha: str) -> Optional[List[str]]:
    """Returns list of files changed between base_sha and HEAD via git diff --name-only."""
    return _diff_checks.get_changed_files_since(repo_path, base_sha, runner=run_command)


def check_drift(
    repo_path: Union[Path, str],
    model: str = DRIFT_MODEL,
    timeout: int = 180,
) -> List[DriftCheckResult]:
    """Audits canonical docs/<domain>/DOMAIN.md and legacy docs/domains/*.md contracts."""
    return _diff_checks.check_drift(repo_path, model=model, timeout=timeout, runner=run_command)


def consolidate_domain(
    repo_path: Union[Path, str],
    domain: str,
    tracked_paths: List[str],
    source_specs: Optional[List[Path]] = None,
    archive_sources: bool = False,
    model: str = DRIFT_MODEL,
    timeout: int = 180,
) -> Tuple[bool, Path, str]:
    """Distills source specifications and live code into a canonical Domain Deed."""
    return _consolidator.consolidate_domain(
        repo_path,
        domain,
        tracked_paths,
        source_specs=source_specs,
        archive_sources=archive_sources,
        model=model,
        timeout=timeout,
        runner=run_command,
    )


__all__ = [
    "DRIFT_MODEL",
    "EXCLUDED_SPEC_NAMES",
    "archive_ephemeral_spec",
    "discover_specs",
    "get_head_sha",
    "get_changed_files_since",
    "check_drift",
    "validate_ontology",
    "consolidate_domain",
]
