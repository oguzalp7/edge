"""Ship-prep submodule: render_examiner."""

from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.paths import _normalize_display_path

def _format_examiner_seal_block(examiner_receipt: Optional[Dict[str, Any]]) -> List[str]:
    if not examiner_receipt:
        return []
    verdict = str(examiner_receipt.get("verdict") or "").upper()
    icon = "✅" if verdict == "PASS" else "❌"
    summary = str(examiner_receipt.get("summary") or "").strip()
    lines = [
        "",
        "### Examiner 3-Axis Seal",
        f"- **Verdict:** {icon} `{verdict}` — {summary}",
    ]
    raw_ev = examiner_receipt.get("evidence_reviewed") or []
    norm_ev = list(dict.fromkeys(_normalize_display_path(str(p)) for p in raw_ev if str(p).strip()))
    if norm_ev:
        lines.extend([f"<details><summary>📂 Reviewed Artifacts ({len(norm_ev)} files)</summary>", ""])
        lines.extend(f"- `{p}`" for p in norm_ev)
        lines.extend(["", "</details>"])
    return lines


def _format_refactor_evidence_block(refactor_receipts: List[Dict[str, Any]]) -> List[str]:
    if not refactor_receipts:
        return []
    lines: List[str] = ["", "### RefactorReceipt & Deterministic Gate"]
    for rec in refactor_receipts:
        slug = rec.get("slug") or rec.get("seal_1_intent", {}).get("slug") or "refactor"
        s3 = rec.get("seal_3_gate") or {}
        stages = s3.get("stages") or []
        passed_cnt = sum(1 for st in stages if st.get("passed"))
        lines.append(
            f"- **RefactorReceipt:** `.edge/receipts/refactor/{slug}.json` "
            f"(Gate: `{passed_cnt}/{len(stages)}` stages passed, `all_passed={s3.get('all_passed')}`)"
        )
        s4 = rec.get("seal_4_examiner") or {}
        if s4:
            lines.extend(_format_examiner_seal_block(s4))
    return lines
