import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.adapters.typescript import TypeScriptAdapter
from tools.audit.adapters.ts_metrics import calc_ts_complexity, count_ts_exports, count_ts_lines


def test_typescript_adapter_and_ts_metrics(tmp_path: Path) -> None:
    f = tmp_path / "src" / "math.ts"
    f.parent.mkdir(parents=True)
    code = "export function add(a: number, b: number) {\n  if (a > 0) return a + b;\n  return 0;\n}\n"
    f.write_text(code, encoding="utf-8")
    metrics = TypeScriptAdapter().analyze(f, "src/math.ts", code, tmp_path)
    assert metrics.sloc == 4
    assert metrics.public_exports >= 1
    assert count_ts_lines(code.splitlines())[1] == 4
    assert calc_ts_complexity(code) >= 2
    assert count_ts_exports(code) >= 1
