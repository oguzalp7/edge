"""TOON section rendering and water-filling budget truncation for FrictionDigest."""

from typing import Any, Dict, List, Optional

from tools.distill.models_economy import GuardrailGapSignal, NavigationFrictionSignal, RuleInventoryItem
from tools.distill.models_signals import (
    RepeatedEscalation,
    StationEscapeSignal,
    ToolFrictionSignal,
    _extract_meaningful_error_snippet,
)
from tools.distill.models_toon_insights import _cap_section_lines, _render_insights_toon


def _render_escalations_toon(escalations: List[RepeatedEscalation]) -> Optional[str]:
    if not escalations:
        return None
    return "\n".join(["\n## Repeated Escalations", *(e.to_toon() for e in escalations)])


def _render_tool_frictions_toon(tool_frictions: List[ToolFrictionSignal]) -> Optional[str]:
    if not tool_frictions:
        return None
    clusters: Dict[str, Dict[str, Any]] = {}
    for tf in tool_frictions:
        cmd_core = tf.command_or_args.strip().split("\n")[0][:40]
        key = f"{tf.tool_name}:{tf.exit_code}:{cmd_core}"
        if key not in clusters:
            clusters[key] = {"tool": tf.tool_name, "exit": tf.exit_code, "cmd": cmd_core, "err": _extract_meaningful_error_snippet(tf.error_output, max_len=80), "count": 0}
        clusters[key]["count"] += 1
    item_lines = []
    for c in clusters.values():
        repeat_tag = f" (repeated {c['count']}x)" if c["count"] > 1 else ""
        item_lines.append(f"- [TOOL:{c['tool']}] exit={c['exit']}{repeat_tag}: {c['cmd']} -> {c['err']}")
    return _cap_section_lines("\n## Tool Frictions", item_lines, limit=5)


def _render_escapes_toon(station_escapes: List[StationEscapeSignal]) -> Optional[str]:
    return _cap_section_lines("\n## Station Escapes", [esc.to_toon() for esc in station_escapes], limit=5)


def _render_navigation_frictions_toon(navigation_frictions: List[NavigationFrictionSignal], total_tokens_estimate: int = 0) -> Optional[str]:
    if not navigation_frictions and total_tokens_estimate <= 0:
        return None
    header = f"\n## Navigation & Tool Economy (est_tokens={total_tokens_estimate})" if total_tokens_estimate > 0 else "\n## Navigation & Tool Economy"
    return header if not navigation_frictions else _cap_section_lines(header, [s.to_toon() for s in navigation_frictions], limit=5)


def _render_guardrail_gaps_toon(guardrail_gaps: List[GuardrailGapSignal]) -> Optional[str]:
    return _cap_section_lines("\n## Guardrail Gaps", [g.to_toon() for g in guardrail_gaps], limit=5)


def _render_rule_inventory_toon(rule_inventory: List[RuleInventoryItem]) -> Optional[str]:
    return _cap_section_lines("\n## Rule Inventory", [i.to_toon() for i in rule_inventory], limit=5)


def _render_factory_inbox_toon(factory_inbox_signals: List[Dict[str, Any]]) -> Optional[str]:
    return _cap_section_lines("\n## Factory Inbox Signals", [f"- [{s.get('signal_id', '')}] ({s.get('role_or_tool', '')}) {s.get('summary', '')}" for s in factory_inbox_signals], limit=5)


def _render_churn_and_critiques_toon(git_churn: List[Dict[str, Any]], critique_findings: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    churn_sec = _cap_section_lines("\n## Git Churn", [f"- [CHURN] {c.get('commit', '')}: {c.get('message', '')}" for c in git_churn], limit=5)
    crit_sec = _cap_section_lines("\n## Critique Findings", [f"- [CRITIQUE] {c.get('spec', '')}: {c.get('finding', '')}" for c in critique_findings], limit=5)
    if churn_sec:
        out.append(churn_sec)
    if crit_sec:
        out.append(crit_sec)
    return out


def _allocate_section_budgets(lengths: List[int], total_budget: int) -> List[int]:
    budgets, remaining = [0] * len(lengths), max(0, total_budget)
    sorted_indices = sorted(range(len(lengths)), key=lambda i: lengths[i])
    total_count = len(sorted_indices)
    for pos, idx in enumerate(sorted_indices):
        alloc = min(lengths[idx], remaining // (total_count - pos))
        budgets[idx] = alloc
        remaining -= alloc
    return budgets


def _truncate_toon_output(base: str, sections: List[str], max_chars: int) -> str:
    if not sections:
        return base[:max_chars]
    remaining = max_chars - len(base) - (len(sections) + 2)
    if remaining <= 0:
        return base[:max_chars]
    appended: List[str] = []
    for sec, limit in zip(sections, _allocate_section_budgets([len(s) for s in sections], remaining)):
        if len(sec) <= limit:
            appended.append(sec)
        elif limit > 20:
            appended.append(sec[: limit - 16] + "... [truncated]")
        elif limit > 0:
            appended.append(sec[:limit])
    return (f"{base}\n" + "\n".join(appended))[:max_chars]
