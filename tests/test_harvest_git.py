import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.gnhf.harvest_git import _parse_single_blocker_line, _parse_worktree_porcelain


def test_harvest_git_parsers() -> None:
    blocks = _parse_worktree_porcelain("worktree /tmp/wt\nbranch refs/heads/gnhf/x\n")
    assert blocks == [{"worktree": "/tmp/wt", "branch": "refs/heads/gnhf/x"}]
    blk = _parse_single_blocker_line("[SKIPPED-NEEDS-HITL] a.py: manual")
    assert blk is not None and blk.file_path == "a.py"
