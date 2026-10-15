import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tools.gate import EdgeVerificationGate, GateResult


class TestEdgeVerificationGate(unittest.TestCase):
    def setUp(self):
        self.gate = EdgeVerificationGate(Path("/mock/repo"))

    # =========================================================================
    # MigrationGate Tests
    # =========================================================================
    def test_migration_gate_passes_when_no_schema_touched(self):
        self.gate._run_cmd = MagicMock(return_value=(0, "src/actions/appointments.ts\nsrc/lib/appointments/repository.ts\n", ""))
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertTrue(res.passed)
        self.assertIn("preserved", res.message)

    def test_migration_gate_fails_when_schema_touched(self):
        self.gate._run_cmd = MagicMock(return_value=(0, "src/actions/appointments.ts\nsrc/db/schema/appointments.ts\n", ""))
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("MigrationGate VIOLATION", res.message)
        self.assertIn("src/db/schema/appointments.ts", res.details[0])

    def test_migration_gate_fails_when_drizzle_migration_touched(self):
        self.gate._run_cmd = MagicMock(return_value=(0, "drizzle/0002_add_index.sql\n", ""))
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("MigrationGate VIOLATION", res.message)
        self.assertIn("drizzle/0002_add_index.sql", res.details[0])

    def test_migration_gate_handles_windows_path_separators(self):
        self.gate._run_cmd = MagicMock(return_value=(0, "src\\db\\schema\\users.ts\n", ""))
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("MigrationGate VIOLATION", res.message)

    # =========================================================================
    # Net SLOC Budget & Scaffolding Allowance Tests
    # =========================================================================
    def test_net_sloc_passes_when_contracted(self):
        diff_numstat = "10\t40\tsrc/actions/appointments.ts\n"
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_net_sloc_budget("HEAD~1", is_refactor=True)
        self.assertTrue(res.passed)
        self.assertIn("Net SLOC delta: -30", res.message)

    def test_net_sloc_fails_when_inflated_without_scaffolding(self):
        diff_numstat = "40\t10\tsrc/actions/appointments.ts\n"
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_net_sloc_budget("HEAD~1", is_refactor=True, scaffolding_allowance=0)
        self.assertFalse(res.passed)
        self.assertIn("Code inflation detected", res.message)

    def test_net_sloc_passes_within_scaffolding_allowance(self):
        # Net +20 lines, allowance is 25
        diff_numstat = "30\t10\tsrc/lib/appointments/repository.ts\n"
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_net_sloc_budget("HEAD~1", is_refactor=True, scaffolding_allowance=25)
        self.assertTrue(res.passed)
        self.assertIn("Scaffolding allowance used: +20 lines (limit: 25)", res.message)

    def test_net_sloc_fails_when_exceeding_scaffolding_allowance(self):
        # Net +35 lines, allowance is 25
        diff_numstat = "45\t10\tsrc/lib/appointments/repository.ts\n"
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_net_sloc_budget("HEAD~1", is_refactor=True, scaffolding_allowance=25)
        self.assertFalse(res.passed)
        self.assertIn("Code inflation detected", res.message)

    # =========================================================================
    # Target SLOC Contraction Tests
    # =========================================================================
    def test_target_sloc_passes_when_strictly_contracted(self):
        diff_numstat = (
            "10\t45\tsrc/actions/appointments.ts\n"
            "25\t0\tsrc/lib/appointments/repository.ts\n"
        )
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_target_sloc("src/actions/appointments.ts", "HEAD~1")
        self.assertTrue(res.passed)
        self.assertIn("contracted by 35 lines", res.message)

    def test_target_sloc_fails_when_inflated(self):
        diff_numstat = (
            "50\t10\tsrc/actions/appointments.ts\n"
        )
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_target_sloc("src/actions/appointments.ts", "HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("Target file contraction failed", res.message)

    def test_target_sloc_fails_when_neutral(self):
        diff_numstat = (
            "20\t20\tsrc/actions/appointments.ts\n"
        )
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_target_sloc("src/actions/appointments.ts", "HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("Target file contraction failed", res.message)

    def test_target_sloc_fails_when_file_not_modified(self):
        diff_numstat = (
            "10\t45\tsrc/actions/other.ts\n"
        )
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_target_sloc("src/actions/appointments.ts", "HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("was not modified in git diff", res.message)

    def test_target_sloc_normalizes_paths(self):
        diff_numstat = (
            "5\t25\tsrc/actions/appointments.ts\n"
        )
        self.gate._run_cmd = MagicMock(return_value=(0, diff_numstat, ""))
        res = self.gate.check_target_sloc("./src/actions/appointments.ts", "HEAD~1")
        self.assertTrue(res.passed)

    # =========================================================================
    # UI Track Gate Tests (Zero-Wrapper & Domain Purity)
    # =========================================================================
    def test_zero_wrappers_passes_when_no_modified_files(self):
        self.gate._run_cmd = MagicMock(return_value=(0, "", ""))
        res = self.gate.check_zero_wrappers(base_ref="HEAD~1")
        self.assertTrue(res.passed)

    def test_domain_purity_passes_when_no_modified_files(self):
        self.gate._run_cmd = MagicMock(return_value=(0, "", ""))
        res = self.gate.check_domain_purity(base_ref="HEAD~1")
        self.assertTrue(res.passed)
        self.assertIn("UI components are free", res.message)


if __name__ == "__main__":
    unittest.main()
