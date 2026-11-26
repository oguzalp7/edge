import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.ts_fallback_helpers import (
    _check_bag_segments,
    _extract_switch_default_block,
    _find_matching_delimiter,
    _split_top_level_commas,
)


def test_ts_fallback_helpers() -> None:
    assert _find_matching_delimiter("fn(a, (b))", 2, "(", ")") == 9
    assert _split_top_level_commas("a: Record<string, number>, b: (x: number) => void") == [
        "a: Record<string, number>", "b: (x: number) => void"
    ]
    assert _extract_switch_default_block("{ case 1: break; default: return x; }") is not None
    assert _check_bag_segments(["isLoading: boolean", "data?: string", "err?: string"])
