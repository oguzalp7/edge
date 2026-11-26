"""BrigadeFSM mixin: guards_review."""

from typing import Tuple, Dict, Any, Optional, List, Set

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog


class FsmGuardsReviewMixin:
    """Mixin providing guards_review operations for BrigadeFSM."""

    def _seal_findings_to_recorder(self) -> None:
        if not (self.state.review_findings and self.state.active_ticket):
            return
        try:
            recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, self.state.active_ticket.ticket_id)
            recorder.seal_review_findings(self.state.review_findings)
        except Exception as e:
            print(f"[WARN] Failed to seal review findings into flight recorder: {e}")

    def _validate_examiner_receipt(self) -> Tuple[Optional[CycleState], str, Dict[str, Any]]:
        receipt = self.state.examiner_receipt
        if receipt is None:
            return (
                CycleState.REVIEW,
                "Review blocked: Examiner seal missing. Run 'brigade seal-review <repo> --verdict PASS|FAIL --summary \"...\"' before advancing.",
                {"error": "MISSING_EXAMINER_RECEIPT"},
            )
        active_tid = self.state.active_ticket.ticket_id if self.state.active_ticket else None
        if receipt.ticket_id and active_tid and receipt.ticket_id != active_tid:
            return (
                CycleState.REVIEW,
                f"Review blocked: Examiner seal is stale (receipt ticket '{receipt.ticket_id}' != '{active_tid}'). Re-run 'brigade seal-review'.",
                {"error": "STALE_EXAMINER_RECEIPT", "receipt_ticket_id": receipt.ticket_id, "active_ticket_id": active_tid},
            )
        verdict = (receipt.verdict or "").strip().upper()
        if verdict == "FAIL":
            return (
                CycleState.POLISH,
                "Examiner sealed verdict FAIL. Routing to POLISH for remediation.",
                {"verdict": "FAIL"},
            )
        if verdict != "PASS":
            return (
                CycleState.REVIEW,
                f"Review blocked: Invalid ExaminerReceipt verdict '{receipt.verdict}'. Expected PASS or FAIL.",
                {"error": "INVALID_EXAMINER_VERDICT"},
            )
        return None, "", {"examiner_receipt": receipt.to_dict()}

    def guard_review_to_next(self) -> Tuple[CycleState, str, Dict[str, Any]]:
        """
        Evaluates 3-axis review findings, mandatory ExaminerReceipt seal, and hermetic verification:
        - If CRITICAL findings exist -> POLISH
        - If ExaminerReceipt missing/stale -> REVIEW (blocks advancement)
        - If ExaminerReceipt.verdict == FAIL -> POLISH
        - If hermetic verification fails -> POLISH
        - Otherwise (0 CRITICAL + PASS seal + clean verification) -> STAGING
        """
        self._seal_findings_to_recorder()

        critical_findings = [f for f in self.state.review_findings if f.severity == "CRITICAL"]
        if critical_findings:
            msg = f"Review flagged {len(critical_findings)} critical finding(s). Advancing to POLISH for remediation."
            return CycleState.POLISH, msg, {"critical_count": len(critical_findings)}

        receipt_state, receipt_msg, receipt_details = self._validate_examiner_receipt()
        if receipt_state is not None:
            return receipt_state, receipt_msg, receipt_details

        v_passed, v_msg = self._run_hermetic_verification()
        if not v_passed:
            msg = f"Review blocked: Hermetic verification failed before STAGING entry:\n{v_msg}"
            return CycleState.POLISH, msg, {"verification_failed": True, "error": v_msg}

        msg = "Review clean (0 critical findings, Examiner PASS seal) and hermetic verification passed. Advancing to STAGING."
        return CycleState.STAGING, msg, {
            "total_findings": len(self.state.review_findings),
            **receipt_details,
        }

    def guard_polish_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Re-verifies compiler and tests after polish remediation and clears prior findings and receipt."""
        passed, msg = self._run_hermetic_verification()
        if not passed:
            return False, f"Post-polish verification failed:\n{msg}", {}
        self.state.review_findings = []
        self.state.examiner_receipt = None
        return True, "Post-polish verification passed. Routing to GATE for re-verification.", {}

    def guard_polish_to_gate(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Alias for guard_polish_to_review for backward compatibility."""
        return self.guard_polish_to_review()
