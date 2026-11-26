"""BrigadeFSM mixin: ship_finish."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import json

from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.common import normalize_target_path, run_command


class FsmShipFinishMixin:
    """Mixin providing ship_finish operations for BrigadeFSM."""

    def _validate_refactor_ship_preconditions(
        self, ticket: Ticket, diff_repo: Path
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        from tools.brigade.refactor_receipt import RefactorReceiptVerifier

        if self.state.current_state != CycleState.STAGING:
            return False, (
                f"Cannot finish refactor slice via PR: FSM must be in STAGING "
                f"(currently {self.state.current_state.value})."
            ), None

        ex = self.state.examiner_receipt
        if not ex or str(getattr(ex, "verdict", "") or "").upper() != "PASS":
            return False, "Cannot finish refactor slice via PR: ExaminerReceipt PASS seal is required.", None

        receipt_file = self._find_refactor_receipt_file(ticket)
        if not receipt_file:
            return False, (
                f"Cannot finish refactor slice via PR: missing RefactorReceipt under "
                f"{self.target_repo / '.edge' / 'receipts' / 'refactor'}."
            ), None

        v_ok, v_msg, _ = RefactorReceiptVerifier.verify_receipt_file(
            receipt_file,
            repo_path=self.target_repo,
            base_ref=self.state.base_branch,
            work_dir=diff_repo,
            strict=True,
        )
        if not v_ok:
            return False, f"Cannot finish refactor slice via PR: RefactorReceipt verification failed ({v_msg}).", None

        try:
            rec_data = json.loads(receipt_file.read_text(encoding="utf-8"))
        except Exception:
            rec_data = None
        return True, "", rec_data


    def confirm_merge(self, offline: bool = False) -> Tuple[bool, str]:
        """Confirms a queued AWAITING_MERGE PR has merged, completes tracker issue, and resets FSM to IDLE."""
        from tools.brigade.tracker_hooks import complete_ticket_tracker_issue

        ticket = self.state.active_ticket
        if not ticket or self.state.current_state != CycleState.AWAITING_MERGE:
            return False, f"Cannot confirm merge: FSM is not in AWAITING_MERGE (currently {self.state.current_state.value})."

        diff_repo = normalize_target_path(ticket.worktree_path) if ticket.worktree_path else self.target_repo
        ref = getattr(ticket, "pr_url", None) or ticket.branch_name or self.state.active_branch
        if not ref:
            return False, "Cannot confirm merge: no PR URL or branch recorded."

        v_code, v_out, v_err = call_facade("run_command", run_command)(
            ["gh", "pr", "view", ref, "--json", "state,url"],
            cwd=diff_repo,
        )
        if v_code != 0:
            return False, f"Failed to query PR status for '{ref}': {v_err or v_out}"

        pr_state, viewed_url = self._parse_pr_view_state(v_out)
        if pr_state != "MERGED":
            return False, f"PR '{ref}' is not merged yet (state: {pr_state or 'UNKNOWN'}). Remaining in AWAITING_MERGE."

        eff_url = viewed_url or getattr(ticket, "pr_url", "") or ""
        t_ok, t_msg = complete_ticket_tracker_issue(self.target_repo, ticket, eff_url, offline=offline)
        if not t_ok:
            print(f"[WARN] {t_msg}")
        self._reset_after_slice_finish(ticket)
        return True, f"PR {eff_url or ref} confirmed MERGED; linked task completed and FSM reset to IDLE."

    def finish_slice(self, open_pr: bool = False, auto_merge_two_way: bool = True, offline: bool = False) -> Tuple[bool, str]:
        """
        Fast-forward merges the active slice worktree into base_branch (development),
        or opens a Spec-Anchored GitHub PR when open_pr=True (auto-merging Two-Way Doors
        and holding One-Way Doors open for mandatory human review).
        """
        from tools.brigade.tracker_hooks import complete_ticket_tracker_issue, preflight_ticket_tracker

        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active slice or ticket to finish. Brigade is IDLE."

        preflight_ticket_tracker(self.target_repo, ticket, offline=offline)

        if open_pr:
            return self._finish_slice_via_pr(ticket, auto_merge_two_way=auto_merge_two_way, offline=offline)

        ok, msg, details = self.guard_staging_to_completed()
        if not ok:
            return False, f"Finish slice failed: {msg}"

        t_ok, t_msg = complete_ticket_tracker_issue(self.target_repo, ticket, offline=offline)
        if not t_ok:
            print(f"[WARN] {t_msg}")
            msg = f"{msg} (Warning: {t_msg})"

        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Slice {ticket.ticket_id} finished and merged cleanly.")

        return True, msg
