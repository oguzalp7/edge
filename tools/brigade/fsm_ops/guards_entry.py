"""BrigadeFSM mixin: guards_entry."""

from typing import Tuple, Dict, Any, Optional, List, Set

from tools.brigade.flight_recorder import FlightRecorder
from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.fsm_ops.spec_expected import _extract_spec_expected_files
from tools.brigade.fsm_ops.spec_files import _is_non_prod_file, _parse_porcelain_paths
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.worktree import acquire_worktree, is_treehouse_installed, return_worktree


class FsmGuardsEntryMixin:
    """Mixin providing guards_entry operations for BrigadeFSM."""

    def guard_triage_to_surgery(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates that a valid ticket exists, allocates an isolated Treehouse worktree, and prepares for surgery."""
        if not self.state.active_ticket:
            return False, "No active ticket assigned for surgery.", {}
        
        ticket = self.state.active_ticket
        self.state.active_branch = ticket.branch_name

        # Check if target repository is a real Git repository
        is_git_repo = (self.target_repo / ".git").exists()

        # Allocate Treehouse isolated worktree if not yet assigned and in a git repo
        if is_git_repo and not ticket.worktree_path and call_facade("is_treehouse_installed", is_treehouse_installed)():
            ok, wt_path, err = call_facade("acquire_worktree", acquire_worktree)(
                repo_path=self.target_repo,
                branch_name=ticket.branch_name,
                lease_holder=f"brigade-{ticket.ticket_id}",
            )
            if not ok:
                return False, f"Failed to acquire isolated Treehouse worktree: {err}", {"error": err}
            
            ticket.worktree_path = wt_path
            self.state.active_worktree = wt_path
            self.save()

        # Initialize / update flight recorder metadata
        try:
            recorder = call_facade("FlightRecorder", FlightRecorder)(self.target_repo, ticket.ticket_id)
            recorder.set_metadata(
                track=ticket.track,
                domain=ticket.domain,
                target_file=ticket.target_file,
                worktree_path=ticket.worktree_path,
            )
        except Exception as e:
            print(f"[WARN] Failed to initialize flight recorder: {e}")

        return True, f"Ticket {ticket.ticket_id} validated. Worktree leased at {ticket.worktree_path} on branch {ticket.branch_name}.", {"worktree_path": ticket.worktree_path}

    def guard_red_to_surgery(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates that Seam Architect has established a genuine, failing red test baseline.
        Rejects pass-before-code (exit 0) and harness/syntax failures (fake red).
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found in RED_TEST state.", {}

        test_cmd = ticket.test_seam_command if ticket.test_seam_command else "npm run test:unit"
        test_code, test_out, test_err = self._run_cmd(test_cmd.split())

        # 1. Pass-Before-Code Rejection
        if test_code == 0:
            return (
                False,
                "RED_BASELINE VIOLATION: Test suite exited 0 before implementation! SEAM_ARCHITECT must write a genuinely failing test.",
                {"exit_code": 0},
            )

        # 2. Anti-Fake-Red Guard (broken syntax or harness failure)
        combined = f"{test_out}\n{test_err}".lower()
        fake_red_markers = (
            "syntaxerror",
            "indentationerror",
            "taberror",
            "transform failed",
            "parse error",
            "command not found",
            "no test files found",
            "no tests found",
            "collected 0 items",
        )
        if test_code in (126, 127) or any(marker in combined for marker in fake_red_markers):
            return (
                False,
                f"FAKE RED DETECTED (exit {test_code}): Test runner failed due to syntax/harness error rather than a valid assertion failure.\n{test_err or test_out}",
                {"exit_code": test_code},
            )

        # 3. Valid Red Baseline
        return (
            True,
            f"RED_BASELINE verified (exit code {test_code}): Failing TDD anchor confirmed. Advancing to SURGERY.",
            {"exit_code": test_code},
        )

    def _collect_all_changed_files(self, base_ref: str) -> List[str]:
        stdout = ""
        diff_targets = [["HEAD"], [f"{base_ref}...HEAD"], [base_ref], ["HEAD~1"]]
        for target in diff_targets:
            code, out, _ = self._run_cmd(["git", "diff", "--name-only"] + target)
            if code == 0 and out.strip():
                stdout = out
                break

        modified_files = [
            f[2:] if f.startswith("./") else f
            for f in (line.strip().replace("\\", "/") for line in stdout.splitlines())
            if f
        ]

        porcelain_files: List[str] = []
        p_code, p_out, _ = self._run_cmd(["git", "status", "--porcelain"])
        if p_code == 0 and p_out:
            porcelain_files = _parse_porcelain_paths(p_out)

        return list(dict.fromkeys(modified_files + porcelain_files))

    def _get_numstat_output(self, base_ref: str) -> str:
        diff_targets = [["HEAD"], [f"{base_ref}...HEAD"], [base_ref], ["HEAD~1"]]
        for target in diff_targets:
            code, out, _ = self._run_cmd(["git", "diff", "--numstat"] + target)
            if code == 0 and out.strip():
                return out
        return ""

    def _check_migration_gate_violation(
        self, ticket: Ticket, all_changed_files: List[str]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        if getattr(ticket, "allow_schema_migration", False) or getattr(ticket, "track", "core") == "feature":
            return False, "", {}
        import fnmatch
        from tools.common.profiles import is_stack_gate_enabled, resolve_active_profiles

        profiles = resolve_active_profiles(self.target_repo)
        if profiles.source in ("explicit", "explicit_none") and not is_stack_gate_enabled(profiles, "migration_gate"):
            globs = [*(profiles.paths.get("schema_globs") or ()), *(profiles.paths.get("migration_globs") or ())]
            schema_violations = [f for f in all_changed_files if any(fnmatch.fnmatch(f, g) for g in globs)]
        else:
            schema_violations = [f for f in all_changed_files if f.startswith("src/db/schema") or f.startswith("drizzle/")]
        if schema_violations:
            return True, f"MigrationGate Invariant VIOLATION: Refactor touched database schemas: {schema_violations}", {"schema_violations": schema_violations}
        return False, "", {}
