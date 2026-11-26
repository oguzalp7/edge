"""BrigadeFSM mixin: heat."""

from pathlib import Path
from typing import List, Optional, Tuple

from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, YELLOW_HEAT_THRESHOLD
from tools.brigade.models import ContextHeatZone, CycleState, Ticket
from tools.brigade.proof_verifier import SubstepList
from tools.common import normalize_target_path


def _count_file_chars(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(len(line) for line in f)
    except Exception:
        return path.stat().st_size


class FsmHeatMixin:
    """Mixin providing substeps and token heat estimation for BrigadeFSM."""

    def _get_substeps_for_state(self, state: CycleState, ticket: Optional[Ticket] = None) -> Tuple[List[str], List[str], str]:
        """Infers completed and pending substeps plus next action prompt from state."""
        eff_ticket = ticket if ticket is not None else self.state.active_ticket
        target = (
            eff_ticket.target_file
            or (", ".join(eff_ticket.expected_files) if getattr(eff_ticket, "expected_files", None) else "(dynamic-slice)")
            if eff_ticket
            else "target file"
        )
        mapping = {
            CycleState.IDLE: (SubstepList([]), SubstepList(["triage_next_ticket"]), "Run 'brigade triage' to pick next ticket from radar."),
            CycleState.TRIAGE: (SubstepList(["ticket_triaged"]), SubstepList(["git_branch_created", "baseline_compiler_verified", "surgery"]), "Run 'brigade advance' to transition to SURGERY and dispatch Surgeon."),
            CycleState.RED_TEST: (SubstepList(["slice_started"]), SubstepList(["write_red_tests", "verify_red_baseline"]), f"Author failing unit/contract tests for {target} to establish red baseline before advancing to SURGERY."),
            CycleState.SURGERY: (SubstepList(["ticket_triaged", "git_branch_created"]), SubstepList(["code_modifications", "hermetic_verification", "gate_verification"]), f"Execute bounded surgery on {target}, then verify with tests and tsc before advancing to VERIFY."),
            CycleState.VERIFY: (SubstepList(["ticket_triaged", "surgery_completed"]), SubstepList(["test_seam_verification", "tsc_compilation", "edge_gate"]), "Run hermetic test seams and advance to GATE."),
            CycleState.GATE: (SubstepList(["hermetic_tests_passed"]), SubstepList(["edge_gate_execution", "ui_visual_parity", "qa_or_review"]), "Run 'python tools/gate.py' (and UI diff_image.py if ui track) and advance to QA or REVIEW."),
            CycleState.QA: (SubstepList(["gate_passed"]), SubstepList(["browser_e2e_verification", "proof_verifier_receipt", "zero_console_errors", "examiner_review"]), "Execute QA browser inspection, synthesize ProofVerifier receipt, and advance to REVIEW."),
            CycleState.REVIEW: (SubstepList(["gate_passed", "qa_verified_if_needed"]), SubstepList(["standards_review", "spec_review", "evidence_review", "seal_review"]), "Execute 3-axis review (Standards, Spec, Evidence) and run 'brigade seal-review' before advancing to STAGING."),
            CycleState.POLISH: (SubstepList(["review_findings_recorded"]), SubstepList(["remediate_critical_findings", "re_verify", "edge_gate"]), "Remediate critical review findings and advance to GATE."),
            CycleState.STAGING: (SubstepList(["gate_passed", "review_sealed_pass"]), SubstepList(["squash_merge_to_base", "radar_ledger_update"]), "Squash-merge branch into base and update radar ledger."),
        }
        return mapping.get(state, (SubstepList([]), SubstepList([]), f"Resume execution in state {state.value}."))

    @staticmethod
    def calculate_token_estimate(transcript_path: Path) -> int:
        norm_path = normalize_target_path(transcript_path)
        if not norm_path.exists():
            return 0
        if norm_path.is_file():
            return _count_file_chars(norm_path) // 4
        if norm_path.is_dir():
            return sum(_count_file_chars(p) for p in norm_path.glob("*.jsonl")) // 4
        return 0

    @staticmethod
    def get_heat_zone(token_count: int) -> Tuple[ContextHeatZone, str]:
        if token_count < GREEN_HEAT_THRESHOLD:
            return ContextHeatZone.GREEN, f"GREEN ZONE ({token_count:,} tokens): Context is optimal. Proceed with normal operations."
        if token_count <= YELLOW_HEAT_THRESHOLD:
            return ContextHeatZone.YELLOW, f"YELLOW ZONE ({token_count:,} tokens): Cognitive drain limit approaching. DRAIN ACTIVE TICKET ONLY. Do NOT start new tickets. Trigger 'brigade pause' upon ticket completion."
        return ContextHeatZone.RED, f"RED ZONE ({token_count:,} tokens): Cognitive saturation limit reached! EMERGENCY CHECKPOINT REQUIRED. Run 'brigade pause' immediately to preserve in-flight work."

    def check_heat(self, transcript_path: Path) -> Tuple[ContextHeatZone, int, str]:
        tokens = self.calculate_token_estimate(transcript_path)
        zone, recommendation = self.get_heat_zone(tokens)
        return zone, tokens, recommendation
