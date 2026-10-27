"""
Unit tests for Slice F5: MUTATOR — Alias-Aware Differential Core Mutation Gate.
Covers core scope boundary enforcement, UTF-8 byte-offset mutations, Tree-Sitter mutation sites,
materialized Next.js @/ alias overlays with config physical copies, leak-free cleanup,
and differential result caching.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import json
import pytest
from unittest.mock import patch

from tools.mutator.sites import MutationSite, discover_mutation_sites, apply_mutation
from tools.mutator.overlay import create_worker_overlay, cleanup_worker_overlay
from tools.mutator.runner import MutantOutcome, MutationSummary, enforce_core_scope, run_mutation_suite
try:
    from tools.audit.crapper import TREE_SITTER_AVAILABLE
except ImportError:
    try:
        import tree_sitter
        import tree_sitter_language_pack
        TREE_SITTER_AVAILABLE = True
    except ImportError:
        TREE_SITTER_AVAILABLE = False


class TestCoreScopeGuard:
    def test_enforce_core_scope_allowed(self):
        assert enforce_core_scope("src/core/pricing.ts") is True
        assert enforce_core_scope("core/calc.py") is True
        assert enforce_core_scope("tools/audit/crapper.py") is True
        assert enforce_core_scope("./src/core/billing/invoices.ts") is True

    def test_enforce_core_scope_disallowed_raises_value_error(self):
        with pytest.raises(ValueError, match="Mutation testing restricted to core logic"):
            enforce_core_scope("src/components/Modal.tsx")

        with pytest.raises(ValueError, match="Mutation testing restricted to core logic"):
            enforce_core_scope("src/actions/bookings.ts")

    def test_enforce_core_scope_override_flag(self):
        assert enforce_core_scope("src/components/Modal.tsx", allow_non_core=True) is True


class TestByteReplacement:
    def test_apply_mutation_with_multibyte_utf8_offset(self):
        """
        Verifies that byte-based replacement works reliably even when multi-byte UTF-8
        characters precede the mutated operator, where character offset != byte offset.
        """
        # "🚀" is 4 bytes in UTF-8 (F0 9F 9A 80) but 1 character (or 2 UTF-16 code units)
        # "ş" and "ğ" are 2 bytes each in UTF-8
        source_text = (
            "# 🚀 Test Başlığı: şığöç éà\n"
            "def calculate_total(a, b):\n"
            "    return a + b\n"
        )
        source_bytes = source_text.encode("utf-8")

        # Locate the exact byte offset of the '+' operator
        plus_char_idx = source_text.index("+")
        # Compute exact byte position
        prefix_bytes = source_text[:plus_char_idx].encode("utf-8")
        start_byte = len(prefix_bytes)
        end_byte = start_byte + 1
        assert source_bytes[start_byte:end_byte] == b"+"

        site = MutationSite(
            file_path="math.py",
            function_name="calculate_total",
            line=3,
            start_byte=start_byte,
            end_byte=end_byte,
            original="+",
            mutant="-",
            category="Arithmetic"
        )

        mutated_bytes = apply_mutation(source_bytes, site)
        mutated_text = mutated_bytes.decode("utf-8")

        assert "return a - b" in mutated_text
        assert "🚀 Test Başlığı: şığöç éà" in mutated_text
        assert mutated_bytes[:start_byte] == source_bytes[:start_byte]


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")
class TestMutationSiteDiscovery:
    def test_discover_mutation_sites_operators(self, tmp_path):
        ts_code = """
        export function evaluateCondition(a: number, b: number, flag: boolean): boolean {
            const sum = a + b;
            const isGreater = a > 10;
            const isEqual = a === b;
            const combined = flag && isGreater;
            const fallback = a ?? 0;
            const state = true;
            return combined;
        }
        """
        ts_file = tmp_path / "condition.ts"
        ts_file.write_text(ts_code, encoding="utf-8")

        sites = discover_mutation_sites(ts_file, "src/core/condition.ts")
        assert len(sites) >= 5, f"Expected at least 5 mutation sites, found {len(sites)}"

        originals = [s.original for s in sites]
        assert "+" in originals
        assert ">" in originals
        assert "===" in originals
        assert "&&" in originals

        # Verify replacement operators
        plus_site = next(s for s in sites if s.original == "+")
        assert plus_site.mutant == "-"
        assert plus_site.category == "Arithmetic"

        eq_site = next(s for s in sites if s.original == '===')
        assert eq_site.mutant == '!=='

    def test_discover_mutation_sites_respects_covered_lines(self, tmp_path):
        ts_code = """
        export function calc(x: number): number {
            const a = x + 1; // line 3
            const b = x * 2; // line 4 (uncovered)
            return a;
        }
        """
        ts_file = tmp_path / "calc.ts"
        ts_file.write_text(ts_code, encoding="utf-8")

        # Pass covered_lines={3} (only line 3 was executed during coverage)
        sites = discover_mutation_sites(ts_file, "src/core/calc.ts", covered_lines={3})
        for s in sites:
            assert s.line == 3, f"Mutant on uncovered line {s.line} should have been skipped!"


class TestWorkerOverlay:
    def test_create_and_cleanup_worker_overlay_with_aliases(self, tmp_path):
        """
        Synthetic Next.js / Vitest repo test:
        1. tsconfig.json maps @/* to ./src/*
        2. vitest.config.ts and tsconfig.json must be physically copied (NOT symlinked).
        3. tests/billing.test.ts imports '@/core/billing' and must be materialized (copied).
        4. Mutated bytes written to overlay only; primary repo remains 100% UNCHANGED.
        5. cleanup_worker_overlay unlinks symlinks cleanly without altering primary repo.
        """
        repo_root = tmp_path / "repo"
        repo_root.mkdir()

        # Build configs
        tsconfig = repo_root / "tsconfig.json"
        tsconfig.write_text(json.dumps({
            "compilerOptions": {
                "baseUrl": ".",
                "paths": {"@/*": ["./src/*"]}
            }
        }), encoding="utf-8")

        vitest_config = repo_root / "vitest.config.ts"
        vitest_config.write_text("export default { test: { globals: true } };", encoding="utf-8")

        package_json = repo_root / "package.json"
        package_json.write_text('{"name": "test-repo"}', encoding="utf-8")

        # Source files
        src_core = repo_root / "src" / "core"
        src_core.mkdir(parents=True)
        billing_ts = src_core / "billing.ts"
        billing_original = "export function calculateTotal(qty: number): number { return qty * 10; }"
        billing_ts.write_text(billing_original, encoding="utf-8")

        unchanged_ts = src_core / "unchanged.ts"
        unchanged_ts.write_text("export const PI = 3.14159;", encoding="utf-8")

        # Test importing via alias
        tests_dir = repo_root / "tests"
        tests_dir.mkdir()
        billing_test = tests_dir / "billing.test.ts"
        billing_test.write_text(
            "import { calculateTotal } from '@/core/billing';\n"
            "test('calc', () => expect(calculateTotal(5)).toBe(50));\n",
            encoding="utf-8"
        )

        # Unrelated assets to be symlinked
        node_modules = repo_root / "node_modules" / "dummy_pkg"
        node_modules.mkdir(parents=True)
        (node_modules / "index.js").write_text("module.exports = {};", encoding="utf-8")

        # Execute create_worker_overlay
        mutated_bytes = b"export function calculateTotal(qty: number): number { return qty / 10; }"
        overlay = create_worker_overlay(repo_root, "src/core/billing.ts", mutated_bytes)

        try:
            assert overlay.exists()

            # Verify build configs are physical copies, NOT symlinks
            overlay_vitest = overlay / "vitest.config.ts"
            overlay_tsconfig = overlay / "tsconfig.json"
            assert overlay_vitest.is_file()
            assert not overlay_vitest.is_symlink(), "vitest.config.ts must be physically copied, not symlinked"
            assert overlay_tsconfig.is_file()
            assert not overlay_tsconfig.is_symlink(), "tsconfig.json must be physically copied, not symlinked"

            # Verify mutated file inside overlay contains mutated bytes
            overlay_billing = overlay / "src" / "core" / "billing.ts"
            assert overlay_billing.read_bytes() == mutated_bytes

            # PRIMARY REPO MUST BE 100% UNCHANGED
            assert billing_ts.read_text(encoding="utf-8") == billing_original

            # Verify tests/billing.test.ts was materialized (copied) because it imports @/core/billing
            overlay_test = overlay / "tests" / "billing.test.ts"
            assert overlay_test.is_file()
            assert not overlay_test.is_symlink(), "Dependent test importing @/ alias must be materialized"

            # Verify untouched node_modules is symlinked
            overlay_nm = overlay / "node_modules"
            assert overlay_nm.is_symlink()

        finally:
            # Tear down overlay
            cleanup_worker_overlay(overlay)
            assert not overlay.exists()

            # Ensure primary repo was not modified during cleanup
            assert billing_ts.exists()
            assert billing_ts.read_text(encoding="utf-8") == billing_original
            assert (node_modules / "index.js").exists()
            assert unchanged_ts.exists()


class TestDifferentialRunner:
    def test_run_mutation_suite_killed_survived_and_cached(self, tmp_path):
        """
        Runs mutation suite against a synthetic Python core module:
        1. Verifies test catches mutant -> KILLED.
        2. Verifies weak assertion misses mutant -> SURVIVED.
        3. Re-running hits the differential cache in .edge/metrics/mutator.json.
        """
        repo_root = tmp_path / "py_repo"
        repo_root.mkdir()

        core_dir = repo_root / "core"
        core_dir.mkdir()
        calc_py = core_dir / "calc.py"
        calc_py.write_text(
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n\n"
            "def check_positive(x: int) -> bool:\n"
            "    if x > 0:\n"
            "        return True\n"
            "    return True  # Weak logic\n",
            encoding="utf-8"
        )

        tests_dir = repo_root / "tests"
        tests_dir.mkdir()
        test_py = tests_dir / "test_calc.py"
        test_py.write_text(
            "import unittest\n"
            "from core.calc import add, check_positive\n\n"
            "class TestCalc(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n\n"
            "    def test_check(self):\n"
            "        self.assertTrue(check_positive(10))\n",
            encoding="utf-8"
        )

        test_cmd = ["python3", "-m", "unittest", "tests/test_calc.py"]

        summary = run_mutation_suite(
            repo_root=repo_root,
            target_file=calc_py,
            test_cmd=test_cmd,
            timeout_sec=10.0,
            allow_non_core=False
        )

        assert isinstance(summary, MutationSummary)
        assert summary.total >= 2
        assert summary.killed >= 1, "Expected mutant 'a - b' to be caught (KILLED)"
        assert summary.survived >= 1, "Expected weak logic mutant 'x >= 0' to SURVIVE"

        # Verify cache file was created
        cache_file = repo_root / ".edge" / "metrics" / "mutator.json"
        assert cache_file.exists()

        # Re-running with same files should utilize cached results
        summary_cached = run_mutation_suite(
            repo_root=repo_root,
            target_file=calc_py,
            test_cmd=test_cmd,
            timeout_sec=10.0
        )
        assert summary_cached.total == summary.total
        assert summary_cached.killed == summary.killed
