"""UI Audit Reporters Facade: Markdown RFC, TOON, Console, and JSON formatters."""

import json
from typing import Any, Dict

from tools.common.toon import encode
from .models import UIAuditSummary
from .reporter_markdown import UIMarkdownReporter


def _build_toon_payload(summary: UIAuditSummary) -> Dict[str, Any]:
    clusters = [
        {"category": c.category, "primitive": c.suggested_primitive, "count": c.count, "saving": c.estimated_sloc_saving, "sample_files": "|".join(c.distinct_files[:3])}
        for c in summary.clusters[:8]
    ]
    return {
        "ui_audit": {
            "score": round(summary.health_score, 1), "files": summary.total_tsx_files, "sloc": summary.total_sloc,
            "orphans_count": summary.total_orphans, "dead_imports": summary.total_dead_imports,
            "clusters_count": len(summary.clusters),
            "orphans": [{"path": o.rel_path, "sloc": o.sloc} for o in summary.orphan_components[:15]],
            "duplicate_clusters": clusters,
        }
    }


def _build_json_payload(summary: UIAuditSummary) -> Dict[str, Any]:
    clusters = [
        {"category": c.category, "primitive": c.suggested_primitive, "count": c.count, "distinct_files": c.distinct_files, "estimated_sloc_saving": c.estimated_sloc_saving}
        for c in summary.clusters
    ]
    return {
        "ui_audit": {
            "target_path": str(summary.target_path), "health_score": round(summary.health_score, 1),
            "total_tsx_files": summary.total_tsx_files, "total_sloc": summary.total_sloc,
            "app_routes_count": summary.app_routes_count, "components_count": summary.components_count,
            "orphan_count": summary.total_orphans, "dead_import_count": summary.total_dead_imports,
            "clusters_count": len(summary.clusters),
            "orphan_components": [{"path": o.rel_path, "sloc": o.sloc, "exports": o.exported_symbols} for o in summary.orphan_components],
            "dead_imports": [{"file": d[0], "symbol": d[1], "source": d[2]} for d in summary.dead_imports],
            "duplicate_clusters": clusters,
        }
    }


class UIToonReporter:
    """Renders token-frugal TOON UI audit summary."""

    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        return encode(_build_toon_payload(summary))


class UIConsoleReporter:
    """Renders console UI audit summary."""

    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        lines = [
            "=" * 70, f"  🎨 EDGE UI AUDIT: {summary.target_path}", "=" * 70,
            f"  Health Score: {summary.health_score:.1f} / 100",
            f"  Total TSX Files: {summary.total_tsx_files}  |  Total SLOC: {summary.total_sloc:,}",
            f"  Orphan Components: {summary.total_orphans}  |  Dead Imports: {summary.total_dead_imports}",
            f"  Duplicate JSX Clusters: {len(summary.clusters)}", "-" * 70,
        ]
        if summary.orphan_components:
            lines.append("  🛑 Top Orphan Components (Unreferenced):")
            lines.extend(f"    - {o.rel_path} ({o.sloc} lines)" for o in summary.orphan_components[:8])
            if len(summary.orphan_components) > 8:
                lines.append(f"    - ... and {len(summary.orphan_components) - 8} more")
            lines.append("-" * 70)
        if summary.clusters:
            lines.append("  🧩 Top Centralization Candidates (src/components/ui/):")
            for c in summary.clusters[:5]:
                lines.append(f"    - [{c.category.upper()}] -> {c.suggested_primitive}")
                lines.append(f"      {c.count} instances across {len(c.distinct_files)} files (Est saving: ~{c.estimated_sloc_saving} lines)")
            lines.append("-" * 70)
        return "\n".join(lines)


class UIJsonReporter:
    """Renders machine-readable JSON UI audit summary."""

    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        return json.dumps(_build_json_payload(summary), indent=2)
