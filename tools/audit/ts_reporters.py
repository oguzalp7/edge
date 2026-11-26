"""
Human, Markdown, JSON, and TOON formatters for TsDisciplineSummary.
"""

from __future__ import annotations

import json
from typing import List

from tools.audit.ts_models import TsDisciplineSummary, _score_to_band_and_badge
from tools.common.toon import encode


def format_human(summary: TsDisciplineSummary, top: int = 15) -> str:
    _, badge = _score_to_band_and_badge(summary.overall_score)
    lines: List[str] = [
        "=" * 95,
        "🔷 TYPESCRIPT TYPE-SYSTEM DISCIPLINE AUDIT (edge-audit --track types)",
        "=" * 95,
        f"Target Path      : {summary.target_path}",
        f"Overall Score    : {badge} {summary.overall_score}/100 ({summary.overall_band})",
        f"Files Analyzed   : {summary.files_analyzed} (Total SLOC: {summary.total_sloc:,})",
        f"Band Distribution: 🟢 STRICT {summary.strict_count} | 🟡 LOOSE {summary.loose_count} | 🔴 POROUS {summary.porous_count}",
    ]
    if summary.rule_counts:
        lines.append("\nRule Violation Counts:")
        lines.extend(f"  - {rid:<28} : {cnt}" for rid, cnt in sorted(summary.rule_counts.items(), key=lambda kv: (-kv[1], kv[0])))

    hotspots = [r for r in summary.file_reports if r.findings][:top]
    if hotspots:
        lines.extend([f"\n🚨 TOP {len(hotspots)} TYPE-DISCIPLINE HOTSPOTS:", "-" * 95])
        for idx, r in enumerate(hotspots, 1):
            lines.append(f"[#{idx:02d}] {r.badge} [{r.score:03d}/100] ({r.sloc} SLOC) -> {r.path}")
            lines.extend(f"       ❌ L{f.line_number} {f.rule_id} ({f.penalty}p): {f.message}" for f in r.findings[:8])
    else:
        lines.append("\n✨ All analyzed TypeScript files passed with zero type-discipline penalties.")
    lines.append("=" * 95)
    return "\n".join(lines)


def format_markdown(summary: TsDisciplineSummary, top: int = 15) -> str:
    lines: List[str] = [
        "# 🔷 TypeScript Type-System Discipline Report (`--track types`)",
        "",
        f"> **Target:** `{summary.target_path}` | **Overall Score:** `{summary.overall_score}/100` (`{summary.overall_band}`) | **Files:** `{summary.files_analyzed}` (`{summary.total_sloc:,}` SLOC)",
        "",
        "| Band | Count |",
        "| :--- | :--- |",
        f"| 🟢 STRICT (85-100) | `{summary.strict_count}` |",
        f"| 🟡 LOOSE (60-84) | `{summary.loose_count}` |",
        f"| 🔴 POROUS (0-59) | `{summary.porous_count}` |",
        "",
    ]
    if summary.rule_counts:
        lines.extend(["## 📊 Rule Breakdown", "", "| Rule ID | Count |", "| :--- | :--- |"])
        lines.extend(f"| `{rid}` | `{cnt}` |" for rid, cnt in sorted(summary.rule_counts.items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append("")

    hotspots = [r for r in summary.file_reports if r.findings][:top]
    if hotspots:
        lines.extend([f"## 🚨 Top {len(hotspots)} Hotspots", "", "| Score | Band | SLOC | Path | Rules |", "| :--- | :--- | :--- | :--- | :--- |"])
        for r in hotspots:
            rules = ", ".join(dict.fromkeys(f.rule_id for f in r.findings))
            lines.append(f"| `{r.score}/100` | {r.badge} | `{r.sloc}` | `{r.path}` | {rules} |")
        lines.append("")
    return "\n".join(lines)


def format_json(summary: TsDisciplineSummary, top: int = 15) -> str:
    return json.dumps({"ts_discipline_summary": {
        "target_path": summary.target_path, "overall_score": summary.overall_score,
        "overall_band": summary.overall_band, "files_analyzed": summary.files_analyzed,
        "total_sloc": summary.total_sloc, "strict_count": summary.strict_count,
        "loose_count": summary.loose_count, "porous_count": summary.porous_count,
        "rule_counts": dict(summary.rule_counts), "results": [r.to_dict() for r in summary.file_reports[:top]],
    }}, indent=2)


def format_toon(summary: TsDisciplineSummary, top: int = 15) -> str:
    hotspots = [r for r in summary.file_reports if r.findings][:top]
    return encode({"ts_discipline_result": {
        "target": summary.target_path, "overall_score": summary.overall_score,
        "overall_band": summary.overall_band, "files_analyzed": summary.files_analyzed,
        "total_sloc": summary.total_sloc, "strict_count": summary.strict_count,
        "loose_count": summary.loose_count, "porous_count": summary.porous_count,
        "rule_counts": dict(summary.rule_counts),
        "hotspots": [{"path": r.path, "score": r.score, "band": r.band, "sloc": r.sloc, "rules": "|".join(dict.fromkeys(f.rule_id for f in r.findings))} for r in hotspots],
    }})
