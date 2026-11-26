"""BrigadeFSM mixin: ship_pr."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.fsm_ops.constants import call_facade
from tools.brigade.models import CycleState, Ticket
from tools.common import normalize_target_path, run_command


class FsmShipPrMixin:
    """Mixin providing PR-based slice completion helpers for BrigadeFSM."""

    def _collect_door_info(self, ticket: Ticket, ship_res: Any, rec_data: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        is_one_way = self._is_ticket_one_way_door(ticket, ship_res.door_type)
        reasons: List[str] = list(ship_res.blast_radius.get("one_way_reasons") or [])
        if not rec_data:
            return is_one_way, reasons
        s1 = rec_data.get("seal_1_intent") or {}
        if str(s1.get("door_type") or "").startswith("One-way"):
            is_one_way = True
        reasons.extend(r for r in (s1.get("one_way_reasons") or []) if r not in reasons)
        return is_one_way, reasons

    def _handle_pr_automerge(
        self, ticket: Ticket, diff_repo: Path, branch: str, pr_title: str, pr_url: Optional[str],
        is_refactor_track: bool, offline: bool,
    ) -> Tuple[bool, str]:
        from tools.brigade.tracker_hooks import warn_complete_ticket_tracker_issue

        m_code, m_out, m_err = call_facade("run_command", run_command)(["gh", "pr", "merge", branch, "--auto", "--merge"], cwd=diff_repo)
        if m_code != 0:
            return False, f"Failed to merge GitHub PR for {branch}: {m_err or m_out}"
        v_code, v_out, _ = call_facade("run_command", run_command)(["gh", "pr", "view", pr_url or branch, "--json", "state,url"], cwd=diff_repo)
        pr_state, viewed_url = self._parse_pr_view_state(v_out) if v_code == 0 else ("", "")
        eff_url = viewed_url or pr_url
        if (is_refactor_track and pr_state != "MERGED") or (not is_refactor_track and pr_state == "OPEN"):
            ticket.pr_url = eff_url
            self._transition(CycleState.AWAITING_MERGE, f"Auto-merge queued for PR {eff_url or branch}; awaiting merge confirmation.")
            return True, f"Two-way door PR ({eff_url or pr_title}) created with auto-merge queued; state transitioned to AWAITING_MERGE."
        warn_complete_ticket_tracker_issue(self.target_repo, ticket, eff_url, offline=offline)
        self._reset_after_slice_finish(ticket)
        return True, f"Two-way door PR ({eff_url or pr_title}) {'merged' if is_refactor_track else 'created and auto-merged'} into {self.state.base_branch}."

    def _finish_slice_via_pr(self, ticket: Ticket, auto_merge_two_way: bool = True, offline: bool = False) -> Tuple[bool, str]:
        from tools.brigade.ship_prep import prepare_ship_payload

        is_refactor_track = getattr(ticket, "track", "core") in ("core", "ui")
        diff_repo = normalize_target_path(ticket.worktree_path) if ticket.worktree_path else self.target_repo
        rec_data: Optional[Dict[str, Any]] = None
        if is_refactor_track:
            pre_ok, pre_err, rec_data = self._validate_refactor_ship_preconditions(ticket, diff_repo)
            if not pre_ok:
                return False, pre_err
        ship_ok, ship_res, ship_err = prepare_ship_payload(diff_repo, base_branch=self.state.base_branch)
        if not ship_ok:
            return False, f"Cannot finish slice via PR: prepare_ship_payload failed: {ship_err}"
        is_one_way, one_way_reasons = self._collect_door_info(ticket, ship_res, rec_data)
        branch = ticket.branch_name or self.state.active_branch or "HEAD"
        pr_title = f"{'[ONE-WAY DOOR]' if is_one_way else '[TWO-WAY DOOR]'} {branch}: {ticket.description}"
        p_code, p_out, p_err = call_facade("run_command", run_command)(["git", "push", "-u", "origin", branch], cwd=diff_repo)
        if p_code != 0:
            return False, f"Failed to push branch '{branch}': {p_err or p_out}"
        c_code, c_out, c_err = call_facade("run_command", run_command)(
            ["gh", "pr", "create", "--base", self.state.base_branch, "--head", branch, "--title", pr_title, "--body", ship_res.pr_body or pr_title],
            cwd=diff_repo,
        )
        if c_code != 0:
            return False, f"Failed to create GitHub PR for {branch}: {c_err or c_out}"
        ticket.pr_url = self._extract_pr_url(c_out)
        self.save()
        if is_one_way:
            reasons_msg = f" Reasons: {'; '.join(one_way_reasons)}" if one_way_reasons else ""
            return True, f"One-way door PR opened ({ticket.pr_url or pr_title}) and held open for mandatory human review before merging.{reasons_msg}"
        if auto_merge_two_way:
            return self._handle_pr_automerge(ticket, diff_repo, branch, pr_title, ticket.pr_url, is_refactor_track, offline)
        if is_refactor_track:
            self._transition(CycleState.AWAITING_MERGE, f"Two-way door PR {ticket.pr_url or branch} opened without auto-merge; awaiting merge confirmation.")
            return True, f"Two-way door PR ({ticket.pr_url or pr_title}) opened; state transitioned to AWAITING_MERGE."
        self._reset_after_slice_finish(ticket)
        return True, f"Two-way door PR ({pr_title}) created and auto-merged into {self.state.base_branch}."
