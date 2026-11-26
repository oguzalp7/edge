"""BrigadeFSM mixin: guards_qa."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import json
import sys

from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.proof_verifier import _validate_qa_proof_receipt
from tools.common import normalize_target_path, run_command


class FsmGuardsQaMixin:
    """Mixin providing guards_qa operations for BrigadeFSM."""

    def _has_lavish_candidate(self, ticket: Ticket, work_dir: Path) -> bool:
        slug = ticket.domain.lower().replace("_", "-")
        cands = [work_dir / ".lavish" / f"{slug}.html", self.target_repo / ".lavish" / f"{slug}.html"]
        if ticket.branch_name:
            bslug = ticket.branch_name.removeprefix("feat/").removeprefix("refactor/").replace("_", "-")
            cands.extend([work_dir / ".lavish" / f"{bslug}.html", self.target_repo / ".lavish" / f"{bslug}.html"])
        return any(c.is_file() for c in cands)

    def should_run_qa(self, ticket: Optional[Ticket] = None) -> bool:
        """Evaluates 'Lavish Varsa QA Yap, Yoksa Es Geç' invariant."""
        t = ticket or self.state.active_ticket
        if not t:
            return False
        if t.require_qa is not None:
            return bool(t.require_qa)
        if t.lavish_path and str(t.lavish_path).strip():
            return True
        work_dir = Path(t.worktree_path) if t.worktree_path else self.target_repo
        if self._has_lavish_candidate(t, work_dir):
            return True
        base = self.state.base_branch or "development"
        code, stdout, _ = self._run_cmd(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=work_dir)
        lines = [ln.strip() for ln in (stdout or "").splitlines()]
        return code == 0 and any(ln.startswith(".lavish/") or ln.endswith(".lavish.html") for ln in lines)

    def _run_qa_db_drift_preflight(self, work_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """
        Executes 'npm run db:check-drift' preflight if defined in package.json.
        Returns (True, msg) if script is absent or passes; returns (False, error) on schema drift.
        """
        ticket = self.state.active_ticket
        eff_dir = work_dir or (
            normalize_target_path(ticket.worktree_path) if (ticket and ticket.worktree_path) else self.target_repo
        )
        pkg_json = eff_dir / "package.json"

        if not pkg_json.exists():
            return True, "No package.json found; skipping db:check-drift preflight (bypass)."

        try:
            scripts = json.loads(pkg_json.read_text(encoding="utf-8")).get("scripts", {})
        except Exception as e:
            return True, f"Could not parse package.json for db:check-drift: {e} (bypass)"

        if "db:check-drift" not in scripts:
            return True, "db:check-drift script not defined in package.json; zero-cost bypass."

        code, out, err = self._run_cmd(["npm", "run", "db:check-drift"], cwd=eff_dir)
        if code != 0:
            return False, f"QA DB Drift Preflight FAILED (exit code {code}): Database migration schema drift detected!\n{err or out}"

        return True, "QA DB Drift Preflight PASSED: Database schema is fully synchronized with migrations."

    def guard_qa_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates the QA verification stage before Examiner REVIEW:
        1. Fails if any CRITICAL review finding exists (routes to POLISH).
        2. Enforces deterministic ProofVerifier Receipt Gate (.edge/qa/proofs/<slug>.json).
        3. Executes QA DB drift preflight.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found for QA gate.", {}

        critical_findings = [
            f for f in self.state.review_findings
            if getattr(f, "severity", "").upper() == "CRITICAL"
        ]
        if critical_findings:
            details = {"critical_count": len(critical_findings), "findings": [f.to_dict() if hasattr(f, "to_dict") else f for f in critical_findings]}
            return False, f"QA verification blocked by {len(critical_findings)} critical defects.", details

        work_dir = Path(ticket.worktree_path) if ticket.worktree_path else self.target_repo
        proof_ok, proof_msg, proof_details = call_facade("_validate_qa_proof_receipt", _validate_qa_proof_receipt)(
            self.target_repo, work_dir, ticket
        )
        if not proof_ok:
            return False, proof_msg, proof_details

        drift_ok, drift_msg = self._run_qa_db_drift_preflight(work_dir)
        if not drift_ok:
            return False, drift_msg, {"db_drift": True}

        return (
            True,
            f"QA verification passed (0 critical findings, valid proof receipt for '{proof_details.get('slug')}'). Advancing to REVIEW.",
            {
                "total_findings": len(self.state.review_findings),
                "proof_details": proof_details,
            },
        )

    def guard_qa_to_staging(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Backward-compatibility alias delegating to guard_qa_to_review."""
        return self.guard_qa_to_review()
