"""
Finite State Machine Engine for Edge Brigade.
Deterministic state transitions driven strictly by OS process exit codes
and hard data invariants, never by LLM self-evaluation.
"""

import importlib
from pathlib import Path
from typing import Any, Tuple

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.models import BrigadeState, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket
from tools.brigade.proof_verifier import ProofVerifier, SubstepList, _validate_qa_proof_receipt
from tools.brigade.stations import StationRegistry
from tools.brigade.worktree import (
    acquire_worktree,
    get_pool_status,
    is_treehouse_installed,
    is_worktree_backend_available,
    prune_worktrees,
    return_worktree,
)
from tools.common import normalize_target_path, run_command

if not hasattr(BrigadeState, "guard_failures"):
    BrigadeState.guard_failures = property(lambda self: [h for h in self.history if not h.success])

from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD
from tools.brigade.fsm_ops.core_mixin import FsmCoreMixin
from tools.brigade.fsm_ops.guards_entry import FsmGuardsEntryMixin
from tools.brigade.fsm_ops.guards_verify import FsmGuardsVerifyMixin
from tools.brigade.fsm_ops.guards_hermetic import FsmGuardsHermeticMixin
from tools.brigade.fsm_ops.guards_review import FsmGuardsReviewMixin
from tools.brigade.fsm_ops.guards_visual import FsmGuardsVisualMixin
from tools.brigade.fsm_ops.guards_gate import FsmGuardsGateMixin
from tools.brigade.fsm_ops.guards_qa import FsmGuardsQaMixin
from tools.brigade.fsm_ops.handoff import FsmHandoffMixin
from tools.brigade.fsm_ops.staging_archive import FsmStagingArchiveMixin
from tools.brigade.fsm_ops.staging_sync import FsmStagingSyncMixin
from tools.brigade.fsm_ops.advance_dispatch import FsmAdvanceDispatchMixin
from tools.brigade.fsm_ops.transitions import FsmTransitionsMixin
from tools.brigade.fsm_ops.triage import FsmTriageMixin
from tools.brigade.fsm_ops.metrics_capture import FsmMetricsCaptureMixin
from tools.brigade.fsm_ops.slice_start import FsmSliceStartMixin
from tools.brigade.fsm_ops.refactor_seal import FsmRefactorSealMixin
from tools.brigade.fsm_ops.ship_pr import FsmShipPrMixin
from tools.brigade.fsm_ops.ship_finish import FsmShipFinishMixin
from tools.brigade.fsm_ops.pause_resume import FsmPauseResumeMixin
from tools.brigade.fsm_ops.heat import FsmHeatMixin

__all__ = [
    "BrigadeFSM",
    "ProofVerifier",
    "SubstepList",
    "FlightRecorder",
    "GREEN_HEAT_THRESHOLD",
    "YELLOW_HEAT_THRESHOLD",
    "VERIFICATION_TIMEOUT_SECONDS",
    "run_command",
    "acquire_worktree",
    "return_worktree",
    "is_treehouse_installed",
    "is_worktree_backend_available",
    "prune_worktrees",
]


class BrigadeFSM(
    FsmCoreMixin,
    FsmGuardsEntryMixin,
    FsmGuardsVerifyMixin,
    FsmGuardsHermeticMixin,
    FsmGuardsReviewMixin,
    FsmGuardsVisualMixin,
    FsmGuardsGateMixin,
    FsmGuardsQaMixin,
    FsmHandoffMixin,
    FsmStagingArchiveMixin,
    FsmStagingSyncMixin,
    FsmAdvanceDispatchMixin,
    FsmTransitionsMixin,
    FsmTriageMixin,
    FsmMetricsCaptureMixin,
    FsmSliceStartMixin,
    FsmRefactorSealMixin,
    FsmShipPrMixin,
    FsmShipFinishMixin,
    FsmPauseResumeMixin,
    FsmHeatMixin,
):
    """Finite State Machine orchestrating Edge Brigade ticket lifecycle and deterministic guards."""


_LAZY_SUBMODULES: Tuple[str, ...] = (
    "tools.brigade.proof_verifier",
    "tools.brigade.fsm_ops.spec_files",
    "tools.brigade.fsm_ops.spec_expected",
    "tools.brigade.fsm_ops.mode_validators",
    "tools.brigade.fsm_ops.sloc_deltas",
    "tools.brigade.fsm_ops.constants",
)


def __getattr__(name: str) -> Any:
    for mod_path in _LAZY_SUBMODULES:
        mod = importlib.import_module(mod_path)
        if name in mod.__dict__:
            return mod.__dict__[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
