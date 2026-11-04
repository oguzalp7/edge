"""
Living Flight Recorder & Negative Constraints Ledger for Edge Brigade.
Maintains persistent audit logs, dead-end discovery tracking, and negative constraints
so that retry agents or successor stations never repeat failed paths.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from tools.common import normalize_target_path


class FlightRecorder:
    def __init__(self, repo_path: Path, ticket_id: str):
        self.repo_path = normalize_target_path(repo_path)
        self.ticket_id = str(ticket_id)
        self.storage_dir = self.repo_path / ".edge" / "flight-recorder"
        self.json_file = self.storage_dir / f"{self.ticket_id}.json"
        self.md_file = self.storage_dir / f"{self.ticket_id}-learnings.md"
        self.data = self._load_or_init()

    def _load_or_init(self) -> Dict[str, Any]:
        if self.json_file.exists():
            try:
                with open(self.json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "guard_failures" not in data:
                        data["guard_failures"] = []
                    if "review_findings" not in data:
                        data["review_findings"] = []
                    return data
            except Exception:
                pass

        return {
            "ticket_id": self.ticket_id,
            "status": "ACTIVE",  # ACTIVE, PAUSED_ESCALATED, TERMINATED, RESOLVED
            "track": "core",
            "domain": "unknown",
            "target_file": "",
            "worktree_path": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "dead_ends": [],      # List of {id, title, reason, prohibited_rule, failure_output}
            "escalations": [],    # List of {timestamp, reason, decision, resolved_at}
            "attempts": [],       # List of {attempt_num, timestamp, exit_code, summary, diff_stat}
            "guard_failures": [], # List of {state, timestamp, message, details}
            "review_findings": [],# List of serialized ReviewFinding dicts
        }

    def save(self) -> None:
        """Atomically saves the JSON state and synchronizes the markdown living report."""
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        tmp_json = self.json_file.with_suffix(".tmp")
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False, default=str)
        if tmp_json.exists():
            if self.json_file.exists():
                self.json_file.unlink()
            tmp_json.rename(self.json_file)

        self._render_markdown()

    def load(self) -> Dict[str, Any]:
        """Returns the loaded flight recorder data dictionary."""
        return self.data

    def set_metadata(
        self,
        track: str = "core",
        domain: str = "unknown",
        target_file: str = "",
        worktree_path: str = "",
    ) -> None:
        self.data["track"] = track
        self.data["domain"] = domain
        self.data["target_file"] = target_file
        self.data["worktree_path"] = worktree_path
        self.save()

    def record_dead_end(
        self,
        title: str = "",
        reason: str = "",
        prohibited_rule: str = "",
        failure_output: str = "",
        approach: str = "",
        failure_reason: str = "",
        negative_constraint: str = "",
        station: str = "",
    ) -> Dict[str, Any]:
        """Records a proven failed path / architectural trap and its resulting negative constraint."""
        eff_title = title or approach or "Unnamed dead end"
        eff_reason = reason or failure_reason or ""
        eff_rule = prohibited_rule or negative_constraint or ""
        
        idx = len(self.data["dead_ends"]) + 1
        dead_end_id = f"DEAD_END_{idx}"
        entry = {
            "id": dead_end_id,
            "title": eff_title,
            "station": station,
            "reason": eff_reason,
            "prohibited_rule": eff_rule,
            "failure_output": failure_output[:500] if failure_output else "",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.data["dead_ends"].append(entry)
        self.save()
        return entry

    def record_escalation(self, reason: str, station: str = "") -> None:
        """Records an escalation event requiring captain intervention."""
        self.data["status"] = "PAUSED_ESCALATED"
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "station": station,
            "reason": reason,
            "decision": None,
            "resolved_at": None,
        }
        self.data["escalations"].append(entry)
        self.save()

    def record_decision(self, decision: str) -> None:
        """Records captain's resolution to the latest escalation."""
        self.data["status"] = "ACTIVE"
        now = datetime.now(timezone.utc).isoformat()
        if self.data["escalations"]:
            last = self.data["escalations"][-1]
            last["decision"] = decision
            last["resolved_at"] = now
        else:
            self.data["escalations"].append({
                "timestamp": now,
                "reason": "Direct captain decision override",
                "decision": decision,
                "resolved_at": now,
            })
        self.save()

    def record_captain_decision(self, decision: str, decided_by: str = "captain") -> None:
        """Alias for record_decision with captain tracking."""
        self.data["captain_decision"] = {
            "decision": decision,
            "decided_by": decided_by,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        self.record_decision(decision)
        self.data["status"] = "DECIDED"
        self.save()

    def record_attempt(
        self,
        attempt_num: int,
        exit_code: int,
        summary: str,
        diff_stat: str = "",
    ) -> None:
        """Records an iteration attempt result."""
        entry = {
            "attempt_num": attempt_num,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exit_code": exit_code,
            "summary": summary,
            "diff_stat": diff_stat[:300] if diff_stat else "",
        }
        self.data["attempts"].append(entry)
        self.save()

    def record_guard_failure(
        self,
        state: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Atomically appends a failed guard execution record."""
        entry = {
            "state": state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "details": details or {},
        }
        self.data.setdefault("guard_failures", []).append(entry)
        self.save()
        return entry

    def seal_review_findings(
        self,
        findings: List[Any],
    ) -> None:
        """Atomically seals and preserves examiner review findings, deduplicating records."""
        existing = self.data.setdefault("review_findings", [])
        seen_keys = {
            (
                f.get("axis"),
                f.get("file_path"),
                f.get("line_number"),
                f.get("description"),
            )
            for f in existing
        }

        for finding in findings:
            if hasattr(finding, "to_dict"):
                f_dict = finding.to_dict()
            elif isinstance(finding, dict):
                f_dict = dict(finding)
            else:
                f_dict = {"description": str(finding)}

            key = (
                f_dict.get("axis"),
                f_dict.get("file_path"),
                f_dict.get("line_number"),
                f_dict.get("description"),
            )
            if key not in seen_keys:
                seen_keys.add(key)
                existing.append(f_dict)

        self.save()

    def mark_status(self, status: str) -> None:
        """Sets overall ticket lifecycle status (ACTIVE, RESOLVED, TERMINATED, STAGNATED)."""
        self.data["status"] = status
        self.save()

    def get_negative_constraints(self) -> List[str]:
        """Returns the list of string constraints for the ticket."""
        return [de["prohibited_rule"] for de in self.data.get("dead_ends", []) if de.get("prohibited_rule")]

    def get_prompt_alert_block(self) -> str:
        """
        Formats a zero-amnesia negative constraints block to be injected into station prompts.
        """
        dead_ends = self.data.get("dead_ends", [])
        escalations = [e for e in self.data.get("escalations", []) if e.get("decision")]

        if not dead_ends and not escalations:
            return ""

        lines = [
            "\n> [!CAUTION]",
            "> ### 🚫 ZERO-AMNESIA FLIGHT RECORDER: PREVIOUS DEAD-ENDS & CONSTRAINTS",
            "> The following approaches were already tried and proven FATAL. DO NOT REPEAT THEM:",
        ]

        for de in dead_ends:
            lines.append(f"> - **[{de['id']} - {de['title']}]:** {de['prohibited_rule']}")
            lines.append(f">   *Why it failed:* {de['reason']}")

        if escalations:
            lines.append(">")
            lines.append("> ### 👑 BINDING CAPTAIN DECISIONS:")
            for esc in escalations:
                lines.append(f"> - **Decision:** {esc['decision']} *(Context: {esc['reason']})*")

        lines.append("")
        return "\n".join(lines)

    def _render_guard_failures(self, md: List[str]) -> None:
        guard_failures = self.data.get("guard_failures", [])
        if not guard_failures:
            return
        md.extend(["---", "", "## 🛡️ Guard Failures & Verification Blocks"])
        for gf in guard_failures:
            md.append(f"* **[{gf.get('state')}]** (`{gf.get('timestamp')}`): {gf.get('message')}")
            if gf.get("details"):
                md.append(f"  * Details: `{gf.get('details')}`")
        md.append("")

    def _render_review_findings(self, md: List[str]) -> None:
        review_findings = self.data.get("review_findings", [])
        if not review_findings:
            return
        md.extend(["---", "", "## 🧐 Examiner Review Findings Ledger"])
        for rf in review_findings:
            sev = rf.get("severity", "INFO")
            axis = rf.get("axis", "standards")
            fpath = rf.get("file_path", "")
            line = f":{rf.get('line_number')}" if rf.get("line_number") is not None else ""
            md.append(f"* **[{sev}] [{axis.upper()}]** `{fpath}{line}`: {rf.get('description')}")
            if rf.get("rule"):
                md.append(f"  * Rule: `{rf.get('rule')}`")
            if rf.get("suggested_fix"):
                md.append(f"  * Suggested Fix: {rf.get('suggested_fix')}")
        md.append("")

    def _render_markdown(self) -> None:
        """Generates human-readable Markdown post-mortem/living report."""
        status_icons = {
            "ACTIVE": "🟢 ACTIVE",
            "PAUSED_ESCALATED": "⏸️ PAUSED (ESCALATED)",
            "TERMINATED": "🛑 TERMINATED (ABORTED)",
            "RESOLVED": "✅ RESOLVED & LANDED",
            "STAGNATED": "⚠️ STAGNATED",
        }

        md = [
            f"# 📓 Flight Recorder: [{self.ticket_id}]",
            f"- **Status:** {status_icons.get(self.data['status'], self.data['status'])}",
            f"- **Track / Domain:** `{self.data.get('track')}` / `{self.data.get('domain')}`",
            f"- **Target File:** `{self.data.get('target_file')}`",
            f"- **Worktree Path:** `{self.data.get('worktree_path') or 'N/A'}`",
            f"- **Last Updated:** `{self.data.get('updated_at')}`",
            "",
            "---",
            "",
            "## 🚫 Negatif Kısıtlar & Çıkmaz Yollar (Dead Ends)",
        ]

        dead_ends = self.data.get("dead_ends", [])
        if not dead_ends:
            md.append("*Henüz kaydedilmiş negatif kısıt bulunmuyor.*")
        else:
            for de in dead_ends:
                md.append(f"### ❌ {de['id']}: {de['title']}")
                md.append(f"* **Neden Başarısız Oldu:** {de['reason']}")
                md.append(f"* **Yasaklı Kural (Constraint):** `{de['prohibited_rule']}`")
                if de.get("failure_output"):
                    md.append(f"```text\n{de['failure_output']}\n```")
                md.append("")

        md.append("---")
        md.append("")
        md.append("## ⏸️ Escalation & İnsan Kararları (Captain Calls)")
        escalations = self.data.get("escalations", [])
        if not escalations:
            md.append("*Henüz eskalasyon yaşanmadı.*")
        else:
            for i, esc in enumerate(escalations, 1):
                decision_str = f"**Cevap:** {esc['decision']}" if esc.get("decision") else "*(Henüz Cevaplanmadı - BEKLEMEDE)*"
                md.append(f"{i}. **Soru / Neden ({esc['timestamp']}):** {esc['reason']}")
                md.append(f"   - {decision_str}")
                md.append("")

        md.append("---")
        md.append("")
        md.append("## 📊 Deneme Geçmişi (Attempt History)")
        attempts = self.data.get("attempts", [])
        if not attempts:
            md.append("*Henüz deneme kaydı yok.*")
        else:
            for att in attempts:
                icon = "🟢" if att["exit_code"] == 0 else "🔴"
                md.append(f"* {icon} **Attempt {att['attempt_num']}** (Exit: {att['exit_code']}) - `{att['timestamp']}`")
                md.append(f"  * {att['summary']}")
                if att.get("diff_stat"):
                    md.append(f"  * Diff: `{att['diff_stat']}`")

        self._render_guard_failures(md)
        self._render_review_findings(md)

        tmp_md = self.md_file.with_suffix(".tmp")
        with open(tmp_md, "w", encoding="utf-8") as f:
            f.write("\n".join(md) + "\n")
        if tmp_md.exists():
            if self.md_file.exists():
                self.md_file.unlink()
            tmp_md.rename(self.md_file)
