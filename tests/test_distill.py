#!/usr/bin/env python3
"""
Unit Tests for edge-distill: Pattern & Playbook Miner.
Tests models, extraction logic from mock FSM history, git log/diff,
compiler logs, debt ledger, playbook generation, and CLI interfaces.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Dict
from unittest.mock import patch, MagicMock

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.distill.models import (
    RescueLoop,
    NegativeConstraint,
    DiffPattern,
    DistillReport,
)
from tools.distill.miner import DistillMiner
from tools.distill.generator import PlaybookGenerator
from tools.distill.session_miner import SessionMiner, INTENT_DEFINITIONS, extract_project_from_path
from tools.distill.cli import run_distill, main as distill_main
from tools.brigade.cli import main as brigade_main


class TestDistillModels(unittest.TestCase):
    def test_rescue_loop_serialization(self):
        rl = RescueLoop(
            loop_id="RESCUE-001",
            stage="SURGERY",
            symptom="MigrationGate violation: schema altered",
            root_cause="Surgeon modified schema directly",
            remediation="Revert schema and map in repository",
            rule_enforced="MigrationGate Invariant",
            verification_cmd="git diff --name-only base...HEAD",
            occurred_at="2026-10-05T12:00:00Z",
            resolved_at="2026-10-05T12:05:00Z",
            details={"files": ["src/db/schema/test.ts"]},
        )
        d = rl.to_dict()
        self.assertEqual(d["loop_id"], "RESCUE-001")
        self.assertEqual(d["stage"], "SURGERY")
        self.assertEqual(d["details"]["files"], ["src/db/schema/test.ts"])

        restored = RescueLoop.from_dict(d)
        self.assertEqual(restored.loop_id, "RESCUE-001")
        self.assertEqual(restored.verification_cmd, "git diff --name-only base...HEAD")

    def test_negative_constraint_serialization(self):
        nc = NegativeConstraint(
            constraint_id="NC-RAW-SQL",
            rule_id="RULE-CORE-DB-LEAK",
            title="No raw db queries in controller",
            anti_pattern="Calling db.select() in actions/bookings.ts",
            risk="Couples DB implementation to controller",
            required_pattern="Delegate to domain repository",
            severity="CRITICAL",
            source="ledger",
        )
        d = nc.to_dict()
        self.assertEqual(d["severity"], "CRITICAL")
        self.assertEqual(d["source"], "ledger")

        restored = NegativeConstraint.from_dict(d)
        self.assertEqual(restored.constraint_id, "NC-RAW-SQL")
        self.assertEqual(restored.rule_id, "RULE-CORE-DB-LEAK")

    def test_diff_pattern_serialization(self):
        dp = DiffPattern(
            domain="bookings",
            target_file="src/actions/bookings.ts",
            scaffolded_files=["src/lib/bookings/repository.ts"],
            before_code="const b = await db.select()...",
            after_code="const b = await bookingRepo.find()...",
            description="Extracted repository",
            net_lines=-120,
            target_delta=-200,
        )
        d = dp.to_dict()
        self.assertEqual(d["net_lines"], -120)
        self.assertEqual(d["target_delta"], -200)

        restored = DiffPattern.from_dict(d)
        self.assertEqual(restored.domain, "bookings")
        self.assertEqual(len(restored.scaffolded_files), 1)

    def test_distill_report_serialization(self):
        report = DistillReport(
            domain="customers",
            track="core",
            target_file="src/actions/customers.ts",
            scaffolded_files=["src/lib/customers/repository.ts"],
            base_branch="feat/clean",
            ticket_id="TICK-1234",
            rescue_loops=[
                RescueLoop(
                    loop_id="RL-1",
                    stage="VERIFY",
                    symptom="TS error",
                    root_cause="any type",
                    remediation="explicit type",
                    rule_enforced="Type Safety",
                    verification_cmd="npx tsc",
                )
            ],
            negative_constraints=[
                NegativeConstraint(
                    constraint_id="NC-1",
                    rule_id="RULE-1",
                    title="No any",
                    anti_pattern="as any",
                    risk="unsafe",
                    required_pattern="use Drizzle types",
                )
            ],
            diff_patterns=[
                DiffPattern(
                    domain="customers",
                    target_file="src/actions/customers.ts",
                    before_code="// before",
                    after_code="// after",
                )
            ],
            compiler_fixes=[{"code": "TS2322", "description": "Type mismatch"}],
            test_seams=[{"command": "npm test", "status": "GREEN"}],
            resolved_debt_items=[{"rule_id": "RULE-CORE-DB-LEAK"}],
        )

        d = report.to_dict()
        self.assertEqual(d["domain"], "customers")
        self.assertEqual(len(d["rescue_loops"]), 1)
        self.assertEqual(len(d["negative_constraints"]), 1)
        self.assertEqual(len(d["diff_patterns"]), 1)

        restored = DistillReport.from_dict(d)
        self.assertEqual(restored.ticket_id, "TICK-1234")
        self.assertEqual(restored.rescue_loops[0].loop_id, "RL-1")
        self.assertEqual(restored.negative_constraints[0].constraint_id, "NC-1")


class TestDistillMiner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_distill_")
        self.repo_path = Path(self.temp_dir)
        self.edge_dir = self.repo_path / ".edge"
        self.edge_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_dir = self.edge_dir / "ledger"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir = self.edge_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mine_rescue_loops_from_fsm_history(self):
        # Setup mock .edge/brigade.json with guard failures and recoveries
        state_data = {
            "version": "1.0.0",
            "repo_path": str(self.repo_path),
            "base_branch": "main",
            "active_branch": "refactor/bookings",
            "active_ticket": {
                "ticket_id": "TICK-BOOKINGS-01",
                "track": "core",
                "domain": "bookings",
                "rule_id": "RULE-CORE-DB-LEAK",
                "severity": "CRITICAL",
                "target_file": "src/actions/bookings.ts",
                "line_number": 45,
                "fingerprint": "fp123",
                "description": "Direct DB operations in action",
                "suggested_fix": "Extract to repository",
                "branch_name": "refactor/bookings",
                "test_seam_command": "npx vitest run bookings.test.ts",
                "negative_constraints": ["Do not touch schema"],
            },
            "review_findings": [
                {
                    "axis": "standards",
                    "severity": "CRITICAL",
                    "file_path": "src/actions/bookings.ts",
                    "rule": "coding_standards.md §3",
                    "description": "Index signature tampering [key: string]: any",
                    "suggested_fix": "Use explicit interface",
                    "line_number": 50,
                }
            ],
            "history": [
                {
                    "from_state": "SURGERY",
                    "to_state": "SURGERY",
                    "timestamp": "2026-10-05T10:00:00Z",
                    "success": False,
                    "message": "MigrationGate Invariant VIOLATION: Refactor touched database schemas",
                    "details": {"schema_violations": ["src/db/schema/bookings.ts"]},
                },
                {
                    "from_state": "SURGERY",
                    "to_state": "VERIFY",
                    "timestamp": "2026-10-05T10:05:00Z",
                    "success": True,
                    "message": "Surgery invariants passed",
                    "details": {"target_delta": -120, "total_net": -50},
                },
                {
                    "from_state": "VERIFY",
                    "to_state": "VERIFY",
                    "timestamp": "2026-10-05T10:06:00Z",
                    "success": False,
                    "message": "TypeScript compiler check failed",
                    "details": {"output": "src/actions/bookings.ts:50:5 - error TS2322: Type 'string' is not assignable to type 'number'"},
                },
                {
                    "from_state": "VERIFY",
                    "to_state": "REVIEW",
                    "timestamp": "2026-10-05T10:10:00Z",
                    "success": True,
                    "message": "Verification passed",
                    "details": {},
                },
                {
                    "from_state": "REVIEW",
                    "to_state": "POLISH",
                    "timestamp": "2026-10-05T10:12:00Z",
                    "success": True,
                    "message": "Review flagged 1 critical finding(s)",
                    "details": {"critical_count": 1},
                },
                {
                    "from_state": "POLISH",
                    "to_state": "GATE",
                    "timestamp": "2026-10-05T10:15:00Z",
                    "success": True,
                    "message": "Post-polish verification passed",
                    "details": {},
                },
            ],
        }

        with open(self.edge_dir / "brigade.json", "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        miner = DistillMiner(self.repo_path)
        report = miner.mine(domain="bookings")

        self.assertEqual(report.domain, "bookings")
        self.assertEqual(report.ticket_id, "TICK-BOOKINGS-01")

        # Check rescue loops
        loop_rules = [rl.rule_enforced for rl in report.rescue_loops]
        self.assertTrue(any("MigrationGate" in r for r in loop_rules))
        self.assertTrue(any("TypeScript compiler" in r or "Hermetic" in r for r in loop_rules))
        self.assertTrue(any("Dual-Axis Review" in r for r in loop_rules))

        # Check negative constraints
        constraint_titles = [nc.title for nc in report.negative_constraints]
        self.assertTrue(any("Zero Schema" in t for t in constraint_titles))
        self.assertTrue(any("Direct DB" in t for t in constraint_titles))

    def test_mine_with_ledger_and_compiler_logs(self):
        # Create mock ledger
        ledger_data = {
            "track": "core",
            "health_score": 85.0,
            "items": [
                {
                    "fingerprint": "fp001",
                    "track": "core",
                    "rule_id": "RULE-CORE-DB-LEAK",
                    "title": "Raw SQL leak in customers.ts",
                    "file_path": "src/actions/customers.ts",
                    "line_number": 88,
                    "symbol": "deleteCustomer",
                    "severity": "CRITICAL",
                    "status": "RESOLVED",
                    "details": {},
                    "suggested_fix": "Extract to customers repository",
                    "first_seen_at": "2026-10-05T01:00:00Z",
                    "last_seen_at": "2026-10-05T02:00:00Z",
                    "resolved_at": "2026-10-05T03:00:00Z",
                }
            ],
        }
        with open(self.ledger_dir / "core.json", "w", encoding="utf-8") as f:
            json.dump(ledger_data, f)

        # Create mock tsc.log
        tsc_log_content = "src/actions/customers.ts:88:12 - error TS2339: Property 'id' does not exist on type 'CustomerRecord'.\n"
        with open(self.logs_dir / "tsc.log", "w", encoding="utf-8") as f:
            f.write(tsc_log_content)

        miner = DistillMiner(self.repo_path)
        report = miner.mine(domain="customers")

        self.assertEqual(report.domain, "customers")
        self.assertTrue(len(report.compiler_fixes) > 0)
        self.assertEqual(report.compiler_fixes[0]["code"], "TS2339")
        self.assertTrue(len(report.resolved_debt_items) > 0)
        self.assertEqual(report.resolved_debt_items[0]["rule_id"], "RULE-CORE-DB-LEAK")

    def test_mine_fallback_and_diff_patterns(self):
        # Without git repository, should provide robust domain fallback pattern
        miner = DistillMiner(self.repo_path)
        report = miner.mine(domain="branches")

        self.assertEqual(report.domain, "branches")
        self.assertEqual(len(report.diff_patterns), 1)
        dp = report.diff_patterns[0]
        self.assertIn("createBranch", dp.before_code)
        self.assertIn("branchRepository", dp.after_code)
        self.assertIn("db.transaction", dp.after_code)

    def test_mine_contraction_and_vitest_rescue_loops(self):
        state_data = {
            "version": "1.0.0",
            "repo_path": str(self.repo_path),
            "base_branch": "main",
            "active_ticket": {
                "ticket_id": "TICK-INVENTORY-01",
                "track": "core",
                "domain": "inventory",
                "target_file": "src/actions/inventory.ts",
                "test_seam_command": "npx vitest run inventory.test.ts",
            },
            "history": [
                {
                    "from_state": "SURGERY",
                    "to_state": "SURGERY",
                    "timestamp": "2026-10-05T11:00:00Z",
                    "success": False,
                    "message": "Target Contraction VIOLATION: Target controller failed to shrink",
                    "details": {"target_delta": 45},
                },
                {
                    "from_state": "SURGERY",
                    "to_state": "VERIFY",
                    "timestamp": "2026-10-05T11:05:00Z",
                    "success": True,
                    "message": "Surgery invariants passed",
                    "details": {"target_delta": -80, "total_net": -20},
                },
                {
                    "from_state": "VERIFY",
                    "to_state": "VERIFY",
                    "timestamp": "2026-10-05T11:06:00Z",
                    "success": False,
                    "message": "Characterization test failed (exit code 1)",
                    "details": {"output": "FAIL inventory.test.ts > createItem > AssertionError: expected 200 to be 201"},
                },
                {
                    "from_state": "VERIFY",
                    "to_state": "REVIEW",
                    "timestamp": "2026-10-05T11:10:00Z",
                    "success": True,
                    "message": "Verification passed",
                    "details": {},
                },
            ],
        }
        with open(self.edge_dir / "brigade.json", "w", encoding="utf-8") as f:
            json.dump(state_data, f)

        miner = DistillMiner(self.repo_path)
        report = miner.mine(domain="inventory")

        self.assertEqual(report.domain, "inventory")
        loop_rules = [rl.rule_enforced for rl in report.rescue_loops]
        self.assertTrue(any("Target Contraction Gate" in r for r in loop_rules))
        self.assertTrue(any("Characterization Test Invariant" in r for r in loop_rules))

    def test_mine_with_mocked_git_diff(self):
        mock_diff = """diff --git a/src/actions/bookings.ts b/src/actions/bookings.ts
--- a/src/actions/bookings.ts
+++ b/src/actions/bookings.ts
@@ -10,15 +10,5 @@
-export async function deleteBooking(id: string) {
-  const res = await db.delete(bookingsTable).where(eq(bookingsTable.id, id));
-  return res;
-}
+export async function deleteBooking(id: string) {
+  return await bookingRepository.delete(id);
+}
"""
        mock_numstat = "5\t15\tsrc/actions/bookings.ts\n25\t0\tsrc/lib/bookings/repository.ts"

        miner = DistillMiner(self.repo_path)
        with patch.object(miner, "_run_git") as mock_git:
            def side_effect(args):
                if "--numstat" in args:
                    return 0, mock_numstat, ""
                elif "diff" in args:
                    return 0, mock_diff, ""
                return 0, "", ""
            mock_git.side_effect = side_effect

            report = miner.mine(domain="bookings")
            self.assertEqual(len(report.diff_patterns), 1)
            dp = report.diff_patterns[0]
            self.assertIn("db.delete", dp.before_code)
            self.assertIn("bookingRepository.delete", dp.after_code)
            self.assertEqual(dp.target_delta, -10)
            self.assertEqual(dp.net_lines, 15)


class TestPlaybookGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_generator_")
        self.repo_path = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_generate_playbook_markdown(self):
        report = DistillReport(
            domain="bookings",
            track="core",
            target_file="src/actions/bookings.ts",
            scaffolded_files=["src/lib/bookings/repository.ts"],
            base_branch="feat/nextjs-clean-monolith",
            ticket_id="TICK-BOOKINGS-99",
            rescue_loops=[
                RescueLoop(
                    loop_id="RESCUE-01",
                    stage="SURGERY",
                    symptom="MigrationGate violation",
                    root_cause="Schema file touched",
                    remediation="Reverted schema",
                    rule_enforced="MigrationGate Invariant",
                    verification_cmd="git diff --name-only base...HEAD",
                )
            ],
            negative_constraints=[
                NegativeConstraint(
                    constraint_id="NC-01",
                    rule_id="RULE-DB-LEAK",
                    title="No DB operations in action",
                    anti_pattern="Calling db.select() in actions",
                    risk="Coupling",
                    required_pattern="Delegate to repository",
                    severity="CRITICAL",
                )
            ],
            diff_patterns=[
                DiffPattern(
                    domain="bookings",
                    target_file="src/actions/bookings.ts",
                    before_code="export async function createBooking() { db.select(); }",
                    after_code="export async function createBooking() { repo.create(); }",
                    description="Extracted repo",
                    target_delta=-150,
                    net_lines=-80,
                )
            ],
            compiler_fixes=[{"code": "TS2322", "description": "Type mismatch in booking status"}],
            test_seams=[{"command": "npm run test:unit -- bookings", "status": "GREEN"}],
        )

        generator = PlaybookGenerator(self.repo_path)
        out_file = generator.generate(report)

        self.assertTrue(out_file.exists())
        self.assertEqual(out_file.name, "bookings-playbook.md")

        content = out_file.read_text(encoding="utf-8")

        # Assert GitHub markdown callout boxes
        self.assertIn("> [!NOTE]", content)
        self.assertIn("> [!CAUTION]", content)
        self.assertIn("> [!IMPORTANT]", content)
        self.assertIn("> [!TIP]", content)

        # Assert sections
        self.assertIn("# 📖 Operational Playbook: Bookings Domain Architecture & Refactoring Recipes", content)
        self.assertIn("## 🧭 1. Domain Profili ve Veri İzi Bağlamı", content)
        self.assertIn("## 🚫 2. Negatif Kısıtlar Kütüğü", content)
        self.assertIn("## 🔄 3. Yapısal Dönüşüm Şablonu", content)
        self.assertIn("## 🛟 4. Kurtarma Döngüleri ve İyileştirme Reçeteleri", content)
        self.assertIn("## 🧪 5. Hermetik Doğrulama ve Test Seam Reçetesi", content)
        self.assertIn("## ✅ 6. Operasyonel Kontrol Listesi", content)

        # Assert checklists and terminal commands
        self.assertIn("- [ ] **MigrationGate Invariant:**", content)
        self.assertIn("- [ ] **Hedef Kapsam Daralması:**", content)
        self.assertIn("git diff --name-only feat/nextjs-clean-monolith...HEAD", content)
        self.assertIn("npx tsc --noEmit", content)
        self.assertIn("python tools/gate.py .", content)


class TestDistillCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_cli_")
        self.repo_path = Path(self.temp_dir)
        self.edge_dir = self.repo_path / ".edge"
        self.edge_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_run_distill_function(self):
        code = run_distill(self.repo_path, domain="pricing", track="core")
        self.assertEqual(code, 0)
        expected_playbook = self.repo_path / "rules" / "playbooks" / "generated" / "pricing-playbook.md"
        self.assertTrue(expected_playbook.exists())

    def test_distill_standalone_cli(self):
        test_args = ["edge-distill", str(self.repo_path), "--domain", "payments"]
        with patch.object(sys, "argv", test_args):
            code = distill_main()
            self.assertEqual(code, 0)

    def test_custom_output_path(self):
        custom_out = self.repo_path / "custom" / "my-domain-playbook.md"
        test_args = ["edge-distill", str(self.repo_path), "--domain", "analytics", "--output", str(custom_out)]
        with patch.object(sys, "argv", test_args):
            code = distill_main()
            self.assertEqual(code, 0)
        self.assertTrue(custom_out.exists())

    def test_brigade_distill_subcommand(self):
        test_args = ["brigade", "distill", str(self.repo_path), "--domain", "customers"]
        with patch.object(sys, "argv", test_args):
            code = brigade_main()
            self.assertEqual(code, 0)

        expected_playbook = self.repo_path / "rules" / "playbooks" / "generated" / "customers-playbook.md"
        self.assertTrue(expected_playbook.exists())

    def test_journal_lifecycle(self):
        from tools.distill.journal import DistillJournal
        journal_mgr = DistillJournal(self.repo_path)
        session = journal_mgr.start_session(goal="Fix divergent booking feature", operational_domain="reconcile")
        self.assertEqual(session.status, "RECORDING")
        self.assertEqual(session.operational_domain, "reconcile")
        self.assertEqual(len(session.journal_entries), 1)

        # Log a step
        entry = journal_mgr.log_step("Created characterization test seam", tag="SEAM_CREATION")
        self.assertEqual(entry.tag, "SEAM_CREATION")
        active = journal_mgr.get_active_session()
        self.assertEqual(len(active.journal_entries), 2)

        # Resolve session
        resolved = journal_mgr.resolve_session(resolution_notes="Synchronized API and Core")
        self.assertEqual(resolved.status, "RESOLVED")
        self.assertIsNotNone(resolved.resolved_at)

    def test_mine_and_generate_proposal(self):
        from tools.distill.journal import DistillJournal
        journal_mgr = DistillJournal(self.repo_path)
        journal_mgr.start_session(goal="Harmonize orders feature", operational_domain="reconcile")
        journal_mgr.log_step("Found two-headed implementation", tag="OBSERVATION")
        journal_mgr.log_step("Wrote missing seam in tests/unit/orders", tag="SEAM_CREATION")
        journal_mgr.log_step("Unified behavior in ordersRepository", tag="BEHAVIOR_SYNC")
        journal_mgr.log_step("Fixed transaction isolation bug", tag="BUG_FIX")
        journal_mgr.resolve_session("Problem resolved and verified")

        miner = DistillMiner(self.repo_path)
        proposal = miner.mine_session_proposal()

        self.assertEqual(proposal.domain_name, "reconcile")
        self.assertTrue(len(proposal.chronological_steps) >= 5)
        self.assertIn("RECONCILE", proposal.title)

        generator = PlaybookGenerator(self.repo_path)
        out_file = generator.generate_proposal(proposal)

        self.assertTrue(out_file.exists())
        self.assertEqual(out_file.name, "reconcile-domain-proposal.md")
        content = out_file.read_text(encoding="utf-8")
        self.assertIn("# 📜 Operational Playbook Proposal: `RECONCILE` Domain Protocol", content)
        self.assertIn("## 🚨 1. Kriz Arketipi & İki Başlı Yapı Analizi", content)
        self.assertIn("## ⏱️ 2. Kronolojik Kara Kutu Günlüğü", content)
        self.assertIn("## 🪡 3. Eksik Dikiş İnşası ve Senkronizasyon Reçetesi", content)
        self.assertIn("- [x] Eksik test dikişleri", content)

    def test_distill_cli_flight_recorder_workflow(self):
        # 1. Start session
        with patch.object(sys, "argv", ["edge-distill", "start", str(self.repo_path), "--goal", "Crisis fix", "--domain", "reconcile"]):
            code = distill_main()
            self.assertEqual(code, 0)

        # 2. Log step
        with patch.object(sys, "argv", ["edge-distill", "log", str(self.repo_path), "--step", "Added test seam", "--tag", "SEAM_CREATION"]):
            code = distill_main()
            self.assertEqual(code, 0)

        # 3. Status
        with patch.object(sys, "argv", ["edge-distill", "status", str(self.repo_path)]):
            code = distill_main()
            self.assertEqual(code, 0)

        # 4. Resolve
        with patch.object(sys, "argv", ["edge-distill", "resolve", str(self.repo_path), "--notes", "Solved"]):
            code = distill_main()
            self.assertEqual(code, 0)

        # 5. Propose
        with patch.object(sys, "argv", ["edge-distill", "propose", str(self.repo_path)]):
            code = distill_main()
            self.assertEqual(code, 0)

        expected_proposal = self.repo_path / "rules" / "playbooks" / "proposals" / "reconcile-domain-proposal.md"
        self.assertTrue(expected_proposal.exists())

    def test_brigade_distill_flight_recorder_actions(self):
        # Start via brigade
        with patch.object(sys, "argv", ["brigade", "distill", str(self.repo_path), "--action", "start", "--goal", "Sync dual heads"]):
            code = brigade_main()
            self.assertEqual(code, 0)

        # Log via brigade
        with patch.object(sys, "argv", ["brigade", "distill", str(self.repo_path), "--action", "log", "--step", "Step via brigade", "--tag", "BEHAVIOR_SYNC"]):
            code = brigade_main()
            self.assertEqual(code, 0)

        # Resolve via brigade
        with patch.object(sys, "argv", ["brigade", "distill", str(self.repo_path), "--action", "resolve", "--notes", "Resolved via brigade"]):
            code = brigade_main()
            self.assertEqual(code, 0)

        # Propose via brigade
        with patch.object(sys, "argv", ["brigade", "distill", str(self.repo_path), "--action", "propose"]):
            code = brigade_main()
            self.assertEqual(code, 0)

    def test_nonexistent_repo_error(self):
        nonexistent = self.repo_path / "does_not_exist"
        test_args = ["edge-distill", "run", str(nonexistent)]
        with patch.object(sys, "argv", test_args):
            code = distill_main()
            self.assertEqual(code, 1)


class TestSessionMiner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_distill_miner_")
        self.brain_root = Path(self.temp_dir) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(self.temp_dir) / "mock_repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session(self, conv_id: str, lines: Any) -> Path:
        sess_dir = self.brain_root / conv_id / ".system_generated" / "logs"
        sess_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = sess_dir / "transcript.jsonl"
        with open(transcript_path, "w", encoding="utf-8") as f:
            for item in lines:
                if isinstance(item, str):
                    f.write(item + "\n")
                else:
                    f.write(json.dumps(item) + "\n")
        return transcript_path

    def test_zero_crash_streaming_and_malformed_json(self):
        lines = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z", "content": "Proje için plan yapalım"},
            "{malformed json line",
            "",
            "   ",
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-13T10:05:00Z", "tool_calls": [{"name": "run_command", "args": {"Cwd": "C:\\Users\\oguz_\\.gemini\\config\\plugins\\edge"}}]},
            "12345",  # valid JSON but not a dict
            '{"step_index": 2, truncated line...',
            {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:15:00Z", "content": "Teşekkürler"},
        ]
        tpath = self._create_session("sess-malformed", lines)
        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        parsed = miner.parse_transcript(tpath)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["conversation_id"], "sess-malformed")
        self.assertEqual(parsed["total_steps"], 3)  # Only 3 valid dict steps
        self.assertEqual(parsed["human_turns"], 2)
        self.assertEqual(parsed["duration_minutes"], 15)
        self.assertEqual(parsed["project"], "edge")

    def test_project_classification_hierarchy(self):
        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)

        # 1. Priority 1: workspaceUris wins over tool call args
        tpath1 = self._create_session("sess-ws", [
            {"step_index": 0, "workspaceUris": ["file:///c:/Users/oguz_/.gemini/config/plugins/edge"], "created_at": "2026-10-13T10:00:00Z"},
            {"step_index": 1, "tool_calls": [{"name": "run_command", "args": {"Cwd": "/home/oguz/MS-Randevu-monolith"}}]},
        ])
        p1 = miner.parse_transcript(tpath1)
        self.assertEqual(p1["project"], "edge")

        # 2. Priority 2: No workspaceUris, tool call arguments determine project
        tpath2 = self._create_session("sess-tools", [
            {"step_index": 0, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "cd /home/oguz/MS-Randevu-monolith && pytest"}}]},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/home/oguz/MS-Randevu-monolith/src/main.ts"}}]},
        ])
        p2 = miner.parse_transcript(tpath2)
        self.assertEqual(p2["project"], "MS-Randevu-monolith")

        # 3. Priority 3: Only internal brain scratch paths -> UNASSIGNED / SCRATCH
        tpath3 = self._create_session("sess-scratch", [
            {"step_index": 0, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "C:\\Users\\oguz_\\.gemini\\antigravity\\brain\\abc\\plan.md"}}]},
        ])
        p3 = miner.parse_transcript(tpath3)
        self.assertEqual(p3["project"], "UNASSIGNED / SCRATCH")

    def test_chronological_ordering(self):
        # Create 3 sessions for same project with disordered start timestamps
        self._create_session("sess-late", [
            {"step_index": 0, "source": "USER_EXPLICIT", "created_at": "2026-10-14T12:00:00Z", "content": "Late session"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])
        self._create_session("sess-early", [
            {"step_index": 0, "source": "USER_EXPLICIT", "created_at": "2026-10-10T08:00:00Z", "content": "Early session"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])
        self._create_session("sess-middle", [
            {"step_index": 0, "source": "USER_EXPLICIT", "created_at": "2026-10-12T10:00:00Z", "content": "Middle session"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])

        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        data = miner.mine_sessions()

        self.assertIn("edge", data["projects"])
        sessions = data["projects"]["edge"]["sessions"]
        self.assertEqual(len(sessions), 3)

        # Check chronological order
        ordered_ids = [s["conversation_id"] for s in sessions]
        self.assertEqual(ordered_ids, ["sess-early", "sess-middle", "sess-late"])
        self.assertTrue(sessions[0]["start_time"] < sessions[1]["start_time"] < sessions[2]["start_time"])

    def test_intent_detection_and_clustering(self):
        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)

        # Human messages targeting all 5 intents
        lines = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z",
             "content": "Balon penceresini temiz tutmak adına bu görevi alt ajan ile çöz, bağlam boğulmasın."},
            {"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:05:00Z",
             "content": "Uçtan uca dikey dilim istiyorum, sadece db katmanı yazıp bırakma."},
            {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:10:00Z",
             "content": "Feathers dikiş yeri aç, repository interface sözleşme kur."},
            {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:15:00Z",
             "content": "Önce test yazılmalı, kırmızı test olmadan koda dokunma, testi bozma hile yapma."},
            {"step_index": 4, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:20:00Z",
             "content": "Arayüz için lavish prototip hazırla ve görsel olarak bana göster."},
            # Model message should NOT trigger intent detection
            {"step_index": 5, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-13T10:25:00Z",
             "content": "Anladım, balon pencereni temiz tutuyorum ve lavish ile görsel arayüzü açıyorum."},
            {"step_index": 6, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/code-manor/SKILL.md"}}]},
        ]
        tpath = self._create_session("sess-intents", lines)
        parsed = miner.parse_transcript(tpath)

        expected_intents = ["Context Hygiene", "Seam & Contracts", "Test Immutability", "Vertical Slice", "Visual Gate"]
        self.assertEqual(parsed["detected_intents"], expected_intents)
        self.assertTrue(len(parsed["quotes_by_intent"]) == 5)
        self.assertIn("temiz tutmak", parsed["quotes_by_intent"]["Context Hygiene"].lower())
        self.assertIn("dikey dilim", parsed["quotes_by_intent"]["Vertical Slice"].lower())

    def test_json_output_schema_and_persistence(self):
        self._create_session("sess-1", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z", "content": "Balon pencereni temiz tut alt ajan delege et."},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])

        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        data = miner.mine_sessions()

        self.assertIn("generated_at", data)
        self.assertEqual(data["total_sessions"], 1)
        self.assertIn("projects", data)
        self.assertIn("edge", data["projects"])
        self.assertEqual(data["projects"]["edge"]["session_count"], 1)

        sess_obj = data["projects"]["edge"]["sessions"][0]
        self.assertEqual(sess_obj["conversation_id"], "sess-1")
        self.assertIn("Context Hygiene", sess_obj["detected_intents"])

        self.assertIn("intent_summary", data)
        for intent_name in INTENT_DEFINITIONS.keys():
            self.assertIn(intent_name, data["intent_summary"])
            self.assertIn("session_frequency", data["intent_summary"][intent_name])
            self.assertIn("sample_quote", data["intent_summary"][intent_name])

        self.assertEqual(data["intent_summary"]["Context Hygiene"]["session_frequency"], 1)
        self.assertTrue(len(data["intent_summary"]["Context Hygiene"]["sample_quote"]) > 0)

        # Test save
        out_file = miner.save_sessions_json(data)
        self.assertTrue(out_file.exists())
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["total_sessions"], 1)

    def test_cli_sessions_and_intents_commands(self):
        self._create_session("sess-cli", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z", "content": "Görsel arayüz için lavish prototip hazırla"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])

        custom_json = self.repo_dir / "custom_sessions.json"

        # 1. edge-distill sessions
        with patch.object(sys, "argv", [
            "edge-distill", "sessions", str(self.repo_dir),
            "--brain-roots", str(self.brain_root),
            "--output", str(custom_json)
        ]):
            code = distill_main()
            self.assertEqual(code, 0)
            self.assertTrue(custom_json.exists())

        # 2. edge-distill sessions --by-project
        with patch.object(sys, "argv", [
            "edge-distill", "sessions", str(self.repo_dir),
            "--by-project",
            "--brain-roots", str(self.brain_root),
            "--output", str(custom_json)
        ]):
            code = distill_main()
            self.assertEqual(code, 0)

        # 3. edge-distill intents
        with patch.object(sys, "argv", [
            "edge-distill", "intents", str(self.repo_dir),
            "--brain-roots", str(self.brain_root),
            "--output", str(custom_json)
        ]):
            code = distill_main()
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
