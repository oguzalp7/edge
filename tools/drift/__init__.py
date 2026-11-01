#!/usr/bin/env python3
"""
tools.drift - Git-diff gated domain contract drift detector,
ephemeral spec archiver, and domain consolidator for Edge Plugin.
"""

from .models import (
    DomainContract,
    DomainDriftRecord,
    DriftCheckResult,
    SpecDiscoveryReport,
    DriftStateStore,
    parse_domain_frontmatter,
    matches_tracked_paths,
)
from .scanner import (
    DRIFT_MODEL,
    archive_ephemeral_spec,
    check_drift,
    discover_specs,
    consolidate_domain,
    get_head_sha,
    get_changed_files_since,
)
from .cli import run_drift, main

__all__ = [
    "DomainContract",
    "DomainDriftRecord",
    "DriftCheckResult",
    "SpecDiscoveryReport",
    "DriftStateStore",
    "parse_domain_frontmatter",
    "matches_tracked_paths",
    "DRIFT_MODEL",
    "archive_ephemeral_spec",
    "check_drift",
    "discover_specs",
    "consolidate_domain",
    "get_head_sha",
    "get_changed_files_since",
    "run_drift",
    "main",
]
