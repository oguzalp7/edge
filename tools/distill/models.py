#!/usr/bin/env python3
"""
Data models for edge-distill: Pattern & Playbook Miner & Zero-Token Harvester.
Encapsulates:
- v2 signals: StationEscapeSignal, ToolFrictionSignal, RepeatedEscalation, CandidateRule
- v2 state & digest: DistillWatermarkState, FrictionDigest (with TOON format)
- Legacy compatibility models: JournalEntry, DistillSession, RescueLoop, NegativeConstraint, DiffPattern, PlaybookProposal, DistillReport
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import hashlib


# ---------------------------------------------------------------------------
# Legacy v1 Models (Retained for Backward Compatibility)
# ---------------------------------------------------------------------------

@dataclass
class JournalEntry:
    entry_id: str
    timestamp: str
    step: str
    tag: str = "OBSERVATION"
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JournalEntry":
        return cls(**data)


@dataclass
class DistillSession:
    session_id: str
    repo_path: str
    started_at: str
    status: str = "RECORDING"
    goal: str = ""
    operational_domain: str = "reconcile"
    baseline_commit: Optional[str] = None
    final_commit: Optional[str] = None
    resolved_at: Optional[str] = None
    journal_entries: List[JournalEntry] = field(default_factory=list)
    initial_metrics: Dict[str, Any] = field(default_factory=dict)
    resolution_notes: Optional[str] = None
    proposal_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "repo_path": self.repo_path,
            "started_at": self.started_at,
            "status": self.status,
            "goal": self.goal,
            "operational_domain": self.operational_domain,
            "baseline_commit": self.baseline_commit,
            "final_commit": self.final_commit,
            "resolved_at": self.resolved_at,
            "journal_entries": [j.to_dict() for j in self.journal_entries],
            "initial_metrics": self.initial_metrics,
            "resolution_notes": self.resolution_notes,
            "proposal_path": self.proposal_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillSession":
        raw = dict(data)
        if "journal_entries" in raw:
            raw["journal_entries"] = [JournalEntry.from_dict(j) for j in raw["journal_entries"]]
        return cls(**raw)


@dataclass
class RescueLoop:
    loop_id: str
    stage: str
    symptom: str
    root_cause: str
    remediation: str
    rule_enforced: str
    verification_cmd: str
    occurred_at: Optional[str] = None
    resolved_at: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RescueLoop":
        return cls(**data)


@dataclass
class NegativeConstraint:
    constraint_id: str
    rule_id: str
    title: str
    anti_pattern: str
    risk: str
    required_pattern: str
    severity: str = "CRITICAL"
    source: str = "ledger"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NegativeConstraint":
        return cls(**data)


@dataclass
class DiffPattern:
    domain: str
    target_file: str
    scaffolded_files: List[str] = field(default_factory=list)
    before_code: str = ""
    after_code: str = ""
    diff_hunks: List[str] = field(default_factory=list)
    pattern_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiffPattern":
        return cls(**data)


@dataclass
class PlaybookProposal:
    proposal_id: str
    domain_name: str
    title: str
    summary: str
    crisis_context: str
    chronological_steps: List[JournalEntry] = field(default_factory=list)
    two_headed_divergence_analysis: Dict[str, Any] = field(default_factory=dict)
    seam_establishment_recipes: List[str] = field(default_factory=list)
    rescue_loops: List[RescueLoop] = field(default_factory=list)
    negative_constraints: List[NegativeConstraint] = field(default_factory=list)
    diff_patterns: List[DiffPattern] = field(default_factory=list)
    proposed_rules: List[str] = field(default_factory=list)
    verification_checklist: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "domain_name": self.domain_name,
            "title": self.title,
            "summary": self.summary,
            "crisis_context": self.crisis_context,
            "chronological_steps": [c.to_dict() for c in self.chronological_steps],
            "two_headed_divergence_analysis": self.two_headed_divergence_analysis,
            "seam_establishment_recipes": list(self.seam_establishment_recipes),
            "rescue_loops": [r.to_dict() for r in self.rescue_loops],
            "negative_constraints": [n.to_dict() for n in self.negative_constraints],
            "diff_patterns": [d.to_dict() for d in self.diff_patterns],
            "proposed_rules": list(self.proposed_rules),
            "verification_checklist": list(self.verification_checklist),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlaybookProposal":
        raw = dict(data)
        if "chronological_steps" in raw:
            raw["chronological_steps"] = [JournalEntry.from_dict(c) for c in raw["chronological_steps"]]
        if "rescue_loops" in raw:
            raw["rescue_loops"] = [RescueLoop.from_dict(r) for r in raw["rescue_loops"]]
        if "negative_constraints" in raw:
            raw["negative_constraints"] = [NegativeConstraint.from_dict(n) for n in raw["negative_constraints"]]
        if "diff_patterns" in raw:
            raw["diff_patterns"] = [DiffPattern.from_dict(d) for d in raw["diff_patterns"]]
        return cls(**raw)


@dataclass
class DistillReport:
    domain: str
    track: str = "core"
    target_file: str = ""
    scaffolded_files: List[str] = field(default_factory=list)
    base_branch: str = "feat/nextjs-clean-monolith"
    active_branch: Optional[str] = None
    ticket_id: Optional[str] = None
    rescue_loops: List[RescueLoop] = field(default_factory=list)
    negative_constraints: List[NegativeConstraint] = field(default_factory=list)
    diff_patterns: List[DiffPattern] = field(default_factory=list)
    compiler_fixes: List[Dict[str, Any]] = field(default_factory=list)
    test_seams: List[Dict[str, Any]] = field(default_factory=list)
    resolved_debt_items: List[Dict[str, Any]] = field(default_factory=list)
    session: Optional[DistillSession] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    playbook_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "track": self.track,
            "target_file": self.target_file,
            "scaffolded_files": list(self.scaffolded_files),
            "base_branch": self.base_branch,
            "active_branch": self.active_branch,
            "ticket_id": self.ticket_id,
            "rescue_loops": [r.to_dict() for r in self.rescue_loops],
            "negative_constraints": [n.to_dict() for n in self.negative_constraints],
            "diff_patterns": [d.to_dict() for d in self.diff_patterns],
            "compiler_fixes": list(self.compiler_fixes),
            "test_seams": list(self.test_seams),
            "resolved_debt_items": list(self.resolved_debt_items),
            "session": self.session.to_dict() if self.session else None,
            "created_at": self.created_at,
            "playbook_path": self.playbook_path,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillReport":
        raw = dict(data)
        if "rescue_loops" in raw:
            raw["rescue_loops"] = [RescueLoop.from_dict(r) for r in raw["rescue_loops"]]
        if "negative_constraints" in raw:
            raw["negative_constraints"] = [NegativeConstraint.from_dict(n) for n in raw["negative_constraints"]]
        if "diff_patterns" in raw:
            raw["diff_patterns"] = [DiffPattern.from_dict(d) for d in raw["diff_patterns"]]
        if "session" in raw and raw["session"]:
            raw["session"] = DistillSession.from_dict(raw["session"])
        return cls(**raw)


# ---------------------------------------------------------------------------
# v2 Models (Signals, Watermark State, Candidate Rules, Friction Digest)
# ---------------------------------------------------------------------------

@dataclass
class StationEscapeSignal:
    signal_id: str
    station_role: str
    escape_type: str
    description: str
    evidence: str
    timestamp: str
    conversation_id: str
    step_index: Optional[int] = None
    ticket_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StationEscapeSignal":
        return cls(**data)

    def to_toon(self) -> str:
        cid_short = self.conversation_id[:8] if self.conversation_id else "unknown"
        step_str = f"step {self.step_index}" if self.step_index is not None else "step ?"
        return f"- [ESCAPE:{self.station_role}] {self.escape_type}: {self.description} ({step_str}, {cid_short})"


def _extract_meaningful_error_snippet(error_output: str, max_len: int = 80) -> str:
    """Selects the last meaningful error-bearing line from log tails, falling back cleanly."""
    if "Log tail:\n" in error_output:
        tail = error_output.split("Log tail:\n", 1)[1]
        lines = [ln.strip() for ln in tail.splitlines() if ln.strip()]
        if lines:
            markers = ("error", "exception", "traceback", "fail", "fatal", "killed", "panic")
            for ln in reversed(lines):
                if any(m in ln.lower() for m in markers):
                    return ln[:max_len]
            return lines[-1][:max_len]
    return " ".join(error_output.strip().splitlines())[:max_len]


@dataclass
class ToolFrictionSignal:
    signal_id: str
    tool_name: str
    command_or_args: str
    error_output: str
    conversation_id: str
    step_index: int
    timestamp: str
    exit_code: Optional[int] = None
    error_type: str = "COMMAND_FAILURE"
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolFrictionSignal":
        return cls(**data)

    @property
    def command(self) -> str:
        return self.command_or_args

    def to_toon(self) -> str:
        cmd_short = self.command_or_args.strip().replace("\n", " ")[:60]
        err_short = _extract_meaningful_error_snippet(self.error_output, max_len=80)
        return f"- [TOOL:{self.tool_name}] exit={self.exit_code} retries={self.retry_count}: {cmd_short} -> {err_short}"


def _format_escalation_quotes(occurrences: List[Dict[str, Any]], max_quotes: int = 2) -> str:
    """Extracts up to max_quotes normalized, 80-char-truncated user quote snippets."""
    quotes: List[str] = []
    for occ in occurrences:
        if not isinstance(occ, dict):
            continue
        raw = str(occ.get("text", "")).strip()
        if not raw:
            continue
        norm = " ".join(raw.split())[:80]
        quotes.append(f'"{norm}"')
        if len(quotes) >= max_quotes:
            break
    if not quotes:
        return ""
    return f" | quotes: {'; '.join(quotes)}"


@dataclass
class RepeatedEscalation:
    escalation_id: str
    category: str
    pattern_key: str
    occurrence_count: int
    occurrences: List[Dict[str, Any]] = field(default_factory=list)
    rule_recommendation: Optional[str] = None
    target_role: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepeatedEscalation":
        return cls(**data)

    def to_toon(self) -> str:
        target = f"target={self.target_role}" if self.target_role else "target=all"
        rec = f" -> {self.rule_recommendation}" if self.rule_recommendation else ""
        quotes_str = _format_escalation_quotes(self.occurrences)
        return f"- [ESCALATION:{self.category}] count={self.occurrence_count} {target}: {self.pattern_key}{rec}{quotes_str}"


@dataclass
class NavigationFrictionSignal:
    """Deterministic navigation friction and token-economy signal."""

    signal_type: str
    session_id: str
    role: str = "unknown"
    step_index: int = 0
    file_paths: List[str] = field(default_factory=list)
    count: int = 0
    metric_value: int = 0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NavigationFrictionSignal":
        return cls(
            signal_type=str(data["signal_type"]),
            session_id=str(data["session_id"]),
            role=str(data.get("role", "unknown")),
            step_index=int(data.get("step_index", 0)),
            file_paths=list(data.get("file_paths") or []),
            count=int(data.get("count", 0)),
            metric_value=int(data.get("metric_value", 0)),
            summary=str(data.get("summary", "")),
        )

    def to_toon(self) -> str:
        sid = self.session_id[:8] if self.session_id else "unknown"
        clean_summary = " ".join(self.summary.split())
        return (
            f"- [NAV:{self.signal_type}] session={sid} role={self.role} "
            f"step={self.step_index} count={self.count} metric={self.metric_value}: {clean_summary}"
        )


@dataclass
class GuardrailGapSignal:
    """Deterministic unwired or missing CI/pre-commit guardrail signal."""

    gap_type: str
    source_file: str
    script_or_check: str
    summary: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GuardrailGapSignal":
        return cls(
            gap_type=str(data["gap_type"]),
            source_file=str(data.get("source_file", "")),
            script_or_check=str(data.get("script_or_check", "")),
            summary=str(data.get("summary", "")),
        )

    def to_toon(self) -> str:
        return f"- [GUARDRAIL:{self.gap_type}] {self.source_file} ({self.script_or_check}): {self.summary}"


@dataclass
class RuleInventoryItem:
    """Line budget and session citation telemetry for a station/agent rubric file."""

    file_path: str
    line_count: int
    budget_limit: Optional[int] = None
    citation_count: int = 0
    status: str = "OK"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuleInventoryItem":
        return cls(
            file_path=str(data["file_path"]),
            line_count=int(data.get("line_count", 0)),
            budget_limit=data.get("budget_limit"),
            citation_count=int(data.get("citation_count", 0)),
            status=str(data.get("status", "OK")),
        )

    def to_toon(self) -> str:
        lim = str(self.budget_limit) if self.budget_limit is not None else "none"
        return f"- [RULE:{self.status}] {self.file_path} lines={self.line_count}/{lim} citations={self.citation_count}"


@dataclass
class CandidateRule:
    candidate_id: str
    fingerprint: str
    rule_text: str
    target_role: str
    scope_class: str
    stack_tokens_matched: List[str] = field(default_factory=list)
    first_seen_at: str = ""
    last_seen_at: str = ""
    source_projects: List[str] = field(default_factory=list)
    occurrence_count: int = 1
    status: str = "INCUBATING"
    evidence: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateRule":
        return cls(**data)

    def to_toon(self) -> str:
        proj_count = len(self.source_projects)
        return f"- [CANDIDATE:{self.candidate_id}] role={self.target_role} status={self.status} projects={proj_count}: {self.rule_text}"


@dataclass
class DistillWatermarkState:
    version: str = "2.1"
    last_harvested_at: str = ""
    processed_sessions: List[str] = field(default_factory=list)
    project_sessions: Dict[str, List[str]] = field(default_factory=dict)
    factory_processed_sessions: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "last_harvested_at": self.last_harvested_at,
            "processed_sessions": list(self.processed_sessions),
            "project_sessions": {k: list(v) for k, v in self.project_sessions.items()},
            "factory_processed_sessions": list(self.factory_processed_sessions),
            "metrics": dict(self.metrics),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillWatermarkState":
        raw = dict(data)
        if "factory_processed_sessions" not in raw:
            raw["factory_processed_sessions"] = []
        if "project_sessions" not in raw:
            raw["project_sessions"] = {}
        if "processed_sessions" not in raw:
            raw["processed_sessions"] = []
        if "metrics" not in raw:
            raw["metrics"] = {}
        return cls(**raw)


def _render_escalations_toon(escalations: List[RepeatedEscalation]) -> Optional[str]:
    if not escalations:
        return None
    lines = ["\n## Repeated Escalations"]
    for esc in escalations:
        lines.append(esc.to_toon())
    return "\n".join(lines)


def _cap_section_lines(header: str, item_lines: List[str], limit: int = 5) -> Optional[str]:
    """Caps rendered entries in a TOON section and appends (+N more) if truncated."""
    if not item_lines:
        return None
    lines = [header] + item_lines[:limit]
    if len(item_lines) > limit:
        lines.append(f"- ... (+{len(item_lines) - limit} more)")
    return "\n".join(lines)


def _render_tool_frictions_toon(tool_frictions: List[ToolFrictionSignal]) -> Optional[str]:
    if not tool_frictions:
        return None
    clusters: Dict[str, Dict[str, Any]] = {}
    for tf in tool_frictions:
        cmd_core = tf.command_or_args.strip().split("\n")[0][:40]
        key = f"{tf.tool_name}:{tf.exit_code}:{cmd_core}"
        if key not in clusters:
            err_snip = _extract_meaningful_error_snippet(tf.error_output, max_len=80)
            clusters[key] = {
                "tool_name": tf.tool_name,
                "exit_code": tf.exit_code,
                "cmd": cmd_core,
                "err": err_snip,
                "count": 0,
            }
        clusters[key]["count"] += 1

    item_lines: List[str] = []
    for c in clusters.values():
        cnt = c["count"]
        rep = f" (repeated {cnt}x)" if cnt > 1 else ""
        item_lines.append(f"- [TOOL:{c['tool_name']}] exit={c['exit_code']}{rep}: {c['cmd']} -> {c['err']}")
    return _cap_section_lines("\n## Tool Frictions", item_lines, limit=5)


def _render_escapes_toon(station_escapes: List[StationEscapeSignal]) -> Optional[str]:
    item_lines = [esc.to_toon() for esc in station_escapes]
    return _cap_section_lines("\n## Station Escapes", item_lines, limit=5)


def _pick_first_str(*values: Any) -> str:
    for v in values:
        if v:
            s = str(v).strip()
            if s:
                return s
    return ""


def _format_insight_details(details: Any) -> str:
    if isinstance(details, dict) and details:
        return ", ".join(f"{k}={v}" for k, v in list(details.items())[:3])
    if details and not isinstance(details, dict):
        return str(details).strip()[:60]
    return ""


def _format_guard_failure_insight(insight: Dict[str, Any]) -> Optional[str]:
    gf = insight.get("guard_failure")
    gf_dict = gf if isinstance(gf, dict) else {}
    state = _pick_first_str(insight.get("state"), gf_dict.get("state"))
    message = _pick_first_str(insight.get("message"), gf_dict.get("message"))
    details = insight.get("details")
    if details is None:
        details = gf_dict.get("details")

    head_parts = [p for p in (state, message) if p]
    head = ": ".join(head_parts) if head_parts else _pick_first_str(gf)
    det_str = _format_insight_details(details)
    if det_str and head:
        return f"- [GUARD_FAIL] {head} ({det_str})"
    if det_str or head:
        return f"- [GUARD_FAIL] {head or det_str}"
    return None


def _format_dead_end_insight(insight: Dict[str, Any]) -> Optional[str]:
    details = insight.get("details")
    det_dict = details if isinstance(details, dict) else {}
    title = _pick_first_str(
        insight.get("title"),
        insight.get("approach"),
        insight.get("dead_end"),
        det_dict.get("title"),
        det_dict.get("approach"),
    )
    reason = _pick_first_str(insight.get("reason"), det_dict.get("reason"))
    rule = _pick_first_str(insight.get("prohibited_rule"), det_dict.get("prohibited_rule"))

    parts: List[str] = []
    if title:
        parts.append(title)
    if reason:
        parts.append(f"reason={reason}")
    if rule:
        parts.append(f"rule={rule}")
    return f"- [DEAD_END] {' | '.join(parts)}" if parts else None


def _render_single_insight_toon(insight: Dict[str, Any]) -> Optional[str]:
    if not isinstance(insight, dict):
        text = str(insight).strip()
        return f"- [DEAD_END] {text}" if text else None
    kind = str(insight.get("kind", "")).lower()
    if kind == "guard_failure" or (not kind and "guard_failure" in insight):
        return _format_guard_failure_insight(insight)
    return _format_dead_end_insight(insight)


def _render_insights_toon(flight_recorder_insights: List[Dict[str, Any]]) -> Optional[str]:
    if not flight_recorder_insights:
        return None
    item_lines: List[str] = []
    for insight in flight_recorder_insights:
        line = _render_single_insight_toon(insight)
        if line:
            item_lines.append(line)
    return _cap_section_lines("\n## Flight Recorder Insights", item_lines, limit=5)


def _render_navigation_frictions_toon(
    navigation_frictions: List[NavigationFrictionSignal],
    total_tokens_estimate: int = 0,
) -> Optional[str]:
    if not navigation_frictions and total_tokens_estimate <= 0:
        return None
    header = "\n## Navigation & Tool Economy"
    if total_tokens_estimate > 0:
        header = f"\n## Navigation & Tool Economy (est_tokens={total_tokens_estimate})"
    if not navigation_frictions:
        return header
    item_lines = [sig.to_toon() for sig in navigation_frictions]
    return _cap_section_lines(header, item_lines, limit=5)


def _render_guardrail_gaps_toon(guardrail_gaps: List[GuardrailGapSignal]) -> Optional[str]:
    item_lines = [gap.to_toon() for gap in guardrail_gaps]
    return _cap_section_lines("\n## Guardrail Gaps", item_lines, limit=5)


def _render_rule_inventory_toon(rule_inventory: List[RuleInventoryItem]) -> Optional[str]:
    item_lines = [item.to_toon() for item in rule_inventory]
    return _cap_section_lines("\n## Rule Inventory", item_lines, limit=5)


def _render_factory_inbox_toon(factory_inbox_signals: List[Dict[str, Any]]) -> Optional[str]:
    item_lines = [
        f"- [{sig.get('signal_id', '')}] ({sig.get('role_or_tool', '')}) {sig.get('summary', '')}"
        for sig in factory_inbox_signals
    ]
    return _cap_section_lines("\n## Factory Inbox Signals", item_lines, limit=5)


def _render_churn_and_critiques_toon(git_churn: List[Dict[str, Any]], critique_findings: List[Dict[str, Any]]) -> List[str]:
    result: List[str] = []
    churn_sec = _cap_section_lines(
        "\n## Git Churn",
        [f"- [CHURN] {c.get('commit', '')}: {c.get('message', '')}" for c in git_churn],
        limit=5,
    )
    if churn_sec:
        result.append(churn_sec)

    crit_sec = _cap_section_lines(
        "\n## Critique Findings",
        [f"- [CRITIQUE] {c.get('spec', '')}: {c.get('finding', '')}" for c in critique_findings],
        limit=5,
    )
    if crit_sec:
        result.append(crit_sec)
    return result


def _allocate_section_budgets(lengths: List[int], total_budget: int) -> List[int]:
    """Water-filling budget allocation so small sections are never starved by huge ones."""
    budgets = [0] * len(lengths)
    remaining = max(0, total_budget)
    sorted_indices = sorted(range(len(lengths)), key=lambda i: lengths[i])
    total_count = len(sorted_indices)
    for pos, idx in enumerate(sorted_indices):
        share = remaining // (total_count - pos)
        alloc = min(lengths[idx], share)
        budgets[idx] = alloc
        remaining -= alloc
    return budgets


def _truncate_toon_output(base: str, sections: List[str], max_chars: int) -> str:
    if not sections:
        return base[:max_chars]
    sep_overhead = len(sections) + 2
    remaining = max_chars - len(base) - sep_overhead
    if remaining <= 0:
        return base[:max_chars]

    budgets = _allocate_section_budgets([len(s) for s in sections], remaining)
    appended: List[str] = []
    for sec, limit in zip(sections, budgets):
        if len(sec) <= limit:
            appended.append(sec)
        elif limit > 20:
            appended.append(sec[: limit - 16] + "... [truncated]")
        elif limit > 0:
            appended.append(sec[:limit])

    result = f"{base}\n" + "\n".join(appended)
    return result[:max_chars]


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
            "digest_id": self.digest_id,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "generated_at": self.generated_at,
            "sessions_analyzed": list(self.sessions_analyzed),
            "station_escapes": [e.to_dict() for e in self.station_escapes],
            "tool_frictions": [f.to_dict() for f in self.tool_frictions],
            "repeated_escalations": [r.to_dict() for r in self.repeated_escalations],
            "flight_recorder_insights": list(self.flight_recorder_insights),
            "git_churn": list(self.git_churn),
            "critique_findings": list(self.critique_findings),
            "total_tokens_estimate": self.total_tokens_estimate,
            "harness_signals_queued": self.harness_signals_queued,
            "factory_inbox_signals": list(self.factory_inbox_signals),
            "navigation_frictions": [n.to_dict() for n in self.navigation_frictions],
            "guardrail_gaps": [g.to_dict() for g in self.guardrail_gaps],
            "rule_inventory": [ri.to_dict() for ri in self.rule_inventory],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FrictionDigest":
        raw = dict(data)
        if "station_escapes" in raw:
            raw["station_escapes"] = [StationEscapeSignal.from_dict(e) for e in raw["station_escapes"]]
        if "tool_frictions" in raw:
            raw["tool_frictions"] = [ToolFrictionSignal.from_dict(f) for f in raw["tool_frictions"]]
        if "repeated_escalations" in raw:
            raw["repeated_escalations"] = [RepeatedEscalation.from_dict(r) for r in raw["repeated_escalations"]]
        raw["navigation_frictions"] = [NavigationFrictionSignal.from_dict(n) for n in raw.get("navigation_frictions", [])]
        raw["guardrail_gaps"] = [GuardrailGapSignal.from_dict(g) for g in raw.get("guardrail_gaps", [])]
        raw["rule_inventory"] = [RuleInventoryItem.from_dict(ri) for ri in raw.get("rule_inventory", [])]
        raw.setdefault("harness_signals_queued", 0)
        raw.setdefault("factory_inbox_signals", [])
        return cls(**raw)

    def to_toon(self, max_tokens: int = 2000) -> str:
        max_chars = max_tokens * 4
        header = (
            f"# FrictionDigest: {self.project_name} ({self.digest_id})\n"
            f"Sessions: {len(self.sessions_analyzed)} | Generated: {self.generated_at}"
        )

        sec_escalations = _render_escalations_toon(self.repeated_escalations)
        base = f"{header}\n{sec_escalations}" if sec_escalations else header

        candidates = [
            _render_factory_inbox_toon(self.factory_inbox_signals),
            _render_navigation_frictions_toon(self.navigation_frictions, self.total_tokens_estimate),
            _render_guardrail_gaps_toon(self.guardrail_gaps),
            _render_rule_inventory_toon(self.rule_inventory),
            _render_tool_frictions_toon(self.tool_frictions),
            _render_escapes_toon(self.station_escapes),
            _render_insights_toon(self.flight_recorder_insights),
        ]
        other_sections = [s for s in candidates if s]
        other_sections.extend(_render_churn_and_critiques_toon(self.git_churn, self.critique_findings))

        full_text = f"{base}\n" + "\n".join(other_sections)
        if len(full_text) <= max_chars:
            return full_text

        return _truncate_toon_output(base, other_sections, max_chars)
