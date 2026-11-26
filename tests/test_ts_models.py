import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.ts_models import _compute_sloc, _is_core_or_lib_path, _is_test_path, _score_to_band_and_badge


def test_ts_models_helpers() -> None:
    assert _score_to_band_and_badge(90)[0] == "STRICT"
    assert _score_to_band_and_badge(70)[0] == "LOOSE"
    assert _score_to_band_and_badge(20)[0] == "POROUS"
    assert _is_test_path("src/foo.test.ts")
    assert _is_core_or_lib_path("src/core/calc.ts")
    assert _compute_sloc("// c\nconst x = 1;\n\nconst y = 2;\n") == 2
