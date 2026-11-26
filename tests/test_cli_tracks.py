import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.audit.cli_tracks import run_core_track


def test_run_core_track_json_on_small_dir(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    out = run_core_track(tmp_path, "json", top=5)
    assert "edge_audit_summary" in out
