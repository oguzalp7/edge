#!/usr/bin/env python3
"""edge-tests-audit-typescript: Deterministic Test Purity & External I/O Leakage Auditor."""

import argparse
from pathlib import Path
import sys
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import normalize_target_path, setup_utf8_console
from tools.test_audit.analyzer import analyze_test_file, get_test_files
from tools.test_audit.formatter import format_human, format_json, format_markdown, format_toon

setup_utf8_console()


class TestFileAuditor:
    """Audits TypeScript/JavaScript unit tests for live DB and action-layer leakage."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()

    def get_test_files(self, target_dir: Path) -> List[Path]:
        return get_test_files(target_dir)

    def analyze_file(self, file_path: Path) -> Dict[str, Any]:
        return analyze_test_file(file_path, self.root_dir)


def main() -> None:
    """CLI entrypoint for test purity auditing."""
    parser = argparse.ArgumentParser(description="edge-tests-audit-typescript: Deterministic Unit Test Purity & Isolation Auditor")
    parser.add_argument("target", nargs="?", default="tests/unit", help="Target directory or file to audit")
    parser.add_argument("--format", choices=["human", "table", "markdown", "toon", "json"], default="human", help="Output format")
    parser.add_argument("--top", type=int, default=15, help="Maximum number of toxic tests to display")
    parser.add_argument("-o", "--output", "--out", dest="output", type=str, default=None, help="Optional output file path")
    parser.add_argument("--fail-under", type=int, default=None, help="Exit 1 if average score is below threshold")
    parser.add_argument("--strict-pure", action="store_true", help="Exit 1 if any toxic (< 50) test exists")
    args = parser.parse_args()

    project_root = Path.cwd()
    target_path = normalize_target_path(args.target)
    if not target_path.is_absolute():
        target_path = (project_root / target_path).resolve()
    files = TestFileAuditor(project_root).get_test_files(target_path)
    if not files:
        print(f"Warning: No test files found in target path: {target_path}", file=sys.stderr)
        sys.exit(0)
    auditor = TestFileAuditor(project_root)
    results = sorted((auditor.analyze_file(f) for f in files), key=lambda x: x["score"])
    fmt_map = {"toon": format_toon, "markdown": format_markdown, "json": format_json}
    output = fmt_map.get(args.format, format_human)(results, top=args.top)
    print(output)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"\nReport saved to: {out_path}")
    avg_score = sum(r["score"] for r in results) / len(results)
    if (args.fail_under is not None and avg_score < args.fail_under) or (args.strict_pure and any(r["score"] < 50 for r in results)):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
