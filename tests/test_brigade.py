#!/usr/bin/env python3
"""
Unit Tests for Edge Brigade: Michelin Station & Deterministic State Machine Engine
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.brigade.models import (
    StationRole,
    CycleState,
    Station,
    Ticket,
    ReviewFinding,
    TransitionLog,
    BrigadeState,
    Checkpoint,
    ContextHeatZone,
)
from tools.brigade.stations import StationRegistry
from tools.brigade.fsm import BrigadeFSM


class TestBrigadeModels(unittest.TestCase):
    def test_station_serialization(self):
        s = Station(role="surgeon", conversation_id="conv-123", name="Chef Surgeon")
        d = s.to_dict()
        self.assertEqual(d["role"], "surgeon")
        self.assertEqual(d["conversation_id"], "conv-123")
        
        restored = Station.from_dict(d)
        self.assertEqual(restored.name, "Chef Surgeon")
        self.assertEqual(restored.status, "IDLE")

    def test_ticket_id_generation_and_serialization(self):
        tid = Ticket.generate_id("core", "customers", "RULE-DB-LEAK", 100)
        self.assertTrue(tid.startswith("TICK-"))
        
        ticket = Ticket(
            ticket_id=tid,
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=100,
            fingerprint="fp123456",
            description="DB leak in action",
            suggested_fix="Move to repository",
            branch_name="refactor/core-customers-dbleak",
            test_seam_command="npx vitest run customers.test.ts",
            scaffolding_allowance=25,
        )
        d = ticket.to_dict()
        self.assertEqual(d["scaffolding_allowance"], 25)
        
        restored = Ticket.from_dict(d)
        self.assertEqual(restored.ticket_id, tid)
        self.assertEqual(restored.target_file, "src/actions/customers.ts")

    def test_review_finding_serialization(self):
        rf = ReviewFinding(
            axis="standards",
            severity="CRITICAL",
            file_path="src/lib/customers/repository.ts",
            rule="coding_standards.md §4.3",
            description="Index signature tampering",
            suggested_fix="Define explicit interface",
            line_number=45,
        )
        d = rf.to_dict()
        self.assertEqual(d["severity"], "CRITICAL")
        
        restored = ReviewFinding.from_dict(d)
        self.assertEqual(restored.axis, "standards")
        self.assertEqual(restored.line_number, 45)

    def test_brigade_state_serialization(self):
        state = BrigadeState(
            repo_path="/test/repo",
            base_branch="feat/clean",
            current_state=CycleState.SURGERY,
        )
        state.stations["surgeon"] = Station(role="surgeon", conversation_id="conv-1", name="Surgeon")
        d = state.to_dict()
        self.assertEqual(d["current_state"], "SURGERY")
        self.assertIn("surgeon", d["stations"])

        restored = BrigadeState.from_dict(d)
        self.assertEqual(restored.current_state, CycleState.SURGERY)
        self.assertEqual(restored.stations["surgeon"].conversation_id, "conv-1")

    def test_checkpoint_serialization(self):
        ticket = Ticket(
            ticket_id="TICK-PAUSE",
            track="ui",
            domain="BranchManager",
            rule_id="RULE-JSX-DUPLICATE-CLUSTER",
            severity="WARNING",
            target_file="src/components/branches/BranchManager.tsx",
            line_number=415,
            fingerprint="fp777",
            description="Duplicate modal overlay",
            suggested_fix="Consolidate to Modal.tsx",
            branch_name="refactor/ui-BranchManager-jsxduplica",
            test_seam_command="npm run test:unit",
        )
        cp = Checkpoint(
            paused_at="2026-10-05T21:00:00Z",
            reason="CONTEXT_LIMIT_YELLOW",
            base_branch="feat/nextjs-clean-monolith",
            active_branch="refactor/ui-BranchManager-jsxduplica",
            active_ticket=ticket,
            fsm_state="SURGERY",
            completed_substeps=["git_branch_created"],
            pending_substeps=["modal_consolidation", "gate_verification"],
            wip_commit_sha="a45a380",
            has_uncommitted_work=True,
            next_action="Continue modal consolidation",
        )
        d = cp.to_dict()
        self.assertEqual(d["reason"], "CONTEXT_LIMIT_YELLOW")
        self.assertEqual(d["fsm_state"], "SURGERY")
        self.assertTrue(d["has_uncommitted_work"])
        self.assertEqual(d["active_ticket"]["ticket_id"], "TICK-PAUSE")

        restored = Checkpoint.from_dict(d)
        self.assertEqual(restored.reason, "CONTEXT_LIMIT_YELLOW")
        self.assertEqual(restored.fsm_state, "SURGERY")
        self.assertEqual(restored.active_ticket.ticket_id, "TICK-PAUSE")
        self.assertEqual(restored.pending_substeps, ["modal_consolidation", "gate_verification"])



class TestStationRegistry(unittest.TestCase):
    def setUp(self):
        self.state = BrigadeState()
        self.registry = StationRegistry(self.state)

    def test_register_and_lookup(self):
        station = self.registry.register(StationRole.SURGERY if hasattr(StationRole, 'SURGERY') else StationRole.SURGEON, "conv-abc", "Surgeon 1")
        self.assertEqual(station.role, "surgeon")
        self.assertIn("surgeon", self.registry.stations)

        found = self.registry.get_station(StationRole.SURGEON)
        self.assertIsNotNone(found)
        self.assertEqual(found.conversation_id, "conv-abc")

    def test_mark_active_and_idle(self):
        self.registry.register(StationRole.SURGEON, "conv-abc")
        self.registry.mark_active(StationRole.SURGEON)
        self.assertEqual(self.registry.get_station(StationRole.SURGEON).status, "BUSY")

        self.registry.mark_idle(StationRole.SURGEON)
        self.assertEqual(self.registry.get_station(StationRole.SURGEON).status, "IDLE")

    def test_prompt_builders(self):
        ticket = Ticket(
            ticket_id="TICK-TEST",
            track="core",
            domain="bookings",
            rule_id="RULE-ACTION-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/bookings.ts",
            line_number=610,
            fingerprint="fp999",
            description="Raw DB query in action",
            suggested_fix="Extract to repository",
            branch_name="refactor/core-bookings-dbleak",
            test_seam_command="npx vitest run bookings.test.ts",
            scaffolding_allowance=25,
            negative_constraints=["Do not touch schema"],
        )

        surgeon_prompt = StationRegistry.build_surgeon_prompt(ticket, "feat/clean")
        self.assertIn("SURGEON", surgeon_prompt)
        self.assertIn("TICK-TEST", surgeon_prompt)
        self.assertIn("src/actions/bookings.ts", surgeon_prompt)
        self.assertIn("Do not touch schema", surgeon_prompt)

        std_prompt = StationRegistry.build_standards_review_prompt(ticket, "feat/clean")
        self.assertIn("STANDARDS_EXAMINER", std_prompt)
        self.assertIn("git diff feat/clean..HEAD", std_prompt)

        spec_prompt = StationRegistry.build_spec_review_prompt(ticket, "feat/clean")
        self.assertIn("SPEC_EXAMINER", spec_prompt)
        self.assertIn("MigrationGate Invariant", spec_prompt)

        finding = ReviewFinding(
            axis="standards",
            severity="CRITICAL",
            file_path="src/lib/bookings/repository.ts",
            rule="coding_standards.md §4.3",
            description="Missing transaction",
            suggested_fix="Wrap in db.transaction",
        )
        polish_prompt = StationRegistry.build_polish_prompt(ticket, [finding])
        self.assertIn("Polish Remediation", polish_prompt)
        self.assertIn("Missing transaction", polish_prompt)

        expediter_prompt = StationRegistry.build_expediter_prompt(ticket, "feat/clean")
        self.assertIn("EXPEDITER", expediter_prompt)
        self.assertIn("git merge --squash", expediter_prompt)

        spec_writer_prompt = StationRegistry.build_spec_writer_prompt(ticket, "User wants payment wallet")
        self.assertIn("SPEC_WRITER", spec_writer_prompt)
        self.assertIn("lavish-axi", spec_writer_prompt)
        self.assertIn("Ubiquitous Language", spec_writer_prompt)

        researcher_prompt = StationRegistry.build_researcher_prompt(ticket, "Investigate Drizzle transaction leaks")
        self.assertIn("RESEARCHER", researcher_prompt)
        self.assertIn("Root Cause Analysis", researcher_prompt)

        seam_prompt = StationRegistry.build_seam_architect_prompt(ticket, "Wallet recharge spec")
        self.assertIn("SEAM_ARCHITECT", seam_prompt)
        self.assertIn("RED Unit/Contract Tests", seam_prompt)

        coder_prompt = StationRegistry.build_coder_prompt(ticket, "npx vitest run")
        self.assertIn("CODER", coder_prompt)
        self.assertIn("Test Immutability", coder_prompt)


class TestBrigadeFSM(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.fsm = BrigadeFSM(self.repo_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_state_is_idle(self):
        self.assertEqual(self.fsm.state.current_state, CycleState.IDLE)
        self.assertIsNone(self.fsm.state.active_ticket)

    def test_advance_from_idle_without_ticket_fails(self):
        success, state, msg = self.fsm.advance()
        self.assertFalse(success)
        self.assertEqual(state, CycleState.IDLE)
        self.assertIn("Cannot advance from IDLE without an active ticket", msg)

    def test_triage_next_ticket_from_ledger(self):
        # Create mock .edge/ledger/core.json
        ledger_dir = self.repo_path / ".edge" / "ledger"
        ledger_dir.mkdir(parents=True)
        ledger_file = ledger_dir / "core.json"
        
        ledger_data = {
            "track": "core",
            "items": [
                {
                    "fingerprint": "warn_fp",
                    "track": "core",
                    "rule_id": "RULE-FAT-FUNCTION",
                    "title": "Function too long",
                    "file_path": "src/actions/pricing.ts",
                    "line_number": 50,
                    "severity": "WARNING",
                    "status": "OPEN",
                    "suggested_fix": "Thin function",
                },
                {
                    "fingerprint": "crit_fp",
                    "track": "core",
                    "rule_id": "RULE-ACTION-DB-LEAK",
                    "title": "Raw DB query in action",
                    "file_path": "src/actions/bookings.ts",
                    "line_number": 610,
                    "symbol": "createBookingAction",
                    "severity": "CRITICAL",
                    "status": "OPEN",
                    "suggested_fix": "Move to repository",
                }
            ]
        }
        with open(ledger_file, "w", encoding="utf-8") as f:
            json.dump(ledger_data, f)

        ticket = self.fsm.triage_next_ticket("core")
        self.assertIsNotNone(ticket)
        # CRITICAL must take precedence over WARNING
        self.assertEqual(ticket.rule_id, "RULE-ACTION-DB-LEAK")
        self.assertEqual(ticket.domain, "bookings")
        self.assertEqual(ticket.target_file, "src/actions/bookings.ts")
        self.assertEqual(ticket.scaffolding_allowance, 25) # repo doesn't exist yet
        self.assertEqual(self.fsm.state.current_state, CycleState.TRIAGE)

    def test_guard_surgery_rejection_on_schema_violation(self):
        # Set up active ticket
        ticket = Ticket(
            ticket_id="TICK-TEST",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=100,
            fingerprint="fp1",
            description="test",
            suggested_fix="fix",
            branch_name="refactor/core-customers-test",
            test_seam_command="vitest",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        # Mock _run_cmd returning schema modification
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            # git diff --name-only returns schema file
            mock_cmd.return_value = (0, "src/actions/customers.ts\nsrc/db/schema/customers.ts", "")
            
            passed, msg, _ = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("MigrationGate Invariant VIOLATION", msg)

    def test_guard_surgery_rejection_on_target_file_inflation(self):
        ticket = Ticket(
            ticket_id="TICK-TEST",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=100,
            fingerprint="fp1",
            description="test",
            suggested_fix="fix",
            branch_name="refactor/core-customers-test",
            test_seam_command="vitest",
            enforce_contraction=True,
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/actions/customers.ts", "")
                if "--numstat" in cmd:
                    # 50 insertions, 10 deletions -> net +40 inflation!
                    return (0, "50\t10\tsrc/actions/customers.ts", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            # 1. When enforce_contraction is True, it catches the violation
            passed, msg, _ = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("Target Contraction VIOLATION", msg)

            # 2. When enforce_contraction is False (the new default), it passes!
            ticket.enforce_contraction = False
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertTrue(passed)
            self.assertEqual(details["target_delta"], 40)

    def test_guard_surgery_success(self):
        ticket = Ticket(
            ticket_id="TICK-TEST",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=100,
            fingerprint="fp1",
            description="test",
            suggested_fix="fix",
            branch_name="refactor/core-customers-test",
            test_seam_command="vitest",
            scaffolding_allowance=25,
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/actions/customers.ts\nsrc/lib/customers/repository.ts", "")
                if "--numstat" in cmd:
                    # Target shrunk by -80 lines (20 ins, 100 del), repo created with +20 lines -> net -60 lines
                    return (0, "20\t100\tsrc/actions/customers.ts\n20\t0\tsrc/lib/customers/repository.ts", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertTrue(passed)
            self.assertEqual(details["target_delta"], -80)
            self.assertEqual(details["total_net"], -60)

    def test_guard_verify_success_and_failure(self):
        ticket = Ticket(
            ticket_id="TICK-TEST",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=100,
            fingerprint="fp1",
            description="test",
            suggested_fix="fix",
            branch_name="refactor/core-customers-test",
            test_seam_command="npx vitest run test.ts",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.VERIFY

        # 1. Failure case: vitest fails
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = (1, "FAIL", "Assertion error")
            passed, msg, _ = self.fsm.guard_verify_to_review()
            self.assertFalse(passed)
            self.assertIn("Characterization test failed", msg)

        # 2. Failure case: tsc fails
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "vitest" in cmd:
                    return (0, "PASS", "")
                if "tsc" in cmd:
                    return (2, "TS2304: Cannot find name", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, _ = self.fsm.guard_verify_to_review()
            self.assertFalse(passed)
            self.assertIn("TypeScript compiler check failed", msg)

        # 3. Success case: both pass
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "PASS", "")
            passed, msg, _ = self.fsm.guard_verify_to_review()
            self.assertTrue(passed)

    def test_review_branching_to_polish_or_gate(self):
        self.fsm.state.current_state = CycleState.REVIEW
        
        # Case A: Clean review -> goes to GATE
        self.fsm.state.review_findings = [
            ReviewFinding(axis="standards", severity="WARNING", file_path="a.ts", rule="r1", description="minor", suggested_fix="f1")
        ]
        next_state, msg, _ = self.fsm.guard_review_to_next()
        self.assertEqual(next_state, CycleState.GATE)

        # Case B: Critical review finding -> goes to POLISH
        self.fsm.state.review_findings.append(
            ReviewFinding(axis="spec", severity="CRITICAL", file_path="b.ts", rule="r2", description="missing tx", suggested_fix="f2")
        )
        next_state, msg, _ = self.fsm.guard_review_to_next()
        self.assertEqual(next_state, CycleState.POLISH)

    def test_full_cycle_progression_and_reset(self):
        ticket = Ticket(
            ticket_id="TICK-LIFECYCLE",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=100,
            fingerprint="fp1",
            description="test",
            suggested_fix="fix",
            branch_name="refactor/core-customers-test",
            test_seam_command="vitest",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.IDLE

        # IDLE -> TRIAGE
        s, state, _ = self.fsm.advance()
        self.assertTrue(s)
        self.assertEqual(state, CycleState.TRIAGE)

        # TRIAGE -> SURGERY
        s, state, _ = self.fsm.advance()
        self.assertTrue(s)
        self.assertEqual(state, CycleState.SURGERY)

        # SURGERY -> VERIFY (with mock guards)
        with patch.object(self.fsm, "guard_surgery_to_verify", return_value=(True, "ok", {})):
            s, state, _ = self.fsm.advance()
            self.assertTrue(s)
            self.assertEqual(state, CycleState.VERIFY)

        # VERIFY -> REVIEW
        with patch.object(self.fsm, "guard_verify_to_review", return_value=(True, "ok", {})):
            s, state, _ = self.fsm.advance()
            self.assertTrue(s)
            self.assertEqual(state, CycleState.REVIEW)

        # REVIEW -> GATE (clean review)
        s, state, _ = self.fsm.advance()
        self.assertTrue(s)
        self.assertEqual(state, CycleState.GATE)

        # GATE -> STAGING
        with patch.object(self.fsm, "guard_gate_to_staging", return_value=(True, "ok", {})):
            s, state, _ = self.fsm.advance()
            self.assertTrue(s)
            self.assertEqual(state, CycleState.STAGING)

        # STAGING -> COMPLETED
        with patch.object(self.fsm, "guard_staging_to_completed", return_value=(True, "ok", {})):
            s, state, _ = self.fsm.advance()
            self.assertTrue(s)
            self.assertEqual(state, CycleState.COMPLETED)

        # COMPLETED -> IDLE (reset)
        s, state, _ = self.fsm.advance()
        self.assertTrue(s)
        self.assertEqual(state, CycleState.IDLE)
        self.assertIsNone(self.fsm.state.active_ticket)

    def test_abort_resets_cycle(self):
        self.fsm.state.current_state = CycleState.SURGERY
        self.fsm.state.active_ticket = MagicMock()
        self.fsm.abort("User cancelled")
        self.assertEqual(self.fsm.state.current_state, CycleState.IDLE)
        self.assertIsNone(self.fsm.state.active_ticket)

    def test_whitelist_and_blacklist_triage(self):
        # Create a mock ledger with multiple findings across domains
        ledger_dir = Path(self.test_dir) / ".edge" / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        core_ledger = {
            "items": [
                {
                    "rule_id": "RULE-ACTION-DB-LEAK",
                    "severity": "CRITICAL",
                    "file_path": "src/actions/bookings.ts",
                    "line_number": 45,
                    "title": "Booking SQL leak",
                    "status": "OPEN",
                },
                {
                    "rule_id": "RULE-ACTION-DB-LEAK",
                    "severity": "WARNING",
                    "file_path": "src/actions/customers.ts",
                    "line_number": 12,
                    "title": "Customer SQL leak",
                    "status": "OPEN",
                },
            ]
        }
        with open(ledger_dir / "core.json", "w", encoding="utf-8") as f:
            json.dump(core_ledger, f)

        # Blacklist bookings -> should pick customers
        ticket = self.fsm.triage_next_ticket(track="core", blacklist=["bookings"])
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.domain, "customers")

        # Whitelist bookings only -> should pick bookings
        ticket_b = self.fsm.triage_next_ticket(track="core", whitelist=["bookings"])
        self.assertIsNotNone(ticket_b)
        self.assertEqual(ticket_b.domain, "bookings")

    def test_rollback_stagnated(self):
        ticket = Ticket(
            ticket_id="TICK-TEST",
            track="core",
            domain="test",
            rule_id="RULE-TEST",
            severity="CRITICAL",
            target_file="src/actions/test.ts",
            line_number=10,
            fingerprint="fp123",
            description="test desc",
            suggested_fix="test fix",
            branch_name="refactor/test",
            test_seam_command="npm test",
            attempt_count=2,
            status="OPEN",
        )
        self.fsm.state.active_ticket = ticket
        with patch.object(self.fsm, "_run_cmd", return_value=(0, "", "")):
            self.fsm.rollback_stagnated("Health failed to improve")
            self.assertEqual(self.fsm.state.current_state, CycleState.IDLE)
            self.assertEqual(ticket.status, "STAGNATED")

    def test_pause_clean_worktree(self):
        ticket = Ticket(
            ticket_id="TICK-CLEAN",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=50,
            fingerprint="fp1",
            description="desc",
            suggested_fix="fix",
            branch_name="refactor/clean",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.active_branch = "refactor/clean"
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--porcelain" in cmd:
                    return (0, "", "") # clean worktree
                if "rev-parse" in cmd:
                    return (0, "abc12345\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            cp = self.fsm.pause(reason="HUMAN_PAUSE")

            self.assertEqual(self.fsm.state.current_state, CycleState.PAUSED)
            self.assertFalse(cp.has_uncommitted_work)
            self.assertEqual(cp.wip_commit_sha, "abc12345")
            self.assertTrue(self.fsm.checkpoint_file.exists())

            with open(self.fsm.checkpoint_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["reason"], "HUMAN_PAUSE")
            self.assertEqual(saved["fsm_state"], "SURGERY")
            self.assertEqual(saved["active_ticket"]["ticket_id"], "TICK-CLEAN")

    def test_pause_dirty_worktree(self):
        ticket = Ticket(
            ticket_id="TICK-DIRTY",
            track="core",
            domain="customers",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/customers.ts",
            line_number=50,
            fingerprint="fp1",
            description="desc",
            suggested_fix="fix",
            branch_name="refactor/dirty",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.active_branch = "refactor/dirty"
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            calls = []
            def side_effect(cmd, cwd=None):
                calls.append(cmd)
                if "--porcelain" in cmd:
                    return (0, " M src/actions/customers.ts\n", "") # dirty
                if "rev-parse" in cmd:
                    return (0, "wip9999\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            cp = self.fsm.pause(reason="CONTEXT_LIMIT_RED")

            self.assertEqual(self.fsm.state.current_state, CycleState.PAUSED)
            self.assertTrue(cp.has_uncommitted_work)
            self.assertEqual(cp.wip_commit_sha, "wip9999")
            self.assertTrue(any("add" in c and "-A" in c for c in calls))
            self.assertTrue(any("commit" in c and "wip(checkpoint): safe pause at SURGERY [TICK-DIRTY]" in c for c in calls))

    def test_resume_success(self):
        self.fsm.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        ticket = Ticket(
            ticket_id="TICK-RESTORE",
            track="ui",
            domain="branches",
            rule_id="RULE-JSX-DUPLICATE",
            severity="WARNING",
            target_file="src/components/Branch.tsx",
            line_number=20,
            fingerprint="fp333",
            description="duplicate",
            suggested_fix="fix",
            branch_name="refactor/ui-branches-jsx",
            test_seam_command="npm test",
        )
        cp = Checkpoint(
            paused_at="2026-10-05T20:00:00Z",
            reason="HUMAN_PAUSE",
            base_branch="feat/nextjs-clean-monolith",
            active_branch="refactor/ui-branches-jsx",
            active_ticket=ticket,
            fsm_state="SURGERY",
            completed_substeps=["git_branch_created"],
            pending_substeps=["surgery"],
            wip_commit_sha="commit123",
            has_uncommitted_work=False,
            next_action="Continue surgery",
        )
        with open(self.fsm.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(cp.to_dict(), f)

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            mock_cmd.return_value = (0, "refactor/ui-branches-jsx", "")
            success, restored_cp, summary = self.fsm.resume()

            self.assertTrue(success)
            self.assertIsNotNone(restored_cp)
            self.assertEqual(self.fsm.state.current_state, CycleState.SURGERY)
            self.assertEqual(self.fsm.state.active_ticket.ticket_id, "TICK-RESTORE")
            self.assertEqual(self.fsm.state.active_branch, "refactor/ui-branches-jsx")
            self.assertFalse(self.fsm.checkpoint_file.exists())

    def test_resume_missing_checkpoint(self):
        if self.fsm.checkpoint_file.exists():
            self.fsm.checkpoint_file.unlink()
        success, cp, msg = self.fsm.resume()
        self.assertFalse(success)
        self.assertIsNone(cp)
        self.assertIn("No checkpoint found", msg)

    def test_heat_zone_detection(self):
        zone, rec = self.fsm.get_heat_zone(100_000)
        self.assertEqual(zone, ContextHeatZone.GREEN)
        self.assertIn("GREEN ZONE", rec)

        zone_y, rec_y = self.fsm.get_heat_zone(200_000)
        self.assertEqual(zone_y, ContextHeatZone.YELLOW)
        self.assertIn("YELLOW ZONE", rec_y)

        zone_r, rec_r = self.fsm.get_heat_zone(280_000)
        self.assertEqual(zone_r, ContextHeatZone.RED)
        self.assertIn("RED ZONE", rec_r)

    def test_calculate_token_estimate(self):
        mock_transcript = self.repo_path / "mock_transcript.jsonl"
        with open(mock_transcript, "w", encoding="utf-8") as f:
            f.write("a" * 4000)
        
        tokens = self.fsm.calculate_token_estimate(mock_transcript)
        self.assertEqual(tokens, 1000)

    def test_triage_throttled_by_heat(self):
        ledger_dir = self.repo_path / ".edge" / "ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        with open(ledger_dir / "core.json", "w", encoding="utf-8") as f:
            json.dump({
                "items": [{
                    "fingerprint": "fp1",
                    "rule_id": "RULE-TEST",
                    "title": "test",
                    "file_path": "src/actions/test.ts",
                    "line_number": 1,
                    "severity": "CRITICAL",
                    "status": "OPEN",
                }]
            }, f)

        hot_transcript = self.repo_path / "hot_transcript.jsonl"
        with open(hot_transcript, "w", encoding="utf-8") as f:
            f.write("x" * 800_000)

        ticket = self.fsm.triage_next_ticket("core", transcript_path=hot_transcript)
        self.assertIsNone(ticket)

    def test_triage_blocked_when_paused(self):
        self.fsm.state.current_state = CycleState.PAUSED
        ticket = self.fsm.triage_next_ticket("core")
        self.assertIsNone(ticket)


class TestBrigadeCLIPrototype(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.lavish_dir = self.repo_path / ".lavish"
        self.lavish_dir.mkdir(parents=True, exist_ok=True)
        self.html_file = self.lavish_dir / "test.html"
        self.html_file.write_text("<h1>Test</h1>", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_prototype_serve_missing_file_flag(self):
        from tools.brigade.cli import cmd_prototype
        import argparse
        args = argparse.Namespace(repo=str(self.repo_path), action="serve", file=None)
        self.assertEqual(cmd_prototype(args), 1)

    def test_prototype_serve_nonexistent_file(self):
        from tools.brigade.cli import cmd_prototype
        import argparse
        args = argparse.Namespace(repo=str(self.repo_path), action="serve", file=".lavish/nonexistent.html")
        self.assertEqual(cmd_prototype(args), 1)

    def test_prototype_poll_missing_file_flag(self):
        from tools.brigade.cli import cmd_prototype
        import argparse
        args = argparse.Namespace(repo=str(self.repo_path), action="poll", file=None)
        self.assertEqual(cmd_prototype(args), 1)


if __name__ == "__main__":
    unittest.main()

