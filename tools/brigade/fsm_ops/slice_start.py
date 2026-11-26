"""BrigadeFSM mixin: slice_start."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import re

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.fsm_ops.spec_expected import _extract_spec_expected_files
from tools.brigade.fsm_ops.spec_files import _is_non_prod_file, _parse_porcelain_paths
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.worktree import acquire_worktree, is_treehouse_installed, return_worktree


class FsmSliceStartMixin:
    """Mixin providing slice_start operations for BrigadeFSM."""

    def _resolve_slice_lavish(self, lavish_path: Optional[str], clean_name: str, eff_domain: str) -> Optional[str]:
        if lavish_path:
            return lavish_path
        for stem in (clean_name, eff_domain):
            if stem and (cand := self.target_repo / ".lavish" / f"{stem}.html").exists():
                return str(cand.relative_to(self.target_repo)).replace("\\", "/")
        return None

    def _lease_slice_worktree(self, ticket: Ticket, auto_lease_worktree: bool, branch_name: str) -> Tuple[bool, str, str]:
        if not (auto_lease_worktree and (self.target_repo / ".git").exists() and call_facade("is_treehouse_installed", is_treehouse_installed)()):
            return True, "", ""
        ok, wt_path, err = call_facade("acquire_worktree", acquire_worktree)(
            repo_path=self.target_repo, branch_name=branch_name, lease_holder=f"brigade-{ticket.ticket_id}",
        )
        if not ok:
            return False, "", f"Failed to acquire isolated Treehouse worktree: {err}"
        ticket.worktree_path = wt_path
        self.state.active_worktree = wt_path
        return True, f" Worktree leased at {wt_path}.", ""

    def _check_slice_ready(self) -> Optional[Tuple[bool, Optional[Ticket], str]]:
        if self.state.active_ticket and self.state.current_state != CycleState.IDLE:
            if self.state.current_state == CycleState.PAUSED:
                self.state.active_ticket = self.state.active_branch = self.state.active_worktree = None
                return None
            return False, self.state.active_ticket, f"Cannot start slice: Active ticket {self.state.active_ticket.ticket_id} is currently in progress (State: {self.state.current_state.value}). Finish or abort it first."
        return None

    def _create_slice_ticket(
        self, ticket_id: str, track: str, eff_domain: str, clean_name: str, name: str,
        target_file: str, branch_name: str, test_seam_command: str, allow_schema_migration: bool,
        eff_exp: List[str], eff_spec: Optional[str], lavish_path: Optional[str],
        require_qa: Optional[bool], eff_issue: Optional[int], eff_parent: Optional[int],
        offline: bool, all_c: List[str],
    ) -> Ticket:
        return Ticket(
            ticket_id=ticket_id, track=track, domain=eff_domain, rule_id=f"SLICE-{clean_name.upper()[:12]}",
            severity="NORMAL", target_file=target_file, line_number=1, fingerprint=f"slice-{clean_name}",
            description=f"Live slice: {name}", suggested_fix=f"Implement slice {name}", branch_name=branch_name,
            test_seam_command=test_seam_command, scaffolding_allowance=50 if track == "feature" else 15,
            enforce_contraction=False, allow_schema_migration=allow_schema_migration, expected_files=eff_exp,
            spec_path=eff_spec, lavish_path=self._resolve_slice_lavish(lavish_path, clean_name, eff_domain),
            require_qa=require_qa, issue_number=eff_issue, parent_issue=eff_parent, tracker_offline=bool(offline),
            before_metrics=self._capture_before_metrics(target_file=target_file, expected_files=eff_exp),
            surgeon_cid=self._resolve_station_cid("surgeon"), negative_constraints=all_c,
        )

    def start_slice(
        self, name: str, track: str = "feature", target_file: str = "", domain: str = "",
        test_seam_command: str = "npm run test:unit", allow_schema_migration: bool = True,
        auto_lease_worktree: bool = True, expected_files: Optional[List[str]] = None,
        spec_path: Optional[str] = None, lavish_path: Optional[str] = None,
        require_qa: Optional[bool] = None, issue_number: Optional[int] = None,
        parent_issue: Optional[int] = None, offline: bool = False,
    ) -> Tuple[bool, Optional[Ticket], str]:
        """Deterministically initiates a live feature or refactor slice."""
        if (blocked := self._check_slice_ready()) is not None:
            return blocked
        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).lower().strip("-")
        eff_domain = domain or (Path(target_file).stem if target_file else clean_name)
        slug = clean_name.upper() if len(clean_name) <= 18 else f"{clean_name[:11].upper()}-{clean_name[-6:].upper()}"
        ticket_id = f"TICK-{track.upper()[:4]}-{slug}"
        branch_name = f"{'feat' if track == 'feature' else 'refactor'}/{clean_name}"
        recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket_id)
        base_c = [
            "Zero-Touch Primary Checkout Invariant: All mutations must be executed strictly inside the leased worktree.",
            "Test Immutability: Coder must not delete or loosen tests authored by Seam Architect.",
        ]
        if track != "feature" and not allow_schema_migration:
            base_c.append("MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations.")
        all_c = base_c + [c for c in recorder.get_negative_constraints() if c not in base_c]
        from tools.brigade.tracker_hooks import mark_issue_in_progress, resolve_slice_issue_spec
        eff_spec, eff_issue, eff_parent = resolve_slice_issue_spec(self.target_repo, issue_number=issue_number, parent_issue=parent_issue, spec_path=spec_path, offline=offline)
        eff_exp = list(expected_files or []) or _extract_spec_expected_files(repo_path=self.target_repo, spec_path=eff_spec, clean_name=clean_name)
        ticket = self._create_slice_ticket(
            ticket_id, track, eff_domain, clean_name, name, target_file, branch_name,
            test_seam_command, allow_schema_migration, eff_exp, eff_spec, lavish_path,
            require_qa, eff_issue, eff_parent, offline, all_c,
        )
        ok_wt, wt_msg, wt_err = self._lease_slice_worktree(ticket, auto_lease_worktree, branch_name)
        if not ok_wt:
            return False, None, wt_err
        recorder.set_metadata(track=track, domain=eff_domain, target_file=ticket.target_file, worktree_path=ticket.worktree_path or "", expected_files=ticket.expected_files)
        mark_issue_in_progress(self.target_repo, eff_issue, offline=offline)
        self.state.active_ticket, self.state.active_branch = ticket, branch_name
        if track == "feature":
            self.state.current_state = CycleState.RED_TEST
            self._transition(CycleState.RED_TEST, "Initialized feature slice in RED_TEST state")
            state_label = "RED_TEST"
        else:
            self.state.current_state = CycleState.SURGERY
            self.save()
            state_label = "SURGERY"
        return True, ticket, f"Slice '{name}' initiated successfully.{wt_msg} Branch: {branch_name} (State: {state_label})."
