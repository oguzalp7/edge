"""Harvest and legacy run_distill subcommands for edge-distill."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Optional

from tools.common import normalize_target_path
from tools.distill.harvester import TranscriptGraphHarvester
from tools.distill.state import DistillStateManager


def run_distill(
    repo_path: Path, domain: Optional[str] = None, track: str = "core",
    ticket_id: Optional[str] = None, output_path: Optional[str] = None, max_commits: int = 15,
) -> int:
    """Legacy wrapper running TranscriptGraphHarvester and printing or writing TOON."""
    digest = TranscriptGraphHarvester(repo_path=repo_path).harvest(project_path=repo_path)
    if output_path:
        Path(output_path).write_text(digest.to_toon(), encoding="utf-8")
    else:
        print(digest.to_toon())
    return 0


def _resolve_harvest_mode(mode_arg: str, target_repo: Path) -> str:
    if mode_arg != "auto":
        return mode_arg
    plugin_root = Path(__file__).resolve().parents[2]
    return "factory" if target_repo.resolve() == plugin_root.resolve() else "project"


def _commit_harvest_watermark(
    harvester: TranscriptGraphHarvester, digest: Any, mode: str, target_repo: Path, state_mgr: DistillStateManager,
) -> None:
    harvester.watermark_state.last_harvested_at = datetime.now(timezone.utc).isoformat()
    target_repo_str = str(target_repo.resolve())
    for sid in digest.sessions_analyzed:
        if sid not in harvester.watermark_state.processed_sessions:
            harvester.watermark_state.processed_sessions.append(sid)
        target_list = (
            harvester.watermark_state.factory_processed_sessions if mode == "factory"
            else harvester.watermark_state.project_sessions.setdefault(target_repo_str, [])
        )
        if sid not in target_list:
            target_list.append(sid)
    harvester.watermark_state.metrics["total_harvested"] = len(harvester.watermark_state.processed_sessions)
    state_mgr.save_state(harvester.watermark_state)


def _format_digest_output(digest: Any, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(digest.to_dict(), indent=2)
    if fmt == "toon":
        return digest.to_toon()
    return f"FrictionDigest for {digest.project_name}: {len(digest.sessions_analyzed)} sessions, {len(digest.tool_frictions)} frictions, {len(digest.station_escapes)} escapes"


def cmd_harvest(args: argparse.Namespace) -> int:
    """Harvest zero-token signals from Antigravity session transcripts."""
    target_repo = normalize_target_path(getattr(args, "project", None) or getattr(args, "repo", "."))
    mode = _resolve_harvest_mode(getattr(args, "mode", "auto"), target_repo)
    state_mgr = DistillStateManager()
    env_brain = os.environ.get("GEMINI_BRAIN_ROOT")
    harvester = TranscriptGraphHarvester(
        repo_path=target_repo, watermark_state=state_mgr.load_state(),
        brain_roots=[Path(env_brain)] if env_brain else None, since_hours=getattr(args, "since_hours", None),
    )
    digest = harvester.harvest(
        project_path=target_repo, reprocess=getattr(args, "reprocess", False),
        current_session_id=getattr(args, "current", None), max_sessions=getattr(args, "max_sessions", 50), mode=mode,
    )
    _commit_harvest_watermark(harvester, digest, mode, target_repo, state_mgr)
    if digest.harness_signals_queued > 0:
        print(f"[NOTE] Queued {digest.harness_signals_queued} harness signal(s) to edge_factory_inbox.json", file=sys.stderr)
    output_str = _format_digest_output(digest, getattr(args, "format", "toon"))
    out_path = getattr(args, "output", None)
    if out_path:
        Path(out_path).write_text(output_str, encoding="utf-8")
    else:
        print(output_str)
    return 0
