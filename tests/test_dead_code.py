"""
Unit tests for Slice F4: Knip Dead-Code Elimination & Mechanical Debt Pre-Sweep.
Covers Knip JSON parsing, fallback orphan graph discovery, and mechanical eslint --fix pre-sweep.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import json
import pytest
from unittest.mock import patch, MagicMock

from tools.audit.dead_code import (
    DeadCodeReport,
    parse_knip_json,
    run_dead_code_scan,
    run_mechanical_presweep,
)


class TestKnipParser:
    def test_parse_knip_json_realistic_output(self):
        raw_knip_payload = json.dumps({
            "files": ["src/legacy/old_helper.ts", "src/unused_view.tsx"],
            "issues": [
                {
                    "file": "src/utils/math.ts",
                    "exports": [
                        {"name": "deprecatedMultiplier", "line": 45, "col": 14}
                    ],
                    "types": [
                        {"name": "OldMathOptions", "line": 12, "col": 13}
                    ]
                },
                {
                    "file": "src/services/api.ts",
                    "exports": [
                        {"name": "unusedEndpoint", "line": 88, "col": 10}
                    ],
                    "types": []
                }
            ]
        })

        report = parse_knip_json(raw_knip_payload)
        assert isinstance(report, DeadCodeReport)
        assert report.engine == "knip"
        assert "src/legacy/old_helper.ts" in report.unused_files
        assert "src/unused_view.tsx" in report.unused_files
        assert len(report.unused_files) == 2

        # Check unused exports
        export_names = [e["name"] for e in report.unused_exports]
        assert "deprecatedMultiplier" in export_names
        assert "unusedEndpoint" in export_names
        assert len(report.unused_exports) == 2

        # Check unused types
        type_names = [t["name"] for t in report.unused_types]
        assert "OldMathOptions" in type_names
        assert len(report.unused_types) == 1

    def test_parse_knip_json_empty_clean_project(self):
        report = parse_knip_json('{"files": [], "issues": []}')
        assert isinstance(report, DeadCodeReport)
        assert report.engine == "knip"
        assert report.unused_files == []
        assert report.unused_exports == []
        assert report.unused_types == []


class TestDeadCodeFallback:
    def test_run_dead_code_scan_fallback_to_graph_builder(self, tmp_path):
        """
        When knip is not installed or package.json has no knip, run_dead_code_scan
        must fall back cleanly to GraphBuilder orphan detection with engine='fallback'.
        """
        src_dir = tmp_path / "src" / "components"
        src_dir.mkdir(parents=True, exist_ok=True)

        orphan_card = src_dir / "OrphanCard.tsx"
        orphan_card.write_text("export function OrphanCard() { return <div>Orphan</div>; }", encoding="utf-8")

        active_card = src_dir / "ActiveCard.tsx"
        active_card.write_text("export function ActiveCard() { return <div>Active</div>; }", encoding="utf-8")

        index_file = tmp_path / "src" / "index.ts"
        index_file.write_text("import { ActiveCard } from './components/ActiveCard';", encoding="utf-8")

        report = run_dead_code_scan(tmp_path)
        assert isinstance(report, DeadCodeReport)
        assert report.engine == "fallback"
        assert any("OrphanCard.tsx" in f for f in report.unused_files)
        assert not any("ActiveCard.tsx" in f for f in report.unused_files)


class TestMechanicalPresweep:
    def test_run_mechanical_presweep_executes_eslint_fix(self, tmp_path):
        """
        run_mechanical_presweep executes 'npx eslint --fix' to eliminate unused imports
        and mechanical debt without consuming LLM reasoning tokens.
        """
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="✔ Fixed 4 problems in 2 files automatically",
                stderr=""
            )

            code, output = run_mechanical_presweep(tmp_path)
            assert code == 0
            assert "Fixed 4 problems" in output

            mock_run.assert_called_once()
            called_args = mock_run.call_args[0][0]
            assert "eslint" in called_args
            assert "--fix" in called_args
