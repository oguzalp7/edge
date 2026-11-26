"""BrigadeFSM mixin: guards_verify."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import shutil
import sys

from tools.brigade.fsm_ops.mode_validators import _check_missing_expected_files, _validate_mode_a, _validate_mode_b, _validate_mode_c
from tools.brigade.fsm_ops.sloc_deltas import _compute_sloc_deltas
from tools.brigade.fsm_ops.spec_expected import _extract_spec_expected_files
from tools.brigade.fsm_ops.spec_files import _is_non_prod_file, _parse_porcelain_paths
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.common import normalize_target_path, run_command


class FsmGuardsVerifyMixin:
    """Mixin providing guards_verify operations for BrigadeFSM."""

    def _validate_modes(
        self,
        ticket: Ticket,
        target_file_norm: str,
        target_file_raw: str,
        all_changed_files: List[str],
        prod_changed_files: List[str],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        expected_files = getattr(ticket, "expected_files", None) or []
        if expected_files:
            return _validate_mode_a(expected_files, target_file_norm, all_changed_files, prod_changed_files)
        if target_file_norm:
            return _validate_mode_b(target_file_norm, all_changed_files, target_file_raw)
        return _validate_mode_c(prod_changed_files, all_changed_files)

    def guard_surgery_to_verify(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates surgery invariants via git diff:
        1. MigrationGate Invariant: Zero schema or drizzle files touched (on refactor tracks).
        2. Target File Modification / Multi-file / New-file scope verification (Modes A, B, C).
        3. Records SLOC delta telemetry.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found in SURGERY state.", {}

        base_ref = self.state.base_branch
        all_changed_files = self._collect_all_changed_files(base_ref)
        prod_changed_files = [f for f in all_changed_files if not _is_non_prod_file(f)]

        is_violation, v_msg, v_details = self._check_migration_gate_violation(ticket, all_changed_files)
        if is_violation:
            return False, v_msg, v_details

        numstat_out = self._get_numstat_output(base_ref)
        target_file_raw = ticket.target_file or ""
        target_file_norm = target_file_raw.replace("\\", "/").strip()
        target_file_norm = target_file_norm[2:] if target_file_norm.startswith("./") else target_file_norm

        eff_dir = normalize_target_path(ticket.worktree_path) if ticket.worktree_path else self.target_repo
        target_delta, total_net, _ = _compute_sloc_deltas(
            numstat_out, prod_changed_files, target_file_norm, eff_dir
        )

        ok, msg, details = self._validate_modes(
            ticket, target_file_norm, target_file_raw, all_changed_files, prod_changed_files
        )
        if not ok:
            return False, msg, details

        return (
            True,
            f"Surgery invariants passed: Target file delta {target_delta:+d} lines (Net SLOC: {total_net:+d}).",
            {
                "target_delta": target_delta,
                "total_net": total_net,
                "modified_files": all_changed_files,
            },
        )

