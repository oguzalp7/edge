"""BrigadeFSM mixin: refactor_seal."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import json

from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.worktree import acquire_worktree, is_treehouse_installed, return_worktree
from tools.brigade.worktree_git import is_native_worktree_path


class FsmRefactorSealMixin:
    """Mixin providing refactor_seal operations for BrigadeFSM."""

    @staticmethod
    def _derive_refactor_slug(ticket: Ticket) -> str:
        if ticket.branch_name:
            return ticket.branch_name.split("/")[-1].strip()
        if ticket.domain:
            return ticket.domain.lower().replace("_", "-").strip()
        return ticket.ticket_id.lower()

    def _synthesize_refactor_receipt(self, ticket: Ticket) -> None:
        from tools.brigade.refactor_receipt import build_and_write_refactor_receipt

        work_dir = self._get_work_dir()
        if not (work_dir / ".git").exists() and not (self.target_repo / ".git").exists():
            return
        slug = self._derive_refactor_slug(ticket)
        surgeon_cid = ticket.surgeon_cid or self._resolve_station_cid("surgeon")
        try:
            receipt, _, _ = build_and_write_refactor_receipt(
                target_repo=self.target_repo,
                work_dir=work_dir,
                slug=slug,
                base_branch=self.state.base_branch or "development",
                ticket=ticket,
                examiner_receipt=self.state.examiner_receipt,
                surgeon_cid=surgeon_cid,
            )
            after_sloc = receipt.seal_2_metrics.get("after", {}).get("sloc")
            if isinstance(after_sloc, int):
                ticket.sloc_after = after_sloc
            target_in_work = (work_dir / ticket.target_file) if ticket.target_file else None
            if target_in_work and target_in_work.is_file():
                _, ticket.health_after = self.calculate_file_metrics(target_in_work)
            self.save()
        except Exception as exc:
            print(f"[WARN] Failed to synthesize RefactorReceipt: {exc}")

    def _refresh_refactor_seal_4(self, ticket: Ticket) -> None:
        from tools.brigade.refactor_receipt import refresh_receipt_examiner_seal

        slug = self._derive_refactor_slug(ticket)
        surgeon_cid = ticket.surgeon_cid or self._resolve_station_cid("surgeon")
        res = refresh_receipt_examiner_seal(
            target_repo=self.target_repo,
            slug=slug,
            examiner_receipt=self.state.examiner_receipt,
            surgeon_cid=surgeon_cid,
        )
        if res is None:
            self._synthesize_refactor_receipt(ticket)

    def _find_refactor_receipt_file(self, ticket: Ticket) -> Optional[Path]:
        rec_dir = self.target_repo / ".edge" / "receipts" / "refactor"
        if not rec_dir.is_dir():
            return None
        slug = self._derive_refactor_slug(ticket)
        cand = rec_dir / f"{slug}.json"
        if cand.is_file():
            return cand
        return next(
            (jf for jf in sorted(rec_dir.glob("*.json")) if self._receipt_matches_ticket(jf, ticket.ticket_id)),
            None,
        )

    @staticmethod
    def _receipt_matches_ticket(json_file: Path, ticket_id: str) -> bool:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            return isinstance(data, dict) and data.get("ticket_id") == ticket_id
        except Exception:
            return False
        return None

    def _is_ticket_one_way_door(self, ticket: Ticket, ship_door_type: str) -> bool:
        if ship_door_type.startswith("One-way"):
            return True
        from tools.brigade.ship_prep import _is_one_way_door_path, _is_refactor_auth_path
        paths = [ticket.target_file, *(getattr(ticket, "expected_files", None) or [])]
        if any(_is_one_way_door_path(p) for p in paths if p):
            return True
        if getattr(ticket, "track", "core") in ("core", "ui"):
            return any(_is_refactor_auth_path(p) for p in paths if p)
        return False

    @staticmethod
    def _extract_pr_url(stdout: str) -> str:
        for line in reversed((stdout or "").splitlines()):
            s = line.strip()
            if s.startswith("http://") or s.startswith("https://"):
                return s
        return (stdout or "").strip()

    @staticmethod
    def _parse_pr_view_state(stdout: str) -> Tuple[str, str]:
        try:
            data = json.loads(stdout or "{}")
            if isinstance(data, dict):
                return str(data.get("state") or "").upper(), str(data.get("url") or "")
        except Exception:
            pass
        return "", ""

    def _reset_after_slice_finish(self, ticket: Ticket) -> None:
        if ticket.worktree_path:
            ret_kwargs: Dict[str, Any] = {"force": False}
            if is_native_worktree_path(ticket.worktree_path):
                ret_kwargs["base_branch"] = self.state.base_branch or "development"
            call_facade("return_worktree", return_worktree)(self.target_repo, ticket.worktree_path, **ret_kwargs)
        self._archive_ticket_spec(ticket)
        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Slice {ticket.ticket_id} finished and merged cleanly.")
