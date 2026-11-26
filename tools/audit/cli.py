#!/usr/bin/env python3
"""
edge-audit: Unified Deterministic Codebase Health, UI Architecture, and Test Isolation Auditor
"""

import argparse
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.audit.cli_tracks import (
    run_all_tracks,
    run_clones_track,
    run_core_track,
    run_tests_track,
    run_types_track,
    run_ui_track,
)
from tools.common import normalize_target_path, setup_utf8_console

setup_utf8_console()


def _dispatch_track(track: str, target_path: Path, fmt: str, top: int) -> str:
    if track == "dead-code":
        from tools.audit.dead_code import format_dead_code_report, run_dead_code_scan
        return format_dead_code_report(run_dead_code_scan(target_path), fmt)
    if track == "ui":
        return run_ui_track(target_path, fmt)
    if track == "clones":
        return run_clones_track(target_path, fmt)
    handlers = {"tests": run_tests_track, "types": run_types_track, "all": run_all_tracks, "core": run_core_track}
    return handlers[track](target_path, fmt, top=top)


def main() -> None:
    parser = argparse.ArgumentParser(description="edge-audit: Deterministic Codebase Health & Bloat Assessment Tool")
    parser.add_argument("target", nargs="?", default=".", help="Target directory to audit")
    parser.add_argument("--track", choices=["core", "ui", "tests", "clones", "dead-code", "types", "all"], default="core")
    parser.add_argument("--format", choices=["human", "table", "markdown", "toon", "json"], default="human")
    parser.add_argument("--top", type=int, default=15, help="Maximum number of hotspots to display")
    parser.add_argument("-o", "--output", "--out", dest="output", type=str, default=None, help="Optional output file")

    args = parser.parse_args()
    target_path = normalize_target_path(args.target)
    if not target_path.exists():
        print(f"Error: Target directory not found: {target_path}", file=sys.stderr)
        sys.exit(1)

    fmt = "human" if args.format == "table" else args.format
    try:
        output = _dispatch_track(args.track, target_path, fmt, args.top)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(output)
    if args.output:
        out_file = Path(args.output)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(output, encoding="utf-8")
        print(f"\n📁 Report successfully saved to: {out_file}")


if __name__ == "__main__":
    main()
