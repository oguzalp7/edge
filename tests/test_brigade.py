#!/usr/bin/env python3
"""
Unit Tests for Edge Brigade: Michelin Station & Deterministic State Machine Engine
"""

import os
import sys
import json
import zlib
import struct
import shutil
import tempfile
import importlib
import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import tools.brigade.models as brigade_models
import tools.brigade.fsm as brigade_fsm
import tools.brigade.cli as brigade_cli
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
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.examiner_receipt = ExaminerReceipt(verdict="PASS", summary="Clean review")

        # Case A: Clean review with PASS seal -> goes to STAGING
        self.fsm.state.review_findings = [
            ReviewFinding(axis="standards", severity="WARNING", file_path="a.ts", rule="r1", description="minor", suggested_fix="f1")
        ]
        next_state, msg, _ = self.fsm.guard_review_to_next()
        self.assertEqual(next_state, CycleState.STAGING)

        # Case B: Critical review finding -> goes to POLISH
        self.fsm.state.review_findings.append(
            ReviewFinding(axis="spec", severity="CRITICAL", file_path="b.ts", rule="r2", description="missing tx", suggested_fix="f2")
        )
        next_state, msg, _ = self.fsm.guard_review_to_next()
        self.assertEqual(next_state, CycleState.POLISH)

    def test_full_cycle_progression_and_reset(self):
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm, "guard_verify_to_gate"), "BrigadeFSM must define guard_verify_to_gate")
        self.assertTrue(hasattr(self.fsm, "guard_gate_to_next"), "BrigadeFSM must define guard_gate_to_next")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

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

        # VERIFY -> GATE
        with patch.object(self.fsm, "guard_verify_to_gate", return_value=(True, "ok", {})):
            s, state, _ = self.fsm.advance()
            self.assertTrue(s)
            self.assertEqual(state, CycleState.GATE)

        # GATE -> REVIEW (no QA required)
        with patch.object(self.fsm, "guard_gate_to_next", return_value=(True, "ok", {})):
            s, state, _ = self.fsm.advance()
            self.assertTrue(s)
            self.assertEqual(state, CycleState.REVIEW)

        # REVIEW -> STAGING (sealed PASS receipt + clean review + hermetic verification pass)
        self.fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="PASS",
            summary="Clean 3-axis review",
            ticket_id=ticket.ticket_id,
        )
        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(True, "ok")):
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
        self.assertIsNone(self.fsm.state.examiner_receipt)

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

    def test_omission_audit_rubric_gates_across_all_stations(self):
        agents_dir = self.repo_root / "agents"
        forbidden_tokens = ("modaldialog", "radix", "shadcn", "daisyui")

        for p_path in agents_dir.glob("*.md"):
            text = p_path.read_text(encoding="utf-8")
            lines = text.splitlines()
            self.assertLessEqual(
                len(lines),
                60,
                f"Persona {p_path.name} exceeds 60-line budget: {len(lines)} lines",
            )
            lowered = text.lower()
            for tok in forbidden_tokens:
                self.assertNotIn(tok, lowered, f"{p_path.name} contains forbidden token '{tok}'")

        # 1. agents/spec-writer.md
        sw_text = (agents_dir / "spec-writer.md").read_text(encoding="utf-8")
        sw_lower = sw_text.lower()
        for tok in ("200", "value sourcing", "pagination", "idempotency", "abac", "4-state", "force-dynamic"):
            self.assertIn(tok, sw_lower, f"agents/spec-writer.md missing required rubric token '{tok}'")
        self.assertTrue(
            "DEFAULT_" in sw_text or "MOCK_" in sw_text,
            "agents/spec-writer.md must contain 'DEFAULT_' or 'MOCK_'",
        )

        # 2. agents/spec-critic.md
        sc_lower = (agents_dir / "spec-critic.md").read_text(encoding="utf-8").lower()
        for tok in ("pagination", "idempotency", "abac", "rollback", "mock"):
            self.assertIn(tok, sc_lower, f"agents/spec-critic.md missing required rubric token '{tok}'")

        # 3. agents/seam-architect.md
        sa_lower = (agents_dir / "seam-architect.md").read_text(encoding="utf-8").lower()
        for tok in ("idempotency", "pagination", "abac", "rollback", "revalidatepath"):
            self.assertIn(tok, sa_lower, f"agents/seam-architect.md missing required rubric token '{tok}'")

        # 4. agents/coder.md
        cd_text = (agents_dir / "coder.md").read_text(encoding="utf-8")
        cd_lower = cd_text.lower()
        self.assertIn("disabled={isPending}", cd_text, "agents/coder.md missing 'disabled={isPending}'")
        self.assertIn("rollback", cd_lower, "agents/coder.md missing 'rollback'")
        self.assertTrue(
            "DEFAULT_" in cd_text or "MOCK_" in cd_text,
            "agents/coder.md must contain 'DEFAULT_' or 'MOCK_'",
        )
        for tok in ("force-dynamic", "dark:", "aria-label"):
            self.assertIn(tok, cd_lower, f"agents/coder.md missing '{tok}'")

        # 5. agents/surgeon.md
        sg_text = (agents_dir / "surgeon.md").read_text(encoding="utf-8")
        sg_lower = sg_text.lower()
        self.assertIn("disabled={isPending}", sg_text, "agents/surgeon.md missing 'disabled={isPending}'")
        self.assertIn("rollback", sg_lower, "agents/surgeon.md missing 'rollback'")
        self.assertTrue(
            "DEFAULT_" in sg_text or "MOCK_" in sg_text,
            "agents/surgeon.md must contain 'DEFAULT_' or 'MOCK_'",
        )
        for tok in ("force-dynamic", "dark:", "aria-label"):
            self.assertIn(tok, sg_lower, f"agents/surgeon.md missing '{tok}'")

        # 6. agents/examiner.md
        ex_lower = (agents_dir / "examiner.md").read_text(encoding="utf-8").lower()
        for tok in ("pagination", "idempotency", "abac", "rollback", "bg-white", "aria-label"):
            self.assertIn(tok, ex_lower, f"agents/examiner.md missing required rubric token '{tok}'")

        # 7. agents/qa-engineer.md
        qa_lower = (agents_dir / "qa-engineer.md").read_text(encoding="utf-8").lower()
        for tok in ("double-submit", "reload", "pagination", "4-state", "dark"):
            self.assertIn(tok, qa_lower, f"agents/qa-engineer.md missing required rubric token '{tok}'")

        # 8. agents/researcher.md
        rs_text = (agents_dir / "researcher.md").read_text(encoding="utf-8")
        rs_lower = rs_text.lower()
        for tok in ("pagination", "abac", "idempotency"):
            self.assertIn(tok, rs_lower, f"agents/researcher.md missing required rubric token '{tok}'")
        self.assertTrue(
            "DEFAULT_" in rs_text or "MOCK_" in rs_text,
            "agents/researcher.md must contain 'DEFAULT_' or 'MOCK_'",
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
        self.assertTrue(hasattr(self.fsm, "guard_gate_to_next"), "BrigadeFSM must define guard_gate_to_next")
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
        with patch.object(self.fsm, "guard_gate_to_next", return_value=(True, "Gate passed", {})):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok)
            self.assertEqual(next_state, qa_state)
            self.assertEqual(self.fsm.state.current_state, qa_state)
            self.assertIn("QA", msg)

        # Case B: When should_run_qa is False -> advance from GATE bypasses QA directly to CycleState.REVIEW
        ticket.require_qa = False
        self.fsm.state.current_state = CycleState.GATE
        with patch.object(self.fsm, "guard_gate_to_next", return_value=(True, "Gate passed", {})):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok)
            self.assertEqual(next_state, CycleState.REVIEW)
            self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)
            self.assertIn("REVIEW", msg)

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

        # Case A: Clean findings or non-blocking advisory/warning with valid proof receipt -> advance to REVIEW
        proof_dir = self.repo_path / ".edge" / "qa" / "proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        shot_file = self.repo_path / ".edge" / "qa" / "screenshots" / "dash.png"
        shot_file.parent.mkdir(parents=True, exist_ok=True)
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\nvalid-dashboard-screenshot")
        valid_receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter", "reload"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
            "host_facts_verified": True,
            "db_crosscheck": {"dashboard": 1},
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
        self.assertTrue(ok, f"QA advance should succeed with valid ProofVerifier receipt: {msg}")
        self.assertEqual(next_state, CycleState.REVIEW)
        self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)

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
            branch_name="feat/dashboard",
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

        # Priority 2: ticket.spec_path stem overrides domain and branch_name (prevents shared domain collisions)
        t_spec = Ticket(
            ticket_id="TICK-PORTAL-1",
            track="ui",
            domain="portal",
            rule_id="R",
            severity="NORMAL",
            target_file="src/portal/grid.tsx",
            line_number=1,
            fingerprint="fp-portal",
            description="Portal grid polish",
            suggested_fix="Polish",
            branch_name="feat/portal-grid-polish",
            spec_path=".edge/specs/portal-grid-polish.md",
        )
        resolved_spec_slug = StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_spec)
        self.assertNotEqual(resolved_spec_slug, "portal")
        self.assertEqual(resolved_spec_slug, "portal-grid-polish")

        t_archived_spec = Ticket(
            ticket_id="TICK-PORTAL-2",
            track="ui",
            domain="portal",
            rule_id="R",
            severity="NORMAL",
            target_file="src/portal/studio.tsx",
            line_number=1,
            fingerprint="fp-studio",
            description="Content studio polish",
            suggested_fix="Polish",
            branch_name="feat/portal-polish",
            spec_path=".edge/archive/specs/content-studio-polish.md",
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_archived_spec),
            "content-studio-polish",
        )

        # Priority 3: ticket.branch_name (prefixes stripped) overrides domain when spec_path is absent
        for prefix, expected in [
            ("feat/checkout_flow", "checkout-flow"),
            ("fix/login_redirect", "login-redirect"),
            ("refactor/user_auth", "user-auth"),
            ("hotfix/crash_fix", "crash-fix"),
            ("chore/cleanup_db", "cleanup-db"),
            ("ship/alpha_slice", "alpha-slice"),
        ]:
            t_branch = Ticket(
                ticket_id="TICK-2",
                track="ui",
                domain="portal",
                rule_id="R",
                severity="NORMAL",
                target_file="",
                line_number=1,
                fingerprint="",
                description="",
                suggested_fix="",
                branch_name=prefix,
                spec_path=None,
            )
            self.assertEqual(
                StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_branch),
                expected,
            )

        # Priority 4: non-generic ticket.domain when spec_path and branch_name are absent
        t_domain = Ticket(
            ticket_id="TICK-1",
            track="ui",
            domain="User_Profile",
            rule_id="R",
            severity="NORMAL",
            target_file="src/profile/view.tsx",
            line_number=1,
            fingerprint="",
            description="",
            suggested_fix="",
            branch_name="",
            spec_path=None,
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_domain),
            "user-profile",
        )

        # Priority 5: Generic domains ('core', 'general', 'ui', 'feature') are skipped -> target_file stem
        t_generic_core = Ticket(
            ticket_id="TICK-CORE-1",
            track="core",
            domain="core",
            rule_id="R",
            severity="NORMAL",
            target_file="tools/brigade/ship_prep.py",
            line_number=1,
            fingerprint="",
            description="",
            suggested_fix="",
            branch_name="",
            spec_path=None,
        )
        resolved_core = StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_generic_core)
        self.assertNotEqual(resolved_core, "core")
        self.assertEqual(resolved_core, "ship-prep")

        for generic_dom in ("general", "ui", "feature"):
            t_gen = Ticket(
                ticket_id="TICK-GEN",
                track="ui",
                domain=generic_dom,
                rule_id="R",
                severity="NORMAL",
                target_file="src/components/booking_card.tsx",
                line_number=1,
                fingerprint="",
                description="",
                suggested_fix="",
                branch_name="",
                spec_path=None,
            )
            self.assertEqual(
                StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_gen),
                "booking-card",
            )

        # Priority 6: ticket.ticket_id (lowercased, '_' replaced with '-')
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
            spec_path=None,
        )
        self.assertEqual(
            StationRegistry._resolve_qa_slug("qa_scenario", ticket=t_tid),
            "tick-999-payment",
        )

        # Priority 7: Fallback to 'qa_scenario'
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
            spec_path=None,
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
        self.assertTrue(hasattr(self.fsm, "guard_qa_to_review"), "BrigadeFSM must define guard_qa_to_review")
        shot_file = self.repo_path / ".edge" / "qa" / "screenshots" / "dash.png"
        shot_file.parent.mkdir(parents=True, exist_ok=True)
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\nvalid-dash-shot")
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter", "reload"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
            "host_facts_verified": True,
            "db_crosscheck": {"rows": 1},
        }
        (self.proofs_dir / "dashboard.json").write_text(json.dumps(receipt), encoding="utf-8")

        ok, msg, details = self.fsm.guard_qa_to_staging()
        self.assertTrue(ok, f"guard_qa_to_staging should pass with valid proof: {msg}")
        self.assertIn("QA verification passed", msg)
        self.assertIn("proof_details", details)
        self.assertEqual(details["proof_details"].get("slug"), "dashboard")
        self.assertEqual(details["proof_details"].get("screenshot_count"), 1)

        adv_ok, next_state, adv_msg = self.fsm.advance()
        self.assertTrue(adv_ok)
        self.assertEqual(next_state, CycleState.REVIEW)
        self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)

    def test_guard_qa_to_staging_critical_findings_priority(self):
        shot_file = self.repo_path / ".edge" / "qa" / "screenshots" / "dash.png"
        shot_file.parent.mkdir(parents=True, exist_ok=True)
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\nvalid-dash-shot")
        receipt = {
            "slug": "dashboard",
            "visited_urls": ["http://localhost:3000/dashboard"],
            "user_actions_executed": ["click button#filter", "reload"],
            "persistence_verified": True,
            "console_clean": True,
            "screenshot_paths": [".edge/qa/screenshots/dash.png"],
            "host_facts_verified": True,
            "db_crosscheck": {"rows": 1},
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
        self.assertTrue(hasattr(self.fsm, "guard_gate_to_next"), "BrigadeFSM must define guard_gate_to_next")
        self.fsm.state.current_state = CycleState.GATE
        self.fsm.guard_gate_to_next = MagicMock(return_value=(True, "Gate OK", {}))
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

        shot_file = self.worktree_path / ".edge" / "qa" / "screenshots" / "sync.png"
        shot_file.parent.mkdir(parents=True, exist_ok=True)
        shot_file.write_bytes(b"\x89PNG\r\n\x1a\nsync-shot")
        proof_dir = self.worktree_path / ".edge" / "qa" / "proofs"
        proof_dir.mkdir(parents=True, exist_ok=True)
        (proof_dir / "core.json").write_text(
            json.dumps({
                "slug": "core",
                "visited_urls": ["http://localhost:3000/sync"],
                "user_actions_executed": ["click button#sync"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/sync.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"sync": 1},
            }),
            encoding="utf-8",
        )

        # Mock proof receipt validator to pass
        with patch("tools.brigade.fsm._validate_qa_proof_receipt", return_value=(True, "Valid receipt", {"slug": "core"})):
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
        """Scenario 1: Polish transitions to GATE and clears prior review findings and examiner receipt."""
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

        self.fsm.state.current_state = CycleState.POLISH
        self.fsm.state.examiner_receipt = ExaminerReceipt(verdict="FAIL", summary="Needs fix")
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
            self.assertEqual(next_state, CycleState.GATE, "POLISH must transition to GATE for gate/QA re-verification before REVIEW")
            self.assertEqual(self.fsm.state.current_state, CycleState.GATE)
            self.assertEqual(self.fsm.state.review_findings, [], "Remediated review findings must be cleared")
            self.assertIsNone(self.fsm.state.examiner_receipt, "Prior ExaminerReceipt must be cleared after POLISH")

    def test_review_blocked_by_hermetic_verification_failure(self):
        """Scenario 2: REVIEW to STAGING blocked when hermetic verification fails (routes to POLISH)."""
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.examiner_receipt = ExaminerReceipt(verdict="PASS", summary="Review PASS")
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
        """Scenario 2b: REVIEW advances to STAGING when 0 critical findings, PASS seal, AND verification passes."""
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.examiner_receipt = ExaminerReceipt(verdict="PASS", summary="Verified 3-axis review")
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
            self.assertEqual(next_state, CycleState.STAGING)

            adv_success, adv_state, adv_msg = self.fsm.advance()
            self.assertTrue(adv_success)
            self.assertEqual(adv_state, CycleState.STAGING)
            self.assertEqual(self.fsm.state.current_state, CycleState.STAGING)

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


class TestEvidenceFirstReviewAndShipBridge(unittest.TestCase):
    """
    RED/Contract tests for SPEC-EDGE-BRIGADE-003 (IC-1 .. IC-5):
    - IC-1: FSM Order Inversion (VERIFY -> GATE -> [QA] -> REVIEW -> STAGING, POLISH -> GATE)
    - IC-2: Deterministic ProofVerifier (disk existence, non-zero size, SHA-256 uniqueness, auth-wall trap, host_facts_verified, db_crosscheck)
    - IC-3: UI Refactor diff_image.py Pixel Parity Gate (<= 0.15%)
    - IC-4: Examiner Axis 3 ('evidence'), ExaminerReceipt & brigade seal-review CLI
    - IC-5: tools.brigade.ship_prep & brigade prepare-ship CLI
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.repo_path = Path(self.test_dir)
        self.repo_root = Path(__file__).resolve().parents[1]
        self.fsm = BrigadeFSM(self.repo_path)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @staticmethod
    def _make_solid_png(width: int, height: int, rgb: tuple) -> bytes:
        """Creates a valid minimal RGB PNG using Python stdlib only."""
        def chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack("!I", len(data))
                + tag
                + data
                + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        r, g, b = rgb
        row = b"\x00" + bytes([r, g, b]) * width
        raw = row * height
        ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    def _make_ticket(self, **overrides) -> Ticket:
        defaults = dict(
            ticket_id="TICK-FEAT-BRIDGE",
            track="feature",
            domain="bookings",
            rule_id="RULE-FEAT",
            severity="NORMAL",
            target_file="src/bookings/service.ts",
            line_number=1,
            fingerprint="fp-bridge",
            description="Booking workflow slice",
            suggested_fix="Implement slice",
            branch_name="feat/bookings-flow",
            test_seam_command="npm run test:unit",
        )
        defaults.update(overrides)
        return Ticket(**defaults)

    # ------------------------------------------------------------------
    # IC-1: FSM Order Inversion (VERIFY -> GATE -> [QA] -> REVIEW -> STAGING & POLISH -> GATE)
    # ------------------------------------------------------------------

    def test_ic1_fsm_verify_to_gate_and_gate_to_qa_or_review(self):
        self.assertTrue(hasattr(self.fsm, "guard_verify_to_gate"), "BrigadeFSM must define guard_verify_to_gate")
        self.assertTrue(hasattr(self.fsm, "guard_gate_to_next"), "BrigadeFSM must define guard_gate_to_next")

        ticket = self._make_ticket(require_qa=True)
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.VERIFY

        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(True, "Tests & tsc clean")):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok, f"VERIFY should advance to GATE: {msg}")
            self.assertEqual(next_state, CycleState.GATE)
            self.assertEqual(self.fsm.state.current_state, CycleState.GATE)

        # GATE -> QA when should_run_qa() is True
        with (
            patch.object(self.fsm, "guard_gate_to_next", return_value=(True, "Gate OK", {})),
            patch.object(self.fsm, "_run_qa_db_drift_preflight", return_value=(True, "No drift")),
        ):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok, f"GATE with require_qa=True should advance to QA: {msg}")
            self.assertEqual(next_state, CycleState.QA)
            self.assertEqual(self.fsm.state.current_state, CycleState.QA)

        # GATE -> REVIEW when should_run_qa() is False
        ticket.require_qa = False
        self.fsm.state.current_state = CycleState.GATE
        with patch.object(self.fsm, "guard_gate_to_next", return_value=(True, "Gate OK", {})):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok, f"GATE with require_qa=False should advance to REVIEW: {msg}")
            self.assertEqual(next_state, CycleState.REVIEW)
            self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)

    def test_ic1_qa_to_review_or_polish(self):
        self.assertTrue(hasattr(self.fsm, "guard_qa_to_review"), "BrigadeFSM must define guard_qa_to_review")

        ticket = self._make_ticket(domain="orders", branch_name="feat/orders")
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.QA

        shot_path = self.repo_path / ".edge" / "qa" / "screenshots" / "orders.png"
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        shot_path.write_bytes(self._make_solid_png(4, 4, (10, 20, 30)))

        proof_path = self.repo_path / ".edge" / "qa" / "proofs" / "orders.json"
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(
            json.dumps({
                "slug": "orders",
                "visited_urls": ["http://localhost:3000/orders"],
                "user_actions_executed": ["submit order form"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/orders.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"orders": 1},
            }),
            encoding="utf-8",
        )

        with patch.object(self.fsm, "_run_qa_db_drift_preflight", return_value=(True, "No drift")):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok, f"QA should advance to REVIEW with valid proof: {msg}")
            self.assertEqual(next_state, CycleState.REVIEW)
            self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)

        # CRITICAL finding in QA routes to POLISH
        self.fsm.state.current_state = CycleState.QA
        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="qa",
                severity="CRITICAL",
                file_path="src/orders/page.tsx",
                rule="TIER1-CONSOLE-ERROR",
                description="Uncaught TypeError",
                suggested_fix="Guard null order",
            )
        ]
        ok, next_state, msg = self.fsm.advance()
        self.assertFalse(ok)
        self.assertEqual(next_state, CycleState.POLISH)
        self.assertEqual(self.fsm.state.current_state, CycleState.POLISH)

    def test_ic1_review_requires_examiner_receipt_and_routes_pass_fail(self):
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

        ticket = self._make_ticket(ticket_id="TICK-REV-SEAL")
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.review_findings = []
        self.fsm.state.examiner_receipt = None

        # 1. Missing ExaminerReceipt -> MUST reject advancement and stay in REVIEW
        ok, state, msg = self.fsm.advance()
        self.assertFalse(ok, "REVIEW without ExaminerReceipt must NOT advance")
        self.assertEqual(state, CycleState.REVIEW)
        self.assertEqual(self.fsm.state.current_state, CycleState.REVIEW)
        self.assertIn("seal-review", msg)

        # 2. Stale ticket_id receipt -> blocked in REVIEW
        self.fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="PASS",
            summary="Old ticket receipt",
            ticket_id="TICK-OTHER",
        )
        ok, state, msg = self.fsm.advance()
        self.assertFalse(ok, "Stale ExaminerReceipt for another ticket must block in REVIEW")
        self.assertEqual(state, CycleState.REVIEW)

        # 3. Sealed FAIL verdict -> routes to POLISH
        self.fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="FAIL",
            summary="Missing error boundary in evidence review",
            ticket_id=ticket.ticket_id,
        )
        ok, state, msg = self.fsm.advance()
        self.assertTrue(ok)
        self.assertEqual(state, CycleState.POLISH)
        self.assertEqual(self.fsm.state.current_state, CycleState.POLISH)

        # 4. Sealed PASS verdict + 0 CRITICAL + hermetic pass -> transitions to STAGING
        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="PASS",
            summary="All 3 axes verified",
            ticket_id=ticket.ticket_id,
            evidence_reviewed=[".edge/qa/proofs/bookings.json"],
        )
        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(True, "Clean")):
            ok, state, msg = self.fsm.advance()
            self.assertTrue(ok, f"REVIEW with PASS seal should advance to STAGING: {msg}")
            self.assertEqual(state, CycleState.STAGING)
            self.assertEqual(self.fsm.state.current_state, CycleState.STAGING)

    def test_ic1_polish_clears_findings_and_receipt_and_returns_to_gate(self):
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(self.fsm.state, "examiner_receipt"), "BrigadeState must have examiner_receipt")

        ticket = self._make_ticket()
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.POLISH
        self.fsm.state.review_findings = [
            ReviewFinding(
                axis="evidence",
                severity="CRITICAL",
                file_path="src/bookings/service.ts",
                rule="EVIDENCE-GAP",
                description="Stubbed response",
                suggested_fix="Persist to DB",
            )
        ]
        self.fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="FAIL",
            summary="Failed evidence check",
            ticket_id=ticket.ticket_id,
        )

        with patch.object(self.fsm, "_run_hermetic_verification", return_value=(True, "Clean")):
            ok, next_state, msg = self.fsm.advance()
            self.assertTrue(ok, f"POLISH should advance to GATE: {msg}")
            self.assertEqual(next_state, CycleState.GATE)
            self.assertEqual(self.fsm.state.current_state, CycleState.GATE)
            self.assertEqual(self.fsm.state.review_findings, [])
            self.assertIsNone(self.fsm.state.examiner_receipt)

    # ------------------------------------------------------------------
    # IC-2: Deterministic ProofVerifier
    # ------------------------------------------------------------------

    def test_ic2_proof_verifier_missing_and_empty_screenshot(self):
        ProofVerifier = getattr(brigade_fsm, "ProofVerifier", None)
        self.assertIsNotNone(ProofVerifier, "ProofVerifier must exist in tools.brigade.fsm")

        proof_path = self.repo_path / ".edge" / "qa" / "proofs" / "bookings.json"
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        ticket = self._make_ticket()

        # 1. Missing screenshot file
        proof_path.write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["click#create"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/missing.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )
        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=ticket)
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "MISSING_SCREENSHOT_FILE")

        # 2. Zero-byte screenshot file
        empty_shot = self.repo_path / ".edge" / "qa" / "screenshots" / "empty.png"
        empty_shot.parent.mkdir(parents=True, exist_ok=True)
        empty_shot.write_bytes(b"")
        proof_path.write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["click#create"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/empty.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )
        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=ticket)
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "EMPTY_SCREENSHOT_FILE")

    def test_ic2_proof_verifier_duplicate_screenshot_sha256(self):
        ProofVerifier = getattr(brigade_fsm, "ProofVerifier", None)
        self.assertIsNotNone(ProofVerifier, "ProofVerifier must exist in tools.brigade.fsm")

        shots_dir = self.repo_path / ".edge" / "qa" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        same_bytes = self._make_solid_png(4, 4, (50, 100, 150))
        (shots_dir / "before.png").write_bytes(same_bytes)
        (shots_dir / "after.png").write_bytes(same_bytes)

        proof_path = self.repo_path / ".edge" / "qa" / "proofs" / "bookings.json"
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["click#create", "reload"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [
                    ".edge/qa/screenshots/before.png",
                    ".edge/qa/screenshots/after.png",
                ],
                "host_facts_verified": True,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )

        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=self._make_ticket())
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "DUPLICATE_SCREENSHOT_EVIDENCE")

    def test_ic2_proof_verifier_auth_wall_redirect_trap(self):
        ProofVerifier = getattr(brigade_fsm, "ProofVerifier", None)
        self.assertIsNotNone(ProofVerifier, "ProofVerifier must exist in tools.brigade.fsm")

        shots_dir = self.repo_path / ".edge" / "qa" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / "s1.png").write_bytes(self._make_solid_png(4, 4, (10, 10, 10)))

        proof_path = self.repo_path / ".edge" / "qa" / "proofs" / "bookings.json"
        proof_path.parent.mkdir(parents=True, exist_ok=True)

        # Non-auth ticket trapped at /login?redirect=...
        non_auth_ticket = self._make_ticket(
            ticket_id="TICK-BOOK-1",
            domain="bookings",
            branch_name="feat/bookings-create",
            description="Create a booking",
        )
        for bad_url in [
            "http://localhost:3000/login?redirect=/bookings",
            "http://localhost:3000/signin",
        ]:
            proof_path.write_text(
                json.dumps({
                    "slug": "bookings",
                    "visited_urls": [bad_url],
                    "user_actions_executed": ["open /bookings"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/s1.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"bookings": 1},
                }),
                encoding="utf-8",
            )
            ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=non_auth_ticket)
            self.assertFalse(ok, f"Auth wall URL {bad_url} must be rejected on non-auth ticket")
            self.assertEqual(details.get("error"), "AUTH_WALL_REDIRECT_TRAP")

        # Auth ticket IS allowed to visit /login
        auth_ticket = self._make_ticket(
            ticket_id="TICK-AUTH-1",
            domain="auth",
            branch_name="feat/login",
            description="User login flow",
        )
        proof_path.write_text(
            json.dumps({
                "slug": "auth",
                "visited_urls": ["http://localhost:3000/login"],
                "user_actions_executed": ["submit credentials"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/s1.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"sessions": 1},
            }),
            encoding="utf-8",
        )
        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=auth_ticket)
        self.assertTrue(ok, f"Auth ticket should be permitted to visit /login: {msg}")

    def test_ic2_proof_verifier_host_facts_and_db_crosscheck_and_valid_pass(self):
        ProofVerifier = getattr(brigade_fsm, "ProofVerifier", None)
        self.assertIsNotNone(ProofVerifier, "ProofVerifier must exist in tools.brigade.fsm")

        shots_dir = self.repo_path / ".edge" / "qa" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / "pre.png").write_bytes(self._make_solid_png(4, 4, (1, 2, 3)))
        (shots_dir / "post.png").write_bytes(self._make_solid_png(4, 4, (200, 210, 220)))

        proof_path = self.repo_path / ".edge" / "qa" / "proofs" / "bookings.json"
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        ticket = self._make_ticket()

        # 1. host_facts_verified=False -> HOST_FACTS_NOT_VERIFIED
        proof_path.write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["create booking"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/pre.png"],
                "host_facts_verified": False,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )
        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=ticket)
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "HOST_FACTS_NOT_VERIFIED")

        # 2. db_crosscheck={} -> MISSING_DB_CROSSCHECK
        proof_path.write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["create booking"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/pre.png"],
                "host_facts_verified": True,
                "db_crosscheck": {},
            }),
            encoding="utf-8",
        )
        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=ticket)
        self.assertFalse(ok)
        self.assertEqual(details.get("error"), "MISSING_DB_CROSSCHECK")

        # 3. Full valid receipt with 2 unique-hash screenshots
        proof_path.write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["create booking", "reload"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [
                    ".edge/qa/screenshots/pre.png",
                    ".edge/qa/screenshots/post.png",
                ],
                "host_facts_verified": True,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )
        ok, msg, details = ProofVerifier.verify_receipt(proof_path, [self.repo_path], ticket=ticket)
        self.assertTrue(ok, f"Valid ProofVerifier receipt should pass: {msg}")
        hashes = details.get("screenshot_hashes", {})
        self.assertEqual(len(hashes), 2)
        self.assertEqual(len(set(hashes.values())), 2)

    # ------------------------------------------------------------------
    # IC-3: UI Refactor diff_image.py Pixel Parity Gate
    # ------------------------------------------------------------------

    def test_ic3_ui_track_gate_blocks_missing_visual_parity_images(self):
        self.assertTrue(hasattr(self.fsm, "guard_gate_to_next"), "BrigadeFSM must define guard_gate_to_next")
        self.assertTrue(hasattr(self.fsm, "_check_ui_visual_parity"), "BrigadeFSM must define _check_ui_visual_parity")

        ticket = self._make_ticket(track="ui", domain="checkout", branch_name="refactor/ui-checkout")
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.GATE

        with patch.object(self.fsm, "_run_cmd", return_value=(0, "Gate passed", "")):
            ok, msg, details = self.fsm.guard_gate_to_next()
            self.assertFalse(ok)
            self.assertEqual(details.get("error"), "MISSING_VISUAL_PARITY_IMAGES")

    def test_ic3_ui_track_gate_diff_image_mismatch_fail_and_pass(self):
        self.assertTrue(hasattr(self.fsm, "guard_gate_to_next"), "BrigadeFSM must define guard_gate_to_next")
        self.assertTrue(hasattr(self.fsm, "_check_ui_visual_parity"), "BrigadeFSM must define _check_ui_visual_parity")

        from tools.common import run_command as real_run_command

        ticket = self._make_ticket(track="ui", domain="checkout", branch_name="refactor/checkout")
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.GATE

        visual_dir = self.repo_path / ".edge" / "qa" / "visual"
        visual_dir.mkdir(parents=True, exist_ok=True)
        baseline = visual_dir / "checkout-baseline.png"
        refactored = visual_dir / "checkout-refactored.png"

        def run_cmd_side_effect(cmd, cwd=None):
            cmd_str = " ".join(str(x) for x in cmd)
            if "gate.py" in cmd_str:
                return (0, "Gate passed", "")
            return real_run_command(cmd, cwd=cwd or self.repo_root)

        # 1. Mismatch > 0.15% (black vs white 10x10 PNG -> 100% mismatch) -> VISUAL_PARITY_FAILED
        baseline.write_bytes(self._make_solid_png(10, 10, (0, 0, 0)))
        refactored.write_bytes(self._make_solid_png(10, 10, (255, 255, 255)))
        with patch.object(self.fsm, "_run_cmd", side_effect=run_cmd_side_effect):
            ok, msg, details = self.fsm.guard_gate_to_next()
            self.assertFalse(ok, "Mismatched UI screenshots (> 0.15%) must fail GATE")
            self.assertEqual(details.get("error"), "VISUAL_PARITY_FAILED")

        # 2. Identical images (0.0% <= 0.15%) -> GATE passes
        identical = self._make_solid_png(10, 10, (120, 140, 160))
        baseline.write_bytes(identical)
        refactored.write_bytes(identical)
        with patch.object(self.fsm, "_run_cmd", side_effect=run_cmd_side_effect):
            ok, msg, details = self.fsm.guard_gate_to_next()
            self.assertTrue(ok, f"Identical UI screenshots (<= 0.15%) must pass GATE: {msg}")

    # ------------------------------------------------------------------
    # IC-4: Examiner Axis 3 ('evidence') & brigade seal-review CLI
    # ------------------------------------------------------------------

    def test_ic4_examiner_axis_evidence_seal_review_cli_and_prompt(self):
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")
        self.assertTrue(hasattr(brigade_cli, "cmd_seal_review"), "tools.brigade.cli must define cmd_seal_review")

        ticket = self._make_ticket(ticket_id="TICK-IC4-EXAM")
        self.fsm.state.active_ticket = ticket
        self.fsm.state.current_state = CycleState.REVIEW
        self.fsm.save()

        # 1. ReviewFinding supports axis="evidence" and CLI add-finding --axis evidence works
        rf = ReviewFinding(
            axis="evidence",
            severity="WARNING",
            file_path=".edge/qa/proofs/test.json",
            rule="EVIDENCE-AUDIT",
            description="Minor missing assertion",
            suggested_fix="Add reload assertion",
        )
        self.assertEqual(rf.axis, "evidence")

        try:
            with patch.object(
                sys,
                "argv",
                [
                    "brigade",
                    "add-finding",
                    str(self.repo_path),
                    "--axis",
                    "evidence",
                    "--severity",
                    "WARNING",
                    "--file",
                    ".edge/qa/proofs/test.json",
                    "--rule",
                    "EVIDENCE-AUDIT",
                    "--desc",
                    "Minor missing assertion",
                ],
            ):
                ret_find = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'add-finding --axis evidence' exited abnormally: {exc}")
        self.assertEqual(ret_find, 0)

        # 2. CLI seal-review saves ExaminerReceipt to BrigadeState
        try:
            with patch.object(
                sys,
                "argv",
                [
                    "brigade",
                    "seal-review",
                    str(self.repo_path),
                    "--verdict",
                    "PASS",
                    "--summary",
                    "Verified code and proofs",
                    "--evidence-reviewed",
                    ".edge/qa/proofs/test.json,.edge/qa/visual/diff.png",
                ],
            ):
                ret_seal = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'seal-review' exited abnormally: {exc}")
        self.assertEqual(ret_seal, 0)

        reloaded = BrigadeFSM(self.repo_path)
        self.assertIsNotNone(reloaded.state.examiner_receipt)
        self.assertEqual(reloaded.state.examiner_receipt.verdict, "PASS")
        self.assertEqual(reloaded.state.examiner_receipt.summary, "Verified code and proofs")
        self.assertEqual(reloaded.state.examiner_receipt.ticket_id, "TICK-IC4-EXAM")
        self.assertEqual(
            reloaded.state.examiner_receipt.evidence_reviewed,
            [".edge/qa/proofs/test.json", ".edge/qa/visual/diff.png"],
        )

        # Legacy BrigadeState.from_dict without examiner_receipt defaults to None
        legacy_dict = reloaded.state.to_dict()
        legacy_dict.pop("examiner_receipt", None)
        restored_legacy = BrigadeState.from_dict(legacy_dict)
        self.assertIsNone(restored_legacy.examiner_receipt)

        # 3. build_examiner_prompt includes Axis 3 / evidence and seal-review
        prompt = StationRegistry.build_examiner_prompt(ticket, "development")
        self.assertIn("axis 3", prompt.lower())
        self.assertIn("evidence", prompt.lower())
        self.assertIn("seal-review", prompt)

        # 4. agents/examiner.md stays <= 60 lines and documents Axis 3 & seal-review
        examiner_md = self.repo_root / "agents" / "examiner.md"
        ex_text = examiner_md.read_text(encoding="utf-8")
        self.assertLessEqual(len(ex_text.splitlines()), 60)
        self.assertIn("Axis 3", ex_text)
        self.assertIn("seal-review", ex_text)

    # ------------------------------------------------------------------
    # IC-5: tools.brigade.ship_prep & brigade prepare-ship CLI
    # ------------------------------------------------------------------

    def test_ic5_parse_index_diff_and_classify_merge_danger(self):
        spec = importlib.util.find_spec("tools.brigade.ship_prep")
        self.assertIsNotNone(spec, "tools.brigade.ship_prep module must exist")
        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        sample_diff = "\n".join([
            "diff --git a/specs/INDEX.md b/specs/INDEX.md",
            "--- a/specs/INDEX.md",
            "+++ b/specs/INDEX.md",
            "@@ -1,2 +1,8 @@",
            "+- @route /bookings | Page: BookingsPage | Create and list bookings",
            "+- @module bookings | Action: createBookingAction | Schema: bookings",
            "+- @spec .edge/archive/specs/bookings-flow.md",
        ])
        changes = ship_prep.parse_index_diff(sample_diff)
        self.assertTrue(len(changes) >= 5, f"Expected structured index tokens parsed, got: {changes}")
        kinds = {c.kind for c in changes}
        for expected_kind in ("@route", "Page", "@module", "Action", "Schema", "@spec"):
            self.assertIn(expected_kind, kinds, f"Missing parsed token kind {expected_kind} in {changes}")

        door_sql, blast_sql = ship_prep.classify_merge_danger(
            ["drizzle/0001_init.sql", "src/actions/bookings.ts"],
            diff_stat="2 files changed, 20 insertions(+)",
        )
        self.assertTrue(door_sql.startswith("One-way door"), f"Expected One-way door for drizzle SQL, got: {door_sql}")
        self.assertIsInstance(blast_sql, dict)

        door_schema, _ = ship_prep.classify_merge_danger(["src/db/schema/users.ts"])
        self.assertTrue(door_schema.startswith("One-way door"), f"Expected One-way door for src/db/schema, got: {door_schema}")

        door_two_way, _ = ship_prep.classify_merge_danger(["src/lib/bookings/service.ts", "tests/bookings.test.ts"])
        self.assertTrue(door_two_way.startswith("Two-way door"), f"Expected Two-way door, got: {door_two_way}")

    def test_ic5_prepare_ship_payload_and_cli_prepare_ship(self):
        spec = importlib.util.find_spec("tools.brigade.ship_prep")
        self.assertIsNotNone(spec, "tools.brigade.ship_prep module must exist")
        self.assertTrue(hasattr(brigade_cli, "cmd_prepare_ship"), "tools.brigade.cli must define cmd_prepare_ship")
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt, "ExaminerReceipt must exist in tools.brigade.models")

        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        def git(*git_args):
            proc = subprocess.run(
                ["git", *git_args],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return proc.stdout.strip()

        git("init", "-b", "development")
        git("config", "user.email", "brigade@example.com")
        git("config", "user.name", "Edge Brigade")

        (self.repo_path / "specs").mkdir(parents=True, exist_ok=True)
        (self.repo_path / "specs" / "INDEX.md").write_text("# Navigation Index\n", encoding="utf-8")
        (self.repo_path / "CONTEXT.md").write_text("# Context\n- **Booking**: Customer reservation.\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "chore: base development")

        git("checkout", "-b", "feat/bookings-flow")
        (self.repo_path / "specs" / "INDEX.md").write_text(
            "# Navigation Index\n"
            "- @route /bookings | Page: BookingsPage | Booking flow\n"
            "- @module bookings | Action: createBooking | Schema: bookings\n"
            "- @spec .edge/archive/specs/bookings-flow.md\n",
            encoding="utf-8",
        )
        arch_dir = self.repo_path / ".edge" / "archive" / "specs"
        arch_dir.mkdir(parents=True, exist_ok=True)
        (arch_dir / "bookings-flow.md").write_text("# Bookings Flow Spec\nCreate and persist bookings.\n", encoding="utf-8")

        shots_dir = self.repo_path / ".edge" / "qa" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / "bookings-1.png").write_bytes(self._make_solid_png(4, 4, (30, 60, 90)))
        (shots_dir / "bookings-2.png").write_bytes(self._make_solid_png(4, 4, (90, 120, 150)))

        proofs_dir = self.repo_path / ".edge" / "qa" / "proofs"
        proofs_dir.mkdir(parents=True, exist_ok=True)
        (proofs_dir / "bookings.json").write_text(
            json.dumps({
                "slug": "bookings",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["create booking", "reload"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [
                    ".edge/qa/screenshots/bookings-1.png",
                    ".edge/qa/screenshots/bookings-2.png",
                ],
                "host_facts_verified": True,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )

        fsm_local = BrigadeFSM(self.repo_path)
        fsm_local.state.examiner_receipt = ExaminerReceipt(
            verdict="PASS",
            summary="Verified code and QA proofs",
            ticket_id="TICK-FEAT-BOOKINGS",
            evidence_reviewed=[".edge/qa/proofs/bookings.json"],
        )
        fsm_local.save()

        (self.repo_path / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo_path / "src" / "bookings" / "service.ts").write_text("export const createBooking = () => true;\n", encoding="utf-8")

        git("add", "-A")
        git("commit", "-m", "feat(bookings): implement booking flow")

        ok, result, err = ship_prep.prepare_ship_payload(self.repo_path, base_branch="development")
        self.assertTrue(ok, f"prepare_ship_payload should succeed: {err}")
        self.assertTrue(result.intent.strip())
        self.assertNotIn("\n", result.intent.strip())
        self.assertTrue(len(result.scenario_contract) > 0)

        pr_text = ship_prep.format_ship_output(result, fmt="pr")
        self.assertIn("## Summary", pr_text)
        self.assertIn("## Evidence", pr_text)
        self.assertNotIn("## Merge Danger", pr_text)
        self.assertNotIn("One-way door", pr_text)
        self.assertNotIn("Two-way door", pr_text)

        show_me_text = ship_prep.format_ship_output(result, fmt="show-me")
        self.assertIn("## Summary", show_me_text)
        self.assertIn("## Evidence", show_me_text)
        self.assertNotIn("## Merge Danger", show_me_text)
        self.assertNotIn("One-way door", show_me_text)
        self.assertNotIn("Two-way door", show_me_text)

        # CLI prepare-ship --format json --out <path>
        out_file = self.repo_path / ".edge" / "ship-payload.json"
        try:
            with patch.object(
                sys,
                "argv",
                [
                    "brigade",
                    "prepare-ship",
                    str(self.repo_path),
                    "--base",
                    "development",
                    "--format",
                    "json",
                    "--out",
                    str(out_file),
                ],
            ):
                ret_ship = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'prepare-ship' exited abnormally: {exc}")
        self.assertEqual(ret_ship, 0)
        self.assertTrue(out_file.is_file())
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        for key in ("intent", "scenario_contract", "pr_body", "door_type", "blast_radius", "verified_proofs", "failed_proofs"):
            self.assertIn(key, payload)

        # Broken QA proof receipt changed in development..HEAD -> prepare-ship fails (exit 1)
        (proofs_dir / "broken.json").write_text(
            json.dumps({
                "slug": "broken",
                "visited_urls": ["http://localhost:3000/bookings"],
                "user_actions_executed": ["click"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/nonexistent.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"bookings": 1},
            }),
            encoding="utf-8",
        )
        git("add", ".edge/qa/proofs/broken.json")
        git("commit", "-m", "test: add broken scoped proof")
        ok_bad, res_bad, _ = ship_prep.prepare_ship_payload(self.repo_path, base_branch="development")
        self.assertFalse(ok_bad, "Broken QA proof must fail prepare_ship_payload")
        self.assertTrue(len(res_bad.failed_proofs) >= 1)

        try:
            with patch.object(
                sys,
                "argv",
                ["brigade", "prepare-ship", str(self.repo_path), "--base", "development"],
            ):
                ret_bad = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'prepare-ship' should return 1 cleanly instead of raising SystemExit: {exc}")
        self.assertEqual(ret_bad, 1)

    # ------------------------------------------------------------------
    # Spec-Anchored PR & Multi-Spec Ship Bridge (4-Pillar Hardening)
    # ------------------------------------------------------------------

    def test_ship_prep_excludes_critique_files_and_aggregates_multiple_specs_with_mermaid(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        self.assertTrue(
            hasattr(ship_prep, "parse_spec_document"),
            "tools.brigade.ship_prep must export parse_spec_document",
        )

        repo_dir = Path(tempfile.mkdtemp(dir=self.test_dir))

        def git(*git_args):
            proc = subprocess.run(
                ["git", *git_args],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return proc.stdout.strip()

        git("init", "-b", "staging")
        git("config", "user.email", "brigade@example.com")
        git("config", "user.name", "Edge Brigade")

        (repo_dir / "README.md").write_text("# Base Repo\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "chore: initial staging")

        git("checkout", "-b", "development")

        arch_dir = repo_dir / ".edge" / "archive" / "specs"
        arch_dir.mkdir(parents=True, exist_ok=True)
        specs_dir = repo_dir / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)

        (arch_dir / "slice-alpha.md").write_text(
            "# Alpha Booking Flow\n\n"
            "Summary: Enables multi-step customer appointment booking with slot reservation.\n\n"
            "```mermaid\n"
            "stateDiagram-v2\n"
            "    Idle --> Booked\n"
            "```\n\n"
            "| ID | Scenario | Expected |\n"
            "| :--- | :--- | :--- |\n"
            "| SC-1 | Reserve slot | State transitions Idle -> Booked |\n",
            encoding="utf-8",
        )

        (arch_dir / "slice-beta.md").write_text(
            "# Beta Payment Refund\n\n"
            "Summary: Processes automated refund reversal on cancelled bookings.\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "    Paid --> Refunded\n"
            "```\n",
            encoding="utf-8",
        )

        # Critique artifact that MUST NEVER be linked as a spec
        (specs_dir / "slice-alpha-critique.md").write_text(
            "# Spec Critique: slice-alpha.md\n\n- **Model:** claude-opus-5-5-high\n\n## 1. Paraphrase Check\nAdvisory critique.\n",
            encoding="utf-8",
        )

        (repo_dir / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (repo_dir / "src" / "bookings" / "alpha.ts").write_text("export const alpha = true;\n", encoding="utf-8")
        (repo_dir / "src" / "payments").mkdir(parents=True, exist_ok=True)
        (repo_dir / "src" / "payments" / "beta.ts").write_text("export const beta = true;\n", encoding="utf-8")

        git("add", "-A")
        git("commit", "-m", "feat: deliver slice-alpha and slice-beta on development")

        ok, result, err = ship_prep.prepare_ship_payload(repo_dir, base_branch="staging")
        self.assertTrue(ok, f"prepare_ship_payload should succeed: {err}")

        # 1. Critique file must NEVER appear in specs_linked, pr_body, or intent
        self.assertTrue(
            all("critique" not in s.lower() for s in result.specs_linked),
            f"Critique files must be excluded from specs_linked: {result.specs_linked}",
        )
        self.assertNotIn("slice-alpha-critique.md", result.pr_body)
        self.assertNotIn("slice-alpha-critique.md", result.intent)

        # 2. Both archived specs must be discovered even when branch is 'development'
        self.assertIn(".edge/archive/specs/slice-alpha.md", result.specs_linked)
        self.assertIn(".edge/archive/specs/slice-beta.md", result.specs_linked)
        self.assertTrue(
            hasattr(result, "spec_digests"),
            "ShipPrepResult must include spec_digests field",
        )
        digest_paths = [
            (d.path if hasattr(d, "path") else d.get("path", ""))
            for d in result.spec_digests
        ]
        self.assertIn(".edge/archive/specs/slice-alpha.md", digest_paths)
        self.assertIn(".edge/archive/specs/slice-beta.md", digest_paths)

        # 3. Intent must include BOTH specs so multi-slice milestones never drop scopes
        intent_low = result.intent.lower()
        self.assertTrue(
            "alpha booking flow" in intent_low or "slice-alpha" in intent_low,
            f"Intent missing alpha spec scope: {result.intent}",
        )
        self.assertTrue(
            "beta payment refund" in intent_low or "slice-beta" in intent_low,
            f"Intent missing beta spec scope: {result.intent}",
        )

        # 4. PR body embeds Mermaid blocks and spec titles directly
        self.assertIn("Alpha Booking Flow", result.pr_body)
        self.assertIn("Beta Payment Refund", result.pr_body)
        self.assertIn("stateDiagram-v2", result.pr_body)
        self.assertIn("Idle --> Booked", result.pr_body)
        self.assertIn("flowchart LR", result.pr_body)
        self.assertIn("Paid --> Refunded", result.pr_body)

    def test_finish_slice_pr_mode_auto_merges_two_way_door_and_holds_one_way_door(self):
        import inspect

        sig = inspect.signature(self.fsm.finish_slice)
        self.assertIn("open_pr", sig.parameters, "BrigadeFSM.finish_slice must accept open_pr: bool = False")
        self.assertIn(
            "auto_merge_two_way",
            sig.parameters,
            "BrigadeFSM.finish_slice must accept auto_merge_two_way: bool = True",
        )
        self.assertIs(sig.parameters["open_pr"].default, False)
        self.assertIs(sig.parameters["auto_merge_two_way"].default, True)

        # Verify CLI finish-slice parser accepts --pr and --no-auto-merge
        with patch.object(
            BrigadeFSM,
            "finish_slice",
            return_value=(True, "PR merged"),
        ) as mock_finish:
            with patch.object(
                sys,
                "argv",
                ["brigade", "finish-slice", str(self.repo_path), "--pr", "--no-auto-merge"],
            ):
                rc = brigade_cli.main()
            self.assertEqual(rc, 0)
            mock_finish.assert_called_once_with(open_pr=True, auto_merge_two_way=False)

        # Set up git marker and spec for PR body synthesis
        (self.repo_path / ".git").mkdir(parents=True, exist_ok=True)
        specs_dir = self.repo_path / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        (specs_dir / "button-ui.md").write_text(
            "# Button UI Slice\n\n```mermaid\nflowchart LR\n    Click --> Submit\n```\n",
            encoding="utf-8",
        )

        # --- Case A: Two-Way Door (src/components/Button.tsx) -> PR opened + auto-merged via gh pr merge ---
        ticket_two_way = self._make_ticket(
            ticket_id="TICK-FEAT-BUTTON-UI",
            domain="ui",
            target_file="src/components/Button.tsx",
            branch_name="feat/button-ui",
            spec_path=".edge/specs/button-ui.md",
        )
        self.fsm.state.base_branch = "development"
        self.fsm.state.active_ticket = ticket_two_way
        self.fsm.state.active_branch = "feat/button-ui"
        self.fsm.state.current_state = CycleState.STAGING

        two_way_cmds: List[List[str]] = []

        def run_cmd_two_way(cmd, cwd=None, timeout=120):
            cmd_list = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else str(cmd).split()
            two_way_cmds.append(cmd_list)
            joined = " ".join(cmd_list)
            if "status" in cmd_list and "--porcelain" in cmd_list:
                return (0, "", "")
            if "branch" in cmd_list and "--show-current" in cmd_list:
                return (0, "development\n", "")
            if "rev-parse" in cmd_list and "--verify" in cmd_list:
                return (0, "abc1234\n", "")
            if "diff" in cmd_list and "--name-only" in cmd_list:
                return (0, "src/components/Button.tsx\n", "")
            if "diff" in cmd_list and "--stat" in cmd_list:
                return (0, "1 file changed, 10 insertions(+)\n", "")
            if "gh" in cmd_list and "pr" in cmd_list and "create" in cmd_list:
                return (0, "https://github.com/org/repo/pull/42\n", "")
            if "gh" in cmd_list and "pr" in cmd_list and "merge" in cmd_list:
                return (0, "Merged pull request #42\n", "")
            return (0, "", "")

        with (
            patch("tools.brigade.fsm.run_command", side_effect=run_cmd_two_way),
            patch("tools.brigade.ship_prep.run_command", side_effect=run_cmd_two_way),
            patch("tools.brigade.fsm.return_worktree", return_value=(True, "returned")),
        ):
            ok_a, msg_a = self.fsm.finish_slice(open_pr=True, auto_merge_two_way=True)

        self.assertTrue(ok_a, f"Two-way door finish_slice(open_pr=True) should succeed: {msg_a}")
        pr_create_calls_a = [c for c in two_way_cmds if "gh" in c and "pr" in c and "create" in c]
        pr_merge_calls_a = [c for c in two_way_cmds if "gh" in c and "pr" in c and "merge" in c]
        self.assertTrue(pr_create_calls_a, f"Expected gh pr create call for Two-Way Door, got: {two_way_cmds}")
        self.assertTrue(pr_merge_calls_a, f"Expected gh pr merge call for Two-Way Door, got: {two_way_cmds}")
        create_args_str_a = " ".join(pr_create_calls_a[0])
        self.assertIn("[TWO-WAY DOOR]", create_args_str_a.upper())

        # --- Case B: One-Way Door (src/db/migrations/0005_add_col.sql) -> PR opened with [ONE-WAY DOOR], NOT auto-merged ---
        (specs_dir / "db-mig.md").write_text(
            "# DB Migration Slice\n\n```mermaid\nstateDiagram-v2\n    V1 --> V2\n```\n",
            encoding="utf-8",
        )
        ticket_one_way = self._make_ticket(
            ticket_id="TICK-FEAT-DB-MIG",
            domain="db",
            target_file="src/db/migrations/0005_add_col.sql",
            branch_name="feat/db-mig",
            spec_path=".edge/specs/db-mig.md",
        )
        self.fsm.state.active_ticket = ticket_one_way
        self.fsm.state.active_branch = "feat/db-mig"
        self.fsm.state.current_state = CycleState.STAGING

        one_way_cmds: List[List[str]] = []

        def run_cmd_one_way(cmd, cwd=None, timeout=120):
            cmd_list = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else str(cmd).split()
            one_way_cmds.append(cmd_list)
            if "status" in cmd_list and "--porcelain" in cmd_list:
                return (0, "", "")
            if "branch" in cmd_list and "--show-current" in cmd_list:
                return (0, "development\n", "")
            if "rev-parse" in cmd_list and "--verify" in cmd_list:
                return (0, "abc1234\n", "")
            if "diff" in cmd_list and "--name-only" in cmd_list:
                return (0, "src/db/migrations/0005_add_col.sql\nsrc/db/schema/bookings.ts\n", "")
            if "diff" in cmd_list and "--stat" in cmd_list:
                return (0, "2 files changed, 25 insertions(+)\n", "")
            if "gh" in cmd_list and "pr" in cmd_list and "create" in cmd_list:
                return (0, "https://github.com/org/repo/pull/43\n", "")
            if "gh" in cmd_list and "pr" in cmd_list and "merge" in cmd_list:
                return (0, "Merged pull request #43\n", "")
            return (0, "", "")

        with (
            patch("tools.brigade.fsm.run_command", side_effect=run_cmd_one_way),
            patch("tools.brigade.ship_prep.run_command", side_effect=run_cmd_one_way),
            patch("tools.brigade.fsm.return_worktree", return_value=(True, "returned")),
        ):
            ok_b, msg_b = self.fsm.finish_slice(open_pr=True, auto_merge_two_way=True)

        pr_create_calls_b = [c for c in one_way_cmds if "gh" in c and "pr" in c and "create" in c]
        pr_merge_calls_b = [c for c in one_way_cmds if "gh" in c and "pr" in c and "merge" in c]
        self.assertTrue(pr_create_calls_b, f"Expected gh pr create call for One-Way Door, got: {one_way_cmds}")
        self.assertEqual(len(pr_merge_calls_b), 0, "One-Way Door PR must NEVER call gh pr merge automatically!")
        create_args_str_b = " ".join(pr_create_calls_b[0])
        self.assertIn("[ONE-WAY DOOR]", create_args_str_b.upper())
        self.assertIn("one-way door", msg_b.lower())
        self.assertTrue(
            "human review" in msg_b.lower() or "held open" in msg_b.lower() or "manual" in msg_b.lower(),
            f"Expected One-Way Door hold diagnostic in message, got: {msg_b}",
        )

    def test_spec_writer_and_qa_engineer_rubrics_document_mermaid_workflow_alignment_within_budget(self):
        spec_writer_path = self.repo_root / "agents" / "spec-writer.md"
        qa_engineer_path = self.repo_root / "agents" / "qa-engineer.md"

        sw_text = spec_writer_path.read_text(encoding="utf-8")
        sw_lines = sw_text.splitlines()
        self.assertLessEqual(len(sw_lines), 60, f"agents/spec-writer.md exceeded 60 lines ({len(sw_lines)})")
        self.assertIn("mermaid", sw_text.lower(), "agents/spec-writer.md must require a mermaid workflow/state diagram")
        self.assertTrue(
            "flowchart" in sw_text.lower() or "statediagram" in sw_text.lower(),
            "agents/spec-writer.md must reference flowchart or stateDiagram-v2",
        )

        qa_text = qa_engineer_path.read_text(encoding="utf-8")
        qa_lines = qa_text.splitlines()
        self.assertLessEqual(len(qa_lines), 60, f"agents/qa-engineer.md exceeded 60 lines ({len(qa_lines)})")
        self.assertIn("mermaid", qa_text.lower(), "agents/qa-engineer.md must reference following the spec's mermaid workflow")

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-004 (IC-2, IC-3, IC-5): Per-Spec Ship Engine & Skills Decoupling
    # ------------------------------------------------------------------

    def test_per_spec_ship_plans_scoped_proofs_and_split_branches(self):
        import inspect
        import io
        from contextlib import redirect_stdout

        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        SpecShipPlan = getattr(ship_prep, "SpecShipPlan", None)
        self.assertIsNotNone(SpecShipPlan, "tools.brigade.ship_prep must define SpecShipPlan")
        discover_fn = getattr(ship_prep, "discover_changed_specs", None)
        self.assertIsNotNone(discover_fn, "tools.brigade.ship_prep must define discover_changed_specs")
        split_fn = getattr(ship_prep, "create_split_branches", None)
        self.assertIsNotNone(split_fn, "tools.brigade.ship_prep must define create_split_branches")

        sig = inspect.signature(ship_prep.prepare_ship_payload)
        self.assertIn("spec_slug", sig.parameters, "prepare_ship_payload must accept spec_slug")
        self.assertIn("split_branches", sig.parameters, "prepare_ship_payload must accept split_branches")

        tmp_parent = Path(tempfile.mkdtemp(dir=self.test_dir))
        bare_dir = tmp_parent / "origin.git"
        repo_dir = tmp_parent / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

        def git(*git_args):
            proc = subprocess.run(
                ["git", *git_args],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            return proc.stdout.strip()

        git("init", "-b", "development")
        git("config", "user.email", "brigade@example.com")
        git("config", "user.name", "Edge Brigade")
        git("remote", "add", "origin", bare_dir.as_uri())

        # Base origin/development commit with a stale/malformed historical proof that MUST NOT block future slices
        (repo_dir / "README.md").write_text("# Base Repo\n", encoding="utf-8")
        (repo_dir / "specs").mkdir(parents=True, exist_ok=True)
        (repo_dir / "specs" / "INDEX.md").write_text("# Navigation Index\n", encoding="utf-8")
        proofs_dir = repo_dir / ".edge" / "qa" / "proofs"
        proofs_dir.mkdir(parents=True, exist_ok=True)
        (proofs_dir / "legacy-broken.json").write_text("{malformed-legacy-json", encoding="utf-8")
        git("add", "-A")
        git("commit", "-m", "chore: origin/development base with legacy broken proof")
        git("push", "-u", "origin", "development")

        arch_dir = repo_dir / ".edge" / "archive" / "specs"
        arch_dir.mkdir(parents=True, exist_ok=True)
        (arch_dir / "alpha.md").write_text(
            "---\n"
            "expected_files:\n"
            "  - src/alpha/core.ts\n"
            "---\n\n"
            "# Alpha Flow Slice\n\n"
            "Summary: Implements alpha slice.\n\n"
            "```mermaid\n"
            "flowchart LR\n"
            "    Start --> AlphaDone\n"
            "```\n",
            encoding="utf-8",
        )
        (arch_dir / "beta.md").write_text(
            "---\n"
            "expected_files:\n"
            "  - src/beta/core.ts\n"
            "---\n\n"
            "# Beta Flow Slice\n\n"
            "Summary: Implements beta slice.\n\n"
            "```mermaid\n"
            "stateDiagram-v2\n"
            "    Init --> BetaReady\n"
            "```\n",
            encoding="utf-8",
        )

        (repo_dir / "specs" / "INDEX.md").write_text(
            "# Navigation Index\n"
            "- @module alpha | Action: runAlpha | @spec .edge/archive/specs/alpha.md\n"
            "- @module beta | Action: runBeta | @spec .edge/archive/specs/beta.md\n",
            encoding="utf-8",
        )
        (repo_dir / "src" / "alpha").mkdir(parents=True, exist_ok=True)
        (repo_dir / "src" / "alpha" / "core.ts").write_text("export const alpha = 1;\n", encoding="utf-8")
        (repo_dir / "src" / "beta").mkdir(parents=True, exist_ok=True)
        (repo_dir / "src" / "beta" / "core.ts").write_text("export const beta = 2;\n", encoding="utf-8")

        shots_dir = repo_dir / ".edge" / "qa" / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / "alpha-1.png").write_bytes(self._make_solid_png(4, 4, (10, 40, 80)))
        (proofs_dir / "alpha.json").write_text(
            json.dumps({
                "slug": "alpha",
                "visited_urls": ["http://localhost:3000/alpha"],
                "user_actions_executed": ["click alpha", "reload"],
                "persistence_verified": True,
                "console_clean": True,
                "screenshot_paths": [".edge/qa/screenshots/alpha-1.png"],
                "host_facts_verified": True,
                "db_crosscheck": {"alpha": 1},
            }),
            encoding="utf-8",
        )

        git("add", "-A")
        git("commit", "-m", "feat: deliver alpha and beta slices on development")

        # 1. Scoped ProofVerifier ignores legacy-broken.json & builds 2 SpecShipPlans
        ok, result, err = ship_prep.prepare_ship_payload(repo_dir, base_branch="development")
        self.assertTrue(ok, f"prepare_ship_payload must ignore legacy-broken.json and succeed: {err}")
        self.assertEqual(result.failed_proofs, [], f"legacy-broken.json must not fail scoped proofs: {result.failed_proofs}")
        self.assertTrue(hasattr(result, "spec_plans"), "ShipPrepResult must include spec_plans")
        self.assertEqual(len(result.spec_plans), 2, f"Expected 2 SpecShipPlans, got: {result.spec_plans}")

        plans_by_slug = {p.spec_slug: p for p in result.spec_plans}
        self.assertIn("alpha", plans_by_slug)
        self.assertIn("beta", plans_by_slug)

        alpha_plan = plans_by_slug["alpha"]
        beta_plan = plans_by_slug["beta"]
        self.assertEqual(alpha_plan.pr_branch, "ship/alpha")
        self.assertEqual(beta_plan.pr_branch, "ship/beta")
        self.assertIn("src/alpha/core.ts", alpha_plan.matched_files)
        self.assertIn("src/beta/core.ts", beta_plan.matched_files)
        self.assertTrue(len(alpha_plan.verified_proofs) == 1 and alpha_plan.verified_proofs[0]["slug"] == "alpha")
        self.assertEqual(alpha_plan.failed_proofs, [])

        # 2. Lean 2-section PR body (NO ## Merge Danger / One-way door / Two-way door)
        for body in (alpha_plan.pr_body, alpha_plan.show_me_body, beta_plan.pr_body, result.pr_body, result.show_me_body):
            self.assertIn("## Summary", body)
            self.assertIn("## Evidence", body)
            self.assertNotIn("## Merge Danger", body)
            self.assertNotIn("One-way door", body)
            self.assertNotIn("Two-way door", body)
        self.assertIn("gh pr create", alpha_plan.show_me_body)
        self.assertIn("ship/alpha", alpha_plan.show_me_body)
        self.assertNotIn("no-mistakes axi run", alpha_plan.show_me_body)

        # 3. CLI --spec alpha --format pr (defaults to --base development)
        stdout_buf = io.StringIO()
        try:
            with patch.object(
                sys,
                "argv",
                ["brigade", "prepare-ship", str(repo_dir), "--base", "development", "--spec", "alpha", "--format", "pr"],
            ), redirect_stdout(stdout_buf):
                rc_spec = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'prepare-ship --spec alpha' exited abnormally: {exc}")
        self.assertEqual(rc_spec, 0)
        spec_out = stdout_buf.getvalue()
        self.assertIn("## Summary", spec_out)
        self.assertIn("## Evidence", spec_out)
        self.assertIn("Alpha Flow Slice", spec_out)
        self.assertNotIn("Beta Flow Slice", spec_out)
        self.assertNotIn("## Merge Danger", spec_out)

        # 4. CLI --split-branches --format json creates isolated ship/alpha & ship/beta off origin/development and restores HEAD
        json_buf = io.StringIO()
        try:
            with patch.object(
                sys,
                "argv",
                ["brigade", "prepare-ship", str(repo_dir), "--base", "development", "--split-branches", "--format", "json"],
            ), redirect_stdout(json_buf):
                rc_split = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'prepare-ship --split-branches' exited abnormally: {exc}")
        self.assertEqual(rc_split, 0)
        json_payload = json.loads(json_buf.getvalue())
        self.assertIn("spec_plans", json_payload)
        self.assertIn("split_branches_created", json_payload)
        self.assertEqual(sorted(json_payload["split_branches_created"]), ["ship/alpha", "ship/beta"])

        self.assertEqual(git("branch", "--show-current"), "development", "Original branch must be restored after --split-branches")
        branches_out = git("branch", "--list", "ship/*")
        self.assertIn("ship/alpha", branches_out)
        self.assertIn("ship/beta", branches_out)

        alpha_tree = set(git("ls-tree", "-r", "--name-only", "ship/alpha").splitlines())
        self.assertIn("src/alpha/core.ts", alpha_tree)
        self.assertIn(".edge/archive/specs/alpha.md", alpha_tree)
        self.assertIn(".edge/qa/proofs/alpha.json", alpha_tree)
        self.assertIn(".edge/qa/screenshots/alpha-1.png", alpha_tree)
        self.assertNotIn("src/beta/core.ts", alpha_tree)
        self.assertNotIn(".edge/archive/specs/beta.md", alpha_tree)

        beta_tree = set(git("ls-tree", "-r", "--name-only", "ship/beta").splitlines())
        self.assertIn("src/beta/core.ts", beta_tree)
        self.assertIn(".edge/archive/specs/beta.md", beta_tree)
        self.assertNotIn("src/alpha/core.ts", beta_tree)
        self.assertNotIn(".edge/archive/specs/alpha.md", beta_tree)

        # 5. Unknown --spec returns exit code 1
        try:
            with patch.object(
                sys,
                "argv",
                ["brigade", "prepare-ship", str(repo_dir), "--base", "development", "--spec", "does-not-exist"],
            ):
                rc_missing = brigade_cli.main()
        except SystemExit as exc:
            self.fail(f"CLI 'prepare-ship --spec does-not-exist' should return 1 cleanly, not SystemExit: {exc}")
        self.assertEqual(rc_missing, 1)

    def test_edge_ship_and_edge_no_mistakes_skills_decoupled(self):
        edge_ship_path = self.repo_root / "skills" / "edge-ship" / "SKILL.md"
        edge_nm_path = self.repo_root / "skills" / "edge-no-mistakes" / "SKILL.md"

        ship_text = edge_ship_path.read_text(encoding="utf-8")
        self.assertIn("--split-branches", ship_text)
        self.assertIn("gh pr checks", ship_text)
        self.assertIn("gh pr create", ship_text)
        self.assertIn("--base staging", ship_text)
        self.assertNotIn("no-mistakes axi run", ship_text)

        nm_text = edge_nm_path.read_text(encoding="utf-8")
        self.assertNotIn("This skill is an alias for", nm_text)
        self.assertIn("--skip review,test", nm_text)
        self.assertIn("gh issue create", nm_text)
        self.assertIn("frontier-axi", nm_text)

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-005 (IC-1 .. IC-5): Gitignored .edge/, Commit Splitting & Visual PR Evidence
    # ------------------------------------------------------------------

    def test_SPEC_EDGE_BRIGADE_005_ic1_gitignored_spec_discovery_and_ticket_resolution(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        resolve_ticket_fn = getattr(ship_prep, "_resolve_spec_ticket_ids", None)
        self.assertIsNotNone(
            resolve_ticket_fn,
            "tools.brigade.ship_prep must define _resolve_spec_ticket_ids (SPEC-EDGE-BRIGADE-005 IC-1)",
        )

        with tempfile.TemporaryDirectory() as tmp_root:
            repo_dir = Path(tmp_root)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")

            (repo_dir / ".gitignore").write_text(".edge/\n", encoding="utf-8")
            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            git("add", ".gitignore", "README.md")
            git("commit", "-m", "chore: base staging with .edge ignored")

            git("checkout", "-b", "development")

            # Commits in staging..HEAD without committing .edge/ specs
            (repo_dir / "src" / "components" / "portfolio").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "components" / "portfolio" / "PortfolioStudio.tsx").write_text(
                "export const PortfolioStudio = () => null;\n", encoding="utf-8"
            )
            (repo_dir / "src" / "actions").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "actions" / "portal-stories.ts").write_text(
                "export async function updatePortalStoryAction() {}\n", encoding="utf-8"
            )
            git("add", "src")
            git("commit", "-m", "feat(polish): [TICK-FEAT-CONTENT-STU-POLISH] avatar and story polish")

            (repo_dir / "src" / "components" / "portal").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "components" / "portal" / "LookbookCard.tsx").write_text(
                "export const LookbookCard = () => null;\n", encoding="utf-8"
            )
            git("add", "src")
            git("commit", "-m", "feat(portal): 3:4 grid and object-top framing")

            # Untracked gitignored specs under .edge/archive/specs/ (no TICK-* literal in markdown!)
            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "content-studio-avatar-story-polish.md").write_text(
                "# Spec: Content Studio Avatar & Story Polish\n\n"
                "| AC | Scope | File |\n"
                "| :--- | :--- | :--- |\n"
                "| AC-01 | Avatar | `src/components/portfolio/PortfolioStudio.tsx` |\n"
                "| AC-03 | Story | `src/actions/portal-stories.ts` |\n",
                encoding="utf-8",
            )
            (arch_dir / "content-studio-avatar-story-polish-critique.md").write_text(
                "# Critique: Content Studio\n\n`src/actions/portal-stories.ts`\n",
                encoding="utf-8",
            )
            (arch_dir / "portal-grid-aspect-and-mobile-nav-polish.md").write_text(
                "# Spec: Portal Grid & Mobile Nav Polish\n\n"
                "| AC | Scope | File |\n"
                "| :--- | :--- | :--- |\n"
                "| AC-01 | Grid | `src/components/portal/LookbookCard.tsx` |\n",
                encoding="utf-8",
            )
            (arch_dir / "unrelated-old.md").write_text(
                "# Old Unrelated Spec\n\n"
                "---\nexpected_files:\n  - src/legacy/never_touched.ts\n---\n",
                encoding="utf-8",
            )

            # Untracked proof JSON + brigade.json history for reverse ticket resolution
            proofs_dir = repo_dir / ".edge" / "qa" / "proofs"
            proofs_dir.mkdir(parents=True, exist_ok=True)
            (proofs_dir / "portal.json").write_text(
                json.dumps({
                    "slug": "portal",
                    "spec": ".edge/specs/portal-grid-aspect-and-mobile-nav-polish.md",
                    "ticket_id": "TICK-FEAT-PORTAL-GRID-POLISH",
                    "visited_urls": ["http://localhost:3000/portal/explore"],
                    "user_actions_executed": ["open"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [],
                    "host_facts_verified": True,
                    "db_crosscheck": {"cells": 1},
                }),
                encoding="utf-8",
            )

            brigade_state = {
                "version": "2.0.0",
                "repo_path": str(repo_dir),
                "base_branch": "development",
                "current_state": "IDLE",
                "active_ticket": None,
                "examiner_receipt": None,
                "history": [
                    {
                        "timestamp": "2026-11-19T03:00:00Z",
                        "from_state": "REVIEW",
                        "to_state": "STAGING",
                        "success": True,
                        "message": "Sealed TICK-FEAT-CONTENT-STU-POLISH",
                        "details": {
                            "ticket_id": "TICK-FEAT-CONTENT-STU-POLISH",
                            "examiner_receipt": {
                                "verdict": "PASS",
                                "summary": "Avatar & story polish passed",
                                "evidence_reviewed": [
                                    ".edge/archive/specs/content-studio-avatar-story-polish.md",
                                    "src/actions/portal-stories.ts",
                                ],
                            },
                        },
                    }
                ],
            }
            (repo_dir / ".edge" / "brigade.json").write_text(
                json.dumps(brigade_state, indent=2), encoding="utf-8"
            )

            changed_files = git("diff", "--name-only", "staging..HEAD").splitlines()
            discovered = ship_prep.discover_changed_specs(repo_dir, "staging", changed_files, [])

            self.assertEqual(
                sorted(discovered),
                sorted([
                    ".edge/archive/specs/content-studio-avatar-story-polish.md",
                    ".edge/archive/specs/portal-grid-aspect-and-mobile-nav-polish.md",
                ]),
                f"Expected only the 2 matching gitignored archive specs, got: {discovered}",
            )
            self.assertNotIn(".edge/archive/specs/unrelated-old.md", discovered)
            self.assertNotIn(".edge/archive/specs/content-studio-avatar-story-polish-critique.md", discovered)

            history_receipts = {
                "TICK-FEAT-CONTENT-STU-POLISH": brigade_state["history"][0]["details"]["examiner_receipt"]
            }
            ticket_map = resolve_ticket_fn(repo_dir, "staging", discovered, history_receipts)
            self.assertEqual(
                ticket_map.get(".edge/archive/specs/content-studio-avatar-story-polish.md"),
                "TICK-FEAT-CONTENT-STU-POLISH",
            )
            self.assertEqual(
                ticket_map.get(".edge/archive/specs/portal-grid-aspect-and-mobile-nav-polish.md"),
                "TICK-FEAT-PORTAL-GRID-POLISH",
            )

    def test_SPEC_EDGE_BRIGADE_005_ic2_table_extraction_globs_and_commit_split_branches(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        extract_tables_fn = getattr(ship_prep, "_extract_table_paths", None)
        self.assertIsNotNone(
            extract_tables_fn,
            "tools.brigade.ship_prep must define _extract_table_paths (SPEC-EDGE-BRIGADE-005 IC-2)",
        )

        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_path = Path(tmp_root)
            bare_dir = tmp_path / "origin.git"
            repo_dir = tmp_path / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "development")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")
            git("remote", "add", "origin", bare_dir.as_uri())

            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            (repo_dir / "src" / "app" / "(portal)" / "portal").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "app" / "(portal)" / "portal" / "page.tsx").write_text(
                "export const base = 1;\n", encoding="utf-8"
            )
            git("add", "-A")
            git("commit", "-m", "chore: origin/development base")
            git("push", "-u", "origin", "development")

            # Spec 1 using ONLY Markdown tables (no YAML expected_files / ## Expected Files)
            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "slug-one.md").write_text(
                "# Slice One Spec\n\n"
                "## 1. AC\n"
                "| AC | Scope | Contract |\n"
                "| :--- | :--- | :--- |\n"
                "| AC-01 | Migration | Add column in `src/db/migrations/0017_*.sql` |\n\n"
                "## 2. Inventory\n"
                "| Layer | File |\n"
                "| :--- | :--- |\n"
                "| Core | `src/slice1/studio.ts` |\n",
                encoding="utf-8",
            )

            extracted_one = ship_prep._extract_spec_expected_files(arch_dir / "slug-one.md")
            self.assertIn("src/db/migrations/0017_*.sql", extracted_one)
            self.assertIn("src/slice1/studio.ts", extracted_one)

            # Slice 1 commits: [TICK-ONE], fix(polish):, and untagged test(portal):
            (repo_dir / "src" / "db" / "migrations").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "db" / "migrations" / "0017_avatar_poster.sql").write_text(
                "ALTER TABLE profiles ADD COLUMN avatar_url text;\n", encoding="utf-8"
            )
            (repo_dir / "src" / "slice1").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "slice1" / "studio.ts").write_text("export const v = 1;\n", encoding="utf-8")
            shots_dir = repo_dir / ".edge" / "qa" / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / "s1.png").write_bytes(self._make_solid_png(4, 4, (10, 20, 30)))
            proofs_dir = repo_dir / ".edge" / "qa" / "proofs"
            proofs_dir.mkdir(parents=True, exist_ok=True)
            (proofs_dir / "portal.json").write_text(
                json.dumps({
                    "slug": "portal",
                    "spec": ".edge/specs/slug-one.md",
                    "ticket_id": "TICK-ONE",
                    "visited_urls": ["http://localhost:3000/dashboard/content"],
                    "user_actions_executed": ["save avatar"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/s1.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"slice": 1},
                }),
                encoding="utf-8",
            )
            git("add", "-A")
            git("commit", "-m", "feat(studio): [TICK-ONE] migration, studio and slice-1 proof")

            (repo_dir / "src" / "slice1" / "studio.ts").write_text("export const v = 2;\n", encoding="utf-8")
            git("add", "src/slice1/studio.ts")
            git("commit", "-m", "fix(polish): harden studio guard")

            (repo_dir / "tests" / "unit").mkdir(parents=True, exist_ok=True)
            (repo_dir / "tests" / "unit" / "studio.test.ts").write_text(
                "import '../src/slice1/studio';\n", encoding="utf-8"
            )
            git("add", "tests/unit/studio.test.ts")
            git("commit", "-m", "test(portal): add untagged studio regression test")

            # Spec 2 + Slice 2 commits: [TICK-TWO] modifying shared portal.json + non-overlapping page.tsx
            (arch_dir / "slug-two.md").write_text(
                "# Slice Two Spec\n\n"
                "## 1. AC\n"
                "| AC | Scope | Contract |\n"
                "| :--- | :--- | :--- |\n"
                "| AC-01 | Layout | Update `src/app/(portal)/layout.tsx` and `src/app/(portal)/portal/page.tsx` |\n",
                encoding="utf-8",
            )
            (repo_dir / "src" / "app" / "(portal)" / "layout.tsx").write_text(
                "export default function Layout() { return null; }\n", encoding="utf-8"
            )
            (repo_dir / "src" / "app" / "(portal)" / "portal" / "page.tsx").write_text(
                "export const base = 2;\n", encoding="utf-8"
            )
            (shots_dir / "s2.png").write_bytes(self._make_solid_png(4, 4, (50, 60, 70)))
            (proofs_dir / "portal.json").write_text(
                json.dumps({
                    "slug": "portal",
                    "spec": ".edge/specs/slug-two.md",
                    "ticket_id": "TICK-TWO",
                    "visited_urls": ["http://localhost:3000/portal/explore"],
                    "user_actions_executed": ["open grid"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/s2.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"slice": 2},
                }),
                encoding="utf-8",
            )
            git("add", "-A")
            git("commit", "-m", "feat(portal): [TICK-TWO] layout, portal page and slice-2 proof")

            (repo_dir / "src" / "app" / "(portal)" / "layout.tsx").write_text(
                "export default function Layout() { return 'v2'; }\n", encoding="utf-8"
            )
            git("add", "src/app/(portal)/layout.tsx")
            git("commit", "-m", "test(QA): [TICK-TWO] verify mobile nav")

            ok, result, err = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="development", split_branches=True
            )
            self.assertTrue(ok, f"prepare_ship_payload(split_branches=True) failed: {err}")
            self.assertEqual(sorted(result.split_branches_created), ["ship/slug-one", "ship/slug-two"])
            self.assertEqual(git("branch", "--show-current"), "development")

            slug1_tree = set(git("ls-tree", "-r", "--name-only", "ship/slug-one").splitlines())
            self.assertIn("src/db/migrations/0017_avatar_poster.sql", slug1_tree)
            self.assertIn("src/slice1/studio.ts", slug1_tree)
            self.assertIn("tests/unit/studio.test.ts", slug1_tree)
            self.assertNotIn("src/app/(portal)/layout.tsx", slug1_tree)
            slug1_proof = json.loads(git("show", "ship/slug-one:.edge/qa/proofs/portal.json"))
            self.assertEqual(slug1_proof["ticket_id"], "TICK-ONE")

            slug2_tree = set(git("ls-tree", "-r", "--name-only", "ship/slug-two").splitlines())
            self.assertIn("src/app/(portal)/layout.tsx", slug2_tree)
            self.assertIn("src/app/(portal)/portal/page.tsx", slug2_tree)
            self.assertNotIn("src/slice1/studio.ts", slug2_tree)
            slug2_proof = json.loads(git("show", "ship/slug-two:.edge/qa/proofs/portal.json"))
            self.assertEqual(slug2_proof["ticket_id"], "TICK-TWO")

    def test_SPEC_EDGE_BRIGADE_005_ic3_ic4_historical_proof_blobs_and_examiner_receipt_recovery(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        extract_receipts_fn = getattr(ship_prep, "_extract_examiner_receipts_by_ticket", None)
        self.assertIsNotNone(
            extract_receipts_fn,
            "tools.brigade.ship_prep must define _extract_examiner_receipts_by_ticket (SPEC-EDGE-BRIGADE-005 IC-4)",
        )

        with tempfile.TemporaryDirectory() as tmp_root:
            repo_dir = Path(tmp_root)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")
            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            git("add", "README.md")
            git("commit", "-m", "chore: staging base")

            git("checkout", "-b", "development")

            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "slug-one.md").write_text(
                "---\nexpected_files:\n  - src/one.ts\n---\n# Slice One\n", encoding="utf-8"
            )
            (arch_dir / "slug-two.md").write_text(
                "---\nexpected_files:\n  - src/two.ts\n---\n# Slice Two\n", encoding="utf-8"
            )

            shots_dir = repo_dir / ".edge" / "qa" / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / "s1.png").write_bytes(self._make_solid_png(4, 4, (11, 22, 33)))
            (shots_dir / "s2.png").write_bytes(self._make_solid_png(4, 4, (44, 55, 66)))

            proofs_dir = repo_dir / ".edge" / "qa" / "proofs"
            proofs_dir.mkdir(parents=True, exist_ok=True)

            # Commit A: Slice 1 writes portal.json
            (repo_dir / "src").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "one.ts").write_text("export const one = 1;\n", encoding="utf-8")
            (proofs_dir / "portal.json").write_text(
                json.dumps({
                    "slug": "portal",
                    "spec": ".edge/specs/slug-one.md",
                    "ticket_id": "TICK-ONE",
                    "visited_urls": ["http://localhost:3000/one"],
                    "user_actions_executed": ["verify one"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/s1.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"one": 1},
                }),
                encoding="utf-8",
            )
            git("add", "-A")
            git("commit", "-m", "feat: [TICK-ONE] deliver slice one")

            # Commit B: Slice 2 overwrites the same .edge/qa/proofs/portal.json path
            (repo_dir / "src" / "two.ts").write_text("export const two = 2;\n", encoding="utf-8")
            (proofs_dir / "portal.json").write_text(
                json.dumps({
                    "slug": "portal",
                    "spec": ".edge/specs/slug-two.md",
                    "ticket_id": "TICK-TWO",
                    "visited_urls": ["http://localhost:3000/two"],
                    "user_actions_executed": ["verify two"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/s2.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"two": 2},
                }),
                encoding="utf-8",
            )
            git("add", "-A")
            git("commit", "-m", "feat: [TICK-TWO] deliver slice two")

            # Simulate finish-slice resetting state.examiner_receipt = None while keeping history entries
            brigade_state = {
                "version": "2.0.0",
                "repo_path": str(repo_dir),
                "base_branch": "development",
                "current_state": "IDLE",
                "active_ticket": None,
                "examiner_receipt": None,
                "history": [
                    {
                        "timestamp": "2026-11-19T01:00:00Z",
                        "from_state": "REVIEW",
                        "to_state": "STAGING",
                        "success": True,
                        "message": "Landed TICK-ONE",
                        "details": {
                            "ticket_id": "TICK-ONE",
                            "examiner_receipt": {
                                "verdict": "PASS",
                                "summary": "Slice 1 Examiner Seal",
                                "evidence_reviewed": [".edge/archive/specs/slug-one.md", "src/one.ts"],
                            },
                        },
                    },
                    {
                        "timestamp": "2026-11-19T02:00:00Z",
                        "from_state": "REVIEW",
                        "to_state": "STAGING",
                        "success": True,
                        "message": "Landed TICK-TWO",
                        "details": {
                            "ticket_id": "TICK-TWO",
                            "examiner_receipt": {
                                "verdict": "PASS",
                                "summary": "Slice 2 Examiner Seal",
                                "evidence_reviewed": [".edge/archive/specs/slug-two.md", "src/two.ts"],
                            },
                        },
                    },
                ],
            }
            (repo_dir / ".edge" / "brigade.json").write_text(
                json.dumps(brigade_state, indent=2), encoding="utf-8"
            )

            ok, result, err = ship_prep.prepare_ship_payload(repo_dir, base_branch="staging")
            self.assertTrue(ok, f"prepare_ship_payload failed: {err}")
            self.assertEqual(result.failed_proofs, [])
            self.assertEqual(len(result.verified_proofs), 2, f"Expected both proofs recovered: {result.verified_proofs}")

            proofs_by_ticket = {p.get("ticket_id"): p for p in result.verified_proofs}
            self.assertEqual(proofs_by_ticket["TICK-ONE"].get("spec_slug"), "slug-one")
            self.assertEqual(proofs_by_ticket["TICK-ONE"].get("path"), ".edge/qa/proofs/portal.json")
            self.assertEqual(proofs_by_ticket["TICK-TWO"].get("spec_slug"), "slug-two")
            self.assertEqual(proofs_by_ticket["TICK-TWO"].get("path"), ".edge/qa/proofs/portal.json")

            plans_by_slug = {p.spec_slug: p for p in result.spec_plans}
            self.assertEqual(len(plans_by_slug["slug-one"].verified_proofs), 1)
            self.assertEqual(plans_by_slug["slug-one"].verified_proofs[0].get("ticket_id"), "TICK-ONE")
            self.assertIn("Slice 1 Examiner Seal", plans_by_slug["slug-one"].pr_body)
            self.assertNotIn("Slice 2 Examiner Seal", plans_by_slug["slug-one"].pr_body)

            self.assertEqual(len(plans_by_slug["slug-two"].verified_proofs), 1)
            self.assertEqual(plans_by_slug["slug-two"].verified_proofs[0].get("ticket_id"), "TICK-TWO")
            self.assertIn("Slice 2 Examiner Seal", plans_by_slug["slug-two"].pr_body)
            self.assertNotIn("Slice 1 Examiner Seal", plans_by_slug["slug-two"].pr_body)

    def test_SPEC_EDGE_BRIGADE_005_ic5_publish_evidence_orphan_branch_and_pr_images(self):
        import inspect
        import io
        from contextlib import redirect_stdout

        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        publish_fn = getattr(ship_prep, "publish_screenshots_to_evidence_branch", None)
        parse_fn = getattr(ship_prep, "parse_github_owner_repo", None)
        self.assertIsNotNone(publish_fn, "tools.brigade.ship_prep must define publish_screenshots_to_evidence_branch")
        self.assertIsNotNone(parse_fn, "tools.brigade.ship_prep must define parse_github_owner_repo")

        sig = inspect.signature(ship_prep.prepare_ship_payload)
        self.assertIn("publish_evidence", sig.parameters)
        self.assertIn("evidence_branch", sig.parameters)

        # Verify parse_github_owner_repo handles SSH & HTTPS remotes
        self.assertEqual(parse_fn("git@github.com:o/r.git"), ("o", "r"))
        self.assertEqual(parse_fn("https://github.com/o/r.git"), ("o", "r"))

        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_path = Path(tmp_root)
            bare_dir = tmp_path / "origin.git"
            repo_dir = tmp_path / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)

            subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")
            git("remote", "add", "origin", bare_dir.as_uri())

            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            git("add", "README.md")
            git("commit", "-m", "chore: staging base")
            git("push", "-u", "origin", "staging")

            git("checkout", "-b", "development")

            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "slug-one.md").write_text(
                "---\nexpected_files:\n  - src/one.ts\n---\n# Slice One\n", encoding="utf-8"
            )
            (arch_dir / "slug-two.md").write_text(
                "---\nexpected_files:\n  - src/two.ts\n---\n# Slice Two\n", encoding="utf-8"
            )
            (repo_dir / "src").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "one.ts").write_text("export const one = 1;\n", encoding="utf-8")
            (repo_dir / "src" / "two.ts").write_text("export const two = 2;\n", encoding="utf-8")

            shots_dir = repo_dir / ".edge" / "qa" / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / "shot1.png").write_bytes(self._make_solid_png(4, 4, (12, 34, 56)))
            (shots_dir / "shot2.png").write_bytes(self._make_solid_png(4, 4, (78, 90, 12)))

            proofs_dir = repo_dir / ".edge" / "qa" / "proofs"
            proofs_dir.mkdir(parents=True, exist_ok=True)
            (proofs_dir / "slug-one.json").write_text(
                json.dumps({
                    "slug": "slug-one",
                    "visited_urls": ["http://localhost:3000/one"],
                    "user_actions_executed": ["click"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/shot1.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"one": 1},
                }),
                encoding="utf-8",
            )
            (proofs_dir / "slug-two.json").write_text(
                json.dumps({
                    "slug": "slug-two",
                    "visited_urls": ["http://localhost:3000/two"],
                    "user_actions_executed": ["click"],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [".edge/qa/screenshots/shot2.png"],
                    "host_facts_verified": True,
                    "db_crosscheck": {"two": 2},
                }),
                encoding="utf-8",
            )
            git("add", "-A")
            git("commit", "-m", "feat: deliver slug-one and slug-two with screenshots")

            # Backward compatibility when publish_evidence=False (no inline image markdown)
            ok_no_pub, res_no_pub, err_no_pub = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging", publish_evidence=False
            )
            self.assertTrue(ok_no_pub, f"prepare_ship_payload(publish_evidence=False) failed: {err_no_pub}")
            self.assertNotIn("?raw=true", res_no_pub.pr_body)

            # Sequential accumulation on orphan branch edge-qa-evidence via publish_screenshots_to_evidence_branch
            plan_one = ship_prep.SpecShipPlan(
                spec_slug="slug-one",
                spec_path=".edge/archive/specs/slug-one.md",
                pr_branch="ship/slug-one",
                pr_title="feat(slug-one): Slice One",
                verified_proofs=[{"slug": "slug-one", "screenshot_paths": [".edge/qa/screenshots/shot1.png"]}],
            )
            plan_two = ship_prep.SpecShipPlan(
                spec_slug="slug-two",
                spec_path=".edge/archive/specs/slug-two.md",
                pr_branch="ship/slug-two",
                pr_title="feat(slug-two): Slice Two",
                verified_proofs=[{"slug": "slug-two", "screenshot_paths": [".edge/qa/screenshots/shot2.png"]}],
            )

            with patch.object(ship_prep, "parse_github_owner_repo", return_value=("o", "r")):
                publish_fn(repo_dir, "edge-qa-evidence", [plan_one], [repo_dir])
                first_sha = git("rev-parse", "refs/heads/edge-qa-evidence")

                # Publish ONLY plan_two in a second call to prove _seed_evidence_parent_tree retains plan_one
                publish_fn(repo_dir, "edge-qa-evidence", [plan_two], [repo_dir])
                second_sha = git("rev-parse", "refs/heads/edge-qa-evidence")

                ok_pub, res_pub, err_pub = ship_prep.prepare_ship_payload(
                    repo_dir,
                    base_branch="staging",
                    publish_evidence=True,
                    evidence_branch="edge-qa-evidence",
                )

            self.assertTrue(ok_pub, f"prepare_ship_payload(publish_evidence=True) failed: {err_pub}")
            self.assertEqual(git("branch", "--show-current"), "development")
            self.assertEqual(git("status", "--porcelain"), "")

            parents_line = git("rev-list", "--parents", "-n", "1", second_sha)
            self.assertIn(first_sha, parents_line.split()[1:], "Second evidence commit must chain -p <first_sha>")

            evidence_tree = set(git("ls-tree", "-r", "--name-only", second_sha).splitlines())
            self.assertIn("evidence/slug-one/shot1.png", evidence_tree)
            self.assertIn("evidence/slug-two/shot2.png", evidence_tree)

            third_sha = git("rev-parse", "refs/heads/edge-qa-evidence")
            plans_by_slug = {p.spec_slug: p for p in res_pub.spec_plans}
            expected_img_1 = f"![shot1.png](https://github.com/o/r/blob/{third_sha}/evidence/slug-one/shot1.png?raw=true)"
            expected_img_2 = f"![shot2.png](https://github.com/o/r/blob/{third_sha}/evidence/slug-two/shot2.png?raw=true)"
            for body in (plans_by_slug["slug-one"].pr_body, plans_by_slug["slug-one"].show_me_body):
                self.assertIn("## Evidence", body)
                self.assertIn(expected_img_1, body)
            self.assertIn(expected_img_1, res_pub.pr_body)
            self.assertIn(expected_img_2, res_pub.pr_body)

        # CLI --help & SKILL.md assertions
        help_buf = io.StringIO()
        with patch.object(sys, "argv", ["brigade", "prepare-ship", "--help"]), redirect_stdout(help_buf):
            with self.assertRaises(SystemExit) as cm:
                brigade_cli.main()
            self.assertEqual(cm.exception.code, 0)
        help_text = help_buf.getvalue()
        self.assertIn("--publish-evidence", help_text)
        self.assertIn("--evidence-branch", help_text)

        skill_text = (self.repo_root / "skills" / "edge-ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--publish-evidence", skill_text)

    def test_parse_github_owner_repo_supports_userinfo_urls(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        self.assertEqual(
            ship_prep.parse_github_owner_repo(
                "https://x-access-token:tok123@github.com/org/private-repo.git"
            ),
            ("org", "private-repo"),
        )
        self.assertEqual(
            ship_prep.parse_github_owner_repo("https://user@github.com/org/repo.git"),
            ("org", "repo"),
        )
        self.assertEqual(
            ship_prep.parse_github_owner_repo("ssh://git@github.com/org/repo.git"),
            ("org", "repo"),
        )
        self.assertEqual(
            ship_prep.parse_github_owner_repo("git@github.com:org/repo.git"),
            ("org", "repo"),
        )
        self.assertEqual(
            ship_prep.parse_github_owner_repo("https://github.com/org/repo.git"),
            ("org", "repo"),
        )
        self.assertIsNone(
            ship_prep.parse_github_owner_repo(
                "https://x-access-token:tok123@gitlab.com/org/repo.git"
            )
        )

    def test_publish_evidence_redacts_credentials_from_userinfo_and_git_errors(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        with tempfile.TemporaryDirectory() as tmp_root:
            repo_dir = Path(tmp_root)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "development")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")

            shots_dir = repo_dir / ".edge" / "qa" / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / "shot1.png").write_bytes(self._make_solid_png(4, 4, (10, 20, 30)))

            plan = ship_prep.SpecShipPlan(
                spec_slug="auth-fix",
                spec_path=".edge/archive/specs/auth-fix.md",
                pr_branch="ship/auth-fix",
                pr_title="feat(auth-fix): Auth Fix",
                verified_proofs=[
                    {
                        "slug": "auth-fix",
                        "screenshot_paths": [".edge/qa/screenshots/shot1.png"],
                    }
                ],
            )

            # Case 1: Non-GitHub remote containing credentialed userinfo must redact token
            git("remote", "add", "origin", "https://x-access-token:tok123@gitlab.com/org/repo.git")
            ok_non_gh, err_non_gh = ship_prep.publish_screenshots_to_evidence_branch(
                repo_dir, "edge-qa-evidence", [plan], [repo_dir]
            )
            self.assertFalse(ok_non_gh)
            self.assertNotIn("tok123", err_non_gh)
            self.assertNotIn("x-access-token:tok123@", err_non_gh)
            self.assertIn("gitlab.com/org/repo.git", err_non_gh)

            # Case 2: Credentialed GitHub remote where git push stderr echoes credentialed URL
            git("remote", "set-url", "origin", "https://x-access-token:tok123@github.com/org/private-repo.git")
            real_run_command = ship_prep.run_command

            def fake_run_command(cmd, cwd=None, **kwargs):
                if isinstance(cmd, list) and len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "push":
                    return (
                        1,
                        "",
                        "fatal: Authentication failed for 'https://x-access-token:tok123@github.com/org/private-repo.git/'",
                    )
                return real_run_command(cmd, cwd=cwd, **kwargs)

            with patch.object(ship_prep, "run_command", side_effect=fake_run_command):
                ok_push, err_push = ship_prep.publish_screenshots_to_evidence_branch(
                    repo_dir, "edge-qa-evidence", [plan], [repo_dir]
                )
            self.assertFalse(ok_push)
            self.assertNotIn("tok123", err_push)
            self.assertNotIn("x-access-token:tok123@", err_push)
            self.assertIn("github.com/org/private-repo.git", err_push)

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-005 (IC-1 .. IC-4): Spec Realization Audit & Human-Readable PR Evidence
    # ------------------------------------------------------------------

    def test_spec_realization_digest_title_normalization_and_skill_alignment(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        # IC-2: Word-boundary PR title truncation
        clean_title_fn = getattr(ship_prep, "_clean_pr_title", None)
        self.assertIsNotNone(clean_title_fn, "tools.brigade.ship_prep must define _clean_pr_title")
        truncated_title = clean_title_fn(
            "content-studio-avatar-story-polish",
            "Spec: Content Studio — Avatar, Story Preview, Edit & ABAC Polish",
        )
        self.assertLessEqual(len(truncated_title), 96)
        self.assertTrue(truncated_title.endswith("..."), f"Expected '...' suffix, got: {truncated_title!r}")
        self.assertNotIn("ABAC Po...", truncated_title)
        prefix = "feat(content-studio-avatar-story-polish): "
        self.assertTrue(truncated_title.startswith(prefix))
        body_part = truncated_title[len(prefix):-3]
        self.assertFalse(body_part.endswith(("&", "-", ":", ",", "(", "/", ";")))
        last_word = body_part.split()[-1]
        self.assertIn(
            last_word,
            {"Content", "Studio", "—", "Avatar,", "Avatar", "Story", "Preview,", "Preview", "Edit", "ABAC", "Polish"},
            f"Title cut mid-word at {last_word!r} in {truncated_title!r}",
        )

        # IC-2: Evidence artifact exclusion predicate
        is_ev_fn = getattr(ship_prep, "_is_evidence_artifact_path", None)
        self.assertIsNotNone(is_ev_fn, "tools.brigade.ship_prep must define _is_evidence_artifact_path")
        self.assertTrue(is_ev_fn(".edge/qa/screenshots/shot.png"))
        self.assertTrue(is_ev_fn(".edge/qa/proofs/portal.json"))
        self.assertTrue(is_ev_fn(".edge/qa/visual/diff.png"))
        self.assertFalse(is_ev_fn("src/portal/page.tsx"))
        self.assertFalse(is_ev_fn(".edge/archive/specs/portal.md"))

        # IC-3: Repo-relative display path normalization
        norm_fn = getattr(ship_prep, "_normalize_display_path", None)
        self.assertIsNotNone(norm_fn, "tools.brigade.ship_prep must define _normalize_display_path")
        self.assertEqual(
            norm_fn("/home/oguz/.treehouse/MS-Randevu-e3e293/8/MS-Randevu/.edge/qa/proofs/portal.json"),
            ".edge/qa/proofs/portal.json",
        )
        self.assertEqual(
            norm_fn("/home/oguz/MS-Randevu-monolith/src/a.ts"),
            "src/a.ts",
        )
        self.assertEqual(
            norm_fn("/home/oguz/.treehouse/pool/slot-1/app/src/a.ts"),
            "src/a.ts",
        )

        # IC-1: SpecDigest callstack_blocks & acceptance_criteria
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_file = Path(tmp_dir) / "portal-polish.md"
            spec_file.write_text(
                "---\n"
                "expected_files:\n"
                "  - src/portal/page.tsx\n"
                "  - src/portal/missing.ts\n"
                "---\n\n"
                "# Portal Polish Spec\n\n"
                "Summary: Delivers portal polish and call-stack audit.\n\n"
                "## 1. Acceptance Criteria\n\n"
                "| ID | Title | Expectation |\n"
                "| :--- | :--- | :--- |\n"
                "| AC-01 | Portal Filter | Filter updates rendered portal cards |\n"
                "| IC-1 | Repository Sync | Create portal item via repository |\n\n"
                "## 4. Call-Stack Tree & Responsive Layout Flow\n\n"
                "```text\n"
                "Page -> Action -> Repository -> DB\n"
                "```\n",
                encoding="utf-8",
            )
            digest = ship_prep.parse_spec_document(spec_file, rel_path=".edge/archive/specs/portal-polish.md")
            self.assertTrue(hasattr(digest, "callstack_blocks"), "SpecDigest must define callstack_blocks")
            self.assertTrue(hasattr(digest, "acceptance_criteria"), "SpecDigest must define acceptance_criteria")
            self.assertTrue(
                any("Page -> Action -> Repository" in blk for blk in digest.callstack_blocks),
                f"Expected callstack block captured, got: {digest.callstack_blocks}",
            )
            crit_ids = [c.get("id") for c in digest.acceptance_criteria]
            self.assertIn("AC-01", crit_ids)
            self.assertIn("IC-1", crit_ids)

        # IC-4: skills/edge-ship/SKILL.md alignment
        skill_text = (self.repo_root / "skills" / "edge-ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Spec Expectations vs. Realization", skill_text)
        self.assertIn("Examiner 3-Axis Seal", skill_text)

    def test_realization_audit_and_human_readable_pr_report_end_to_end(self):
        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        ExaminerReceipt = getattr(brigade_models, "ExaminerReceipt", None)
        self.assertIsNotNone(ExaminerReceipt)

        RealizationAudit = getattr(ship_prep, "RealizationAudit", None)
        self.assertIsNotNone(RealizationAudit, "tools.brigade.ship_prep must define RealizationAudit")
        compute_audit_fn = getattr(ship_prep, "compute_realization_audit", None)
        self.assertIsNotNone(compute_audit_fn, "tools.brigade.ship_prep must define compute_realization_audit")

        with tempfile.TemporaryDirectory() as tmp_root:
            repo_dir = Path(tmp_root)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")

            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            (repo_dir / "specs").mkdir(parents=True, exist_ok=True)
            (repo_dir / "specs" / "INDEX.md").write_text("# Navigation Index\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-m", "chore: base staging")

            git("checkout", "-b", "development")

            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "portal-polish.md").write_text(
                "---\n"
                "expected_files:\n"
                "  - src/portal/page.tsx\n"
                "  - src/portal/missing.ts\n"
                "---\n\n"
                "# Portal Polish\n\n"
                "Summary: Polish portal list and persistence.\n\n"
                "## 1. Acceptance Criteria\n\n"
                "| ID | Title | Expectation |\n"
                "| :--- | :--- | :--- |\n"
                "| AC-01 | Portal Filter | Filter portal cards on page |\n"
                "| IC-1 | Repository Save | Persist portal record via action |\n\n"
                "## 4. Call-Stack Tree & Responsive Layout Flow\n\n"
                "```text\n"
                "Page -> Action -> Repository -> DB\n"
                "```\n",
                encoding="utf-8",
            )

            (repo_dir / "src" / "portal").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "portal" / "page.tsx").write_text("export const PortalPage = () => null;\n", encoding="utf-8")
            (repo_dir / "src" / "SettlementSimulatorStudio.tsx").write_text(
                "export const SettlementSimulatorStudio = () => null;\n",
                encoding="utf-8",
            )

            shots_dir = repo_dir / ".edge" / "qa" / "screenshots"
            shots_dir.mkdir(parents=True, exist_ok=True)
            (shots_dir / "01-portal-favorites-desktop.png").write_bytes(self._make_solid_png(4, 4, (20, 40, 80)))
            (shots_dir / "02-portal-after.png").write_bytes(self._make_solid_png(4, 4, (80, 120, 160)))

            proofs_dir = repo_dir / ".edge" / "qa" / "proofs"
            proofs_dir.mkdir(parents=True, exist_ok=True)
            (proofs_dir / "portal-polish.json").write_text(
                json.dumps({
                    "slug": "portal-polish",
                    "visited_urls": [
                        "http://localhost:3000/portal/favorites",
                        "http://localhost:3000/portal/explore",
                    ],
                    "user_actions_executed": [
                        "Filter portal cards on page",
                        "Reload page and verify state",
                    ],
                    "persistence_verified": True,
                    "console_clean": True,
                    "screenshot_paths": [
                        ".edge/qa/screenshots/01-portal-favorites-desktop.png",
                        ".edge/qa/screenshots/02-portal-after.png",
                    ],
                    "host_facts_verified": True,
                    "db_crosscheck": {"portal_items": 3, "favorites": 1},
                    "directives_checklist": {
                        "AC-01": "Filter portal cards on page verified",
                    },
                }),
                encoding="utf-8",
            )

            fsm_local = BrigadeFSM(repo_dir)
            fsm_local.state.examiner_receipt = ExaminerReceipt(
                verdict="PASS",
                summary="3-axis audit passed cleanly",
                ticket_id="TICK-FEAT-PORTAL",
                evidence_reviewed=[
                    "/home/oguz/.treehouse/MS-Randevu-e3e293/8/MS-Randevu/.edge/qa/proofs/portal.json",
                    "/home/oguz/MS-Randevu-monolith/src/a.ts",
                ],
            )
            fsm_local.save()

            git("add", "-A")
            git("commit", "-m", "feat(portal-polish): implement portal polish")

            ok, result, err = ship_prep.prepare_ship_payload(repo_dir, base_branch="staging")
            self.assertTrue(ok, f"prepare_ship_payload failed: {err}")
            self.assertEqual(len(result.spec_plans), 1)
            plan = result.spec_plans[0]

            # IC-2: RealizationAudit fields & exclusion of evidence artifacts from actual_code_files
            audit = getattr(plan, "realization_audit", None)
            self.assertIsNotNone(audit, "SpecShipPlan must populate realization_audit")
            self.assertNotIn(".edge/qa/proofs/portal-polish.json", audit.actual_code_files)
            self.assertNotIn(".edge/qa/screenshots/01-portal-favorites-desktop.png", audit.actual_code_files)
            self.assertIn("src/portal/page.tsx", audit.realized_files)
            self.assertIn("src/portal/missing.ts", audit.untouched_expected_files)
            self.assertIn("src/SettlementSimulatorStudio.tsx", audit.unplanned_extra_files)
            self.assertIn("```diff", audit.file_tree_diff)
            self.assertIn("+ src/portal/page.tsx", audit.file_tree_diff)
            self.assertIn("~ src/SettlementSimulatorStudio.tsx", audit.file_tree_diff)
            self.assertIn("! src/portal/missing.ts", audit.file_tree_diff)

            crit_map = {r["id"]: r for r in audit.criteria_rows}
            self.assertIn("AC-01", crit_map)
            self.assertIn("IC-1", crit_map)

            # IC-1, IC-2, IC-3: PR body structure and readability
            for body in (plan.pr_body, plan.show_me_body):
                self.assertIn(f"({len(audit.actual_code_files)} code file(s) changed)", body)
                self.assertIn("### Spec Expectations vs. Realization", body)
                self.assertIn("### Architecture & Call-Stack Flow", body)
                self.assertIn("Page -> Action -> Repository", body)
                self.assertIn("| ID | Spec Expectation | Status | Realized Evidence / Notes |", body)
                self.assertIn("### Examiner 3-Axis Seal", body)
                self.assertIn("<details><summary>📂 Reviewed Artifacts", body)
                self.assertIn(".edge/qa/proofs/portal.json", body)
                self.assertIn("src/a.ts", body)
                self.assertNotIn("/home/oguz/.treehouse/", body)
                self.assertNotIn("/home/oguz/MS-Randevu-monolith/", body)
                self.assertIn("### Live QA Proof & Visual Evidence", body)
                self.assertIn("- **Visited Routes:**", body)
                self.assertIn("<details><summary>⚡ Executed E2E Actions", body)
                self.assertIn("<details><summary>🗄️ Database & State Cross-Check", body)
                self.assertIn('  "portal_items": 3', body)
                self.assertNotIn("urls=['", body)
                self.assertNotIn("actions=['", body)
                self.assertNotIn("db_crosscheck={", body)
                self.assertNotIn("## Merge Danger", body)

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-006 (IC-1 .. IC-4): Development-First PR Topology & Two-Tier Release Flow
    # ------------------------------------------------------------------

    def test_development_first_pr_topology_and_two_tier_release_flow(self):
        import inspect
        import io
        from contextlib import redirect_stdout

        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        # IC-1: Default base_branch must be "development"
        sig_payload = inspect.signature(ship_prep.prepare_ship_payload)
        self.assertEqual(
            sig_payload.parameters["base_branch"].default,
            "development",
            "prepare_ship_payload must default base_branch to 'development'",
        )

        # IC-1: _resolve_base_ref accepts head_branch
        sig_ref = inspect.signature(ship_prep._resolve_base_ref)
        self.assertIn(
            "head_branch",
            sig_ref.parameters,
            "_resolve_base_ref must accept head_branch for remote-first resolution",
        )

        # IC-2: Hard Branch Topology Guard (validate_branch_topology)
        validate_fn = getattr(ship_prep, "validate_branch_topology", None)
        self.assertIsNotNone(
            validate_fn,
            "tools.brigade.ship_prep must define validate_branch_topology",
        )

        ok_split_stg, msg_split_stg = validate_fn("staging", "development", split_branches=True)
        self.assertFalse(ok_split_stg)
        self.assertIn("Branch topology violation", msg_split_stg)

        for slice_branch in (
            "feat/my-slice",
            "fix/bug-1",
            "refactor/core",
            "hotfix/urgent",
            "chore/deps",
            "ship/alpha",
        ):
            ok_slice, msg_slice = validate_fn("staging", slice_branch, split_branches=False)
            self.assertFalse(ok_slice, f"Slice branch {slice_branch} must be blocked from staging")
            self.assertIn("Branch topology violation", msg_slice)

        self.assertEqual(validate_fn("development", "feat/my-slice", split_branches=False), (True, ""))
        self.assertEqual(validate_fn("development", "development", split_branches=True), (True, ""))
        self.assertEqual(validate_fn("staging", "development", split_branches=False), (True, ""))

        # IC-1, IC-2, IC-3: End-to-end Smart Base Resolution, Guard Enforcement, Tier 1 & Tier 2 Flow
        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_path = Path(tmp_root)
            bare_dir = tmp_path / "origin.git"
            repo_dir = tmp_path / "repo"
            local_only_dir = tmp_path / "local_only"
            repo_dir.mkdir(parents=True, exist_ok=True)
            local_only_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

            def git_in(target_dir: Path, *git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=target_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            # Local-only fallback test repo (no origin remote)
            git_in(local_only_dir, "init", "-b", "staging")
            git_in(local_only_dir, "config", "user.email", "brigade@example.com")
            git_in(local_only_dir, "config", "user.name", "Edge Brigade")
            (local_only_dir / "README.md").write_text("# Local\n", encoding="utf-8")
            git_in(local_only_dir, "add", "README.md")
            git_in(local_only_dir, "commit", "-m", "init")
            git_in(local_only_dir, "checkout", "-b", "development")
            self.assertEqual(
                ship_prep._resolve_base_ref(local_only_dir, "development", head_branch="development"),
                "development",
            )
            self.assertEqual(
                ship_prep._resolve_base_ref(local_only_dir, "staging", head_branch="development"),
                "staging",
            )

            # Repo with origin remote
            git_in(repo_dir, "init", "-b", "staging")
            git_in(repo_dir, "config", "user.email", "brigade@example.com")
            git_in(repo_dir, "config", "user.name", "Edge Brigade")
            git_in(repo_dir, "remote", "add", "origin", bare_dir.as_uri())

            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            (repo_dir / "specs").mkdir(parents=True, exist_ok=True)
            (repo_dir / "specs" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
            git_in(repo_dir, "add", "-A")
            git_in(repo_dir, "commit", "-m", "chore: initial staging")
            git_in(repo_dir, "push", "-u", "origin", "staging")

            git_in(repo_dir, "checkout", "-b", "development")
            git_in(repo_dir, "push", "-u", "origin", "development")

            # Add 2 delivered specs on development ahead of origin/development and origin/staging
            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "alpha.md").write_text(
                "---\nexpected_files:\n  - src/alpha.ts\n---\n# Alpha Slice\n\nSummary: Alpha feature.\n",
                encoding="utf-8",
            )
            (arch_dir / "beta.md").write_text(
                "---\nexpected_files:\n  - src/beta.ts\n---\n# Beta Slice\n\nSummary: Beta feature.\n",
                encoding="utf-8",
            )
            (repo_dir / "src").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "alpha.ts").write_text("export const alpha = 1;\n", encoding="utf-8")
            (repo_dir / "src" / "beta.ts").write_text("export const beta = 2;\n", encoding="utf-8")
            git_in(repo_dir, "add", "-A")
            git_in(repo_dir, "commit", "-m", "feat: deliver alpha and beta on development")

            # IC-1: Remote-first base ref resolution
            self.assertEqual(
                ship_prep._resolve_base_ref(repo_dir, "development", head_branch="development"),
                "origin/development",
            )
            self.assertEqual(
                ship_prep._resolve_base_ref(repo_dir, "staging", head_branch="development"),
                "origin/staging",
            )

            # IC-2: Blocked prepare_ship_payload & CLI when staging + split_branches=True
            ok_blk, _, err_blk = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging", split_branches=True
            )
            self.assertFalse(ok_blk)
            self.assertIn("Branch topology violation", err_blk)

            try:
                with patch.object(
                    sys,
                    "argv",
                    ["brigade", "prepare-ship", str(repo_dir), "--base", "staging", "--split-branches"],
                ):
                    rc_blk = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI topology violation should exit 1 cleanly: {exc}")
            self.assertEqual(rc_blk, 1)

            # IC-3 Tier 1: default --base development (no --base flag) works cleanly
            json_tier1_buf = io.StringIO()
            try:
                with patch.object(
                    sys,
                    "argv",
                    ["brigade", "prepare-ship", str(repo_dir), "--split-branches", "--format", "json"],
                ), redirect_stdout(json_tier1_buf):
                    rc_tier1 = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI Tier 1 default '--base development' exited abnormally: {exc}")
            self.assertEqual(rc_tier1, 0)
            tier1_payload = json.loads(json_tier1_buf.getvalue())
            self.assertEqual(tier1_payload["base_branch"], "development")
            self.assertEqual(sorted(tier1_payload["split_branches_created"]), ["ship/alpha", "ship/beta"])
            self.assertIn("gh pr create --base development", tier1_payload["spec_plans"][0]["show_me_body"])

            # IC-3 Tier 2: development -> staging consolidated Release PR (split_branches=False)
            ok_t2, res_t2, err_t2 = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging", split_branches=False
            )
            self.assertTrue(ok_t2, f"Tier 2 development -> staging Release PR should succeed: {err_t2}")
            self.assertIn("gh pr create --base staging --head development", res_t2.show_me_body)
            self.assertIn("## Summary", res_t2.pr_body)
            self.assertIn("## Evidence", res_t2.pr_body)
            self.assertIn("### Included Specs & Realization", res_t2.pr_body)
            self.assertIn("Alpha Slice", res_t2.pr_body)
            self.assertIn("Beta Slice", res_t2.pr_body)

            # IC-2: Slice branch targeting staging directly is blocked
            git_in(repo_dir, "checkout", "-b", "feat/my-slice")
            self.assertEqual(
                ship_prep._resolve_base_ref(repo_dir, "development", head_branch="feat/my-slice"),
                "development",
            )
            ok_slice_blk, _, err_slice_blk = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging"
            )
            self.assertFalse(ok_slice_blk)
            self.assertIn("Branch topology violation", err_slice_blk)

        # IC-4: skills/edge-ship/SKILL.md documents Tier 1, Tier 2, and --base development
        skill_text = (self.repo_root / "skills" / "edge-ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Tier 1", skill_text)
        self.assertIn("Tier 2", skill_text)
        self.assertIn("--base development", skill_text)

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-007 (IC-1 .. IC-5): Tier 2 Route Smoke Scanner, Auto-Triage & Staging Gate
    # ------------------------------------------------------------------

    def test_smoke_routes_discovery_scan_and_auto_triage(self):
        spec = importlib.util.find_spec("tools.brigade.smoke_routes")
        self.assertIsNotNone(spec, "tools.brigade.smoke_routes module must exist")
        smoke_mod = importlib.import_module("tools.brigade.smoke_routes")

        DiscoveredRoute = getattr(smoke_mod, "DiscoveredRoute", None)
        RouteSmokeResult = getattr(smoke_mod, "RouteSmokeResult", None)
        SmokeScanReport = getattr(smoke_mod, "SmokeScanReport", None)
        discover_fn = getattr(smoke_mod, "discover_project_routes", None)
        scan_fn = getattr(smoke_mod, "run_route_smoke_scan", None)
        triage_fn = getattr(smoke_mod, "triage_smoke_failures", None)

        self.assertIsNotNone(DiscoveredRoute, "smoke_routes must define DiscoveredRoute")
        self.assertIsNotNone(RouteSmokeResult, "smoke_routes must define RouteSmokeResult")
        self.assertIsNotNone(SmokeScanReport, "smoke_routes must define SmokeScanReport")
        self.assertIsNotNone(discover_fn, "smoke_routes must define discover_project_routes")
        self.assertIsNotNone(scan_fn, "smoke_routes must define run_route_smoke_scan")
        self.assertIsNotNone(triage_fn, "smoke_routes must define triage_smoke_failures")

        # IC-1: Multi-variant route discovery (Next.js App Router, SvelteKit, specs/INDEX.md, dynamic params)
        with tempfile.TemporaryDirectory() as tmp_disc:
            disc_repo = Path(tmp_disc)
            (disc_repo / "src" / "app" / "(portal)" / "explore").mkdir(parents=True, exist_ok=True)
            (disc_repo / "src" / "app" / "(portal)" / "explore" / "page.tsx").write_text(
                "export default function Explore() { return null; }\n", encoding="utf-8"
            )
            (disc_repo / "src" / "app" / "(portal)" / "stylists" / "[id]").mkdir(parents=True, exist_ok=True)
            (disc_repo / "src" / "app" / "(portal)" / "stylists" / "[id]" / "page.tsx").write_text(
                "export default function Stylist() { return null; }\n", encoding="utf-8"
            )
            (disc_repo / "src" / "app" / "api" / "health").mkdir(parents=True, exist_ok=True)
            (disc_repo / "src" / "app" / "api" / "health" / "route.ts").write_text(
                "export async function GET() { return new Response('ok'); }\n", encoding="utf-8"
            )
            (disc_repo / "src" / "routes" / "dashboard").mkdir(parents=True, exist_ok=True)
            (disc_repo / "src" / "routes" / "dashboard" / "+page.svelte").write_text(
                "<h1>Dashboard</h1>\n", encoding="utf-8"
            )
            (disc_repo / "specs").mkdir(parents=True, exist_ok=True)
            (disc_repo / "specs" / "INDEX.md").write_text(
                "# Navigation Index\n- @route /legacy/report | Page: LegacyReport | Legacy report\n",
                encoding="utf-8",
            )
            proofs_dir = disc_repo / ".edge" / "qa" / "proofs"
            proofs_dir.mkdir(parents=True, exist_ok=True)
            (proofs_dir / "stylists.json").write_text(
                json.dumps({"visited_urls": ["http://localhost:3000/stylists/1744c61b-0001"]}),
                encoding="utf-8",
            )

            routes = discover_fn(disc_repo)
            by_pat = {r.route_pattern: r for r in routes}
            self.assertIn("/explore", by_pat)
            self.assertIn("/stylists/[id]", by_pat)
            self.assertIn("/dashboard", by_pat)
            self.assertIn("/legacy/report", by_pat)
            self.assertFalse(any("/api" in pat or "(portal)" in pat for pat in by_pat))

            self.assertEqual(by_pat["/explore"].framework, "nextjs-app")
            self.assertTrue(by_pat["/stylists/[id]"].is_dynamic)
            self.assertEqual(by_pat["/stylists/[id]"].concrete_url_path, "/stylists/1744c61b-0001")
            self.assertEqual(by_pat["/dashboard"].framework, "sveltekit")
            self.assertTrue(by_pat["/dashboard"].requires_auth)
            self.assertEqual(by_pat["/legacy/report"].framework, "index")

            routes_override = discover_fn(disc_repo, params={"id": "42"})
            by_pat_override = {r.route_pattern: r for r in routes_override}
            self.assertEqual(by_pat_override["/stylists/[id]"].concrete_url_path, "/stylists/42")

        # IC-2 & IC-3: Headless smoke scan with injectable driver_fn + auto-triage
        with tempfile.TemporaryDirectory() as tmp_scan:
            scan_repo = Path(tmp_scan)
            (scan_repo / "src" / "app" / "(portal)" / "explore").mkdir(parents=True, exist_ok=True)
            (scan_repo / "src" / "app" / "(portal)" / "explore" / "page.tsx").write_text(
                "export default function Explore() { return null; }\n", encoding="utf-8"
            )
            (scan_repo / "src" / "routes" / "dashboard").mkdir(parents=True, exist_ok=True)
            (scan_repo / "src" / "routes" / "dashboard" / "+page.svelte").write_text(
                "<h1>Dashboard</h1>\n", encoding="utf-8"
            )

            fsm = BrigadeFSM(scan_repo)
            self.assertEqual(fsm.state.current_state, CycleState.IDLE)
            fsm.save()

            def fake_driver(route, full_url, auth_cookie):
                if route.route_pattern == "/explore":
                    return {
                        "http_status": 200,
                        "final_url": full_url,
                        "console_errors": [],
                        "page_errors": [],
                        "failed_requests": [],
                    }
                return {
                    "http_status": 200,
                    "final_url": full_url,
                    "console_errors": ["TypeError: null"],
                    "page_errors": [],
                    "failed_requests": [],
                }

            report = scan_fn(scan_repo, base_url="http://localhost:3000", driver_fn=fake_driver)
            smoke_file = scan_repo / ".edge" / "qa" / "smoke-routes.json"
            self.assertTrue(smoke_file.is_file(), ".edge/qa/smoke-routes.json must be written")
            self.assertFalse(report.all_navigable)
            self.assertEqual(report.passed_routes, 1)
            self.assertEqual(report.failed_routes, 1)
            self.assertEqual(report.total_console_errors, 1)

            reloaded_report = SmokeScanReport.from_dict(json.loads(smoke_file.read_text(encoding="utf-8")))
            self.assertFalse(reloaded_report.all_navigable)
            self.assertEqual(reloaded_report.failed_routes, 1)

            created_tickets = triage_fn(scan_repo, report)
            self.assertIn("TICK-SMOKE-DASHBOARD", created_tickets)

            ledger_file = scan_repo / ".edge" / "ledger" / "ui.json"
            self.assertTrue(ledger_file.is_file(), ".edge/ledger/ui.json must be written by auto-triage")
            ledger_data = json.loads(ledger_file.read_text(encoding="utf-8"))
            items = ledger_data.get("items", [])
            dash_items = [it for it in items if it.get("ticket_id") == "TICK-SMOKE-DASHBOARD"]
            self.assertEqual(len(dash_items), 1)
            self.assertEqual(dash_items[0].get("severity"), "CRITICAL")
            self.assertEqual(dash_items[0].get("rule_id"), "ROUTE_SMOKE_NAVIGABILITY")

            fsm_after = BrigadeFSM(scan_repo)
            self.assertEqual(fsm_after.state.current_state, CycleState.TRIAGE)
            self.assertIsNotNone(fsm_after.state.active_ticket)
            self.assertEqual(fsm_after.state.active_ticket.ticket_id, "TICK-SMOKE-DASHBOARD")

            # Idempotent re-triage does not duplicate ledger ticket
            triage_fn(scan_repo, report)
            ledger_data_2 = json.loads(ledger_file.read_text(encoding="utf-8"))
            self.assertEqual(
                len([it for it in ledger_data_2.get("items", []) if it.get("ticket_id") == "TICK-SMOKE-DASHBOARD"]),
                1,
            )

        # IC-5: skills/edge-ship/SKILL.md documents smoke-routes and --require-smoke
        skill_text = (self.repo_root / "skills" / "edge-ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("smoke-routes", skill_text)
        self.assertIn("--require-smoke", skill_text)

    def test_tier2_staging_smoke_gate_and_cli_smoke_routes(self):
        import inspect
        import io
        from contextlib import redirect_stdout

        spec = importlib.util.find_spec("tools.brigade.smoke_routes")
        self.assertIsNotNone(spec, "tools.brigade.smoke_routes module must exist")
        self.assertTrue(hasattr(brigade_cli, "cmd_smoke_routes"), "tools.brigade.cli must define cmd_smoke_routes")

        ship_prep = importlib.import_module("tools.brigade.ship_prep")
        sig = inspect.signature(ship_prep.prepare_ship_payload)
        self.assertIn("require_smoke", sig.parameters, "prepare_ship_payload must accept require_smoke")

        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_path = Path(tmp_root)
            bare_dir = tmp_path / "origin.git"
            repo_dir = tmp_path / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")
            git("remote", "add", "origin", bare_dir.as_uri())

            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            (repo_dir / "specs").mkdir(parents=True, exist_ok=True)
            (repo_dir / "specs" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-m", "chore: initial staging")
            git("push", "-u", "origin", "staging")

            git("checkout", "-b", "development")
            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "alpha.md").write_text(
                "---\nexpected_files:\n  - src/alpha.ts\n---\n# Alpha Slice\n\nSummary: Alpha feature.\n",
                encoding="utf-8",
            )
            (repo_dir / "src" / "app" / "explore").mkdir(parents=True, exist_ok=True)
            (repo_dir / "src" / "app" / "explore" / "page.tsx").write_text(
                "export default function Explore() { return null; }\n", encoding="utf-8"
            )
            (repo_dir / "src" / "alpha.ts").write_text("export const alpha = 1;\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-m", "feat: deliver alpha on development")

            # CLI: brigade smoke-routes --discover-only exits 0
            disc_buf = io.StringIO()
            try:
                with patch.object(
                    sys,
                    "argv",
                    ["brigade", "smoke-routes", str(repo_dir), "--discover-only"],
                ), redirect_stdout(disc_buf):
                    rc_disc = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI 'smoke-routes --discover-only' exited abnormally: {exc}")
            self.assertEqual(rc_disc, 0)
            self.assertIn("/explore", disc_buf.getvalue())

            # Case A: require_smoke=True when .edge/qa/smoke-routes.json is missing -> blocked
            ok_missing, _, err_missing = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging", require_smoke=True
            )
            self.assertFalse(ok_missing)
            self.assertIn("Tier 2 staging release blocked", err_missing)

            # Case B: .edge/qa/smoke-routes.json has all_navigable=False -> blocked + auto-triage
            smoke_file = repo_dir / ".edge" / "qa" / "smoke-routes.json"
            smoke_file.parent.mkdir(parents=True, exist_ok=True)
            smoke_file.write_text(
                json.dumps({
                    "schema_version": "1.0.0",
                    "base_url": "http://localhost:3000",
                    "scanned_at": "2026-11-20T00:00:00Z",
                    "total_routes": 2,
                    "passed_routes": 1,
                    "failed_routes": 1,
                    "all_navigable": False,
                    "total_console_errors": 1,
                    "total_page_errors": 0,
                    "triage_tickets_created": [],
                    "results": [
                        {
                            "route_pattern": "/explore",
                            "url": "http://localhost:3000/explore",
                            "source_file": "src/app/explore/page.tsx",
                            "http_status": 200,
                            "final_url": "http://localhost:3000/explore",
                            "auth_redirected": False,
                            "console_errors": [],
                            "page_errors": [],
                            "failed_requests": [],
                            "navigable": True,
                        },
                        {
                            "route_pattern": "/dashboard",
                            "url": "http://localhost:3000/dashboard",
                            "source_file": "src/routes/dashboard/+page.svelte",
                            "http_status": 200,
                            "final_url": "http://localhost:3000/dashboard",
                            "auth_redirected": False,
                            "console_errors": ["TypeError: null"],
                            "page_errors": [],
                            "failed_requests": [],
                            "navigable": False,
                        },
                    ],
                }),
                encoding="utf-8",
            )
            ok_fail, res_fail, err_fail = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging"
            )
            self.assertFalse(ok_fail)
            self.assertIn("Tier 2 staging release blocked", err_fail)
            self.assertTrue((repo_dir / ".edge" / "ledger" / "ui.json").is_file())
            self.assertEqual(BrigadeFSM(repo_dir).state.current_state, CycleState.TRIAGE)

            try:
                with patch.object(
                    sys,
                    "argv",
                    ["brigade", "prepare-ship", str(repo_dir), "--base", "staging"],
                ):
                    rc_fail = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI 'prepare-ship --base staging' with failed smoke must return 1 cleanly: {exc}")
            self.assertEqual(rc_fail, 1)

            # Case C: .edge/qa/smoke-routes.json has all_navigable=True -> passes & embeds Smoke Audit
            smoke_file.write_text(
                json.dumps({
                    "schema_version": "1.0.0",
                    "base_url": "http://localhost:3000",
                    "scanned_at": "2026-11-20T00:05:00Z",
                    "total_routes": 5,
                    "passed_routes": 5,
                    "failed_routes": 0,
                    "all_navigable": True,
                    "total_console_errors": 0,
                    "total_page_errors": 0,
                    "triage_tickets_created": [],
                    "results": [],
                }),
                encoding="utf-8",
            )
            ok_pass, res_pass, err_pass = ship_prep.prepare_ship_payload(
                repo_dir, base_branch="staging", require_smoke=True
            )
            self.assertTrue(ok_pass, f"Tier 2 prepare-ship with clean smoke report should pass: {err_pass}")
            self.assertTrue(hasattr(res_pass, "smoke_report") and res_pass.smoke_report is not None)
            self.assertIn("### Route Navigability & Console Smoke Audit", res_pass.pr_body)
            self.assertIn("5/5 routes navigable · 0 console errors · 0 page errors", res_pass.pr_body)

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-008 (IC-1 .. IC-5): Pre-Staging Perf Telemetry, Two-Tier Auto-Triage & Stage Topology
    # ------------------------------------------------------------------

    def test_smoke_routes_perf_telemetry_two_tier_triage_and_toon_format(self):
        import inspect
        import io
        from contextlib import redirect_stdout

        smoke_mod = importlib.import_module("tools.brigade.smoke_routes")
        format_fn = getattr(smoke_mod, "format_smoke_report", None)
        self.assertIsNotNone(format_fn, "tools.brigade.smoke_routes must define format_smoke_report")

        sig_scan = inspect.signature(smoke_mod.run_route_smoke_scan)
        for param_name in ("settle_budget_ms", "hard_settle_timeout_ms", "heap_budget_mb"):
            self.assertIn(
                param_name,
                sig_scan.parameters,
                f"run_route_smoke_scan must accept {param_name}",
            )

        def fake_driver(route, full_url, auth_cookie):
            if route.route_pattern == "/explore":
                return {
                    "http_status": 200,
                    "final_url": full_url,
                    "console_errors": [],
                    "page_errors": [],
                    "failed_requests": [],
                    "ttfb_ms": 60,
                    "settle_ms": 320,
                    "heap_used_mb": 18.5,
                    "dom_nodes": 350,
                    "spinner_state": "settled",
                }
            if route.route_pattern == "/analytics":
                return {
                    "http_status": 200,
                    "final_url": full_url,
                    "console_errors": [],
                    "page_errors": [],
                    "failed_requests": [],
                    "ttfb_ms": 400,
                    "settle_ms": 2400,
                    "heap_used_mb": 45.0,
                    "dom_nodes": 920,
                    "spinner_state": "settled",
                }
            return {
                "http_status": 200,
                "final_url": full_url,
                "console_errors": [],
                "page_errors": [],
                "failed_requests": [],
                "ttfb_ms": 100,
                "settle_ms": 5000,
                "heap_used_mb": 22.0,
                "dom_nodes": 410,
                "spinner_state": "stuck",
            }

        # IC-1 & IC-2 Sub-case B: /explore (PASS), /analytics (WARN_SLOW), /orders (FAIL_STUCK)
        with tempfile.TemporaryDirectory() as tmp_both:
            both_repo = Path(tmp_both)
            for seg in ("explore", "analytics", "orders"):
                (both_repo / "src" / "app" / seg).mkdir(parents=True, exist_ok=True)
                (both_repo / "src" / "app" / seg / "page.tsx").write_text(
                    "export default function Page() { return null; }\n", encoding="utf-8"
                )
            BrigadeFSM(both_repo).save()

            report = smoke_mod.run_route_smoke_scan(
                both_repo,
                base_url="http://localhost:3000",
                driver_fn=fake_driver,
                settle_budget_ms=1500,
                hard_settle_timeout_ms=5000,
                heap_budget_mb=80.0,
            )
            by_pat = {r.route_pattern: r for r in report.results}

            self.assertEqual(by_pat["/explore"].perf_status, "PASS")
            self.assertTrue(by_pat["/explore"].navigable)
            self.assertEqual(by_pat["/explore"].spinner_state, "settled")
            self.assertEqual(by_pat["/explore"].ttfb_ms, 60)
            self.assertEqual(by_pat["/explore"].settle_ms, 320)
            self.assertEqual(by_pat["/explore"].heap_used_mb, 18.5)
            self.assertEqual(by_pat["/explore"].dom_nodes, 350)

            self.assertEqual(by_pat["/analytics"].spinner_state, "slow_settle")
            self.assertEqual(by_pat["/analytics"].perf_status, "WARN_SLOW")
            self.assertTrue(by_pat["/analytics"].navigable)

            self.assertEqual(by_pat["/orders"].spinner_state, "stuck")
            self.assertEqual(by_pat["/orders"].perf_status, "FAIL_STUCK")
            self.assertFalse(by_pat["/orders"].navigable)

            self.assertEqual(report.slow_routes, 1)
            self.assertEqual(report.stuck_routes, 1)
            self.assertEqual(report.max_settle_ms, 5000)
            self.assertEqual(report.max_heap_mb, 45.0)
            self.assertFalse(report.all_navigable)

            # IC-3: Default TOON ("axi") output format
            toon_out = format_fn(report)
            self.assertTrue(toon_out.startswith("smoke_routes["), f"Expected TOON header, got: {toon_out!r}")
            self.assertIn("budget_ms:1500", toon_out)
            self.assertIn("heap_budget_mb:80.0", toon_out)
            self.assertIn(
                "route | status | settle_ms | ttfb_ms | heap_mb | dom_nodes | spinner | perf | navigable | source",
                toon_out,
            )
            self.assertIn("WARN_SLOW", toon_out)
            self.assertIn("FAIL_STUCK", toon_out)

            # IC-2: CRITICAL TICK-SMOKE-ORDERS takes priority over WARNING TICK-PERF-ANALYTICS
            created_both = smoke_mod.triage_smoke_failures(both_repo, report)
            self.assertIn("TICK-SMOKE-ORDERS", created_both)
            self.assertIn("TICK-PERF-ANALYTICS", created_both)

            ledger_both = json.loads((both_repo / ".edge" / "ledger" / "ui.json").read_text(encoding="utf-8"))
            by_tid = {it["ticket_id"]: it for it in ledger_both.get("items", [])}
            self.assertEqual(by_tid["TICK-SMOKE-ORDERS"]["severity"], "CRITICAL")
            self.assertEqual(by_tid["TICK-PERF-ANALYTICS"]["severity"], "WARNING")
            self.assertEqual(by_tid["TICK-PERF-ANALYTICS"]["rule_id"], "ROUTE_PERF_SLOW_SETTLE")

            fsm_both = BrigadeFSM(both_repo)
            self.assertEqual(fsm_both.state.current_state, CycleState.TRIAGE)
            self.assertIsNotNone(fsm_both.state.active_ticket)
            self.assertEqual(fsm_both.state.active_ticket.ticket_id, "TICK-SMOKE-ORDERS")

            # IC-3 CLI: brigade smoke-routes --format toon --settle-budget-ms 1500 --heap-budget-mb 80
            cli_buf = io.StringIO()
            try:
                with patch.object(smoke_mod, "run_route_smoke_scan", return_value=report), patch.object(
                    sys,
                    "argv",
                    [
                        "brigade",
                        "smoke-routes",
                        str(both_repo),
                        "--format",
                        "toon",
                        "--settle-budget-ms",
                        "1500",
                        "--heap-budget-mb",
                        "80",
                    ],
                ), redirect_stdout(cli_buf):
                    rc_toon = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI 'smoke-routes --format toon --settle-budget-ms 1500 --heap-budget-mb 80' exited abnormally: {exc}")
            self.assertEqual(rc_toon, 1)
            self.assertTrue(cli_buf.getvalue().startswith("smoke_routes["))
            self.assertIn("budget_ms:1500", cli_buf.getvalue())

        # IC-2 Sub-case A: Slow navigable route ONLY (/analytics WARN_SLOW) -> TICK-PERF-ANALYTICS in TRIAGE
        with tempfile.TemporaryDirectory() as tmp_slow:
            slow_repo = Path(tmp_slow)
            (slow_repo / "src" / "app" / "analytics").mkdir(parents=True, exist_ok=True)
            (slow_repo / "src" / "app" / "analytics" / "page.tsx").write_text(
                "export default function Analytics() { return null; }\n", encoding="utf-8"
            )
            BrigadeFSM(slow_repo).save()

            slow_report = smoke_mod.run_route_smoke_scan(
                slow_repo,
                base_url="http://localhost:3000",
                driver_fn=fake_driver,
                settle_budget_ms=1500,
                hard_settle_timeout_ms=5000,
                heap_budget_mb=80.0,
            )
            self.assertTrue(slow_report.all_navigable)
            self.assertEqual(slow_report.slow_routes, 1)

            created_slow = smoke_mod.triage_smoke_failures(slow_repo, slow_report)
            self.assertIn("TICK-PERF-ANALYTICS", created_slow)

            ledger_slow = json.loads((slow_repo / ".edge" / "ledger" / "ui.json").read_text(encoding="utf-8"))
            perf_items = [it for it in ledger_slow.get("items", []) if it.get("ticket_id") == "TICK-PERF-ANALYTICS"]
            self.assertEqual(len(perf_items), 1)
            self.assertEqual(perf_items[0]["severity"], "WARNING")
            self.assertEqual(perf_items[0]["rule_id"], "ROUTE_PERF_SLOW_SETTLE")

            fsm_slow = BrigadeFSM(slow_repo)
            self.assertEqual(fsm_slow.state.current_state, CycleState.TRIAGE)
            self.assertIsNotNone(fsm_slow.state.active_ticket)
            self.assertEqual(fsm_slow.state.active_ticket.ticket_id, "TICK-PERF-ANALYTICS")

    def test_overridable_stage_branch_topology_and_skill_alignment(self):
        import inspect

        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        default_stages = getattr(ship_prep, "DEFAULT_STAGE_BRANCHES", None)
        self.assertIsNotNone(default_stages, "tools.brigade.ship_prep must define DEFAULT_STAGE_BRANCHES")
        self.assertEqual(
            default_stages,
            {"integration": "development", "staging": "staging", "production": "production"},
        )

        resolve_fn = getattr(ship_prep, "resolve_stage_branches", None)
        self.assertIsNotNone(resolve_fn, "tools.brigade.ship_prep must define resolve_stage_branches")

        sig_topo = inspect.signature(ship_prep.validate_branch_topology)
        self.assertIn("allow_override", sig_topo.parameters)
        self.assertIn("stage_branches", sig_topo.parameters)

        sig_prep = inspect.signature(ship_prep.prepare_ship_payload)
        self.assertIn("allow_topology_override", sig_prep.parameters)
        self.assertIn("stage_branches", sig_prep.parameters)

        with tempfile.TemporaryDirectory() as tmp_root:
            repo_dir = Path(tmp_root)
            (repo_dir / ".edge").mkdir(parents=True, exist_ok=True)
            (repo_dir / ".edge" / "brigade.json").write_text(
                json.dumps({
                    "version": "2.0.0",
                    "stage_branches": {"integration": "main", "staging": "pre-prod"},
                }),
                encoding="utf-8",
            )

            resolved_from_cfg = resolve_fn(repo_dir)
            self.assertEqual(
                resolved_from_cfg,
                {"integration": "main", "staging": "pre-prod", "production": "production"},
            )

            resolved_override = resolve_fn(repo_dir, overrides={"staging": "qa-stage"})
            self.assertEqual(
                resolved_override,
                {"integration": "main", "staging": "qa-stage", "production": "production"},
            )

        # allow_override=True permits manual topology bypass
        self.assertEqual(
            ship_prep.validate_branch_topology(
                "staging", "feat/hotfix", split_branches=False, allow_override=True
            ),
            (True, ""),
        )

        # Custom stage_branches enforces topology against custom staging branch and cites custom integration branch
        ok_custom_blk, msg_custom_blk = ship_prep.validate_branch_topology(
            "qa-stage",
            "feat/hotfix",
            split_branches=False,
            allow_override=False,
            stage_branches={"integration": "main", "staging": "qa-stage", "production": "production"},
        )
        self.assertFalse(ok_custom_blk)
        self.assertIn("main", msg_custom_blk)

        # CLI: brigade prepare-ship --allow-topology-override --stage-branch staging=staging
        with tempfile.TemporaryDirectory() as tmp_cli:
            cli_repo = Path(tmp_cli)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=cli_repo,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")
            (cli_repo / "README.md").write_text("# Base\n", encoding="utf-8")
            git("add", "README.md")
            git("commit", "-m", "chore: base staging")

            git("checkout", "-b", "feat/hotfix")
            (cli_repo / "hotfix.ts").write_text("export const fixed = true;\n", encoding="utf-8")
            git("add", "hotfix.ts")
            git("commit", "-m", "fix: hotfix")

            try:
                with patch.object(
                    sys,
                    "argv",
                    [
                        "brigade",
                        "prepare-ship",
                        str(cli_repo),
                        "--base",
                        "staging",
                        "--allow-topology-override",
                        "--stage-branch",
                        "staging=staging",
                    ],
                ):
                    rc_ovr = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI 'prepare-ship --allow-topology-override --stage-branch' exited abnormally: {exc}")
            self.assertEqual(rc_ovr, 0)

        # IC-5: skills/edge-ship/SKILL.md documents TICK-PERF-, --settle-budget-ms, --allow-topology-override, --stage-branch
        skill_text = (self.repo_root / "skills" / "edge-ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("TICK-PERF-", skill_text)
        self.assertIn("--settle-budget-ms", skill_text)
        self.assertIn("--allow-topology-override", skill_text)
        self.assertIn("--stage-branch", skill_text)

    # ------------------------------------------------------------------
    # SPEC-EDGE-BRIGADE-010 (IC-1 .. IC-5): Incremental Security Audit Shared Ledger & Tier 2 Gate
    # ------------------------------------------------------------------

    def test_security_audit_shared_ledger_refutation_toon_and_triage(self):
        spec = importlib.util.find_spec("tools.brigade.security_audit")
        self.assertIsNotNone(spec, "tools.brigade.security_audit module must exist")
        sec_mod = importlib.import_module("tools.brigade.security_audit")

        for sym in (
            "CoverageUnit",
            "CoverageLedger",
            "SecurityTrace",
            "SecurityFinding",
            "SecurityAuditReport",
            "validate_security_artifacts",
            "run_security_audit",
            "triage_security_findings",
            "format_security_report",
        ):
            self.assertIsNotNone(getattr(sec_mod, sym, None), f"tools.brigade.security_audit must define {sym}")

        run_audit = sec_mod.run_security_audit
        validate_fn = sec_mod.validate_security_artifacts
        triage_fn = sec_mod.triage_security_findings
        format_fn = sec_mod.format_security_report
        CoverageLedger = sec_mod.CoverageLedger
        CoverageUnit = sec_mod.CoverageUnit
        SecurityFinding = sec_mod.SecurityFinding

        # IC-1: Shared incremental coverage ledger (.edge/security/coverage-ledger.json) & multi-scope
        with tempfile.TemporaryDirectory() as tmp_ledger:
            repo = Path(tmp_ledger)
            (repo / "src" / "actions").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "core").mkdir(parents=True, exist_ok=True)
            (repo / "src" / "lib").mkdir(parents=True, exist_ok=True)

            orders_ts = repo / "src" / "actions" / "orders.ts"
            orders_ts.write_text(
                '"use server";\n'
                "export async function createOrder(session: any) {\n"
                "    await requireAuth(session);\n"
                "    await db.insert(orders).values({ ok: true });\n"
                "}\n",
                encoding="utf-8",
            )
            (repo / "src" / "core" / "billing.ts").write_text(
                "export function calcTotal(a: number, b: number) { return a + b; }\n",
                encoding="utf-8",
            )
            (repo / "src" / "lib" / "unused.ts").write_text(
                "export const UNUSED = true;\n",
                encoding="utf-8",
            )

            rep1 = run_audit(repo, scopes=["src/actions"])
            self.assertTrue(rep1.passed)
            ledger_file = repo / ".edge" / "security" / "coverage-ledger.json"
            self.assertTrue(ledger_file.is_file(), ".edge/security/coverage-ledger.json must be written")

            units1 = {u["file_path"]: u for u in json.loads(ledger_file.read_text(encoding="utf-8")).get("units", [])}
            self.assertEqual(units1["src/actions/orders.ts"]["status"], "covered")
            self.assertEqual(units1["src/core/billing.ts"]["status"], "out_of_scope")
            self.assertEqual(units1["src/lib/unused.ts"]["status"], "out_of_scope")
            orders_sha1 = units1["src/actions/orders.ts"]["file_sha256"]
            orders_ts1 = units1["src/actions/orders.ts"]["last_audited_at"]

            # Second run targeting src/core preserves unchanged src/actions/orders.ts covered status
            rep2 = run_audit(repo, scopes=["src/core"])
            self.assertTrue(rep2.passed)
            units2 = {u["file_path"]: u for u in json.loads(ledger_file.read_text(encoding="utf-8")).get("units", [])}
            self.assertEqual(units2["src/actions/orders.ts"]["status"], "covered")
            self.assertEqual(units2["src/actions/orders.ts"]["last_audited_at"], orders_ts1)
            self.assertEqual(units2["src/core/billing.ts"]["status"], "covered")
            self.assertEqual(units2["src/lib/unused.ts"]["status"], "out_of_scope")

            # Modifying src/actions/orders.ts triggers automatic re-audit on next scopes=["src/core"] run
            orders_ts.write_text(
                '"use server";\n'
                "export async function wipeOrders() {\n"
                "    await db.delete(orders);\n"
                "}\n",
                encoding="utf-8",
            )
            rep3 = run_audit(repo, scopes=["src/core"])
            units3 = {u["file_path"]: u for u in json.loads(ledger_file.read_text(encoding="utf-8")).get("units", [])}
            self.assertNotEqual(units3["src/actions/orders.ts"]["file_sha256"], orders_sha1)
            self.assertFalse(rep3.passed, "Modified covered file with unguarded db.delete must be re-scanned and fail")
            self.assertGreaterEqual(rep3.confirmed_count, 1)

        # IC-2 & IC-3: 4 attack classes, automated refutation, validate_security_artifacts, TOON & TICK-SEC triage
        with tempfile.TemporaryDirectory() as tmp_scan:
            scan_repo = Path(tmp_scan)
            (scan_repo / "src" / "actions").mkdir(parents=True, exist_ok=True)
            (scan_repo / "src" / "components").mkdir(parents=True, exist_ok=True)

            (scan_repo / "src" / "actions" / "profile.ts").write_text(
                '"use server";\n'
                "export async function updateProfile(session: any) {\n"
                "    await requireAuth(session);\n"
                '    await db.update(users).set({}).where(eq(id, 1));\n'
                "}\n",
                encoding="utf-8",
            )
            (scan_repo / "src" / "components" / "safe.tsx").write_text(
                'import DOMPurify from "dompurify";\n'
                "export function SafeHtml({ html }: { html: string }) {\n"
                "    const clean = DOMPurify.sanitize(html);\n"
                "    return <div dangerouslySetInnerHTML={{ __html: clean }} />;\n"
                "}\n",
                encoding="utf-8",
            )
            (scan_repo / "src" / "actions" / "unsafe.ts").write_text(
                '"use server";\n'
                "export async function dangerAction(id: string) {\n"
                "    await db.delete(orders);\n"
                "    return sql.raw(`SELECT * FROM t WHERE id = ${id}`);\n"
                "}\n",
                encoding="utf-8",
            )

            BrigadeFSM(scan_repo).save()
            report = run_audit(scan_repo, recursive=True)
            self.assertFalse(report.passed)
            self.assertGreaterEqual(report.confirmed_count, 2)
            self.assertGreaterEqual(report.rejected_count, 2)

            rejected_profile = [
                f for f in report.findings
                if f.verdict == "rejected" and "profile.ts" in (f.fix_target or str(f.trace))
            ]
            self.assertTrue(rejected_profile, f"Expected refuted finding for profile.ts, got: {report.findings}")
            for rf in rejected_profile:
                self.assertIsNone(rf.severity)
                self.assertTrue(bool((rf.rejection_reason or "").strip()))

            rejected_safe = [
                f for f in report.findings
                if f.verdict == "rejected" and "safe.tsx" in (f.fix_target or str(f.trace))
            ]
            self.assertTrue(rejected_safe, f"Expected refuted finding for safe.tsx, got: {report.findings}")
            for rf in rejected_safe:
                self.assertIsNone(rf.severity)
                self.assertTrue(bool((rf.rejection_reason or "").strip()))

            confirmed_unsafe = [
                f for f in report.findings
                if f.verdict == "confirmed" and "unsafe.ts" in (f.fix_target or str(f.trace))
            ]
            self.assertGreaterEqual(len(confirmed_unsafe), 2)
            for cf in confirmed_unsafe:
                self.assertIn(cf.severity, ("CRITICAL", "HIGH"))
                self.assertTrue(bool(cf.trace.get("entrypoint")))
                self.assertTrue(bool(cf.trace.get("sink")))

            # validate_security_artifacts check
            ledger_raw = json.loads((scan_repo / ".edge" / "security" / "coverage-ledger.json").read_text(encoding="utf-8"))
            ledger_obj = CoverageLedger(
                version=ledger_raw.get("version", "1.0.0"),
                updated_at=ledger_raw.get("updated_at", ""),
                units=[CoverageUnit(**u) for u in ledger_raw.get("units", [])],
            )
            valid_ok, valid_errs = validate_fn(ledger_obj, report.findings)
            self.assertTrue(valid_ok, f"validate_security_artifacts failed: {valid_errs}")
            self.assertEqual(valid_errs, [])

            bad_finding = SecurityFinding(
                finding_id="F-BAD",
                fingerprint="fp-bad",
                verdict="rejected",
                severity="HIGH",
                attack_class="INJECTION_AND_SINKS",
                boundary="component",
                trace={"entrypoint": "safe.tsx", "propagation": [], "sink": "dangerouslySetInnerHTML"},
                evidence="bad",
                rejection_reason="Refuted",
                fix_target="src/components/safe.tsx",
            )
            bad_ok, bad_errs = validate_fn(ledger_obj, [bad_finding])
            self.assertFalse(bad_ok)
            self.assertTrue(len(bad_errs) >= 1)

            # IC-3: Default TOON output
            toon = format_fn(report)
            self.assertTrue(toon.startswith("security_audit["), f"Expected TOON header, got: {toon!r}")
            self.assertIn("ledger_covered:", toon)
            self.assertIn("id | verdict | severity | attack_class | entrypoint | sink | summary", toon)

            # IC-3: Core triage -> .edge/ledger/core.json + IDLE -> TRIAGE
            triage_tickets = triage_fn(scan_repo, report)
            self.assertTrue(any(tid.startswith("TICK-SEC-") for tid in triage_tickets))

            core_ledger = json.loads((scan_repo / ".edge" / "ledger" / "core.json").read_text(encoding="utf-8"))
            sec_items = [it for it in core_ledger.get("items", []) if str(it.get("ticket_id", "")).startswith("TICK-SEC-")]
            self.assertTrue(sec_items)
            self.assertEqual(sec_items[0].get("rule_id"), "SECURITY_AUDIT_CONFIRMED")

            fsm_after = BrigadeFSM(scan_repo)
            self.assertEqual(fsm_after.state.current_state, CycleState.TRIAGE)
            self.assertIsNotNone(fsm_after.state.active_ticket)
            self.assertTrue(fsm_after.state.active_ticket.ticket_id.startswith("TICK-SEC-"))

        # IC-5: skills/edge-security-audit/SKILL.md & skills/edge-ship/SKILL.md alignment
        sec_skill_path = self.repo_root / "skills" / "edge-security-audit" / "SKILL.md"
        self.assertTrue(sec_skill_path.is_file(), "skills/edge-security-audit/SKILL.md must exist")
        sec_skill_text = sec_skill_path.read_text(encoding="utf-8")
        for tok in ("--scope", "coverage-ledger.json", "confirmed", "rejected"):
            self.assertIn(tok, sec_skill_text)

        ship_skill_text = (self.repo_root / "skills" / "edge-ship" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("security-audit", ship_skill_text)
        self.assertIn("Security & ABAC Audit", ship_skill_text)

    def test_tier2_staging_auto_security_audit_gate_and_cli(self):
        import io
        from contextlib import redirect_stdout

        spec = importlib.util.find_spec("tools.brigade.security_audit")
        self.assertIsNotNone(spec, "tools.brigade.security_audit module must exist")
        self.assertTrue(hasattr(brigade_cli, "cmd_security_audit"), "tools.brigade.cli must define cmd_security_audit")

        ship_prep = importlib.import_module("tools.brigade.ship_prep")

        with tempfile.TemporaryDirectory() as tmp_root:
            tmp_path = Path(tmp_root)
            bare_dir = tmp_path / "origin.git"
            repo_dir = tmp_path / "repo"
            repo_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "--bare", str(bare_dir)], check=True, capture_output=True)

            def git(*git_args):
                proc = subprocess.run(
                    ["git", *git_args],
                    cwd=repo_dir,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                return proc.stdout.strip()

            git("init", "-b", "staging")
            git("config", "user.email", "brigade@example.com")
            git("config", "user.name", "Edge Brigade")
            git("remote", "add", "origin", bare_dir.as_uri())

            (repo_dir / "README.md").write_text("# Base\n", encoding="utf-8")
            (repo_dir / "specs").mkdir(parents=True, exist_ok=True)
            (repo_dir / "specs" / "INDEX.md").write_text("# Index\n", encoding="utf-8")
            git("add", "-A")
            git("commit", "-m", "chore: initial staging")
            git("push", "-u", "origin", "staging")

            git("checkout", "-b", "development")
            arch_dir = repo_dir / ".edge" / "archive" / "specs"
            arch_dir.mkdir(parents=True, exist_ok=True)
            (arch_dir / "orders-sec.md").write_text(
                "---\nexpected_files:\n  - src/actions/unsafe.ts\n---\n# Orders Action\n\nSummary: Orders action.\n",
                encoding="utf-8",
            )
            (repo_dir / "src" / "actions").mkdir(parents=True, exist_ok=True)
            unsafe_ts = repo_dir / "src" / "actions" / "unsafe.ts"
            unsafe_ts.write_text(
                '"use server";\n'
                "export async function wipeOrders() {\n"
                "    await db.delete(orders);\n"
                "}\n",
                encoding="utf-8",
            )
            git("add", "-A")
            git("commit", "-m", "feat: add unsafe server action")

            # Tier 2 prepare-ship automatically blocks on confirmed vulnerability & updates coverage-ledger.json
            ok_blk, res_blk, err_blk = ship_prep.prepare_ship_payload(repo_dir, base_branch="staging")
            self.assertFalse(ok_blk)
            self.assertIn("Tier 2 staging release blocked: Security audit", err_blk)
            self.assertTrue((repo_dir / ".edge" / "security" / "coverage-ledger.json").is_file())
            self.assertTrue(hasattr(res_blk, "security_report") and res_blk.security_report is not None)

            # Fix vulnerability with auth guard + .where() -> Tier 2 passes and embeds Security & ABAC Audit
            unsafe_ts.write_text(
                '"use server";\n'
                "export async function wipeOrders(session: any, id: string) {\n"
                "    await requireAuth(session);\n"
                "    await db.delete(orders).where(eq(orders.id, id));\n"
                "}\n",
                encoding="utf-8",
            )
            git("add", "src/actions/unsafe.ts")
            git("commit", "-m", "fix: add requireAuth and .where() guard")

            ok_pass, res_pass, err_pass = ship_prep.prepare_ship_payload(repo_dir, base_branch="staging")
            self.assertTrue(ok_pass, f"Clean Tier 2 release should pass security audit gate: {err_pass}")
            self.assertTrue(hasattr(res_pass, "security_report") and res_pass.security_report is not None)
            self.assertTrue(res_pass.security_report.get("passed"))
            self.assertIn("### Security & ABAC Audit", res_pass.pr_body)

            # CLI: brigade security-audit <repo> --scope src/actions --format toon
            cli_buf = io.StringIO()
            try:
                with patch.object(
                    sys,
                    "argv",
                    ["brigade", "security-audit", str(repo_dir), "--scope", "src/actions", "--format", "toon"],
                ), redirect_stdout(cli_buf):
                    rc_sec = brigade_cli.main()
            except SystemExit as exc:
                self.fail(f"CLI 'security-audit' exited abnormally: {exc}")
            self.assertEqual(rc_sec, 0)
            self.assertTrue(cli_buf.getvalue().startswith("security_audit["))


if __name__ == "__main__":
    unittest.main()

