"""
Comprehensive Unit Tests for Edge Audit Suite Consolidation & Pruning
Tests SLOC-weighted scoring, auto indentation, domain-aware test seams,
scoped scans, semicolon-free import stripping, and unified CLI tracks.
"""

import sys
import unittest
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch

# Add project root to sys.path for direct execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.audit.models import FileMetrics, AuditSummary, IssueTag, RiskCategory, FunctionMetrics
from tools.audit.scorer import HealthScorer
from tools.audit.adapters.typescript import TypeScriptAdapter
from tools.audit.scanner import FileScanner
from tools.ui_audit.graph_builder import GraphBuilder
from tools.ui_audit.models import ComponentNode, ComponentImport
from tools.gate import EdgeVerificationGate


class TestSLOCWeightedScorer(unittest.TestCase):
    def test_sloc_thresholds_alignment(self):
        adapter = TypeScriptAdapter()

        # Clean file (< 200 SLOC)
        m_clean = FileMetrics(
            path=Path("clean.ts"), rel_path="clean.ts", extension=".ts",
            total_lines=150, sloc=150, comment_lines=0, blank_lines=0,
            complexity_score=5, max_indent_level=2, public_exports=2,
            has_test_seam=True
        )
        scored_clean = HealthScorer.score_file(m_clean)
        self.assertEqual(scored_clean.risk_category, RiskCategory.CLEAN)
        self.assertNotIn(IssueTag.GOD_FILE, scored_clean.issue_tags)

        # Attention file (200 - 350 SLOC)
        m_attention = FileMetrics(
            path=Path("attention.ts"), rel_path="attention.ts", extension=".ts",
            total_lines=250, sloc=250, comment_lines=0, blank_lines=0,
            complexity_score=5, max_indent_level=2, public_exports=2,
            has_test_seam=True
        )
        scored_attention = HealthScorer.score_file(m_attention)
        self.assertEqual(scored_attention.risk_score, 12.0)
        self.assertNotIn(IssueTag.GOD_FILE, scored_attention.issue_tags)

        # Hotspot file (> 350 SLOC)
        m_hotspot = FileMetrics(
            path=Path("hotspot.ts"), rel_path="hotspot.ts", extension=".ts",
            total_lines=400, sloc=400, comment_lines=0, blank_lines=0,
            complexity_score=5, max_indent_level=2, public_exports=2,
            has_test_seam=True
        )
        scored_hotspot = HealthScorer.score_file(m_hotspot)
        self.assertIn(IssueTag.GOD_FILE, scored_hotspot.issue_tags)
        self.assertEqual(scored_hotspot.risk_score, 25.0)

        # Critical God file (> 500 SLOC)
        m_god = FileMetrics(
            path=Path("god.ts"), rel_path="god.ts", extension=".ts",
            total_lines=600, sloc=600, comment_lines=0, blank_lines=0,
            complexity_score=5, max_indent_level=2, public_exports=2,
            has_test_seam=True
        )
        scored_god = HealthScorer.score_file(m_god)
        self.assertIn(IssueTag.GOD_FILE, scored_god.issue_tags)
        self.assertEqual(scored_god.risk_score, 45.0)

    def test_sloc_weighted_health_score_prevents_barrel_masking(self):
        # 1 massive God file (600 SLOC, 70 risk) and 20 tiny barrel files (5 SLOC each, 0 risk)
        god_file = FileMetrics(
            path=Path("god.ts"), rel_path="god.ts", extension=".ts",
            total_lines=600, sloc=600, comment_lines=0, blank_lines=0,
            complexity_score=40, max_indent_level=5, public_exports=15,
            has_test_seam=False, risk_score=70.0, risk_category=RiskCategory.CRITICAL
        )
        barrel_files = [
            FileMetrics(
                path=Path(f"barrel_{i}.ts"), rel_path=f"barrel_{i}.ts", extension=".ts",
                total_lines=5, sloc=5, comment_lines=0, blank_lines=0,
                complexity_score=1, max_indent_level=1, public_exports=1,
                has_test_seam=True, risk_score=0.0, risk_category=RiskCategory.CLEAN
            )
            for i in range(20)
        ]

        summary = AuditSummary(
            target_path=Path("."),
            file_results=[god_file] + barrel_files
        )
        summary = HealthScorer.calculate_summary(summary)

        # SLOC-weighted: total sloc = 700. God file represents 600/700 = ~85.7% of code!
        # Weighted risk = 70.0 * (600/700) = 60.0.
        # Plus critical hotspot penalty (1 * 3.0 = 3.0) -> combined risk = 63.0.
        # Overall health should be ~37.0 / 100, NOT ~96.5 / 100!
        self.assertLess(summary.overall_health_score, 50.0)
        self.assertEqual(summary.critical_hotspots, 1)

    def test_ui_action_mixing_penalty(self):
        m = FileMetrics(
            path=Path("Component.tsx"), rel_path="Component.tsx", extension=".tsx",
            total_lines=100, sloc=100, comment_lines=0, blank_lines=0,
            complexity_score=5, max_indent_level=2, public_exports=1,
            has_test_seam=True, has_ui_action_mixing=True
        )
        scored = HealthScorer.score_file(m)
        self.assertIn(IssueTag.UI_ACTION_MIXING, scored.issue_tags)
        self.assertEqual(scored.risk_score, 25.0)


class TestTypeScriptAdapterEnhancements(unittest.TestCase):
    def setUp(self):
        self.adapter = TypeScriptAdapter()

    def test_auto_indent_detection_4_spaces(self):
        code_4_space = [
            "function compute() {",
            "    const a = 1;",
            "    if (a > 0) {",
            "        return a + 1;",
            "    }",
            "    return 0;",
            "}"
        ]
        max_indent = self.adapter._calc_max_indent(code_4_space)
        # In 4-space code, max indent is 8 spaces -> level 2
        self.assertEqual(max_indent, 2)

    def test_auto_indent_detection_2_spaces(self):
        code_2_space = [
            "function compute() {",
            "  const a = 1;",
            "  if (a > 0) {",
            "    return a + 1;",
            "  }",
            "  return 0;",
            "}"
        ]
        max_indent = self.adapter._calc_max_indent(code_2_space)
        # In 2-space code, max indent is 4 spaces -> level 2
        self.assertEqual(max_indent, 2)

    def test_find_functions_calculates_actual_complexity_and_deep_window(self):
        # Generate a large function of 200 lines with multiple decision points
        lines = ["export function complexHandler() {"]
        for i in range(180):
            if i % 15 == 0:
                lines.append(f"    if (x === {i}) return {i};")
            else:
                lines.append(f"    const val_{i} = {i};")
        lines.append("    return null;")
        lines.append("}")

        funcs = self.adapter._find_functions(lines)
        self.assertEqual(len(funcs), 1)
        self.assertEqual(funcs[0].name, "complexHandler")
        self.assertGreater(funcs[0].sloc, 170)
        self.assertGreater(funcs[0].complexity, 10)

    def test_ui_action_mixing_flag_in_tsx(self):
        tsx_with_db = (
            "export function AppointmentsList() {\n"
            "  const data = await db.select().from(appointments);\n"
            "  return <div>{data.length}</div>;\n"
            "}\n"
        )
        metric = self.adapter.analyze(
            path=Path("AppointmentsList.tsx"),
            rel_path="src/components/AppointmentsList.tsx",
            content=tsx_with_db,
            workspace_root=Path(".")
        )
        self.assertTrue(metric.has_ui_action_mixing)


class TestDomainAwareTestSeamResolution(unittest.TestCase):
    def setUp(self):
        self.adapter = TypeScriptAdapter()

    def test_generic_stem_no_false_positive_collision(self):
        # A test index that has users/repository test, but NOT billing/repository test
        test_index = {
            "users/repository": ["tests/unit/users/repository.test.ts"],
        }

        # Billing repository should NOT match users repository
        billing_repo = Path("src/lib/billing/repository.ts")
        matches = self.adapter.find_companion_tests(billing_repo, Path("."), test_index)
        self.assertEqual(matches, [])

    def test_generic_stem_matches_exact_parent_dir(self):
        test_index = {
            "billing/repository": ["tests/unit/billing/repository.test.ts"],
        }
        billing_repo = Path("src/lib/billing/repository.ts")
        matches = self.adapter.find_companion_tests(billing_repo, Path("."), test_index)
        self.assertEqual(matches, ["tests/unit/billing/repository.test.ts"])

    def test_generic_stem_matches_domain_level_test(self):
        test_index = {
            "domain:billing": ["tests/unit/billing.test.ts"],
        }
        billing_repo = Path("src/lib/billing/repository.ts")
        matches = self.adapter.find_companion_tests(billing_repo, Path("."), test_index)
        self.assertEqual(matches, ["tests/unit/billing.test.ts"])


class TestFileScannerScoped(unittest.TestCase):
    def test_scoped_files_analyzes_only_specified_subset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            f1 = tmp_path / "file1.ts"
            f2 = tmp_path / "file2.ts"
            f3 = tmp_path / "file3.ts"

            f1.write_text("export const a = 1;\n", encoding="utf-8")
            f2.write_text("export const b = 2;\n", encoding="utf-8")
            f3.write_text("export const c = 3;\n", encoding="utf-8")

            scanner = FileScanner(workspace_root=tmp_path)
            summary = scanner.scan(tmp_path, scoped_files=["file1.ts"])

            self.assertEqual(summary.analyzed_files, 1)
            self.assertEqual(len(summary.file_results), 1)
            self.assertEqual(summary.file_results[0].path.name, "file1.ts")


class TestGraphBuilderSemicolonFree(unittest.TestCase):
    def test_safe_import_stripping_without_semicolons(self):
        content = (
            "import { Button } from './Button'\n"
            "import { Card } from './Card'\n\n"
            "export function Page() {\n"
            "  return <Button />\n"
            "}\n"
        )
        builder = GraphBuilder(Path("."))
        imports = builder._extract_imports(content)

        # Button should be used, Card should be dead
        button_imp = next(i for i in imports if i.source_str == "./Button")
        card_imp = next(i for i in imports if i.source_str == "./Card")

        self.assertIn("Button", button_imp.used_symbols)
        self.assertEqual(button_imp.dead_symbols, [])
        self.assertIn("Card", card_imp.dead_symbols)

    def test_hooks_reference_prevents_component_orphan(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            src_dir = root / "src"
            comp_dir = src_dir / "components"
            hooks_dir = src_dir / "hooks"
            comp_dir.mkdir(parents=True)
            hooks_dir.mkdir(parents=True)

            modal_file = comp_dir / "Modal.tsx"
            modal_file.write_text("export function Modal() { return <div>Modal</div>; }\n", encoding="utf-8")

            hook_file = hooks_dir / "useModal.ts"
            hook_file.write_text("import { Modal } from '@/components/Modal';\nexport function useModal() {}\n", encoding="utf-8")

            builder = GraphBuilder(root)
            nodes = builder.build_graph()

            orphans = builder.find_orphans()
            orphan_paths = [o.rel_path for o in orphans]

            # Modal.tsx should NOT be an orphan because useModal.ts imported it
            self.assertNotIn("src/components/Modal.tsx", orphan_paths)


class TestGatePurityEnhancements(unittest.TestCase):
    def test_domain_purity_catches_canonical_arrays_in_ts_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo = Path(tmp_dir)
            lib_dir = repo / "src" / "lib" / "departments"
            lib_dir.mkdir(parents=True)

            constants_file = lib_dir / "constants.ts"
            constants_file.write_text("export const CANONICAL_DEPARTMENTS = ['A', 'B'];\n", encoding="utf-8")

            gate = EdgeVerificationGate(repo)
            res = gate.check_domain_purity()
            self.assertFalse(res.passed)
            self.assertIn("Hardcoded canonical definition found", res.details[0])


class TestUnifiedCLI(unittest.TestCase):
    def test_cli_tracks_and_formats(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            src_dir = root / "src"
            comp_dir = src_dir / "components"
            tests_dir = root / "tests"
            comp_dir.mkdir(parents=True)
            tests_dir.mkdir(parents=True)

            (src_dir / "service.ts").write_text("export function run() { return 1; }\n", encoding="utf-8")
            (comp_dir / "Button.tsx").write_text("export function Button() { return <button>Click</button>; }\n", encoding="utf-8")
            (tests_dir / "service.test.ts").write_text("import { run } from '../src/service';\ntest('run', () => expect(run()).toBe(1));\n", encoding="utf-8")

            from tools.audit.cli import run_core_track, run_ui_track, run_tests_track, run_all_tracks

            # Core track formats
            core_json = run_core_track(root, "json", top=5)
            self.assertIn("edge_audit_summary", core_json)

            core_md = run_core_track(root, "markdown", top=5)
            self.assertIn("# 🛡️ EDGE-AUDIT", core_md)

            core_toon = run_core_track(root, "toon", top=5)
            self.assertIn("edge_audit_result", core_toon)

            # UI track formats
            ui_json = run_ui_track(root, "json")
            self.assertIn("ui_audit", ui_json)

            ui_md = run_ui_track(root, "markdown")
            self.assertIn("UI Architecture Audit", ui_md)

            # Tests track formats
            test_json = run_tests_track(root, "json", top=5)
            self.assertIn("test_audit_summary", test_json)

            test_md = run_tests_track(root, "markdown")
            self.assertIn("TypeScript Unit Test Health Radar", test_md)

            # Unified track formats
            all_json = run_all_tracks(root, "json", top=5)
            parsed_all = json.loads(all_json)
            self.assertIn("unified_audit", parsed_all)
            self.assertIn("core", parsed_all["unified_audit"])
            self.assertIn("ui", parsed_all["unified_audit"])
            self.assertIn("tests", parsed_all["unified_audit"])

            all_md = run_all_tracks(root, "markdown", top=5)
            self.assertIn("Edge Unified Codebase Audit Report", all_md)


if __name__ == "__main__":
    unittest.main()
