"""Companion unit tests for tools.drift.header_scanner."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pathlib import Path

from tools.drift.header_scanner import _extract_header_lines, _scan_files_for_headers, _walk_code_tree


def test_extract_and_scan_headers(tmp_path: Path) -> None:
    src = tmp_path / "tools" / "mod.py"
    src.parent.mkdir(parents=True)
    src.write_text(
        '"""\nModule doc.\n@concepts known-concept\n@invariants [INV-CORE-1]\n"""\nx = 1\n',
        encoding="utf-8",
    )
    lines = _extract_header_lines(src.read_text(encoding="utf-8"))
    assert "@concepts known-concept" in lines

    files = _walk_code_tree(tmp_path / "tools", tmp_path, {".git"})
    inv_index = {}
    issues = _scan_files_for_headers(files, {"known-concept"}, {"INV-CORE-1"}, inv_index)
    assert issues == []
    assert inv_index == {"INV-CORE-1": ["tools/mod.py"]}
