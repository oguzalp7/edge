"""Companion unit tests for tools.gnhf.harvest and tools.gnhf.harvest_git."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pathlib import Path
from types import SimpleNamespace

from tools.gnhf import harvest, harvest_git


def test_parse_worktree_porcelain_and_blocker_lines(tmp_path: Path) -> None:
    raw = (
        f"worktree {tmp_path}/wt1\n"
        "HEAD abcdef123456\n"
        "branch refs/heads/gnhf/slice-a\n\n"
        f"worktree {tmp_path}/main\n"
        "branch refs/heads/main\n"
    )
    blocks = harvest_git._parse_worktree_porcelain(raw)
    assert len(blocks) == 2
    assert blocks[0]["branch"] == "refs/heads/gnhf/slice-a"

    notes = tmp_path / ".gnhf" / "notes.md"
    notes.parent.mkdir(parents=True)
    notes.write_text(
        "ok line\n[SKIPPED-NEEDS-HITL] src/a.py: needs manual review\n[SKIPPED-NEEDS-HITL] src/b.py\n",
        encoding="utf-8",
    )
    blockers = harvest_git._extract_blockers(tmp_path)
    assert [(b.file_path, b.reason) for b in blockers] == [
        ("src/a.py", "needs manual review"),
        ("src/b.py", ""),
    ]


def test_harvest_worktree_missing_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(harvest, "get_gnhf_status", lambda _p: [])
    res_missing = harvest.harvest_worktree(tmp_path, branch_name="gnhf/none")
    assert not res_missing.gate_passed
    assert "not found" in (res_missing.error or "")

    monkeypatch.setattr(
        harvest,
        "get_gnhf_status",
        lambda _p: [
            harvest.GnhfWorktreeStatus(
                worktree_path=tmp_path,
                branch_name="gnhf/slice-a",
                base_branch="main",
                commits_ahead=1,
                last_commit_hash="abc123",
                last_commit_subject="test",
                last_commit_timestamp="2026-01-01T00:00:00Z",
            )
        ],
    )
    monkeypatch.setattr(
        harvest.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=" 1 file changed\n", stderr=""),
    )
    monkeypatch.setattr(harvest, "_run_gate", lambda *_a, **_kw: (True, 0, "PASS"))
    res_dry = harvest.harvest_worktree(tmp_path, branch_name="slice-a", base_branch="main", dry_run=True)
    assert res_dry.gate_passed
    assert not res_dry.merged
