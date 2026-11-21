#!/usr/bin/env python3
"""
edge-audit: Unified Deterministic Codebase Health, UI Architecture, and Test Isolation Auditor
Supports specialized single tracks (--track [core|ui|tests]) and unified whole-repo analysis (--track all).
"""

import sys
import os
import argparse
import json
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path
from tools.common.toon import encode
from tools.audit.scanner import FileScanner
from tools.audit.reporters import ConsoleReporter, ToonReporter, MarkdownReporter, JsonReporter
from tools.ui_audit.cli import run_ui_audit
from tools.ui_audit.reporter import UIConsoleReporter, UIMarkdownReporter, UIToonReporter, UIJsonReporter
from tools.test_audit.cli import TestFileAuditor, format_human as test_format_human, format_markdown as test_format_markdown, format_toon as test_format_toon, format_json as test_format_json
from tools.audit.ts_discipline import (
    TsDisciplineAuditor,
    format_human as ts_format_human,
    format_markdown as ts_format_markdown,
    format_toon as ts_format_toon,
    format_json as ts_format_json,
)

setup_utf8_console()


def run_clones_track(target_path: Path, output_format: str = "human") -> str:
    from tools.audit.dryer import DryerScanner, TREE_SITTER_AVAILABLE
    if not TREE_SITTER_AVAILABLE:
        return "⚠️ tree-sitter or tree-sitter-language-pack not found. Clones track unavailable."
    scanner = DryerScanner()
    pairs = scanner.scan_path(target_path)
    clusters = scanner.cluster_clones(pairs)

    if output_format == "json":
        data = {
            "clones": {
                "total_pairs": len(pairs),
                "total_clusters": len(clusters),
                "pairs": [
                    {
                        "score": p.score,
                        "language": p.language,
                        "left": {
                            "file": p.left.file_path,
                            "symbol": p.left.symbol,
                            "lines": f"{p.left.start_line}-{p.left.end_line}",
                        },
                        "right": {
                            "file": p.right.file_path,
                            "symbol": p.right.symbol,
                            "lines": f"{p.right.start_line}-{p.right.end_line}",
                        }
                    }
                    for p in pairs
                ],
                "clusters": [
                    {
                        "cluster_id": c.cluster_id,
                        "distinct_files": c.distinct_files,
                        "max_score": c.max_score,
                        "members": [f"{m.file_path}:{m.symbol}" for m in c.members]
                    }
                    for c in clusters
                ]
            }
        }
        return json.dumps(data, indent=2)
    elif output_format == "markdown":
        out = ["# 👯 DRYER Structural AST Clones Report", f"> **Target:** `{target_path}` | **Clone Pairs:** {len(pairs)} | **Clusters:** {len(clusters)}\n"]
        for c in clusters:
            out.append(f"### Cluster `{c.cluster_id}` (Max Similarity: {c.max_score * 100:.1f}%)")
            out.append(f"- **Files:** {', '.join(c.distinct_files)}")
            for m in c.members:
                out.append(f"  - `{Path(m.file_path).name}:{m.symbol}` (lines {m.start_line}-{m.end_line})")
        return "\n".join(out)
    else:
        out = [
            "=" * 80,
            f"👯  DRYER STRUCTURAL AST CLONES ({len(pairs)} pairs, {len(clusters)} clusters)",
            "=" * 80,
        ]
        for c in clusters:
            out.append(f"\n📦 Cluster {c.cluster_id} (Similarity: {c.max_score * 100:.1f}%)")
            out.append(f"   Files: {', '.join(c.distinct_files)}")
            for m in c.members:
                out.append(f"   - {Path(m.file_path).name}::{m.symbol} (lines {m.start_line}-{m.end_line})")
        return "\n".join(out)


def run_core_track(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    scanner = FileScanner()
    summary = scanner.scan(target_path)
    if output_format == "toon":
        return ToonReporter.render(summary, top_n=top)
    elif output_format == "markdown":
        return MarkdownReporter.render(summary, top_n=top)
    elif output_format == "json":
        return JsonReporter.render(summary, top_n=top)
    else:
        return ConsoleReporter.render(summary, top_n=top)


def run_ui_track(target_path: Path, output_format: str = "table") -> str:
    summary = run_ui_audit(target_path)
    if output_format == "markdown":
        return UIMarkdownReporter.render(summary)
    elif output_format == "toon":
        return UIToonReporter.render(summary)
    elif output_format == "json":
        return UIJsonReporter.render(summary)
    else:
        return UIConsoleReporter.render(summary)


def run_tests_track(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    auditor = TestFileAuditor(target_path)
    test_target = target_path
    if target_path.is_dir() and (target_path / "tests").exists() and not target_path.name.startswith("test"):
        test_target = target_path / "tests"
    files = auditor.get_test_files(test_target)
    results = [auditor.analyze_file(f) for f in files]
    results.sort(key=lambda x: x["score"])

    if output_format == "toon":
        return test_format_toon(results, top=top)
    elif output_format == "markdown":
        return test_format_markdown(results, top=top)
    elif output_format == "json":
        return test_format_json(results, top=top)
    else:
        return test_format_human(results, top=top)


def run_types_track(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    auditor = TsDisciplineAuditor(target_path)
    summary = auditor.scan(target_path)
    if output_format == "toon":
        return ts_format_toon(summary, top=top)
    elif output_format == "markdown":
        return ts_format_markdown(summary, top=top)
    elif output_format == "json":
        return ts_format_json(summary, top=top)
    else:
        return ts_format_human(summary, top=top)


def run_all_tracks(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    scanner = FileScanner()
    core_summary = scanner.scan(target_path)

    ui_summary = run_ui_audit(target_path)

    auditor = TestFileAuditor(target_path)
    test_target = target_path
    if target_path.is_dir() and (target_path / "tests").exists() and not target_path.name.startswith("test"):
        test_target = target_path / "tests"
    test_files = auditor.get_test_files(test_target)
    test_results = [auditor.analyze_file(f) for f in test_files]
    test_results.sort(key=lambda x: x["score"])

    types_summary = TsDisciplineAuditor(target_path).scan(target_path)

    if output_format == "toon":
        data = {
            "edge_unified_audit": {
                "core": {
                    "health_score": core_summary.overall_health_score,
                    "sloc": core_summary.total_sloc,
                    "critical": core_summary.critical_hotspots,
                    "attention": core_summary.attention_files,
                },
                "ui": {
                    "health_score": round(ui_summary.health_score, 1),
                    "files": ui_summary.total_tsx_files,
                    "orphans": ui_summary.total_orphans,
                    "clusters": len(ui_summary.clusters),
                },
                "tests": {
                    "total_files": len(test_results),
                    "average_score": round(sum(r["score"] for r in test_results) / len(test_results)) if test_results else 0,
                    "toxic_count": sum(1 for r in test_results if r["score"] < 50),
                },
                "types": {
                    "health_score": types_summary.overall_score,
                    "band": types_summary.overall_band,
                    "files": types_summary.files_analyzed,
                    "porous": types_summary.porous_count,
                },
            }
        }
        return encode(data)

    elif output_format == "markdown":
        out = []
        out.append("# 🌐 Edge Unified Codebase Audit Report")
        out.append(f"> **Target Scope:** `{target_path}`  ")
        out.append(
            f"> **Core Health:** `{core_summary.overall_health_score}/100` | "
            f"**UI Health:** `{ui_summary.health_score:.1f}/100` | "
            f"**Tests Analyzed:** `{len(test_results)}` | "
            f"Types Health: `{types_summary.overall_score}/100 ({types_summary.overall_band})`"
        )
        out.append("\n---\n")
        out.append(MarkdownReporter.render(core_summary, top_n=top))
        out.append("\n---\n")
        out.append(UIMarkdownReporter.render(ui_summary))
        out.append("\n---\n")
        out.append(test_format_markdown(test_results, top=top))
        out.append("\n---\n")
        out.append(ts_format_markdown(types_summary, top=top))
        return "\n".join(out)

    elif output_format == "json":
        data = {
            "unified_audit": {
                "target_path": str(target_path),
                "core": json.loads(JsonReporter.render(core_summary, top_n=top)),
                "ui": json.loads(UIJsonReporter.render(ui_summary)),
                "tests": json.loads(test_format_json(test_results, top=top)),
                "types": json.loads(ts_format_json(types_summary, top=top)),
            }
        }
        return json.dumps(data, indent=2)

    else:
        out = []
        out.append("=" * 80)
        out.append("🌐  EDGE UNIFIED CODEBASE AUDIT (ALL TRACKS: CORE, UI, TESTS, TYPES)")
        out.append("=" * 80)
        out.append("\n--- [TRACK 1/4] CORE ARCHITECTURAL HEALTH & BLOAT ---")
        out.append(ConsoleReporter.render(core_summary, top_n=top))
        out.append("\n--- [TRACK 2/4] UI COMPONENT & JSX DUPLICATION ---")
        out.append(UIConsoleReporter.render(ui_summary))
        out.append("\n--- [TRACK 3/4] UNIT TEST PURITY & ISOLATION ---")
        out.append(test_format_human(test_results, top=top))
        out.append("\n--- [TRACK 4/4] TYPESCRIPT TYPE-SYSTEM DISCIPLINE ---")
        out.append(ts_format_human(types_summary, top=top))
        return "\n".join(out)


def main():
    parser = argparse.ArgumentParser(
        description="edge-audit: Deterministic Codebase Health & Bloat Assessment Tool"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Target directory to audit (e.g. /home/oguz/my-project or .)"
    )
    parser.add_argument(
        "--track",
        choices=["core", "ui", "tests", "clones", "dead-code", "types", "all"],
        default="core",
        help="Audit track to execute: 'core' (default), 'ui', 'tests', 'clones', 'dead-code', 'types', or 'all' (unified)"
    )
    parser.add_argument(
        "--format",
        choices=["human", "table", "markdown", "toon", "json"],
        default="human",
        help="Output format: 'human'/'table' (console), 'markdown', 'toon', or 'json'"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Maximum number of hotspots to display (default: 15)"
    )
    parser.add_argument(
        "-o", "--output", "--out",
        dest="output",
        type=str,
        default=None,
        help="Optional file path to write report to (e.g. report.md)"
    )

    args = parser.parse_args()

    target_path = normalize_target_path(args.target)
    if not target_path.exists():
        print(f"Error: Target directory not found: {target_path}", file=sys.stderr)
        sys.exit(1)

    fmt = args.format
    if fmt == "table":
        fmt = "human"

    try:
        if args.track == "ui":
            output = run_ui_track(target_path, fmt)
        elif args.track == "tests":
            output = run_tests_track(target_path, fmt, top=args.top)
        elif args.track == "clones":
            output = run_clones_track(target_path, fmt)
        elif args.track == "dead-code":
            from tools.audit.dead_code import run_dead_code_scan, format_dead_code_report
            report = run_dead_code_scan(target_path)
            output = format_dead_code_report(report, fmt)
        elif args.track == "types":
            output = run_types_track(target_path, fmt, top=args.top)
        elif args.track == "all":
            output = run_all_tracks(target_path, fmt, top=args.top)
        else:
            output = run_core_track(target_path, fmt, top=args.top)
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
