"""
CLI Entry Point for Edge Mutator: Statement Deletion (SDL) & Differential Core Mutation Gate.
"""

import argparse
from pathlib import Path
import shlex
import sys
from typing import List, Optional, Set, Union

try:
    from .runner import (
        MutantOutcome,
        MutationSummary,
        RecursiveMutationSummary,
        discover_recursive_targets,
        enforce_core_scope,
        extract_git_diff_changed_lines,
        format_mutation_report,
        run_mutations,
        run_recursive_mutations,
    )
    from .sites import discover_mutation_sites
except (ImportError, ValueError):
    parent = Path(__file__).resolve().parent.parent.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    from tools.mutator.runner import (
        MutantOutcome,
        MutationSummary,
        RecursiveMutationSummary,
        discover_recursive_targets,
        enforce_core_scope,
        extract_git_diff_changed_lines,
        format_mutation_report,
        run_mutations,
        run_recursive_mutations,
    )
    from tools.mutator.sites import discover_mutation_sites


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="edge-mutator: SDL & Differential Core Mutation Gate")
    parser.add_argument("--repo", default=".", help="Repository root directory (default: cwd)")
    parser.add_argument("--target", default=None, help="Target source file or directory (optional with --recursive/--diff-only)")
    parser.add_argument("--test-cmd", default="pytest", help="Command to run tests (e.g. 'pytest' or 'npm run test:unit')")
    parser.add_argument("--threshold", type=float, default=80.0, help="Minimum mutation score percentage (default: 80.0)")
    parser.add_argument("--timeout", type=float, default=15.0, help="Timeout in seconds per test run (default: 15.0)")
    parser.add_argument("--scan-only", action="store_true", help="Discover mutation sites without executing tests")
    parser.add_argument("--allow-non-core", action="store_true", help="Allow running mutation tests outside core scope")
    parser.add_argument("--mode", choices=["all", "sdl", "operators"], default="all", help="Mutation mode (default: all)")
    parser.add_argument("--diff-only", action="store_true", help="Restrict mutations to git diff changed lines")
    parser.add_argument("--base", default=None, help="Git base ref for --diff-only (e.g. HEAD~1 or origin/development)")
    parser.add_argument("--recursive", action="store_true", help="Scan src/core/ (or --target dir) recursively")
    parser.add_argument("--format", choices=["toon", "json", "human"], default="toon", help="Report format (default: toon)")
    return parser


def _to_rel_posix(repo_root: Path, target_path: Path) -> str:
    try:
        return str(target_path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        return target_path.name


def _scan_single_file_summary(
    repo_root: Path,
    target_path: Path,
    mode: str,
    diff_only: bool,
    base_ref: Optional[str],
) -> MutationSummary:
    rel = _to_rel_posix(repo_root, target_path)
    lines: Optional[Set[int]] = None
    if diff_only:
        lines = extract_git_diff_changed_lines(repo_root, target_path, base_ref=base_ref)
    sites = [] if (lines is not None and not lines) else discover_mutation_sites(target_path, rel, covered_lines=lines, mode=mode)
    outcomes = [MutantOutcome(site=s, status="DISCOVERED", duration_sec=0.0) for s in sites]
    return MutationSummary(len(outcomes), 0, 0, 0, 100.0, outcomes, file_path=rel, mode=mode, passed=True)


def _run_scan_only(
    repo_root: Path,
    target_path: Optional[Path],
    is_recursive: bool,
    args: argparse.Namespace,
) -> Union[MutationSummary, RecursiveMutationSummary]:
    if not is_recursive and target_path is not None:
        return _scan_single_file_summary(repo_root, target_path, args.mode, args.diff_only, args.base)
    targets = discover_recursive_targets(
        repo_root, target_dir=target_path, diff_only=args.diff_only, base_ref=args.base, allow_non_core=args.allow_non_core
    )
    summaries = [_scan_single_file_summary(repo_root, tf, args.mode, args.diff_only, args.base) for tf in targets]
    total = sum(s.total for s in summaries)
    return RecursiveMutationSummary(len(summaries), total, 0, 0, 0, 100.0, True, summaries)


def _execute_cli_mode(
    repo_root: Path,
    target_path: Optional[Path],
    is_recursive: bool,
    args: argparse.Namespace,
) -> Union[MutationSummary, RecursiveMutationSummary]:
    if args.scan_only:
        return _run_scan_only(repo_root, target_path, is_recursive, args)
    test_cmd = shlex.split(args.test_cmd)
    if not is_recursive and target_path is not None:
        return run_mutations(
            repo_root=repo_root,
            target_file=target_path,
            test_cmd=test_cmd,
            timeout_sec=args.timeout,
            allow_non_core=args.allow_non_core,
            mode=args.mode,
            diff_only=args.diff_only,
            base_ref=args.base,
            threshold=args.threshold,
        )
    return run_recursive_mutations(
        repo_root=repo_root,
        test_cmd=test_cmd,
        target_dir=target_path,
        timeout_sec=args.timeout,
        allow_non_core=args.allow_non_core,
        mode=args.mode,
        diff_only=args.diff_only,
        base_ref=args.base,
        threshold=args.threshold,
    )


def _resolve_target_path(repo_root: Path, raw_target: Optional[str]) -> Optional[Path]:
    if not raw_target:
        return None
    cand = Path(raw_target)
    return (cand if cand.is_absolute() else (repo_root / cand)).resolve()


def _prepare_cli_context(
    args: argparse.Namespace,
) -> tuple[Optional[Path], Optional[Path], bool, int]:
    if not args.target and not args.recursive and not args.diff_only:
        print("Error: --target is required unless --recursive or --diff-only is specified.", file=sys.stderr)
        return None, None, False, 2
    repo_root = Path(args.repo).resolve()
    target_path = _resolve_target_path(repo_root, args.target)
    if args.target and (target_path is None or not target_path.exists()):
        print(f"Error: Target path not found: {args.target}", file=sys.stderr)
        return None, None, False, 1
    is_recursive = bool(args.recursive or (target_path is not None and target_path.is_dir()) or target_path is None)
    return repo_root, target_path, is_recursive, 0


def main(argv: Optional[List[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root, target_path, is_recursive, err_rc = _prepare_cli_context(args)
    if err_rc != 0 or repo_root is None:
        return err_rc

    try:
        if target_path is not None and not is_recursive:
            enforce_core_scope(_to_rel_posix(repo_root, target_path), allow_non_core=args.allow_non_core)
        summary = _execute_cli_mode(repo_root, target_path, is_recursive, args)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(format_mutation_report(summary, fmt=args.format, mode=args.mode))
    if args.scan_only:
        return 0
    return 0 if summary.score_pct >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
