"""BrigadeFSM mixin: advance_dispatch."""

from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional, List, Set

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog


class FsmAdvanceDispatchMixin:
    """Mixin providing advance_dispatch operations for BrigadeFSM."""

    def _record_guard_failure(
        self,
        state: CycleState,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records guard failure in transition history and synchronizes to FlightRecorder."""
        state_str = state.value if isinstance(state, CycleState) else str(state)
        log = TransitionLog(
            from_state=state_str,
            to_state=state_str,
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=False,
            message=message,
            details=details or {},
        )
        self.state.history.append(log)
        self.save()

        if not self.state.active_ticket:
            return
        try:
            recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, self.state.active_ticket.ticket_id)
            recorder.record_guard_failure(state=state_str, message=message, details=details or {})
        except Exception as e:
            print(f"[WARN] Failed to record guard failure in flight recorder: {e}")

    def _advance_from_gate(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        """Handles advance logic from GATE to either QA (preflight checked) or REVIEW."""
        curr = CycleState.GATE
        passed, msg, details = self.guard_gate_to_next()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            return False, curr, f"Edge Gate blocked advancement: {msg}"

        ticket = self.state.active_ticket
        if ticket and getattr(ticket, "track", "core") in ("core", "ui"):
            self._synthesize_refactor_receipt(ticket)

        if self.should_run_qa(self.state.active_ticket):
            drift_ok, drift_msg = self._run_qa_db_drift_preflight()
            if not drift_ok and not force:
                self._record_guard_failure(curr, drift_msg, {"db_drift": True})
                return False, curr, f"QA Preflight blocked advancement: {drift_msg}"

            adv_msg = "Gate passed; Lavish prototype detected -> advancing to QA."
            self._transition(CycleState.QA, adv_msg, details)
            return True, self.state.current_state, adv_msg

        adv_msg = "Gate passed; no QA required -> advancing to REVIEW."
        self._transition(CycleState.REVIEW, adv_msg, details)
        return True, self.state.current_state, adv_msg

    def _advance_from_qa(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        curr = CycleState.QA
        passed, msg, details = self.guard_qa_to_review()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            if details.get("critical_count", 0) > 0:
                self._transition(CycleState.POLISH, f"QA failed with critical defects -> routing to POLISH: {msg}", details)
                return False, CycleState.POLISH, f"Critical QA defects detected. Routed to POLISH: {msg}"
            return False, curr, f"QA guard blocked advancement: {msg}"
        self._transition(CycleState.REVIEW, msg, details)
        return True, self.state.current_state, msg

    def _advance_from_review(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        curr = CycleState.REVIEW
        next_state, msg, details = self.guard_review_to_next()
        if next_state == CycleState.REVIEW:
            if force:
                self._transition(CycleState.STAGING, f"Forced advance from REVIEW: {msg}", details)
                return True, self.state.current_state, msg
            self._record_guard_failure(curr, msg, details)
            return False, curr, msg
        if next_state == CycleState.STAGING:
            ticket = self.state.active_ticket
            if ticket and getattr(ticket, "track", "core") in ("core", "ui"):
                self._refresh_refactor_seal_4(ticket)
        self._transition(next_state, msg, details)
        return True, self.state.current_state, msg

    def _advance_from_polish(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        curr = CycleState.POLISH
        passed, msg, details = self.guard_polish_to_review()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            return False, curr, f"Polish guard blocked advancement: {msg}"
        if force:
            self.state.review_findings = []
            self.state.examiner_receipt = None
        self._transition(CycleState.GATE, msg, details)
        return True, self.state.current_state, msg

    def _advance_from_completed(self) -> Tuple[bool, CycleState, str]:
        self._seal_findings_to_recorder()
        self._transition(CycleState.IDLE, "Cycle completed. Reset to IDLE.")
        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.save()
        return True, self.state.current_state, "Reset to IDLE for next ticket."
