"""Living Flight Recorder & Negative Constraints Ledger for Edge Brigade."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.brigade.flight_io import atomic_save_flight_json, atomic_write_text_file, load_flight_data
from tools.brigade.flight_render import format_prompt_alert_block, render_flight_markdown
from tools.common import normalize_target_path


def _normalize_finding_dict(finding: Any) -> Dict[str, Any]:
    if hasattr(finding, "to_dict"):
        return finding.to_dict()
    if isinstance(finding, dict):
        return dict(finding)
    return {"description": str(finding)}


def _finding_dedup_key(f_dict: Dict[str, Any]) -> tuple:
    return (f_dict.get("axis"), f_dict.get("file_path"), f_dict.get("line_number"), f_dict.get("description"))


class FlightRecorder:
    """Maintains persistent audit logs, dead-end discovery tracking, and negative constraints."""

    def __init__(self, repo_path: Path, ticket_id: str):
        self.repo_path = normalize_target_path(repo_path)
        self.ticket_id = str(ticket_id)
        self.storage_dir = self.repo_path / ".edge" / "flight-recorder"
        self.json_file = self.storage_dir / f"{self.ticket_id}.json"
        self.md_file = self.storage_dir / f"{self.ticket_id}-learnings.md"
        self.data = load_flight_data(self.json_file, self.ticket_id)

    def save(self) -> None:
        """Atomically save JSON state and synchronize the Markdown living report."""
        atomic_save_flight_json(self.json_file, self.data)
        self._render_markdown()

    def load(self) -> Dict[str, Any]:
        """Return loaded flight recorder state dictionary."""
        return self.data

    def set_metadata(
        self, track: str = "core", domain: str = "unknown", target_file: str = "",
        worktree_path: str = "", expected_files: Optional[List[str]] = None,
    ) -> None:
        self.data["track"] = track
        self.data["domain"] = domain
        self.data["target_file"] = target_file
        self.data["worktree_path"] = worktree_path
        if expected_files is not None:
            self.data["expected_files"] = expected_files
        self.save()

    def record_dead_end(
        self, title: str = "", reason: str = "", prohibited_rule: str = "",
        failure_output: str = "", approach: str = "", failure_reason: str = "",
        negative_constraint: str = "", station: str = "", is_abort: bool = False,
    ) -> Dict[str, Any]:
        """Record a failed path and its resulting negative constraint."""
        entry = {
            "id": f"DEAD_END_{len(self.data['dead_ends']) + 1}",
            "title": title or approach or "Unnamed dead end",
            "station": station,
            "reason": reason or failure_reason or "",
            "prohibited_rule": prohibited_rule or negative_constraint or "",
            "failure_output": failure_output[:500] if failure_output else "",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.data["dead_ends"].append(entry)
        if is_abort:
            self.data["status"] = "ABANDONED"
        self.save()
        return entry

    def record_escalation(self, reason: str, station: str = "") -> None:
        """Record an escalation event requiring captain intervention."""
        self.data["status"] = "PAUSED_ESCALATED"
        self.data["escalations"].append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "station": station,
            "reason": reason,
            "decision": None,
            "resolved_at": None,
        })
        self.save()

    def record_decision(self, decision: str) -> None:
        """Record captain resolution for the latest escalation."""
        self.data["status"] = "ACTIVE"
        now = datetime.now(timezone.utc).isoformat()
        if self.data["escalations"]:
            last = self.data["escalations"][-1]
            last["decision"], last["resolved_at"] = decision, now
        else:
            self.data["escalations"].append({"timestamp": now, "reason": "Direct captain decision override", "decision": decision, "resolved_at": now})
        self.save()

    def record_captain_decision(self, decision: str, decided_by: str = "captain") -> None:
        """Record captain decision with attribution and DECIDED status."""
        self.data["captain_decision"] = {"decision": decision, "decided_by": decided_by, "resolved_at": datetime.now(timezone.utc).isoformat()}
        self.record_decision(decision)
        self.data["status"] = "DECIDED"
        self.save()

    def record_attempt(self, attempt_num: int, exit_code: int, summary: str, diff_stat: str = "") -> None:
        """Record an execution attempt result."""
        self.data["attempts"].append({
            "attempt_num": attempt_num,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exit_code": exit_code,
            "summary": summary,
            "diff_stat": diff_stat[:300] if diff_stat else "",
        })
        self.save()

    def record_guard_failure(self, state: str, message: str, details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Atomically append a failed guard execution record."""
        entry = {"state": state, "timestamp": datetime.now(timezone.utc).isoformat(), "message": message, "details": details or {}}
        self.data.setdefault("guard_failures", []).append(entry)
        self.save()
        return entry

    def seal_review_findings(self, findings: List[Any]) -> None:
        """Atomically seal and deduplicate examiner review findings."""
        existing = self.data.setdefault("review_findings", [])
        seen_keys = {_finding_dedup_key(f) for f in existing}
        for finding in findings:
            f_dict = _normalize_finding_dict(finding)
            key = _finding_dedup_key(f_dict)
            if key not in seen_keys:
                seen_keys.add(key)
                existing.append(f_dict)
        self.save()

    def mark_status(self, status: str) -> None:
        """Set overall ticket lifecycle status."""
        self.data["status"] = status
        self.save()

    def get_negative_constraints(self) -> List[str]:
        """Return list of negative constraint strings for this ticket."""
        return [de["prohibited_rule"] for de in self.data.get("dead_ends", []) if de.get("prohibited_rule")]

    def get_prompt_alert_block(self) -> str:
        """Format zero-amnesia negative constraints block for station prompts."""
        return format_prompt_alert_block(self.data)

    def _render_markdown(self) -> str:
        rendered = render_flight_markdown(self.ticket_id, self.data)
        atomic_write_text_file(self.md_file, rendered)
        return rendered
