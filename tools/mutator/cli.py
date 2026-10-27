"""
CLI Entry Point for Edge Mutator: Differential Core Mutation Testing Gate.
"""

import sys
import argparse
import shlex
from pathlib import Path

from .sites import discover_mutation_sites
from .runner import run_mutation_suite, enforce_core_scope


def main():
    parser = argparse.ArgumentParser(
        description="edge-mutator: Alias-Aware Differential Core Mutation Gate"
    )
    parser.add_argument(
        "--target",
        required=True,
        help="Target source file to mutate (e.g. src/core/pricing.ts)"
    )
    parser.add_argument(
        "--test-cmd",
        default="pytest",
        help="Command to run tests (e.g. 'pytest tests/test_calc.py' or 'npm run test:unit')"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=80.0,
        help="Minimum mutation score percentage (default: 80.0)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Timeout in seconds per test run (default: 15.0)"
    )
    parser.add_argument(
        "--scan-only",
        action="store_true",
        help="Discover and display mutation sites without running tests"
    )
    parser.add_argument(
        "--allow-non-core",
        action="store_true",
        help="Allow running mutation tests on files outside core scope"
    )

    args = parser.parse_args()

    target_path = Path(args.target).resolve()
    if not target_path.exists():
        print(f"Error: Target file not found: {args.target}", file=sys.stderr)
        sys.exit(1)

    repo_root = Path.cwd().resolve()
    try:
        rel_path = str(target_path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        rel_path = target_path.name

    try:
        enforce_core_scope(rel_path, allow_non_core=args.allow_non_core)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.scan_only:
        sites = discover_mutation_sites(target_path, rel_path)
        print(f"Discovered {len(sites)} mutation sites in {rel_path}:")
        for s in sites:
            print(f"  Line {s.line:3d} [{s.category:14s}] {s.original} -> {s.mutant} ({s.function_name})")
        sys.exit(0)

    test_cmd = shlex.split(args.test_cmd)
    summary = run_mutation_suite(
        repo_root=repo_root,
        target_file=target_path,
        test_cmd=test_cmd,
        timeout_sec=args.timeout,
        allow_non_core=args.allow_non_core
    )

    print("=" * 70)
    print("🧬  EDGE MUTATOR REPORT")
    print(f"   Target: {rel_path}")
    print(f"   Total Mutants: {summary.total} | Killed: {summary.killed} | Survived: {summary.survived} | Timed Out: {summary.timed_out}")
    print(f"   Mutation Score: {summary.score_pct:.1f}% (Threshold: {args.threshold:.1f}%)")
    print("=" * 70)

    for o in summary.outcomes:
        icon = "✔" if o.status == "KILLED" else "✖"
        print(f"   {icon} [{o.status:9s}] Line {o.site.line:3d}: {o.site.original} -> {o.site.mutant} in {o.site.function_name} ({o.duration_sec:.2f}s)")

    if summary.score_pct < args.threshold:
        print(f"\n❌ Mutation score {summary.score_pct:.1f}% is below threshold {args.threshold:.1f}%!", file=sys.stderr)
        sys.exit(1)

    print("\n✅ Mutation testing passed all score gates.")
    sys.exit(0)


if __name__ == "__main__":
    main()
