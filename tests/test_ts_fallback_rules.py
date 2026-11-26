import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.ts_fallback_rules import scan_non_null_assertions, scan_positional_args
from tools.audit.ts_models import _build_line_starts


def test_ts_fallback_rules() -> None:
    src = "const x = foo!;\nfunction many(a: string, b: number, c: boolean, d: string) { return a; }\n"
    ls = _build_line_starts(src)
    lines = src.splitlines()
    assert len(scan_non_null_assertions(src, ls, lines)) == 1
    assert len(scan_positional_args(src, ls, lines)) == 1
