import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.harvester_discovery import discover_candidates, link_parent_sender


def test_discover_candidates_and_link_parent_sender(tmp_path: Path) -> None:
    sess = tmp_path / "sess-1"
    sess.mkdir()
    assert discover_candidates([tmp_path], since_hours=24) == [sess]

    c2p, p2c, roles = {}, {}, {}
    steps = [
        {"step_index": 0, "content": "[swarm] new board message"},
        {"step_index": 1, "content": "Message for **@surgeon**: go\nsender=11111111-2222-3333-4444-555555555555"},
    ]
    link_parent_sender(steps, "child-1", c2p, p2c, set(), lambda cid, r, _p: roles.setdefault(cid, r))
    assert c2p["child-1"] == "11111111-2222-3333-4444-555555555555"
    assert roles["child-1"] == "surgeon"
