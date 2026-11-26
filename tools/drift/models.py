#!/usr/bin/env python3
"""
Data models and frontmatter parsing facade for edge-drift.
Re-exports path_matcher, domain_doc, and state_store contracts for backward compatibility.
"""

from tools.drift.domain_doc import (
    INV_PAT_DEF_RE,
    LEGACY_ERROR_TAGS,
    LEGACY_FRONTMATTER_TAGS,
    LEGACY_WARNING_TAGS,
    CanonicalDomainDoc,
    OntologyIssue,
    OntologyReport,
    parse_canonical_domain_doc,
    parse_context_glossary,
)
from tools.drift.path_matcher import (
    _glob_to_regex,
    matches_tracked_paths,
    parse_domain_frontmatter,
)
from tools.drift.state_store import (
    DomainContract,
    DomainDriftRecord,
    DriftCheckResult,
    DriftStateStore,
    SpecDiscoveryReport,
)

__all__ = [
    "matches_tracked_paths",
    "parse_domain_frontmatter",
    "DomainContract",
    "DomainDriftRecord",
    "DriftCheckResult",
    "SpecDiscoveryReport",
    "DriftStateStore",
    "LEGACY_ERROR_TAGS",
    "LEGACY_WARNING_TAGS",
    "LEGACY_FRONTMATTER_TAGS",
    "INV_PAT_DEF_RE",
    "CanonicalDomainDoc",
    "OntologyIssue",
    "OntologyReport",
    "parse_canonical_domain_doc",
    "parse_context_glossary",
]
