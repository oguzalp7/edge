import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.dryer_ast import jaccard_similarity


def test_dryer_ast_jaccard_similarity() -> None:
    assert jaccard_similarity(frozenset({"a", "b"}), frozenset({"b", "c"})) == 0.3333
    assert jaccard_similarity(frozenset(), frozenset({"a"})) == 0.0
