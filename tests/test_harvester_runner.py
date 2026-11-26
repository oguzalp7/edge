import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.harvester_runner import filter_sessions, find_matched_sessions
from tools.distill.models import DistillWatermarkState


def test_harvester_runner_matching_and_filtering(tmp_path: Path) -> None:
    proj = tmp_path / "demo-app"
    proj.mkdir()
    steps = {"c1": [{"workspaceUris": [str(proj)]}], "c2": [{"workspaceUris": ["/other/repo"]}]}
    matched = find_matched_sessions(steps, proj, {}, {})
    assert matched == {"c1"}

    wm = DistillWatermarkState(processed_sessions=["c1"])
    assert filter_sessions(wm, matched, None, False, 10, {"c1"}) == []
    assert filter_sessions(wm, matched, "c1", False, 10, {"c1"}) == ["c1"]
