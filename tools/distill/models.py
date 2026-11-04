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

    def to_toon(self) -> str:
        cmd_short = self.command_or_args.strip().replace("\n", " ")[:60]
        err_short = self.error_output.strip().replace("\n", " ")[:80]
        return f"- [TOOL:{self.tool_name}] exit={self.exit_code} retries={self.retry_count}: {cmd_short} -> {err_short}"


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
        return f"- [ESCALATION:{self.category}] count={self.occurrence_count} {target}: {self.pattern_key}{rec}"


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
    version: str = "2.0"
    last_harvested_at: str = ""
    processed_sessions: List[str] = field(default_factory=list)
    project_sessions: Dict[str, List[str]] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DistillWatermarkState":
        return cls(**data)


def _render_escalations_toon(escalations: List[RepeatedEscalation]) -> Optional[str]:
    if not escalations:
        return None
    lines = ["\n## Repeated Escalations"]
    for esc in escalations:
        lines.append(esc.to_toon())
    return "\n".join(lines)


def _render_tool_frictions_toon(tool_frictions: List[ToolFrictionSignal]) -> Optional[str]:
    if not tool_frictions:
        return None
    lines = ["\n## Tool Frictions"]
    clusters: Dict[str, Dict[str, Any]] = {}
    for tf in tool_frictions:
        cmd_core = tf.command_or_args.strip().split("\n")[0][:40]
        key = f"{tf.tool_name}:{tf.exit_code}:{cmd_core}"
        if key not in clusters:
            clusters[key] = {
                "tool_name": tf.tool_name,
                "exit_code": tf.exit_code,
                "cmd": cmd_core,
                "err": tf.error_output.strip().split("\n")[0][:60],
                "count": 0,
            }
        clusters[key]["count"] += 1

    for c in clusters.values():
        cnt = c["count"]
        if cnt > 1:
            lines.append(f"- [TOOL:{c['tool_name']}] exit={c['exit_code']} (repeated {cnt}x): {c['cmd']} -> {c['err']}")
        else:
            lines.append(f"- [TOOL:{c['tool_name']}] exit={c['exit_code']}: {c['cmd']} -> {c['err']}")
    return "\n".join(lines)


def _render_escapes_toon(station_escapes: List[StationEscapeSignal]) -> Optional[str]:
    if not station_escapes:
        return None
    lines = ["\n## Station Escapes"]
    for esc in station_escapes:
        lines.append(esc.to_toon())
    return "\n".join(lines)


def _render_insights_toon(flight_recorder_insights: List[Dict[str, Any]]) -> Optional[str]:
    if not flight_recorder_insights:
        return None
    lines = ["\n## Flight Recorder Insights"]
    for insight in flight_recorder_insights:
        dead_end = insight.get("dead_end", insight.get("approach", ""))
        lines.append(f"- [INSIGHT] {dead_end}")
    return "\n".join(lines)


def _render_churn_and_critiques_toon(git_churn: List[Dict[str, Any]], critique_findings: List[Dict[str, Any]]) -> List[str]:
    result = []
    if git_churn:
        churn_lines = ["\n## Git Churn"]
        for churn in git_churn:
            churn_lines.append(f"- [CHURN] {churn.get('commit', '')}: {churn.get('message', '')}")
        result.append("\n".join(churn_lines))

    if critique_findings:
        crit_lines = ["\n## Critique Findings"]
        for crit in critique_findings:
            crit_lines.append(f"- [CRITIQUE] {crit.get('spec', '')}: {crit.get('finding', '')}")
        result.append("\n".join(crit_lines))
    return result


def _truncate_toon_output(base: str, sections: List[str], max_chars: int) -> str:
    remaining = max_chars - len(base) - 50
    if remaining <= 0:
        return base[:max_chars]

    appended = []
    for sec in sections:
        if len(sec) < remaining:
            appended.append(sec)
            remaining -= len(sec)
        else:
            appended.append(sec[:remaining] + "... [truncated]")
            break

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
        return cls(**raw)

    def to_toon(self, max_tokens: int = 2000) -> str:
        max_chars = max_tokens * 4
        header = f"# FrictionDigest: {self.project_name} ({self.digest_id})\nSessions: {len(self.sessions_analyzed)} | Generated: {self.generated_at}"

        sec_escalations = _render_escalations_toon(self.repeated_escalations)
        base = f"{header}\n{sec_escalations}" if sec_escalations else header

        other_sections: List[str] = []
        sec_tf = _render_tool_frictions_toon(self.tool_frictions)
        if sec_tf:
            other_sections.append(sec_tf)

        sec_esc = _render_escapes_toon(self.station_escapes)
        if sec_esc:
            other_sections.append(sec_esc)

        sec_fr = _render_insights_toon(self.flight_recorder_insights)
        if sec_fr:
            other_sections.append(sec_fr)

        other_sections.extend(_render_churn_and_critiques_toon(self.git_churn, self.critique_findings))

        full_text = f"{base}\n" + "\n".join(other_sections)
        if len(full_text) <= max_chars:
            return full_text

        return _truncate_toon_output(base, other_sections, max_chars)
