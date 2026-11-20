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


# ----------------------------------------------------------------------
# SPEC-EDGE-BRIGADE-009 (IC-1 .. IC-3, IC-5): SDL Deletion Mutator & Differential/Recursive Runner
# ----------------------------------------------------------------------


class TestSDLAndRegexFallback:
    def test_ts_regex_fallback_sdl_and_operators(self, tmp_path):
        import inspect
        import tools.mutator.sites as sites_mod

        fallback_fn = getattr(sites_mod, "_discover_with_regex_fallback", None)
        assert fallback_fn is not None, "tools.mutator.sites must define _discover_with_regex_fallback"

        sig = inspect.signature(discover_mutation_sites)
        assert "mode" in sig.parameters, "discover_mutation_sites must accept mode parameter"

        ts_code = (
            'import { User } from "./types";\n'
            "export function authorize(token: string, a: number, b: number): number {\n"
            '    if (!token) throw new Error("unauthorized");\n'
            "    return a + b;\n"
            "}\n"
        )
        ts_file = tmp_path / "auth.ts"
        ts_file.write_text(ts_code, encoding="utf-8")

        with patch.object(sites_mod, "TREE_SITTER_AVAILABLE", False):
            sites_all = discover_mutation_sites(ts_file, "src/core/auth.ts", mode="all")
            sdl_sites = [s for s in sites_all if getattr(s, "op_category", None) == "sdl"]
            op_sites = [s for s in sites_all if getattr(s, "op_category", None) == "operators"]

            assert len(sdl_sites) >= 1, f"Expected SDL deletion site in TS fallback, got: {sites_all}"
            assert any(s.mutant == "/* [SDL-DELETED] */" and s.category == "SDL" for s in sdl_sites)
            assert any(s.original == "+" and s.mutant == "-" for s in op_sites)

            sites_sdl_only = discover_mutation_sites(ts_file, "src/core/auth.ts", mode="sdl")
            assert len(sites_sdl_only) >= 1
            assert all(getattr(s, "op_category", None) == "sdl" and s.category == "SDL" for s in sites_sdl_only)

            sites_ops_only = discover_mutation_sites(ts_file, "src/core/auth.ts", mode="operators")
            assert len(sites_ops_only) >= 1
            assert all(getattr(s, "op_category", None) == "operators" for s in sites_ops_only)

        direct_sites = fallback_fn(ts_code.encode("utf-8"), "src/core/auth.ts", mode="all")
        assert any(getattr(s, "op_category", None) == "sdl" for s in direct_sites)
        assert any(s.original == "+" and s.mutant == "-" for s in direct_sites)

    def test_python_sdl_preserves_indentation(self, tmp_path):
        import inspect
        import tools.mutator.sites as sites_mod

        sig = inspect.signature(discover_mutation_sites)
        assert "mode" in sig.parameters, "discover_mutation_sites must accept mode parameter"

        py_code = (
            "def validate_positive(x: int) -> int:\n"
            '    if x < 0: raise ValueError("neg")\n'
            "    assert x > 0\n"
            "    return x\n"
        )
        py_file = tmp_path / "guard_calc.py"
        py_file.write_text(py_code, encoding="utf-8")

        sites_sdl = discover_mutation_sites(py_file, "core/guard_calc.py", mode="sdl")
        assert len(sites_sdl) >= 2, f"Expected Python SDL sites for raise guard and assert, got: {sites_sdl}"
        assert all(getattr(s, "op_category", None) == "sdl" and s.category == "SDL" for s in sites_sdl)
        assert all(s.mutant == "pass  # [SDL-DELETED]" for s in sites_sdl)

        mutated_text = apply_mutation(py_code.encode("utf-8"), sites_sdl[0]).decode("utf-8")
        assert "    pass  # [SDL-DELETED]" in mutated_text


class TestImporterCacheDiffAndRecursive:
    def test_importer_cache_avoids_repeated_rglob(self, tmp_path):
        import tools.mutator.overlay as overlay_mod

        cache_dict = getattr(overlay_mod, "_IMPORTER_CACHE", None)
        clear_fn = getattr(overlay_mod, "clear_importer_cache", None)
        assert cache_dict is not None, "tools.mutator.overlay must define _IMPORTER_CACHE"
        assert clear_fn is not None, "tools.mutator.overlay must define clear_importer_cache"

        repo = tmp_path / "cached_repo"
        (repo / "src" / "core").mkdir(parents=True)
        (repo / "tests").mkdir(parents=True)
        (repo / "src" / "core" / "pricing.ts").write_text("export const price = 10;\n", encoding="utf-8")
        (repo / "tests" / "pricing.test.ts").write_text("import { price } from '../src/core/pricing';\n", encoding="utf-8")

        clear_fn(repo)
        orig_rglob = Path.rglob
        rglob_calls = 0

        def counting_rglob(self_path, *args, **kwargs):
            nonlocal rglob_calls
            if self_path == repo or self_path.resolve() == repo.resolve():
                rglob_calls += 1
            return orig_rglob(self_path, *args, **kwargs)

        with patch.object(Path, "rglob", autospec=True, side_effect=counting_rglob):
            imp1 = overlay_mod._find_all_importers(repo, "src/core/pricing.ts")
            imp2 = overlay_mod._find_all_importers(repo, "src/core/pricing.ts")

        assert len(imp1) == 1
        assert len(imp2) == 1
        assert rglob_calls == 1, f"Expected single cached rglob walk, got {rglob_calls}"
        assert str(repo.resolve()) in cache_dict

        clear_fn(repo)
        assert str(repo.resolve()) not in cache_dict

    def test_extract_git_diff_changed_lines_and_diff_only_run_mutations(self, tmp_path):
        import subprocess
        import tools.mutator.runner as runner_mod

        extract_fn = getattr(runner_mod, "extract_git_diff_changed_lines", None)
        run_fn = getattr(runner_mod, "run_mutations", None)
        assert extract_fn is not None, "tools.mutator.runner must define extract_git_diff_changed_lines"
        assert run_fn is not None, "tools.mutator.runner must define run_mutations"

        repo = tmp_path / "diff_repo"
        repo.mkdir()

        def git(*args):
            subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)

        git("init")
        git("config", "user.email", "mutator@example.com")
        git("config", "user.name", "Mutator")

        (repo / "core").mkdir()
        calc_py = repo / "core" / "calc.py"
        calc_py.write_text(
            "def calc(a: int, b: int) -> int:\n"
            '    if a < 0: raise ValueError("neg_a")\n'
            "    return a + b\n",
            encoding="utf-8",
        )
        (repo / "tests").mkdir()
        (repo / "tests" / "test_calc.py").write_text(
            "import unittest\n"
            "from core.calc import calc\n\n"
            "class TestCalc(unittest.TestCase):\n"
            "    def test_calc(self):\n"
            "        self.assertEqual(calc(2, 3), 5)\n"
            "        with self.assertRaises(ValueError):\n"
            "            calc(-1, 2)\n",
            encoding="utf-8",
        )
        git("add", "-A")
        git("commit", "-m", "init")

        # Add a new unasserted guard on line 3 only
        calc_py.write_text(
            "def calc(a: int, b: int) -> int:\n"
            '    if a < 0: raise ValueError("neg_a")\n'
            '    if b < 0: raise ValueError("neg_b")\n'
            "    return a + b\n",
            encoding="utf-8",
        )
        git("add", "-A")
        git("commit", "-m", "feat: add b guard")

        changed = extract_fn(repo, calc_py, base_ref="HEAD~1")
        assert changed == {3}, f"Expected only changed line {{3}}, got: {changed}"

        summary = run_fn(
            repo_root=repo,
            target_file=calc_py,
            test_cmd=["python3", "-m", "unittest", "tests/test_calc.py"],
            mode="sdl",
            diff_only=True,
            base_ref="HEAD~1",
        )
        assert summary.total == 1
        assert summary.survived == 1
        assert summary.outcomes[0].site.line == 3

    def test_discover_recursive_targets_and_run_recursive_mutations(self, tmp_path):
        import tools.mutator.runner as runner_mod

        disc_fn = getattr(runner_mod, "discover_recursive_targets", None)
        run_rec_fn = getattr(runner_mod, "run_recursive_mutations", None)
        rec_cls = getattr(runner_mod, "RecursiveMutationSummary", None)
        assert disc_fn is not None, "tools.mutator.runner must define discover_recursive_targets"
        assert run_rec_fn is not None, "tools.mutator.runner must define run_recursive_mutations"
        assert rec_cls is not None, "tools.mutator.runner must define RecursiveMutationSummary"

        repo = tmp_path / "rec_repo"
        (repo / "src" / "core" / "sub").mkdir(parents=True)
        (repo / "tests").mkdir(parents=True)

        (repo / "src" / "core" / "alpha.py").write_text(
            'def check_a(x: int) -> int:\n    if x < 0: raise ValueError("a")\n    return x\n',
            encoding="utf-8",
        )
        (repo / "src" / "core" / "sub" / "beta.py").write_text(
            'def check_b(y: int) -> int:\n    if y < 0: raise ValueError("b")\n    return y\n',
            encoding="utf-8",
        )
        (repo / "src" / "core" / "alpha.test.py").write_text("# test file excluded\n", encoding="utf-8")
        (repo / "tests" / "test_all.py").write_text(
            "import unittest\n"
            "from src.core.alpha import check_a\n"
            "from src.core.sub.beta import check_b\n\n"
            "class TestAll(unittest.TestCase):\n"
            "    def test_guards(self):\n"
            "        with self.assertRaises(ValueError):\n"
            "            check_a(-1)\n"
            "        with self.assertRaises(ValueError):\n"
            "            check_b(-1)\n",
            encoding="utf-8",
        )

        targets = disc_fn(repo)
        rel_targets = sorted(p.relative_to(repo).as_posix() for p in targets)
        assert rel_targets == ["src/core/alpha.py", "src/core/sub/beta.py"]

        rec_summary = run_rec_fn(
            repo_root=repo,
            test_cmd=["python3", "-m", "unittest", "tests/test_all.py"],
            mode="sdl",
        )
        assert isinstance(rec_summary, rec_cls)
        assert rec_summary.files_scanned >= 2
        assert rec_summary.total >= 2
        assert rec_summary.killed >= 2
        assert rec_summary.passed is True


class TestToonFormatCliAndSkillAlignment:
    def test_format_mutation_report_toon_default_and_cli_flags(self, tmp_path):
        import io
        from contextlib import redirect_stdout
        import tools.mutator.runner as runner_mod
        import tools.mutator.cli as mutator_cli

        fmt_fn = getattr(runner_mod, "format_mutation_report", None)
        assert fmt_fn is not None, "tools.mutator.runner must define format_mutation_report"

        site = MutationSite(
            file_path="src/core/auth.ts",
            function_name="authorize",
            line=3,
            start_byte=10,
            end_byte=52,
            original='if (!token) throw new Error("unauthorized");',
            mutant="/* [SDL-DELETED] */",
            category="SDL",
        )
        summary = MutationSummary(
            total=1,
            killed=1,
            survived=0,
            timed_out=0,
            score_pct=100.0,
            outcomes=[MutantOutcome(site=site, status="KILLED", duration_ms=12)],
        )
        toon = fmt_fn(summary)
        assert toon.startswith("mutator["), f"Expected TOON header starting with 'mutator[', got: {toon!r}"
        assert "line | op | original | mutated | status" in toon
        assert "KILLED" in toon

        # CLI flags: --mode sdl --diff-only --recursive --scan-only --format toon
        repo = tmp_path / "cli_repo"
        (repo / "src" / "core").mkdir(parents=True)
        (repo / "src" / "core" / "guard.py").write_text(
            'def f(x: int) -> int:\n    if x < 0: raise ValueError("neg")\n    return x\n',
            encoding="utf-8",
        )
        out_buf = io.StringIO()
        try:
            with patch.object(
                sys,
                "argv",
                [
                    "edge-mutator",
                    "--repo",
                    str(repo),
                    "--recursive",
                    "--scan-only",
                    "--mode",
                    "sdl",
                    "--format",
                    "toon",
                ],
            ), redirect_stdout(out_buf):
                rc = mutator_cli.main()
        except SystemExit as exc:
            pytest.fail(f"mutator cli exited abnormally with SystemExit: {exc}")
        assert rc == 0

    def test_edge_mutator_skill_documents_sdl_diff_recursive(self):
        skill_text = (root_dir / "skills" / "edge-mutator" / "SKILL.md").read_text(encoding="utf-8")
        assert "--mode sdl" in skill_text
        assert "--diff-only" in skill_text
        assert "--recursive" in skill_text
