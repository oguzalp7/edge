"""
Track execution runners (core, ui, tests, clones, types, all) for edge-audit CLI.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from tools.audit.reporters import ConsoleReporter, JsonReporter, MarkdownReporter, ToonReporter
from tools.audit.scanner import FileScanner
from tools.audit.ts_discipline import (
    TsDisciplineAuditor,
    format_human as ts_format_human,
    format_json as ts_format_json,
    format_markdown as ts_format_markdown,
    format_toon as ts_format_toon,
)
from tools.common.toon import encode
from tools.test_audit.cli import (
    TestFileAuditor,
    format_human as test_format_human,
    format_json as test_format_json,
    format_markdown as test_format_markdown,
    format_toon as test_format_toon,
)
from tools.ui_audit.cli import run_ui_audit
from tools.ui_audit.reporter import UIConsoleReporter, UIJsonReporter, UIMarkdownReporter, UIToonReporter


def _pair_to_dict(p: Any) -> Dict[str, Any]:
    return {
        "score": p.score,
        "language": p.language,
        "left": {"file": p.left.file_path, "symbol": p.left.symbol, "lines": f"{p.left.start_line}-{p.left.end_line}"},
        "right": {"file": p.right.file_path, "symbol": p.right.symbol, "lines": f"{p.right.start_line}-{p.right.end_line}"},
    }


def _cluster_to_dict(c: Any) -> Dict[str, Any]:
    return {
        "cluster_id": c.cluster_id,
        "distinct_files": c.distinct_files,
        "max_score": c.max_score,
        "members": [f"{m.file_path}:{m.symbol}" for m in c.members],
    }


def run_clones_track(target_path: Path, output_format: str = "human") -> str:
    from tools.audit.dryer import TREE_SITTER_AVAILABLE, DryerScanner
    if not TREE_SITTER_AVAILABLE:
        return "⚠️ tree-sitter or tree-sitter-language-pack not found. Clones track unavailable."
    scanner = DryerScanner()
    pairs = scanner.scan_path(target_path)
    clusters = scanner.cluster_clones(pairs)

    if output_format == "json":
        return json.dumps({"clones": {
            "total_pairs": len(pairs),
            "total_clusters": len(clusters),
            "pairs": [_pair_to_dict(p) for p in pairs],
            "clusters": [_cluster_to_dict(c) for c in clusters],
        }}, indent=2)

    is_md = output_format == "markdown"
    out = (
        ["# 👯 DRYER Structural AST Clones Report", f"> **Target:** `{target_path}` | **Clone Pairs:** {len(pairs)} | **Clusters:** {len(clusters)}\n"]
        if is_md else ["=" * 80, f"👯  DRYER STRUCTURAL AST CLONES ({len(pairs)} pairs, {len(clusters)} clusters)", "=" * 80]
    )
    for c in clusters:
        if is_md:
            out.append(f"### Cluster `{c.cluster_id}` (Max Similarity: {c.max_score * 100:.1f}%)")
            out.append(f"- **Files:** {', '.join(c.distinct_files)}")
            out.extend(f"  - `{Path(m.file_path).name}:{m.symbol}` (lines {m.start_line}-{m.end_line})" for m in c.members)
        else:
            out.append(f"\n📦 Cluster {c.cluster_id} (Similarity: {c.max_score * 100:.1f}%)")
            out.append(f"   Files: {', '.join(c.distinct_files)}")
            out.extend(f"   - {Path(m.file_path).name}::{m.symbol} (lines {m.start_line}-{m.end_line})" for m in c.members)
    return "\n".join(out)


def run_core_track(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    summary = FileScanner().scan(target_path)
    renderers = {"toon": ToonReporter.render, "markdown": MarkdownReporter.render, "json": JsonReporter.render}
    return renderers.get(output_format, ConsoleReporter.render)(summary, top_n=top)


def run_ui_track(target_path: Path, output_format: str = "table") -> str:
    summary = run_ui_audit(target_path)
    renderers = {"markdown": UIMarkdownReporter.render, "toon": UIToonReporter.render, "json": UIJsonReporter.render}
    return renderers.get(output_format, UIConsoleReporter.render)(summary)


def run_tests_track(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    auditor = TestFileAuditor(target_path)
    test_target = (target_path / "tests") if (target_path.is_dir() and (target_path / "tests").exists() and not target_path.name.startswith("test")) else target_path
    results = sorted((auditor.analyze_file(f) for f in auditor.get_test_files(test_target)), key=lambda x: x["score"])
    renderers = {"toon": test_format_toon, "markdown": test_format_markdown, "json": test_format_json}
    return renderers.get(output_format, test_format_human)(results, top=top)


def run_types_track(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    summary = TsDisciplineAuditor(target_path).scan(target_path)
    renderers = {"toon": ts_format_toon, "markdown": ts_format_markdown, "json": ts_format_json}
    return renderers.get(output_format, ts_format_human)(summary, top=top)


def run_all_tracks(target_path: Path, output_format: str = "human", top: int = 15) -> str:
    core_summary = FileScanner().scan(target_path)
    ui_summary = run_ui_audit(target_path)
    test_auditor = TestFileAuditor(target_path)
    test_target = (target_path / "tests") if (target_path.is_dir() and (target_path / "tests").exists() and not target_path.name.startswith("test")) else target_path
    test_results = sorted((test_auditor.analyze_file(f) for f in test_auditor.get_test_files(test_target)), key=lambda x: x["score"])
    types_summary = TsDisciplineAuditor(target_path).scan(target_path)

    if output_format == "toon":
        return encode({"edge_unified_audit": {
            "core": {"health_score": core_summary.overall_health_score, "sloc": core_summary.total_sloc, "critical": core_summary.critical_hotspots, "attention": core_summary.attention_files},
            "ui": {"health_score": round(ui_summary.health_score, 1), "files": ui_summary.total_tsx_files, "orphans": ui_summary.total_orphans, "clusters": len(ui_summary.clusters)},
            "tests": {"total_files": len(test_results), "average_score": round(sum(r["score"] for r in test_results) / len(test_results)) if test_results else 0, "toxic_count": sum(1 for r in test_results if r["score"] < 50)},
            "types": {"health_score": types_summary.overall_score, "band": types_summary.overall_band, "files": types_summary.files_analyzed, "porous": types_summary.porous_count},
        }})
    if output_format == "json":
        return json.dumps({"unified_audit": {
            "target_path": str(target_path),
            "core": json.loads(JsonReporter.render(core_summary, top_n=top)),
            "ui": json.loads(UIJsonReporter.render(ui_summary)),
            "tests": json.loads(test_format_json(test_results, top=top)),
            "types": json.loads(ts_format_json(types_summary, top=top)),
        }}, indent=2)
    if output_format == "markdown":
        return "\n".join([
            "# 🌐 Edge Unified Codebase Audit Report",
            f"> **Target Scope:** `{target_path}`  ",
            f"> **Core Health:** `{core_summary.overall_health_score}/100` | **UI Health:** `{ui_summary.health_score:.1f}/100` | **Tests Analyzed:** `{len(test_results)}` | Types Health: `{types_summary.overall_score}/100 ({types_summary.overall_band})`",
            "\n---\n", MarkdownReporter.render(core_summary, top_n=top),
            "\n---\n", UIMarkdownReporter.render(ui_summary),
            "\n---\n", test_format_markdown(test_results, top=top),
            "\n---\n", ts_format_markdown(types_summary, top=top),
        ])
    return "\n".join([
        "=" * 80, "🌐  EDGE UNIFIED CODEBASE AUDIT (ALL TRACKS: CORE, UI, TESTS, TYPES)", "=" * 80,
        "\n--- [TRACK 1/4] CORE ARCHITECTURAL HEALTH & BLOAT ---", ConsoleReporter.render(core_summary, top_n=top),
        "\n--- [TRACK 2/4] UI COMPONENT & JSX DUPLICATION ---", UIConsoleReporter.render(ui_summary),
        "\n--- [TRACK 3/4] UNIT TEST PURITY & ISOLATION ---", test_format_human(test_results, top=top),
        "\n--- [TRACK 4/4] TYPESCRIPT TYPE-SYSTEM DISCIPLINE ---", ts_format_human(types_summary, top=top),
    ])
