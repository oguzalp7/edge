#!/usr/bin/env python3
from datetime import datetime, timezone
"""
CLI Driver for edge-distill v2: Zero-Token Harvester, State Watermark & Cross-Project Candidate Engine.
"""

import sys
import os
import argparse
import json
from pathlib import Path
from typing import Optional, List, Tuple, Any

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path, toon_encode
setup_utf8_console()

from tools.distill.models import (
    DistillReport,
    FrictionDigest,
    CandidateRule,
    DistillWatermarkState,
)
from tools.distill.session_miner import SessionMiner
from tools.distill.harvester import TranscriptGraphHarvester
from tools.distill.state import (
    FactoryInbox,
    DistillStateManager,
    LexicalStackGate,
    CandidatePool,
    check_line_budget,
    collect_budget_targets,
)


def run_distill(
    repo_path: Path,
    domain: Optional[str] = None,
    track: str = "core",
    ticket_id: Optional[str] = None,
    output_path: Optional[str] = None,
    max_commits: int = 15,
) -> int:
    """Legacy backward compatibility wrapper: runs harvester."""
    harvester = TranscriptGraphHarvester(repo_path=repo_path)
    digest = harvester.harvest(project_path=repo_path)
    if output_path:
        Path(output_path).write_text(digest.to_toon(), encoding="utf-8")
    else:
        print(digest.to_toon())
    return 0


def _resolve_harvest_mode(mode_arg: str, target_repo: Path) -> str:
    if mode_arg != "auto":
        return mode_arg
    plugin_root = Path(__file__).resolve().parents[2]
    if target_repo.resolve() == plugin_root.resolve():
        return "factory"
    return "project"


def _commit_harvest_watermark(
    harvester: TranscriptGraphHarvester,
    digest: Any,
    mode: str,
    target_repo: Path,
    state_mgr: DistillStateManager,
) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    harvester.watermark_state.last_harvested_at = now_iso
    target_repo_str = str(target_repo.resolve())

    for sid in digest.sessions_analyzed:
        if sid not in harvester.watermark_state.processed_sessions:
            harvester.watermark_state.processed_sessions.append(sid)
        if mode == "factory":
            if sid not in harvester.watermark_state.factory_processed_sessions:
                harvester.watermark_state.factory_processed_sessions.append(sid)
        else:
            p_sessions = harvester.watermark_state.project_sessions.setdefault(target_repo_str, [])
            if sid not in p_sessions:
                p_sessions.append(sid)

    harvester.watermark_state.metrics["total_harvested"] = len(harvester.watermark_state.processed_sessions)
    state_mgr.save_state(harvester.watermark_state)


def _format_digest_output(digest: Any, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(digest.to_dict(), indent=2)
    if fmt == "toon":
        return digest.to_toon()
    return f"FrictionDigest for {digest.project_name}: {len(digest.sessions_analyzed)} sessions, {len(digest.tool_frictions)} frictions, {len(digest.station_escapes)} escapes"


def cmd_harvest(args: argparse.Namespace) -> int:
    repo_raw = getattr(args, "project", None) or getattr(args, "repo", ".")
    target_repo = normalize_target_path(repo_raw)
    mode = _resolve_harvest_mode(getattr(args, "mode", "auto"), target_repo)

    state_mgr = DistillStateManager()
    watermark_state = state_mgr.load_state()

    env_brain = os.environ.get("GEMINI_BRAIN_ROOT")
    brain_roots = [Path(env_brain)] if env_brain else None
    harvester = TranscriptGraphHarvester(
        repo_path=target_repo,
        watermark_state=watermark_state,
        brain_roots=brain_roots,
        since_hours=getattr(args, "since_hours", None),
    )
    digest = harvester.harvest(
        project_path=target_repo,
        reprocess=getattr(args, "reprocess", False),
        current_session_id=getattr(args, "current", None),
        max_sessions=getattr(args, "max_sessions", 50),
        mode=mode,
    )

    _commit_harvest_watermark(harvester, digest, mode, target_repo, state_mgr)

    if digest.harness_signals_queued > 0:
        print(f"[NOTE] Queued {digest.harness_signals_queued} harness signal(s) to edge_factory_inbox.json", file=sys.stderr)

    fmt = getattr(args, "format", "toon")
    output_str = _format_digest_output(digest, fmt)

    out_path = getattr(args, "output", None)
    if out_path:
        Path(out_path).write_text(output_str, encoding="utf-8")
    else:
        print(output_str)
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    action = getattr(args, "action", "list")
    pool = CandidatePool()
    if action == "record":
        rule = getattr(args, "rule", None)
        if not rule:
            print("Error: --rule is required for record action", file=sys.stderr)
            return 1
        role = getattr(args, "role", "coder")
        proj = getattr(args, "project", ".")
        cand = pool.record_candidate(
            rule_text=rule,
            target_role=role,
            project_path=str(normalize_target_path(proj)),
        )
        print(f"Recorded candidate {cand.candidate_id}: {cand.status}")
        return 0
    else:
        cands = pool.list_candidates()
        fmt = getattr(args, "format", "toon")
        if fmt == "json":
            print(json.dumps([c.to_dict() for c in cands], indent=2))
        elif fmt == "toon":
            for c in cands:
                print(c.to_toon())
        else:
            for c in cands:
                print(f"{c.candidate_id} [{c.status}] ({c.target_role}): {c.rule_text}")
        return 0


def cmd_promote(args: argparse.Namespace) -> int:
    cid = getattr(args, "candidate", None)
    if not cid:
        print("Error: --candidate is required", file=sys.stderr)
        return 1
    root = getattr(args, "plugin_root", None)
    force = getattr(args, "force", False)
    pool = CandidatePool(plugin_root=Path(root) if root else None)
    try:
        success = pool.promote_candidate(candidate_id=cid, force=force)
        if success:
            print(f"Promoted candidate {cid}")
        else:
            print(f"Candidate {cid} not eligible for promotion")
        return 0
    except ValueError as e:
        print(f"Error promoting candidate {cid}: {e}", file=sys.stderr)
        return 1


def cmd_mark_processed(args: argparse.Namespace) -> int:
    clear_inbox = getattr(args, "clear_factory_inbox", False)
    mode = getattr(args, "mode", "project")
    raw_sessions = getattr(args, "session", []) or []
    if isinstance(raw_sessions, str):
        raw_sessions = [raw_sessions]
    sessions = [s.strip() for raw in raw_sessions for s in raw.split(",") if s.strip()]

    if not sessions and not clear_inbox:
        print("Error: --session or --clear-factory-inbox is required", file=sys.stderr)
        return 1

    if clear_inbox or mode == "factory":
        inbox = FactoryInbox()
        inbox.clear()
        print("Cleared factory inbox")

    if sessions:
        proj = getattr(args, "project", None)
        proj_str = str(normalize_target_path(proj)) if proj else None
        manager = DistillStateManager()
        for sid in sessions:
            manager.mark_session_processed(
                session_id=sid,
                project_path=proj_str,
                mode=mode,
            )
            print(f"Marked session {sid} as processed ({mode} mode)")
    return 0


def _resolve_budget_targets(p: Path, max_lines_override: Optional[int]) -> List[Tuple[Path, int]]:
    targets = collect_budget_targets(p)
    fallback_limit = max_lines_override or 60
    if not targets and p.is_dir():
        return [(f, fallback_limit) for f in sorted(p.glob("*.md"))]
    if not targets:
        return [(p, fallback_limit)]
    return targets


def _check_and_print_targets(targets: List[Tuple[Path, int]], override_limit: Optional[int]) -> bool:
    all_ok = True
    for f, def_limit in targets:
        lim = override_limit or def_limit
        lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        cnt = len(lines)
        if cnt <= lim:
            print(f"PASS: {f.name} has {cnt} lines (budget <= {lim})")
        else:
            print(f"FAIL: {f.name} has {cnt} lines (budget <= {lim} exceeded)", file=sys.stderr)
            all_ok = False
    return all_ok


def cmd_check_budget(args: argparse.Namespace) -> int:
    raw_path = getattr(args, "path", None)
    if not raw_path:
        print("Error: path is required", file=sys.stderr)
        return 1
    p = Path(raw_path).resolve()
    if not p.exists():
        print(f"Error: path does not exist: {p}", file=sys.stderr)
        return 1

    override_limit = getattr(args, "max_lines", None)
    targets = _resolve_budget_targets(p, override_limit)
    all_ok = _check_and_print_targets(targets, override_limit)
    return 0 if all_ok else 1


def _extract_brain_roots(args: argparse.Namespace) -> Optional[List[Path]]:
    brain_roots_arg = getattr(args, "brain_roots", None)
    if isinstance(brain_roots_arg, list):
        return [Path(r) for r in brain_roots_arg]
    elif brain_roots_arg:
        return [Path(brain_roots_arg)]
    return None


def cmd_sessions(args: argparse.Namespace) -> int:
    repo = normalize_target_path(getattr(args, "repo", "."))
    roots = _extract_brain_roots(args)
    miner = SessionMiner(brain_roots=roots, repo_path=repo)
    data = miner.mine_sessions()
    out_path = getattr(args, "output", None)
    if out_path:
        miner.save_sessions_json(data, output_path=out_path)
    fmt = getattr(args, "format", "human")
    if fmt == "toon":
        print(toon_encode({"sessions_summary": data}))
    else:
        print(miner.format_sessions_report(data, by_project=getattr(args, "by_project", False)))
    return 0


def cmd_intents(args: argparse.Namespace) -> int:
    repo = normalize_target_path(getattr(args, "repo", "."))
    roots = _extract_brain_roots(args)
    miner = SessionMiner(brain_roots=roots, repo_path=repo)
    data = miner.mine_sessions()
    out_path = getattr(args, "output", None)
    if out_path:
        miner.save_sessions_json(data, output_path=out_path)
    fmt = getattr(args, "format", "human")
    if fmt == "toon":
        print(toon_encode({"intents_summary": data}))
    else:
        print(miner.format_intents_report(data))
    return 0


def _cmd_inbox_list(args: argparse.Namespace, inbox: FactoryInbox) -> int:
    pending_only = getattr(args, "pending_only", False)
    signals = inbox.load_pending() if pending_only else inbox.load_signals()
    fmt = getattr(args, "format", "human")
    if fmt == "json":
        print(json.dumps({"signals": signals}, indent=2))
        return 0
    if not signals:
        print("Factory inbox is empty.")
        return 0
    print(f"Factory inbox ({len(signals)} signal(s)):")
    for s in signals:
        status = "resolved" if s.get("resolved") else "pending"
        print(f"- [{s.get('signal_id', '')}] ({status}, {s.get('role_or_tool', '')}) {str(s.get('summary', '')).splitlines()[0][:80]}")
    return 0


def _cmd_inbox_prune(args: argparse.Namespace, inbox: FactoryInbox) -> int:
    res = inbox.prune(
        drop_exit_zero=not getattr(args, "no_drop_exit_zero", False),
        drop_benign_tools=not getattr(args, "no_drop_benign_tools", False),
        resolved_only=getattr(args, "resolved_only", False),
        max_age_days=getattr(args, "max_age_days", None),
        project=getattr(args, "project", None),
        dry_run=getattr(args, "dry_run", False),
    )
    fmt = getattr(args, "format", "human")
    if fmt == "json":
        print(json.dumps(res, indent=2))
    else:
        mode_tag = "[DRY-RUN] " if res["dry_run"] else ""
        print(f"{mode_tag}Pruned {res['removed']} signal(s) ({res['before']} -> {res['after']}): {res['removed_by_reason']}")
    return 0


def _cmd_inbox_clear(inbox: FactoryInbox) -> int:
    inbox.clear()
    print("Cleared factory inbox")
    return 0


def cmd_inbox(args: argparse.Namespace) -> int:
    action = getattr(args, "action", None) or "list"
    inbox = FactoryInbox()
    if action == "prune":
        return _cmd_inbox_prune(args, inbox)
    if action == "clear":
        return _cmd_inbox_clear(inbox)
    return _cmd_inbox_list(args, inbox)


DISPATCH_MAP = {
    "harvest": cmd_harvest,
    "candidates": cmd_candidates,
    "promote": cmd_promote,
    "mark-processed": cmd_mark_processed,
    "check-budget": cmd_check_budget,
    "sessions": cmd_sessions,
    "intents": cmd_intents,
    "inbox": cmd_inbox,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edge-distill", description="Edge Distill v2")
    subparsers = parser.add_subparsers(dest="subcommand")

    # harvest
    p_harvest = subparsers.add_parser("harvest", help="Harvest zero-token signals")
    p_harvest.add_argument("repo", nargs="?", default=".", help="Target repository")
    p_harvest.add_argument("--project", help="Target project path")
    p_harvest.add_argument("--mode", choices=["auto", "project", "factory"], default="auto", help="Operational mode")
    p_harvest.add_argument("--all-projects", action="store_true", help="Harvest all projects")
    p_harvest.add_argument("--current", help="Force harvest current session")
    p_harvest.add_argument("--format", choices=["toon", "json", "human"], default="toon", help="Output format")
    p_harvest.add_argument("--reprocess", action="store_true", help="Reprocess historical sessions")
    p_harvest.add_argument("--output", help="Output file path")
    p_harvest.add_argument("--max-sessions", type=int, default=50, help="Max sessions to analyze")
    p_harvest.add_argument(
        "--since-hours",
        type=int,
        default=None,
        help="Only inspect session transcripts modified within the last N hours",
    )

    # candidates
    p_cand = subparsers.add_parser("candidates", help="Manage candidate pool")
    p_cand.add_argument("action", nargs="?", default="list", choices=["list", "record"], help="Action")
    p_cand.add_argument("--rule", help="Candidate rule text")
    p_cand.add_argument("--role", default="coder", help="Target role")
    p_cand.add_argument("--project", help="Source project path")
    p_cand.add_argument("--format", choices=["toon", "json", "human"], default="toon", help="Output format")

    # promote
    p_promote = subparsers.add_parser("promote", help="Promote candidate rule")
    p_promote.add_argument("--candidate", required=True, help="Candidate ID")
    p_promote.add_argument("--plugin-root", help="Plugin root path")
    p_promote.add_argument("--force", action="store_true", help="Force promotion")

    # mark-processed
    p_mark = subparsers.add_parser("mark-processed", help="Mark session as processed")
    p_mark.add_argument("--session", action="append", help="Session ID(s)")
    p_mark.add_argument("--project", help="Project path")
    p_mark.add_argument("--mode", choices=["project", "factory"], default="project", help="Watermark mode")
    p_mark.add_argument("--clear-factory-inbox", action="store_true", help="Clear factory inbox")

    # check-budget
    p_budget = subparsers.add_parser("check-budget", help="Check physical line budget")
    p_budget.add_argument("path", help="Path to rubric markdown file or directory")
    p_budget.add_argument("--max-lines", type=int, help="Optional line limit override")

    # sessions
    p_sess = subparsers.add_parser("sessions", help="Mine Antigravity sessions")
    p_sess.add_argument("repo", nargs="?", default=".", help="Target repository")
    p_sess.add_argument("--by-project", action="store_true", help="Group by project")
    p_sess.add_argument("--brain-roots", nargs="+", help="Brain root paths")
    p_sess.add_argument("--format", choices=["human", "toon"], default="human", help="Output format")
    p_sess.add_argument("--output", help="Output file")

    # intents
    p_intents = subparsers.add_parser("intents", help="Mine architectural intents")
    p_intents.add_argument("repo", nargs="?", default=".", help="Target repository")
    p_intents.add_argument("--brain-roots", nargs="+", help="Brain root paths")
    p_intents.add_argument("--format", choices=["human", "toon"], default="human", help="Output format")
    p_intents.add_argument("--output", help="Output file")

    # inbox
    p_inbox = subparsers.add_parser("inbox", help="Inspect, prune, or clear factory inbox")
    p_inbox.add_argument("action", nargs="?", default="list", choices=["list", "prune", "clear"], help="Action")
    p_inbox.add_argument("--pending-only", action="store_true", help="List only unresolved signals")
    p_inbox.add_argument("--dry-run", action="store_true", help="Preview prune counts without modifying disk")
    p_inbox.add_argument("--no-drop-exit-zero", action="store_true", help="Keep exit=0 harness signals")
    p_inbox.add_argument("--no-drop-benign-tools", action="store_true", help="Keep benign tool signals")
    p_inbox.add_argument("--resolved-only", action="store_true", help="Only prune already-resolved signals")
    p_inbox.add_argument("--max-age-days", type=int, default=None, help="Drop signals older than N days")
    p_inbox.add_argument("--project", default=None, help="Scope prune to project path")
    p_inbox.add_argument("--format", choices=["human", "json"], default="human", help="Output format")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 0
    handler = DISPATCH_MAP.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
