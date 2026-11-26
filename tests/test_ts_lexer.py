import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.ts_lexer import _sanitize_ts_source


def test_ts_lexer_masks_strings_comments_and_jsx_text() -> None:
    src = "// @ts-ignore\nconst s = 'as any';\nexport const El = () => <div>hello any</div>;\n"
    masked, comments = _sanitize_ts_source(src, is_tsx=True)
    assert len(comments) == 1 and "@ts-ignore" in comments[0][1]
    assert "as any" not in masked
    assert "hello any" not in masked
