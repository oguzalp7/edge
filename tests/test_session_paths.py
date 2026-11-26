import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.session_paths import extract_clean_quote, extract_project_from_path


def test_extract_project_and_quote() -> None:
    assert extract_project_from_path("/home/oguz/edge-proj/src/app.py") == "edge-proj"
    assert "dikey dilim" in extract_clean_quote("Lütfen dikey dilim olarak geliştir.", "dikey dilim")
