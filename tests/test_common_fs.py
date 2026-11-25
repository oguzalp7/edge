"""
Hermetic tests for `tools.common.fs` and backward-compatible re-exports.

Covers worktree primary root resolution (`INV-TRACKER-WORKTREE-ROOT`), atomic
sibling `mkstemp` + `os.replace` writes (`INV-TRACKER-ATOMIC-IO`), error
cleanup with zero `.tmp` remnants, and `tasks_bridge` / `tools.common` identity.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import tools.common as common_pkg
import tools.common.fs as common_fs
from tools.brigade import tasks_bridge


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_temp_git_repo(repo_dir: Path) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Edge Test")
    (repo_dir / "README.md").write_text("# temp repo\n", encoding="utf-8")
    _git(repo_dir, "add", "README.md")
    _git(repo_dir, "commit", "-m", "initial commit")
    return repo_dir


def test_resolve_target_repo_root_primary_and_nested_subdir(tmp_path: Path) -> None:
    repo = _init_temp_git_repo(tmp_path / "primary")
    nested = repo / "src" / "nested"
    nested.mkdir(parents=True)

    assert common_fs.resolve_target_repo_root(repo) == repo.resolve()
    assert common_fs.resolve_target_repo_root(str(nested)) == repo.resolve()


def test_resolve_target_repo_root_worktree_anchors_to_primary(tmp_path: Path) -> None:
    repo = _init_temp_git_repo(tmp_path / "primary")
    worktree = tmp_path / "leased-worktree"
    _git(repo, "worktree", "add", str(worktree), "-b", "slice/test-wt")
    wt_nested = worktree / "packages" / "core"
    wt_nested.mkdir(parents=True)

    assert common_fs.resolve_target_repo_root(worktree) == repo.resolve()
    assert common_fs.resolve_target_repo_root(wt_nested) == repo.resolve()


def test_resolve_target_repo_root_non_git_fallback(tmp_path: Path) -> None:
    plain_dir = tmp_path / "non_git"
    plain_dir.mkdir()

    assert common_fs.resolve_target_repo_root(plain_dir) == plain_dir.resolve()


def test_resolve_target_repo_root_delegates_to_normalize_target_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    calls = []

    def fake_normalize(raw_path):
        calls.append(raw_path)
        return plain_dir.resolve()

    monkeypatch.setattr(common_fs, "normalize_target_path", fake_normalize)
    result = common_fs.resolve_target_repo_root("/home/oguz/fake-path")

    assert calls == ["/home/oguz/fake-path"]
    assert result == plain_dir.resolve()


def test_atomic_write_text_creates_parents_preserves_bytes_and_leaves_no_tmp(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "spec.md"
    payload = "---\r\ntitle: \"Edge: ÜĞİŞÖÇ\"\r\n---\r\nBody line\n\n"

    common_fs.atomic_write_text(target, payload)

    assert target.exists()
    assert target.read_bytes() == payload.encode("utf-8")
    siblings = [p.name for p in target.parent.iterdir()]
    assert siblings == ["spec.md"]


def test_atomic_write_text_uses_sibling_mkstemp_and_os_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "state.json"
    real_mkstemp = tempfile.mkstemp
    real_replace = os.replace
    recorded_mkstemp = []
    recorded_replace = []

    def spy_mkstemp(*args, **kwargs):
        recorded_mkstemp.append(kwargs.get("dir"))
        return real_mkstemp(*args, **kwargs)

    def spy_replace(src, dst):
        recorded_replace.append((Path(src).parent, Path(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(tempfile, "mkstemp", spy_mkstemp)
    monkeypatch.setattr(os, "replace", spy_replace)

    common_fs.atomic_write_text(target, "hello\n")

    assert recorded_mkstemp == [target.parent]
    assert recorded_replace == [(target.parent, target)]
    assert [p.name for p in target.parent.iterdir()] == ["state.json"]


def test_atomic_write_text_cleans_up_temp_on_replace_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config.json"
    target.write_text("original-content", encoding="utf-8")

    def boom_replace(src, dst):
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", boom_replace)

    with pytest.raises(OSError, match="simulated disk full"):
        common_fs.atomic_write_text(target, "corrupted-new-content")

    assert target.read_text(encoding="utf-8") == "original-content"
    assert [p.name for p in target.parent.iterdir()] == ["config.json"]


def test_atomic_write_json_formats_utf8_trailing_newline_and_cleans_on_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "sub" / "meta.json"
    payload = {"city": "İstanbul", "items": [1, 2], "ok": True}

    common_fs.atomic_write_json(target, payload)

    raw_text = target.read_text(encoding="utf-8")
    assert raw_text.endswith("\n")
    assert "İstanbul" in raw_text
    assert json.loads(raw_text) == payload
    assert [p.name for p in target.parent.iterdir()] == ["meta.json"]

    def boom_replace(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom_replace)
    with pytest.raises(OSError, match="replace failed"):
        common_fs.atomic_write_json(target, {"city": "Ankara"})

    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert [p.name for p in target.parent.iterdir()] == ["meta.json"]


def test_common_and_tasks_bridge_reexport_identity() -> None:
    assert common_pkg.resolve_target_repo_root is common_fs.resolve_target_repo_root
    assert common_pkg.atomic_write_text is common_fs.atomic_write_text
    assert common_pkg.atomic_write_json is common_fs.atomic_write_json

    assert tasks_bridge.resolve_target_repo_root is common_fs.resolve_target_repo_root
    assert tasks_bridge.atomic_write_text is common_fs.atomic_write_text
