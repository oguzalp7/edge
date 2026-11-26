"""Human, Markdown, TOON, and JSON report formatters for edge-tests-audit-typescript."""

import json
from typing import Any, Dict, List, Tuple

from tools.common.toon import encode


def _bucket_results(results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], int]:
    toxic = [r for r in results if r["score"] < 50]
    masked = [r for r in results if 50 <= r["score"] < 85]
    pure = [r for r in results if r["score"] >= 85]
    avg_score = round(sum(r["score"] for r in results) / len(results)) if results else 0
    return toxic, masked, pure, avg_score


def format_human(results: List[Dict[str, Any]], top: int = 15) -> str:
    """Format terminal health radar report."""
    toxic, masked, pure, avg_score = _bucket_results(results)
    lines = ["=" * 95, "📊 TYPESCRIPT UNIT TEST HEALTH RADAR (edge-tests-audit-typescript)", "=" * 95]
    if toxic:
        lines.extend([f"\n🚨 TOP {min(top, len(toxic))} TOXIC UNIT TESTS (URGENT ISOLATION REQUIRED):", "-" * 95])
        for idx, r in enumerate(toxic[:top]):
            lines.append(f"[#{idx + 1:02d}] {r['badge']} [Score: {r['score']:02d}/100] -> {r['path']}")
            lines.extend(f"       ❌ {v['penalty']}p : {v['desc']}" for v in r["violations"])
            lines.extend(f"       ✅ +{b['bonus']}p : {b['desc']}" for b in r["bonuses"])
    else:
        lines.append("\n✨ Excellent! No toxic / database-leaking unit tests were found.")
    total = len(results)
    pct = lambda n: round((n / total) * 100) if total else 0
    lines.extend([
        "\n" + "=" * 95, "📈 DISTRIBUTION & SUMMARY STATISTICS:",
        f"   Total Test Files    : {total}", f"   Average Health      : {avg_score} / 100",
        f"   🟢 Pure Unit        : {len(pure)} ({pct(len(pure))}%)",
        f"   🟡 Masked Integrat. : {len(masked)} ({pct(len(masked))}%)",
        f"   🔴 Toxic / Leaky DB : {len(toxic)} ({pct(len(toxic))}%)",
        "=" * 95,
    ])
    return "\n".join(lines)


def format_markdown(results: List[Dict[str, Any]], top: int = 15) -> str:
    """Format Markdown unit test purity table."""
    toxic, masked, pure, avg_score = _bucket_results(results)
    lines = [
        "# 📊 TypeScript Unit Test Health Radar (`edge-tests-audit-typescript`)", "",
        f"- **Average Health:** `{avg_score}/100` | **Files Analyzed:** `{len(results)}`",
        f"- **Distribution:** 🟢 Pure: `{len(pure)}` | 🟡 Masked: `{len(masked)}` | 🔴 Toxic: `{len(toxic)}`", "",
    ]
    if toxic:
        lines.extend(["### 🚨 Toxic Unit Tests (Leaky Database / I/O)", "", "| Score | Status | Test File | Violations |", "| :--- | :--- | :--- | :--- |"])
        for r in toxic[:top]:
            viols = ", ".join(f"{v['rule']} ({v['penalty']}p)" for v in r["violations"])
            lines.append(f"| `{r['score']}/100` | {r['badge']} | `{r['path']}` | {viols} |")
        lines.append("")
    else:
        lines.extend(["✅ *Excellent! No toxic / database-leaking unit tests were found.*", ""])
    return "\n".join(lines)


def format_toon(results: List[Dict[str, Any]], top: int = 15) -> str:
    """Format compact TOON output."""
    toxic, masked, pure, avg_score = _bucket_results(results)
    return encode({
        "test_purity_result": {
            "total_files": len(results), "average_score": avg_score,
            "pure_count": len(pure), "masked_count": len(masked), "toxic_count": len(toxic),
            "toxic_hotspots": [{"path": r["path"], "score": r["score"], "violations": "|".join(v["rule"] for v in r["violations"])} for r in toxic[:top]],
        }
    })


def format_json(results: List[Dict[str, Any]], top: int = 15) -> str:
    """Format machine-readable JSON output."""
    toxic, masked, pure, avg_score = _bucket_results(results)
    return json.dumps({
        "test_audit_summary": {
            "total_files": len(results), "average_score": avg_score,
            "pure_count": len(pure), "masked_count": len(masked), "toxic_count": len(toxic),
            "results": [{"path": r["path"], "score": r["score"], "category": r["category"], "violations": r["violations"], "bonuses": r["bonuses"]} for r in results[:top]],
        }
    }, indent=2)
