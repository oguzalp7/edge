#!/usr/bin/env python3
"""
Unit Tests for Brigade Worktree Management and Flight Recorder
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.brigade.models import (
    Ticket,
    CycleState,
    BrigadeState,
    Checkpoint,
)
from tools.brigade.fsm import BrigadeFSM
from tools.brigade.worktree import (
    acquire_worktree,
    return_worktree,
    get_pool_status,
    is_treehouse_installed,
)
from tools.brigade.flight_recorder import FlightRecorder


class TestWorktreeAdapter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("tools.brigade.worktree.run_command")
    def test_is_treehouse_installed(self, mock_run):
        mock_run.return_value = (0, "treehouse 0.4.0\n", "")
        self.assertTrue(is_treehouse_installed())

        mock_run.return_value = (1, "", "treehouse: command not found")
        self.assertFalse(is_treehouse_installed())

    @patch("tools.brigade.worktree.is_treehouse_installed", return_value=True)
    @patch("tools.brigade.worktree.run_command")
    def test_acquire_worktree_success_json(self, mock_run, mock_installed):
        mock_run.return_value = (
            0,
            json.dumps({"path": "/home/oguz/.treehouse/pool/slot-1", "slot": 1}),
            "",
        )
        ok, path, err = acquire_worktree(
            self.repo_path,
            branch_name="brigade/TICK-101",
            lease_holder="brigade-TICK-101",
        )
        self.assertTrue(ok)
        self.assertEqual(path, "/home/oguz/.treehouse/pool/slot-1")
        self.assertEqual(err, "")

    @patch("tools.brigade.worktree.is_treehouse_installed", return_value=True)
    @patch("tools.brigade.worktree.run_command")
    def test_acquire_worktree_failure(self, mock_run, mock_installed):
        mock_run.return_value = (1, "", "No free slots in pool")
        ok, path, err = acquire_worktree(
            self.repo_path,
            branch_name="brigade/TICK-101",
        )
        self.assertFalse(ok)
        self.assertEqual(path, "")
        self.assertIn("No free slots", err)

    @patch("tools.brigade.worktree.run_command")
    def test_return_worktree(self, mock_run):
        mock_run.return_value = (0, "Worktree returned successfully", "")
        ok, msg = return_worktree(
            self.repo_path,
            worktree_path="/home/oguz/.treehouse/pool/slot-1",
            force=True,
        )
        self.assertTrue(ok)
        cmd_args = mock_run.call_args[0][0]
        self.assertIn("--force", cmd_args)
        self.assertIn("/home/oguz/.treehouse/pool/slot-1", cmd_args)


class TestFlightRecorder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)
        self.recorder = FlightRecorder(self.repo_path, "TICK-TEST-001")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_record_dead_end_and_alert_block(self):
        self.recorder.set_metadata(
            track="core",
            domain="billing",
            target_file="src/actions/checkout.ts",
        )
        entry = self.recorder.record_dead_end(
            station="surgeon",
            approach="Extracting inline query into checkout repo without db transaction",
            failure_reason="Transaction deadlock observed under concurrency tests",
            negative_constraint="DO NOT extract checkout actions without wrapping in db.transaction() context.",
        )
        self.assertEqual(entry["station"], "surgeon")
        self.assertEqual(len(self.recorder.get_negative_constraints()), 1)

        # Verify learnings file generated
        learnings_file = self.repo_path / ".edge" / "flight-recorder" / "TICK-TEST-001-learnings.md"
        self.assertTrue(learnings_file.exists())
        content = learnings_file.read_text(encoding="utf-8")
        self.assertIn("DO NOT extract checkout actions", content)
        self.assertIn("Transaction deadlock", content)

        # Verify prompt alert block formatting
        alert_block = self.recorder.get_prompt_alert_block()
        self.assertIn("ZERO-AMNESIA FLIGHT RECORDER", alert_block)
        self.assertIn("DO NOT extract checkout actions", alert_block)

    def test_escalation_and_captain_decision(self):
        self.recorder.record_escalation(
            station="spec_examiner",
            reason="Ambiguous business requirement: whether refund requires manager approval.",
        )
        report = self.recorder.load()
        self.assertEqual(report["status"], "PAUSED_ESCALATED")
        self.assertEqual(report["escalations"][0]["station"], "spec_examiner")

        self.recorder.record_captain_decision(
            decision="Allow refunds under $50 without manager approval.",
            decided_by="human_captain",
        )
        report = self.recorder.load()
        self.assertEqual(report["captain_decision"]["decision"], "Allow refunds under $50 without manager approval.")
        self.assertEqual(report["status"], "DECIDED")


class TestFsmEscalationAndAbort(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)
        self.fsm = BrigadeFSM(target_repo=self.repo_path)
        
        # Setup an active ticket
        self.ticket = Ticket(
            ticket_id="TICK-ESC-01",
            track="core",
            domain="users",
            rule_id="RULE-LEAK",
            severity="HIGH",
            target_file="src/actions/users.ts",
            line_number=42,
            fingerprint="fp999",
            description="Leaked query",
            suggested_fix="Repository extraction",
            test_seam_command="npm run test:unit",
            branch_name="brigade/TICK-ESC-01",
            worktree_path="/tmp/mock-worktree-slot",
        )
        self.fsm.state.active_ticket = self.ticket
        self.fsm.state.current_state = CycleState.SURGERY
        self.fsm.save()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_escalate_and_release(self):
        checkpoint = self.fsm.escalate(reason="Need clarification on schema field name.")
        self.assertIsNotNone(checkpoint)
        self.assertEqual(self.fsm.state.current_state, CycleState.PAUSED)
        self.assertEqual(checkpoint.fsm_state, CycleState.SURGERY.value)
        self.assertTrue(self.fsm.checkpoint_file.exists())
        self.assertEqual(self.ticket.escalation_reason, "Need clarification on schema field name.")

        # Release with human decision
        ok, cp, msg = self.fsm.release(decision="Use 'user_display_name' field.")
        self.assertTrue(ok)
        self.assertEqual(self.fsm.state.current_state, CycleState.SURGERY)
        self.assertEqual(self.ticket.captain_decision, "Use 'user_display_name' field.")
        self.assertFalse(self.fsm.checkpoint_file.exists())

    @patch("tools.brigade.fsm.return_worktree")
    def test_abort_with_dead_end_and_force_return(self, mock_return):
        mock_return.return_value = (True, "Returned")
        
        self.fsm.abort(
            reason="Approach completely failed verification. Diverged too far.",
            negative_constraint="DO NOT rewrite action using async generators; use standard promises.",
            force=True,
        )
        self.assertEqual(self.fsm.state.current_state, CycleState.IDLE)
        self.assertIsNone(self.fsm.state.active_ticket)
        self.assertIsNone(self.fsm.state.active_worktree)
        
        # Ensure return_worktree was invoked with force=True
        mock_return.assert_called_once_with(
            self.repo_path,
            "/tmp/mock-worktree-slot",
            force=True,
        )

        # Ensure negative constraint was saved to flight recorder
        recorder = FlightRecorder(self.repo_path, "TICK-ESC-01")
        constraints = recorder.get_negative_constraints()
        self.assertEqual(len(constraints), 1)
        self.assertEqual(constraints[0], "DO NOT rewrite action using async generators; use standard promises.")

    @patch("tools.brigade.fsm.is_treehouse_installed", return_value=True)
    @patch("tools.brigade.fsm.acquire_worktree")
    @patch("tools.brigade.fsm.return_worktree")
    def test_start_slice_and_finish_slice(self, mock_return, mock_acquire, mock_installed):
        mock_acquire.return_value = (True, "/tmp/mock-slot-42", "")
        mock_return.return_value = (True, "Returned")

        # Fake git repo
        (self.repo_path / ".git").mkdir()

        # 1. Start slice
        fsm = BrigadeFSM(self.repo_path)
        ok, ticket, msg = fsm.start_slice(
            name="staff-allocation",
            track="feature",
            target_file="src/core/modules/staff/allocation.ts",
            domain="staff",
        )
        self.assertTrue(ok)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.track, "feature")
        self.assertEqual(ticket.domain, "staff")
        self.assertEqual(ticket.branch_name, "feat/staff-allocation")
        self.assertEqual(ticket.worktree_path, "/tmp/mock-slot-42")
        self.assertEqual(fsm.state.current_state, CycleState.SURGERY)
        self.assertEqual(fsm.state.active_worktree, "/tmp/mock-slot-42")

        # Ensure flight recorder was initialized
        recorder = FlightRecorder(self.repo_path, ticket.ticket_id)
        self.assertEqual(recorder.data["domain"], "staff")
        self.assertEqual(recorder.data["worktree_path"], "/tmp/mock-slot-42")

        # 2. Finish slice
        with patch.object(fsm, "guard_staging_to_completed", return_value=(True, "Merged cleanly", {})):
            fin_ok, fin_msg = fsm.finish_slice()
            self.assertTrue(fin_ok)
            self.assertEqual(fsm.state.current_state, CycleState.IDLE)
            self.assertIsNone(fsm.state.active_ticket)
            self.assertIsNone(fsm.state.active_worktree)


if __name__ == "__main__":
    unittest.main()
