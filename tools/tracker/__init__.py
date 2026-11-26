"""
Edge Tracker Core Adapter package (GitHub Issues + native Sub-issues + local fallback).
"""

from .backends import TrackerBackend, has_github_remote, resolve_backend
from .cache import cache_issue_spec
from .gh_axi_backend import GhAxiBackend
from .gh_cli_backend import GhCliBackend
from .local_backend import LocalTrackerBackend
from .models import (
    CANONICAL_LABELS,
    TrackerAuthError,
    TrackerBackendKind,
    TrackerComment,
    TrackerError,
    TrackerIssue,
    TrackerNotFoundError,
)

__all__ = [
    "CANONICAL_LABELS",
    "GhAxiBackend",
    "GhCliBackend",
    "LocalTrackerBackend",
    "TrackerAuthError",
    "TrackerBackend",
    "TrackerBackendKind",
    "TrackerComment",
    "TrackerError",
    "TrackerIssue",
    "TrackerNotFoundError",
    "cache_issue_spec",
    "has_github_remote",
    "resolve_backend",
]
