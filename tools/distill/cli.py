#!/usr/bin/env python3
"""
CLI Driver for edge-distill v2: Zero-Token Harvester, State Watermark & Cross-Project Candidate Engine.
"""

import sys
import os
import argparse
import json
from pathlib import Path
from typing import Optional, List

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
    DistillStateManager,
    LexicalStackGate,
    CandidatePool,
    check_line_budget,
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


def cmd_harvest(args: argparse.Namespace) -> int:
    repo_raw = getattr(args, "project", None) or getattr(args, "repo", ".")
    target_repo = normalize_target_path(repo_raw)
    harvester = TranscriptGraphHarvester(repo_path=target_repo)
    digest = harvester.harvest(
        project_path=target_repo,
        reprocess=getattr(args, "reprocess", False),
        current_session_id=getattr(args, "current", None),
        max_sessions=getattr(args, "max_sessions", 50),
    )
    fmt = getattr(args, "format", "toon")
    if fmt == "json":
        output_str = json.dumps(digest.to_dict(), indent=2)
    elif fmt == "toon":
        output_str = digest.to_toon()
    else:
        output_str = f"FrictionDigest for {digest.project_name}: {len(digest.sessions_analyzed)} sessions, {len(digest.tool_frictions)} frictions, {len(digest.station_escapes)} escapes"

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
    pool.promote_candidate(candidate_id=cid, force=force)
    return 0


def cmd_mark_processed(args: argparse.Namespace) -> int:
    sid = getattr(args, "session", None)
    if not sid:
        print("Error: --session is required", file=sys.stderr)
        return 1
    proj = getattr(args, "project", None)
    manager = DistillStateManager()
    manager.mark_session_processed(
        session_id=sid,
        project_path=str(normalize_target_path(proj)) if proj else None,
    )
    print(f"Marked session {sid} as processed")
    return 0


def cmd_check_budget(args: argparse.Namespace) -> int:
    raw_path = getattr(args, "path", None)
    if not raw_path:
        print("Error: path is required", file=sys.stderr)
        return 1
    p = Path(raw_path).resolve()
    max_lines = getattr(args, "max_lines", None)
    ok, count, limit = check_line_budget(p, max_lines=max_lines)
    if ok:
        print(f"PASS: {p.name} has {count} lines (budget <= {limit})")
        return 0
    else:
        print(f"FAIL: {p.name} has {count} lines (budget <= {limit} exceeded)", file=sys.stderr)
        return 1


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


DISPATCH_MAP = {
    "harvest": cmd_harvest,
    "candidates": cmd_candidates,
    "promote": cmd_promote,
    "mark-processed": cmd_mark_processed,
    "check-budget": cmd_check_budget,
    "sessions": cmd_sessions,
    "intents": cmd_intents,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="edge-distill", description="Edge Distill v2")
    subparsers = parser.add_subparsers(dest="subcommand")

    # harvest
    p_harvest = subparsers.add_parser("harvest", help="Harvest zero-token signals")
    p_harvest.add_argument("repo", nargs="?", default=".", help="Target repository")
    p_harvest.add_argument("--project", help="Target project path")
    p_harvest.add_argument("--all-projects", action="store_true", help="Harvest all projects")
    p_harvest.add_argument("--current", help="Force harvest current session")
    p_harvest.add_argument("--format", choices=["toon", "json", "human"], default="toon", help="Output format")
    p_harvest.add_argument("--reprocess", action="store_true", help="Reprocess historical sessions")
    p_harvest.add_argument("--output", help="Output file path")
    p_harvest.add_argument("--max-sessions", type=int, default=50, help="Max sessions to analyze")

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
    p_mark.add_argument("--session", required=True, help="Session ID")
    p_mark.add_argument("--project", help="Project path")

    # check-budget
    p_budget = subparsers.add_parser("check-budget", help="Check physical line budget")
    p_budget.add_argument("path", help="Path to rubric markdown file")
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
