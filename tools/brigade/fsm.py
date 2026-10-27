"""
Finite State Machine Engine for Edge Brigade.
Deterministic state transitions driven strictly by OS process exit codes
and hard data invariants, never by LLM self-evaluation.
"""

import os
import sys
import json
import re
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List
from datetime import datetime, timezone

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from .models import (
        BrigadeState,
        CycleState,
        Ticket,
        StationRole,
        TransitionLog,
        ReviewFinding,
        Checkpoint,
        ContextHeatZone,
    )
    from .stations import StationRegistry
    from .worktree import acquire_worktree, return_worktree, is_treehouse_installed, get_pool_status
    from .flight_recorder import FlightRecorder
except ImportError:
    from tools.brigade.models import (
        BrigadeState,
        CycleState,
        Ticket,
        StationRole,
        TransitionLog,
        ReviewFinding,
        Checkpoint,
        ContextHeatZone,
    )
    from tools.brigade.stations import StationRegistry
    from tools.brigade.worktree import acquire_worktree, return_worktree, is_treehouse_installed, get_pool_status
    from tools.brigade.flight_recorder import FlightRecorder

from tools.common import normalize_target_path, run_command

# SSOT Heat Zone Thresholds (SPEC-002)
GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000


class BrigadeFSM:
    def __init__(self, target_repo_path: Optional[Path] = None, target_repo: Optional[Path] = None):
        eff_path = target_repo_path or target_repo or Path.cwd()
        self.target_repo = normalize_target_path(eff_path)
        self.state_file = self.target_repo / ".edge" / "brigade.json"
        self.checkpoint_file = self.target_repo / ".edge" / "checkpoint.json"
        self.state = self._load_or_init()
        self.registry = StationRegistry(self.state)

    # =========================================================================
    # Persistence & Loading
    # =========================================================================

    def _load_or_init(self) -> BrigadeState:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return BrigadeState.from_dict(data)
            except Exception as e:
                print(f"[WARN] Failed to load existing brigade state: {e}. Reinitializing.")
        
        # New default state
        state = BrigadeState(
            repo_path=str(self.target_repo),
            base_branch="development",
            current_state=CycleState.IDLE,
        )
        return state

    def save(self) -> None:
        """Atomically saves the state to .edge/brigade.json."""
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        tmp_file = self.state_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)
        
        if tmp_file.exists():
            if self.state_file.exists():
                self.state_file.unlink()
            tmp_file.rename(self.state_file)

    # =========================================================================
    # Command Execution (WSL & Windows Aware)
    # =========================================================================

    def _run_cmd(self, cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
        """Runs a subprocess command with transparent WSL / Windows path handling."""
        if cwd:
            work_dir = cwd
        elif self.state.active_ticket and self.state.active_ticket.worktree_path:
            work_dir = normalize_target_path(self.state.active_ticket.worktree_path)
        else:
            work_dir = self.target_repo
        return run_command(cmd, cwd=work_dir)

    # =========================================================================
    # State Transition Guards (Deterministic QA)
    # =========================================================================

    def guard_triage_to_surgery(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates that a valid ticket exists, allocates an isolated Treehouse worktree, and prepares for surgery."""
        if not self.state.active_ticket:
            return False, "No active ticket assigned for surgery.", {}
        
        ticket = self.state.active_ticket
        self.state.active_branch = ticket.branch_name

        # Check if target repository is a real Git repository
        is_git_repo = (self.target_repo / ".git").exists()

        # Allocate Treehouse isolated worktree if not yet assigned and in a git repo
        if is_git_repo and not ticket.worktree_path and is_treehouse_installed():
            ok, wt_path, err = acquire_worktree(
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
            recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
            recorder.set_metadata(
                track=ticket.track,
                domain=ticket.domain,
                target_file=ticket.target_file,
                worktree_path=ticket.worktree_path,
            )
        except Exception as e:
            print(f"[WARN] Failed to initialize flight recorder: {e}")

        return True, f"Ticket {ticket.ticket_id} validated. Worktree leased at {ticket.worktree_path} on branch {ticket.branch_name}.", {"worktree_path": ticket.worktree_path}

    def guard_surgery_to_verify(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates surgery invariants via git diff:
        1. MigrationGate Invariant: Zero schema or drizzle files touched.
        2. Target File Contraction: insertions - deletions < 0 in target_file.
        3. Scaffolding allowance respected.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found in SURGERY state.", {}

        base_ref = self.state.base_branch
        # Check files modified: check working tree against HEAD first, then fallback to base_ref
        code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", "HEAD"])
        if code != 0 or not stdout.strip():
            code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", f"{base_ref}...HEAD"])
        if code != 0 or not stdout.strip():
            code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", base_ref])
        if code != 0 or not stdout.strip():
            code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", "HEAD~1"])

        modified_files = [f.strip().replace("\\", "/") for f in stdout.splitlines() if f.strip()]
        
        # 1. MigrationGate Invariant check (Enforced unless feature track or explicitly permitted)
        if not getattr(ticket, "allow_schema_migration", False) and getattr(ticket, "track", "core") != "feature":
            schema_violations = [f for f in modified_files if f.startswith("src/db/schema") or f.startswith("drizzle/")]
            if schema_violations:
                details = {"schema_violations": schema_violations}
                return False, f"MigrationGate Invariant VIOLATION: Refactor touched database schemas: {schema_violations}", details

        # 2. Check target file delta
        numstat_code, numstat_out, _ = self._run_cmd(["git", "diff", "--numstat", "HEAD"])
        if numstat_code != 0 or not numstat_out.strip():
            numstat_code, numstat_out, _ = self._run_cmd(["git", "diff", "--numstat", f"{base_ref}...HEAD"])
        if numstat_code != 0 or not numstat_out.strip():
            numstat_code, numstat_out, _ = self._run_cmd(["git", "diff", "--numstat", base_ref])
        if numstat_code != 0 or not numstat_out.strip():
            numstat_code, numstat_out, _ = self._run_cmd(["git", "diff", "--numstat", "HEAD~1"])

        target_file_norm = ticket.target_file.replace("\\", "/")
        target_found = False
        target_delta = 0
        total_net = 0

        for line in numstat_out.splitlines():
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                ins_str, del_str, file_name = parts[0], parts[1], parts[2].replace("\\", "/")
                if ins_str.isdigit() and del_str.isdigit():
                    ins, dels = int(ins_str), int(del_str)

                    if file_name == target_file_norm:
                        target_found = True
                        target_delta = ins - dels

                    # Filter out tests, docs, json ledgers, and .edge from net production SLOC
                    if (
                        ".test." in file_name
                        or ".spec." in file_name
                        or file_name.startswith("tests/")
                        or file_name.endswith(".md")
                        or file_name.endswith(".json")
                        or file_name.startswith(".edge/")
                    ):
                        continue

                    total_net += (ins - dels)

        if not target_found:
            return False, f"Target file '{ticket.target_file}' was not modified in the diff.", {"modified_files": modified_files}

        # 3. Optional contraction check (Decoupled by default: code cleanliness & tests govern quality)
        if getattr(ticket, "enforce_contraction", False):
            if target_delta >= 0:
                return False, f"Target Contraction VIOLATION: '{ticket.target_file}' did not contract (delta: +{target_delta} lines).", {"target_delta": target_delta}

            allowance = ticket.scaffolding_allowance
            if total_net > allowance:
                return False, f"Net SLOC Budget VIOLATION: Net line change +{total_net} exceeds scaffolding allowance of +{allowance}.", {"net_sloc": total_net, "allowance": allowance}

        return True, f"Surgery invariants passed: Target file delta {target_delta:+d} lines (Net SLOC: {total_net:+d}).", {
            "target_delta": target_delta,
            "total_net": total_net,
            "modified_files": modified_files,
        }

    def guard_verify_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates hermetic verification:
        1. Characterization test command exits 0.
        2. TypeScript compiler tsc --noEmit exits 0.
        """
        ticket = self.state.active_ticket
        test_cmd = ticket.test_seam_command if ticket and ticket.test_seam_command else "npm run test:unit"
        
        # 1. Run scoped test command
        test_parts = test_cmd.split()
        test_code, test_out, test_err = self._run_cmd(test_parts)
        if test_code != 0:
            return False, f"Characterization test failed (exit code {test_code}): {test_cmd}\n{test_err or test_out}", {"output": test_out, "stderr": test_err}

        # 2. Run TypeScript compiler
        tsc_code, tsc_out, tsc_err = self._run_cmd(["npx", "tsc", "--noEmit"])
        if tsc_code != 0:
            return False, f"TypeScript compiler check failed (exit code {tsc_code}):\n{tsc_out or tsc_err}", {"output": tsc_out, "stderr": tsc_err}

        return True, "Verification passed: Characterization tests and TypeScript compilation are 100% clean.", {}

    def guard_review_to_next(self) -> Tuple[CycleState, str, Dict[str, Any]]:
        """
        Evaluates review findings:
        - If CRITICAL findings exist -> POLISH
        - If only WARNING/ADVISORY or clean -> GATE
        """
        critical_findings = [f for f in self.state.review_findings if f.severity == "CRITICAL"]
        if critical_findings:
            msg = f"Review flagged {len(critical_findings)} critical finding(s). Advancing to POLISH for remediation."
            return CycleState.POLISH, msg, {"critical_count": len(critical_findings)}
        else:
            msg = "Review clean (0 critical findings). Advancing to GATE."
            return CycleState.GATE, msg, {"total_findings": len(self.state.review_findings)}

    def guard_polish_to_gate(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Re-verifies compiler and tests after polish remediation."""
        ticket = self.state.active_ticket
        test_cmd = ticket.test_seam_command if ticket and ticket.test_seam_command else "npm run test:unit"
        
        test_code, test_out, test_err = self._run_cmd(test_cmd.split())
        if test_code != 0:
            return False, f"Post-polish test verification failed:\n{test_err or test_out}", {}

        tsc_code, tsc_out, tsc_err = self._run_cmd(["npx", "tsc", "--noEmit"])
        if tsc_code != 0:
            return False, f"Post-polish TypeScript verification failed:\n{tsc_out or tsc_err}", {}

        return True, "Post-polish verification passed. Advancing to GATE.", {}

    def guard_gate_to_staging(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Runs tools/gate.py to execute the full deterministic verification suite."""
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found.", {}

        # Resolve path to tools/gate.py
        gate_script = Path(__file__).resolve().parent.parent / "gate.py"
        eff_repo = ticket.worktree_path if (ticket and ticket.worktree_path) else self.target_repo
        target_path_str = str(eff_repo)
        target_file_flag = ["--target-file", ticket.target_file] if getattr(ticket, "enforce_contraction", False) else []
        if target_path_str.startswith(r"\\wsl.localhost") or target_path_str.startswith("/home/"):
            # Execute inside WSL
            wsl_target = target_path_str.replace(r"\\wsl.localhost\Ubuntu-24.04", "").replace("\\", "/")
            wsl_gate = str(gate_script).replace(r"C:\Users\oguz_\.gemini\config\plugins\edge", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge").replace("\\", "/")
            base_to_compare = "HEAD~1" if not getattr(ticket, "enforce_contraction", False) else self.state.base_branch
            no_refactor_flag = ["--no-refactor"] if (not getattr(ticket, "enforce_contraction", False) or getattr(ticket, "track", "core") == "feature") else []
            cmd = [
                "python3",
                wsl_gate,
                wsl_target,
                "--base", base_to_compare,
                "--track", ticket.track,
                "--allow-scaffolding", str(ticket.scaffolding_allowance),
                "--skip-verify",
            ] + target_file_flag + no_refactor_flag
        else:
            base_to_compare = "HEAD~1" if not getattr(ticket, "enforce_contraction", False) else self.state.base_branch
            no_refactor_flag = ["--no-refactor"] if (not getattr(ticket, "enforce_contraction", False) or getattr(ticket, "track", "core") == "feature") else []
            cmd = [
                sys.executable,
                str(gate_script),
                str(eff_repo),
                "--base", base_to_compare,
                "--track", ticket.track,
                "--allow-scaffolding", str(ticket.scaffolding_allowance),
                "--skip-verify",
            ] + target_file_flag + no_refactor_flag

        code, stdout, stderr = self._run_cmd(cmd)
        if code != 0:
            return False, f"Edge Verification Gate FAILED (exit code {code}):\n{stdout}\n{stderr}", {"output": stdout}

        return True, "Edge Verification Gate PASSED all invariant stages.", {"output": stdout}

    def guard_staging_to_completed(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Executes local codebase fast-forward synchronization and cleanup:
        1. Checks primary checkout clean status and branch.
        2. Validates fast-forward mergeability (--is-ancestor).
        3. Executes git merge --ff-only into base_branch in primary repo.
        4. Returns worktree to Treehouse pool.
        5. Marks FlightRecorder status as RESOLVED.
        6. Triggers radar ledger rescan.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found.", {}

        # If not a git repository (e.g. mock test environment), skip git merge operations
        if not (self.target_repo / ".git").exists():
            return True, f"Ticket {ticket.ticket_id} delivered (non-git workspace).", {}

        # 1. Primary checkout clean status check
        code, status_out, _ = run_command(["git", "status", "--porcelain"], cwd=self.target_repo)
        if status_out.strip():
            return False, f"Primary repository {self.target_repo} has uncommitted dirty changes. Refusing to merge into dirty checkout.", {}

        # Check primary checkout branch
        code, curr_branch, _ = run_command(["git", "branch", "--show-current"], cwd=self.target_repo)
        curr_b = curr_branch.strip()
        if curr_b != self.state.base_branch:
            # Try to switch to base_branch cleanly
            code, _, err = run_command(["git", "checkout", self.state.base_branch], cwd=self.target_repo)
            if code != 0:
                return False, f"Primary repository is on '{curr_b}', failed to checkout base branch '{self.state.base_branch}': {err}", {}

        # 2. Fast-Forward check: is base_branch an ancestor of ticket branch?
        code, _, _ = run_command(
            ["git", "merge-base", "--is-ancestor", self.state.base_branch, ticket.branch_name],
            cwd=self.target_repo,
        )
        if code != 0:
            return False, (
                f"REFUSED: Branch '{ticket.branch_name}' has diverged from '{self.state.base_branch}' (not a clean fast-forward). "
                f"Rebase '{ticket.branch_name}' onto '{self.state.base_branch}' inside worktree before merging."
            ), {}

        # 3. Fast-forward merge into primary repo
        code, merge_out, merge_err = run_command(
            ["git", "merge", "--ff-only", ticket.branch_name],
            cwd=self.target_repo,
        )
        if code != 0:
            return False, f"Failed to fast-forward merge {ticket.branch_name} into {self.state.base_branch}: {merge_err or merge_out}", {}

        # 4. Return worktree to Treehouse pool
        if ticket.worktree_path:
            ok, wt_msg = return_worktree(self.target_repo, ticket.worktree_path, force=False)
            if not ok:
                print(f"[WARN] Failed to cleanly return worktree to Treehouse pool: {wt_msg}")

        # 5. Mark flight recorder as RESOLVED
        try:
            recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
            recorder.mark_status("RESOLVED")
        except Exception as e:
            print(f"[WARN] Failed to mark flight recorder RESOLVED: {e}")

        # 6. Refresh radar ledger to resolve debt
        radar_cli = Path(__file__).resolve().parent.parent / "radar" / "cli.py"
        target_path_str = str(self.target_repo)
        
        if target_path_str.startswith(r"\\wsl.localhost") or target_path_str.startswith("/home/"):
            wsl_target = target_path_str.replace(r"\\wsl.localhost\Ubuntu-24.04", "").replace("\\", "/")
            wsl_radar = str(radar_cli).replace(r"C:\Users\oguz_\.gemini\config\plugins\edge", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge").replace("\\", "/")
            cmd = ["python3", wsl_radar, "scan", wsl_target]
        else:
            cmd = [sys.executable, str(radar_cli), "scan", str(self.target_repo)]

        code, stdout, stderr = run_command(cmd, cwd=self.target_repo)
        if code != 0:
            print(f"[WARN] Radar scan had issues: {stderr}")

        return True, f"Ticket {ticket.ticket_id} successfully merged into {self.state.base_branch} and worktree released to pool.", {"output": merge_out}

    # =========================================================================
    # State Machine Transitions
    # =========================================================================

    def advance(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        """
        Advances the state machine to the next deterministic state.
        Guards govern each step. If a guard fails, the machine remains in place
        or transitions to BLOCKED.
        """
        curr = self.state.current_state

        if curr == CycleState.IDLE:
            if not self.state.active_ticket:
                return False, curr, "Cannot advance from IDLE without an active ticket. Run 'triage' first."
            self._transition(CycleState.TRIAGE, "Initialized triage from active ticket.")
            return True, self.state.current_state, "Moved to TRIAGE."

        elif curr == CycleState.TRIAGE:
            passed, msg, details = self.guard_triage_to_surgery()
            if not passed and not force:
                return False, curr, f"Triage validation failed: {msg}"
            self._transition(CycleState.SURGERY, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.SURGERY:
            passed, msg, details = self.guard_surgery_to_verify()
            if not passed and not force:
                return False, curr, f"Surgery guard blocked advancement: {msg}"
            self._transition(CycleState.VERIFY, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.VERIFY:
            passed, msg, details = self.guard_verify_to_review()
            if not passed and not force:
                return False, curr, f"Verification guard blocked advancement: {msg}"
            self._transition(CycleState.REVIEW, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.REVIEW:
            next_state, msg, details = self.guard_review_to_next()
            self._transition(next_state, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.POLISH:
            passed, msg, details = self.guard_polish_to_gate()
            if not passed and not force:
                return False, curr, f"Polish guard blocked advancement: {msg}"
            self._transition(CycleState.GATE, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.GATE:
            passed, msg, details = self.guard_gate_to_staging()
            if not passed and not force:
                return False, curr, f"Edge Gate blocked advancement: {msg}"
            self._transition(CycleState.STAGING, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.STAGING:
            passed, msg, details = self.guard_staging_to_completed()
            if not passed and not force:
                return False, curr, f"Staging guard blocked completion: {msg}"
            self._transition(CycleState.COMPLETED, msg, details)
            return True, self.state.current_state, msg

        elif curr == CycleState.COMPLETED:
            # Reset for next cycle
            self._transition(CycleState.IDLE, "Cycle completed. Reset to IDLE.")
            self.state.active_ticket = None
            self.state.active_branch = None
            self.state.review_findings = []
            self.save()
            return True, self.state.current_state, "Reset to IDLE for next ticket."

        elif curr == CycleState.BLOCKED:
            return False, curr, f"State is BLOCKED ({self.state.blocked_reason}). Run 'abort' to reset."

        elif curr == CycleState.PAUSED:
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

    def abort(self, reason: str, force: bool = True, negative_constraint: Optional[str] = None) -> None:
        """
        Aborts active cycle, releases isolated worktree back to Treehouse pool,
        records dead-end into FlightRecorder, and resets machine to IDLE.
        """
        ticket = self.state.active_ticket
        if ticket:
            # 1. Record dead-end and negative constraint in FlightRecorder
            try:
                recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
                recorder.record_dead_end(
                    title=f"Aborted in state {self.state.current_state.value}",
                    reason=reason,
                    prohibited_rule=negative_constraint or f"Avoid design/path resulting in abortion: {reason}",
                )
                recorder.mark_status("TERMINATED")
            except Exception as e:
                print(f"[WARN] Failed to record dead-end in flight recorder: {e}")

            # 2. Release worktree back to Treehouse pool if allocated
            if ticket.worktree_path:
                try:
                    return_worktree(self.target_repo, ticket.worktree_path, force=force)
                except Exception as e:
                    print(f"[WARN] Failed to return worktree during abort: {e}")

        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
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
                recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
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
                recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
                recorder.record_decision(decision)
            except Exception as e:
                print(f"[WARN] Failed to log decision in flight recorder: {e}")

        return self.resume()

    def calculate_file_metrics(self, file_path: Path) -> Tuple[int, float]:
        """Calculates SLOC and Health Score for a target file. Returns (sloc, health_score)."""
        if not file_path.exists():
            return 0, 0.0
        try:
            from tools.audit.scanner import FileScanner
            from tools.audit.scorer import HealthScorer
            scanner = FileScanner(workspace_root=self.target_repo)
            ext = file_path.suffix.lower()
            adapter = scanner.ext_map.get(ext)
            if not adapter:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [l for l in f if l.strip()]
                return len(lines), 0.0
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            try:
                rel = str(file_path.relative_to(self.target_repo)).replace("\\", "/")
            except ValueError:
                rel = str(file_path).replace("\\", "/")
            metric = adapter.analyze(path=file_path, rel_path=rel, content=content, workspace_root=self.target_repo, test_index={})
            scored = HealthScorer.score_file(metric)
            health = round(max(0.0, 100.0 - scored.risk_score), 2)
            return scored.sloc, health
        except Exception:
            return 0, 0.0

    def rollback_stagnated(self, reason: str) -> None:
        """Rolls back the active ticket branch if health score failed to improve after N attempts."""
        ticket = self.state.active_ticket
        base_ref = self.state.base_branch
        self._run_cmd(["git", "checkout", base_ref])
        if ticket and ticket.branch_name:
            self._run_cmd(["git", "branch", "-D", ticket.branch_name])
        
        if ticket:
            ticket.status = "STAGNATED"
        
        self.state.blocked_reason = f"Stagnated after {ticket.attempt_count if ticket else 0} attempts: {reason}"
        self._transition(CycleState.STAGNATED, f"Stagnation rollback: {reason}")
        self._transition(CycleState.IDLE, "Reset to IDLE after rollback.")

    # =========================================================================
    # Radar Ledger Triage Engine
    # =========================================================================

    def triage_next_ticket(
        self,
        track: str = "core",
        target_domain: Optional[str] = None,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None,
        transcript_path: Optional[Path] = None,
    ) -> Optional[Ticket]:
        """
        Inspects .edge/ledger/<track>.json and creates a discrete Ticket
        for the highest priority finding.
        Supports whitelist (only allowed domains) and blacklist (forbidden domains).
        Throttles/blocks triage if context heat zone is YELLOW or RED.
        """
        if self.state.current_state == CycleState.PAUSED:
            print("⚠️ Cannot triage while state is PAUSED. Run 'brigade resume' first.")
            return None

        if transcript_path:
            tokens = self.calculate_token_estimate(transcript_path)
            zone, rec = self.get_heat_zone(tokens)
            if zone in (ContextHeatZone.YELLOW, ContextHeatZone.RED):
                print(f"⚠️ TRIAGE BLOCKED BY HEAT POLICY: {rec}")
                return None

        ledger_path = self.target_repo / ".edge" / "ledger" / f"{track}.json"
        if not ledger_path.exists():
            return None

        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        items = data.get("items", [])
        open_items = [i for i in items if i.get("status") == "OPEN"]
        if not open_items:
            return None

        # Domain whitelist filtering
        if whitelist:
            whitelist_norm = [w.lower().rstrip("s") for w in whitelist]
            open_items = [
                i for i in open_items
                if any(w in i.get("file_path", "").lower() or w in i.get("title", "").lower() for w in whitelist_norm)
            ]

        # Domain blacklist filtering (e.g. skip bookings)
        if blacklist:
            blacklist_norm = [b.lower().rstrip("s") for b in blacklist]
            open_items = [
                i for i in open_items
                if not any(b in i.get("file_path", "").lower() or b in i.get("title", "").lower() for b in blacklist_norm)
            ]

        if not open_items:
            return None

        if target_domain:
            domain_norm = target_domain.lower().rstrip("s")
            domain_filtered = [
                i for i in open_items
                if domain_norm in i.get("file_path", "").lower() or domain_norm in i.get("title", "").lower()
            ]
            if domain_filtered:
                open_items = domain_filtered

        # Prioritize CRITICAL over WARNING over ADVISORY
        severity_order = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2}
        open_items.sort(key=lambda x: severity_order.get(x.get("severity", "WARNING"), 99))
        
        target = open_items[0]
        file_path = target.get("file_path", "")
        
        # Extract domain name: e.g. src/actions/bookings.ts -> bookings
        path_obj = Path(file_path)
        domain = path_obj.stem
        if domain.endswith(".test") or domain.endswith(".spec"):
            domain = domain.split(".")[0]

        rule_id = target.get("rule_id", "RULE-GENERAL")
        line_num = target.get("line_number", 1)
        ticket_id = Ticket.generate_id(track, domain, rule_id, line_num)
        
        # Branch name: refactor/<track>-<domain>-<rule_short>
        rule_short = rule_id.lower().replace("rule-", "").replace("-", "")[:10]
        branch_name = f"refactor/{track}-{domain}-{rule_short}"

        # Scaffolding allowance: if repository doesn't exist yet, allow +25
        repo_file = self.target_repo / "src" / "lib" / domain / "repository.ts"
        scaffolding = 25 if not repo_file.exists() else 0

        # Characterization test seam command
        test_file = self.target_repo / "tests" / "unit" / domain / f"{domain}.test.ts"
        if test_file.exists():
            test_seam = f"npx vitest run tests/unit/{domain}/{domain}.test.ts"
        else:
            test_seam = "npm run test:unit"

        # Measure initial metrics before surgery
        full_target = self.target_repo / file_path
        sloc_b, health_b = self.calculate_file_metrics(full_target)

        # Check flight recorder for prior dead ends / constraints
        recorder = FlightRecorder(self.target_repo, ticket_id)
        prior_constraints = recorder.get_negative_constraints()

        base_constraints = [
            "MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations.",
            "Database Leak Elimination: Zero direct `db.select`, `db.insert`, `db.update`, `db.delete` in action controller.",
            f"Target Contraction: `{file_path}` must strictly shrink in net SLOC.",
            f"Scaffolding Budget: Scaffolding allowance is +{scaffolding} lines.",
            "Zero-Wrapper Left Behind: Do not create shallow 1-line pass-through services.",
        ]
        all_constraints = base_constraints + [c for c in prior_constraints if c not in base_constraints]

        ticket = Ticket(
            ticket_id=ticket_id,
            track=track,
            domain=domain,
            rule_id=rule_id,
            severity=target.get("severity", "WARNING"),
            target_file=file_path,
            target_symbol=target.get("symbol"),
            line_number=line_num,
            fingerprint=target.get("fingerprint", ""),
            description=target.get("title", ""),
            suggested_fix=target.get("suggested_fix", ""),
            branch_name=branch_name,
            test_seam_command=test_seam,
            scaffolding_allowance=scaffolding,
            negative_constraints=all_constraints,
            health_before=health_b,
            sloc_before=sloc_b,
        )

        self.state.active_ticket = ticket
        self.state.active_branch = branch_name
        self.state.current_state = CycleState.TRIAGE
        self.save()
        return ticket

    def start_slice(
        self,
        name: str,
        track: str = "feature",
        target_file: str = "",
        domain: str = "",
        test_seam_command: str = "npm run test:unit",
        allow_schema_migration: bool = True,
        auto_lease_worktree: bool = True,
    ) -> Tuple[bool, Optional[Ticket], str]:
        """
        Deterministically initiates a live feature or refactor slice:
        1. Checks if an active ticket is currently in-flight.
        2. Generates ticket (e.g. TICK-FEAT-<name>).
        3. Derives branch name (e.g. feat/<name> or refactor/<name>).
        4. If auto_lease_worktree is True and treehouse is installed, acquires an isolated worktree slot.
        5. Initializes FlightRecorder.
        6. Sets FSM state to SURGERY (ready for Coder or Surgeon).
        """
        if self.state.active_ticket and self.state.current_state != CycleState.IDLE:
            return False, self.state.active_ticket, f"Cannot start slice: Active ticket {self.state.active_ticket.ticket_id} is currently in progress (State: {self.state.current_state.value}). Finish or abort it first."

        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).lower().strip("-")
        eff_domain = domain or (Path(target_file).stem if target_file else clean_name)
        rule_id = f"SLICE-{clean_name.upper()[:12]}"
        ticket_id = f"TICK-{track.upper()[:4]}-{clean_name.upper()[:16]}"
        
        prefix = "feat" if track == "feature" else "refactor"
        branch_name = f"{prefix}/{clean_name}"

        # Flight recorder setup
        recorder = FlightRecorder(self.target_repo, ticket_id)
        prior_constraints = recorder.get_negative_constraints()

        base_constraints = [
            "Zero-Touch Primary Checkout Invariant: All mutations must be executed strictly inside the leased worktree.",
            "Test Immutability: Coder must not delete or loosen tests authored by Seam Architect.",
        ]
        if track != "feature" and not allow_schema_migration:
            base_constraints.append("MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations.")

        all_constraints = base_constraints + [c for c in prior_constraints if c not in base_constraints]

        ticket = Ticket(
            ticket_id=ticket_id,
            track=track,
            domain=eff_domain,
            rule_id=rule_id,
            severity="NORMAL",
            target_file=target_file or f"src/{clean_name}",
            line_number=1,
            fingerprint=f"slice-{clean_name}",
            description=f"Live slice: {name}",
            suggested_fix=f"Implement slice {name}",
            branch_name=branch_name,
            test_seam_command=test_seam_command,
            scaffolding_allowance=50 if track == "feature" else 15,
            enforce_contraction=False,
            allow_schema_migration=allow_schema_migration,
            negative_constraints=all_constraints,
        )

        is_git_repo = (self.target_repo / ".git").exists()
        worktree_msg = ""
        if auto_lease_worktree and is_git_repo and is_treehouse_installed():
            ok, wt_path, err = acquire_worktree(
                repo_path=self.target_repo,
                branch_name=branch_name,
                lease_holder=f"brigade-{ticket_id}",
            )
            if not ok:
                return False, None, f"Failed to acquire isolated Treehouse worktree: {err}"
            ticket.worktree_path = wt_path
            self.state.active_worktree = wt_path
            worktree_msg = f" Worktree leased at {wt_path}."

        recorder.set_metadata(
            track=track,
            domain=eff_domain,
            target_file=ticket.target_file,
            worktree_path=ticket.worktree_path or "",
        )

        self.state.active_ticket = ticket
        self.state.active_branch = branch_name
        self.state.current_state = CycleState.SURGERY
        self.save()

        return True, ticket, f"Slice '{name}' initiated successfully.{worktree_msg} Branch: {branch_name} (State: SURGERY)."

    def finish_slice(self) -> Tuple[bool, str]:
        """
        Fast-forward merges the active slice worktree into base_branch (development),
        releases the Treehouse worktree back to pool, and resets FSM to IDLE.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active slice or ticket to finish. Brigade is IDLE."

        ok, msg, details = self.guard_staging_to_completed()
        if not ok:
            return False, f"Finish slice failed: {msg}"

        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Slice {ticket.ticket_id} finished and merged cleanly.")

        return True, msg

    # =========================================================================
    # Pause, Resume & Context Heat Protocols
    # =========================================================================

    def _get_substeps_for_state(self, state: CycleState, ticket: Optional[Ticket]) -> Tuple[List[str], List[str], str]:
        """Infers completed and pending substeps plus next action prompt from state."""
        target = ticket.target_file if ticket else "target file"
        if state == CycleState.IDLE:
            return [], ["triage_next_ticket"], "Run 'brigade triage' to pick next ticket from radar."
        elif state == CycleState.TRIAGE:
            return ["ticket_triaged"], ["git_branch_created", "baseline_compiler_verified", "surgery"], "Run 'brigade advance' to transition to SURGERY and dispatch Surgeon."
        elif state == CycleState.SURGERY:
            return ["ticket_triaged", "git_branch_created"], ["code_modifications", "hermetic_verification", "gate_verification"], f"Execute bounded surgery on {target}, then verify with tests and tsc before advancing to VERIFY."
        elif state == CycleState.VERIFY:
            return ["ticket_triaged", "surgery_completed"], ["test_seam_verification", "tsc_compilation", "dual_axis_review"], "Run hermetic test seams and advance to REVIEW."
        elif state == CycleState.REVIEW:
            return ["ticket_triaged", "surgery_completed", "hermetic_tests_passed"], ["standards_review", "spec_review", "edge_gate"], "Execute dual-axis review (Standards & Spec) and record findings."
        elif state == CycleState.POLISH:
            return ["review_findings_recorded"], ["remediate_critical_findings", "re_verify", "edge_gate"], "Remediate critical review findings and advance to GATE."
        elif state == CycleState.GATE:
            return ["review_clean"], ["edge_gate_execution", "squash_merge"], "Run 'python tools/gate.py' verification suite and advance to STAGING."
        elif state == CycleState.STAGING:
            return ["gate_passed"], ["squash_merge_to_base", "radar_ledger_update"], "Squash-merge refactor branch into base and update radar ledger."
        return [], [], f"Resume execution in state {state.value}."

    def pause(self, reason: str = "MANUAL_PAUSE") -> Checkpoint:
        """
        Durable Safe Checkpoint:
        1. Checks for dirty uncommitted changes in git working tree.
        2. If dirty, creates a safe 'wip(checkpoint): safe pause at <STATE>' commit.
        3. Retrieves active HEAD commit SHA.
        4. Serializes in-flight ticket, substeps, and next action to .edge/checkpoint.json.
        5. Transitions FSM state to CycleState.PAUSED.
        """
        code, status_out, _ = self._run_cmd(["git", "status", "--porcelain"])
        dirty = bool(status_out.strip())
        has_uncommitted_work = False

        prior_state = self.state.current_state
        ticket = self.state.active_ticket
        ticket_id = ticket.ticket_id if ticket else "NO_TICKET"

        if dirty:
            commit_msg = f"wip(checkpoint): safe pause at {prior_state.value} [{ticket_id}]"
            self._run_cmd(["git", "add", "-A"])
            self._run_cmd(["git", "commit", "-m", commit_msg])
            has_uncommitted_work = True

        code, head_sha, _ = self._run_cmd(["git", "rev-parse", "HEAD"])
        wip_commit_sha = head_sha.strip() if code == 0 else None

        completed, pending, next_action = self._get_substeps_for_state(prior_state, ticket)

        checkpoint = Checkpoint(
            paused_at=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            base_branch=self.state.base_branch,
            active_branch=self.state.active_branch,
            worktree_path=ticket.worktree_path if ticket else self.state.active_worktree,
            active_ticket=ticket,
            fsm_state=prior_state.value,
            completed_substeps=completed,
            pending_substeps=pending,
            wip_commit_sha=wip_commit_sha,
            has_uncommitted_work=has_uncommitted_work,
            next_action=next_action,
        )

        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.checkpoint_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
        if tmp_file.exists():
            if self.checkpoint_file.exists():
                self.checkpoint_file.unlink()
            tmp_file.rename(self.checkpoint_file)

        self._transition(CycleState.PAUSED, f"Paused: {reason} (prior state: {prior_state.value})", {
            "reason": reason,
            "prior_state": prior_state.value,
            "has_uncommitted_work": has_uncommitted_work,
            "wip_commit_sha": wip_commit_sha,
        })

        return checkpoint

    def resume(self) -> Tuple[bool, Optional[Checkpoint], str]:
        """
        Zero-Transcript Session Pickup:
        1. Reads .edge/checkpoint.json.
        2. Verifies / switches to active git branch.
        3. Restores FSM in-memory state and active ticket.
        4. Archives/removes checkpoint file.
        5. Returns actionable resume prompt for the next agent turn.
        """
        if not self.checkpoint_file.exists():
            return False, None, "No checkpoint found at .edge/checkpoint.json. Brigade is in state IDLE."

        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            checkpoint = Checkpoint.from_dict(data)
        except Exception as e:
            return False, None, f"Failed to read checkpoint: {e}"

        # Branch verification
        if checkpoint.active_branch:
            code, curr_branch, _ = self._run_cmd(["git", "branch", "--show-current"])
            curr_branch_str = curr_branch.strip()
            if curr_branch_str != checkpoint.active_branch:
                self._run_cmd(["git", "checkout", checkpoint.active_branch])

        # Restore state
        try:
            restored_state = CycleState(checkpoint.fsm_state)
        except ValueError:
            restored_state = CycleState.IDLE

        self.state.current_state = restored_state
        self.state.active_ticket = checkpoint.active_ticket
        self.state.active_branch = checkpoint.active_branch
        self.state.active_worktree = checkpoint.worktree_path or (checkpoint.active_ticket.worktree_path if checkpoint.active_ticket else None)
        self.state.base_branch = checkpoint.base_branch
        self.state.blocked_reason = None

        self._transition(
            restored_state,
            f"Resumed from checkpoint (paused at {checkpoint.paused_at}). State restored to {checkpoint.fsm_state}.",
            {
                "checkpoint_reason": checkpoint.reason,
                "wip_commit_sha": checkpoint.wip_commit_sha,
            }
        )
        self.save()

        # Archive checkpoint by renaming or removing
        try:
            bak_file = self.checkpoint_file.with_suffix(".json.bak")
            if bak_file.exists():
                bak_file.unlink()
            self.checkpoint_file.rename(bak_file)
        except Exception:
            if self.checkpoint_file.exists():
                self.checkpoint_file.unlink()

        summary = (
            f"✅ Checkpoint restored successfully!\n"
            f"   State:     [{restored_state.value}]\n"
            f"   Ticket:    {checkpoint.active_ticket.ticket_id if checkpoint.active_ticket else 'None'}\n"
            f"   Branch:    {checkpoint.active_branch or 'None'}\n"
            f"   Next Step: {checkpoint.next_action}"
        )
        return True, checkpoint, summary

    @staticmethod
    def calculate_token_estimate(transcript_path: Path) -> int:
        norm_path = normalize_target_path(transcript_path)
        if not norm_path.exists():
            return 0
        total_chars = 0
        if norm_path.is_file():
            try:
                with open(norm_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        total_chars += len(line)
            except Exception:
                total_chars = norm_path.stat().st_size
        elif norm_path.is_dir():
            for p in norm_path.glob("*.jsonl"):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            total_chars += len(line)
                except Exception:
                    total_chars += p.stat().st_size
        return total_chars // 4

    @staticmethod
    def get_heat_zone(token_count: int) -> Tuple[ContextHeatZone, str]:
        if token_count < GREEN_HEAT_THRESHOLD:
            return (
                ContextHeatZone.GREEN,
                f"GREEN ZONE ({token_count:,} tokens): Context is optimal. Proceed with normal operations."
            )
        elif token_count <= YELLOW_HEAT_THRESHOLD:
            return (
                ContextHeatZone.YELLOW,
                f"YELLOW ZONE ({token_count:,} tokens): Cognitive drain limit approaching. DRAIN ACTIVE TICKET ONLY. Do NOT start new tickets. Trigger 'brigade pause' upon ticket completion."
            )
        else:
            return (
                ContextHeatZone.RED,
                f"RED ZONE ({token_count:,} tokens): Cognitive saturation limit reached! EMERGENCY CHECKPOINT REQUIRED. Run 'brigade pause' immediately to preserve in-flight work."
            )

    def check_heat(self, transcript_path: Path) -> Tuple[ContextHeatZone, int, str]:
        tokens = self.calculate_token_estimate(transcript_path)
        zone, recommendation = self.get_heat_zone(tokens)
        return zone, tokens, recommendation

