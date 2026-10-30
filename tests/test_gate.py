import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tools.gate as gate_mod
from tools.gate import EdgeVerificationGate, GateResult, _compute_source_max_cc


def _build_ts_function_with_cc(func_name: str, target_cc: int) -> str:
    """
    Deterministically builds a TypeScript function with exact cyclomatic complexity `target_cc`.
    Base complexity is 1; each `if (val === i)` adds +1 in both tree-sitter AST and fallback mode.
    """
    branches = max(0, target_cc - 1)
    lines = [
        f"export function {func_name}(val: number): number {{",
        "    let total = 0;",
    ]
    for i in range(branches):
        lines.append(f"    if (val === {i}) {{")
        lines.append(f"        total += {i + 1};")
        lines.append("    }")
    lines.append("    return total;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _build_py_function_with_cc(func_name: str, target_cc: int) -> str:
    """Deterministically builds a Python function with exact cyclomatic complexity `target_cc`."""
    branches = max(0, target_cc - 1)
    lines = [
        f"def {func_name}(val: int) -> int:",
        "    total = 0",
    ]
    for i in range(branches):
        lines.append(f"    if val == {i}:")
        lines.append(f"        total += {i + 1}")
    lines.append("    return total")
    return "\n".join(lines) + "\n"


class _HermeticGitRepoTestCase(unittest.TestCase):
    """Base fixture initializing a real isolated git repository inside TemporaryDirectory."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo_path = Path(self._tmp.name)
        self._git("init")
        self._git("config", "user.email", "surgeon@edge.local")
        self._git("config", "user.name", "Edge Surgeon Test")
        self.gate = EdgeVerificationGate(self.repo_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_and_commit(self, files: dict[str, str], msg: str) -> None:
        for rel_path, content in files.items():
            full = self.repo_path / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        self._git("add", "-A")
        self._git("commit", "--no-gpg-sign", "-m", msg)


class TestEdgeVerificationGateMocked(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = EdgeVerificationGate(Path("/mock/repo"))

    # =========================================================================
    # MigrationGate Tests
    # =========================================================================
    def test_migration_gate_passes_when_no_schema_touched(self) -> None:
        self.gate._run_cmd = MagicMock(
            return_value=(0, "src/actions/appointments.ts\nsrc/lib/appointments/repository.ts\n", "")
        )
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertTrue(res.passed)
        self.assertIn("preserved", res.message)

    def test_migration_gate_fails_when_schema_touched(self) -> None:
        self.gate._run_cmd = MagicMock(
            return_value=(0, "src/actions/appointments.ts\nsrc/db/schema/appointments.ts\n", "")
        )
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("MigrationGate VIOLATION", res.message)
        self.assertIn("src/db/schema/appointments.ts", res.details[0])

    def test_migration_gate_fails_when_drizzle_migration_touched(self) -> None:
        self.gate._run_cmd = MagicMock(return_value=(0, "drizzle/0002_add_index.sql\n", ""))
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("MigrationGate VIOLATION", res.message)
        self.assertIn("drizzle/0002_add_index.sql", res.details[0])

    def test_migration_gate_handles_windows_path_separators(self) -> None:
        self.gate._run_cmd = MagicMock(return_value=(0, "src\\db\\schema\\users.ts\n", ""))
        res = self.gate.check_migration_gate("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("MigrationGate VIOLATION", res.message)

    # =========================================================================
    # UI Track Gate Tests (Zero-Wrapper & Domain Purity)
    # =========================================================================
    def test_zero_wrappers_passes_when_no_modified_files(self) -> None:
        self.gate._run_cmd = MagicMock(return_value=(0, "", ""))
        res = self.gate.check_zero_wrappers(base_ref="HEAD~1")
        self.assertTrue(res.passed)

    def test_domain_purity_passes_when_no_modified_files(self) -> None:
        self.gate._run_cmd = MagicMock(return_value=(0, "", ""))
        res = self.gate.check_domain_purity(base_ref="HEAD~1")
        self.assertTrue(res.passed)
        self.assertIn("UI components are free", res.message)

    # =========================================================================
    # _compute_source_max_cc AST & Fallback Parity Tests
    # =========================================================================
    def test_compute_source_max_cc_ts_and_py_with_and_without_treesitter(self) -> None:
        ts_src = (
            _build_ts_function_with_cc("lowHelper", 3)
            + "\n"
            + _build_ts_function_with_cc("heavyDispatcher", 12)
        )
        py_src = (
            _build_py_function_with_cc("small_fn", 2)
            + "\n"
            + _build_py_function_with_cc("complex_pipeline", 11)
        )

        cc_ts, sym_ts = _compute_source_max_cc(ts_src, ".ts")
        self.assertEqual(cc_ts, 12)
        self.assertEqual(sym_ts, "heavyDispatcher")

        cc_py, sym_py = _compute_source_max_cc(py_src, ".py")
        self.assertEqual(cc_py, 11)
        self.assertEqual(sym_py, "complex_pipeline")

        # Explicitly verify deterministic fallback when tree-sitter is unavailable
        with patch.object(gate_mod, "TREE_SITTER_AVAILABLE", False):
            fb_cc_ts, fb_sym_ts = _compute_source_max_cc(ts_src, ".ts")
            self.assertEqual(fb_cc_ts, 12)
            self.assertEqual(fb_sym_ts, "heavyDispatcher")

            fb_cc_py, fb_sym_py = _compute_source_max_cc(py_src, ".py")
            self.assertEqual(fb_cc_py, 11)
            self.assertEqual(fb_sym_py, "complex_pipeline")


class TestComplexityNonRegressionGate(_HermeticGitRepoTestCase):
    def test_hotspot_cc_decrease_passes(self) -> None:
        """Existing hotspot (CC=15 > 10) refactored down to CC=12 (<= 15) MUST PASS."""
        self._write_and_commit(
            {"src/core/hotspot.ts": _build_ts_function_with_cc("legacyHotspot", 15)},
            "chore: baseline hotspot CC=15",
        )
        self._write_and_commit(
            {"src/core/hotspot.ts": _build_ts_function_with_cc("legacyHotspot", 12)},
            "refactor: reduce hotspot CC to 12",
        )

        res = self.gate.check_complexity_non_regression("HEAD~1", healthy_cc_ceiling=10)
        self.assertTrue(res.passed, msg=str(res))

    def test_hotspot_cc_increase_fails(self) -> None:
        """Existing hotspot (CC=14) worsening to CC=16 MUST FAIL with file, symbol, and 14 -> 16."""
        self._write_and_commit(
            {"src/core/hotspot.ts": _build_ts_function_with_cc("legacyHotspot", 14)},
            "chore: baseline hotspot CC=14",
        )
        self._write_and_commit(
            {"src/core/hotspot.ts": _build_ts_function_with_cc("legacyHotspot", 16)},
            "feat: inflate hotspot CC to 16",
        )

        res = self.gate.check_complexity_non_regression("HEAD~1", healthy_cc_ceiling=10)
        self.assertFalse(res.passed)
        joined = "\n".join(res.details)
        self.assertIn("src/core/hotspot.ts", joined)
        self.assertIn("legacyHotspot", joined)
        self.assertIn("14 -> 16", joined)

    def test_clean_file_within_healthy_ceiling_passes(self) -> None:
        """Existing clean file (CC=2) growing up to CC=10 MUST PASS."""
        self._write_and_commit(
            {"src/core/pricing.ts": _build_ts_function_with_cc("calcPrice", 2)},
            "chore: baseline clean file CC=2",
        )
        self._write_and_commit(
            {"src/core/pricing.ts": _build_ts_function_with_cc("calcPrice", 10)},
            "feat: add rules up to CC=10",
        )

        res = self.gate.check_complexity_non_regression("HEAD~1", healthy_cc_ceiling=10)
        self.assertTrue(res.passed, msg=str(res))

    def test_clean_file_exceeding_healthy_ceiling_fails(self) -> None:
        """Existing clean file (CC=2) growing to CC=12 (> 10) MUST FAIL."""
        self._write_and_commit(
            {"src/core/pricing.ts": _build_ts_function_with_cc("calcPrice", 2)},
            "chore: baseline clean file CC=2",
        )
        self._write_and_commit(
            {"src/core/pricing.ts": _build_ts_function_with_cc("calcPrice", 12)},
            "feat: bloat calcPrice to CC=12",
        )

        res = self.gate.check_complexity_non_regression("HEAD~1", healthy_cc_ceiling=10)
        self.assertFalse(res.passed)
        joined = "\n".join(res.details)
        self.assertIn("src/core/pricing.ts", joined)
        self.assertIn("calcPrice", joined)
        self.assertIn("2 -> 12", joined)

    def test_new_file_exceeding_healthy_ceiling_fails(self) -> None:
        """Newly created production file with CC=13 (> 10) MUST FAIL."""
        self._write_and_commit(
            {"README.md": "# Init\n"},
            "chore: init",
        )
        self._write_and_commit(
            {
                "src/core/new_clean.ts": _build_ts_function_with_cc("cleanHelper", 6),
                "src/core/new_bloated.ts": _build_ts_function_with_cc("bloatedEngine", 13),
            },
            "feat: add new files",
        )

        res = self.gate.check_complexity_non_regression("HEAD~1", healthy_cc_ceiling=10)
        self.assertFalse(res.passed)
        joined = "\n".join(res.details)
        self.assertIn("src/core/new_bloated.ts", joined)
        self.assertIn("bloatedEngine", joined)
        self.assertNotIn("new_clean.ts", joined)


class TestLayerLeakageGate(_HermeticGitRepoTestCase):
    def test_new_action_file_with_db_select_fails(self) -> None:
        """Brand-new action controller containing db.select MUST FAIL."""
        self._write_and_commit({"README.md": "# Init\n"}, "chore: init")
        self._write_and_commit(
            {
                "src/actions/orders.ts": (
                    "import { db } from '@/db';\n"
                    "export async function listOrders() {\n"
                    "    return await db.select().from('orders');\n"
                    "}\n"
                )
            },
            "feat: leaky new action",
        )

        res = self.gate.check_layer_leakage("HEAD~1")
        self.assertFalse(res.passed)
        self.assertIn("src/actions/orders.ts", "\n".join(res.details))

    def test_existing_action_leak_increase_fails(self) -> None:
        """Existing action file increasing DB leaks (1 -> 2) MUST FAIL."""
        self._write_and_commit(
            {
                "app/actions/bookings.ts": (
                    "export async function manageBooking() {\n"
                    "    await db.select();\n"
                    "}\n"
                )
            },
            "chore: baseline 1 leak",
        )
        self._write_and_commit(
            {
                "app/actions/bookings.ts": (
                    "export async function manageBooking() {\n"
                    "    await db.select();\n"
                    "    await db.insert();\n"
                    "}\n"
                )
            },
            "feat: add second leak",
        )

        res = self.gate.check_layer_leakage("HEAD~1")
        self.assertFalse(res.passed)
        joined = "\n".join(res.details)
        self.assertIn("app/actions/bookings.ts", joined)
        self.assertIn("1 -> 2", joined)

    def test_existing_action_strangler_fig_leak_reduction_passes(self) -> None:
        """Strangler Fig incremental extraction (5 leaks -> 3 leaks) MUST PASS."""
        five_leaks = "\n".join(["    await db.select();" for _ in range(5)])
        three_leaks = "\n".join(["    await db.select();" for _ in range(3)])
        self._write_and_commit(
            {"src/actions/bookings.ts": f"export async function act() {{\n{five_leaks}\n}}\n"},
            "chore: baseline 5 leaks",
        )
        self._write_and_commit(
            {
                "src/actions/bookings.ts": f"export async function act() {{\n{three_leaks}\n}}\n",
                "src/lib/bookings/repository.ts": (
                    "export const repo = {\n"
                    "    async q1() { return await db.select(); },\n"
                    "    async q2() { return await db.select(); },\n"
                    "};\n"
                ),
            },
            "refactor: extract 2 leaks to repository",
        )

        res = self.gate.check_layer_leakage("HEAD~1")
        self.assertTrue(res.passed, msg=str(res))

    def test_run_all_passes_on_positive_net_sloc_extraction(self) -> None:
        """
        Extracting repository interfaces + domain core logic that adds +40 net production lines
        MUST PASS run_all() as long as MigrationGate, Max CC Non-Regression, and Layer Leakage pass.
        """
        baseline_action = (
            "import { db } from '@/db';\n"
            "export async function createAppointment(input: { start: number; end: number }) {\n"
            "    if (input.start >= input.end) { return { ok: false }; }\n"
            "    const existing = await db.select();\n"
            "    if (existing.length > 0) { return { ok: false }; }\n"
            "    const created = await db.insert();\n"
            "    return { ok: true, data: created };\n"
            "}\n"
        )
        self._write_and_commit(
            {"src/actions/appointments.ts": baseline_action},
            "chore: monolithic action baseline (8 lines)",
        )

        # Clean layered refactor with > +45 net production lines (interfaces, repo, core validator)
        thinned_action = (
            "import { appointmentRepo } from '@/lib/appointments/repository';\n"
            "import { validateWindow } from '@/core/appointments/validator';\n\n"
            "export interface ActionResponse<T> {\n"
            "    ok: boolean;\n"
            "    reason?: string;\n"
            "    data?: T;\n"
            "}\n\n"
            "export async function createAppointment(\n"
            "    input: { start: number; end: number }\n"
            "): Promise<ActionResponse<unknown>> {\n"
            "    const check = validateWindow(input.start, input.end);\n"
            "    if (!check.valid) {\n"
            "        return { ok: false, reason: check.reason };\n"
            "    }\n"
            "    const existing = await appointmentRepo.findActive();\n"
            "    if (existing.length > 0) {\n"
            "        return { ok: false, reason: 'conflict' };\n"
            "    }\n"
            "    const created = await appointmentRepo.create(input);\n"
            "    return { ok: true, data: created };\n"
            "}\n"
        )
        new_repo = (
            "import { db } from '@/db';\n\n"
            "export interface AppointmentRecord {\n"
            "    id: string;\n"
            "    start: number;\n"
            "    end: number;\n"
            "}\n\n"
            "export interface AppointmentRepository {\n"
            "    findActive(): Promise<AppointmentRecord[]>;\n"
            "    create(payload: { start: number; end: number }): Promise<AppointmentRecord>;\n"
            "}\n\n"
            "export const appointmentRepo: AppointmentRepository = {\n"
            "    async findActive() {\n"
            "        return await db.select();\n"
            "    },\n"
            "    async create(payload) {\n"
            "        return await db.insert(payload);\n"
            "    },\n"
            "};\n"
        )
        new_core = (
            "export interface ValidationOutcome {\n"
            "    valid: boolean;\n"
            "    reason?: string;\n"
            "}\n\n"
            "export function validateWindow(start: number, end: number): ValidationOutcome {\n"
            "    if (start < 0 || end < 0) {\n"
            "        return { valid: false, reason: 'negative_timestamp' };\n"
            "    }\n"
            "    if (start >= end) {\n"
            "        return { valid: false, reason: 'invalid_interval' };\n"
            "    }\n"
            "    return { valid: true };\n"
            "}\n"
        )
        self._write_and_commit(
            {
                "src/actions/appointments.ts": thinned_action,
                "src/lib/appointments/repository.ts": new_repo,
                "src/core/appointments/validator.ts": new_core,
            },
            "refactor: extract repository and domain validator (+50 net SLOC)",
        )

        net_lines_added = (
            len(thinned_action.splitlines())
            + len(new_repo.splitlines())
            + len(new_core.splitlines())
            - len(baseline_action.splitlines())
        )
        self.assertGreaterEqual(net_lines_added, 40)

        passed = self.gate.run_all(
            base_ref="HEAD~1",
            is_refactor=True,
            skip_verification=True,
            target_file="src/actions/appointments.ts",
            scaffolding_allowance=0,
            track="all",
        )
        self.assertTrue(passed)


if __name__ == "__main__":
    unittest.main()
