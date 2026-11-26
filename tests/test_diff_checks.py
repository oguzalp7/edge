"""Companion unit tests for tools.drift.diff_checks."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pathlib import Path

from tools.drift.diff_checks import check_drift, get_changed_files_since, get_head_sha


def test_diff_checks_empty_repo_and_git_helpers(tmp_path: Path) -> None:
    def fake_runner(cmd, **_kw):
        if "rev-parse" in cmd:
            return 0, "abc123\n", ""
        if "diff" in cmd:
            return 0, "tools/a.py\n", ""
        return 1, "", "err"

    assert get_head_sha(tmp_path, runner=fake_runner) == "abc123"
    assert get_changed_files_since(tmp_path, "000", runner=fake_runner) == ["tools/a.py"]
    assert get_changed_files_since(tmp_path, "", runner=fake_runner) is None
    assert check_drift(tmp_path, runner=fake_runner) == []
