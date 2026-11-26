import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.drift.state_store import DriftStateStore


def test_drift_state_store_roundtrip(tmp_path: Path) -> None:
    store = DriftStateStore.load_from_repo(tmp_path)
    store.update_record("core", "abc123", "docs/core/DOMAIN.md", ["tools/core/**"])
    reloaded = DriftStateStore.load_from_repo(tmp_path)
    rec = reloaded.get_record("core")
    assert rec is not None and rec.last_checked_sha == "abc123"
