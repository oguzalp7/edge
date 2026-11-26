import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.ts_lexer_jsx import LexerState, consume_jsx_tag, is_generic_arrow_ahead


def test_jsx_lookahead_and_consume() -> None:
    assert is_generic_arrow_ahead("const f = <T,>(x: T) => x;", 10)
    assert not is_generic_arrow_ahead("const el = <Box a='1'>x</Box>;", 11)
    src = "<Box a={1}>x</Box>"
    st = LexerState(source=src, out=[" "] * len(src), comments=[], i=0)
    consume_jsx_tag(st)
    assert st.stack[-1] == ["jsx_children"]
