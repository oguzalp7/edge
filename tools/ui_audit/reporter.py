"""
UI Audit Reporters
Provides Markdown RFC, TOON (Token-Oriented Object Notation), and Console formats
for UI component graph and JSX duplication analysis.
"""

from typing import List
from .models import UIAuditSummary, DuplicateCluster


class UIMarkdownReporter:
    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        lines = []
        lines.append("# 🎨 UI Architecture Audit & Consolidation RFC")
        lines.append("")
        lines.append(f"> **Target Scope:** `{summary.target_path}`  ")
        lines.append(f"> **UI Health Score:** `{summary.health_score:.1f} / 100`  ")
        lines.append(f"> **Stack Policy:** Pure Tailwind CSS (No external UI dependencies)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # 1. Executive Summary Table
        lines.append("## 📊 1. Executive Summary")
        lines.append("")
        lines.append("| Metric | Count | Assessment |")
        lines.append("| :--- | :--- | :--- |")
        lines.append(f"| **Total TSX Files** | `{summary.total_tsx_files}` | Scope: `src/app` + `src/components` |")
        lines.append(f"| **Total UI SLOC** | `{summary.total_sloc:,}` lines | Front-end surface area |")
        lines.append(f"| **App Routes / Pages** | `{summary.app_routes_count}` | Ingress endpoints |")
        lines.append(f"| **Component Count** | `{summary.components_count}` | Shared & domain components |")
        lines.append(f"| **Orphan Components** | `{summary.total_orphans}` | Unreferenced in `src/components` |")
        lines.append(f"| **Dead Imports** | `{summary.total_dead_imports}` | Unused imported symbols |")
        lines.append(f"| **JSX Duplicate Clusters** | `{len(summary.clusters)}` | Opportunities for centralized primitives |")
        lines.append("")

        # 2. Orphan Components
        lines.append("## 🛑 2. Orphan Components (0 Ingress References)")
        lines.append("")
        lines.append("The following components are defined under `src/components/`, but are **never imported or rendered** by any route or component:")
        lines.append("")
        if not summary.orphan_components:
            lines.append("✅ *No orphan components detected. All components have active consumers.*")
        else:
            lines.append("| Component Path | SLOC | Exported Symbols | Action Proposal |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for node in summary.orphan_components:
                exports_str = ", ".join(f"`{s}`" for s in node.exported_symbols[:3]) or "*none*"
                lines.append(f"| `{node.rel_path}` | `{node.sloc}` | {exports_str} | Candidate for deprecation / safe deletion |")
        lines.append("")

        # 3. Dead Imports
        lines.append("## 🧹 3. Dead Symbol Imports in TSX Files")
        lines.append("")
        if not summary.dead_imports:
            lines.append("✅ *No unused symbol imports detected in TSX files.*")
        else:
            lines.append(f"Found **{summary.total_dead_imports}** unused imported symbols:")
            lines.append("")
            lines.append("| File | Dead Symbol | Source Module |")
            lines.append("| :--- | :--- | :--- |")
            for file_path, sym, src in summary.dead_imports[:25]:
                lines.append(f"| `{file_path}` | `{sym}` | `{src}` |")
            if len(summary.dead_imports) > 25:
                lines.append(f"| *...and {len(summary.dead_imports) - 25} more* | | |")
        lines.append("")

        # 4. Duplicate JSX Clusters & Primitive Proposals
        lines.append("## 🧩 4. Duplicate JSX Clusters & Centralized Primitive Proposals")
        lines.append("")
        lines.append("Recurring structural patterns identified across multiple components. Consolidating these into `src/components/ui/` eliminates boilerplate and ensures token consistency:")
        lines.append("")

        if not summary.clusters:
            lines.append("✅ *No severe structural JSX duplication found.*")
        else:
            for idx, c in enumerate(summary.clusters[:10], 1):
                lines.append(f"### 4.{idx} [{c.category.upper()}] Cluster: `{c.suggested_primitive}`")
                lines.append(f"- **Occurrences:** `{c.count}` instances across `{len(c.distinct_files)}` files.")
                lines.append(f"- **Estimated SLOC Reduction:** `~{c.estimated_sloc_saving}` lines.")
                lines.append(f"- **Files Involved:**")
                for f in c.distinct_files[:6]:
                    lines.append(f"  - `{f}`")
                if len(c.distinct_files) > 6:
                    lines.append(f"  - *...and {len(c.distinct_files) - 6} more files*")
                
                lines.append("")
                lines.append("**Proposed TypeScript Interface:**")
                lines.append("```typescript")
                lines.append(c.props_proposal)
                lines.append("```")
                
                lines.append("")
                lines.append("**Example Concrete Call Site Snippet:**")
                lines.append(f"```tsx\n{c.instances[0].snippet}\n```")
                lines.append("")
                lines.append("---")
                lines.append("")

        # 5. Visual Parity Gate via chrome-devtools-axi
        lines.append("## 👁️ 5. Visual Verification Protocol (`chrome-devtools-axi`)")
        lines.append("")
        lines.append("When approving and executing any slice above:")
        lines.append("1. **Baseline Screenshot:** Capture baseline UI with `chrome-devtools-axi screenshot <slice>_baseline.png`")
        lines.append("2. **Centralize:** Extract the primitive into `src/components/ui/` and swap duplicate JSX with `<Primitive variant=\"...\" />`.")
        lines.append("3. **Typecheck & Test:** Run `tsc --noEmit` and component unit tests.")
        lines.append("4. **Parity Comparison:** Capture `chrome-devtools-axi screenshot <slice>_refactored.png` and verify layout consistency (max 3 loops).")
        lines.append("5. **PR Gate:** Final review with `no-mistakes axi run --skip ci`.")
        lines.append("")

        return "\n".join(lines)


from tools.common.toon import encode


class UIToonReporter:
    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        data = {
            "ui_audit": {
                "score": round(summary.health_score, 1),
                "files": summary.total_tsx_files,
                "sloc": summary.total_sloc,
                "orphans_count": summary.total_orphans,
                "dead_imports": summary.total_dead_imports,
                "clusters_count": len(summary.clusters),
                "orphans": [
                    {"path": o.rel_path, "sloc": o.sloc}
                    for o in summary.orphan_components[:15]
                ],
                "duplicate_clusters": [
                    {
                        "category": c.category,
                        "primitive": c.suggested_primitive,
                        "count": c.count,
                        "saving": c.estimated_sloc_saving,
                        "sample_files": "|".join(c.distinct_files[:3]),
                    }
                    for c in summary.clusters[:8]
                ],
            }
        }
        return encode(data)



class UIConsoleReporter:
    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        lines = []
        lines.append("=" * 70)
        lines.append(f"  🎨 EDGE UI AUDIT: {summary.target_path}")
        lines.append("=" * 70)
        lines.append(f"  Health Score: {summary.health_score:.1f} / 100")
        lines.append(f"  Total TSX Files: {summary.total_tsx_files}  |  Total SLOC: {summary.total_sloc:,}")
        lines.append(f"  Orphan Components: {summary.total_orphans}  |  Dead Imports: {summary.total_dead_imports}")
        lines.append(f"  Duplicate JSX Clusters: {len(summary.clusters)}")
        lines.append("-" * 70)
        
        if summary.orphan_components:
            lines.append("  🛑 Top Orphan Components (Unreferenced):")
            for o in summary.orphan_components[:8]:
                lines.append(f"    - {o.rel_path} ({o.sloc} lines)")
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
