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
    def test_canonical_roles_roster(self):
        expected_roles = {
            "spec_writer",
            "researcher",
            "seam_architect",
            "coder",
            "surgeon",
            "examiner",
            "qa_engineer",
            "spec_critic",
        }
        actual_roles = {r.value for r in StationRole}
        self.assertEqual(actual_roles, expected_roles)
        self.assertEqual(len(StationRole), 8)
        self.assertEqual(StationRole.SPEC_CRITIC.value, "spec_critic")
        self.assertEqual(StationRole.EXAMINER.value, "examiner")
        self.assertFalse(hasattr(StationRole, "EXPEDITER"))
        self.assertFalse(hasattr(StationRole, "STANDARDS_EXAMINER"))
        self.assertFalse(hasattr(StationRole, "SPEC_EXAMINER"))

    def test_legacy_brigade_state_migration(self):
        legacy_data = {
            "version": "1.0.0",
            "repo_path": "/test/legacy-repo",
            "base_branch": "main",
            "current_state": "REVIEW",
            "stations": {
                "expediter": {
                    "role": "expediter",
                    "conversation_id": "legacy-exp-1",
                    "name": "Expediter Station",
                },
                "standards_examiner": {
                    "role": "standards_examiner",
                    "conversation_id": "legacy-std-1",
                    "name": "Standards Examiner Station",
                },
                "spec_examiner": {
                    "role": "spec_examiner",
                    "conversation_id": "legacy-spec-1",
                    "name": "Spec Examiner Station",
                },
                "surgeon": {
                    "role": "surgeon",
                    "conversation_id": "legacy-surg-1",
                    "name": "Surgeon Station",
                },
            },
        }
        restored = BrigadeState.from_dict(legacy_data)
        self.assertNotIn("expediter", restored.stations)
        self.assertNotIn("standards_examiner", restored.stations)
        self.assertNotIn("spec_examiner", restored.stations)
        self.assertIn("examiner", restored.stations)
        self.assertIn("surgeon", restored.stations)
        self.assertEqual(restored.stations["examiner"].role, "examiner")
        self.assertEqual(restored.stations["examiner"].conversation_id, "legacy-std-1")

    def test_station_serialization(self):
        s = Station(role="surgeon", conversation_id="conv-123", name="Chef Surgeon")
        d = s.to_dict()
        self.assertEqual(d["role"], "surgeon")
        self.assertEqual(d["conversation_id"], "conv-123")
        
        restored = Station.from_dict(d)
        self.assertEqual(restored.name, "Chef Surgeon")
        self.assertEqual(restored.status, "IDLE")

    def test_station_from_dict_extra_fields_resilience(self):
        # Station.from_dict must gracefully ignore unexpected/legacy fields (e.g. conversationId, updated_at)
        data = {
            "role": "surgeon",
            "conversation_id": "conv-resilience-123",
            "name": "Chef Surgeon",
            "status": "BUSY",
            "conversationId": "legacy-alias-cid",
            "updated_at": "2026-10-31T00:00:00Z",
            "extra_custom_metadata": {"foo": "bar"},
        }
        restored = Station.from_dict(data)
        self.assertEqual(restored.role, "surgeon")
        self.assertEqual(restored.conversation_id, "conv-resilience-123")
        self.assertEqual(restored.name, "Chef Surgeon")
        self.assertEqual(restored.status, "BUSY")

    def test_station_from_dict_missing_name_resilience(self):
        # Station.from_dict must gracefully auto-populate name when missing
        data = {
            "role": "coder",
            "conversation_id": "conv-no-name-123",
            "status": "IDLE",
        }
        restored = Station.from_dict(data)
        self.assertEqual(restored.role, "coder")
        self.assertEqual(restored.conversation_id, "conv-no-name-123")
        self.assertEqual(restored.name, "Coder Station")

        data_seam = {
            "role": "seam_architect",
            "conversation_id": "conv-seam-123",
        }
        restored_seam = Station.from_dict(data_seam)
        self.assertEqual(restored_seam.name, "Seam Architect Station")

        # When role is empty or missing
        data_empty = {
            "conversation_id": "conv-empty-role",
        }
        restored_empty = Station.from_dict(data_empty)
        self.assertEqual(restored_empty.name, "Station Worker")

        # Direct instantiation default
        st_direct = Station(role="surgeon", conversation_id="conv-direct")
        self.assertEqual(st_direct.name, "")

    def test_station_model_default_and_custom_serialization(self):
        # 1. Station(role="coder", conversation_id="c1") defaults to model == "flash"
        st = Station(role="coder", conversation_id="c1")
        self.assertEqual(st.model, "flash")

        # 2. Serializes "model": "flash" in to_dict()
        st_dict = st.to_dict()
        self.assertIn("model", st_dict)
        self.assertEqual(st_dict["model"], "flash")

        # 3. Station.from_dict({"role": "coder", "conversation_id": "c1"}) defaults missing "model" to "flash"
        from_missing = Station.from_dict({"role": "coder", "conversation_id": "c1"})
        self.assertEqual(from_missing.model, "flash")
        self.assertEqual(from_missing.to_dict().get("model"), "flash")

        # 4. Station.from_dict({"role": "examiner", "conversation_id": "e1", "model": "pro"}) preserves "pro"
        from_custom = Station.from_dict({"role": "examiner", "conversation_id": "e1", "model": "pro"})
        self.assertEqual(from_custom.model, "pro")
        self.assertEqual(from_custom.to_dict().get("model"), "pro")


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

    def test_station_registry_register_with_model(self):
        # 1. fsm.registry.register(StationRole.CODER, "c1") sets station.model == "flash"
        st_default = self.registry.register(StationRole.CODER, "c1")
        self.assertEqual(st_default.model, "flash")

        # 2. fsm.registry.register(StationRole.EXAMINER, "e1", model="pro") sets station.model == "pro"
        st_custom = self.registry.register(StationRole.EXAMINER, "e1", model="pro")
        self.assertEqual(st_custom.model, "pro")

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

        examiner_prompt = StationRegistry.build_examiner_prompt(ticket, "feat/clean")
        self.assertIn("EXAMINER", examiner_prompt)
        self.assertIn("git diff feat/clean..HEAD", examiner_prompt)
        self.assertIn("coding_standards.md", examiner_prompt)
        self.assertIn("MigrationGate Invariant", examiner_prompt)
        self.assertIn("EXAMINER REVIEW: PASS", examiner_prompt)

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
            enforce_contraction=True,  # Legacy flag is retired; must never block positive SLOC
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/actions/customers.ts", "")
                if "--numstat" in cmd:
                    # 50 insertions, 10 deletions -> net +40 lines!
                    return (0, "50\t10\tsrc/actions/customers.ts", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            # Positive SLOC (+40 lines) passes guard_surgery_to_verify and records telemetry
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertTrue(passed)
            self.assertEqual(details["target_delta"], 40)
            self.assertEqual(details["total_net"], 40)

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
        zone, rec = self.fsm.get_heat_zone(30_000)
        self.assertEqual(zone, ContextHeatZone.GREEN)
        self.assertIn("GREEN ZONE", rec)

        zone_y, rec_y = self.fsm.get_heat_zone(60_000)
        self.assertEqual(zone_y, ContextHeatZone.YELLOW)
        self.assertIn("YELLOW ZONE", rec_y)

        zone_r, rec_r = self.fsm.get_heat_zone(90_000)
        self.assertEqual(zone_r, ContextHeatZone.RED)
        self.assertIn("RED ZONE", rec_r)

    def test_fsm_heat_threshold_constants(self):
        from tools.brigade import fsm as fsm_module
        self.assertTrue(hasattr(fsm_module, "GREEN_HEAT_THRESHOLD"), "GREEN_HEAT_THRESHOLD SSOT must exist in fsm.py")
        self.assertTrue(hasattr(fsm_module, "YELLOW_HEAT_THRESHOLD"), "YELLOW_HEAT_THRESHOLD SSOT must exist in fsm.py")
        self.assertEqual(fsm_module.GREEN_HEAT_THRESHOLD, 45_000)
        self.assertEqual(fsm_module.YELLOW_HEAT_THRESHOLD, 75_000)

    def test_fsm_gate_appends_skip_verify(self):
        from unittest.mock import MagicMock, patch
        self.fsm.state.base_branch = "development"
        self.fsm.state.active_ticket = MagicMock()
        self.fsm.state.active_ticket.track = "core"
        self.fsm.state.active_ticket.worktree_path = self.repo_path
        self.fsm.state.active_ticket.scaffolding_allowance = 0
        self.fsm.state.active_ticket.enforce_contraction = False

        with patch.object(self.fsm, "_run_cmd", return_value=(0, "Gate ok", "")) as mock_cmd:
            passed, msg, _ = self.fsm.guard_gate_to_staging()
            self.assertTrue(passed)
            mock_cmd.assert_called_once()
            invoked_cmd = mock_cmd.call_args[0][0]
            self.assertIn("--skip-verify", invoked_cmd, "gate.py must be invoked with --skip-verify to prevent 120s timeouts")
            self.assertIn("development", invoked_cmd)
            self.assertNotIn("--no-refactor", invoked_cmd)

        # Feature track passes --no-refactor
        self.fsm.state.active_ticket.track = "feature"
        with patch.object(self.fsm, "_run_cmd", return_value=(0, "Gate ok", "")) as mock_cmd:
            passed, _, _ = self.fsm.guard_gate_to_staging()
            self.assertTrue(passed)
            invoked_cmd = mock_cmd.call_args[0][0]
            self.assertIn("--no-refactor", invoked_cmd)

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


class TestBrigadeWave2FsmAndCli(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.fsm = BrigadeFSM(self.repo_path)
        self.ticket = Ticket(
            ticket_id="TICK-FEAT-STAFF-ALLOC",
            track="feature",
            domain="staff",
            rule_id="RULE-STAFF",
            severity="NORMAL",
            target_file="src/staff/alloc.ts",
            line_number=1,
            fingerprint="fp-staff",
            description="Staff allocation feature",
            suggested_fix="Implement allocation logic",
            branch_name="feat/staff-alloc",
            test_seam_command="npm run test:unit",
        )
        self.fsm.state.active_ticket = self.ticket

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # a) RED_TEST guard rejecting exit 0, fake red, and advancing on genuine exit 1
    # -------------------------------------------------------------------------
    def test_red_test_guard_pass_before_code_rejection(self):
        self.fsm.state.current_state = CycleState.RED_TEST
        with patch.object(self.fsm, "_run_cmd", return_value=(0, "All 5 tests passed", "")):
            passed, msg, details = self.fsm.guard_red_to_surgery()
            self.assertFalse(passed)
            self.assertIn("RED_BASELINE VIOLATION", msg)
            self.assertEqual(details["exit_code"], 0)

            # Advance must be blocked
            adv_ok, state, adv_msg = self.fsm.advance()
            self.assertFalse(adv_ok)
            self.assertEqual(state, CycleState.RED_TEST)

    def test_red_test_guard_fake_red_syntax_and_harness_rejection(self):
        self.fsm.state.current_state = CycleState.RED_TEST

        # SyntaxError rejection
        with patch.object(self.fsm, "_run_cmd", return_value=(1, "", "SyntaxError: Unexpected identifier")):
            passed, msg, details = self.fsm.guard_red_to_surgery()
            self.assertFalse(passed)
            self.assertIn("FAKE RED DETECTED", msg)

        # Collected 0 items rejection
        with patch.object(self.fsm, "_run_cmd", return_value=(1, "collected 0 items\nno tests ran", "")):
            passed, msg, details = self.fsm.guard_red_to_surgery()
            self.assertFalse(passed)
            self.assertIn("FAKE RED DETECTED", msg)

        # Exit 127 command not found
        with patch.object(self.fsm, "_run_cmd", return_value=(127, "", "bash: npm: command not found")):
            passed, msg, details = self.fsm.guard_red_to_surgery()
            self.assertFalse(passed)
            self.assertIn("FAKE RED DETECTED", msg)

    def test_red_test_guard_advances_on_genuine_assertion_failure(self):
        self.fsm.state.current_state = CycleState.RED_TEST
        genuine_failure_out = "FAIL tests/staff/alloc.test.ts\nAssertionError: expected false to be true\n  at test (tests/staff/alloc.test.ts:12:7)"
        with patch.object(self.fsm, "_run_cmd", return_value=(1, genuine_failure_out, "")):
            passed, msg, details = self.fsm.guard_red_to_surgery()
            self.assertTrue(passed)
            self.assertIn("RED_BASELINE verified", msg)
            self.assertEqual(details["exit_code"], 1)

            # advance() moves to SURGERY
            adv_ok, state, adv_msg = self.fsm.advance()
            self.assertTrue(adv_ok)
            self.assertEqual(state, CycleState.SURGERY)
            self.assertEqual(self.fsm.state.current_state, CycleState.SURGERY)

    # -------------------------------------------------------------------------
    # b) guard_surgery_to_verify on track="feature"
    # -------------------------------------------------------------------------
    def test_guard_surgery_to_verify_feature_brand_new_files(self):
        self.fsm.state.current_state = CycleState.SURGERY
        self.ticket.track = "feature"
        self.ticket.target_file = ""
        self.ticket.expected_files = []

        # 1. When no production files are touched -> fail
        with patch.object(self.fsm, "_run_cmd", return_value=(0, "", "")):
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("No production files were modified or created", msg)

        # 2. When new production file exists in porcelain status -> pass
        src_dir = self.repo_path / "src" / "staff"
        src_dir.mkdir(parents=True, exist_ok=True)
        new_prod_file = src_dir / "new_alloc.ts"
        new_prod_file.write_text("export const alloc = 1;\nexport const free = 2;\n", encoding="utf-8")

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "status" in cmd:
                    return (0, "?? src/staff/new_alloc.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertTrue(passed)
            self.assertIn("Surgery invariants passed", msg)
            self.assertEqual(details["total_net"], 2)

    def test_guard_surgery_to_verify_feature_expected_files_missing_rejection(self):
        self.fsm.state.current_state = CycleState.SURGERY
        self.ticket.track = "feature"
        self.ticket.target_file = ""
        self.ticket.expected_files = ["src/staff/alloc.ts", "src/staff/types.ts"]

        # Only one of the expected files is modified
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/staff/alloc.ts\n", "")
                if "--numstat" in cmd:
                    return (0, "10\t0\tsrc/staff/alloc.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("Incomplete Feature Implementation", msg)
            self.assertIn("src/staff/types.ts", details["missing_files"])

    def test_guard_surgery_to_verify_feature_scope_drift_rejection(self):
        self.fsm.state.current_state = CycleState.SURGERY
        self.ticket.track = "feature"
        self.ticket.target_file = ""
        self.ticket.expected_files = ["src/staff/**"]

        # Rogue file outside expected_files was modified
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/staff/alloc.ts\nsrc/rogue/unrelated.ts\ntests/staff/alloc.test.ts\n", "")
                if "--numstat" in cmd:
                    return (0, "10\t0\tsrc/staff/alloc.ts\n5\t0\tsrc/rogue/unrelated.ts\n20\t0\ttests/staff/alloc.test.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("Deterministic Spec-Code Scope Drift", msg)
            self.assertIn("src/rogue/unrelated.ts", details["unexpected_files"])
            # Note tests/ is non-prod, so it should not be in unexpected_files
            self.assertNotIn("tests/staff/alloc.test.ts", details["unexpected_files"])

    # -------------------------------------------------------------------------
    # c) cmd_ticket --prompt dispatching
    # -------------------------------------------------------------------------
    def test_cmd_ticket_prompt_routing(self):
        import argparse
        from io import StringIO
        from tools.brigade.cli import cmd_ticket

        args = argparse.Namespace(repo=str(self.repo_path), prompt=True, format="toon")

        # 1. In RED_TEST -> SEAM_ARCHITECT prompt
        self.fsm.state.current_state = CycleState.RED_TEST
        self.fsm.save()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            code = cmd_ticket(args)
            self.assertEqual(code, 0)
            self.assertIn("SEAM_ARCHITECT", fake_out.getvalue())

        # 2. In SURGERY, feature track -> CODER prompt
        self.fsm.state.current_state = CycleState.SURGERY
        self.ticket.track = "feature"
        self.fsm.save()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            code = cmd_ticket(args)
            self.assertEqual(code, 0)
            self.assertIn("CODER", fake_out.getvalue())

        # 3. In SURGERY, core track -> SURGEON prompt
        self.ticket.track = "core"
        self.fsm.save()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            code = cmd_ticket(args)
            self.assertEqual(code, 0)
            self.assertIn("SURGEON", fake_out.getvalue())

        # 4. In POLISH, feature track -> CODER polish prompt
        self.fsm.state.current_state = CycleState.POLISH
        self.ticket.track = "feature"
        self.fsm.save()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            code = cmd_ticket(args)
            self.assertEqual(code, 0)
            self.assertIn("CODER", fake_out.getvalue())
            self.assertIn("Test Immutability", fake_out.getvalue())

        # 5. In POLISH, core track -> SURGEON polish prompt
        self.ticket.track = "core"
        self.fsm.save()
        with patch("sys.stdout", new=StringIO()) as fake_out:
            code = cmd_ticket(args)
            self.assertEqual(code, 0)
            self.assertIn("SURGEON", fake_out.getvalue())

    # -------------------------------------------------------------------------
    # d) cmd_critique_spec CLI integration with mocked run_spec_critique
    # -------------------------------------------------------------------------
    def test_cmd_critique_spec_cli_integration(self):
        import argparse
        from io import StringIO
        from tools.brigade.cli import cmd_critique_spec
        from tools.brigade.spec_critic import SpecCritiqueResult

        args = argparse.Namespace(
            repo=str(self.repo_path),
            spec=".edge/specs/feat-staff.md",
            model="claude-opus-5-5-high",
            fallback_model="gemini-3.8-flash-high",
            timeout=180,
        )

        with patch("tools.brigade.cli.run_spec_critique") as mock_crit:
            # Success path
            mock_crit.return_value = SpecCritiqueResult(
                success=True,
                model_used="claude-opus-5-5-high",
                fallback_triggered=False,
                report_path=".edge/specs/feat-staff.critique.md",
                summary="Paraphrase: Clean staff slice with sound boundaries.",
                error=None,
            )
            with patch("sys.stdout", new=StringIO()) as fake_out:
                ret = cmd_critique_spec(args)
                self.assertEqual(ret, 0)
                out = fake_out.getvalue()
                self.assertIn("SUCCESS", out)
                self.assertIn("claude-opus-5-5-high", out)
                self.assertIn("feat-staff.critique.md", out)

            # Failure path
            mock_crit.return_value = SpecCritiqueResult(
                success=False,
                model_used="gemini-3.8-flash-high",
                fallback_triggered=True,
                report_path="",
                summary="",
                error="Quota exceeded on both models",
            )
            with patch("sys.stdout", new=StringIO()) as fake_out:
                ret = cmd_critique_spec(args)
                self.assertEqual(ret, 1)
                out = fake_out.getvalue()
                self.assertIn("FAILED", out)
                self.assertIn("Quota exceeded", out)

    def test_cmd_start_slice_cli_expected_files_and_spec(self):
        import argparse
        from io import StringIO
        from tools.brigade.cli import cmd_start_slice

        # Feature track
        args = argparse.Namespace(
            repo=str(self.repo_path),
            name="bundle-modal",
            track="feature",
            target_file="src/components/BundleModal.tsx",
            domain="bundle",
            test_cmd="npm run test:unit",
            allow_migration=True,
            expected_files="src/components/BundleModal.tsx,src/types/bundle.ts",
            spec=".edge/specs/bundle-modal.md",
        )
        self.fsm.state.active_ticket = None
        self.fsm.state.current_state = CycleState.IDLE
        self.fsm.save()

        with patch("sys.stdout", new=StringIO()) as fake_out:
            ret = cmd_start_slice(args)
            self.assertEqual(ret, 0)
            out = fake_out.getvalue()
            self.assertIn("RED_TEST", out)
            self.assertIn("Expected Files:", out)
            self.assertIn("Spec Path:", out)

        # Reload FSM from disk to verify persistence
        reloaded_fsm = BrigadeFSM(self.repo_path)
        ticket = reloaded_fsm.state.active_ticket
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.expected_files, ["src/components/BundleModal.tsx", "src/types/bundle.ts"])
        self.assertEqual(ticket.spec_path, ".edge/specs/bundle-modal.md")
        self.assertEqual(reloaded_fsm.state.current_state, CycleState.RED_TEST)

    # -------------------------------------------------------------------------
    # e) Automatic .edge/specs/<slice>.md -> .edge/archive/specs/ archival
    # -------------------------------------------------------------------------
    def test_ephemeral_spec_archiving_on_guard_staging_to_completed(self):
        specs_dir = self.repo_path / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec_file = specs_dir / "staff-alloc.md"
        spec_file.write_text("# Staff Allocation Spec\n\nINVEST slice spec content.", encoding="utf-8")

        self.ticket.branch_name = "feat/staff-alloc"
        self.ticket.spec_path = str(spec_file)

        # Call guard_staging_to_completed in non-git test environment
        self.fsm.state.active_ticket = self.ticket
        passed, msg, _ = self.fsm.guard_staging_to_completed()
        self.assertTrue(passed)

        # Verify spec was archived
        self.assertFalse(spec_file.exists(), "Source spec should have been archived/moved")
        archived_spec = self.repo_path / ".edge" / "archive" / "specs" / "staff-alloc.md"
        self.assertTrue(archived_spec.exists(), "Archived spec must exist in .edge/archive/specs/")
        self.assertIn("Staff Allocation Spec", archived_spec.read_text(encoding="utf-8"))

    def test_cli_register_and_stations_display_model(self):
        import io
        import contextlib
        import argparse
        from tools.brigade.cli import cmd_register, cmd_stations

        # Register station with custom model "pro"
        args_pro = argparse.Namespace(
            repo=str(self.repo_path),
            role="examiner",
            conversation_id="e1",
            name="Examiner Station",
            model="pro",
        )
        ret_pro = cmd_register(args_pro)
        self.assertEqual(ret_pro, 0)

        # Register station with default model "flash"
        args_flash = argparse.Namespace(
            repo=str(self.repo_path),
            role="coder",
            conversation_id="c1",
            name="Coder Station",
            model="flash",
        )
        ret_flash = cmd_register(args_flash)
        self.assertEqual(ret_flash, 0)

        # Assert .edge/brigade.json persists model
        state_file = self.repo_path / ".edge" / "brigade.json"
        self.assertTrue(state_file.exists(), "brigade.json should be created after registration")
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("stations", {}).get("examiner", {}).get("model"), "pro")
        self.assertEqual(data.get("stations", {}).get("coder", {}).get("model"), "flash")

        # Assert cmd_stations displays model
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ret_stat = cmd_stations(argparse.Namespace(repo=str(self.repo_path)))
        self.assertEqual(ret_stat, 0)
        output = buf.getvalue()
        self.assertIn("pro", output, "cmd_stations output should display model 'pro'")
        self.assertIn("flash", output, "cmd_stations output should display model 'flash'")




class TestStationRegistryPromptsAndOverlays(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_repo = Path(self.temp_dir)
        self.stations_dir = self.temp_repo / ".edge" / "stations"
        self.stations_dir.mkdir(parents=True, exist_ok=True)
        self.ticket = Ticket(
            ticket_id="TICK-SLICE1-001",
            track="feature",
            domain="billing",
            rule_id="RULE-FEATURE-NEW",
            severity="NORMAL",
            target_file="src/billing/service.py",
            line_number=1,
            fingerprint="fp-slice1",
            description="Billing service implementation",
            suggested_fix="Implement billing logic",
            branch_name="feat/billing-service",
            test_seam_command="pytest tests/test_billing.py",
            negative_constraints=["Do not mutate database schema"],
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_station_rubric_canonical_slugs_and_normalization(self):
        # Must support canonical hyphenated, underscore, uppercase, and enum roles
        roles_to_test = [
            ("coder", "coder.md"),
            ("surgeon", "surgeon.md"),
            ("seam_architect", "seam-architect.md"),
            ("seam-architect", "seam-architect.md"),
            ("researcher", "researcher.md"),
            ("spec_writer", "spec-writer.md"),
            ("spec-writer", "spec-writer.md"),
            ("spec_critic", "spec-critic.md"),
            ("spec-critic", "spec-critic.md"),
            ("examiner", "examiner.md"),
            ("orchestrator", "orchestrator.md"),
            ("qa_engineer", "qa-engineer.md"),
            ("qa-engineer", "qa-engineer.md"),
        ]
        for role_slug, expected_filename in roles_to_test:
            rubric = StationRegistry.load_station_rubric(role_slug)
            self.assertIsInstance(rubric, str)
            self.assertTrue(len(rubric) > 0)
            self.assertIn("Persona:", rubric)

        # Enums and uppercase
        self.assertIn("Persona:", StationRegistry.load_station_rubric(StationRole.CODER))
        self.assertIn("Persona:", StationRegistry.load_station_rubric("CODER"))
        self.assertIn("Persona:", StationRegistry.load_station_rubric("SEAM_ARCHITECT"))

        # Unknown fallback
        fallback = StationRegistry.load_station_rubric("unknown_station")
        self.assertIn("# Persona: UNKNOWN_STATION", fallback)
        self.assertIn("coding_standards.md", fallback)

    def test_load_station_rubric_with_repo_overlay(self):
        # 1. Overlay present with content
        overlay_file = self.stations_dir / "coder.md"
        overlay_file.write_text("### Local Coder Overlay: Always run ruff format\n", encoding="utf-8")

        rubric = StationRegistry.load_station_rubric("coder", repo_path=self.temp_repo)
        self.assertIn("Persona:", rubric)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", rubric)
        self.assertIn("### Local Coder Overlay: Always run ruff format", rubric)

        # 2. Overlay absent
        clean_rubric = StationRegistry.load_station_rubric("surgeon", repo_path=self.temp_repo)
        self.assertNotIn("## REPOSITORY-LOCAL STATION OVERLAY", clean_rubric)

        # 3. Overlay empty/whitespace only
        empty_overlay = self.stations_dir / "surgeon.md"
        empty_overlay.write_text("   \n\n  ", encoding="utf-8")
        clean_rubric_empty = StationRegistry.load_station_rubric("surgeon", repo_path=self.temp_repo)
        self.assertNotIn("## REPOSITORY-LOCAL STATION OVERLAY", clean_rubric_empty)

        # 4. Underscore overlay fallback lookup: .edge/stations/seam_architect.md
        underscore_overlay = self.stations_dir / "seam_architect.md"
        underscore_overlay.write_text("### Seam Underscore Overlay Rule", encoding="utf-8")
        seam_rubric = StationRegistry.load_station_rubric("seam_architect", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", seam_rubric)
        self.assertIn("### Seam Underscore Overlay Rule", seam_rubric)

    def test_prompt_builders_accept_repo_path_and_include_overlay(self):
        # Create overlays for multiple roles
        (self.stations_dir / "coder.md").write_text("### Local Coder Overlay Rule", encoding="utf-8")
        (self.stations_dir / "surgeon.md").write_text("### Local Surgeon Overlay Rule", encoding="utf-8")
        (self.stations_dir / "examiner.md").write_text("### Local Examiner Overlay Rule", encoding="utf-8")
        (self.stations_dir / "seam-architect.md").write_text("### Local Seam Overlay Rule", encoding="utf-8")
        (self.stations_dir / "researcher.md").write_text("### Local Researcher Overlay Rule", encoding="utf-8")
        (self.stations_dir / "spec-writer.md").write_text("### Local Spec Writer Overlay Rule", encoding="utf-8")
        (self.stations_dir / "qa-engineer.md").write_text("### Local QA Overlay Rule", encoding="utf-8")

        # Coder
        p_coder = StationRegistry.build_coder_prompt(self.ticket, "pytest", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_coder)
        self.assertIn("### Local Coder Overlay Rule", p_coder)

        # Surgeon
        p_surgeon = StationRegistry.build_surgeon_prompt(self.ticket, "development", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_surgeon)
        self.assertIn("### Local Surgeon Overlay Rule", p_surgeon)

        # Examiner
        p_examiner = StationRegistry.build_examiner_prompt(self.ticket, "development", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_examiner)
        self.assertIn("### Local Examiner Overlay Rule", p_examiner)

        # Seam Architect (testing canonical method and optional alias)
        p_seam = StationRegistry.build_seam_architect_prompt(self.ticket, "seam spec", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_seam)
        self.assertIn("### Local Seam Overlay Rule", p_seam)

        if hasattr(StationRegistry, "build_seam_prompt"):
            p_seam_alias = StationRegistry.build_seam_prompt(self.ticket, "seam spec", repo_path=self.temp_repo)
            self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_seam_alias)
            self.assertIn("### Local Seam Overlay Rule", p_seam_alias)

        # Researcher
        p_researcher = StationRegistry.build_researcher_prompt(self.ticket, "topic", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_researcher)
        self.assertIn("### Local Researcher Overlay Rule", p_researcher)

        # Spec Writer
        p_spec = StationRegistry.build_spec_writer_prompt(self.ticket, "story", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_spec)
        self.assertIn("### Local Spec Writer Overlay Rule", p_spec)

        # QA Prompt
        p_qa = StationRegistry.build_qa_prompt("checkout scenario", repo_path=self.temp_repo)
        self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", p_qa)
        self.assertIn("### Local QA Overlay Rule", p_qa)

        # Backward compatibility without repo_path
        p_coder_no_repo = StationRegistry.build_coder_prompt(self.ticket, "pytest")
        self.assertNotIn("## REPOSITORY-LOCAL STATION OVERLAY", p_coder_no_repo)
        p_surgeon_no_repo = StationRegistry.build_surgeon_prompt(self.ticket, "development")
        self.assertNotIn("## REPOSITORY-LOCAL STATION OVERLAY", p_surgeon_no_repo)

    def test_spec_critic_supports_repo_overlay(self):
        from tools.brigade.spec_critic import run_spec_critique

        (self.stations_dir / "spec-critic.md").write_text("### Local Spec Critic Overlay Rule", encoding="utf-8")
        specs_dir = self.temp_repo / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec_file = specs_dir / "billing-slice.md"
        spec_file.write_text("# Billing Spec\nINVEST slice content", encoding="utf-8")

        with patch("tools.brigade.spec_critic.run_command") as mock_run:
            mock_run.return_value = (0, "Advisory Critique Output", "")
            res = run_spec_critique(repo_path=self.temp_repo, spec_path=spec_file)
            self.assertTrue(res.success)
            mock_run.assert_called_once()
            cmd_args = mock_run.call_args[0][0]
            # Prompt is the last argument of agy command
            sent_prompt = cmd_args[-1]
            self.assertIn("## REPOSITORY-LOCAL STATION OVERLAY", sent_prompt)
            self.assertIn("### Local Spec Critic Overlay Rule", sent_prompt)


class TestPersonaCompletenessAndLineBudget(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]

    def test_all_canonical_personas_exist_and_line_budget(self):
        expected_personas = [
            "coder.md",
            "surgeon.md",
            "seam-architect.md",
            "researcher.md",
            "spec-writer.md",
            "spec-critic.md",
            "examiner.md",
            "orchestrator.md",
            "qa-engineer.md",
        ]
        agents_dir = self.repo_root / "agents"
        for persona_file in expected_personas:
            p_path = agents_dir / persona_file
            self.assertTrue(p_path.is_file(), f"Missing required canonical persona file: {p_path}")

        # Check line budget: every markdown in agents/*.md <= 60 lines
        for p_path in agents_dir.glob("*.md"):
            lines = p_path.read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(
                len(lines),
                60,
                f"Persona {p_path.name} exceeds 60-line budget: {len(lines)} lines",
            )

    def test_zero_legacy_tech_stack_leaks(self):
        # Purged: modaldialog, radix, shadcn, daisyui across agents/*.md and tools/brigade/stations.py
        target_files = list((self.repo_root / "agents").glob("*.md"))
        target_files.append(self.repo_root / "tools" / "brigade" / "stations.py")

        forbidden_patterns = ["modaldialog", "radix", "shadcn", "daisyui"]
        leaks_found = []

        for f in target_files:
            if not f.is_file():
                continue
            text = f.read_text(encoding="utf-8").lower()
            for pattern in forbidden_patterns:
                if pattern in text:
                    leaks_found.append(f"{f.name} contains forbidden pattern '{pattern}'")

        self.assertEqual(leaks_found, [], f"Found forbidden legacy stack leaks: {leaks_found}")

    def test_purged_playbooks_and_modernized_agents_rules(self):
        # bookings-playbook.md and customers-playbook.md must be deleted
        bookings_pb = self.repo_root / "rules" / "playbooks" / "generated" / "bookings-playbook.md"
        customers_pb = self.repo_root / "rules" / "playbooks" / "generated" / "customers-playbook.md"
        self.assertFalse(bookings_pb.exists(), f"Stale domain playbook must be deleted: {bookings_pb}")
        self.assertFalse(customers_pb.exists(), f"Stale domain playbook must be deleted: {customers_pb}")

        # rules/AGENTS.md must reference .edge/stations/ instead of <domain>-playbook.md
        agents_rules = self.repo_root / "rules" / "AGENTS.md"
        self.assertTrue(agents_rules.is_file())
        rules_text = agents_rules.read_text(encoding="utf-8")
        self.assertIn(".edge/stations/", rules_text)
        self.assertNotIn("<domain>-playbook.md", rules_text)

    def test_slice1_playbook_and_strategic_fork_directives_exist(self):
        # 1. rules/playbooks/swarm-vs-brigade.md must exist and contain 'model: "flash"' and 'narrator'
        pb_path = self.repo_root / "rules" / "playbooks" / "swarm-vs-brigade.md"
        self.assertTrue(pb_path.is_file(), f"Authoritative playbook missing: {pb_path}")
        pb_text = pb_path.read_text(encoding="utf-8")
        self.assertIn('model: "flash"', pb_text)
        self.assertIn("narrator", pb_text)

        # 2. rules/AGENTS.md must link to swarm-vs-brigade.md
        agents_rules = self.repo_root / "rules" / "AGENTS.md"
        self.assertTrue(agents_rules.is_file())
        agents_text = agents_rules.read_text(encoding="utf-8")
        self.assertIn("swarm-vs-brigade.md", agents_text, "rules/AGENTS.md must link to swarm-vs-brigade.md")

        # 3. agents/examiner.md, agents/spec-writer.md, agents/researcher.md, skills/edge-orchestrator/SKILL.md
        # must document Strategic Domain Forking (fork from spec_writer / researcher, never from coder / surgeon)
        examiner_path = self.repo_root / "agents" / "examiner.md"
        self.assertTrue(examiner_path.is_file())
        examiner_text = examiner_path.read_text(encoding="utf-8")
        self.assertIn("fork", examiner_text.lower(), "agents/examiner.md must document strategic forking")
        self.assertTrue(
            "spec_writer" in examiner_text.lower() or "researcher" in examiner_text.lower(),
            "agents/examiner.md must document forking from spec_writer or researcher",
        )
        self.assertTrue(
            "coder" in examiner_text.lower() or "surgeon" in examiner_text.lower(),
            "agents/examiner.md must explicitly forbid inheriting from coder or surgeon",
        )

        spec_writer_path = self.repo_root / "agents" / "spec-writer.md"
        self.assertTrue(spec_writer_path.is_file())
        spec_writer_text = spec_writer_path.read_text(encoding="utf-8")
        self.assertIn("fork", spec_writer_text.lower(), "agents/spec-writer.md must document domain context root for forking")

        researcher_path = self.repo_root / "agents" / "researcher.md"
        self.assertTrue(researcher_path.is_file())
        researcher_text = researcher_path.read_text(encoding="utf-8")
        self.assertIn("fork", researcher_text.lower(), "agents/researcher.md must document domain context root for forking")

        orch_path = self.repo_root / "skills" / "edge-orchestrator" / "SKILL.md"
        self.assertTrue(orch_path.is_file())
        orch_text = orch_path.read_text(encoding="utf-8")
        self.assertIn("fork", orch_text.lower(), "skills/edge-orchestrator/SKILL.md must document strategic forking")
        self.assertTrue(
            "spec_writer" in orch_text.lower() or "researcher" in orch_text.lower(),
            "skills/edge-orchestrator/SKILL.md must mention forking from spec_writer/researcher",
        )


class TestBrigadePromptCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)
        self.cli_path = Path(__file__).resolve().parents[1] / "tools" / "brigade" / "cli.py"

        # Initialize brigade state in temp repo
        from tools.brigade.fsm import BrigadeFSM
        self.fsm = BrigadeFSM(self.repo_path)
        self.fsm.save()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_prompt_standalone_all_roles(self):
        import subprocess
        roles = [
            "coder",
            "surgeon",
            "examiner",
            "researcher",
            "spec_writer",
            "spec-writer",
            "spec_critic",
            "spec-critic",
            "seam_architect",
            "seam-architect",
            "qa_engineer",
            "qa-engineer",
            "orchestrator",
        ]
        for role in roles:
            proc = subprocess.run(
                [sys.executable, str(self.cli_path), "prompt", str(self.repo_path), "--role", role],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"CLI prompt failed for role '{role}': stdout={proc.stdout}, stderr={proc.stderr}",
            )
            self.assertIn("Persona:", proc.stdout)

    def test_cli_prompt_with_active_ticket_includes_flight_recorder_alerts(self):
        import subprocess
        from tools.brigade.flight_recorder import FlightRecorder

        ticket = Ticket(
            ticket_id="TICK-PROMPT-01",
            track="feature",
            domain="checkout",
            rule_id="RULE-PROMPT",
            severity="NORMAL",
            target_file="src/checkout.py",
            line_number=1,
            fingerprint="fp-prompt",
            description="Checkout implementation",
            suggested_fix="Fix",
            branch_name="feat/prompt-test",
            test_seam_command="pytest",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.save()

        # Add dead-end negative constraint
        recorder = FlightRecorder(self.repo_path, "TICK-PROMPT-01")
        recorder.record_dead_end(
            station="coder",
            approach="Async generator stream",
            failure_reason="Lockup during socket close",
            negative_constraint="DO NOT use async generator stream for checkout socket.",
        )

        proc = subprocess.run(
            [sys.executable, str(self.cli_path), "prompt", str(self.repo_path), "--role", "coder"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"CLI prompt failed: {proc.stderr}")
        self.assertIn("ZERO-AMNESIA FLIGHT RECORDER", proc.stdout)
        self.assertIn("DO NOT use async generator stream", proc.stdout)
        self.assertIn("CODER", proc.stdout)


class TestStackAwareVerification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)
        self.fsm = BrigadeFSM(self.repo_path)
        self.ticket = Ticket(
            ticket_id="TICK-PYTHON-STACK",
            track="feature",
            domain="analytics",
            rule_id="RULE-PYTHON",
            severity="NORMAL",
            target_file="src/analytics.py",
            line_number=1,
            fingerprint="fp-py",
            description="Analytics engine",
            suggested_fix="Implement",
            branch_name="feat/py-analytics",
            test_seam_command="uv run --with pytest pytest -q",
        )
        self.fsm.state.active_ticket = self.ticket
        self.fsm.state.current_state = CycleState.VERIFY

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_guard_verify_in_python_repo_skips_tsc_and_runs_pytest(self):
        # Neither package.json nor tsconfig.json exist in self.repo_path
        self.assertFalse((self.repo_path / "tsconfig.json").exists())
        self.assertFalse((self.repo_path / "package.json").exists())

        executed_cmds = []

        def mock_run_cmd(cmd, cwd=None):
            executed_cmds.append(cmd)
            return (0, "1 passed in 0.04s", "")

        with patch.object(self.fsm, "_run_cmd", side_effect=mock_run_cmd):
            passed, msg, details = self.fsm.guard_verify_to_review()
            self.assertTrue(passed, f"guard_verify_to_review should pass: {msg}")

            # Verify pytest command was executed
            self.assertTrue(any("pytest" in str(c) for c in executed_cmds), f"Executed commands: {executed_cmds}")

            # Verify npx tsc --noEmit was cleanly SKIPPED
            for c in executed_cmds:
                c_str = " ".join(c) if isinstance(c, list) else str(c)
                self.assertNotIn("tsc", c_str, "TypeScript compiler must NOT be invoked in a Python-only repo")

    def test_guard_polish_in_python_repo_skips_tsc(self):
        self.fsm.state.current_state = CycleState.POLISH
        executed_cmds = []

        def mock_run_cmd(cmd, cwd=None):
            executed_cmds.append(cmd)
            return (0, "1 passed in 0.04s", "")

        with patch.object(self.fsm, "_run_cmd", side_effect=mock_run_cmd):
            passed, msg, details = self.fsm.guard_polish_to_gate()
            self.assertTrue(passed, f"guard_polish_to_gate should pass: {msg}")

            # Verify tsc was skipped
            for c in executed_cmds:
                c_str = " ".join(c) if isinstance(c, list) else str(c)
                self.assertNotIn("tsc", c_str, "TypeScript compiler must NOT be invoked in a Python-only repo")

    def test_guard_verify_with_tsconfig_executes_tsc(self):
        # When tsconfig.json exists, tsc must be executed
        (self.repo_path / "tsconfig.json").write_text("{}", encoding="utf-8")

        executed_cmds = []

        def mock_run_cmd(cmd, cwd=None):
            executed_cmds.append(cmd)
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else str(cmd)
            if "tsc" in cmd_str:
                return (1, "", "TS2322: Type error in index.ts")
            return (0, "tests passed", "")

        with patch.object(self.fsm, "_run_cmd", side_effect=mock_run_cmd):
            passed, msg, details = self.fsm.guard_verify_to_review()
            self.assertFalse(passed, "Guard should fail when tsc fails")
            self.assertIn("TypeScript compiler check failed", msg)
            self.assertTrue(any("tsc" in str(c) for c in executed_cmds))


class TestBrigadeSlice2LavishGatedQAState(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.fsm = BrigadeFSM(self.repo_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_cycle_state_enum_has_qa_and_ticket_lavish_fields(self):
        # 1. CycleState.QA enum member
        self.assertTrue(hasattr(CycleState, "QA"), "CycleState must have QA member")
        self.assertEqual(CycleState.QA.value, "QA")
        self.assertEqual(CycleState("QA"), CycleState.QA)

        # 2. Ticket constructor defaults
        ticket = Ticket(
            ticket_id="TICK-LAVISH-1",
            track="ui",
            domain="portal",
            rule_id="RULE-UI",
            severity="NORMAL",
            target_file="src/portal.tsx",
            line_number=1,
            fingerprint="fp1",
            description="Portal UI",
            suggested_fix="Fix",
            branch_name="feat/portal",
            test_seam_command="npm test",
        )
        self.assertIsNone(ticket.lavish_path)
        self.assertIsNone(ticket.require_qa)

        # 3. Ticket constructor explicit values
        ticket_custom = Ticket(
            ticket_id="TICK-LAVISH-2",
            track="ui",
            domain="portal",
            rule_id="RULE-UI",
            severity="NORMAL",
            target_file="src/portal.tsx",
            line_number=1,
            fingerprint="fp2",
            description="Portal UI with Lavish",
            suggested_fix="Fix",
            branch_name="feat/portal",
            test_seam_command="npm test",
            lavish_path=".lavish/portal.html",
            require_qa=True,
        )
        self.assertEqual(ticket_custom.lavish_path, ".lavish/portal.html")
        self.assertIs(ticket_custom.require_qa, True)

        # 4. to_dict serialization
        d = ticket_custom.to_dict()
        self.assertEqual(d.get("lavish_path"), ".lavish/portal.html")
        self.assertIs(d.get("require_qa"), True)

        # 5. from_dict deserialization with fields present
        restored = Ticket.from_dict(d)
        self.assertEqual(restored.lavish_path, ".lavish/portal.html")
        self.assertIs(restored.require_qa, True)

        # 6. from_dict deserialization backward compatibility (missing lavish_path and require_qa)
        legacy_dict = ticket.to_dict()
        legacy_dict.pop("lavish_path", None)
        legacy_dict.pop("require_qa", None)
        restored_legacy = Ticket.from_dict(legacy_dict)
        self.assertIsNone(restored_legacy.lavish_path)
        self.assertIsNone(restored_legacy.require_qa)

    def test_should_run_qa_lavish_gate_logic(self):
        ticket = Ticket(
            ticket_id="TICK-QA-GATE",
            track="ui",
            domain="billing",
            rule_id="RULE-UI",
            severity="NORMAL",
            target_file="src/billing.tsx",
            line_number=1,
            fingerprint="fp-qa",
            description="Billing UI",
            suggested_fix="Fix",
            branch_name="feat/billing-portal",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket

        # 1. Default: No .lavish/ file on disk and require_qa is None -> False
        self.assertFalse(self.fsm.should_run_qa(ticket))

        # 2. Explicit flag: require_qa = True -> True (even without files on disk)
        ticket.require_qa = True
        self.assertTrue(self.fsm.should_run_qa(ticket))

        # 3. Explicit flag: require_qa = False -> False (even if .lavish file exists)
        lavish_dir = self.repo_path / ".lavish"
        lavish_dir.mkdir(parents=True, exist_ok=True)
        (lavish_dir / "billing.html").write_text("<h1>Billing</h1>", encoding="utf-8")
        ticket.require_qa = False
        self.assertFalse(self.fsm.should_run_qa(ticket))

        # 4. Prototype on disk: require_qa is None, but <repo>/.lavish/<domain>.html exists -> True
        ticket.require_qa = None
        self.assertTrue(self.fsm.should_run_qa(ticket))

        # 5. Explicit lavish_path: points to prototype -> True
        (lavish_dir / "billing.html").unlink()
        self.assertFalse(self.fsm.should_run_qa(ticket))
        ticket.lavish_path = ".lavish/portal.html"
        self.assertTrue(self.fsm.should_run_qa(ticket))

    def test_advance_from_gate_routes_to_qa_or_bypasses_to_staging(self):
        ticket = Ticket(
            ticket_id="TICK-GATE-ROUTING",
            track="ui",
            domain="checkout",
            rule_id="RULE-UI",
            severity="NORMAL",
            target_file="src/checkout.tsx",
            line_number=1,
            fingerprint="fp-gate",
            description="Checkout",
            suggested_fix="Fix",
            branch_name="feat/checkout",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.GATE

        # Case A: When should_run_qa is True -> advance from GATE transitions to CycleState.QA
        ticket.require_qa = True
        qa_state = getattr(CycleState, "QA", "QA")
        with patch.object(self.fsm, "guard_gate_to_staging", return_value=(True, "Gate passed", {})):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok)
            self.assertEqual(next_state, qa_state)
            self.assertEqual(self.fsm.state.current_state, qa_state)
            self.assertIn("QA", msg)

        # Case B: When should_run_qa is False -> advance from GATE bypasses QA directly to CycleState.STAGING
        ticket.require_qa = False
        self.fsm.state.current_state = CycleState.GATE
        with patch.object(self.fsm, "guard_gate_to_staging", return_value=(True, "Gate passed", {})):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok)
            self.assertEqual(next_state, CycleState.STAGING)
            self.assertEqual(self.fsm.state.current_state, CycleState.STAGING)
            self.assertIn("STAGING", msg)

    def test_guard_qa_to_staging_passes_or_routes_to_polish(self):
        ticket = Ticket(
            ticket_id="TICK-QA-POLISH",
            track="ui",
            domain="dashboard",
            rule_id="RULE-UI",
            severity="NORMAL",
            target_file="src/dashboard.tsx",
            line_number=1,
            fingerprint="fp-qa-pol",
            description="Dashboard",
            suggested_fix="Fix",
            branch_name="feat/dashboard",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket
        qa_state = getattr(CycleState, "QA", "QA")
        self.fsm.state.current_state = qa_state

        # Case A: Clean findings or non-blocking advisory/warning with valid proof receipt -> advance to STAGING
        proof_dir = self.repo_path / ".edge" / "qa" / "proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        valid_receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter", "reload"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (proof_dir / "dashboard.json").write_text(json.dumps(valid_receipt), encoding="utf-8")

        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="qa",
                severity="WARNING",
                file_path="src/dashboard.tsx",
                rule="QA-SOMMELIER",
                description="Minor padding irregularity",
                suggested_fix="Adjust p-4 to p-6",
            )
        ]
        ok, next_state, msg = self.fsm.advance()
        self.assertTrue(ok)
        self.assertEqual(next_state, CycleState.STAGING)
        self.assertEqual(self.fsm.state.current_state, CycleState.STAGING)

        # Case B: Critical finding exists -> advance fails and transitions to POLISH
        self.fsm.state.current_state = qa_state
        self.fsm.state.review_findings.append(
            ReviewFinding(
                axis="qa",
                severity="CRITICAL",
                file_path="src/dashboard.tsx",
                rule="TIER1-CONSOLE-ERROR",
                description="Unhandled hydration error in UserCard",
                suggested_fix="Ensure client-only rendering or match SSR markup",
            )
        )
        ok, next_state, msg = self.fsm.advance()
        self.assertFalse(ok)
        self.assertEqual(next_state, CycleState.POLISH)
        self.assertEqual(self.fsm.state.current_state, CycleState.POLISH)
        self.assertIn("POLISH", msg)

    def test_cli_start_slice_qa_and_lavish_flags_and_qa_directives(self):
        import argparse
        from io import StringIO
        from tools.brigade.cli import cmd_start_slice

        # 1. start-slice with --lavish and --qa
        args_qa = argparse.Namespace(
            repo=str(self.repo_path),
            name="checkout-flow",
            track="ui",
            expected_files="src/checkout.tsx",
            spec=".edge/specs/checkout.md",
            lavish=".lavish/checkout-flow.html",
            require_qa=True,
        )
        with patch("sys.stdout", new=StringIO()):
            ret = cmd_start_slice(args_qa)
        self.assertEqual(ret, 0)

        reloaded_fsm = BrigadeFSM(self.repo_path)
        ticket = reloaded_fsm.state.active_ticket
        self.assertIsNotNone(ticket)
        self.assertEqual(getattr(ticket, "lavish_path", None), ".lavish/checkout-flow.html")
        self.assertIs(getattr(ticket, "require_qa", None), True)

        # Reset state for next slice invocation
        reloaded_fsm.state.active_ticket = None
        reloaded_fsm.state.current_state = CycleState.IDLE
        reloaded_fsm.save()

        # 2. start-slice with --no-qa
        args_no_qa = argparse.Namespace(
            repo=str(self.repo_path),
            name="cli-tool",
            track="core",
            expected_files="src/cli.ts",
            spec=None,
            lavish=None,
            require_qa=False,
        )
        with patch("sys.stdout", new=StringIO()):
            ret2 = cmd_start_slice(args_no_qa)
        self.assertEqual(ret2, 0)

        reloaded_fsm2 = BrigadeFSM(self.repo_path)
        ticket2 = reloaded_fsm2.state.active_ticket
        self.assertIsNotNone(ticket2)
        self.assertIs(getattr(ticket2, "require_qa", None), False)

        # 3. Assert agents/qa-engineer.md and rules/feature.md document Slice 2 contracts
        qa_doc = self.repo_root / "agents" / "qa-engineer.md"
        self.assertTrue(qa_doc.is_file(), f"Missing persona: {qa_doc}")
        qa_text = qa_doc.read_text(encoding="utf-8")
        self.assertIn("lavish", qa_text.lower(), "qa-engineer.md must reference Lavish prototype inspection")
        self.assertTrue(
            "console" in qa_text.lower() or "smoke" in qa_text.lower(),
            "qa-engineer.md must document Tier-1 Console/Smoke Gate",
        )
        self.assertTrue(
            "parity" in qa_text.lower() or "reality" in qa_text.lower(),
            "qa-engineer.md must document Lavish-to-Reality parity",
        )

        feat_rules = self.repo_root / "rules" / "feature.md"
        self.assertTrue(feat_rules.is_file(), f"Missing feature rules: {feat_rules}")
        feat_text = feat_rules.read_text(encoding="utf-8")
        self.assertIn("CycleState.QA", feat_text, "rules/feature.md must document CycleState.QA")
        self.assertTrue(
            "lavish varsa qa yap" in feat_text.lower() or "lavish-gated" in feat_text.lower(),
            "rules/feature.md must document Lavish-Gated QA Invariant ('Lavish varsa QA yap, yoksa es geç')",
        )


class TestBrigadeSlice3AutonomousKitchenRelay(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.fsm = BrigadeFSM(self.repo_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_format_kitchen_roster_empty_and_populated(self):
        # 1. Empty stations dict
        empty_output = StationRegistry.format_kitchen_roster({})
        self.assertIn("### 📋 ACTIVE KITCHEN ROSTER", empty_output)
        self.assertIn("No persistent station workers currently registered", empty_output)

        # 2. Populated stations dict
        stations = {
            "seam_architect": Station(
                role="seam_architect",
                conversation_id="conv-sa-1",
                name="Seam Architect Station",
                status="IDLE",
                model="flash",
            ),
            "coder": Station(
                role="coder",
                conversation_id="conv-cd-2",
                name="Coder Station",
                status="IDLE",
                model="flash",
            ),
            "examiner": Station(
                role="examiner",
                conversation_id="conv-ex-3",
                name="Examiner Station",
                status="IDLE",
                model="flash",
            ),
        }
        populated_output = StationRegistry.format_kitchen_roster(stations)
        self.assertIn("### 📋 ACTIVE KITCHEN ROSTER", populated_output)
        self.assertIn("| Role | Station Name | Conversation ID | Model | Status |", populated_output)
        self.assertIn("`seam_architect`", populated_output)
        self.assertIn("`conv-sa-1`", populated_output)
        self.assertIn("`coder`", populated_output)
        self.assertIn("`conv-cd-2`", populated_output)
        self.assertIn("`examiner`", populated_output)
        self.assertIn("`conv-ex-3`", populated_output)
        self.assertIn("`flash`", populated_output)
        self.assertIn("PEER-TO-PEER HANDOFF RULES", populated_output)
        self.assertIn("[READY_FOR_STAGING]", populated_output)
        self.assertIn("[ESCALATION]", populated_output)

    def test_get_next_station_handoff_across_lifecycle(self):
        # Register stations in fsm
        self.fsm.registry.register(StationRole.SEAM_ARCHITECT, "conv-sa")
        self.fsm.registry.register(StationRole.CODER, "conv-cd")
        self.fsm.registry.register(StationRole.EXAMINER, "conv-ex")
        self.fsm.registry.register(StationRole.QA_ENGINEER, "conv-qa")

        ticket = Ticket(
            ticket_id="TICK-FEAT-RELAY",
            track="feature",
            domain="relay",
            rule_id="RULE-RELAY",
            severity="NORMAL",
            target_file="src/relay.ts",
            line_number=1,
            fingerprint="fp-relay",
            description="Relay feature",
            suggested_fix="Fix",
            branch_name="feat/relay",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket

        # 1. RED_TEST -> seam_architect (conv-sa)
        h_red = self.fsm.get_next_station_handoff(CycleState.RED_TEST)
        self.assertEqual(h_red["target_role"], "seam_architect")
        self.assertEqual(h_red["recipient_cid"], "conv-sa")

        # 2. SURGERY (feature track) -> coder (conv-cd)
        h_surg = self.fsm.get_next_station_handoff(CycleState.SURGERY)
        self.assertEqual(h_surg["target_role"], "coder")
        self.assertEqual(h_surg["recipient_cid"], "conv-cd")

        # 3. REVIEW -> examiner (conv-ex)
        h_rev = self.fsm.get_next_station_handoff(CycleState.REVIEW)
        self.assertEqual(h_rev["target_role"], "examiner")
        self.assertEqual(h_rev["recipient_cid"], "conv-ex")

        # 4. POLISH (feature track) -> coder (conv-cd)
        h_pol = self.fsm.get_next_station_handoff(CycleState.POLISH)
        self.assertEqual(h_pol["target_role"], "coder")
        self.assertEqual(h_pol["recipient_cid"], "conv-cd")

        # 5. QA -> qa_engineer (conv-qa)
        h_qa = self.fsm.get_next_station_handoff(CycleState.QA)
        self.assertEqual(h_qa["target_role"], "qa_engineer")
        self.assertEqual(h_qa["recipient_cid"], "conv-qa")

        # 6. STAGING -> orchestrator ([READY_FOR_STAGING])
        h_stage = self.fsm.get_next_station_handoff(CycleState.STAGING)
        self.assertEqual(h_stage["target_role"], "orchestrator")
        self.assertIn("[READY_FOR_STAGING]", h_stage["instruction"])

    def test_cli_ticket_prompt_and_cmd_prompt_inject_kitchen_roster(self):
        import io
        import contextlib
        import argparse
        from tools.brigade.cli import cmd_ticket, cmd_prompt

        # Register coder and examiner stations in brigade state
        self.fsm.registry.register(StationRole.CODER, "conv-coder-99")
        self.fsm.registry.register(StationRole.EXAMINER, "conv-exam-88")

        ticket = Ticket(
            ticket_id="TICK-ROSTER-01",
            track="feature",
            domain="checkout",
            rule_id="RULE-FEAT",
            severity="NORMAL",
            target_file="src/checkout.ts",
            line_number=1,
            fingerprint="fp-roster",
            description="Checkout slice",
            suggested_fix="Implement",
            branch_name="feat/checkout",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY
        self.fsm.save()

        # 1. Test cmd_ticket --prompt
        buf_ticket = io.StringIO()
        with contextlib.redirect_stdout(buf_ticket):
            ret_ticket = cmd_ticket(argparse.Namespace(repo=str(self.repo_path), prompt=True, format="toon"))
        self.assertEqual(ret_ticket, 0)
        out_ticket = buf_ticket.getvalue()
        self.assertIn("ACTIVE KITCHEN ROSTER", out_ticket)
        self.assertIn("conv-coder-99", out_ticket)
        self.assertIn("conv-exam-88", out_ticket)

        # 2. Test cmd_prompt --role coder
        buf_prompt = io.StringIO()
        with contextlib.redirect_stdout(buf_prompt):
            ret_prompt = cmd_prompt(argparse.Namespace(repo=str(self.repo_path), role="coder", ticket=None))
        self.assertEqual(ret_prompt, 0)
        out_prompt = buf_prompt.getvalue()
        self.assertIn("ACTIVE KITCHEN ROSTER", out_prompt)
        self.assertIn("conv-coder-99", out_prompt)
        self.assertIn("conv-exam-88", out_prompt)

    def test_cli_advance_prints_next_station_handoff_banner(self):
        import io
        import contextlib
        import argparse
        from tools.brigade.cli import cmd_advance

        # Register coder station
        self.fsm.registry.register(StationRole.CODER, "conv-coder-relay")

        ticket = Ticket(
            ticket_id="TICK-ADV-RELAY",
            track="feature",
            domain="orders",
            rule_id="RULE-ADV",
            severity="NORMAL",
            target_file="src/orders.ts",
            line_number=1,
            fingerprint="fp-adv",
            description="Orders slice",
            suggested_fix="Fix",
            branch_name="feat/orders",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.RED_TEST
        self.fsm.save()

        with patch.object(BrigadeFSM, "guard_red_to_surgery", return_value=(True, "Red test verified", {})):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                ret = cmd_advance(argparse.Namespace(repo=str(self.repo_path), force=False))
            self.assertEqual(ret, 0)
            output = buf.getvalue()
            self.assertIn("NEXT STATION HANDOFF", output)
            self.assertIn("coder", output)
            self.assertIn("conv-coder-relay", output)

    def test_slice3_persona_autonomous_kitchen_relay_directives(self):
        personas = [
            "seam-architect.md",
            "coder.md",
            "surgeon.md",
            "examiner.md",
            "qa-engineer.md",
        ]
        agents_dir = self.repo_root / "agents"
        for persona_name in personas:
            p_path = agents_dir / persona_name
            self.assertTrue(p_path.is_file(), f"Missing persona: {p_path}")
            text = p_path.read_text(encoding="utf-8")
            self.assertIn(
                "Autonomous Kitchen Relay",
                text,
                f"Persona {persona_name} must document Autonomous Kitchen Relay directive",
            )
            self.assertIn(
                "NEXT STATION HANDOFF",
                text,
                f"Persona {persona_name} must reference NEXT STATION HANDOFF banner",
            )
            self.assertIn(
                "send_message",
                text,
                f"Persona {persona_name} must instruct direct peer communication via send_message",
            )

        # Examiner and QA Engineer must also document the Green-Zone Staging Invariant
        examiner_text = (agents_dir / "examiner.md").read_text(encoding="utf-8")
        self.assertIn("[READY_FOR_STAGING]", examiner_text)

        qa_text = (agents_dir / "qa-engineer.md").read_text(encoding="utf-8")
        self.assertIn("[READY_FOR_STAGING]", qa_text)




class TestDynamicSliceTargetGuardAndPorcelainParser(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        (self.repo_path / ".git").mkdir(parents=True, exist_ok=True)
        self.fsm = BrigadeFSM(self.repo_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_porcelain_path_parser_preserves_leading_status_space(self):
        """Validates that unstaged files with leading space (' M file') preserve the first path character."""
        from tools.brigade import fsm as fsm_mod

        parse_fn = getattr(fsm_mod, "_parse_porcelain_paths", None)
        self.assertIsNotNone(parse_fn, "_parse_porcelain_paths helper must be defined")

        porcelain_out = " M src/components/button.tsx\n"
        paths = parse_fn(porcelain_out)
        self.assertEqual(paths, ["src/components/button.tsx"])
        self.assertNotIn("rc/components/button.tsx", paths)

    def test_porcelain_path_parser_handles_renames_and_quotes(self):
        """Validates parsing of untracked, added, renamed, and quoted files from porcelain output."""
        from tools.brigade import fsm as fsm_mod

        parse_fn = getattr(fsm_mod, "_parse_porcelain_paths", None)
        self.assertIsNotNone(parse_fn, "_parse_porcelain_paths helper must be defined")

        porcelain_out = (
            "?? new_file.py\n"
            "A  src/index.ts\n"
            "R  old_file.ts -> new_file.ts\n"
            'RM "old path/with spaces.ts" -> "new path/with spaces.ts"\n'
            " D deleted.py\n"
        )
        paths = parse_fn(porcelain_out)
        self.assertIn("new_file.py", paths)
        self.assertIn("src/index.ts", paths)
        self.assertIn("new_file.ts", paths)
        self.assertIn("new path/with spaces.ts", paths)
        self.assertIn("deleted.py", paths)
        self.assertNotIn("old_file.ts", paths)
        self.assertNotIn("old path/with spaces.ts", paths)

    def test_porcelain_leading_space_integration_in_guard_surgery_to_verify(self):
        """Validates that unstaged modification with leading space (' M src/foo.ts') passes surgery guard."""
        ticket = Ticket(
            ticket_id="TICK-PORC-1",
            track="ui",
            domain="ui",
            rule_id="RULE-RAW-JSX",
            severity="NORMAL",
            target_file="src/components/button.tsx",
            line_number=1,
            fingerprint="fp-porc-1",
            description="Porcelain leading space check",
            suggested_fix="Fix",
            branch_name="refactor/ui-btn",
            test_seam_command="vitest",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "status" in cmd:
                    return (0, " M src/components/button.tsx\n", "")
                if "--numstat" in cmd:
                    return (0, "5\t2\tsrc/components/button.tsx\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertTrue(passed, f"Unstaged file with leading space must pass surgery guard: {msg}")

    def test_is_non_prod_file_helper(self):
        """Validates non-production exclusion filter for tests, ledgers, docs, and metadata."""
        from tools.brigade import fsm as fsm_mod

        is_non_prod = getattr(fsm_mod, "_is_non_prod_file", None)
        self.assertIsNotNone(is_non_prod, "_is_non_prod_file helper must be defined")

        # Non-prod paths
        self.assertTrue(is_non_prod("tests/test_fsm.py"))
        self.assertTrue(is_non_prod("src/components/button.test.tsx"))
        self.assertTrue(is_non_prod("src/components/button.spec.tsx"))
        self.assertTrue(is_non_prod("__tests__/auth.ts"))
        self.assertTrue(is_non_prod("test_helper.py"))
        self.assertTrue(is_non_prod("helper_test.py"))
        self.assertTrue(is_non_prod(".edge/specs/feature.md"))
        self.assertTrue(is_non_prod("docs/architecture.md"))
        self.assertTrue(is_non_prod("frontier.md"))
        self.assertTrue(is_non_prod(".frontier.toml"))
        self.assertTrue(is_non_prod("backlog.md"))
        self.assertTrue(is_non_prod("done-archive.md"))
        self.assertTrue(is_non_prod("package.json"))
        self.assertTrue(is_non_prod("pyproject.toml"))

        # Prod paths
        self.assertFalse(is_non_prod("src/actions/bookings.ts"))
        self.assertFalse(is_non_prod("tools/brigade/fsm.py"))
        self.assertFalse(is_non_prod("lib/auth/session.ts"))

    def test_start_slice_zero_phantom_target_fabrication(self):
        """Validates that omitting target_file leaves ticket.target_file as '' instead of synthesizing 'src/<name>'."""
        ok, ticket, msg = self.fsm.start_slice(
            name="user-auth",
            track="feature",
            target_file="",
            auto_lease_worktree=False,
        )
        self.assertTrue(ok)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket.target_file, "")
        self.assertNotEqual(ticket.target_file, "src/user-auth")

    def test_start_slice_discovers_spec_yaml_frontmatter(self):
        """Validates auto-discovery of expected_files from .edge/specs/<name>.md YAML frontmatter."""
        spec_dir = self.repo_path / ".edge" / "specs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_file = spec_dir / "user-auth.md"
        spec_file.write_text(
            "---\n"
            "feature: user-auth\n"
            "expected_files:\n"
            "  - src/lib/auth/token.ts\n"
            "  - src/lib/auth/session.ts\n"
            "---\n"
            "# Spec Prose\n"
            "Prose mentions nothing relevant here.\n",
            encoding="utf-8",
        )

        ok, ticket, msg = self.fsm.start_slice(
            name="user-auth",
            track="feature",
            target_file="",
            auto_lease_worktree=False,
        )
        self.assertTrue(ok)
        self.assertEqual(
            ticket.expected_files,
            ["src/lib/auth/token.ts", "src/lib/auth/session.ts"],
        )

    def test_start_slice_negative_invariant_no_prose_mining(self):
        """Validates strict negative invariant: file paths in spec markdown prose are NEVER mined."""
        spec_dir = self.repo_path / ".edge" / "specs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_file = spec_dir / "payment-flow.md"
        spec_file.write_text(
            "---\n"
            "feature: payment-flow\n"
            "expected_files:\n"
            "  - src/actions/checkout.ts\n"
            "---\n"
            "# Payment Flow Architecture\n"
            "Architecture inspects `src/db/schema.ts`, `rules/AGENTS.md`, and `tests/test_checkout.py`.\n"
            "Never modify `tools/gate.py`.\n",
            encoding="utf-8",
        )

        ok, ticket, msg = self.fsm.start_slice(
            name="payment-flow",
            track="feature",
            target_file="",
            auto_lease_worktree=False,
        )
        self.assertTrue(ok)
        self.assertEqual(ticket.expected_files, ["src/actions/checkout.ts"])
        self.assertNotIn("src/db/schema.ts", ticket.expected_files)
        self.assertNotIn("rules/AGENTS.md", ticket.expected_files)
        self.assertNotIn("tests/test_checkout.py", ticket.expected_files)
        self.assertNotIn("tools/gate.py", ticket.expected_files)

    def test_extract_spec_expected_files_stdlib_fallback_without_pyyaml(self):
        """Validates stdlib fallback in _extract_spec_expected_files when PyYAML is not installed."""
        from tools.brigade import fsm as fsm_mod

        extract_fn = getattr(fsm_mod, "_extract_spec_expected_files", None)
        self.assertIsNotNone(extract_fn, "_extract_spec_expected_files helper must be defined")

        spec_dir = self.repo_path / ".edge" / "specs"
        spec_dir.mkdir(parents=True, exist_ok=True)
        spec_file = spec_dir / "user-auth.md"
        spec_file.write_text(
            "---\n"
            "feature: user-auth\n"
            "expected_files:\n"
            "  - src/lib/auth/token.ts\n"
            "  - src/lib/auth/session.ts\n"
            "---\n"
            "# Spec Body\n",
            encoding="utf-8",
        )

        with patch.dict("sys.modules", {"yaml": None}):
            extracted = extract_fn(self.repo_path, clean_name="user-auth")
            self.assertEqual(extracted, ["src/lib/auth/token.ts", "src/lib/auth/session.ts"])

    def test_surgery_guard_mode_a_100_percent_pass(self):
        """Validates Mode A passes across core, feature, and ui tracks when 100% of expected_files are modified."""
        for track in ["feature", "core", "ui"]:
            with self.subTest(track=track):
                ticket = Ticket(
                    ticket_id=f"TICK-MODE-A-{track.upper()}",
                    track=track,
                    domain="auth",
                    rule_id="RULE-AUTH",
                    severity="NORMAL",
                    target_file="",
                    line_number=1,
                    fingerprint=f"fp-mode-a-{track}",
                    description="Mode A test",
                    suggested_fix="Fix",
                    branch_name=f"feat/auth-{track}",
                    test_seam_command="vitest",
                    expected_files=["src/lib/token.ts", "src/lib/session.ts"],
                )
                self.fsm.state.active_ticket = ticket
                self.fsm.state.current_state = CycleState.SURGERY

                with patch.object(self.fsm, "_run_cmd") as mock_cmd:
                    def side_effect(cmd, cwd=None):
                        if "--name-only" in cmd:
                            return (0, "src/lib/token.ts\nsrc/lib/session.ts\n", "")
                        if "--numstat" in cmd:
                            return (0, "10\t2\tsrc/lib/token.ts\n15\t5\tsrc/lib/session.ts\n", "")
                        return (0, "", "")

                    mock_cmd.side_effect = side_effect
                    passed, msg, details = self.fsm.guard_surgery_to_verify()
                    self.assertTrue(passed, f"Mode A should pass on {track}: {msg}")
                    self.assertIn("Surgery invariants passed", msg)
                    self.assertEqual(details["total_net"], 18)

    def test_surgery_guard_mode_a_missing_file_fail(self):
        """Validates Mode A failure diagnostic when an expected file is missing."""
        ticket = Ticket(
            ticket_id="TICK-MODE-A-FAIL",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="fp-mode-a-fail",
            description="Mode A missing file",
            suggested_fix="Fix",
            branch_name="feat/auth",
            test_seam_command="vitest",
            expected_files=["src/lib/token.ts", "src/lib/session.ts"],
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/lib/token.ts\n", "")
                if "--numstat" in cmd:
                    return (0, "10\t2\tsrc/lib/token.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("Incomplete Feature Implementation", msg)
            self.assertIn("src/lib/session.ts", details["missing_files"])

    def test_surgery_guard_mode_a_pure_glob_zero_prod_files_fail(self):
        """Validates Mode A pure glob with 0 modified production files fails cleanly."""
        ticket = Ticket(
            ticket_id="TICK-MODE-A-GLOB-ZERO",
            track="feature",
            domain="staff",
            rule_id="RULE-STAFF",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="fp-mode-a-glob-zero",
            description="Mode A pure glob check",
            suggested_fix="Fix",
            branch_name="feat/staff",
            test_seam_command="vitest",
            expected_files=["src/staff/**"],
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd", return_value=(0, "", "")):
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertTrue(
                "Incomplete Feature Implementation" in msg or "No production files" in msg,
                f"Unexpected failure message: {msg}",
            )

    def test_surgery_guard_mode_a_scope_drift_fail(self):
        """Validates Mode A detects and rejects unexpected production file modifications."""
        ticket = Ticket(
            ticket_id="TICK-MODE-A-DRIFT",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="fp-mode-a-drift",
            description="Mode A scope drift",
            suggested_fix="Fix",
            branch_name="feat/auth",
            test_seam_command="vitest",
            expected_files=["src/lib/token.ts"],
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/lib/token.ts\nsrc/lib/untracked_action.ts\n", "")
                if "--numstat" in cmd:
                    return (0, "10\t2\tsrc/lib/token.ts\n5\t1\tsrc/lib/untracked_action.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("Deterministic Spec-Code Scope Drift", msg)
            self.assertIn("src/lib/untracked_action.ts", details["unexpected_files"])

    def test_surgery_guard_mode_b_single_target_pass_and_fail(self):
        """Validates Mode B: single target_file passes when present and fails with standard diagnostic when absent."""
        ticket = Ticket(
            ticket_id="TICK-MODE-B",
            track="core",
            domain="bookings",
            rule_id="RULE-FAT-ACTION",
            severity="NORMAL",
            target_file="src/actions/bookings.ts",
            line_number=1,
            fingerprint="fp-mode-b",
            description="Mode B test",
            suggested_fix="Fix",
            branch_name="refactor/bookings",
            test_seam_command="vitest",
            expected_files=[],
            scaffolding_allowance=15,
            enforce_contraction=False,
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        # 1. Target file present in diff -> pass
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect_pass(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/actions/bookings.ts\n", "")
                if "--numstat" in cmd:
                    return (0, "10\t15\tsrc/actions/bookings.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect_pass
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertTrue(passed, f"Mode B should pass when target modified: {msg}")
            self.assertEqual(details["target_delta"], -5)

        # 2. Target file missing in diff -> fail
        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect_fail(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (0, "src/actions/other.ts\n", "")
                if "--numstat" in cmd:
                    return (0, "10\t5\tsrc/actions/other.ts\n", "")
                return (0, "", "")

            mock_cmd.side_effect = side_effect_fail
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("Target file 'src/actions/bookings.ts' was not modified", msg)

    def test_surgery_guard_mode_c_dynamic_slice_pass(self):
        """Validates Mode C passes when target_file='' and expected_files=[] if at least 1 production file is modified."""
        for track in ["feature", "core", "ui"]:
            with self.subTest(track=track):
                ticket = Ticket(
                    ticket_id=f"TICK-MODE-C-{track.upper()}",
                    track=track,
                    domain="calc",
                    rule_id="RULE-CALC",
                    severity="NORMAL",
                    target_file="",
                    line_number=1,
                    fingerprint=f"fp-mode-c-{track}",
                    description="Mode C test",
                    suggested_fix="Fix",
                    branch_name=f"feat/calc-{track}",
                    test_seam_command="vitest",
                    expected_files=[],
                    enforce_contraction=False,
                )
                self.fsm.state.active_ticket = ticket
                self.fsm.state.current_state = CycleState.SURGERY

                with patch.object(self.fsm, "_run_cmd") as mock_cmd:
                    def side_effect(cmd, cwd=None):
                        if "--name-only" in cmd:
                            return (0, "src/utils/calculator.ts\n", "")
                        if "--numstat" in cmd:
                            return (0, "25\t5\tsrc/utils/calculator.ts\n", "")
                        return (0, "", "")

                    mock_cmd.side_effect = side_effect
                    passed, msg, details = self.fsm.guard_surgery_to_verify()
                    self.assertTrue(passed, f"Mode C should pass for track={track}: {msg}")
                    self.assertIn("Surgery invariants passed", msg)
                    self.assertEqual(details["total_net"], 20)

    def test_surgery_guard_mode_c_dynamic_slice_fail_on_tests_or_ledgers_only(self):
        """Validates Mode C fails when only test, doc, metadata, or task ledger files are modified."""
        ticket = Ticket(
            ticket_id="TICK-MODE-C-FAIL",
            track="feature",
            domain="calc",
            rule_id="RULE-CALC",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="fp-mode-c-fail",
            description="Mode C fail on non-prod",
            suggested_fix="Fix",
            branch_name="feat/calc",
            test_seam_command="vitest",
            expected_files=[],
            enforce_contraction=False,
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        with patch.object(self.fsm, "_run_cmd") as mock_cmd:
            def side_effect(cmd, cwd=None):
                if "--name-only" in cmd:
                    return (
                        0,
                        "tests/unit/calc.test.ts\n"
                        ".edge/specs/calc.md\n"
                        "frontier.md\n"
                        ".frontier.toml\n"
                        "backlog.md\n"
                        "done-archive.md\n"
                        "data.json\n"
                        "settings.toml\n",
                        "",
                    )
                if "--numstat" in cmd:
                    return (
                        0,
                        "10\t0\ttests/unit/calc.test.ts\n"
                        "5\t0\t.edge/specs/calc.md\n"
                        "2\t0\tfrontier.md\n",
                        "",
                    )
                return (0, "", "")

            mock_cmd.side_effect = side_effect
            passed, msg, details = self.fsm.guard_surgery_to_verify()
            self.assertFalse(passed)
            self.assertIn("No production files were modified or created in dynamic slice", msg)

    def test_downstream_formatting_null_safety(self):
        """Validates downstream null-safety in StationRegistry, FlightRecorder, and FSM substeps when target_file is empty."""
        from tools.brigade.flight_recorder import FlightRecorder

        ticket_with_expected = Ticket(
            ticket_id="TICK-DOWNSTREAM-1",
            track="core",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="fp-down-1",
            description="Downstream with expected files",
            suggested_fix="Fix",
            branch_name="refactor/auth",
            test_seam_command="vitest",
            expected_files=["src/lib/a.ts", "src/lib/b.ts"],
        )

        ticket_dynamic = Ticket(
            ticket_id="TICK-DOWNSTREAM-2",
            track="core",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="fp-down-2",
            description="Downstream dynamic slice",
            suggested_fix="Fix",
            branch_name="refactor/auth",
            test_seam_command="vitest",
            expected_files=[],
        )

        # 1. StationRegistry.build_surgeon_prompt
        s_prompt1 = StationRegistry.build_surgeon_prompt(ticket_with_expected, "main")
        self.assertIn("in 'src/lib/a.ts, src/lib/b.ts'", s_prompt1)
        self.assertIn("- Target File: src/lib/a.ts, src/lib/b.ts", s_prompt1)
        self.assertNotIn("in ''", s_prompt1)

        s_prompt2 = StationRegistry.build_surgeon_prompt(ticket_dynamic, "main")
        self.assertIn("in '(dynamic-slice)'", s_prompt2)
        self.assertIn("- Target File: (dynamic-slice)", s_prompt2)
        self.assertNotIn("in ''", s_prompt2)

        # 2. StationRegistry.build_seam_architect_prompt
        seam_prompt1 = StationRegistry.build_seam_architect_prompt(ticket_with_expected, "Spec summary")
        self.assertIn("in 'src/lib/a.ts, src/lib/b.ts'", seam_prompt1)
        self.assertNotIn("in ''", seam_prompt1)

        seam_prompt2 = StationRegistry.build_seam_architect_prompt(ticket_dynamic, "Spec summary")
        self.assertIn("in '(dynamic-slice)'", seam_prompt2)
        self.assertNotIn("in ''", seam_prompt2)

        # 3. StationRegistry.build_examiner_prompt
        exam_prompt1 = StationRegistry.build_examiner_prompt(ticket_with_expected, "main")
        self.assertIn("- Target File: src/lib/a.ts, src/lib/b.ts", exam_prompt1)
        self.assertIn("- Expected Files: src/lib/a.ts, src/lib/b.ts", exam_prompt1)

        exam_prompt2 = StationRegistry.build_examiner_prompt(ticket_dynamic, "main")
        self.assertIn("- Target File: (dynamic-slice)", exam_prompt2)

        # 4. FlightRecorder set_metadata and markdown rendering
        recorder = FlightRecorder(self.repo_path, "TICK-RECORDER")
        recorder.set_metadata(
            track="core",
            domain="auth",
            target_file="",
            worktree_path="/tmp/wt",
            expected_files=["src/lib/a.ts", "src/lib/b.ts"],
        )
        self.assertEqual(recorder.data.get("expected_files"), ["src/lib/a.ts", "src/lib/b.ts"])
        md1 = recorder._render_markdown()
        self.assertIn("- **Target File:** `src/lib/a.ts, src/lib/b.ts`", md1)
        self.assertIn("- **Expected Files:** `src/lib/a.ts, src/lib/b.ts`", md1)

        recorder2 = FlightRecorder(self.repo_path, "TICK-RECORDER-2")
        recorder2.set_metadata(
            track="core",
            domain="auth",
            target_file="",
            worktree_path="/tmp/wt",
            expected_files=[],
        )
        md2 = recorder2._render_markdown()
        self.assertIn("- **Target File:** `(dynamic-slice)`", md2)

        # 5. FSM Substep Hints
        self.fsm.state.active_ticket = ticket_with_expected
        hints1 = self.fsm._get_substeps_for_state(CycleState.RED_TEST)
        self.assertNotIn("tests for  to establish", " ".join(hints1))

        self.fsm.state.active_ticket = ticket_dynamic
        hints2 = self.fsm._get_substeps_for_state(CycleState.RED_TEST)
        self.assertNotIn("tests for  to establish", " ".join(hints2))
        self.assertIn("(dynamic-slice)", " ".join(hints2))




class TestBrigadeQABrowserProofGate(unittest.TestCase):
    """
    Test suite for QA Browser Subagent Delegation & Behavioral Proof Receipt Gate
    (SPEC-EDGE-BRIGADE-002)
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.fsm = BrigadeFSM(self.repo_path)
        self.proofs_dir = self.repo_path / ".edge" / "qa" / "proofs"
        self.proofs_dir.mkdir(parents=True, exist_ok=True)

        self.ticket = Ticket(
            ticket_id="TICK-DASHBOARD-1",
            track="ui",
            domain="dashboard",
            rule_id="RULE-UI",
            severity="NORMAL",
            target_file="src/dashboard.tsx",
            line_number=1,
            fingerprint="fp-dash",
            description="User dashboard view",
            suggested_fix="Fix",
            branch_name="feat/dashboard-v2",
            test_seam_command="npm test",
        )
        self.fsm.state.active_ticket = self.ticket
        self.fsm.state.current_state = CycleState.QA
        self.fsm.state.review_findings = []

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_resolve_qa_slug_precedence(self):
        # Priority 1: Explicit scenario_slug if not default 'qa_scenario'
        self.assertEqual(
            StationRegistry._resolve_qa_slug("Custom_Scenario_Slug", ticket=None),
            "custom-scenario-slug",
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("Explicit_Slug", ticket=self.ticket),
            "explicit-slug",
        )

        # Priority 2: ticket.domain (lowercased, '_' replaced with '-')
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=self.ticket),
            "dashboard",
        )
        t_domain = Ticket(
            ticket_id="TICK-1",
            track="ui",
            domain="User_Profile",
            rule_id="R",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="",
            description="",
            suggested_fix="",
            branch_name="feat/some_branch",
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_domain),
            "user-profile",
        )

        # Priority 3: ticket.branch_name (prefixes stripped, lowercased, '_' replaced with '-')
        for prefix, expected in [
            ("feat/checkout_flow", "checkout-flow"),
            ("refactor/user_auth", "user-auth"),
            ("hotfix/crash_fix", "crash-fix"),
            ("chore/cleanup_db", "cleanup-db"),
        ]:
            t_branch = Ticket(
                ticket_id="TICK-2",
                track="ui",
                domain="",
                rule_id="R",
                severity="NORMAL",
                target_file="",
                line_number=1,
                fingerprint="",
                description="",
                suggested_fix="",
                branch_name=prefix,
            )
            self.assertEqual(
                StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_branch),
                expected,
            )

        # Priority 4: ticket.ticket_id (lowercased, '_' replaced with '-')
        t_tid = Ticket(
            ticket_id="TICK_999_PAYMENT",
            track="ui",
            domain=None,
            rule_id="R",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="",
            description="",
            suggested_fix="",
            branch_name=None,
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_tid),
            "tick-999-payment",
        )

        # Priority 5: Fallback to 'qa_scenario'
        t_empty = Ticket(
            ticket_id="",
            track="ui",
            domain="",
            rule_id="R",
            severity="NORMAL",
            target_file="",
            line_number=1,
            fingerprint="",
            description="",
            suggested_fix="",
            branch_name="",
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_empty),
            "qa_scenario",
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=None),
            "qa_scenario",
        )

    def test_guard_qa_to_staging_missing_receipt(self):
        # Ensure proof receipt does not exist
        proof_file = self.proofs_dir / "dashboard.json"
        if proof_file.exists():
            proof_file.unlink()

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertIn("missing proof receipt at '.edge/qa/proofs/dashboard.json'", msg)
        self.assertEqual(details.get("error"), "MISSING_PROOF_RECEIPT")
        self.assertEqual(details.get("expected_slug"), "dashboard")

        # advance() must block and stay in CycleState.QA
        adv_ok, next_state, adv_msg = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)
        self.assertIn("QA guard blocked advancement", adv_msg)

    def test_guard_qa_to_staging_malformed_json(self):
        proof_file = self.proofs_dir / "dashboard.json"
        proof_file.write_text("{not a valid json syntax", encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertIn("malformed JSON in proof receipt", msg)
        self.assertEqual(details.get("error"), "MALFORMED_PROOF_RECEIPT")
        self.assertEqual(details.get("expected_slug"), "dashboard")

        adv_ok, next_state, _ = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)

    def test_guard_qa_to_staging_empty_urls(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": [],
            "user_actions_executed": ["click button#filter"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "INVALID_VISITED_URLS")
        self.assertIn("visited_urls", msg)

        adv_ok, next_state, _ = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)

    def test_guard_qa_to_staging_empty_actions(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": [],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "INVALID_ACTIONS")
        self.assertIn("user_actions_executed", msg)

        adv_ok, next_state, _ = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)

    def test_guard_qa_to_staging_persistence_false(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter"],
            "persistence_verified": False,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "PERSISTENCE_NOT_VERIFIED")
        self.assertIn("persistence_verified", msg)

        adv_ok, next_state, _ = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)

    def test_guard_qa_to_staging_console_false(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter"],
            "persistence_verified": True,
            "console_clean": False,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "CONSOLE_NOT_CLEAN")
        self.assertIn("console_clean", msg)

        adv_ok, next_state, _ = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)

    def test_guard_qa_to_staging_empty_screenshots(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "MISSING_SCREENSHOTS")
        self.assertIn("screenshot_paths", msg)

        adv_ok, next_state, _ = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.QA)
        self.assertEqual(self.fsm.state.current_state, CycleState.QA)

    def test_guard_qa_to_staging_valid_receipt_advances(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter", "reload"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertTrue(ok)
        self.assertIn("QA verification passed", msg)
        self.assertIn("proof_details", details)
        self.assertEqual(details["proof_details"].get("slug"), "dashboard")
        self.assertEqual(details["proof_details"].get("screenshot_count"), 1)

        adv_ok, next_state, adv_msg = self.fsm.advance()
        self.assertTrue(adv_ok)
        self.assertEqual(next_state, CycleState.STAGING)
        self.assertEqual(self.fsm.state.current_state, CycleState.STAGING)

    def test_guard_qa_to_staging_critical_findings_priority(self):
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter", "reload"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        # Add critical review finding
        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="qa",
                severity="CRITICAL",
                file_path="src/dashboard.tsx",
                rule="TIER1-CONSOLE-ERROR",
                description="Unhandled hydration error",
                suggested_fix="Fix hydration",
            )
        ]

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertFalse(ok)
        self.assertEqual(details.get("critical_count"), 1)
        self.assertIn("critical defects", msg)

        # advance() must fail and route directly to POLISH
        adv_ok, next_state, adv_msg = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(next_state, CycleState.POLISH)
        self.assertEqual(self.fsm.state.current_state, CycleState.POLISH)
        self.assertIn("POLISH", adv_msg)

    def test_build_qa_prompt_pruning(self):
        prompt = StationRegistry.build_qa_prompt(
            user_scenario_en="User checks dashboard metrics",
            target_route="http://localhost:3000/dashboard",
            scenario_slug="dashboard",
        )
        self.assertIn("4-STEP BEHAVIORAL PROOF CHAIN", prompt)
        self.assertIn('TypeName="browser"', prompt)
        self.assertIn('Model="flash"', prompt)
        self.assertIn(".edge/qa/proofs/", prompt)
        self.assertNotIn(".edge/qa/replays/", prompt)
        self.assertNotIn("chrome-devtools-axi run", prompt)


class TestWorktreeAutoRebaseAndQaPreflight(unittest.TestCase):
    """
    Contract & hermetic unit tests for:
    - Pre-Staging Automated Worktree Rebase & Escalation (Scenarios 1-3)
    - Hermetic Verification DRY Helper (Scenario 4)
    - Deterministic QA DB-Drift Preflight Gate (Scenario 5)
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.temp_dir)
        (self.repo_path / ".git").mkdir(parents=True, exist_ok=True)

        self.worktree_path = self.repo_path / "worktrees" / "slot-1"
        self.worktree_path.mkdir(parents=True, exist_ok=True)

        self.fsm = BrigadeFSM(self.repo_path)
        self.ticket = Ticket(
            ticket_id="TICK-FEAT-REBASE-SYNC",
            track="feature",
            domain="core",
            rule_id="RULE-SYNC",
            severity="NORMAL",
            target_file="src/actions/sync.ts",
            line_number=1,
            fingerprint="fp-sync-1",
            description="Rebase enforcer unit testing",
            suggested_fix="Automate worktree rebase before fast-forward merge",
            branch_name="feat/rebase-sync",
            worktree_path=str(self.worktree_path),
        )
        self.fsm.state.active_ticket = self.ticket
        self.fsm.state.base_branch = "development"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # --- Scenario 1: Clean Auto-Rebase & Verification Pass ---
    @patch("tools.brigade.fsm.return_worktree", return_value=(True, "returned"))
    @patch("tools.brigade.fsm.run_command")
    def test_guard_staging_to_completed_clean_auto_rebase_and_ff_merge(
        self, mock_run, mock_return_wt
    ):
        """
        Scenario 1:
        When base_branch has diverged (merge-base --is-ancestor exits 1):
        1. FSM executes git rebase <base_branch> inside worktree.
        2. Clean rebase (exit 0) triggers hermetic verification.
        3. If verification passes, fast-forward merge executes in primary repo.
        4. Ticket completes successfully and returns True.
        """
        def run_cmd_side_effect(cmd, cwd=None):
            cmd_list = list(cmd)
            # Status check in primary repo
            if "status" in cmd_list and "--porcelain" in cmd_list:
                return 0, "", ""
            # Branch check in primary repo
            if "branch" in cmd_list and "--show-current" in cmd_list:
                return 0, "development\n", ""
            # merge-base diverged
            if "merge-base" in cmd_list:
                return 1, "", "Diverged: base branch has advanced"
            # In-worktree rebase succeeds
            if "rebase" in cmd_list and "development" in cmd_list:
                return 0, "Successfully rebased and updated refs/heads/feat/rebase-sync.\n", ""
            # Fast-forward merge into base branch
            if "merge" in cmd_list and "--ff-only" in cmd_list:
                return 0, "Updating a1b2c3d..e4f5g6h\nFast-forward\n", ""
            return 0, "", ""

        mock_run.side_effect = run_cmd_side_effect

        # Mock hermetic verification helper to pass
        if hasattr(self.fsm, "_run_hermetic_verification"):
            self.fsm._run_hermetic_verification = MagicMock(
                return_value=(True, "Hermetic verification clean.")
            )

        passed, msg, details = self.fsm.guard_staging_to_completed()

        self.assertTrue(passed, f"guard_staging_to_completed should pass after clean auto-rebase, got: {msg}")
        self.assertIn("successfully merged", msg)

        # Verify rebase was called inside worktree
        rebase_calls = [
            c for c in mock_run.call_args_list
            if "rebase" in c[0][0] and "development" in c[0][0]
        ]
        self.assertTrue(rebase_calls, "git rebase development should be executed inside worktree")
        self.assertEqual(
            rebase_calls[0][1].get("cwd"),
            self.worktree_path,
            "Rebase must be executed inside worktree_path",
        )

        # Verify ff-only merge was called in primary repo
        merge_calls = [
            c for c in mock_run.call_args_list
            if "merge" in c[0][0] and "--ff-only" in c[0][0]
        ]
        self.assertTrue(merge_calls, "git merge --ff-only should be executed in primary repo")
        self.assertEqual(
            merge_calls[0][1].get("cwd"),
            self.repo_path,
            "Merge must be executed in primary repo",
        )

    # --- Scenario 2: Rebase Conflict -> Abort & Escalate to PAUSED ---
    @patch("tools.brigade.fsm.return_worktree", return_value=(True, "returned"))
    @patch("tools.brigade.fsm.FlightRecorder")
    @patch("tools.brigade.fsm.run_command")
    def test_guard_staging_to_completed_rebase_conflict_aborts_and_escalates(
        self, mock_run, mock_recorder_cls, mock_return_wt
    ):
        """
        Scenario 2:
        When git rebase fails (exit != 0) due to merge conflicts:
        1. FSM runs git diff --name-only --diff-filter=U to inspect conflicting files.
        2. FSM runs git rebase --abort to restore worktree to clean HEAD.
        3. FSM invokes escalate(), pausing the FSM into CycleState.PAUSED.
        4. Ticket status is updated to ESCALATED and returns passed=False with conflicting files.
        """
        def run_cmd_side_effect(cmd, cwd=None):
            cmd_list = list(cmd)
            if "status" in cmd_list and "--porcelain" in cmd_list:
                return 0, "", ""
            if "branch" in cmd_list and "--show-current" in cmd_list:
                return 0, "development\n", ""
            if "merge-base" in cmd_list:
                return 1, "", "Diverged"
            if "rebase" in cmd_list and "development" in cmd_list:
                return 1, "", "CONFLICT (content): Merge conflict in src/actions/sync.ts"
            if "diff" in cmd_list and "--diff-filter=U" in cmd_list:
                return 0, "src/actions/sync.ts\n", ""
            if "rebase" in cmd_list and "--abort" in cmd_list:
                return 0, "", ""
            if "rev-parse" in cmd_list:
                return 0, "abc12345\n", ""
            return 0, "", ""

        mock_run.side_effect = run_cmd_side_effect

        passed, msg, details = self.fsm.guard_staging_to_completed()

        self.assertFalse(passed, "guard_staging_to_completed must fail on rebase conflict")
        self.assertTrue(details.get("escalated"), "Details must indicate escalation")
        self.assertIn("src/actions/sync.ts", details.get("conflicting_files", []))
        self.assertEqual(
            self.fsm.state.current_state,
            CycleState.PAUSED,
            "FSM must transition to PAUSED upon rebase conflict escalation",
        )
        self.assertEqual(
            self.fsm.state.active_ticket.status,
            "ESCALATED",
            "Active ticket must be marked ESCALATED",
        )

        # Verify abort was called in worktree
        abort_calls = [
            c for c in mock_run.call_args_list
            if "rebase" in c[0][0] and "--abort" in c[0][0]
        ]
        self.assertTrue(abort_calls, "git rebase --abort must be executed on conflict")
        self.assertEqual(abort_calls[0][1].get("cwd"), self.worktree_path)

    # --- Scenario 3: Clean Rebase -> Post-Rebase Verification Failure -> Escalate to PAUSED ---
    @patch("tools.brigade.fsm.return_worktree", return_value=(True, "returned"))
    @patch("tools.brigade.fsm.FlightRecorder")
    @patch("tools.brigade.fsm.run_command")
    def test_guard_staging_to_completed_semantic_test_failure_escalates(
        self, mock_run, mock_recorder_cls, mock_return_wt
    ):
        """
        Scenario 3:
        When git rebase succeeds (exit 0) but post-rebase verification fails:
        1. FSM executes escalate() citing verification failure.
        2. FSM transitions to CycleState.PAUSED.
        3. Merge into primary repo is refused.
        """
        def run_cmd_side_effect(cmd, cwd=None):
            cmd_list = list(cmd)
            if "status" in cmd_list and "--porcelain" in cmd_list:
                return 0, "", ""
            if "branch" in cmd_list and "--show-current" in cmd_list:
                return 0, "development\n", ""
            if "merge-base" in cmd_list:
                return 1, "", "Diverged"
            if "rebase" in cmd_list and "development" in cmd_list:
                return 0, "Successfully rebased", ""
            if "rev-parse" in cmd_list:
                return 0, "abc12345\n", ""
            return 0, "", ""

        mock_run.side_effect = run_cmd_side_effect

        # Mock verification to fail
        if hasattr(self.fsm, "_run_hermetic_verification"):
            self.fsm._run_hermetic_verification = MagicMock(
                return_value=(False, "Broken assertion: test_sync failed post-rebase")
            )

        passed, msg, details = self.fsm.guard_staging_to_completed()

        self.assertFalse(passed, "guard_staging_to_completed must fail on semantic verification failure")
        self.assertTrue(details.get("escalated"), "Details must indicate escalation")
        self.assertTrue(details.get("semantic_conflict"), "Details must indicate semantic conflict")
        self.assertEqual(
            self.fsm.state.current_state,
            CycleState.PAUSED,
            "FSM must transition to PAUSED upon semantic verification failure",
        )
        self.assertEqual(self.fsm.state.active_ticket.status, "ESCALATED")

        # Verify merge was NEVER called
        merge_calls = [
            c for c in mock_run.call_args_list
            if "merge" in c[0][0] and "--ff-only" in c[0][0]
        ]
        self.assertEqual(len(merge_calls), 0, "git merge --ff-only must NOT be called on semantic failure")

    # --- Scenario 4: _run_hermetic_verification DRY Helper ---
    def test_run_hermetic_verification_method_presence_and_dry_usage(self):
        """
        Scenario 4:
        Validates _run_hermetic_verification helper exists and is used by both
        guard_verify_to_review and guard_polish_to_gate.
        """
        self.assertTrue(
            hasattr(self.fsm, "_run_hermetic_verification"),
            "BrigadeFSM must define _run_hermetic_verification helper method",
        )

        # Test delegating failure from _run_hermetic_verification to guard_verify_to_review
        self.fsm._run_hermetic_verification = MagicMock(
            return_value=(False, "Hermetic test failed: 1 failure")
        )
        v_passed, v_msg, _ = self.fsm.guard_verify_to_review()
        self.assertFalse(v_passed)
        self.assertIn("Hermetic test failed: 1 failure", v_msg)

        # Test delegating failure from _run_hermetic_verification to guard_polish_to_gate
        p_passed, p_msg, _ = self.fsm.guard_polish_to_gate()
        self.assertFalse(p_passed)
        self.assertIn("Hermetic test failed: 1 failure", p_msg)

        # Test delegating success
        self.fsm._run_hermetic_verification = MagicMock(
            return_value=(True, "All tests and types clean")
        )
        v_passed, _, _ = self.fsm.guard_verify_to_review()
        self.assertTrue(v_passed)
        p_passed, _, _ = self.fsm.guard_polish_to_gate()
        self.assertTrue(p_passed)

    @patch("tools.brigade.fsm.run_command")
    def test_run_hermetic_verification_execution_logic(self, mock_run):
        """Tests npm and tsc execution logic inside _run_hermetic_verification."""
        self.assertTrue(
            hasattr(self.fsm, "_run_hermetic_verification"),
            "BrigadeFSM must define _run_hermetic_verification",
        )

        # 1. Failure when scoped test exits != 0
        mock_run.return_value = (1, "", "FAIL src/sync.test.ts")
        passed, msg = self.fsm._run_hermetic_verification(work_dir=self.worktree_path)
        self.assertFalse(passed)
        self.assertIn("failed", msg)

        # 2. Failure when tsc exits != 0
        (self.worktree_path / "tsconfig.json").write_text("{}", encoding="utf-8")
        def run_side_effect(cmd, cwd=None):
            if "tsc" in cmd:
                return 1, "Type error in sync.ts", ""
            return 0, "Tests passed", ""

        mock_run.side_effect = run_side_effect
        passed, msg = self.fsm._run_hermetic_verification(work_dir=self.worktree_path)
        self.assertFalse(passed)
        self.assertIn("TypeScript compiler check failed", msg)

    # --- Scenario 5: Deterministic QA db:check-drift Preflight Hook ---
    def test_qa_db_drift_preflight_method_presence(self):
        """Scenario 5: Validates _run_qa_db_drift_preflight method exists."""
        self.assertTrue(
            hasattr(self.fsm, "_run_qa_db_drift_preflight"),
            "BrigadeFSM must define _run_qa_db_drift_preflight method",
        )

    def test_qa_db_drift_preflight_zero_cost_bypass_when_script_absent(self):
        """Scenario 5a: Missing db:check-drift script returns True immediately."""
        self.assertTrue(hasattr(self.fsm, "_run_qa_db_drift_preflight"))
        pkg_json = self.worktree_path / "package.json"
        pkg_json.write_text(json.dumps({"scripts": {"test": "jest"}}), encoding="utf-8")

        passed, msg = self.fsm._run_qa_db_drift_preflight(work_dir=self.worktree_path)
        self.assertTrue(passed)
        self.assertIn("bypass", msg.lower())

    @patch("tools.brigade.fsm.run_command")
    def test_qa_db_drift_preflight_fails_on_drift(self, mock_run):
        """Scenario 5b: Returns False when npm run db:check-drift exits != 0."""
        self.assertTrue(hasattr(self.fsm, "_run_qa_db_drift_preflight"))
        pkg_json = self.worktree_path / "package.json"
        pkg_json.write_text(
            json.dumps({"scripts": {"db:check-drift": "prisma migrate diff"}}),
            encoding="utf-8",
        )

        mock_run.return_value = (1, "", "Schema drift: table users has uncommitted column")
        passed, msg = self.fsm._run_qa_db_drift_preflight(work_dir=self.worktree_path)
        self.assertFalse(passed)
        self.assertIn("FAILED", msg)

    @patch("tools.brigade.fsm.run_command")
    def test_advance_gate_to_qa_blocked_by_db_drift(self, mock_run):
        """Scenario 5c: advance() halts at GATE when db:check-drift fails."""
        self.fsm.state.current_state = CycleState.GATE
        self.fsm.guard_gate_to_staging = MagicMock(return_value=(True, "Gate OK", {}))
        self.fsm.should_run_qa = MagicMock(return_value=True)

        pkg_json = self.worktree_path / "package.json"
        pkg_json.write_text(
            json.dumps({"scripts": {"db:check-drift": "prisma migrate diff"}}),
            encoding="utf-8",
        )

        # Mock drift failure
        mock_run.return_value = (1, "", "Migration drift detected")

        adv_ok, state, adv_msg = self.fsm.advance()
        self.assertFalse(adv_ok)
        self.assertEqual(state, CycleState.GATE)
        self.assertEqual(self.fsm.state.current_state, CycleState.GATE)
        self.assertIn("QA Preflight blocked advancement", adv_msg)

        # Check guard failure recorded
        last_failure = self.fsm.state.guard_failures[-1]
        self.assertTrue(last_failure.details.get("db_drift"))

    @patch("tools.brigade.fsm.run_command")
    def test_guard_qa_to_staging_blocked_by_db_drift(self, mock_run):
        """Scenario 5d: guard_qa_to_staging blocks advancement on db:check-drift failure."""
        self.fsm.state.current_state = CycleState.QA
        self.fsm.state.review_findings = []

        pkg_json = self.worktree_path / "package.json"
        pkg_json.write_text(
            json.dumps({"scripts": {"db:check-drift": "prisma migrate diff"}}),
            encoding="utf-8",
        )

        # Mock proof receipt validator to pass
        with patch("tools.brigade.fsm._validate_qa_proof_receipt", return_value=(True, "Valid receipt", {"slug": "sync"})):
            mock_run.return_value = (1, "", "Migration drift detected")
            passed, msg, details = self.fsm.guard_qa_to_staging()
            self.assertFalse(passed)
            self.assertTrue(details.get("db_drift"))




class TestBrigadeFSMHardeningAndWorktreePreemption(unittest.TestCase):
    """
    Contract and Unit tests for Brigade FSM Hardening:
    - Polish-to-Review Re-Verification Quality Loop
    - Zero-Exit Hermetic Verification Gate before GATE
    - FlightRecorder record_dead_end is_abort flag and status protection
    - Suffix-preserving collision-free ticket ID generation
    - Checkpoint model active_worktree and stashed_ticket persistence
    - Worktree-aware pause() and resume() executing strictly in worktree
    - Hotfix Preemption in start_slice() while state is PAUSED
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.fsm = BrigadeFSM(self.repo_path)
        self.worktree_dir = tempfile.mkdtemp()
        self.worktree_path = Path(self.worktree_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        shutil.rmtree(self.worktree_dir, ignore_errors=True)

    def test_polish_advances_to_review_and_clears_findings(self):
        """Scenario 1: Polish transitions to REVIEW and clears prior review findings."""
        self.fsm.state.current_state = CycleState.POLISH
        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="spec",
                severity="CRITICAL",
                file_path="src/lib/auth.ts",
                rule="SEC-01",
                description="Token leak",
                suggested_fix="Sanitize token",
            )
        ]

        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(True, "Tests & TSC clean")):
            success, next_state, msg = self.fsm.advance()
            self.assertTrue(success)
            self.assertEqual(next_state, CycleState.REVIEW, "POLISH must transition to REVIEW for examiner re-audit")
            self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)
            self.assertEqual(self.fsm.state.review_findings, [], "Remediated review findings must be cleared")

    def test_review_blocked_by_hermetic_verification_failure(self):
        """Scenario 2: REVIEW to GATE blocked when hermetic verification fails (routes to POLISH)."""
        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="standards",
                severity="WARNING",
                file_path="src/lib/auth.ts",
                rule="STYLE-01",
                description="Minor comment style",
                suggested_fix="Fix style",
            )
        ]

        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(False, "Test failed: syntax error in main.py")):
            next_state, msg, details = self.fsm.guard_review_to_next()
            self.assertEqual(next_state, CycleState.POLISH, "Must route to POLISH when tests/tsc fail even with 0 critical findings")
            self.assertIn("verification failed", msg.lower())

            adv_success, adv_state, adv_msg = self.fsm.advance()
            self.assertTrue(adv_success)
            self.assertEqual(adv_state, CycleState.POLISH)
            self.assertEqual(self.fsm.state.current_state, CycleState.POLISH)

    def test_review_advances_to_gate_when_verification_passes_and_zero_critical(self):
        """Scenario 2b: REVIEW advances to GATE when 0 critical findings AND verification passes."""
        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="standards",
                severity="WARNING",
                file_path="src/lib/auth.ts",
                rule="STYLE-01",
                description="Minor comment style",
                suggested_fix="Fix style",
            )
        ]

        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(True, "Tests & compilation clean")):
            next_state, msg, details = self.fsm.guard_review_to_next()
            self.assertEqual(next_state, CycleState.GATE)

            adv_success, adv_state, adv_msg = self.fsm.advance()
            self.assertTrue(adv_success)
            self.assertEqual(adv_state, CycleState.GATE)
            self.assertEqual(self.fsm.state.current_state, CycleState.GATE)

    def test_flight_recorder_record_dead_end_is_abort_flag(self):
        """Scenario 3 & 4: record_dead_end preserves ACTIVE status unless is_abort=True."""
        from tools.brigade.flight_recorder import FlightRecorder

        recorder = FlightRecorder(self.repo_path, "TICK-TEST-FR")
        self.assertEqual(recorder.data["status"], "ACTIVE")

        # Guard retry (default is_abort=False)
        recorder.record_dead_end(
            title="Attempted approach 1",
            reason="Compilation error",
            prohibited_rule="Do not use any",
        )
        self.assertEqual(
            recorder.data["status"],
            "ACTIVE",
            "Guard retries with is_abort=False must NOT set status to ABANDONED",
        )
        self.assertEqual(len(recorder.data["dead_ends"]), 1)

        # Deliberate abort (is_abort=True)
        recorder.record_dead_end(
            title="Deadlock path",
            reason="Unresolvable cyclic dependency",
            prohibited_rule="Avoid cyclic coupling",
            is_abort=True,
        )
        self.assertEqual(
            recorder.data["status"],
            "ABANDONED",
            "Deliberate abort with is_abort=True must mark status as ABANDONED",
        )
        self.assertEqual(len(recorder.data["dead_ends"]), 2)

    def test_fsm_abort_marks_flight_recorder_abandoned(self):
        """Scenario 4: fsm.abort() marks FlightRecorder status as ABANDONED."""
        from tools.brigade.flight_recorder import FlightRecorder

        ticket = Ticket(
            ticket_id="TICK-FEAT-ABORT-TEST",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="src/auth.ts",
            line_number=1,
            fingerprint="fp_abort",
            description="Abort test",
            suggested_fix="None",
            branch_name="feat/abort-test",
            test_seam_command="pytest",
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.SURGERY

        self.fsm.abort("Deadlock condition")

        recorder = FlightRecorder(self.repo_path, ticket.ticket_id)
        self.assertEqual(
            recorder.data["status"],
            "ABANDONED",
            "fsm.abort() must mark FlightRecorder status as ABANDONED",
        )

    def test_start_slice_collision_free_ticket_id_generation(self):
        """Scenario 5: start_slice preserves suffix in ticket_id to prevent collision across slices."""
        # Short / normal names (<= 18 chars)
        ok1, t1, _ = self.fsm.start_slice("distill-v2-slice1", track="feature", auto_lease_worktree=False)
        self.assertTrue(ok1)
        self.assertEqual(t1.ticket_id, "TICK-FEAT-DISTILL-V2-SLICE1")

        self.fsm.state.active_ticket = None
        self.fsm.state.current_state = CycleState.IDLE

        ok2, t2, _ = self.fsm.start_slice("distill-v2-slice2", track="feature", auto_lease_worktree=False)
        self.assertTrue(ok2)
        self.assertEqual(t2.ticket_id, "TICK-FEAT-DISTILL-V2-SLICE2")
        self.assertNotEqual(t1.ticket_id, t2.ticket_id, "Slice 1 and Slice 2 must have distinct ticket IDs")

        # Long names (> 18 chars) sharing a long common prefix
        self.fsm.state.active_ticket = None
        self.fsm.state.current_state = CycleState.IDLE

        ok3, t3, _ = self.fsm.start_slice("distill-v2-slice-long-seq1", track="feature", auto_lease_worktree=False)
        self.assertTrue(ok3)

        self.fsm.state.active_ticket = None
        self.fsm.state.current_state = CycleState.IDLE

        ok4, t4, _ = self.fsm.start_slice("distill-v2-slice-long-seq2", track="feature", auto_lease_worktree=False)
        self.assertTrue(ok4)

        # First 11 chars + last 6 chars: distill-v2- and g-seq1 / g-seq2
        self.assertEqual(t3.ticket_id, "TICK-FEAT-DISTILL-V2--G-SEQ1")
        self.assertEqual(t4.ticket_id, "TICK-FEAT-DISTILL-V2--G-SEQ2")
        self.assertNotEqual(t3.ticket_id, t4.ticket_id, "Long names sharing prefix must not collide on ticket_id")

    def test_checkpoint_model_active_worktree_and_stashed_ticket(self):
        """Scenario 7a: Checkpoint model supports active_worktree and stashed_ticket serialization."""
        ticket = Ticket(
            ticket_id="TICK-STASHED-1",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="src/auth.ts",
            line_number=1,
            fingerprint="fp_stash",
            description="Stashed ticket",
            suggested_fix="None",
            branch_name="feat/auth-stash",
            test_seam_command="pytest",
            worktree_path=str(self.worktree_path),
        )

        cp = Checkpoint(
            paused_at="2026-11-12T08:00:00Z",
            reason="HOTFIX_PREEMPTION",
            base_branch="main",
            active_branch="feat/auth-stash",
            worktree_path=str(self.worktree_path),
            active_worktree=str(self.worktree_path),
            active_ticket=ticket,
            stashed_ticket=ticket.to_dict(),
            fsm_state="SURGERY",
        )

        d = cp.to_dict()
        self.assertEqual(d["active_worktree"], str(self.worktree_path))
        self.assertIsNotNone(d["stashed_ticket"])
        self.assertEqual(d["stashed_ticket"]["ticket_id"], "TICK-STASHED-1")

        restored = Checkpoint.from_dict(d)
        self.assertEqual(restored.active_worktree, str(self.worktree_path))
        self.assertIsNotNone(restored.active_ticket)
        self.assertEqual(restored.active_ticket.ticket_id, "TICK-STASHED-1")

    def test_worktree_aware_pause_executes_strictly_in_worktree(self):
        """Scenario 6: pause() executes git status, add, and commit strictly inside worktree_path."""
        ticket = Ticket(
            ticket_id="TICK-WT-PAUSE",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="src/auth.ts",
            line_number=1,
            fingerprint="fp_wt_pause",
            description="WT pause",
            suggested_fix="None",
            branch_name="feat/wt-pause",
            test_seam_command="pytest",
            worktree_path=str(self.worktree_path),
        )
        self.fsm.state.active_ticket = ticket
        self.fsm.state.active_worktree = str(self.worktree_path)
        self.fsm.state.active_branch = "feat/wt-pause"
        self.fsm.state.current_state = CycleState.SURGERY

        recorded_calls = []

        def mock_run_cmd(cmd, cwd=None):
            recorded_calls.append((cmd, cwd))
            if "--porcelain" in cmd:
                return (0, " M src/auth.ts\n", "")
            if "rev-parse" in cmd:
                return (0, "sha_wt_123\n", "")
            return (0, "", "")

        with patch.object(self.fsm, "_run_cmd", side_effect=mock_run_cmd):
            cp = self.fsm.pause(reason="MANUAL_PAUSE")

            self.assertEqual(self.fsm.state.current_state, CycleState.PAUSED)
            self.assertEqual(cp.active_worktree, str(self.worktree_path))
            self.assertIsNotNone(cp.stashed_ticket)

            # Ensure all git commands ran inside the worktree
            self.assertTrue(len(recorded_calls) > 0)
            for cmd, cwd in recorded_calls:
                self.assertEqual(
                    Path(cwd),
                    self.worktree_path,
                    f"Command {cmd} was executed in {cwd} instead of worktree {self.worktree_path}",
                )

    def test_worktree_aware_resume_bypasses_primary_checkout(self):
        """Scenario 8: resume() does NOT call git checkout in self.target_repo when active_worktree exists."""
        self.fsm.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        ticket = Ticket(
            ticket_id="TICK-WT-RESUME",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="src/auth.ts",
            line_number=1,
            fingerprint="fp_wt_res",
            description="WT resume",
            suggested_fix="None",
            branch_name="feat/wt-resume",
            test_seam_command="pytest",
            worktree_path=str(self.worktree_path),
        )
        cp = Checkpoint(
            paused_at="2026-11-12T08:00:00Z",
            reason="MANUAL_PAUSE",
            base_branch="main",
            active_branch="feat/wt-resume",
            worktree_path=str(self.worktree_path),
            active_worktree=str(self.worktree_path),
            active_ticket=ticket,
            stashed_ticket=ticket.to_dict(),
            fsm_state="SURGERY",
        )
        with open(self.fsm.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(cp.to_dict(), f)

        recorded_cmds = []

        def mock_run_cmd(cmd, cwd=None):
            recorded_cmds.append((cmd, cwd))
            if "branch" in cmd and "--show-current" in cmd:
                return (0, "main\n", "")
            return (0, "", "")

        with patch.object(self.fsm, "_run_cmd", side_effect=mock_run_cmd):
            success, restored_cp, msg = self.fsm.resume()
            self.assertTrue(success)
            self.assertEqual(self.fsm.state.current_state, CycleState.SURGERY)
            self.assertEqual(self.fsm.state.active_ticket.ticket_id, "TICK-WT-RESUME")
            self.assertEqual(self.fsm.state.active_worktree, str(self.worktree_path))

            # Verify git checkout was NOT executed in primary repository
            for cmd, cwd in recorded_cmds:
                if "checkout" in cmd:
                    self.fail(f"git checkout was executed in {cwd} despite active_worktree presence!")

    def test_hotfix_preemption_on_paused_state(self):
        """Scenario 7: start_slice succeeds on PAUSED state, preserving stashed checkpoint for later resume."""
        epic_ticket = Ticket(
            ticket_id="TICK-FEAT-EPIC-SLIC1",
            track="feature",
            domain="auth",
            rule_id="RULE-AUTH",
            severity="NORMAL",
            target_file="src/auth.ts",
            line_number=1,
            fingerprint="fp_epic",
            description="Epic slice 1",
            suggested_fix="None",
            branch_name="feat/epic-slice1",
            test_seam_command="pytest",
            worktree_path=str(self.worktree_path),
        )
        self.fsm.state.active_ticket = epic_ticket
        self.fsm.state.active_branch = "feat/epic-slice1"
        self.fsm.state.active_worktree = str(self.worktree_path)
        self.fsm.state.current_state = CycleState.PAUSED

        # Create checkpoint file for the paused epic
        self.fsm.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        cp = Checkpoint(
            paused_at="2026-11-12T07:30:00Z",
            reason="CONTEXT_HEAT",
            base_branch="main",
            active_branch="feat/epic-slice1",
            worktree_path=str(self.worktree_path),
            active_worktree=str(self.worktree_path),
            active_ticket=epic_ticket,
            stashed_ticket=epic_ticket.to_dict(),
            fsm_state="SURGERY",
        )
        with open(self.fsm.checkpoint_file, "w", encoding="utf-8") as f:
            json.dump(cp.to_dict(), f)

        # Start urgent hotfix slice while FSM is in PAUSED
        ok, hotfix_ticket, msg = self.fsm.start_slice("urgent-hotfix", track="feature", auto_lease_worktree=False)
        self.assertTrue(ok, f"Hotfix preemption must succeed on PAUSED state: {msg}")
        self.assertEqual(hotfix_ticket.ticket_id, "TICK-FEAT-URGENT-HOTFIX")
        self.assertEqual(self.fsm.state.current_state, CycleState.RED_TEST)
        self.assertTrue(self.fsm.checkpoint_file.exists(), "Original checkpoint must NOT be destroyed by preemption")

        # Simulate hotfix completion to IDLE
        self.fsm.state.active_ticket = None
        self.fsm.state.active_branch = None
        self.fsm.state.active_worktree = None
        self.fsm.state.current_state = CycleState.IDLE

        # Resume the parked epic
        with patch.object(self.fsm, "_run_cmd", return_value=(0, "main", "")):
            res_ok, restored_cp, res_msg = self.fsm.resume()
            self.assertTrue(res_ok)
            self.assertEqual(self.fsm.state.current_state, CycleState.SURGERY)
            self.assertEqual(self.fsm.state.active_ticket.ticket_id, "TICK-FEAT-EPIC-SLIC1")
            self.assertEqual(self.fsm.state.active_worktree, str(self.worktree_path))


if __name__ == "__main__":
    unittest.main()

