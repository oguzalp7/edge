"""
Unit tests for CRAPPER: Tree-Sitter Cyclomatic Complexity + LCOV Branch Risk Engine.
Covers CRAP formula, LCOV branch/line parsing, branch coverage priority,
existing LCOV discovery, and AST-based function analysis on large files with string braces.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pytest

from tools.audit.crapper import (
    FunctionCrapMetric,
    compute_crap,
    parse_lcov,
    function_coverage_from_lcov,
    analyze_file_crap,
    discover_existing_lcov,
    TREE_SITTER_AVAILABLE,
)


class TestCrapFormula:
    def test_compute_crap_matrix(self):
        # 1. Simple function, 100% covered: CC=1, Cov=100% -> CRAP = 1.0
        assert compute_crap(1, 100.0) == 1.0

        # 2. Moderate complexity, 100% covered: CC=10, Cov=100% -> CRAP = 10.0
        assert compute_crap(10, 100.0) == 10.0

        # 3. Moderate complexity, 0% covered: CC=10, Cov=0% -> CRAP = 10^2 * 1^3 + 10 = 110.0
        assert compute_crap(10, 0.0) == 110.0

        # 4. High complexity, 50% covered: CC=30, Cov=50% -> CRAP = 900 * (0.5)^3 + 30 = 900 * 0.125 + 30 = 112.5 + 30 = 142.5
        assert compute_crap(30, 50.0) == 142.5

    def test_compute_crap_clamps_coverage_bounds(self):
        # Negative coverage clamped to 0.0
        assert compute_crap(4, -25.0) == compute_crap(4, 0.0)
        # Over 100% coverage clamped to 100.0
        assert compute_crap(4, 150.0) == compute_crap(4, 100.0)


class TestLcovParsing:
    def test_parse_lcov_lines_and_branches(self):
        lcov_sample = """TN:
SF:src/core/pricing.ts
DA:5,3
DA:6,3
DA:7,0
BRDA:6,0,0,3
BRDA:6,0,1,0
end_of_record
SF:src/core/discount.ts
DA:10,1
DA:11,1
end_of_record
"""
        records = parse_lcov(lcov_sample)
        assert "src/core/pricing.ts" in records
        assert "src/core/discount.ts" in records

        pricing = records["src/core/pricing.ts"]
        assert pricing["lines"] == {5: 3, 6: 3, 7: 0}
        assert pricing["branches"] == [(6, 3), (6, 0)]

        discount = records["src/core/discount.ts"]
        assert discount["lines"] == {10: 1, 11: 1}
        assert discount["branches"] == []

    def test_function_coverage_branch_priority(self):
        """
        When branches exist within [start_line, end_line], branch coverage MUST take priority
        over line coverage to reflect genuine decision path testing.
        """
        # Range [10, 20]: 4 branches (2 taken, 2 missed = 50.0%), lines are 100% hit
        file_cov = {
            "lines": {line: 1 for line in range(10, 21)},
            "branches": [
                (12, 5),   # taken
                (12, 0),   # missed
                (15, 2),   # taken
                (15, 0),   # missed
            ]
        }
        cov_pct = function_coverage_from_lcov(file_cov, 10, 20)
        assert cov_pct == 50.0, f"Expected 50.0% branch coverage priority, got {cov_pct}"

    def test_function_coverage_line_fallback_when_no_branches(self):
        """When no branches exist in the function range, fall back to line hits percentage."""
        file_cov = {
            "lines": {
                20: 5,
                21: 5,
                22: 0,
                23: 5,
            },
            "branches": []
        }
        cov_pct = function_coverage_from_lcov(file_cov, 20, 25)
        # 3 out of 4 lines hit -> 75.0%
        assert cov_pct == 75.0

    def test_function_coverage_uninstrumented_returns_zero(self):
        file_cov = {
            "lines": {1: 1, 2: 1},
            "branches": []
        }
        # Lines 50-60 not in file coverage record
        assert function_coverage_from_lcov(file_cov, 50, 60) == 0.0


class TestLcovDiscovery:
    def test_discover_existing_lcov_success(self, tmp_path):
        cov_dir = tmp_path / "coverage"
        cov_dir.mkdir(parents=True, exist_ok=True)
        lcov_file = cov_dir / "lcov.info"
        lcov_file.write_text("TN:\nend_of_record\n", encoding="utf-8")

        found = discover_existing_lcov(tmp_path)
        assert found is not None
        assert found == lcov_file

    def test_discover_existing_lcov_missing(self, tmp_path):
        assert discover_existing_lcov(tmp_path) is None


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")
class TestCrapperAstAnalysis:
    def test_analyze_file_crap_handles_unbalanced_braces_and_large_files(self, tmp_path):
        """
        Verifies that AST analysis replaces naive regex brace-matching:
        1. Correctly parses strings containing unbalanced braces: const s = '{{{';
        2. Correctly parses functions exceeding 520 lines without truncation bugs.
        3. Computes accurate cyclomatic complexity and CRAP score.
        """
        # Construct a >520 line TypeScript function with nested branches and string braces
        lines = [
            "export function parseComplexPayload(rawInput: string, flag: boolean): number {",
            "    const trickyString = '{{{{ Unbalanced opening braces in literal {'; ",
            "    const trickyRegex = /\\{+/g;",
            "    let accumulator = 0;",
        ]

        # Add 530 lines with periodic branch conditions to exceed the 500-line legacy truncation bug
        for i in range(1, 531):
            if i % 50 == 0:
                lines.append(f"    if (rawInput.length > {i} && flag) {{")
                lines.append(f"        accumulator += {i};")
                lines.append("    }")
            else:
                lines.append(f"    accumulator += {i};")

        lines.append("    return accumulator;")
        lines.append("}")

        ts_file = tmp_path / "large_payload.ts"
        ts_file.write_text("\n".join(lines), encoding="utf-8")

        # Mock LCOV data where lines are partially covered
        lcov_data = {
            "large_payload.ts": {
                "lines": {1: 1, 2: 1, 3: 1, 4: 1},
                "branches": [(52, 1), (52, 0)]  # 50% branch coverage
            }
        }

        metrics = analyze_file_crap(ts_file, "large_payload.ts", lcov_data.get("large_payload.ts"))

        assert len(metrics) == 1, f"Expected 1 function metric, got {len(metrics)}"
        m = metrics[0]
        assert m.name == "parseComplexPayload"
        assert m.start_line == 1
        assert m.end_line >= 530, f"Function end line {m.end_line} indicates 500-line truncation bug!"
        assert m.complexity >= 10, f"Expected cyclomatic complexity >= 10, got {m.complexity}"
        assert m.coverage_pct is not None
        assert m.crap_score is not None
        assert m.crap_score > m.complexity, "CRAP score must reflect risk factor when coverage is partial"
