"""
Integration tests for Radar Scanner Quality Rules:
RULE-DEAD-IMPORT suppression, RULE-HIGH-CRAP emission, RULE-FAT-FUNCTION suppression
via CRAP metric, and RULE-AST-DUPLICATE clone emission.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pytest

from tools.radar.scanner import RadarScanner, LedgerItem
try:
    from tools.audit.crapper import TREE_SITTER_AVAILABLE
except ImportError:
    try:
        import tree_sitter
        import tree_sitter_language_pack
        TREE_SITTER_AVAILABLE = True
    except ImportError:
        TREE_SITTER_AVAILABLE = False


class TestRadarMechanicalDepollution:
    def test_radar_scan_ui_omits_mechanical_dead_import_by_default(self, tmp_path):
        """
        By default (include_mechanical=False), scan_ui MUST NOT emit RULE-DEAD-IMPORT items
        into the architectural ledger. When include_mechanical=True, they are retained.
        """
        src_dir = tmp_path / "src" / "components"
        src_dir.mkdir(parents=True, exist_ok=True)

        card_tsx = src_dir / "UnusedImportCard.tsx"
        card_tsx.write_text(
            "import { useState, useEffect } from 'react';\n"
            "export function UnusedImportCard() {\n"
            "    return <div>Hello</div>;\n"
            "}\n",
            encoding="utf-8"
        )

        scanner = RadarScanner(tmp_path)

        # 1. Default scan_ui (include_mechanical=False)
        findings_clean = scanner.scan_ui(include_mechanical=False)
        dead_imports_clean = [f for f in findings_clean if f.rule_id == "RULE-DEAD-IMPORT"]
        assert len(dead_imports_clean) == 0, "RULE-DEAD-IMPORT must be suppressed by default"

        # 2. Explicit mechanical scan (include_mechanical=True)
        findings_mechanical = scanner.scan_ui(include_mechanical=True)
        dead_imports_mech = [f for f in findings_mechanical if f.rule_id == "RULE-DEAD-IMPORT"]
        assert len(dead_imports_mech) >= 1, "RULE-DEAD-IMPORT must be present when include_mechanical=True"


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")
class TestRadarCrapAndCloneRules:
    def test_radar_scan_core_emits_rule_high_crap(self, tmp_path):
        """
        When LCOV exists and a function has high complexity (CC=10) with 0% coverage (CRAP=110 >= 30),
        RadarScanner.scan_core() must emit RULE-HIGH-CRAP with CRITICAL severity.
        """
        src_core = tmp_path / "src" / "core"
        src_core.mkdir(parents=True, exist_ok=True)

        complex_ts = src_core / "risky_dispatcher.ts"
        lines = [
            "export function riskyDispatcher(evt: string, val: number): number {",
            "    let acc = 0;",
        ]
        # Build 10 branching points (CC >= 10)
        for i in range(10):
            lines.append(f"    if (evt === 'event_{i}' && val > {i}) {{ acc += {i}; }}")
        lines.append("    return acc;")
        lines.append("}")
        complex_ts.write_text("\n".join(lines), encoding="utf-8")

        # Create LCOV report with 0 hits on risky_dispatcher lines
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        lcov_info = cov_dir / "lcov.info"
        lcov_info.write_text(
            "TN:\n"
            "SF:src/core/risky_dispatcher.ts\n"
            "DA:1,0\n"
            "DA:2,0\n"
            "end_of_record\n",
            encoding="utf-8"
        )

        scanner = RadarScanner(tmp_path)
        findings = scanner.scan_core()

        crap_findings = [f for f in findings if f.rule_id == "RULE-HIGH-CRAP"]
        assert len(crap_findings) >= 1, "Expected RULE-HIGH-CRAP to be emitted for complex untested function"
        assert crap_findings[0].severity == "CRITICAL"
        assert "riskyDispatcher" in crap_findings[0].title or "riskyDispatcher" in crap_findings[0].description

    def test_radar_scan_core_suppresses_fat_function_when_crap_clean(self, tmp_path):
        """
        A function > 60 lines normally triggers RULE-FAT-FUNCTION.
        However, if LCOV shows 100% branch/line coverage and CRAP < 15.0,
        RadarScanner MUST suppress the RULE-FAT-FUNCTION finding!
        """
        src_core = tmp_path / "src" / "core"
        src_core.mkdir(parents=True, exist_ok=True)

        clean_ts = src_core / "thoroughly_tested.ts"
        lines = [
            "export function thoroughlyTestedAlgorithm(input: number[]): number {",
            "    let sum = 0;",
        ]
        # Generate 70 lines (exceeds fat function threshold)
        for i in range(70):
            lines.append(f"    sum += input[{i}] ?? 0;")
        lines.append("    return sum;")
        lines.append("}")
        clean_ts.write_text("\n".join(lines), encoding="utf-8")

        # Create LCOV with 100% coverage
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir()
        lcov_info = cov_dir / "lcov.info"
        lcov_entries = ["TN:\nSF:src/core/thoroughly_tested.ts\n"]
        for line_no in range(1, 75):
            lcov_entries.append(f"DA:{line_no},10\n")
        lcov_entries.append("end_of_record\n")
        lcov_info.write_text("".join(lcov_entries), encoding="utf-8")

        scanner = RadarScanner(tmp_path)
        findings = scanner.scan_core()

        fat_findings = [f for f in findings if f.rule_id == "RULE-FAT-FUNCTION" and "thoroughly_tested.ts" in f.file_path]
        assert len(fat_findings) == 0, "RULE-FAT-FUNCTION must be suppressed when function is clean (CRAP < 15.0)"

    def test_radar_scan_core_emits_rule_ast_duplicate(self, tmp_path):
        """
        When two core files contain structural AST clones (score >= 0.82),
        RadarScanner.scan_core() must emit RULE-AST-DUPLICATE.
        """
        src_core = tmp_path / "src" / "core"
        src_core.mkdir(parents=True, exist_ok=True)

        mod_a = """
        export function computeCommissionAlpha(sales: number, tier: number): number {
            const base = 50;
            const gross = sales * tier + base;
            if (gross > 1000) {
                return gross * 1.1;
            }
            return gross;
        }
        """
        mod_b = """
        export function computeCommissionBeta(revenue: number, level: number): number {
            const start = 80;
            const subtotal = revenue * level + start;
            if (subtotal > 2000) {
                return subtotal * 1.1;
            }
            return subtotal;
        }
        """

        (src_core / "comm_a.ts").write_text(mod_a, encoding="utf-8")
        (src_core / "comm_b.ts").write_text(mod_b, encoding="utf-8")

        scanner = RadarScanner(tmp_path)
        findings = scanner.scan_core()

        clone_findings = [f for f in findings if f.rule_id == "RULE-AST-DUPLICATE"]
        assert len(clone_findings) >= 1, "Expected RULE-AST-DUPLICATE finding in scan_core"
