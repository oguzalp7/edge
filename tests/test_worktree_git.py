#!/usr/bin/env python3
"""
Hermetic RED Contract & Real-Git Integration Tests for Session 3 — Slice 1:
Native git worktree fallback (tools/brigade/worktree_git.py),
2-branch router (tools/brigade/worktree.py), legacy mock seam (fsm_ops/constants.py),
zero-data-loss cleanup, orphan pruning, CLI wiring, and doc alignment.
"""

import ast
import hashlib
import importlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Hermetic Helpers
# ---------------------------------------------------------------------------


def _load_worktree_git():
    return importlib.import_module("tools.brigade.worktree_git")


def _load_worktree():
    return importlib.import_module("tools.brigade.worktree")


def _load_fsm_constants():
    return importlib.import_module("tools.brigade.fsm_ops.constants")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_git_repo(repo_dir: Path, base_branch: str = "main") -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    res = _git(repo_dir, "init")
    assert res.returncode == 0, res.stderr
    _git(repo_dir, "checkout", "-B", base_branch)
    _git(repo_dir, "config", "user.email", "edge-test@example.local")
    _git(repo_dir, "config", "user.name", "Edge Test")
    (repo_dir / "README.md").write_text("# Edge Test Repo\n", encoding="utf-8")
    _git(repo_dir, "add", "README.md")
    commit_res = _git(repo_dir, "commit", "-m", "chore: initial commit")
    assert commit_res.returncode == 0, commit_res.stderr
    return repo_dir


def _porcelain_worktree_paths(repo_dir: Path) -> List[Path]:
    res = _git(repo_dir, "worktree", "list", "--porcelain")
    assert res.returncode == 0, res.stderr
    paths: List[Path] = []
    for line in res.stdout.splitlines():
        if line.startswith("worktree "):
            raw = line[len("worktree ") :].strip()
            paths.append(Path(raw).resolve())
    return paths


def _branch_exists(repo_dir: Path, branch_name: str) -> bool:
    res = _git(repo_dir, "show-ref", "--verify", f"refs/heads/{branch_name}")
    return res.returncode == 0


def _list_branches(repo_dir: Path, prefix: str = "") -> List[str]:
    ref_root = f"refs/heads/{prefix}" if prefix else "refs/heads"
    res = _git(repo_dir, "for-each-ref", "--format=%(refname:short)", ref_root)
    assert res.returncode == 0, res.stderr
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]


def _opt_in_git_backend(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, backend: str = "git") -> Path:
    edge_home = tmp_path / "edge_home"
    edge_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EDGE_HOME", str(edge_home))
    monkeypatch.setenv("EDGE_WORKTREE_BACKEND", backend)
    return edge_home


# ---------------------------------------------------------------------------
# 1. Hermetic Isolation (tests/conftest.py)
# ---------------------------------------------------------------------------


def test_conftest_isolates_edge_home_and_defaults_backend_none() -> None:
    from tools.common.env import get_edge_home

    assert os.environ.get("EDGE_WORKTREE_BACKEND") == "none"
    edge_home = get_edge_home()
    assert str(edge_home) == os.environ.get("EDGE_HOME")
    assert edge_home.resolve() != (Path.home() / ".edge").resolve()


# ---------------------------------------------------------------------------
# 2. Layout, Sanitization, Capability & Native Path Detection
# ---------------------------------------------------------------------------


def test_pool_root_sanitization_capability_and_native_path_detection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    edge_home = _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()

    repo = _init_git_repo(tmp_path / "sample-repo")
    expected_sha = hashlib.sha1(str(repo.resolve()).encode("utf-8")).hexdigest()[:6]
    pool_root = wg.get_repo_pool_root(repo)
    assert pool_root == edge_home / "worktrees" / f"{repo.name}-{expected_sha}"
    assert not pool_root.resolve().is_relative_to(repo.resolve())

    assert wg.sanitize_branch_dir("feat/my slice@1") == "feat-my-slice-1"
    assert wg.sanitize_branch_dir("///   ///") == "slice"
    assert wg.sanitize_branch_dir("") == "slice"

    assert wg.is_git_worktree_capable(repo) is True
    non_git = tmp_path / "plain_dir"
    non_git.mkdir()
    assert wg.is_git_worktree_capable(non_git) is False

    with monkeypatch.context() as mp:
        mp.setattr(shutil, "which", lambda _name: None)
        assert wg.is_git_worktree_capable(repo) is False

    inside_pool = edge_home / "worktrees" / "repo-123456" / "feat-a"
    assert wg.is_native_worktree_path(str(inside_pool)) is True
    assert wg.is_native_worktree_path("/home/oguz/.treehouse/pool/slot-1") is False
    assert wg.is_native_worktree_path(str(repo)) is False

    # External git worktree directory with .git file ("gitdir: ...") is detected as native
    ext_wt = tmp_path / "external_wt"
    res = _git(repo, "worktree", "add", "-b", "feat/ext-detect", str(ext_wt))
    assert res.returncode == 0, res.stderr
    assert wg.is_native_worktree_path(str(ext_wt)) is True


# ---------------------------------------------------------------------------
# 3. acquire_git_worktree Contracts & Zero-Touch Primary Invariant
# ---------------------------------------------------------------------------


def test_acquire_git_worktree_isolates_outside_repo_and_keeps_primary_untouched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    edge_home = _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "app-repo", base_branch="main")

    ok, wt_path, err = wg.acquire_git_worktree(repo, "feat/native-wt")
    assert ok is True, err
    assert err == ""

    wt_dir = Path(wt_path)
    expected_sha = hashlib.sha1(str(repo.resolve()).encode("utf-8")).hexdigest()[:6]
    assert wt_dir.is_dir()
    assert wt_dir.resolve() == (edge_home / "worktrees" / f"{repo.name}-{expected_sha}" / "feat-native-wt").resolve()
    assert not wt_dir.resolve().is_relative_to(repo.resolve())
    assert wt_dir.resolve() in _porcelain_worktree_paths(repo)

    wt_branch = _git(wt_dir, "branch", "--show-current").stdout.strip()
    assert wt_branch == "feat/native-wt"

    # Zero-Touch Primary Invariant: mutating & committing inside worktree leaves primary repo clean on main
    (wt_dir / "feature.py").write_text("VALUE = 42\n", encoding="utf-8")
    _git(wt_dir, "add", "feature.py")
    assert _git(wt_dir, "commit", "-m", "feat: add feature module").returncode == 0

    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""
    assert not (repo / "feature.py").exists()


def test_acquire_git_worktree_existing_branch_reuse_and_stale_dir_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "reuse-repo", base_branch="main")

    # Pre-create branch with a commit while primary stays on main
    assert _git(repo, "checkout", "-b", "feat/preexisting").returncode == 0
    (repo / "pre.txt").write_text("preexisting\n", encoding="utf-8")
    _git(repo, "add", "pre.txt")
    assert _git(repo, "commit", "-m", "feat: preexisting commit").returncode == 0
    assert _git(repo, "checkout", "main").returncode == 0

    ok1, wt_path1, err1 = wg.acquire_git_worktree(repo, "feat/preexisting")
    assert ok1 is True, err1
    assert (Path(wt_path1) / "pre.txt").is_file()

    # Re-acquiring already-registered branch reuses the active worktree cleanly
    ok2, wt_path2, err2 = wg.acquire_git_worktree(repo, "feat/preexisting")
    assert ok2 is True, err2
    assert Path(wt_path2).resolve() == Path(wt_path1).resolve()

    # Unregistered stale directory at target slot path is cleaned before registering
    pool_root = wg.get_repo_pool_root(repo)
    stale_dir = pool_root / "feat-stale-slot"
    stale_dir.mkdir(parents=True, exist_ok=True)
    (stale_dir / "orphan.txt").write_text("stale", encoding="utf-8")

    ok3, wt_path3, err3 = wg.acquire_git_worktree(repo, "feat/stale-slot")
    assert ok3 is True, err3
    assert Path(wt_path3).resolve() == stale_dir.resolve()
    assert not (Path(wt_path3) / "orphan.txt").exists()


def test_acquire_git_worktree_fails_cleanly_on_invalid_missing_or_unborn_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()

    missing = tmp_path / "does_not_exist"
    ok_missing, wt_missing, err_missing = wg.acquire_git_worktree(missing, "feat/a")
    assert ok_missing is False and wt_missing == "" and err_missing

    non_git = tmp_path / "plain"
    non_git.mkdir()
    ok_plain, wt_plain, err_plain = wg.acquire_git_worktree(non_git, "feat/a")
    assert ok_plain is False and wt_plain == "" and err_plain

    unborn = tmp_path / "unborn_git"
    unborn.mkdir()
    assert _git(unborn, "init").returncode == 0
    ok_unborn, wt_unborn, err_unborn = wg.acquire_git_worktree(unborn, "feat/a")
    assert ok_unborn is False and wt_unborn == "" and err_unborn


# ---------------------------------------------------------------------------
# 4. return_git_worktree Cleanup Paths (Merged, Unmerged PR, Abort +/- Commits)
# ---------------------------------------------------------------------------


def test_return_git_worktree_merged_branch_removes_prunes_and_deletes_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "merge-repo", base_branch="main")

    ok, wt_path, err = wg.acquire_git_worktree(repo, "feat/merged-slice")
    assert ok is True, err
    wt_dir = Path(wt_path)
    (wt_dir / "delivered.py").write_text("ok = True\n", encoding="utf-8")
    _git(wt_dir, "add", "delivered.py")
    assert _git(wt_dir, "commit", "-m", "feat: merged slice").returncode == 0

    # Fast-forward merge into main before returning worktree
    assert _git(repo, "merge", "--ff-only", "feat/merged-slice").returncode == 0

    ret_ok, ret_msg = wg.return_git_worktree(
        repo,
        wt_path,
        force=False,
        base_branch="main",
        preserve_commits=False,
    )
    assert ret_ok is True, ret_msg
    assert not wt_dir.exists()
    assert wt_dir.resolve() not in _porcelain_worktree_paths(repo)
    assert _branch_exists(repo, "feat/merged-slice") is False
    assert (repo / "delivered.py").is_file()


def test_return_git_worktree_unmerged_pr_branch_keeps_branch_and_guards_dirty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "pr-repo", base_branch="main")

    ok, wt_path, err = wg.acquire_git_worktree(repo, "feat/open-pr")
    assert ok is True, err
    wt_dir = Path(wt_path)
    (wt_dir / "pr_file.py").write_text("pr = 1\n", encoding="utf-8")
    _git(wt_dir, "add", "pr_file.py")
    assert _git(wt_dir, "commit", "-m", "feat: pr work").returncode == 0
    pr_sha = _git(wt_dir, "rev-parse", "HEAD").stdout.strip()

    # Uncommitted file blocks non-forced return
    (wt_dir / "uncommitted.txt").write_text("wip\n", encoding="utf-8")
    dirty_ok, dirty_err = wg.return_git_worktree(
        repo,
        wt_path,
        force=False,
        base_branch="main",
        preserve_commits=False,
    )
    assert dirty_ok is False and dirty_err
    assert (wt_dir / "uncommitted.txt").is_file()

    # Commit remaining work so worktree is clean, then return as unmerged PR
    _git(wt_dir, "add", "uncommitted.txt")
    assert _git(wt_dir, "commit", "-m", "feat: finish pr work").returncode == 0
    latest_sha = _git(wt_dir, "rev-parse", "HEAD").stdout.strip()
    assert latest_sha != pr_sha

    ret_ok, ret_msg = wg.return_git_worktree(
        repo,
        wt_path,
        force=False,
        base_branch="main",
        preserve_commits=False,
    )
    assert ret_ok is True, ret_msg
    assert not wt_dir.exists()
    assert wt_dir.resolve() not in _porcelain_worktree_paths(repo)
    assert _branch_exists(repo, "feat/open-pr") is True
    assert _git(repo, "rev-parse", "feat/open-pr").stdout.strip() == latest_sha


def test_return_git_worktree_abort_with_commits_preserves_to_aborted_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "abort-commits-repo", base_branch="main")

    ok, wt_path, err = wg.acquire_git_worktree(repo, "feat/abort-with-commits")
    assert ok is True, err
    wt_dir = Path(wt_path)
    (wt_dir / "work.py").write_text("important = 1\n", encoding="utf-8")
    _git(wt_dir, "add", "work.py")
    assert _git(wt_dir, "commit", "-m", "wip: valuable commit").returncode == 0
    saved_sha = _git(wt_dir, "rev-parse", "HEAD").stdout.strip()

    # Also leave dirty scratch file to verify force=True removes worktree cleanly
    (wt_dir / "dirty.tmp").write_text("scratch", encoding="utf-8")

    ret_ok, ret_msg = wg.return_git_worktree(
        repo,
        wt_path,
        force=True,
        base_branch="main",
        preserve_commits=True,
    )
    assert ret_ok is True, ret_msg
    assert not wt_dir.exists()
    assert wt_dir.resolve() not in _porcelain_worktree_paths(repo)
    assert _branch_exists(repo, "feat/abort-with-commits") is False

    aborted_branches = _list_branches(repo, "edge/aborted/")
    matching = [b for b in aborted_branches if b.startswith("edge/aborted/feat-abort-with-commits-")]
    assert len(matching) == 1, f"Expected preserved aborted branch, got: {aborted_branches}"
    assert re.match(r"^edge/aborted/feat-abort-with-commits-\d{8}-\d{6}", matching[0])
    assert _git(repo, "rev-parse", matching[0]).stdout.strip() == saved_sha


def test_return_git_worktree_abort_zero_commits_deletes_empty_branch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "abort-empty-repo", base_branch="main")

    ok, wt_path, err = wg.acquire_git_worktree(repo, "feat/abort-empty")
    assert ok is True, err
    wt_dir = Path(wt_path)
    (wt_dir / "dirty.txt").write_text("uncommitted", encoding="utf-8")

    ret_ok, ret_msg = wg.return_git_worktree(
        repo,
        wt_path,
        force=True,
        base_branch="main",
        preserve_commits=True,
    )
    assert ret_ok is True, ret_msg
    assert not wt_dir.exists()
    assert wt_dir.resolve() not in _porcelain_worktree_paths(repo)
    assert _branch_exists(repo, "feat/abort-empty") is False
    assert not [b for b in _list_branches(repo, "edge/aborted/") if "feat-abort-empty" in b]


# ---------------------------------------------------------------------------
# 5. Orphan Pruning & CLI Wiring (`brigade worktree --action prune`)
# ---------------------------------------------------------------------------


def test_prune_git_worktrees_and_brigade_cli_worktree_prune(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "prune-repo", base_branch="main")

    ok_a, wt_active, err_a = wg.acquire_git_worktree(repo, "feat/active-wt")
    ok_s, wt_stale, err_s = wg.acquire_git_worktree(repo, "feat/stale-wt")
    assert ok_a and ok_s, (err_a, err_s)

    # Simulate crashed/deleted worktree directory + unregistered orphan directory in pool root
    shutil.rmtree(wt_stale)
    orphan_dir = wg.get_repo_pool_root(repo) / "orphan-slot"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "leftover.txt").write_text("leftover", encoding="utf-8")

    prune_ok, prune_msg = wg.prune_git_worktrees(repo)
    assert prune_ok is True, prune_msg
    assert not orphan_dir.exists()
    assert Path(wt_stale).resolve() not in _porcelain_worktree_paths(repo)
    assert Path(wt_active).is_dir()
    assert Path(wt_active).resolve() in _porcelain_worktree_paths(repo)

    # Recreate another orphan directory and verify CLI wiring: `brigade worktree <repo> --action prune`
    orphan_cli = wg.get_repo_pool_root(repo) / "orphan-cli"
    orphan_cli.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("tools.brigade.worktree.is_treehouse_installed", lambda: False)

    parser = importlib.import_module("tools.brigade.cli_ops.parser").build_parser()
    parsed = parser.parse_args(["worktree", str(repo), "--action", "prune"])
    assert parsed.action == "prune"

    brigade_cli = importlib.import_module("tools.brigade.cli")
    monkeypatch.setattr(sys, "argv", ["brigade", "worktree", str(repo), "--action", "prune"])
    capsys.readouterr()
    rc = brigade_cli.main()
    out = capsys.readouterr().out
    assert rc == 0, out
    assert not orphan_cli.exists()


# ---------------------------------------------------------------------------
# 6. worktree.py Router, constants.py Seam, Exports & FSM Integration
# ---------------------------------------------------------------------------


def test_worktree_router_dispatch_and_exports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    edge_home = _opt_in_git_backend(monkeypatch, tmp_path, backend="auto")
    wt_mod = _load_worktree()
    wg = _load_worktree_git()
    repo = _init_git_repo(tmp_path / "router-repo", base_branch="main")

    # 1. Treehouse present + auto -> acquire_worktree & get_pool_status route to treehouse
    calls: List[List[str]] = []

    def fake_treehouse_run(cmd, cwd=None, timeout=60):
        calls.append(list(cmd))
        if cmd[:2] == ["treehouse", "get"]:
            return 0, '{"path": "/home/oguz/.treehouse/pool/slot-9"}', ""
        if cmd[:2] == ["treehouse", "status"]:
            return 0, "slot-9 available", ""
        if cmd[:2] == ["treehouse", "return"]:
            return 0, "returned to treehouse", ""
        return 1, "", f"unexpected cmd: {cmd}"

    with monkeypatch.context() as mp:
        mp.setattr(wt_mod, "is_treehouse_installed", lambda: True)
        mp.setattr(wt_mod, "run_command", fake_treehouse_run)

        ok_th, path_th, err_th = wt_mod.acquire_worktree(repo, "feat/via-treehouse")
        assert ok_th is True and path_th == "/home/oguz/.treehouse/pool/slot-9", err_th
        ok_st, out_st, _ = wt_mod.get_pool_status(repo)
        assert ok_st is True and "slot-9" in out_st
        assert any(c[:2] == ["treehouse", "get"] for c in calls)
        assert any(c[:2] == ["treehouse", "status"] for c in calls)

    # 2. Treehouse absent + auto -> acquire_worktree & get_pool_status fall back to worktree_git
    monkeypatch.setattr(wt_mod, "is_treehouse_installed", lambda: False)

    ok_git, path_git, err_git = wt_mod.acquire_worktree(repo, "feat/via-git-fallback")
    assert ok_git is True, err_git
    assert Path(path_git).resolve().is_relative_to((edge_home / "worktrees").resolve())

    ok_git_st, out_git_st, err_git_st = wt_mod.get_pool_status(repo)
    assert ok_git_st is True, err_git_st
    assert "feat/via-git-fallback" in out_git_st or Path(path_git).name in out_git_st

    # 3. return_worktree routes native paths to return_git_worktree even if treehouse IS installed,
    #    and routes ~/.treehouse/... paths to treehouse return without calling return_git_worktree.
    th_return_calls: List[List[str]] = []

    def spy_treehouse_return(cmd, cwd=None, timeout=60):
        th_return_calls.append(list(cmd))
        return 0, "Treehouse returned", ""

    monkeypatch.setattr(wt_mod, "is_treehouse_installed", lambda: True)
    monkeypatch.setattr(wt_mod, "run_command", spy_treehouse_return)

    ok_ret_native, msg_ret_native = wt_mod.return_worktree(
        repo,
        path_git,
        force=True,
        base_branch="main",
        preserve_commits=True,
    )
    assert ok_ret_native is True, msg_ret_native
    assert not Path(path_git).exists()
    assert th_return_calls == []

    def _forbid_git_return(*_args, **_kwargs):
        raise AssertionError("return_git_worktree must not run for treehouse path")

    monkeypatch.setattr(wg, "return_git_worktree", _forbid_git_return)
    if hasattr(wt_mod, "return_git_worktree"):
        monkeypatch.setattr(wt_mod, "return_git_worktree", _forbid_git_return)
    ok_ret_th, msg_ret_th = wt_mod.return_worktree(
        repo,
        "/home/oguz/.treehouse/pool/slot-1",
        force=False,
    )
    assert ok_ret_th is True, msg_ret_th
    assert th_return_calls == [["treehouse", "return", "/home/oguz/.treehouse/pool/slot-1"]]

    # 4. Facade re-exports
    fsm_mod = importlib.import_module("tools.brigade.fsm")
    cli_mod = importlib.import_module("tools.brigade.cli")
    for sym in ("is_worktree_backend_available", "prune_worktrees"):
        assert callable(getattr(wt_mod, sym))
        assert callable(getattr(fsm_mod, sym))
        assert callable(getattr(cli_mod, sym))


def test_should_lease_worktree_legacy_mocks_and_fsm_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    constants = _load_fsm_constants()
    wt_mod = _load_worktree()
    fsm_mod = importlib.import_module("tools.brigade.fsm")
    repo = _init_git_repo(tmp_path / "fsm-repo", base_branch="main")
    non_git = tmp_path / "non-git-dir"
    non_git.mkdir()

    # 1. Default conftest EDGE_WORKTREE_BACKEND=none skips leasing (without legacy mock)
    assert constants.should_lease_worktree(repo) is False
    assert wt_mod.is_worktree_backend_available(repo) is False

    # 2. Legacy fsm.is_treehouse_installed mock overrides EDGE_WORKTREE_BACKEND=none (True) & auto (False)
    with monkeypatch.context() as mp:
        mp.setattr(fsm_mod, "is_treehouse_installed", lambda: True)
        assert constants.should_lease_worktree(repo) is True

        mp.setenv("EDGE_WORKTREE_BACKEND", "auto")
        mp.setattr(fsm_mod, "is_treehouse_installed", lambda: False)
        assert constants.should_lease_worktree(repo) is False

    # 3. Auto on non-git returns False when treehouse is absent; EDGE_WORKTREE_BACKEND=git + FSM lifecycle
    with monkeypatch.context() as mp:
        mp.setenv("EDGE_WORKTREE_BACKEND", "auto")
        mp.setattr(wt_mod, "is_treehouse_installed", lambda: False)
        assert wt_mod.is_worktree_backend_available(non_git) is False
        assert wt_mod.is_worktree_backend_available(repo) is True

    edge_home = _opt_in_git_backend(monkeypatch, tmp_path, backend="git")
    monkeypatch.setattr(wt_mod, "is_treehouse_installed", lambda: False)
    monkeypatch.setattr(fsm_mod.BrigadeFSM, "_run_radar_rescan", lambda self: None)

    assert wt_mod.is_worktree_backend_available(repo) is True
    assert constants.should_lease_worktree(repo) is True

    fsm = fsm_mod.BrigadeFSM(repo)
    fsm.state.base_branch = "main"
    fsm.save()

    ok_start, ticket, msg_start = fsm.start_slice(name="native-slice", track="feature")
    assert ok_start is True and ticket is not None, msg_start
    assert ticket.worktree_path
    wt_dir = Path(ticket.worktree_path)
    assert wt_dir.resolve().is_relative_to((edge_home / "worktrees").resolve())

    # Commit inside worktree, finish_slice -> FF merge into main, delete branch, remove worktree
    (wt_dir / "slice.py").write_text("x = 1\n", encoding="utf-8")
    _git(wt_dir, "add", "slice.py")
    assert _git(wt_dir, "commit", "-m", "feat: native slice").returncode == 0

    fsm.state.current_state = importlib.import_module("tools.brigade.models").CycleState.STAGING
    fsm.save()
    fin_ok, fin_msg = fsm.finish_slice()
    assert fin_ok is True, fin_msg
    assert not wt_dir.exists()
    assert _branch_exists(repo, "feat/native-slice") is False
    assert (repo / "slice.py").is_file()

    # Start second slice, commit, then abort -> preserves commits on edge/aborted/...
    ok_ab, ab_ticket, msg_ab = fsm.start_slice(name="native-abort", track="feature")
    assert ok_ab is True and ab_ticket is not None, msg_ab
    ab_wt = Path(ab_ticket.worktree_path)
    (ab_wt / "aborted_work.py").write_text("keep = True\n", encoding="utf-8")
    _git(ab_wt, "add", "aborted_work.py")
    assert _git(ab_wt, "commit", "-m", "wip: aborted commit").returncode == 0
    ab_sha = _git(ab_wt, "rev-parse", "HEAD").stdout.strip()

    fsm.abort(reason="Dead end during test", force=True)
    assert not ab_wt.exists()
    assert _branch_exists(repo, "feat/native-abort") is False
    aborted_branches = _list_branches(repo, "edge/aborted/")
    preserved = [b for b in aborted_branches if b.startswith("edge/aborted/feat-native-abort-")]
    assert len(preserved) == 1, f"Expected preserved branch on abort, got: {aborted_branches}"
    assert _git(repo, "rev-parse", preserved[0]).stdout.strip() == ab_sha


# ---------------------------------------------------------------------------
# 7. Module Hygiene & Documentation Alignment
# ---------------------------------------------------------------------------


def test_worktree_modules_hygiene_sloc_cc_and_ontology_headers() -> None:
    from tools.gate_cc import compute_source_max_cc, count_source_sloc

    worktree_git_path = REPO_ROOT / "tools" / "brigade" / "worktree_git.py"
    assert worktree_git_path.is_file(), "Missing tools/brigade/worktree_git.py"
    git_src = worktree_git_path.read_text(encoding="utf-8")
    assert count_source_sloc(git_src, ".py") <= 200
    max_cc_git, fn_git = compute_source_max_cc(git_src, ".py")
    assert max_cc_git <= 10, f"worktree_git.py max CC exceeded 10: {fn_git}={max_cc_git}"

    top_30 = "\n".join(git_src.splitlines()[:30])
    for tag in ("@intent", "@concepts", "@invariants"):
        assert tag in top_30, f"worktree_git.py missing {tag} in top 30 lines"

    stdlib_names = sys.stdlib_module_names
    tree = ast.parse(git_src, filename=str(worktree_git_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in stdlib_names or top == "tools"
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            top = node.module.split(".")[0]
            assert top in stdlib_names or top == "tools"

    worktree_path = REPO_ROOT / "tools" / "brigade" / "worktree.py"
    wt_src = worktree_path.read_text(encoding="utf-8")
    assert count_source_sloc(wt_src, ".py") <= 150
    max_cc_wt, fn_wt = compute_source_max_cc(wt_src, ".py")
    assert max_cc_wt <= 10, f"worktree.py max CC exceeded 10: {fn_wt}={max_cc_wt}"


def test_rules_and_skill_docs_document_native_git_worktree_and_share_fallback() -> None:
    agents_text = (REPO_ROOT / "rules" / "AGENTS.md").read_text(encoding="utf-8")
    sec_match = re.search(r"##\s+.*?0\.1\b(.*?)(?=\n---|\n##\s)", agents_text, re.DOTALL)
    assert sec_match is not None, "Missing Rule 0.1 section in rules/AGENTS.md"
    sec01 = sec_match.group(1).lower()

    assert "git worktree" in sec01, "rules/AGENTS.md §0.1 must document native git worktree fallback"
    assert "workspace" in sec01 and "share" in sec01, (
        "rules/AGENTS.md §0.1 must document Antigravity workspace='share' fallback"
    )
    assert any(tok in sec01 for tok in ("fallback", "yedek", "alternatif")), (
        "rules/AGENTS.md §0.1 must state worktree fallback hierarchy"
    )
    assert any(tok in sec01 for tok in ("prune", "cleanup", "temiz", "iade", "abort")), (
        "rules/AGENTS.md §0.1 must document worktree cleanup"
    )

    skill_text = (REPO_ROOT / "skills" / "edge-brigade" / "SKILL.md").read_text(encoding="utf-8")
    skill_low = skill_text.lower()
    assert "git worktree" in skill_low
    assert "fallback" in skill_low
    assert "--action prune" in skill_text
    assert ("workspace" in skill_low and "share" in skill_low) or "edge/aborted" in skill_text
