"""
UI Audit CLI Driver
Provides deterministic static analysis for Next.js/React TSX components,
orphan component detection, dead imports, and structural Tailwind JSX clustering.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path
setup_utf8_console()

try:
    from .models import UIAuditSummary, JSXPattern
    from .graph_builder import GraphBuilder
    from .jsx_fingerprint import JSXFingerprinter
    from .cluster_engine import ClusterEngine
    from .reporter import UIMarkdownReporter, UIToonReporter, UIConsoleReporter
except ImportError:
    from tools.ui_audit.models import UIAuditSummary, JSXPattern
    from tools.ui_audit.graph_builder import GraphBuilder
    from tools.ui_audit.jsx_fingerprint import JSXFingerprinter
    from tools.ui_audit.cluster_engine import ClusterEngine
    from tools.ui_audit.reporter import UIMarkdownReporter, UIToonReporter, UIConsoleReporter


def calculate_ui_health(
    total_files: int,
    orphan_count: int,
    dead_import_count: int,
    cluster_count: int,
    duplicate_instances: int
) -> float:
    """
    Calculate an objective UI health score between 0 and 100.
    Penalties:
      - 1.5 per orphan component (dead weight in codebase)
      - 0.5 per dead symbol import (litter/unused dependency)
      - 2.0 per duplicate structural cluster
      - 0.1 per duplicate instance
    """
    if total_files == 0:
        return 100.0

    score = 100.0
    score -= orphan_count * 1.5
    score -= dead_import_count * 0.5
    score -= cluster_count * 2.0
    score -= duplicate_instances * 0.1

    return max(15.0, min(100.0, score))


def run_ui_audit(target_path: Path, min_instances: int = 2) -> UIAuditSummary:
    """Run full UI audit across the target path."""
    # 1. Build component DAG
    graph_builder = GraphBuilder(target_path)
    nodes = graph_builder.build_graph()

    total_sloc = sum(node.sloc for node in nodes.values())
    app_routes = sum(1 for node in nodes.values() if node.is_app_route)
    components_count = sum(1 for node in nodes.values() if node.is_component)

    orphans = graph_builder.find_orphans()
    dead_imports = graph_builder.find_all_dead_imports()

    # 2. Fingerprint JSX across all scanned files
    fingerprinter = JSXFingerprinter()
    all_patterns: List[JSXPattern] = []

    for rel_path, node in nodes.items():
        patterns = fingerprinter.scan_file(node.file_path, node.rel_path)
        all_patterns.extend(patterns)

    # 3. Cluster duplicate patterns
    cluster_engine = ClusterEngine()
    clusters = cluster_engine.cluster_patterns(all_patterns, min_instances=min_instances)

    duplicate_instances = sum(c.count for c in clusters)

    health_score = calculate_ui_health(
        total_files=len(nodes),
        orphan_count=len(orphans),
        dead_import_count=len(dead_imports),
        cluster_count=len(clusters),
        duplicate_instances=duplicate_instances
    )

    return UIAuditSummary(
        target_path=str(target_path),
        total_tsx_files=len(nodes),
        total_sloc=total_sloc,
        app_routes_count=app_routes,
        components_count=components_count,
        orphan_components=orphans,
        dead_imports=dead_imports,
        clusters=clusters,
        health_score=health_score
    )


def main():
    # Ensure Windows console supports UTF-8
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="Deterministic UI Component & JSX Duplication Audit Tool")
    parser.add_argument("target", help="Path to project directory or src directory")
    parser.add_argument(
        "--format",
        choices=["table", "markdown", "toon"],
        default="table",
        help="Output format: table (default console), markdown (detailed RFC), toon (token-frugal agent format)"
    )
    parser.add_argument(
        "--min-instances",
        type=int,
        default=2,
        help="Minimum pattern instances required to form a duplicate cluster (default: 2)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional file path to write report output"
    )

    args = parser.parse_args()
    resolved_target = normalize_target_path(args.target)

    if not resolved_target.exists():
        print(f"Error: Target path does not exist: {args.target}", file=sys.stderr)
        sys.exit(1)

    summary = run_ui_audit(resolved_target, min_instances=args.min_instances)

    if args.format == "markdown":
        output = UIMarkdownReporter.render(summary)
    elif args.format == "toon":
        output = UIToonReporter.render(summary)
    else:
        output = UIConsoleReporter.render(summary)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"UI Audit report successfully written to: {out_path}")
    else:
        print(output)


if __name__ == "__main__":
    main()
