"""Markdown RFC report renderer for UI Architecture Audit."""

from typing import List

from .models import UIAuditSummary


def _append_summary_and_orphans(lines: List[str], summary: UIAuditSummary) -> None:
    lines.extend([
        "# 🎨 UI Architecture Audit & Consolidation RFC", "",
        f"> **Target Scope:** `{summary.target_path}`  ",
        f"> **UI Health Score:** `{summary.health_score:.1f} / 100`  ",
        "> **Stack Policy:** Pure Tailwind CSS (No external UI dependencies)", "", "---", "",
        "## 📊 1. Executive Summary", "", "| Metric | Count | Assessment |", "| :--- | :--- | :--- |",
        f"| **Total TSX Files** | `{summary.total_tsx_files}` | Scope: `src/app` + `src/components` |",
        f"| **Total UI SLOC** | `{summary.total_sloc:,}` lines | Front-end surface area |",
        f"| **App Routes / Pages** | `{summary.app_routes_count}` | Ingress endpoints |",
        f"| **Component Count** | `{summary.components_count}` | Shared & domain components |",
        f"| **Orphan Components** | `{summary.total_orphans}` | Unreferenced in `src/components` |",
        f"| **Dead Imports** | `{summary.total_dead_imports}` | Unused imported symbols |",
        f"| **JSX Duplicate Clusters** | `{len(summary.clusters)}` | Opportunities for centralized primitives |", "",
        "## 🛑 2. Orphan Components (0 Ingress References)", "",
        "The following components are defined under `src/components/`, but are **never imported or rendered** by any route or component:", "",
    ])
    if not summary.orphan_components:
        lines.extend(["✅ *No orphan components detected. All components have active consumers.*", ""])
        return
    lines.extend(["| Component Path | SLOC | Exported Symbols | Action Proposal |", "| :--- | :--- | :--- | :--- |"])
    for node in summary.orphan_components:
        exp = ", ".join(f"`{s}`" for s in node.exported_symbols[:3]) or "*none*"
        lines.append(f"| `{node.rel_path}` | `{node.sloc}` | {exp} | Candidate for deprecation / safe deletion |")
    lines.append("")


def _append_dead_imports(lines: List[str], summary: UIAuditSummary) -> None:
    lines.extend(["## 🧹 3. Dead Symbol Imports in TSX Files", ""])
    if not summary.dead_imports:
        lines.extend(["✅ *No unused symbol imports detected in TSX files.*", ""])
        return
    lines.extend([f"Found **{summary.total_dead_imports}** unused imported symbols:", "", "| File | Dead Symbol | Source Module |", "| :--- | :--- | :--- |"])
    lines.extend(f"| `{fp}` | `{sym}` | `{src}` |" for fp, sym, src in summary.dead_imports[:25])
    if len(summary.dead_imports) > 25:
        lines.append(f"| *...and {len(summary.dead_imports) - 25} more* | | |")
    lines.append("")


def _append_clusters_and_footer(lines: List[str], summary: UIAuditSummary) -> None:
    lines.extend([
        "## 🧩 4. Duplicate JSX Clusters & Centralized Primitive Proposals", "",
        "Recurring structural patterns identified across multiple components. Consolidating these into `src/components/ui/` eliminates boilerplate and ensures token consistency:", "",
    ])
    if not summary.clusters:
        lines.append("✅ *No severe structural JSX duplication found.*")
    for idx, c in enumerate(summary.clusters[:10], 1):
        lines.extend([
            f"### 4.{idx} [{c.category.upper()}] Cluster: `{c.suggested_primitive}`",
            f"- **Occurrences:** `{c.count}` instances across `{len(c.distinct_files)}` files.",
            f"- **Estimated SLOC Reduction:** `~{c.estimated_sloc_saving}` lines.", "- **Files Involved:**",
            *(f"  - `{f}`" for f in c.distinct_files[:6]),
        ])
        if len(c.distinct_files) > 6:
            lines.append(f"  - *...and {len(c.distinct_files) - 6} more files*")
        lines.extend(["", "**Proposed TypeScript Interface:**", "```typescript", c.props_proposal, "```", "", "**Example Concrete Call Site Snippet:**", f"```tsx\n{c.instances[0].snippet}\n```", "", "---", ""])
    lines.extend([
        "", "## 👁️ 5. Visual Verification Protocol (`chrome-devtools-axi` -> `chrome-devtools-mcp` -> `browser`)", "",
        "When approving and executing any slice above:",
        "1. **Baseline Screenshot:** Capture baseline UI with `chrome-devtools-axi screenshot <slice>_baseline.png` (or fallback to `chrome-devtools-mcp` `take_screenshot` / built-in `browser` subagent).",
        "2. **Centralize:** Extract the primitive into `src/components/ui/` and swap duplicate JSX with `<Primitive variant=\"...\" />`.",
        "3. **Typecheck & Test:** Run `tsc --noEmit` and component unit tests.",
        "4. **Parity Comparison:** Capture `chrome-devtools-axi screenshot <slice>_refactored.png` (or `chrome-devtools-mcp` / `browser`) and verify layout consistency via `diff_image` (max 3 loops).",
        "5. **PR Gate:** Final review with `brigade prepare-ship` / `no-mistakes`.", "",
    ])


class UIMarkdownReporter:
    """Renders detailed Markdown architecture consolidation RFC."""

    @staticmethod
    def render(summary: UIAuditSummary) -> str:
        lines: List[str] = []
        _append_summary_and_orphans(lines, summary)
        _append_dead_imports(lines, summary)
        _append_clusters_and_footer(lines, summary)
        return "\n".join(lines)
