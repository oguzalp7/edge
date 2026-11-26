"""FrictionDigest container and TOON/dict serialization."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from tools.distill.models_economy import GuardrailGapSignal, NavigationFrictionSignal, RuleInventoryItem
from tools.distill.models_signals import RepeatedEscalation, StationEscapeSignal, ToolFrictionSignal
from tools.distill.models_toon import (
    _render_churn_and_critiques_toon,
    _render_escalations_toon,
    _render_escapes_toon,
    _render_factory_inbox_toon,
    _render_guardrail_gaps_toon,
    _render_insights_toon,
    _render_navigation_frictions_toon,
    _render_rule_inventory_toon,
    _render_tool_frictions_toon,
    _truncate_toon_output,
)


@dataclass
class FrictionDigest:
    digest_id: str
    project_path: str
    project_name: str
    generated_at: str
    sessions_analyzed: List[str] = field(default_factory=list)
    station_escapes: List[StationEscapeSignal] = field(default_factory=list)
    tool_frictions: List[ToolFrictionSignal] = field(default_factory=list)
    repeated_escalations: List[RepeatedEscalation] = field(default_factory=list)
    flight_recorder_insights: List[Dict[str, Any]] = field(default_factory=list)
    git_churn: List[Dict[str, Any]] = field(default_factory=list)
    critique_findings: List[Dict[str, Any]] = field(default_factory=list)
    total_tokens_estimate: int = 0
    harness_signals_queued: int = 0
    factory_inbox_signals: List[Dict[str, Any]] = field(default_factory=list)
    navigation_frictions: List[NavigationFrictionSignal] = field(default_factory=list)
    guardrail_gaps: List[GuardrailGapSignal] = field(default_factory=list)
    rule_inventory: List[RuleInventoryItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            **asdict(self),
            "station_escapes": [e.to_dict() for e in self.station_escapes],
            "tool_frictions": [f.to_dict() for f in self.tool_frictions],
            "repeated_escalations": [r.to_dict() for r in self.repeated_escalations],
            "navigation_frictions": [n.to_dict() for n in self.navigation_frictions],
            "guardrail_gaps": [g.to_dict() for g in self.guardrail_gaps],
            "rule_inventory": [ri.to_dict() for ri in self.rule_inventory],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FrictionDigest":
        raw = dict(data)
        for k, cls_t in (("station_escapes", StationEscapeSignal), ("tool_frictions", ToolFrictionSignal), ("repeated_escalations", RepeatedEscalation)):
            if k in raw:
                raw[k] = [cls_t.from_dict(x) for x in raw[k]]
        raw["navigation_frictions"] = [NavigationFrictionSignal.from_dict(n) for n in raw.get("navigation_frictions", [])]
        raw["guardrail_gaps"] = [GuardrailGapSignal.from_dict(g) for g in raw.get("guardrail_gaps", [])]
        raw["rule_inventory"] = [RuleInventoryItem.from_dict(ri) for ri in raw.get("rule_inventory", [])]
        raw.setdefault("harness_signals_queued", 0)
        raw.setdefault("factory_inbox_signals", [])
        return cls(**raw)

    def to_toon(self, max_tokens: int = 2000) -> str:
        max_chars = max_tokens * 4
        header = f"# FrictionDigest: {self.project_name} ({self.digest_id})\nSessions: {len(self.sessions_analyzed)} | Generated: {self.generated_at}"
        sec_esc = _render_escalations_toon(self.repeated_escalations)
        base = f"{header}\n{sec_esc}" if sec_esc else header
        candidates = [
            _render_factory_inbox_toon(self.factory_inbox_signals),
            _render_navigation_frictions_toon(self.navigation_frictions, self.total_tokens_estimate),
            _render_guardrail_gaps_toon(self.guardrail_gaps),
            _render_rule_inventory_toon(self.rule_inventory),
            _render_tool_frictions_toon(self.tool_frictions),
            _render_escapes_toon(self.station_escapes),
            _render_insights_toon(self.flight_recorder_insights),
        ]
        other_sections = [s for s in candidates if s] + _render_churn_and_critiques_toon(self.git_churn, self.critique_findings)
        full_text = f"{base}\n" + "\n".join(other_sections)
        return full_text if len(full_text) <= max_chars else _truncate_toon_output(base, other_sections, max_chars)
