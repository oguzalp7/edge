#!/usr/bin/env python3
"""Data models Facade for edge-distill: Pattern & Playbook Miner & Zero-Token Harvester."""

import importlib
from typing import Any, Dict, Tuple

_EXPORTS: Dict[str, Tuple[str, str]] = {
    "JournalEntry": ("tools.distill.models_legacy", "JournalEntry"),
    "DistillSession": ("tools.distill.models_legacy", "DistillSession"),
    "RescueLoop": ("tools.distill.models_legacy", "RescueLoop"),
    "NegativeConstraint": ("tools.distill.models_legacy", "NegativeConstraint"),
    "DiffPattern": ("tools.distill.models_playbook", "DiffPattern"),
    "PlaybookProposal": ("tools.distill.models_playbook", "PlaybookProposal"),
    "DistillReport": ("tools.distill.models_playbook", "DistillReport"),
    "StationEscapeSignal": ("tools.distill.models_signals", "StationEscapeSignal"),
    "ToolFrictionSignal": ("tools.distill.models_signals", "ToolFrictionSignal"),
    "RepeatedEscalation": ("tools.distill.models_signals", "RepeatedEscalation"),
    "_extract_meaningful_error_snippet": ("tools.distill.models_signals", "_extract_meaningful_error_snippet"),
    "_format_escalation_quotes": ("tools.distill.models_signals", "_format_escalation_quotes"),
    "NavigationFrictionSignal": ("tools.distill.models_economy", "NavigationFrictionSignal"),
    "GuardrailGapSignal": ("tools.distill.models_economy", "GuardrailGapSignal"),
    "RuleInventoryItem": ("tools.distill.models_economy", "RuleInventoryItem"),
    "CandidateRule": ("tools.distill.models_candidates", "CandidateRule"),
    "DistillWatermarkState": ("tools.distill.models_candidates", "DistillWatermarkState"),
    "FrictionDigest": ("tools.distill.models_digest", "FrictionDigest"),
    "_render_escalations_toon": ("tools.distill.models_toon", "_render_escalations_toon"),
    "_cap_section_lines": ("tools.distill.models_toon", "_cap_section_lines"),
    "_render_tool_frictions_toon": ("tools.distill.models_toon", "_render_tool_frictions_toon"),
    "_render_escapes_toon": ("tools.distill.models_toon", "_render_escapes_toon"),
    "_render_insights_toon": ("tools.distill.models_toon", "_render_insights_toon"),
    "_render_navigation_frictions_toon": ("tools.distill.models_toon", "_render_navigation_frictions_toon"),
    "_render_guardrail_gaps_toon": ("tools.distill.models_toon", "_render_guardrail_gaps_toon"),
    "_render_rule_inventory_toon": ("tools.distill.models_toon", "_render_rule_inventory_toon"),
    "_render_factory_inbox_toon": ("tools.distill.models_toon", "_render_factory_inbox_toon"),
    "_render_churn_and_critiques_toon": ("tools.distill.models_toon", "_render_churn_and_critiques_toon"),
    "_allocate_section_budgets": ("tools.distill.models_toon", "_allocate_section_budgets"),
    "_truncate_toon_output": ("tools.distill.models_toon", "_truncate_toon_output"),
}
__all__ = [k for k in _EXPORTS if not k.startswith("_")]


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(target[0]), target[1])
