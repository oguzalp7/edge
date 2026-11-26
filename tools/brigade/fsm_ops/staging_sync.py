"""BrigadeFSM mixin: staging_sync."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import sys

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.worktree import acquire_worktree, is_treehouse_installed, return_worktree
from tools.common import normalize_target_path, run_command


class FsmStagingSyncMixin:
    """Mixin providing staging_sync operations for BrigadeFSM."""

    def _sync_diverged_worktree(self, ticket: Ticket) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Automates in-situ git rebase inside leased worktree and validates hermetic tests.
        On syntactic conflict or semantic verification failure, aborts and escalates to PAUSED.
        """
        if not ticket.worktree_path:
            return False, (
                f"REFUSED: Branch '{ticket.branch_name}' has diverged from '{self.state.base_branch}' (not a clean fast-forward), "
                f"and no worktree is available for automated rebase. Rebase '{ticket.branch_name}' manually before merging."
            ), {}

        wt_dir = normalize_target_path(ticket.worktree_path)
        if not wt_dir.is_dir():
            return False, f"Leased worktree path does not exist on disk: {wt_dir}", {}

        # 1. Run git rebase <base_branch> inside worktree
        reb_code, reb_out, reb_err = call_facade("run_command", run_command)(["git", "rebase", self.state.base_branch], cwd=wt_dir)
        if reb_code != 0:
            diff_code, diff_out, _ = call_facade("run_command", run_command)(["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt_dir)
            conflicting_files = [line.strip() for line in diff_out.splitlines() if line.strip()]

            call_facade("run_command", run_command)(["git", "rebase", "--abort"], cwd=wt_dir)

            reason = (
                f"Rebase conflict onto {self.state.base_branch}: "
                f"{', '.join(conflicting_files) if conflicting_files else reb_err or reb_out}"
            )
            self.escalate(reason)
            return False, reason, {
                "escalated": True,
                "conflicting_files": conflicting_files,
                "error": reb_err or reb_out,
            }

        # 2. Rebase clean: run hermetic verification on rebased code
        verify_ok, verify_msg = self._run_hermetic_verification(work_dir=wt_dir)
        if not verify_ok:
            reason = f"Post-rebase verification failed on {ticket.branch_name}: {verify_msg}"
            self.escalate(reason)
            return False, reason, {
                "escalated": True,
                "semantic_conflict": True,
                "verification_error": verify_msg,
            }

        return True, "Worktree cleanly rebased and verified.", {}

    def _prepare_primary_ff_merge(self, ticket: Ticket) -> Tuple[bool, str, Dict[str, Any]]:
        _, status_out, _ = call_facade("run_command", run_command)(["git", "status", "--porcelain"], cwd=self.target_repo)
        if status_out.strip():
            return False, f"Primary repository {self.target_repo} has uncommitted dirty changes. Refusing to merge into dirty checkout.", {}
        _, curr_branch, _ = call_facade("run_command", run_command)(["git", "branch", "--show-current"], cwd=self.target_repo)
        if curr_branch.strip() != self.state.base_branch:
            code, _, err = call_facade("run_command", run_command)(["git", "checkout", self.state.base_branch], cwd=self.target_repo)
            if code != 0:
                return False, f"Primary repository is on '{curr_branch.strip()}', failed to checkout base branch '{self.state.base_branch}': {err}", {}
        code, _, _ = call_facade("run_command", run_command)(["git", "merge-base", "--is-ancestor", self.state.base_branch, ticket.branch_name], cwd=self.target_repo)
        if code != 0:
            rebase_ok, rebase_msg, rebase_details = self._sync_diverged_worktree(ticket)
            if not rebase_ok:
                return False, rebase_msg, rebase_details
        return True, "", {}

    def guard_staging_to_completed(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Executes local fast-forward merge, worktree release, recorder resolution, and radar rescan."""
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found.", {}
        if not (self.target_repo / ".git").exists():
            self._archive_ticket_spec(ticket)
            return True, f"Ticket {ticket.ticket_id} delivered (non-git workspace).", {}
        ok_prep, prep_msg, prep_det = self._prepare_primary_ff_merge(ticket)
        if not ok_prep:
            return False, prep_msg, prep_det
        code, merge_out, merge_err = call_facade("run_command", run_command)(["git", "merge", "--ff-only", ticket.branch_name], cwd=self.target_repo)
        if code != 0:
            return False, f"Failed to fast-forward merge {ticket.branch_name} into {self.state.base_branch}: {merge_err or merge_out}", {}
        if ticket.worktree_path:
            ok, wt_msg = call_facade("return_worktree", return_worktree)(self.target_repo, ticket.worktree_path, force=False)
            if not ok:
                print(f"[WARN] Failed to cleanly return worktree to Treehouse pool: {wt_msg}")
        try:
            call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket.ticket_id).mark_status("RESOLVED")
        except Exception as e:
            print(f"[WARN] Failed to mark flight recorder RESOLVED: {e}")
        self._archive_ticket_spec(ticket)
        self._run_radar_rescan()
        return True, f"Ticket {ticket.ticket_id} successfully merged into {self.state.base_branch} and worktree released to pool.", {"output": merge_out}
