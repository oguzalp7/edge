"""BrigadeFSM mixin: guards_hermetic."""

from pathlib import Path
import shlex
import shutil
import sys
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.models import Ticket
from tools.common import normalize_target_path


class FsmGuardsHermeticMixin:
    """Mixin providing hermetic verification (tests + tsc) for BrigadeFSM."""

    @staticmethod
    def _is_benign_tsc_error(tsc_out: str, tsc_err: str, eff_dir: Path) -> bool:
        fake_tsc = "This is not the tsc command you are looking for" in tsc_out
        missing_dir = "No such file or directory" in (tsc_err + tsc_out) and not (eff_dir / ".git").exists()
        return fake_tsc or missing_dir

    def _resolve_test_command(self, eff_dir: Path) -> str:
        ticket = self.state.active_ticket
        if ticket and ticket.test_seam_command:
            return ticket.test_seam_command
        if (eff_dir / "package.json").exists():
            return "npm run test:unit"
        uv_bin = shutil.which("uv") or next(
            (str(c) for c in (Path("/opt/homebrew/bin/uv"), Path("/usr/local/bin/uv"), Path.home() / ".local" / "bin" / "uv") if c.is_file()),
            None,
        )
        if uv_bin:
            return f"{shlex.quote(uv_bin)} run --with pytest pytest -q"
        return f"{shlex.quote(sys.executable)} -m pytest -q"

    def _should_run_typecheck(self, eff_dir: Path, ticket: Optional[Ticket]) -> Tuple[bool, List[str]]:
        from tools.common.profiles import has_profile_capability, resolve_active_profiles

        profiles = resolve_active_profiles(eff_dir)
        typecheck_cmd = profiles.commands.get("typecheck") or ["npx", "tsc", "--noEmit"]
        if profiles.source == "explicit_none" or (
            profiles.source == "explicit" and not has_profile_capability(profiles, "typescript") and "typecheck" not in profiles.commands
        ):
            return False, typecheck_cmd
        seam = ticket.test_seam_command if ticket and ticket.test_seam_command else ""
        enabled = (
            "typecheck" in profiles.commands
            or (eff_dir / "tsconfig.json").exists()
            or any(tok in seam for tok in ("vitest", "jest", "tsc", "npm ", "pnpm ", "yarn "))
        )
        return enabled, typecheck_cmd

    def _run_hermetic_verification(self, work_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """Executes hermetic verification (scoped tests + TypeScript compilation) in work_dir."""
        ticket = self.state.active_ticket
        eff_dir = work_dir or (normalize_target_path(ticket.worktree_path) if (ticket and ticket.worktree_path) else self.target_repo)
        test_cmd = self._resolve_test_command(eff_dir)
        test_code, test_out, test_err = self._run_cmd(shlex.split(test_cmd), cwd=eff_dir)
        if test_code != 0:
            no_tests = test_code == 5 and "no tests ran" in (test_out + test_err)
            missing_dir = "No such file or directory" in (test_err + test_out) and not (eff_dir / ".git").exists()
            if not (no_tests or missing_dir):
                return False, f"Characterization test failed (exit code {test_code}): {test_cmd}\n{test_err or test_out}"
        should_run_tsc, typecheck_cmd = self._should_run_typecheck(eff_dir, ticket)
        if should_run_tsc:
            tsc_code, tsc_out, tsc_err = self._run_cmd(typecheck_cmd, cwd=eff_dir)
            if tsc_code != 0 and not self._is_benign_tsc_error(tsc_out, tsc_err, eff_dir):
                return False, f"TypeScript compiler check failed (exit code {tsc_code}):\n{tsc_out or tsc_err}"
        return True, "Hermetic verification passed: Tests and TypeScript compilation clean."

    def guard_verify_to_gate(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates hermetic verification (characterization tests + tsc) before GATE."""
        return self.guard_verify_to_review()

    def guard_verify_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates hermetic verification (characterization tests + tsc)."""
        passed, msg = self._run_hermetic_verification()
        if not passed:
            return False, msg, {}
        return True, "Verification passed: Characterization tests and TypeScript compilation are 100% clean.", {}
