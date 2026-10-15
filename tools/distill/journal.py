#!/usr/bin/env python3
"""
Operational Flight Recorder & Journal Manager for edge-distill.
Maintains continuous recording of complex incident interventions,
from the start of the crisis until the 'problem resolved' sign-off.
"""

import sys
import os
import json
from pathlib import Path
from typing import Optional, Union, Dict, Any, List
from datetime import datetime, timezone
import hashlib

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import normalize_target_path, run_command
from tools.distill.models import DistillSession, JournalEntry


class DistillJournal:
    """
    Manages the lifecycle of live incident sessions and operational journals.
    """

    def __init__(self, repo_path: Union[str, Path]):
        self.repo_path = normalize_target_path(repo_path)
        self.distill_dir = self.repo_path / ".edge" / "distill"
        self.distill_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.distill_dir / "session.json"
        self.archive_dir = self.distill_dir / "archive"

    def _run_git(self, args: List[str]) -> str:
        code, stdout, _ = run_command(["git"] + args, cwd=self.repo_path)
        return stdout.strip() if code == 0 else ""

    def get_active_session(self) -> Optional[DistillSession]:
        """Loads active session if one exists."""
        if not self.session_file.exists():
            return None
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return DistillSession.from_dict(data)
        except Exception:
            return None

    def start_session(
        self,
        goal: str,
        operational_domain: str = "reconcile",
        session_id: Optional[str] = None,
    ) -> DistillSession:
        """
        Starts a continuous recording period.
        Records baseline git commit, branch, and initial environment state.
        """
        # Archive prior completed or abandoned session if present
        existing = self.get_active_session()
        if existing and existing.status == "RECORDING":
            print(f"⚠️ Active session '{existing.session_id}' already recording. Continuing with existing session.")
            return existing

        now_iso = datetime.now(timezone.utc).isoformat()
        current_sha = self._run_git(["rev-parse", "HEAD"]) or "UNKNOWN_HEAD"
        current_branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"]) or "main"
        status_porcelain = self._run_git(["status", "--porcelain"])

        sid = session_id or f"SESS-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

        initial_metrics = {
            "branch": current_branch,
            "baseline_sha": current_sha,
            "has_uncommitted_changes": bool(status_porcelain),
            "uncommitted_files_count": len(status_porcelain.splitlines()) if status_porcelain else 0,
        }

        first_entry = JournalEntry(
            entry_id=f"JE-1",
            timestamp=now_iso,
            step=f"Engaged flight recorder. Operational Goal: {goal}",
            tag="OBSERVATION",
            details=initial_metrics,
        )

        session = DistillSession(
            session_id=sid,
            repo_path=str(self.repo_path),
            started_at=now_iso,
            status="RECORDING",
            goal=goal,
            operational_domain=operational_domain or "reconcile",
            baseline_commit=current_sha,
            journal_entries=[first_entry],
            initial_metrics=initial_metrics,
        )

        self.save(session)
        return session

    def log_step(
        self,
        step: str,
        tag: str = "OBSERVATION",
        details: Optional[Dict[str, Any]] = None,
    ) -> JournalEntry:
        """
        Appends an action, discovery, seam addition, or fix to the continuous journal.
        """
        session = self.get_active_session()
        if not session or session.status != "RECORDING":
            # Auto-start default session if logging without explicit start
            session = self.start_session(goal="Ad-hoc crisis intervention", operational_domain="reconcile")

        entry_num = len(session.journal_entries) + 1
        now_iso = datetime.now(timezone.utc).isoformat()

        entry = JournalEntry(
            entry_id=f"JE-{entry_num}",
            timestamp=now_iso,
            step=step,
            tag=tag.upper(),
            details=details or {},
        )

        session.journal_entries.append(entry)
        self.save(session)
        return entry

    def resolve_session(self, resolution_notes: str = "Problem successfully resolved.") -> DistillSession:
        """
        Marks the session as RESOLVED upon user/developer confirmation.
        Locks final commit and prepares data for playbook proposal generation.
        """
        session = self.get_active_session()
        if not session:
            raise ValueError("No active session found to resolve.")

        final_sha = self._run_git(["rev-parse", "HEAD"]) or "UNKNOWN_FINAL_HEAD"
        now_iso = datetime.now(timezone.utc).isoformat()

        session.status = "RESOLVED"
        session.final_commit = final_sha
        session.resolved_at = now_iso
        session.resolution_notes = resolution_notes

        session.journal_entries.append(
            JournalEntry(
                entry_id=f"JE-{len(session.journal_entries) + 1}",
                timestamp=now_iso,
                step=f"PROBLEM_RESOLVED Sign-off received: {resolution_notes}",
                tag="RESOLVED",
                details={"final_sha": final_sha},
            )
        )

        self.save(session)
        return session

    def abort_session(self, reason: str = "Operation aborted") -> DistillSession:
        """Aborts active session."""
        session = self.get_active_session()
        if not session:
            raise ValueError("No active session found to abort.")

        now_iso = datetime.now(timezone.utc).isoformat()
        session.status = "ABORTED"
        session.resolved_at = now_iso
        session.resolution_notes = f"ABORTED: {reason}"

        session.journal_entries.append(
            JournalEntry(
                entry_id=f"JE-{len(session.journal_entries) + 1}",
                timestamp=now_iso,
                step=f"Session aborted: {reason}",
                tag="ABORTED",
                details={"reason": reason},
            )
        )

        self.save(session)
        return session

    def save(self, session: DistillSession) -> None:
        """Persists session to .edge/distill/session.json."""
        with open(self.session_file, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, indent=2, ensure_ascii=False)
