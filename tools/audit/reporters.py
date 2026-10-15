import json
from typing import List
from .models import AuditSummary, FileMetrics, RiskCategory

class ConsoleReporter:
    @staticmethod
    def render(summary: AuditSummary, top_n: int = 15) -> str:
        out = []
        out.append("=" * 80)
        out.append("🛡️  EDGE-AUDIT: CODEBASE HEALTH & BLOAT ASSESSMENT")
        out.append("=" * 80)
        out.append(f"Target Path: {summary.target_path}")
        out.append(f"Analyzed Files: {summary.analyzed_files} (Total Found: {summary.total_files})")
        out.append(f"Source Lines of Code (SLOC): {summary.total_sloc:,} (Total Lines: {summary.total_lines:,})")
        
        health = summary.overall_health_score
        health_color = "🟢" if health >= 80 else ("🟡" if health >= 60 else "🔴")
        out.append(f"Overall Health Score: {health_color} {health} / 100")
        out.append(
            f"Category Breakdown: 🔴 {summary.critical_hotspots} Critical Hotspots | "
            f"🟡 {summary.attention_files} Attention Needed | "
            f"🟢 {summary.clean_files} Clean Files"
        )
        out.append("-" * 80)

        sorted_files = sorted(summary.file_results, key=lambda f: f.risk_score, reverse=True)
        hotspots = [f for f in sorted_files if f.risk_score >= 18.0]

        if not hotspots:
            out.append("✅ Excellent! No files exceeding bloat and complexity thresholds were found.")
            out.append("=" * 80)
            return "\n".join(out)

        out.append(f"🔥 TOP {min(top_n, len(hotspots))} BLOATED & HIGH-RISK HOTSPOTS:")
        out.append(f"{'Risk':<6} {'SLOC':<7} {'Cmplx':<7} {'Indent':<8} {'Export':<7} {'Test?':<6} {'File Path'}")
        out.append("-" * 80)

        for f in hotspots[:top_n]:
            icon = "🔴" if f.risk_category == RiskCategory.CRITICAL else ("🟠" if f.risk_category == RiskCategory.HOTSPOT else "🟡")
            test_icon = "✅" if f.has_test_seam else "❌"
            out.append(
                f"{icon} {f.risk_score:<4.1f} {f.sloc:<7} {f.complexity_score:<7} "
                f"{f.max_indent_level:<8} {f.public_exports:<7} {test_icon:<6} {f.rel_path}"
            )

        out.append("-" * 80)
        out.append("📋 TOP CRITICAL HOTSPOT RECOMMENDATIONS:")
        out.append("-" * 80)

        critical_sample = [f for f in sorted_files if f.risk_score >= 35.0][:5]
        if not critical_sample:
            critical_sample = sorted_files[:3]

        for idx, f in enumerate(critical_sample, 1):
            out.append(f"\n[{idx}] 📌 {f.rel_path} (Risk: {f.risk_score} | SLOC: {f.sloc})")
            if f.issue_tags:
                out.append(f"    Tags: {', '.join([t.value for t in f.issue_tags])}")
            if f.slicing_recommendations:
                for rec in f.slicing_recommendations:
                    out.append(f"    👉 {rec}")
            else:
                out.append("    👉 Structure is within acceptable bounds.")

        out.append("\n" + "=" * 80)
        return "\n".join(out)

from tools.common.toon import encode


class ToonReporter:
    """Agent eXperience Interface (AXI) Token-Oriented Object Notation Reporter"""
    @staticmethod
    def render(summary: AuditSummary, top_n: int = 15) -> str:
        sorted_files = sorted(summary.file_results, key=lambda f: f.risk_score, reverse=True)
        hotspots = [f for f in sorted_files if f.risk_score >= 20.0][:top_n]

        data = {
            "edge_audit_result": {
                "target": summary.target_path,
                "health_score": summary.overall_health_score,
                "files_analyzed": summary.analyzed_files,
                "total_sloc": summary.total_sloc,
                "critical_count": summary.critical_hotspots,
                "attention_count": summary.attention_files,
                "hotspots": [
                    {
                        "path": f.rel_path,
                        "risk": round(f.risk_score, 1),
                        "sloc": f.sloc,
                        "complexity": f.complexity_score,
                        "indent": f.max_indent_level,
                        "exports": f.public_exports,
                        "has_test": f.has_test_seam,
                        "tags": "|".join([t.value for t in f.issue_tags]),
                    }
                    for f in hotspots
                ],
            }
        }
        return encode(data)

