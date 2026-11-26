"""BrigadeFSM mixin: pause_resume."""

from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional, List, Set
import json

from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog


class FsmPauseResumeMixin:
    """Mixin providing pause_resume operations for BrigadeFSM."""

    def _write_checkpoint_atomic(self, checkpoint: Checkpoint) -> None:
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.checkpoint_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
        if tmp_file.exists():
            if self.checkpoint_file.exists():
                self.checkpoint_file.unlink()
            tmp_file.rename(self.checkpoint_file)

    def pause(self, reason: str = "MANUAL_PAUSE") -> Checkpoint:
        """Durable safe checkpoint pausing git state and active ticket."""
        work_dir = self._get_work_dir()
        _, status_out, _ = self._run_cmd(["git", "status", "--porcelain"], cwd=work_dir)
        prior_state, ticket = self.state.current_state, self.state.active_ticket
        has_uncommitted_work = bool(status_out.strip())
        if has_uncommitted_work:
            self._run_cmd(["git", "add", "-A"], cwd=work_dir)
            self._run_cmd(["git", "commit", "-m", f"wip(checkpoint): safe pause at {prior_state.value} [{ticket.ticket_id if ticket else 'NO_TICKET'}]"], cwd=work_dir)
        code, head_sha, _ = self._run_cmd(["git", "rev-parse", "HEAD"], cwd=work_dir)
        wip_sha = head_sha.strip() if code == 0 else None
        completed, pending, next_action = self._get_substeps_for_state(prior_state, ticket)
        eff_wt = ticket.worktree_path if (ticket and ticket.worktree_path) else self.state.active_worktree
        checkpoint = Checkpoint(
            paused_at=datetime.now(timezone.utc).isoformat(), reason=reason, base_branch=self.state.base_branch,
            active_branch=self.state.active_branch, worktree_path=eff_wt, active_worktree=eff_wt,
            active_ticket=ticket, stashed_ticket=ticket.to_dict() if ticket else None, fsm_state=prior_state.value,
            completed_substeps=completed, pending_substeps=pending, wip_commit_sha=wip_sha,
            has_uncommitted_work=has_uncommitted_work, next_action=next_action,
        )
        self._write_checkpoint_atomic(checkpoint)
        self._transition(CycleState.PAUSED, f"Paused: {reason} (prior state: {prior_state.value})", {
            "reason": reason, "prior_state": prior_state.value, "has_uncommitted_work": has_uncommitted_work, "wip_commit_sha": wip_sha,
        })
        return checkpoint

    def _archive_checkpoint_file(self) -> None:
        try:
            bak_file = self.checkpoint_file.with_suffix(".json.bak")
            if bak_file.exists():
                bak_file.unlink()
            self.checkpoint_file.rename(bak_file)
        except Exception:
            if self.checkpoint_file.exists():
                self.checkpoint_file.unlink()

    def resume(self) -> Tuple[bool, Optional[Checkpoint], str]:
        """Restores FSM state and active ticket from .edge/checkpoint.json."""
        if not self.checkpoint_file.exists():
            return False, None, "No checkpoint found at .edge/checkpoint.json. Brigade is in state IDLE."
        try:
            checkpoint = Checkpoint.from_dict(json.loads(self.checkpoint_file.read_text(encoding="utf-8")))
        except Exception as e:
            return False, None, f"Failed to read checkpoint: {e}"
        if checkpoint.active_branch and not (checkpoint.active_worktree or checkpoint.worktree_path):
            _, curr_branch, _ = self._run_cmd(["git", "branch", "--show-current"])
            if curr_branch.strip() != checkpoint.active_branch:
                self._run_cmd(["git", "checkout", checkpoint.active_branch])
        try:
            restored_state = CycleState(checkpoint.fsm_state)
        except ValueError:
            restored_state = CycleState.IDLE
        self.state.current_state = restored_state
        self.state.active_ticket = checkpoint.active_ticket
        self.state.active_branch = checkpoint.active_branch
        self.state.active_worktree = checkpoint.active_worktree or checkpoint.worktree_path or (checkpoint.active_ticket.worktree_path if checkpoint.active_ticket else None)
        self.state.base_branch, self.state.blocked_reason = checkpoint.base_branch, None
        self._transition(restored_state, f"Resumed from checkpoint (paused at {checkpoint.paused_at}). State restored to {checkpoint.fsm_state}.", {
            "checkpoint_reason": checkpoint.reason, "wip_commit_sha": checkpoint.wip_commit_sha,
        })
        self.save()
        self._archive_checkpoint_file()
        summary = (
            f"✅ Checkpoint restored successfully!\n"
            f"   State:     [{restored_state.value}]\n"
            f"   Ticket:    {checkpoint.active_ticket.ticket_id if checkpoint.active_ticket else 'None'}\n"
            f"   Branch:    {checkpoint.active_branch or 'None'}\n"
            f"   Next Step: {checkpoint.next_action}"
        )
        return True, checkpoint, summary
