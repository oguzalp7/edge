"""BrigadeFSM mixin: guards_gate."""

from pathlib import Path
import sys
from typing import Any, Dict, List, Tuple

from tools.brigade.models import Ticket
from tools.common import normalize_target_path
from tools.common.paths import is_wsl_path, to_wsl_path


class FsmGuardsGateMixin:
    """Mixin providing Edge Verification Gate transitions for BrigadeFSM."""

    def _build_gate_command(self, ticket: Ticket, eff_repo: Any) -> List[str]:
        gate_script = Path(__file__).resolve().parents[2] / "gate.py"
        base_to_compare = self.state.base_branch.strip() if (self.state.base_branch and self.state.base_branch.strip()) else "HEAD~1"
        no_refactor_flag = ["--no-refactor"] if getattr(ticket, "track", "core") == "feature" else []
        if is_wsl_path(eff_repo):
            return [
                "python3", to_wsl_path(gate_script), to_wsl_path(eff_repo),
                "--base", base_to_compare, "--track", ticket.track, "--skip-verify",
            ] + no_refactor_flag
        return [
            sys.executable, str(gate_script), str(eff_repo),
            "--base", base_to_compare, "--track", ticket.track, "--skip-verify",
        ] + no_refactor_flag

    def guard_gate_to_next(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Runs tools/gate.py (and diff_image.py visual parity on ui track) before QA/REVIEW."""
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found.", {}

        eff_repo = ticket.worktree_path if (ticket and ticket.worktree_path) else self.target_repo
        cmd = self._build_gate_command(ticket, eff_repo)
        code, stdout, stderr = self._run_cmd(cmd)
        if code != 0:
            return False, f"Edge Verification Gate FAILED (exit code {code}):\n{stdout}\n{stderr}", {"output": stdout}

        details: Dict[str, Any] = {"output": stdout}
        if getattr(ticket, "track", "core") == "ui":
            work_dir = normalize_target_path(eff_repo)
            parity_ok, parity_msg, parity_details = self._check_ui_visual_parity(ticket, work_dir)
            if not parity_ok:
                return False, parity_msg, parity_details
            details["visual_parity"] = parity_details

        return True, "Edge Verification Gate PASSED all invariant stages.", details

    def guard_gate_to_staging(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Backward-compatibility alias delegating to guard_gate_to_next."""
        return self.guard_gate_to_next()

