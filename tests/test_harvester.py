import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.harvester import TranscriptGraphHarvester


def test_harvester_empty_repo_harvest(tmp_path: Path) -> None:
    h = TranscriptGraphHarvester(repo_path=tmp_path, brain_roots=[tmp_path / "no-brains"])
    digest = h.harvest(tmp_path)
    assert digest.sessions_analyzed == []
    assert digest.tool_frictions == []
