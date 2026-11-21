import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
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



class TestGhostRootDirectoryGate(_HermeticGitRepoTestCase):
    """Hermetic unit tests for Stage-0 Ghost Root Directory Sanitizer Gate."""

    def test_ghost_root_dirs_constant_defined(self):
        """Validates that GHOST_ROOT_DIRS constant exists and contains canonical truncated dirnames."""
        self.assertTrue(
            hasattr(EdgeVerificationGate, "GHOST_ROOT_DIRS"),
            "EdgeVerificationGate must define GHOST_ROOT_DIRS constant",
        )
        self.assertEqual(
            EdgeVerificationGate.GHOST_ROOT_DIRS,
            ("rc", "pecs", "ests", "pp", "ib", "omponents"),
        )

    def test_check_ghost_root_directories_clean_passes(self):
        """Validates that clean repository without ghost directories passes Stage-0."""
        self.assertTrue(
            hasattr(self.gate, "check_ghost_root_directories"),
            "EdgeVerificationGate must define check_ghost_root_directories method",
        )
        for d in ("src", "specs", "tests", "app", "lib", "components"):
            (self.repo_path / d).mkdir(parents=True, exist_ok=True)

        result = self.gate.check_ghost_root_directories()
        self.assertTrue(result.passed)
        self.assertEqual(result.stage_num, 0)
        self.assertIn("No truncated ghost root directories", result.message)

    def test_check_ghost_root_directories_detects_truncated_roots(self):
        """Validates that truncated root directories like 'rc' and 'pecs' fail Stage-0."""
        self.assertTrue(
            hasattr(self.gate, "check_ghost_root_directories"),
            "EdgeVerificationGate must define check_ghost_root_directories method",
        )
        (self.repo_path / "rc").mkdir()
        (self.repo_path / "pecs").mkdir()

        result = self.gate.check_ghost_root_directories()
        self.assertFalse(result.passed)
        self.assertEqual(result.stage_num, 0)
        self.assertTrue(any("rc" in d for d in result.details))
        self.assertTrue(any("pecs" in d for d in result.details))

    def test_run_all_fail_fast_on_ghost_root(self):
        """Validates that run_all() fails fast at Stage 0 when ghost root directories are present."""
        self.assertTrue(
            hasattr(self.gate, "check_ghost_root_directories"),
            "EdgeVerificationGate must define check_ghost_root_directories method",
        )
        self._write_and_commit({"README.md": "# test"}, "initial commit")
        (self.repo_path / "rc").mkdir()
        passed = self.gate.run_all(base_ref="HEAD", skip_verification=True)
        self.assertFalse(passed)


class TestNavigationCheckGate(_HermeticGitRepoTestCase):
    """Hermetic RED tests for unconditional check:navigation stage in EdgeVerificationGate."""

    def test_skips_when_package_json_missing_malformed_or_unconfigured(self) -> None:
        self.assertTrue(hasattr(self.gate, "_has_navigation_check_script"))
        self.assertTrue(hasattr(self.gate, "check_navigation_gate"))

        invalid_package_payloads = [
            None,  # package.json absent
            "{malformed json content",
            "[]",  # non-dict root JSON
            json.dumps({"name": "no-scripts"}),
            json.dumps({"scripts": []}),
            json.dumps({"scripts": None}),
            json.dumps({"scripts": "bad-type"}),
            json.dumps({"scripts": {"test": "vitest"}}),
            json.dumps({"scripts": {"check:navigation": ""}}),
            json.dumps({"scripts": {"check:navigation": "   \t\n  "}}),
            json.dumps({"scripts": {"check:navigation": None}}),
            json.dumps({"scripts": {"check:navigation": 123}}),
            json.dumps({"scripts": {"check:navigation": False}}),
            json.dumps({"scripts": {"check:navigation": {}}}),
        ]

        pkg_path = self.repo_path / "package.json"
        for idx, raw_payload in enumerate(invalid_package_payloads):
            if raw_payload is None:
                if pkg_path.exists():
                    pkg_path.unlink()
            else:
                pkg_path.write_text(raw_payload, encoding="utf-8")

            with patch.object(self.gate, "_run_cmd") as mock_run:
                self.assertFalse(
                    self.gate._has_navigation_check_script(),
                    f"Case {idx} should not detect check:navigation script",
                )
                res = self.gate.check_navigation_gate()
                self.assertIsInstance(res, GateResult)
                self.assertTrue(res.passed, f"Case {idx} should skip cleanly and pass")
                self.assertEqual(res.name, "Navigation Check Gate")
                mock_run.assert_not_called()

    def test_fails_closed_when_node_modules_missing(self) -> None:
        self.assertTrue(hasattr(self.gate, "check_navigation_gate"))
        (self.repo_path / "package.json").write_text(
            json.dumps({"scripts": {"check:navigation": "npx tsx scripts/check-navigation.ts"}}),
            encoding="utf-8",
        )
        self.assertFalse((self.repo_path / "node_modules").exists())

        with patch.object(self.gate, "_run_cmd") as mock_run:
            self.assertTrue(self.gate._has_navigation_check_script())
            res = self.gate.check_navigation_gate()
            self.assertFalse(res.passed)
            self.assertEqual(res.name, "Navigation Check Gate")
            self.assertIn("node_modules", res.message)
            mock_run.assert_not_called()

    def test_runs_npm_check_navigation_when_node_modules_present(self) -> None:
        self.assertTrue(hasattr(self.gate, "check_navigation_gate"))
        (self.repo_path / "package.json").write_text(
            json.dumps({"scripts": {"check:navigation": "npx tsx scripts/check-navigation.ts"}}),
            encoding="utf-8",
        )
        (self.repo_path / "node_modules").mkdir()

        # 1. Pass on exit code 0
        with patch.object(self.gate, "_run_cmd", return_value=(0, "All links verified", "")) as mock_run:
            res_ok = self.gate.check_navigation_gate()
            mock_run.assert_called_once_with(["npm", "run", "check:navigation"], timeout=60)
            self.assertTrue(res_ok.passed)
            self.assertEqual(res_ok.name, "Navigation Check Gate")

        # 2. Fail on non-zero exit with stripped diagnostic lines capped at 8
        stdout_lines = "\n".join(
            [
                "",
                "   nav error line 1   ",
                "   ",
                "nav error line 2",
                "nav error line 3",
                "nav error line 4",
                "nav error line 5",
                "nav error line 6",
            ]
        )
        stderr_lines = "\n".join(
            [
                "  nav stderr line 7  ",
                "nav stderr line 8",
                "nav stderr line 9",
                "nav stderr line 10",
            ]
        )
        with patch.object(self.gate, "_run_cmd", return_value=(1, stdout_lines, stderr_lines)) as mock_run:
            res_fail = self.gate.check_navigation_gate()
            mock_run.assert_called_once_with(["npm", "run", "check:navigation"], timeout=60)
            self.assertFalse(res_fail.passed)
            self.assertEqual(res_fail.name, "Navigation Check Gate")
            self.assertEqual(len(res_fail.details), 8)
            self.assertEqual(
                res_fail.details,
                [
                    "nav error line 1",
                    "nav error line 2",
                    "nav error line 3",
                    "nav error line 4",
                    "nav error line 5",
                    "nav error line 6",
                    "nav stderr line 7",
                    "nav stderr line 8",
                ],
            )

    def test_run_all_executes_navigation_gate_unconditionally_across_tracks_and_skip_verify(self) -> None:
        self.assertTrue(hasattr(self.gate, "check_navigation_gate"))
        self._write_and_commit({"README.md": "# Repo\n"}, "chore: init")

        orig_run = self.gate._run_cmd
        nav_calls: list[tuple[list[str], int]] = []
        nav_response = (0, "Navigation ok", "")

        def _intercept_cmd(cmd, cwd=None, timeout=120):
            if cmd == ["npm", "run", "check:navigation"]:
                nav_calls.append((list(cmd), timeout))
                return nav_response
            return orig_run(cmd, cwd=cwd, timeout=timeout)

        with patch.object(self.gate, "_run_cmd", side_effect=_intercept_cmd):
            # 1. Unconfigured repo passes all tracks with skip_verification=True and 0 npm calls
            for track in ("core", "ui", "feature", "all"):
                passed = self.gate.run_all(base_ref="HEAD", is_refactor=False, skip_verification=True, track=track)
                self.assertTrue(passed, f"Unconfigured repo should pass track={track}")
            self.assertEqual(nav_calls, [])

            # 2. Configure package.json + node_modules; failing check:navigation fails ALL tracks even with skip_verification=True
            (self.repo_path / "package.json").write_text(
                json.dumps({"scripts": {"check:navigation": "npx tsx scripts/check-navigation.ts"}}),
                encoding="utf-8",
            )
            (self.repo_path / "node_modules").mkdir()

            nav_response = (1, "BROKEN_ROUTE /missing in Sidebar.tsx", "")
            for track in ("core", "ui", "feature", "all"):
                nav_calls.clear()
                buf = io.StringIO()
                with redirect_stdout(buf):
                    passed = self.gate.run_all(base_ref="HEAD", is_refactor=True, skip_verification=True, track=track)
                out = buf.getvalue()
                self.assertFalse(passed, f"Failing check:navigation must fail run_all for track={track}")
                self.assertEqual(nav_calls, [(["npm", "run", "check:navigation"], 60)])
                self.assertIn("Stage 0: Ghost Root Directory Sanitizer Gate", out)
                self.assertIn("Stage 1: Navigation Check Gate", out)
                if track != "feature":
                    self.assertIn("Stage 2: MigrationGate Invariant Gate", out)
                else:
                    self.assertIn("Stage 2: Max CC Non-Regression Gate", out)

            # 3. Passing check:navigation passes all tracks under skip_verification=True
            nav_response = (0, "Navigation ok", "")
            for track in ("core", "ui", "feature", "all"):
                nav_calls.clear()
                passed = self.gate.run_all(base_ref="HEAD", is_refactor=False, skip_verification=True, track=track)
                self.assertTrue(passed, f"Passing check:navigation should pass track={track}")
                self.assertEqual(nav_calls, [(["npm", "run", "check:navigation"], 60)])

            # 4. Stage 0 ghost-dir fail-fast still halts before running check_navigation_gate
            nav_calls.clear()
            (self.repo_path / "rc").mkdir()
            passed_ghost = self.gate.run_all(base_ref="HEAD", is_refactor=False, skip_verification=True, track="feature")
            self.assertFalse(passed_ghost)
            self.assertEqual(nav_calls, [])


class TestDeterministicOmissionAndSafetyGates(_HermeticGitRepoTestCase):
    """Hermetic RED tests for mock fallback, type escape, and dual-theme/a11y gates."""

    def test_rules_exports_omission_and_safety_patterns(self) -> None:
        import tools.rules as rules_mod

        for attr_name in (
            "MOCK_FALLBACK_PATTERN",
            "TYPE_ESCAPE_PATTERN",
            "BG_WHITE_NO_DARK_PATTERN",
            "ICON_X_BUTTON_NO_ARIA_PATTERN",
        ):
            self.assertTrue(
                hasattr(rules_mod, attr_name),
                f"tools.rules must export {attr_name}",
            )

    def test_check_mock_fallbacks_gate(self) -> None:
        self.assertTrue(
            hasattr(self.gate, "check_mock_fallbacks"),
            "EdgeVerificationGate must define check_mock_fallbacks",
        )
        self._write_and_commit({"README.md": "# Init\n"}, "chore: init")

        # 1. Fail when production file under src/ defines or uses DEFAULT_SERVICES or MOCK_ITEMS
        self._write_and_commit(
            {
                "src/lib/services/repository.ts": (
                    "export const DEFAULT_SERVICES = [{ id: 's1', name: 'Cut' }];\n"
                    "export const MOCK_ITEMS = [];\n"
                    "export function getServices(rows: unknown[]) {\n"
                    "    return rows.length ? rows : DEFAULT_SERVICES;\n"
                    "}\n"
                ),
            },
            "feat: add mock fallback in production repository",
        )
        res_fail = self.gate.check_mock_fallbacks("HEAD~1")
        self.assertFalse(res_fail.passed)
        self.assertIn("src/lib/services/repository.ts", "\n".join(res_fail.details))

        # 2. Pass when clean in production, while ignoring test files and comment lines
        self._write_and_commit(
            {
                "src/lib/services/repository.ts": (
                    "// removed DEFAULT_SERVICES and MOCK_ITEMS fallback\n"
                    "export function getServices(rows: unknown[]) {\n"
                    "    return rows;\n"
                    "}\n"
                ),
                "tests/unit/foo.test.ts": "const DEFAULT_SERVICES = [{ id: '1' }];\n",
                "src/lib/foo.test.ts": "const MOCK_ITEMS = [{ id: '2' }];\n",
            },
            "fix: remove production mock fallback and keep test fixtures",
        )
        res_pass = self.gate.check_mock_fallbacks("HEAD~1")
        self.assertTrue(res_pass.passed, msg=str(res_pass))

    def test_check_type_escapes_gate(self) -> None:
        self.assertTrue(
            hasattr(self.gate, "check_type_escapes"),
            "EdgeVerificationGate must define check_type_escapes",
        )
        self._write_and_commit({"README.md": "# Init\n"}, "chore: init")

        # 1. Fail when changed production .ts/.tsx contains as any, as unknown as, @ts-ignore, or @ts-expect-error
        self._write_and_commit(
            {
                "src/actions/booking.ts": (
                    "// @ts-ignore\n"
                    "export function parseInput(x: unknown) {\n"
                    "    const a = x as any;\n"
                    "    const b = x as unknown as string;\n"
                    "    return { a, b };\n"
                    "}\n"
                ),
                "src/components/Card.tsx": (
                    "// @ts-expect-error\n"
                    "export function Card() { return <div />; }\n"
                ),
            },
            "feat: introduce type escapes",
        )
        res_fail = self.gate.check_type_escapes("HEAD~1")
        self.assertFalse(res_fail.passed)
        joined = "\n".join(res_fail.details)
        self.assertIn("src/actions/booking.ts", joined)
        self.assertIn("src/components/Card.tsx", joined)

        # 2. Pass when production .ts/.tsx files are clean
        self._write_and_commit(
            {
                "src/actions/booking.ts": (
                    "export function parseInput(x: string): string {\n"
                    "    return x.trim();\n"
                    "}\n"
                ),
                "src/components/Card.tsx": (
                    "export function Card() { return <div />; }\n"
                ),
            },
            "fix: remove type escapes",
        )
        res_pass = self.gate.check_type_escapes("HEAD~1")
        self.assertTrue(res_pass.passed, msg=str(res_pass))

    def test_check_dual_theme_and_a11y_gate(self) -> None:
        self.assertTrue(
            hasattr(self.gate, "check_dual_theme_and_a11y"),
            "EdgeVerificationGate must define check_dual_theme_and_a11y",
        )
        self._write_and_commit({"README.md": "# Init\n"}, "chore: init")

        # 1. Fail when changed .tsx file has bg-white without dark:bg- or icon X button without aria-label
        self._write_and_commit(
            {
                "src/components/Modal.tsx": (
                    "export function Modal({ close }: { close: () => void }) {\n"
                    "    return (\n"
                    '        <div className="p-4 bg-white rounded">\n'
                    '            <button onClick={close}><X className="w-4 h-4" /></button>\n'
                    "        </div>\n"
                    "    );\n"
                    "}\n"
                )
            },
            "feat: modal missing dark bg and aria-label",
        )
        res_fail = self.gate.check_dual_theme_and_a11y("HEAD~1")
        self.assertFalse(res_fail.passed)
        self.assertIn("src/components/Modal.tsx", "\n".join(res_fail.details))

        # 2. Pass when dark:bg- and aria-label are provided
        self._write_and_commit(
            {
                "src/components/Modal.tsx": (
                    "export function Modal({ close }: { close: () => void }) {\n"
                    "    return (\n"
                    '        <div className="p-4 bg-white dark:bg-zinc-900 rounded">\n'
                    '            <button aria-label="Kapat" onClick={close}><X className="w-4 h-4" /></button>\n'
                    "        </div>\n"
                    "    );\n"
                    "}\n"
                )
            },
            "fix: add dark:bg-zinc-900 and aria-label to modal",
        )
        res_pass = self.gate.check_dual_theme_and_a11y("HEAD~1")
        self.assertTrue(res_pass.passed, msg=str(res_pass))

    def test_check_differential_mutation_gate(self) -> None:
        gate_fn = getattr(gate_mod, "check_differential_mutation_gate", None)
        self.assertIsNotNone(
            gate_fn,
            "tools.gate must define check_differential_mutation_gate",
        )
        self.assertTrue(
            hasattr(self.gate, "check_differential_mutation_gate"),
            "EdgeVerificationGate must define check_differential_mutation_gate",
        )

        # 1. Bypass when no src/core/ production files changed
        res_bypass = gate_fn(self.repo_path, ["src/components/Button.tsx"], skip_verify=True)
        self.assertTrue(res_bypass.passed, msg=str(res_bypass))

        # 2. Static differential SDL scan when src/core/pricing.ts changed and skip_verify=True
        self._write_and_commit({"README.md": "# Init\n"}, "chore: init")
        self._write_and_commit(
            {
                "src/core/pricing.ts": (
                    "export function calcTotal(qty: number, price: number): number {\n"
                    '    if (qty <= 0) throw new Error("invalid qty");\n'
                    "    return qty * price;\n"
                    "}\n"
                ),
            },
            "feat: add core pricing guard",
        )
        res_static = gate_fn(
            self.repo_path,
            ["src/core/pricing.ts"],
            skip_verify=True,
            base_ref="HEAD~1",
        )
        self.assertTrue(res_static.passed, msg=str(res_static))
        self.assertIn("SDL", res_static.message)

    def test_verification_default_timeout_is_300s_or_higher(self) -> None:
        recorded: list[tuple[list[str], int]] = []

        def fake_run_command(cmd, cwd=None, timeout=None):
            recorded.append((list(cmd), timeout))
            return (0, "ok", "")

        with patch("tools.gate.run_command", side_effect=fake_run_command):
            res = self.gate.check_verification()

        self.assertTrue(res.passed, msg=str(res))
        self.assertEqual(
            recorded,
            [
                (["npx", "tsc", "--noEmit"], 300),
                (["npm", "run", "test:unit"], 360),
            ],
        )


if __name__ == "__main__":
    unittest.main()
