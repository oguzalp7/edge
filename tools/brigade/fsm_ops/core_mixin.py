"""BrigadeFSM mixin: core_mixin."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import json

from tools.brigade.fsm_ops.constants import GREEN_HEAT_THRESHOLD, VERIFICATION_TIMEOUT_SECONDS, YELLOW_HEAT_THRESHOLD, call_facade
from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.stations import StationRegistry
from tools.common import normalize_target_path, run_command


class FsmCoreMixin:
    """Mixin providing core_mixin operations for BrigadeFSM."""

    def __init__(self, target_repo_path: Optional[Path] = None, target_repo: Optional[Path] = None):
        eff_path = target_repo_path or target_repo or Path.cwd()
        self.target_repo = normalize_target_path(eff_path)
        self.state_file = self.target_repo / ".edge" / "brigade.json"
        self.checkpoint_file = self.target_repo / ".edge" / "checkpoint.json"
        self.state = self._load_or_init()
        self.registry = StationRegistry(self.state)

    def _load_or_init(self) -> BrigadeState:
        if self.state_file.exists():
            try:
                return BrigadeState.from_dict(json.loads(self.state_file.read_text(encoding="utf-8")))
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
        
        if tmp_file.exists() and self.state_file.exists():
            self.state_file.unlink()
        if tmp_file.exists():
            tmp_file.rename(self.state_file)

    def _get_work_dir(self) -> Path:
        """
        Resolves effective working directory for hermetic operations.
        Priority:
        1. active_ticket.worktree_path (if present and exists)
        2. state.active_worktree (if present and exists)
        3. self.target_repo
        """
        if self.state.active_ticket and self.state.active_ticket.worktree_path:
            wt_path = normalize_target_path(self.state.active_ticket.worktree_path)
            if wt_path.exists():
                return wt_path
        if self.state.active_worktree:
            wt_path = normalize_target_path(self.state.active_worktree)
            if wt_path.exists():
                return wt_path
        return self.target_repo

    def _run_cmd(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """Runs a subprocess command with transparent WSL / Windows path handling."""
        if cwd:
            work_dir = cwd
        elif self.state.active_ticket and self.state.active_ticket.worktree_path:
            work_dir = normalize_target_path(self.state.active_ticket.worktree_path)
        else:
            work_dir = self.target_repo
        if timeout is None:
            return call_facade("run_command", run_command)(cmd, cwd=work_dir)
        return call_facade("run_command", run_command)(cmd, cwd=work_dir, timeout=timeout)

    def _safe_rel_path(self, file_path: Path) -> str:
        try:
            return str(file_path.relative_to(self.target_repo)).replace("\\", "/")
        except ValueError:
            return str(file_path).replace("\\", "/")

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
                lines = [l for l in file_path.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
                return len(lines), 0.0
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            rel = self._safe_rel_path(file_path)
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
