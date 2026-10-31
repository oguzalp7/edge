"""
Unified CLI entry point for Edge-GNHF (run, status, harvest).
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

_root_dir = Path(__file__).resolve().parent.parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from tools.gnhf import AfkMode, GnhfRunOptions, GnhfWorktreeStatus
from tools.gnhf.runner import execute_gnhf_run
from tools.gnhf.harvest import get_gnhf_status, harvest_worktree


def _add_run_subparser(subparsers: argparse._SubParsersAction) -> None:
    run_parser = subparsers.add_parser("run", help="Launch an autonomous overnight worktree run")
    run_parser.add_argument("repo", help="Target repository path")
    run_parser.add_argument("objective", help="Natural language instructions for the autonomous loop")
    run_parser.add_argument("--mode", choices=["strict", "yolo"], default="strict", help="Safety mode")
    run_parser.add_argument("--yolo", action="store_true", help="Shorthand alias for --mode yolo")
    run_parser.add_argument("--agent", default="agy", help="Underlying CLI agent")
    run_parser.add_argument("--model", default="gemini-3.8-flash-medium", help="Model name")
    run_parser.add_argument("--track", choices=["core", "ui", "all"], default="all", help="Quality gate track")
    run_parser.add_argument("--max-iterations", type=int, default=None, help="Maximum iteration count")
    run_parser.add_argument("--max-tokens", type=int, default=None, help="Maximum token cap")
    run_parser.add_argument("--stop-when", default=None, help="Stop condition text")
    run_parser.add_argument("--test-cmd", default=None, help="Custom test execution command")
    run_parser.add_argument("--dry-run", action="store_true", help="Print resolved command without executing")


def _add_status_subparser(subparsers: argparse._SubParsersAction) -> None:
    status_parser = subparsers.add_parser("status", help="Inspect active or completed GNHF worktrees")
    status_parser.add_argument("repo", help="Target repository path")


def _add_harvest_subparser(subparsers: argparse._SubParsersAction) -> None:
    harvest_parser = subparsers.add_parser("harvest", help="Audit, merge, and clean up completed GNHF worktrees")
    harvest_parser.add_argument("repo", help="Target repository path")
    harvest_parser.add_argument("branch", nargs="?", default=None, help="GNHF branch to harvest")
    harvest_parser.add_argument("--base", default="development", help="Target base branch in main repo")
    harvest_parser.add_argument("--track", choices=["core", "ui", "all"], default="all", help="Quality gate track")
    harvest_parser.add_argument("--merge", action="store_true", help="Execute fast-forward merge if gate passes")
    harvest_parser.add_argument("--cleanup", action="store_true", help="Remove worktree and delete branch after merge")
    harvest_parser.add_argument("--dry-run", action="store_true", help="Preview diff and gate results without mutating")


def parse_args(args: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="edge-gnhf", description="Edge-GNHF Autonomous Overnight Worktree Engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_run_subparser(subparsers)
    _add_status_subparser(subparsers)
    _add_harvest_subparser(subparsers)

    parsed = parser.parse_args(args if args is not None else sys.argv[1:])
    if getattr(parsed, "yolo", False):
        parsed.mode = "yolo"
    return parsed


def _format_status_report(statuses: List[GnhfWorktreeStatus], repo_path: Path) -> str:
    lines = [
        f"🌙 Edge-GNHF Active Worktrees Status: {repo_path}",
        "━" * 77,
    ]
    if not statuses:
        lines.append("No active or completed GNHF worktrees found.")
        lines.append("━" * 77)
        return "\n".join(lines)

    for st in statuses:
        lines.append(f"Worktree: {st.worktree_path}")
        lines.append(f"Branch:   {st.branch_name}")
        lines.append(f"Base:     {st.base_branch}")
        lines.append(f"Commits:  {st.commits_ahead} commits ahead of {st.base_branch}")
        lines.append(f"Last Run: {st.last_commit_timestamp} (\"{st.last_commit_subject}\")")
        lines.append("")
        if st.blockers:
            lines.append("⚠️ Triaged Blockers ([SKIPPED-NEEDS-HITL]):")
            for idx, blk in enumerate(st.blockers, 1):
                lines.append(f"  {idx}. {blk.file_path}: {blk.reason}")
        else:
            lines.append("Blockers: None recorded")
        lines.append("")
        lines.append(f"Status: READY FOR HARVEST (`edge-gnhf harvest {repo_path} {st.branch_name}`)")
        lines.append("━" * 77)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    repo_path = Path(args.repo)

    if args.command == "run":
        options = GnhfRunOptions(
            repo_path=repo_path,
            objective=args.objective,
            mode=AfkMode(args.mode),
            agent=args.agent,
            model=args.model,
            track=args.track,
            max_iterations=args.max_iterations,
            max_tokens=args.max_tokens,
            stop_when=args.stop_when,
            test_cmd=args.test_cmd,
            dry_run=args.dry_run,
        )
        return execute_gnhf_run(options)

    if args.command == "status":
        statuses = get_gnhf_status(repo_path)
        print(_format_status_report(statuses, repo_path))
        return 0

    if args.command == "harvest":
        res = harvest_worktree(
            repo_path=repo_path,
            branch_name=args.branch,
            base_branch=args.base,
            track=args.track,
            merge=args.merge,
            cleanup=args.cleanup,
            dry_run=args.dry_run,
        )
        if not res.gate_passed:
            print(f"❌ Quality Gate Failed (exit code {res.gate_exit_code}):")
            print(res.gate_output)
            return res.gate_exit_code
        print(f"✅ Quality Gate Passed for branch '{res.branch_name}'")
        if res.diff_stat:
            print(res.diff_stat)
        if res.merged:
            print(f"✅ Merged {res.branch_name} into {res.base_branch}")
        if res.cleaned_up:
            print(f"✅ Cleaned up worktree and deleted branch {res.branch_name}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
