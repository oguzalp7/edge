"""BrigadeFSM mixin: staging_archive."""

from pathlib import Path
import sys
from typing import List

from tools.brigade.fsm_ops.constants import call_facade
from tools.brigade.models import Ticket
from tools.common import run_command


def _is_archivable_spec_path(p: Path, edge_specs_dir: Path, edge_cache_dir: Path) -> bool:
    try:
        p_res = p.resolve()
        in_cache = p_res == edge_cache_dir or edge_cache_dir in p_res.parents
        return not in_cache and (edge_specs_dir in p_res.parents or p_res.parent == edge_specs_dir)
    except Exception:
        return False


class FsmStagingArchiveMixin:
    """Mixin providing spec archival and radar rescan helpers for BrigadeFSM."""

    def _archive_ticket_spec(self, ticket: Ticket) -> None:
        """Archives ephemeral slice spec from .edge/specs/ to .edge/archive/specs/."""
        try:
            from tools.drift.scanner import archive_ephemeral_spec
        except ImportError:
            return
        candidates: List[Path] = []
        edge_specs_dir = (self.target_repo / ".edge" / "specs").resolve()
        edge_cache_dir = (self.target_repo / ".edge" / "cache").resolve()
        if ticket.spec_path:
            p = Path(ticket.spec_path)
            p = p if p.is_absolute() else self.target_repo / p
            if p.is_file() and _is_archivable_spec_path(p, edge_specs_dir, edge_cache_dir):
                candidates.append(p)
        branch_slug = ticket.branch_name.split("/")[-1] if ticket.branch_name else ""
        for stem in (branch_slug, ticket.ticket_id.lower() if ticket.ticket_id else ""):
            if stem and (cand := self.target_repo / ".edge" / "specs" / f"{stem}.md").is_file() and cand not in candidates:
                candidates.append(cand)
        for c in candidates:
            try:
                archive_ephemeral_spec(self.target_repo, c)
            except Exception as e:
                print(f"[WARN] Failed to archive spec {c}: {e}")

    def _run_radar_rescan(self) -> None:
        """Refreshes radar ledger to resolve debt after ticket completion."""
        radar_cli = Path(__file__).resolve().parents[2] / "radar" / "cli.py"
        target_path_str = str(self.target_repo)
        if target_path_str.startswith(r"\\wsl.localhost") or target_path_str.startswith("/home/"):
            wsl_target = target_path_str.replace(r"\\wsl.localhost\Ubuntu-24.04", "").replace("\\", "/")
            wsl_radar = str(radar_cli).replace(r"C:\Users\oguz_\.gemini\config\plugins\edge", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge").replace("\\", "/")
            cmd = ["python3", wsl_radar, "scan", wsl_target]
        else:
            cmd = [sys.executable, str(radar_cli), "scan", str(self.target_repo)]
        code, _, stderr = call_facade("run_command", run_command)(cmd, cwd=self.target_repo)
        if code != 0:
            print(f"[WARN] Radar scan had issues: {stderr}")
