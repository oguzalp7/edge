"""
MUTATOR: Alias-Aware Differential Core Mutation Gate.
"""

from .sites import MutationSite, discover_mutation_sites, apply_mutation
from .overlay import create_worker_overlay, cleanup_worker_overlay
from .runner import MutantOutcome, MutationSummary, enforce_core_scope, run_mutation_suite

__all__ = [
    "MutationSite",
    "discover_mutation_sites",
    "apply_mutation",
    "create_worker_overlay",
    "cleanup_worker_overlay",
    "MutantOutcome",
    "MutationSummary",
    "enforce_core_scope",
    "run_mutation_suite",
]
