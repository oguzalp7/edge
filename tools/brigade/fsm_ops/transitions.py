"""BrigadeFSM mixin: transitions."""

from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional, List, Set

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.worktree import acquire_worktree, is_treehouse_installed, return_worktree


class FsmTransitionsMixin:
    """Mixin providing transitions operations for BrigadeFSM."""

    def _advance_guarded(
        self,
        curr: CycleState,
        guard_fn: Any,
        next_state: CycleState,
        err_prefix: str,
        force: bool = False,
    ) -> Tuple[bool, CycleState, str]:
        passed, msg, details = guard_fn()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            return False, curr, f"{err_prefix}: {msg}"
        self._transition(next_state, msg, details)
        return True, self.state.current_state, msg

    def advance(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        """
        Advances the state machine to the next deterministic state.
        Order: VERIFY -> GATE -> [QA] -> REVIEW -> STAGING -> COMPLETED -> IDLE.
        """
        curr = self.state.current_state
        if curr == CycleState.IDLE:
            if not self.state.active_ticket:
                return False, curr, "Cannot advance from IDLE without an active ticket. Run 'triage' first."
            self._transition(CycleState.TRIAGE, "Initialized triage from active ticket.")
            return True, self.state.current_state, "Moved to TRIAGE."

        simple_routes = {
            CycleState.TRIAGE: (self.guard_triage_to_surgery, CycleState.SURGERY, "Triage validation failed"),
            CycleState.RED_TEST: (self.guard_red_to_surgery, CycleState.SURGERY, "Red test guard blocked advancement"),
            CycleState.SURGERY: (self.guard_surgery_to_verify, CycleState.VERIFY, "Surgery guard blocked advancement"),
            CycleState.VERIFY: (self.guard_verify_to_gate, CycleState.GATE, "Verification guard blocked advancement"),
            CycleState.STAGING: (self.guard_staging_to_completed, CycleState.COMPLETED, "Staging guard blocked completion"),
        }
        if curr in simple_routes:
            guard_fn, next_st, prefix = simple_routes[curr]
            return self._advance_guarded(curr, guard_fn, next_st, prefix, force=force)

        complex_handlers = {
            CycleState.GATE: lambda: self._advance_from_gate(force),
            CycleState.QA: lambda: self._advance_from_qa(force),
            CycleState.REVIEW: lambda: self._advance_from_review(force),
            CycleState.POLISH: lambda: self._advance_from_polish(force),
            CycleState.COMPLETED: self._advance_from_completed,
        }
        handler = complex_handlers.get(curr)
        if handler:
            return handler()

        if curr == CycleState.BLOCKED:
            return False, curr, f"State is BLOCKED ({self.state.blocked_reason}). Run 'abort' to reset."
        if curr == CycleState.PAUSED:
            return False, curr, "State is PAUSED. Run 'brigade resume' to restore execution."
        return False, curr, f"Unknown state {curr}."

    def _transition(self, to_state: CycleState, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        log = TransitionLog(
            from_state=self.state.current_state.value if isinstance(self.state.current_state, CycleState) else str(self.state.current_state),
            to_state=to_state.value if isinstance(to_state, CycleState) else str(to_state),
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=True,
            message=message,
            details=details or {},
        )
        self.state.history.append(log)
        self.state.current_state = to_state
        self.save()

    def _record_abort_and_release_worktree(
        self, ticket: Ticket, reason: str, force: bool, negative_constraint: Optional[str]
    ) -> None:
        try:
            recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket.ticket_id)
            recorder.record_dead_end(
                title=f"Aborted in state {self.state.current_state.value}",
                reason=reason,
                prohibited_rule=negative_constraint or f"Avoid design/path resulting in abortion: {reason}",
                is_abort=True,
            )
        except Exception as e:
            print(f"[WARN] Failed to record dead-end in flight recorder: {e}")
        if ticket.worktree_path:
            try:
                call_facade("return_worktree", return_worktree)(self.target_repo, ticket.worktree_path, force=force)
            except Exception as e:
                print(f"[WARN] Failed to return worktree during abort: {e}")

    def abort(self, reason: str, force: bool = True, negative_constraint: Optional[str] = None) -> None:
        """
        Aborts active cycle, releases isolated worktree back to Treehouse pool,
        records dead-end into FlightRecorder, and resets machine to IDLE.
        """
        ticket = self.state.active_ticket
        if ticket:
            self._record_abort_and_release_worktree(ticket, reason, force, negative_constraint)

        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Aborted: {reason}")

    def escalate(self, reason: str) -> Checkpoint:
        """
        Escalates active ticket to human captain for decision/intervention.
        1. Records escalation in Ticket and FlightRecorder.
        2. Pauses FSM execution safely via durable Checkpoint.
        """
        ticket = self.state.active_ticket
        if ticket:
            ticket.escalation_reason = reason
            ticket.escalation_at = datetime.now(timezone.utc).isoformat()
            ticket.status = "ESCALATED"
            try:
                recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket.ticket_id)
                recorder.record_escalation(reason)
            except Exception as e:
                print(f"[WARN] Failed to log escalation in flight recorder: {e}")

        return self.pause(reason=f"ESCALATION: {reason}")

    def release(self, decision: str) -> Tuple[bool, Optional[Checkpoint], str]:
        """
        Releases an escalated ticket following human captain decision.
        1. Records captain's decision in Ticket and FlightRecorder.
        2. Resumes FSM execution from checkpoint.
        """
        ticket = self.state.active_ticket
        if ticket:
            ticket.captain_decision = decision
            ticket.escalation_reason = None
            ticket.status = "OPEN"
            try:
                recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket.ticket_id)
                recorder.record_decision(decision)
            except Exception as e:
                print(f"[WARN] Failed to log decision in flight recorder: {e}")

        return self.resume()
