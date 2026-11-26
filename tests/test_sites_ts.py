import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.mutator.sites_ts import _discover_with_regex_fallback


def test_sites_ts_regex_fallback_operators_and_sdl() -> None:
    code = b"export function add(a: number, b: number) {\n  if (a === 0) return 0;\n  validateInput(a);\n  return a + b;\n}\n"
    sites = _discover_with_regex_fallback(code, "src/core/add.ts", mode="all")
    originals = {s.original for s in sites}
    assert "===" in originals
    assert "+" in originals
    assert "validateInput(a);" in originals
