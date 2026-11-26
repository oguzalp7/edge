"""Ship-prep submodule: render_refactor."""

from typing import List, Dict, Any, Optional, Tuple

def _format_refactor_summary_block(
    refactor_receipts: List[Dict[str, Any]],
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if not refactor_receipts:
        return []
    lines: List[str] = []
    eff_door = door_type or str(refactor_receipts[0].get("seal_1_intent", {}).get("door_type") or "Two-way door (Reversible Code / Configuration Change)")
    reasons: List[str] = list((blast_radius or {}).get("one_way_reasons") or [])
    for rec in refactor_receipts:
        for r in rec.get("seal_1_intent", {}).get("one_way_reasons") or []:
            if r not in reasons:
                reasons.append(r)

    lines.append(f"- **Door Classification:** {eff_door}")
    if reasons:
        lines.append(f"- **One-Way Reasons:** {'; '.join(reasons)}")

    for rec in refactor_receipts:
        s1 = rec.get("seal_1_intent") or {}
        s2 = rec.get("seal_2_metrics") or {}
        slug = rec.get("slug") or s1.get("slug") or "refactor"
        rules = ", ".join(f"`{r}`" for r in (s1.get("target_rules") or [])) or "—"
        lines.extend([
            "",
            f"### Before/After Metric Delta (`{slug}`)",
            f"- **Intent & Rules:** {rules} (`behavior_preserved: {s1.get('behavior_preserved')}`)",
            "| Metric | Before | Target | After | Delta |",
            "| :--- | ---: | ---: | ---: | ---: |",
        ])
        before = s2.get("before") or {}
        after = s2.get("after") or {}
        targets = s2.get("metric_targets") or {}
        keys = list(dict.fromkeys([*before.keys(), *after.keys(), *targets.keys()]))
        for k in keys:
            b_v = before.get(k)
            t_v = targets.get(k)
            a_v = after.get(k)
            delta_s = f"{a_v - b_v:+g}" if isinstance(b_v, (int, float)) and isinstance(a_v, (int, float)) else "—"
            lines.append(
                f"| `{k}` | {b_v if b_v is not None else 'null'} | "
                f"{t_v if t_v is not None else '—'} | "
                f"{a_v if a_v is not None else 'null'} | {delta_s} |"
            )
    return lines
