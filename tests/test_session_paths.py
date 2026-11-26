import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.session_paths import extract_clean_quote, extract_project_from_path, normalize_path_string


def test_extract_project_and_quote() -> None:
    assert extract_project_from_path("/home/oguz/edge-proj/src/app.py") == "edge-proj"
    assert "dikey dilim" in extract_clean_quote("Lütfen dikey dilim olarak geliştir.", "dikey dilim")


def test_macos_and_windows_file_uri_and_users_paths() -> None:
    assert normalize_path_string("file:///Users/alice/Projects/edge-app/src/index.ts") == "/Users/alice/Projects/edge-app/src/index.ts"
    assert normalize_path_string("file:///C:/Users/alice/edge-app/src/index.ts") == "C:/Users/alice/edge-app/src/index.ts"
    assert extract_project_from_path("file:///Users/alice/Projects/edge-app/src/index.ts") == "edge-app"
    assert extract_project_from_path("/Users/alice/my-repo/src/main.py") == "my-repo"
