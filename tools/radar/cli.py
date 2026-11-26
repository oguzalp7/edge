#!/usr/bin/env python3
"""
Edge Radar CLI Driver: Scoped Pattern Observation & Idempotent Debt Ledger
"""

import argparse
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console

setup_utf8_console()

from tools.radar.cli_export import _derive_item_slug, _derive_metric_targets, cmd_export_tasks
from tools.radar.cli_ops import cmd_report, cmd_scan, cmd_status


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge Radar: Scoped Pattern Observation & Idempotent Debt Ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_scan = subparsers.add_parser("scan", help="Scan repository and update debt ledger")
    p_scan.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_scan.add_argument("--mode", choices=["churn", "pr", "all"], default="churn", help="Scope mode: churn (hot files), pr (diff), all (full repo)")
    p_scan.add_argument("--since", default="14.days", help="Git churn time window (default: 14.days)")
    p_scan.add_argument("--max-churn", type=int, default=25, help="Max churn files to scan (default: 25)")
    p_scan.add_argument("--base", default="main", help="Base ref for PR mode (default: main)")
    p_scan.add_argument("--track", choices=["all", "ui", "core"], default="all", help="Channel track to scan")
    p_scan.set_defaults(func=cmd_scan)

    p_status = subparsers.add_parser("status", help="Show current health board and open findings")
    p_status.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_status.add_argument("--format", choices=["human", "toon", "json"], default="human", help="Output format")
    p_status.set_defaults(func=cmd_status)

    p_report = subparsers.add_parser("report", help="Generate refactoring proposal report")
    p_report.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_report.add_argument("--top", type=int, default=15, help="Max items per track")
    p_report.add_argument("--format", choices=["markdown", "toon"], default="markdown", help="Report format")
    p_report.add_argument("--out", "-o", default=None, help="Output markdown or toon file path")
    p_report.set_defaults(func=cmd_report)

    p_export = subparsers.add_parser("export-tasks", help="Convert open ledger items into refactor tickets")
    p_export.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_export.add_argument("--track", choices=["all", "core", "ui"], default="all", help="Track filter")
    p_export.add_argument("--top", type=int, default=10, help="Max open items to export")
    p_export.add_argument("--parent-issue", type=int, default=None, help="Parent tracker issue number to link exported sub-issues")
    p_export.add_argument("--offline", action="store_true", help="Use local tracker backend")
    export_sync = p_export.add_mutually_exclusive_group()
    export_sync.add_argument("--sync-tasks", dest="sync_tasks", action="store_true", default=None, help="Sync exported tickets to tracker (default)")
    export_sync.add_argument("--no-sync-tasks", dest="sync_tasks", action="store_false", default=None, help="Skip tracker issue creation")
    p_export.set_defaults(func=cmd_export_tasks)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
