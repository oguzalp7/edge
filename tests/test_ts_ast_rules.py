import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.ts_ast_analyzer import _analyze_with_ast
from tools.audit.ts_discipline import _get_parser_for_ext


def test_ts_ast_rules_smoke() -> None:
    parser = _get_parser_for_ext(".ts")
    if parser is None:
        return
    src = "const x = ({ a: 1 } as any);\n"
    findings, _ = _analyze_with_ast(src, "src/core/a.ts", parser)
    assert any(f.rule_id == "RULE-TS-EXPLICIT-ANY" for f in findings)
