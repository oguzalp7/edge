"""Companion unit tests for tools.distill.session_miner and tools.distill.session_paths."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
from pathlib import Path

from tools.distill.session_miner import SessionMiner
from tools.distill.session_paths import extract_project_from_path, parse_timestamp


def test_session_paths_and_miner_end_to_end(tmp_path: Path) -> None:
    assert extract_project_from_path("/home/oguz/my-app/src/index.ts") == "my-app"
    assert parse_timestamp("2026-01-01T12:00:00Z") is not None

    brain = tmp_path / "brain"
    logs = brain / "sess-1" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    steps = [
        {"created_at": "2026-01-01T12:00:00Z", "workspaceUris": ["/home/oguz/my-app"]},
        {"created_at": "2026-01-01T12:05:00Z", "source": "USER_EXPLICIT", "content": "dikey dilim olarak yap, yarım bırakma"},
    ]
    (logs / "transcript.jsonl").write_text("\n".join(json.dumps(s) for s in steps) + "\n", encoding="utf-8")

    miner = SessionMiner(brain_roots=[brain], repo_path=tmp_path)
    mined = miner.mine_sessions()
    assert mined["total_sessions"] == 1
    assert "my-app" in mined["projects"]
    assert "Vertical Slice" in mined["projects"]["my-app"]["sessions"][0]["detected_intents"]
    assert "SESSION SUMMARY" in miner.format_sessions_report(mined, by_project=True)
    assert "INTENT MIRROR" in miner.format_intents_report(mined)
