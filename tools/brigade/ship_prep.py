"""
Per-Spec Ship Engine & Specs-to-PR Bridge for Edge Brigade.
Deterministically discovers changed specs between <base>..HEAD, runs scoped
ProofVerifier validation, constructs per-spec SpecShipPlan payloads (lean
2-section PR bodies with ## Summary and ## Evidence), and optionally creates
isolated ship/<spec-slug> branches via --split-branches.
@intent Synthesize two-tier ship branches, PR summaries, and door-brake validations
@concepts two-tier-delivery, refactor-receipt-binding, one-way-door-brake
@invariants [INV-DELIVERY-DEV-FIRST], [INV-DELIVERY-LEAN-PR]
"""

import importlib
from typing import Any, Tuple

from tools.common import normalize_target_path, run_command
from tools.brigade.ship.context_index import parse_index_diff
from tools.brigade.ship.danger import classify_merge_danger
from tools.brigade.ship.evidence import publish_screenshots_to_evidence_branch
from tools.brigade.ship.models import IndexChange, RealizationAudit, ShipPrepResult, SpecDigest, SpecShipPlan
from tools.brigade.ship.orchestrator import prepare_ship_payload
from tools.brigade.ship.render_output import format_ship_output
from tools.brigade.ship.spec_parser import parse_spec_document
from tools.brigade.ship.specs import discover_changed_specs
from tools.brigade.ship.split_branches import create_split_branches
from tools.brigade.ship.topology import validate_branch_topology
from tools.brigade.ship.topology_config import resolve_stage_branches

__all__ = [
    "IndexChange",
    "SpecDigest",
    "RealizationAudit",
    "SpecShipPlan",
    "ShipPrepResult",
    "parse_index_diff",
    "classify_merge_danger",
    "resolve_stage_branches",
    "validate_branch_topology",
    "discover_changed_specs",
    "parse_spec_document",
    "create_split_branches",
    "publish_screenshots_to_evidence_branch",
    "prepare_ship_payload",
    "format_ship_output",
]

_SHIP_SUBMODULES: Tuple[str, ...] = (
    'constants',
    'models',
    'paths',
    'paths_spec',
    'context_index',
    'danger_paths',
    'danger_diff',
    'danger_breaks',
    'danger',
    'topology_config',
    'topology',
    'brigade_snapshot',
    'spec_summary',
    'spec_callstack',
    'spec_parser',
    'spec_expected_sections',
    'spec_expected',
    'proof_meta',
    'proof_discovery',
    'proofs',
    'tickets_proofs',
    'tickets_receipts',
    'tickets',
    'specs_candidates',
    'specs',
    'realization_intent',
    'realization',
    'render_refactor',
    'render_examiner',
    'render_sections',
    'render_evidence',
    'render_markdown',
    'render_output',
    'git_commits',
    'git_branches',
    'split_materialize',
    'split_branches',
    'evidence_git',
    'evidence',
    'tier2',
    'plans',
    'plans_refactor',
    'orchestrator_helpers',
    'orchestrator_render',
    'orchestrator',
)


def __getattr__(name: str) -> Any:
    for sub in _SHIP_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.ship.{sub}")
        if name in mod.__dict__:
            return mod.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    names = set(__all__)
    for sub in _SHIP_SUBMODULES:
        mod = importlib.import_module(f"tools.brigade.ship.{sub}")
        names.update(k for k in mod.__dict__ if not k.startswith("__"))
    return sorted(names)
