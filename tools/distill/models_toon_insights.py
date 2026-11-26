"""Flight recorder insight TOON formatters for FrictionDigest."""

from typing import Any, Dict, List, Optional


def _cap_section_lines(header: str, item_lines: List[str], limit: int = 5) -> Optional[str]:
    if not item_lines:
        return None
    lines = [header] + item_lines[:limit]
    if len(item_lines) > limit:
        lines.append(f"- ... (+{len(item_lines) - limit} more)")
    return "\n".join(lines)


def _pick_first_str(*values: Any) -> str:
    for v in values:
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _format_insight_details(details: Any) -> str:
    if isinstance(details, dict) and details:
        return ", ".join(f"{k}={v}" for k, v in list(details.items())[:3])
    return str(details).strip()[:60] if (details and not isinstance(details, dict)) else ""


def _format_guard_failure_insight(insight: Dict[str, Any]) -> Optional[str]:
    gf = insight.get("guard_failure")
    gf_dict = gf if isinstance(gf, dict) else {}
    state = _pick_first_str(insight.get("state"), gf_dict.get("state"))
    message = _pick_first_str(insight.get("message"), gf_dict.get("message"))
    details = gf_dict.get("details") if insight.get("details") is None else insight.get("details")
    head = ": ".join(p for p in (state, message) if p) or _pick_first_str(gf)
    det_str = _format_insight_details(details)
    if det_str and head:
        return f"- [GUARD_FAIL] {head} ({det_str})"
    return f"- [GUARD_FAIL] {head or det_str}" if (det_str or head) else None


def _format_dead_end_insight(insight: Dict[str, Any]) -> Optional[str]:
    det = insight.get("details")
    det_dict = det if isinstance(det, dict) else {}
    title = _pick_first_str(insight.get("title"), insight.get("approach"), insight.get("dead_end"), det_dict.get("title"), det_dict.get("approach"))
    reason = _pick_first_str(insight.get("reason"), det_dict.get("reason"))
    rule = _pick_first_str(insight.get("prohibited_rule"), det_dict.get("prohibited_rule"))
    parts = [p for p in (title, f"reason={reason}" if reason else "", f"rule={rule}" if rule else "") if p]
    return f"- [DEAD_END] {' | '.join(parts)}" if parts else None


def _render_insights_toon(flight_recorder_insights: List[Dict[str, Any]]) -> Optional[str]:
    if not flight_recorder_insights:
        return None
    item_lines: List[str] = []
    for ins in flight_recorder_insights:
        if not isinstance(ins, dict):
            txt = str(ins).strip()
            if txt:
                item_lines.append(f"- [DEAD_END] {txt}")
            continue
        kind = str(ins.get("kind", "")).lower()
        ln = _format_guard_failure_insight(ins) if (kind == "guard_failure" or (not kind and "guard_failure" in ins)) else _format_dead_end_insight(ins)
        if ln:
            item_lines.append(ln)
    return _cap_section_lines("\n## Flight Recorder Insights", item_lines, limit=5)
