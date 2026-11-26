"""BrigadeFSM mixin: handoff."""

from typing import Tuple, Dict, Any, Optional, List, Set

from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog


class FsmHandoffMixin:
    """Mixin providing handoff operations for BrigadeFSM."""

    def get_next_station_handoff(self, target_state: Optional[CycleState] = None) -> Dict[str, Any]:
        """
        Returns the target station role, registered conversation_id, model,
        and recommended send_message instruction for the newly entered state.
        """
        state = target_state or self.state.current_state
        ticket = self.state.active_ticket
        track = getattr(ticket, "track", "core") if ticket else "core"

        target_role_str = self._resolve_handoff_target_role(state, track)
        station = self.state.stations.get(target_role_str) if target_role_str != "orchestrator" else None

        cid = station.conversation_id if station else (target_role_str if target_role_str == "orchestrator" else "")
        model = getattr(station, "model", "flash") if station else "flash"
        station_name = station.name if station else (target_role_str.title() if target_role_str == "orchestrator" else "Unknown")

        state_val = state.value if isinstance(state, CycleState) else str(state)
        instruction = self._resolve_handoff_instruction(state, ticket, state_val)

        return {
            "target_state": state_val,
            "target_role": target_role_str,
            "station_name": station_name,
            "recipient_cid": cid,
            "model": model,
            "instruction": instruction,
        }

    @staticmethod
    def _resolve_handoff_target_role(state: Any, track: str) -> str:
        worker_role = "coder" if track == "feature" else "surgeon"
        role_map = {
            CycleState.RED_TEST: "seam_architect",
            CycleState.SURGERY: worker_role,
            CycleState.VERIFY: worker_role,
            CycleState.REVIEW: "examiner",
            CycleState.POLISH: worker_role,
            CycleState.GATE: "none",
            CycleState.QA: "qa_engineer",
            CycleState.STAGING: "orchestrator",
            CycleState.COMPLETED: "orchestrator",
            CycleState.BLOCKED: "orchestrator",
            CycleState.PAUSED: "orchestrator",
        }
        return role_map.get(state, "none")

    @staticmethod
    def _resolve_handoff_instruction(state: Any, ticket: Any, state_val: str) -> str:
        tid = ticket.ticket_id if ticket else "SLICE"
        instructions = {
            CycleState.RED_TEST: "Establish Feathers seams and failing RED tests in the isolated worktree.",
            CycleState.SURGERY: "Implement clean code in the isolated worktree to turn red tests green. Follow contracts strictly.",
            CycleState.VERIFY: "Run characterization tests and compiler verification in worktree, then advance to GATE.",
            CycleState.GATE: "Run tools/gate.py (and diff_image.py on ui track) and advance to QA or REVIEW.",
            CycleState.QA: "Execute browser E2E verification, synthesize ProofVerifier receipt, and advance to REVIEW (EXAMINER).",
            CycleState.REVIEW: "Conduct 3-axis review (Axis 1: Standards, Axis 2: Spec Boundaries, Axis 3: Multimodal Evidence) and run 'brigade seal-review' before advancing to STAGING.",
            CycleState.POLISH: "Remediate review findings in the isolated worktree and verify compiler clean before re-entering GATE.",
            CycleState.STAGING: f"[READY_FOR_STAGING] Ticket {tid} passed all verification gates. Fast-forward merge ready.",
            CycleState.BLOCKED: f"[ESCALATION] Ticket {tid} blocked at state {state_val}. Captain intervention required.",
        }
        return instructions.get(state, f"State transitioned to {state_val}. Proceed with station duties.")
