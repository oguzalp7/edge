"""
Hermetic RED contract tests for `tools.tracker` (Slice 1: Tracker Core Adapter).

Covers:
- Data models & canonical label taxonomy
- Backend resolution matrix & fail-fast auth/network vs 403 rate-limit policy
- Raw runner & `temp_body_file` (`mkstemp`, closed before subprocess, `to_wsl_path`, unlink)
- `GhAxiBackend` + `graphql.py` (TOON/URL create parse, lossless GraphQL JSON reads)
- `GhCliBackend` + `graphql.py` (`addSubIssue` with `replaceParent`, `removeSubIssue`, paginated `subIssues`)
- `LocalTrackerBackend` (CRUD, bidirectional sub-issues, `O_CREAT|O_EXCL` retry, worktree root)
- `cache.py` & `cli.py` (all 9 subcommands, `--json`, `.gitignore`, exit codes 0/1/2)
- Static invariants (`INV-ORCH-HOOK-LATENCY`, `INV-TRACKER-STDLIB-ONLY`, `INV-TRACKER-FILE-BUDGET`)
"""

import ast
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.tracker import backends, cache, cli, graphql
from tools.tracker.gh_axi_backend import GhAxiBackend
from tools.tracker.gh_cli_backend import GhCliBackend
from tools.tracker.local_backend import LocalTrackerBackend
from tools.tracker.models import (
    CANONICAL_LABELS,
    TrackerAuthError,
    TrackerComment,
    TrackerError,
    TrackerIssue,
    TrackerNotFoundError,
)

TRICKY_MARKDOWN_BODY = (
    "---\r\n"
    "expected_files:\r\n"
    "  - tools/tracker/cli.py\r\n"
    "---\r\n"
    "\r\n"
    "# Spec: Edge \"Quotes\" & Colons: Alpha\r\n\r\n"
    "Key: value: nested: colon\n"
    "Lone double quote: \"\n\n"
    "```python\n"
    "def hello():\n"
    "    return \"world\"\n"
    "```\n\n"
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _init_git_repo(repo_dir: Path, remote_url: Optional[str] = None) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(repo_dir, "init")
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Edge Test")
    (repo_dir / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(repo_dir, "add", "README.md")
    _git(repo_dir, "commit", "-m", "init")
    if remote_url:
        _git(repo_dir, "remote", "add", "origin", remote_url)
    return repo_dir


def _gql_issue_node(
    number: int,
    *,
    title: str = "Issue",
    body: str = "",
    state: str = "OPEN",
    labels: Optional[List[str]] = None,
    parent_number: Optional[int] = None,
    subissues: Optional[List[int]] = None,
    comments: Optional[List[Dict[str, Any]]] = None,
    url: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": f"I_node_{number}",
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "url": url or f"https://github.com/acme/widgets/issues/{number}",
        "createdAt": "2026-11-25T10:00:00Z",
        "updatedAt": "2026-11-25T10:05:00Z",
        "closedAt": "2026-11-25T10:10:00Z" if state == "CLOSED" else None,
        "labels": {"nodes": [{"name": lbl} for lbl in (labels or [])]},
        "parent": {"number": parent_number} if parent_number is not None else None,
        "subIssues": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"number": n} for n in (subissues or [])],
        },
        "comments": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": comments or [],
        },
    }


def _extract_flag_value(cmd: List[str], flag: str) -> Optional[str]:
    for idx, token in enumerate(cmd):
        if token == flag and idx + 1 < len(cmd):
            return cmd[idx + 1]
        if token.startswith(f"{flag}="):
            return token.split("=", 1)[1]
    return None


def _patch_which(monkeypatch: pytest.MonkeyPatch, available: Set[str]) -> None:
    def fake_which(name: str, *args: Any, **kwargs: Any) -> Optional[str]:
        return f"/usr/local/bin/{name}" if name in available else None

    monkeypatch.setattr(shutil, "which", fake_which)


# =============================================================================
# 1. Models & Canonical Label Taxonomy
# =============================================================================


class TestTrackerModels:
    def test_canonical_labels_taxonomy_and_hex_colors(self) -> None:
        expected = {
            "type:frontier",
            "spec:draft",
            "spec:approved",
            "status:ready",
            "status:in-progress",
            "status:done",
            "track:feature",
            "track:core",
            "track:ui",
            "track:bug",
        }
        assert set(CANONICAL_LABELS.keys()) == expected
        for name, (hex_color, desc) in CANONICAL_LABELS.items():
            assert re.fullmatch(r"[0-9a-fA-F]{6}", hex_color), f"Invalid hex color on {name}: {hex_color}"
            assert isinstance(desc, str) and desc.strip(), f"Empty description on {name}"

    def test_tracker_comment_roundtrip_and_schema_resilience(self) -> None:
        comment = TrackerComment.from_dict(
            {
                "id": "C_1",
                "author": {"login": "octocat"},
                "body": TRICKY_MARKDOWN_BODY,
                "createdAt": "2026-11-25T12:00:00Z",
                "unexpected_extra": 99,
            }
        )
        assert comment.id == "C_1"
        assert comment.author == "octocat"
        assert comment.body == TRICKY_MARKDOWN_BODY
        assert comment.created_at == "2026-11-25T12:00:00Z"

        reloaded = TrackerComment.from_dict(comment.to_dict())
        assert reloaded == comment

    def test_tracker_issue_roundtrip_and_schema_resilience(self) -> None:
        issue = TrackerIssue.from_dict(
            {
                "number": 42,
                "title": "Tracker SSOT",
                "body": TRICKY_MARKDOWN_BODY,
                "state": "OPEN",
                "labels": [{"name": "type:frontier"}, "spec:draft"],
                "parent": {"number": 7},
                "subissues": [{"number": 43}, 44],
                "comments": [{"id": "C_1", "author": "bot", "body": "ok"}],
                "backend": "gh-axi",
                "unknown_field": {"nested": True},
            }
        )
        assert issue.number == 42
        assert issue.state == "open"
        assert issue.body == TRICKY_MARKDOWN_BODY
        assert issue.labels == ["type:frontier", "spec:draft"]
        assert issue.parent_number == 7
        assert issue.subissues == [43, 44]
        assert len(issue.comments) == 1
        assert issue.comments[0].author == "bot"

        roundtrip = TrackerIssue.from_dict(issue.to_dict())
        assert roundtrip == issue

    def test_tracker_exception_exit_codes(self) -> None:
        err = TrackerError("boom")
        not_found = TrackerNotFoundError("missing #99")
        auth = TrackerAuthError("401 unauthorized")

        assert err.exit_code == 1
        assert not_found.exit_code == 1
        assert auth.exit_code == 2
        assert isinstance(auth, TrackerError)


# =============================================================================
# 2. Backend Resolution Matrix, Fail-Fast Auth & Runner
# =============================================================================


class TestBackendResolutionAndRunner:
    def test_offline_env_and_explicit_local_override_remote(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        _patch_which(monkeypatch, {"gh-axi", "gh"})

        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        assert isinstance(backends.resolve_backend(repo, offline=True), LocalTrackerBackend)
        assert isinstance(backends.resolve_backend(repo, backend="local"), LocalTrackerBackend)

        monkeypatch.setenv("EDGE_TRACKER", "local")
        assert isinstance(backends.resolve_backend(repo, backend="auto"), LocalTrackerBackend)

    def test_no_github_remote_or_non_github_remote_selects_local(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        monkeypatch.delenv("GH_HOST", raising=False)
        _patch_which(monkeypatch, {"gh-axi", "gh"})

        no_remote_repo = _init_git_repo(tmp_path / "no_remote")
        gitlab_repo = _init_git_repo(tmp_path / "gitlab_repo", "https://gitlab.com/acme/widgets.git")

        assert backends.has_github_remote(no_remote_repo) is False
        assert backends.has_github_remote(gitlab_repo) is False
        assert isinstance(backends.resolve_backend(no_remote_repo), LocalTrackerBackend)
        assert isinstance(backends.resolve_backend(gitlab_repo), LocalTrackerBackend)

    def test_gh_host_and_ghe_ssh_remote_detection(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        _patch_which(monkeypatch, {"gh-axi", "gh"})

        ghe_https = _init_git_repo(tmp_path / "ghe_https", "https://ghe.corp.internal/acme/app.git")
        ghe_ssh = _init_git_repo(tmp_path / "ghe_ssh", "git@ghe-alias:acme/app.git")

        monkeypatch.setenv("GH_HOST", "ghe.corp.internal")
        assert backends.has_github_remote(ghe_https) is True
        assert backends.has_github_remote(ghe_ssh) is True
        assert isinstance(backends.resolve_backend(ghe_https), GhAxiBackend)
        assert isinstance(backends.resolve_backend(ghe_ssh), GhAxiBackend)

    def test_auto_prefers_gh_axi_then_gh_else_raises_auth_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        repo = _init_git_repo(tmp_path / "repo", "git@github.com:acme/widgets.git")

        _patch_which(monkeypatch, {"gh-axi", "gh"})
        assert isinstance(backends.resolve_backend(repo), GhAxiBackend)

        _patch_which(monkeypatch, {"gh"})
        assert isinstance(backends.resolve_backend(repo), GhCliBackend)

        _patch_which(monkeypatch, set())
        with pytest.raises(TrackerAuthError) as exc_info:
            backends.resolve_backend(repo)
        assert exc_info.value.exit_code == 2
        assert "--offline" in str(exc_info.value) or "EDGE_TRACKER=local" in str(exc_info.value)

    def test_explicit_backend_missing_binary_fails_fast_without_local_fallback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        no_remote_repo = _init_git_repo(tmp_path / "plain")

        _patch_which(monkeypatch, {"gh"})
        with pytest.raises(TrackerAuthError) as exc_axi:
            backends.resolve_backend(no_remote_repo, backend="gh-axi")
        assert exc_axi.value.exit_code == 2

        _patch_which(monkeypatch, set())
        with pytest.raises(TrackerAuthError) as exc_gh:
            backends.resolve_backend(no_remote_repo, backend="gh")
        assert exc_gh.value.exit_code == 2

    @pytest.mark.parametrize(
        ("rc", "stderr"),
        [
            (1, "HTTP 401: Requires authentication"),
            (1, "AUTH_REQUIRED: please log in"),
            (1, "Bad credentials"),
            (1, "You are not logged into any GitHub hosts. Run gh auth login"),
            (1, "could not resolve host: api.github.com"),
            (1, "dial tcp: connection refused"),
            (1, "request timed out after 30s"),
            (124, "Command timed out"),
        ],
    )
    def test_fail_fast_auth_and_network_errors_raise_tracker_auth_error(
        self,
        rc: int,
        stderr: str,
    ) -> None:
        err = backends.classify_tracker_error(rc, "", stderr, tool="gh-axi")
        assert isinstance(err, TrackerAuthError)
        assert err.exit_code == 2
        msg = str(err).lower()
        assert "gh auth login" in msg or "gh-axi" in msg
        assert "--offline" in msg or "edge_tracker=local" in msg

    @pytest.mark.parametrize(
        "stderr",
        [
            "HTTP 403: API rate limit exceeded for user",
            "You have exceeded a secondary rate limit. Please wait a few minutes",
        ],
    )
    def test_rate_limit_403_raises_tracker_error_not_auth_error(self, stderr: str) -> None:
        err = backends.classify_tracker_error(1, "", stderr, tool="gh")
        assert isinstance(err, TrackerError)
        assert not isinstance(err, TrackerAuthError)
        assert err.exit_code == 1

    def test_run_tracker_cmd_preserves_trailing_newlines_and_wsl_dispatch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh":
                return subprocess.CompletedProcess(cmd, 0, "line1\r\nline2\n\n", " warn \n")
            if cmd[0] == "wsl":
                return subprocess.CompletedProcess(cmd, 0, "wsl-ok\n", "")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)
        rc, out, err = backends.run_tracker_cmd(["gh", "api", "graphql"], cwd=tmp_path, strip=False)
        assert (rc, out, err) == (0, "line1\r\nline2\n\n", " warn \n")

        monkeypatch.setattr(backends.os, "name", "nt")
        assert backends.needs_wsl_dispatch("/home/oguz/target-repo") is True
        monkeypatch.undo()
        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(backends, "needs_wsl_dispatch", lambda cwd: True)
        rc_wsl, out_wsl, _ = backends.run_tracker_cmd(
            ["gh", "issue", "view", "1"],
            cwd="/home/oguz/target-repo",
            strip=False,
        )
        assert rc_wsl == 0
        assert out_wsl == "wsl-ok\n"

    def test_temp_body_file_mkstemp_closed_wsl_path_and_finally_unlink(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        created_host_paths: List[Path] = []
        original_mkstemp = backends.tempfile.mkstemp

        def spy_mkstemp(*args, **kwargs):
            fd, path = original_mkstemp(*args, **kwargs)
            created_host_paths.append(Path(path))
            return fd, path

        monkeypatch.setattr(backends.tempfile, "mkstemp", spy_mkstemp)

        with backends.temp_body_file(TRICKY_MARKDOWN_BODY, cwd=tmp_path) as body_path:
            host_file = Path(body_path)
            assert host_file.exists()
            assert host_file.read_bytes() == TRICKY_MARKDOWN_BODY.encode("utf-8")

        assert created_host_paths
        assert not created_host_paths[-1].exists()

        # Verify cleanup on exception and to_wsl_path conversion under Windows->WSL cwd
        monkeypatch.setattr(backends, "needs_wsl_dispatch", lambda cwd: True)
        monkeypatch.setattr(backends, "to_wsl_path", lambda p: f"/mnt/wsl-mapped/{Path(p).name}")

        with pytest.raises(RuntimeError, match="boom"):
            with backends.temp_body_file("hello", cwd="/home/oguz/repo") as mapped_path:
                assert mapped_path.startswith("/mnt/wsl-mapped/")
                assert created_host_paths[-1].exists()
                raise RuntimeError("boom")

        assert not created_host_paths[-1].exists()


class TestTrackerDotenvAuthLoader:
    def test_dotenv_env_var_takes_precedence_over_repo_and_plugin_dotenv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo")
        (repo / ".env").write_text("GITHUB_TOKEN=ghp_fake_repo_loses\n", encoding="utf-8")

        fake_plugin = tmp_path / "plugin"
        fake_backends_file = fake_plugin / "tools" / "tracker" / "backends.py"
        fake_backends_file.parent.mkdir(parents=True, exist_ok=True)
        (fake_plugin / ".env").write_text("GITHUB_TOKEN=ghp_fake_plugin_loses\n", encoding="utf-8")
        monkeypatch.setattr(backends, "__file__", str(fake_backends_file))

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "ghp_fake_env_wins")

        captured_envs: List[Optional[Dict[str, str]]] = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh":
                captured_envs.append(kwargs.get("env"))
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)
        rc, out, _ = backends.run_tracker_cmd(["gh", "issue", "list"], cwd=repo)

        assert rc == 0 and out == "ok\n"
        assert "GITHUB_TOKEN" not in os.environ
        assert os.environ["GH_TOKEN"] == "ghp_fake_env_wins"
        if captured_envs and captured_envs[0] is not None:
            assert captured_envs[0].get("GH_TOKEN") == "ghp_fake_env_wins"
            assert captured_envs[0].get("GITHUB_TOKEN") != "ghp_fake_repo_loses"
            assert captured_envs[0].get("GITHUB_TOKEN") != "ghp_fake_plugin_loses"

    def test_dotenv_repo_env_takes_precedence_over_plugin_and_parses_syntax(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        primary = _init_git_repo(tmp_path / "primary")
        wt = tmp_path / "worktree"
        _git(primary, "worktree", "add", str(wt), "-b", "feat/dotenv-wt")

        (primary / ".env").write_text(
            "\n"
            "# Leading comment\n"
            "# GITHUB_TOKEN=ghp_fake_commented_out\n"
            "  export GITHUB_TOKEN=\"ghp_fake_repo_token\"  \n",
            encoding="utf-8",
        )
        fake_plugin = tmp_path / "plugin"
        fake_backends_file = fake_plugin / "tools" / "tracker" / "backends.py"
        fake_backends_file.parent.mkdir(parents=True, exist_ok=True)
        (fake_plugin / ".env").write_text("GITHUB_TOKEN=ghp_fake_plugin_loses\n", encoding="utf-8")
        monkeypatch.setattr(backends, "__file__", str(fake_backends_file))

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        captured_envs: List[Optional[Dict[str, str]]] = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "gh-axi":
                captured_envs.append(kwargs.get("env"))
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)
        rc, _, _ = backends.run_tracker_cmd(["gh-axi", "issue", "list"], cwd=wt)

        assert rc == 0
        assert captured_envs and captured_envs[0] is not None
        assert captured_envs[0]["GITHUB_TOKEN"] == "ghp_fake_repo_token"
        assert captured_envs[0]["GH_TOKEN"] == "ghp_fake_repo_token"
        assert "GITHUB_TOKEN" not in os.environ
        assert "GH_TOKEN" not in os.environ

    def test_dotenv_plugin_fallback_populates_both_vars_and_wslenv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo")
        fake_plugin = tmp_path / "plugin"
        fake_backends_file = fake_plugin / "tools" / "tracker" / "backends.py"
        fake_backends_file.parent.mkdir(parents=True, exist_ok=True)
        (fake_plugin / ".env").write_text(
            "# comment\nexport GH_TOKEN='ghp_fake_plugin_single'\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(backends, "__file__", str(fake_backends_file))

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("WSLENV", "EXISTING_VAR/u")

        captured_envs: List[Optional[Dict[str, str]]] = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] in ("gh", "wsl"):
                captured_envs.append(kwargs.get("env"))
                return subprocess.CompletedProcess(cmd, 0, "ok\n", "")
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Native run
        assert backends.run_tracker_cmd(["gh", "issue", "list"], cwd=repo)[0] == 0
        assert captured_envs[0] is not None
        assert captured_envs[0]["GITHUB_TOKEN"] == "ghp_fake_plugin_single"
        assert captured_envs[0]["GH_TOKEN"] == "ghp_fake_plugin_single"
        assert "GITHUB_TOKEN" not in os.environ
        assert "GH_TOKEN" not in os.environ

        # WSL-dispatched run preserves and appends WSLENV
        monkeypatch.setattr(backends, "needs_wsl_dispatch", lambda _cwd: True)
        assert backends.run_tracker_cmd(["gh", "issue", "list"], cwd="/home/oguz/repo")[0] == 0
        assert captured_envs[1] is not None
        assert captured_envs[1]["GITHUB_TOKEN"] == "ghp_fake_plugin_single"
        assert captured_envs[1]["GH_TOKEN"] == "ghp_fake_plugin_single"
        wslenv_parts = captured_envs[1].get("WSLENV", "").split(":")
        assert "EXISTING_VAR/u" in wslenv_parts
        assert "GITHUB_TOKEN" in wslenv_parts
        assert "GH_TOKEN" in wslenv_parts

    def test_dotenv_secret_hygiene_redacts_token_from_errors_and_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo")
        secret_tok = "ghp_fake_secret_999"
        (repo / ".env").write_text(f"GITHUB_TOKEN={secret_tok}\n", encoding="utf-8")

        fake_plugin = tmp_path / "plugin"
        fake_backends_file = fake_plugin / "tools" / "tracker" / "backends.py"
        fake_backends_file.parent.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(backends, "__file__", str(fake_backends_file))
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)

        real_run = subprocess.run

        def fake_fail(cmd, **kwargs):
            if cmd[0] == "gh":
                return subprocess.CompletedProcess(
                    cmd,
                    1,
                    f"debug echo {secret_tok}\n",
                    f"HTTP 401 Bad credentials for {secret_tok}",
                )
            return real_run(cmd, **kwargs)

        monkeypatch.setattr(subprocess, "run", fake_fail)

        rc, out, err = backends.run_tracker_cmd(["gh", "issue", "view", "1"], cwd=repo)
        assert rc == 1
        assert secret_tok not in out
        assert secret_tok not in err

        with pytest.raises(TrackerAuthError) as exc_info:
            backends.run_tracker_checked(["gh", "issue", "view", "1"], cwd=repo)
        assert exc_info.value.exit_code == 2
        assert secret_tok not in str(exc_info.value)


# =============================================================================
# 3. GhAxiBackend + GraphQL Lossless Reads
# =============================================================================


class TestGhAxiBackend:
    def test_gh_axi_ensure_labels_calls_label_create_idempotently(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        calls: List[List[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "created: ok\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhAxiBackend(repo)
        labels = backend.ensure_labels()

        assert set(labels) == set(CANONICAL_LABELS.keys())
        assert len(calls) == len(CANONICAL_LABELS)
        for cmd in calls:
            assert cmd[:3] == ["gh-axi", "label", "create"]
            assert "--name" in cmd
            assert "--color" in cmd
            assert "--description" in cmd

    def test_gh_axi_create_issue_uses_body_file_links_parent_and_reads_losslessly(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        seen_cmds: List[List[str]] = []
        observed_body_files: List[str] = []
        captured_file_bytes: List[bytes] = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            seen_cmds.append(list(cmd))
            if cmd[:3] == ["gh-axi", "issue", "create"]:
                body_file = _extract_flag_value(cmd, "--body-file")
                assert body_file is not None
                observed_body_files.append(body_file)
                captured_file_bytes.append(Path(body_file).read_bytes())
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    "issue:\n  number: 42\n  title: Spec\n  state: open\n  url: https://github.com/acme/widgets/issues/42\n",
                    "",
                )
            if cmd[:4] == ["gh-axi", "issue", "subissue", "add"]:
                return subprocess.CompletedProcess(cmd, 0, "subissue_add:\n  parent: #7\n", "")
            if cmd[:3] == ["gh", "api", "graphql"]:
                node = _gql_issue_node(
                    42,
                    title="Spec",
                    body=TRICKY_MARKDOWN_BODY,
                    labels=["type:frontier", "spec:draft"],
                    parent_number=7,
                )
                return subprocess.CompletedProcess(
                    cmd,
                    0,
                    json.dumps({"data": {"repository": {"issue": node}}}),
                    "",
                )
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhAxiBackend(repo)
        issue = backend.create_issue(
            title="Spec",
            body=TRICKY_MARKDOWN_BODY,
            labels=["type:frontier", "spec:draft"],
            parent_number=7,
        )

        assert issue.number == 42
        assert issue.body == TRICKY_MARKDOWN_BODY
        assert issue.parent_number == 7
        assert issue.backend == "gh-axi"
        assert captured_file_bytes == [TRICKY_MARKDOWN_BODY.encode("utf-8")]
        assert not Path(observed_body_files[0]).exists()
        assert any(cmd[:5] == ["gh-axi", "issue", "subissue", "add", "7"] for cmd in seen_cmds)
        assert not any(cmd[:3] == ["gh-axi", "issue", "view"] for cmd in seen_cmds)

    def test_gh_axi_lossless_reads_and_mutations(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        seen_cmds: List[List[str]] = []
        seen_body_files: List[Path] = []
        real_run = subprocess.run
        page_counter = {"subissues": 0}

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            seen_cmds.append(list(cmd))
            if cmd[:3] == ["gh", "api", "graphql"]:
                query_text = " ".join(cmd)
                if "subIssues" in query_text and "issues(" not in query_text and "comments(" not in query_text:
                    page_counter["subissues"] += 1
                    if page_counter["subissues"] == 1:
                        return subprocess.CompletedProcess(
                            cmd,
                            0,
                            json.dumps(
                                {
                                    "data": {
                                        "repository": {
                                            "issue": {
                                                "number": 10,
                                                "subIssues": {
                                                    "pageInfo": {"hasNextPage": True, "endCursor": "CUR_1"},
                                                    "nodes": [_gql_issue_node(11, title="Child 1", parent_number=10)],
                                                },
                                            }
                                        }
                                    }
                                }
                            ),
                            "",
                        )
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "data": {
                                    "repository": {
                                        "issue": {
                                            "number": 10,
                                            "subIssues": {
                                                "pageInfo": {"hasNextPage": False, "endCursor": None},
                                                "nodes": [_gql_issue_node(12, title="Child 2", parent_number=10)],
                                            },
                                        }
                                    }
                                }
                            }
                        ),
                        "",
                    )
                if "issues(" in query_text:
                    node = _gql_issue_node(42, title="Spec", body=TRICKY_MARKDOWN_BODY, labels=["spec:approved"])
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "data": {
                                    "repository": {
                                        "issues": {
                                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                                            "nodes": [node],
                                        }
                                    }
                                }
                            }
                        ),
                        "",
                    )
                node = _gql_issue_node(
                    42,
                    title="Spec Updated",
                    body=TRICKY_MARKDOWN_BODY,
                    state="CLOSED",
                    labels=["spec:approved"],
                    comments=[{"id": "C_9", "author": {"login": "dev"}, "body": TRICKY_MARKDOWN_BODY, "createdAt": "2026-11-25T11:00:00Z"}],
                )
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"repository": {"issue": node}}}), "")

            body_file = _extract_flag_value(cmd, "--body-file")
            if body_file:
                p = Path(body_file)
                assert p.read_bytes() == TRICKY_MARKDOWN_BODY.encode("utf-8")
                seen_body_files.append(p)
            return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhAxiBackend(repo)

        fetched = backend.get_issue(42)
        assert fetched.body == TRICKY_MARKDOWN_BODY
        assert fetched.comments[0].body == TRICKY_MARKDOWN_BODY

        listed = backend.list_issues(state="open", labels=["spec:approved"])
        assert len(listed) == 1
        assert listed[0].body == TRICKY_MARKDOWN_BODY

        edited = backend.edit_issue(42, title="Spec Updated", body=TRICKY_MARKDOWN_BODY, add_labels=["spec:approved"])
        assert edited.title == "Spec Updated"

        comment = backend.add_comment(42, TRICKY_MARKDOWN_BODY)
        assert comment.body == TRICKY_MARKDOWN_BODY

        subs = backend.list_subissues(10)
        assert [s.number for s in subs] == [11, 12]
        assert page_counter["subissues"] == 2

        backend.remove_subissue(10, [11])
        closed = backend.close_issue(42, comment="Shipped", reason="not_planned")
        assert closed.state == "closed"

        assert len(seen_body_files) == 2
        assert all(not p.exists() for p in seen_body_files)
        assert not any("gh-axi" in cmd[0] and len(cmd) > 1 and cmd[1] == "api" for cmd in seen_cmds)
        assert any(cmd[:4] == ["gh-axi", "issue", "close", "42"] and "not_planned" in cmd for cmd in seen_cmds)

    def test_gh_axi_auth_failure_raises_tracker_auth_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return subprocess.CompletedProcess(cmd, 1, "", "AUTH_REQUIRED: run gh auth login")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhAxiBackend(repo)

        with pytest.raises(TrackerAuthError) as exc:
            backend.create_issue("Test", body="body")
        assert exc.value.exit_code == 2


# =============================================================================
# 4. GhCliBackend + GraphQL Sub-issues
# =============================================================================


class TestGhCliBackend:
    def test_gh_cli_ensure_labels_uses_force(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        calls: List[List[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhCliBackend(repo)
        labels = backend.ensure_labels()

        assert set(labels) == set(CANONICAL_LABELS.keys())
        assert len(calls) == len(CANONICAL_LABELS)
        for cmd in calls:
            assert cmd[:3] == ["gh", "label", "create"]
            assert "--force" in cmd

    def test_gh_cli_create_with_parent_uses_graphql_add_subissue_replace_parent(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        gql_calls: List[str] = []
        body_files: List[Path] = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            if cmd[:3] == ["gh", "issue", "create"]:
                bf = _extract_flag_value(cmd, "--body-file")
                assert bf is not None
                p = Path(bf)
                assert p.read_bytes() == TRICKY_MARKDOWN_BODY.encode("utf-8")
                body_files.append(p)
                return subprocess.CompletedProcess(cmd, 0, "https://github.com/acme/widgets/issues/55\n", "")
            if cmd[:3] == ["gh", "api", "graphql"]:
                joined = " ".join(cmd)
                gql_calls.append(joined)
                if "addSubIssue" in joined:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "data": {
                                    "addSubIssue": {
                                        "issue": {"number": 10},
                                        "subIssue": _gql_issue_node(55, title="Child", body=TRICKY_MARKDOWN_BODY, parent_number=10),
                                    }
                                }
                            }
                        ),
                        "",
                    )
                if "id" in joined and "body" not in joined:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "data": {
                                    "repository": {
                                        "issue": {"id": "I_NODE", "number": 55},
                                        "parent": {"id": "I_NODE_10", "number": 10},
                                        "c0": {"id": "I_NODE_55", "number": 55},
                                    }
                                }
                            }
                        ),
                        "",
                    )
                node = _gql_issue_node(55, title="Child", body=TRICKY_MARKDOWN_BODY, parent_number=10)
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"repository": {"issue": node}}}), "")
            raise AssertionError(f"Unexpected command: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhCliBackend(repo)
        issue = backend.create_issue(title="Child", body=TRICKY_MARKDOWN_BODY, parent_number=10)

        assert issue.number == 55
        assert issue.parent_number == 10
        assert issue.body == TRICKY_MARKDOWN_BODY
        assert issue.backend == "gh"
        assert any("addSubIssue" in q and "replaceParent" in q for q in gql_calls)
        assert body_files and not body_files[0].exists()

    def test_gh_cli_close_reason_mapping_edit_comment_and_subissues(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        seen_cmds: List[List[str]] = []
        real_run = subprocess.run

        def fake_run(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            seen_cmds.append(list(cmd))
            if cmd[:3] == ["gh", "api", "graphql"]:
                joined = " ".join(cmd)
                if "removeSubIssue" in joined:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "data": {
                                    "removeSubIssue": {
                                        "issue": {"number": 10},
                                        "subIssue": _gql_issue_node(55, title="Child", parent_number=None),
                                    }
                                }
                            }
                        ),
                        "",
                    )
                if "id" in joined and "body" not in joined:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        json.dumps(
                            {
                                "data": {
                                    "repository": {
                                        "issue": {"id": "I_NODE", "number": 55},
                                        "parent": {"id": "I_NODE_10", "number": 10},
                                        "c0": {"id": "I_NODE_55", "number": 55},
                                    }
                                }
                            }
                        ),
                        "",
                    )
                node = _gql_issue_node(55, title="Edited", body=TRICKY_MARKDOWN_BODY, state="CLOSED")
                return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"repository": {"issue": node}}}), "")
            return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        backend = GhCliBackend(repo)

        backend.edit_issue(55, title="Edited", body=TRICKY_MARKDOWN_BODY)
        backend.add_comment(55, TRICKY_MARKDOWN_BODY)
        removed = backend.remove_subissue(10, [55])
        closed = backend.close_issue(55, comment="Skipped", reason="not_planned")

        assert len(removed) == 1
        assert removed[0].parent_number is None
        assert closed.state == "closed"
        assert any(cmd[:3] == ["gh", "issue", "edit"] and "--body-file" in cmd for cmd in seen_cmds)
        assert any(cmd[:3] == ["gh", "issue", "comment"] and "--body-file" in cmd for cmd in seen_cmds)
        assert any(cmd[:4] == ["gh", "issue", "close", "55"] and "not planned" in cmd for cmd in seen_cmds)
        assert any("removeSubIssue" in " ".join(cmd) for cmd in seen_cmds)


# =============================================================================
# 5. LocalTrackerBackend
# =============================================================================


class TestLocalTrackerBackend:
    def test_local_backend_anchors_to_primary_root_from_worktree(self, tmp_path: Path) -> None:
        primary = _init_git_repo(tmp_path / "primary")
        wt = tmp_path / "worktree"
        _git(primary, "worktree", "add", str(wt), "-b", "slice/local-wt")

        backend = LocalTrackerBackend(wt)
        issue = backend.create_issue(title="Worktree Anchored", body=TRICKY_MARKDOWN_BODY)

        assert issue.number == 1
        assert (primary / ".edge" / "issues" / "1.md").exists()
        assert (primary / ".edge" / "issues" / "index.json").exists()
        assert not (wt / ".edge" / "issues").exists()

    def test_local_backend_crud_labels_comments_close_and_filters(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path / "repo")
        backend = LocalTrackerBackend(repo)

        ensured = backend.ensure_labels()
        assert set(ensured) == set(CANONICAL_LABELS.keys())

        first = backend.create_issue(
            title="Epic Spec",
            body=TRICKY_MARKDOWN_BODY,
            labels=["type:frontier", "spec:draft", "track:core"],
        )
        second = backend.create_issue(
            title="Child Slice",
            body="child body",
            labels=["status:ready", "track:core"],
            parent_number=first.number,
        )

        # Reload from fresh backend instance to verify disk persistence
        fresh = LocalTrackerBackend(repo)
        reloaded = fresh.get_issue(first.number)
        assert reloaded.body == TRICKY_MARKDOWN_BODY
        assert reloaded.subissues == [second.number]

        edited = fresh.edit_issue(
            first.number,
            title="Epic Approved",
            add_labels=["spec:approved"],
            remove_labels=["spec:draft"],
        )
        assert edited.title == "Epic Approved"
        assert "spec:approved" in edited.labels
        assert "spec:draft" not in edited.labels

        comment = fresh.add_comment(first.number, TRICKY_MARKDOWN_BODY)
        assert comment.body == TRICKY_MARKDOWN_BODY
        assert fresh.get_issue(first.number).comments[0].body == TRICKY_MARKDOWN_BODY

        open_ready = fresh.list_issues(state="open", labels=["status:ready", "track:core"], parent_number=first.number)
        assert [i.number for i in open_ready] == [second.number]

        closed = fresh.close_issue(second.number, comment="Merged", reason="completed")
        assert closed.state == "closed"
        assert closed.closed_at is not None
        assert [i.number for i in fresh.list_issues(state="closed")] == [second.number]
        assert [i.number for i in fresh.list_issues(state="all")] == [first.number, second.number]

        with pytest.raises(TrackerNotFoundError):
            fresh.get_issue(999)

    def test_local_backend_bidirectional_subissues_and_reparent(self, tmp_path: Path) -> None:
        repo = _init_git_repo(tmp_path / "repo")
        backend = LocalTrackerBackend(repo)

        p1 = backend.create_issue("Parent 1")
        p2 = backend.create_issue("Parent 2")
        c1 = backend.create_issue("Child 1")
        c2 = backend.create_issue("Child 2")

        linked = backend.add_subissue(p1.number, [c1.number, c2.number])
        assert [c.parent_number for c in linked] == [p1.number, p1.number]
        assert backend.get_issue(p1.number).subissues == [c1.number, c2.number]

        # Re-parent c1 under p2
        backend.add_subissue(p2.number, [c1.number])
        assert backend.get_issue(p1.number).subissues == [c2.number]
        assert backend.get_issue(p2.number).subissues == [c1.number]
        assert backend.get_issue(c1.number).parent_number == p2.number

        backend.remove_subissue(p1.number, [c2.number])
        assert backend.get_issue(p1.number).subissues == []
        assert backend.get_issue(c2.number).parent_number is None
        assert [s.number for s in backend.list_subissues(p2.number)] == [c1.number]

    def test_local_backend_o_creat_o_excl_collision_retry_and_thread_safety(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo")
        issues_dir = repo / ".edge" / "issues"
        issues_dir.mkdir(parents=True, exist_ok=True)
        # Pre-occupy 1.md without index.json knowing about it
        (issues_dir / "1.md").write_text("preexisting", encoding="utf-8")

        real_open = os.open
        seen_flags: List[int] = []

        def spy_open(path, flags, *args, **kwargs):
            if str(path).endswith(".md"):
                seen_flags.append(flags)
            return real_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", spy_open)
        backend = LocalTrackerBackend(repo)
        created = backend.create_issue("Should Skip #1", body="claimed #2")

        assert created.number == 2
        assert (issues_dir / "1.md").read_text(encoding="utf-8") == "preexisting"
        assert (issues_dir / "2.md").exists()
        assert any((fl & os.O_CREAT) and (fl & os.O_EXCL) for fl in seen_flags)

        # Concurrent multi-threaded creation yields unique issue numbers
        monkeypatch.undo()

        def worker(idx: int) -> int:
            return LocalTrackerBackend(repo).create_issue(f"Concurrent {idx}").number

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            numbers = list(pool.map(worker, range(8)))

        assert len(set(numbers)) == 8


# =============================================================================
# 6. Cache & CLI (All 9 Subcommands + Exit Codes 0/1/2)
# =============================================================================


class TestCacheAndCli:
    def test_cache_issue_spec_writes_verbatim_meta_and_gitignore_idempotently(
        self,
        tmp_path: Path,
    ) -> None:
        primary = _init_git_repo(tmp_path / "primary")
        wt = tmp_path / "worktree"
        _git(primary, "worktree", "add", str(wt), "-b", "slice/cache-wt")

        issue = TrackerIssue(
            number=17,
            title="Cached Spec",
            body=TRICKY_MARKDOWN_BODY,
            state="open",
            labels=["spec:approved"],
            backend="local",
        )
        out_path = cache.cache_issue_spec(wt, issue)

        expected_path = primary.resolve() / ".edge" / "cache" / "issues" / "17.md"
        meta_path = primary.resolve() / ".edge" / "cache" / "issues" / "meta.json"
        gitignore_path = primary.resolve() / ".gitignore"

        assert out_path.resolve() == expected_path
        assert expected_path.read_bytes() == TRICKY_MARKDOWN_BODY.encode("utf-8")
        assert meta_path.exists()
        assert not (wt / ".edge" / "cache").exists()

        # Idempotent .gitignore append
        cache.cache_issue_spec(wt, issue)
        gi_lines = gitignore_path.read_text(encoding="utf-8").splitlines()
        assert gi_lines.count(".edge/cache/") == 1

        # Respect broader `.edge/` rule without duplicating `.edge/cache/`
        gitignore_path.write_text(".edge/\n", encoding="utf-8")
        cache.cache_issue_spec(wt, issue)
        assert gitignore_path.read_text(encoding="utf-8") == ".edge/\n"

    def test_cli_all_nine_subcommands_offline_json_and_cache(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        body_src = tmp_path / "body.md"
        body_src.write_bytes(TRICKY_MARKDOWN_BODY.encode("utf-8"))

        # 1. init-labels
        assert cli.main(["init-labels", str(repo), "--offline", "--json"]) == 0
        labels_out = json.loads(capsys.readouterr().out)
        assert set(labels_out) == set(CANONICAL_LABELS.keys())

        # 2. create parent + child (global flags before AND after subcommand)
        assert cli.main(["--offline", "--json", "create", str(repo), "--title", "Parent", "--body-file", str(body_src), "--label", "type:frontier"]) == 0
        parent_json = json.loads(capsys.readouterr().out)
        assert parent_json["number"] == 1
        assert parent_json["body"] == TRICKY_MARKDOWN_BODY

        assert cli.main(["create", str(repo), "--title", "Child", "--parent", "1", "--label", "status:ready", "--offline", "--json"]) == 0
        child_json = json.loads(capsys.readouterr().out)
        assert child_json["number"] == 2
        assert child_json["parent_number"] == 1

        # 3. view (+ --comments --cache)
        assert cli.main(["view", str(repo), "1", "--comments", "--cache", "--offline", "--json"]) == 0
        viewed = json.loads(capsys.readouterr().out)
        assert viewed["number"] == 1
        assert (repo / ".edge" / "cache" / "issues" / "1.md").exists()

        # 4. edit
        assert cli.main(["edit", str(repo), "2", "--title", "Child Edited", "--add-label", "status:in-progress", "--remove-label", "status:ready", "--offline", "--json"]) == 0
        edited = json.loads(capsys.readouterr().out)
        assert edited["title"] == "Child Edited"
        assert "status:in-progress" in edited["labels"]

        # 5. comment
        assert cli.main(["comment", str(repo), "2", "--body", "LGTM", "--offline", "--json"]) == 0
        commented = json.loads(capsys.readouterr().out)
        assert commented["body"] == "LGTM"

        # 6. list
        assert cli.main(["list", str(repo), "--state", "open", "--label", "status:in-progress", "--parent", "1", "--offline", "--json"]) == 0
        listed = json.loads(capsys.readouterr().out)
        assert [item["number"] for item in listed] == [2]

        # 7. subissue (list / remove / add)
        assert cli.main(["subissue", str(repo), "list", "1", "--offline", "--json"]) == 0
        assert [item["number"] for item in json.loads(capsys.readouterr().out)] == [2]

        assert cli.main(["subissue", str(repo), "remove", "1", "2", "--offline", "--json"]) == 0
        capsys.readouterr()

        assert cli.main(["subissue", str(repo), "add", "1", "2", "--offline", "--json"]) == 0
        capsys.readouterr()

        # 8. close
        assert cli.main(["close", str(repo), "2", "--comment", "Done", "--reason", "completed", "--offline", "--json"]) == 0
        closed = json.loads(capsys.readouterr().out)
        assert closed["state"] == "closed"

        # 9. cache-spec
        assert cli.main(["cache-spec", str(repo), "1", "--offline"]) == 0
        cache_out = capsys.readouterr().out.strip()
        assert cache_out.endswith("1.md")

    def test_cli_exit_codes_0_1_2(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = _init_git_repo(tmp_path / "repo", "https://github.com/acme/widgets.git")
        monkeypatch.delenv("EDGE_TRACKER", raising=False)

        # Exit 1: local not found
        rc_missing = cli.main(["view", str(repo), "999", "--offline"])
        assert rc_missing == 1
        capsys.readouterr()

        # Exit 2: explicit gh missing binary
        _patch_which(monkeypatch, set())
        rc_auth = cli.main(["view", str(repo), "1", "--backend", "gh"])
        assert rc_auth == 2
        capsys.readouterr()

        # Exit 1: 403 rate limit via gh backend
        _patch_which(monkeypatch, {"gh"})
        real_run = subprocess.run

        def fake_rate_limit(cmd, **kwargs):
            if cmd[0] == "git":
                return real_run(cmd, **kwargs)
            return subprocess.CompletedProcess(cmd, 1, "", "HTTP 403: API rate limit exceeded")

        monkeypatch.setattr(subprocess, "run", fake_rate_limit)
        rc_rate = cli.main(["view", str(repo), "1", "--backend", "gh"])
        assert rc_rate == 1


# =============================================================================
# 7. Static Architectural & Budget Invariants
# =============================================================================


def _ast_cc(node: ast.AST) -> int:
    comp = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            comp += 1
        elif isinstance(child, ast.BoolOp):
            comp += max(1, len(child.values) - 1)
        elif hasattr(ast, "Match") and isinstance(child, ast.Match):
            comp += len(child.cases)
    return comp


def _collect_runtime_imports(py_file: Path) -> List[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: List[str] = []

    def _is_type_checking_guard(test: ast.AST) -> bool:
        return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )

    def _walk(stmts: List[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If) and _is_type_checking_guard(stmt.test):
                continue
            if isinstance(stmt, ast.Import):
                modules.extend(alias.name for alias in stmt.names)
            elif isinstance(stmt, ast.ImportFrom):
                if stmt.level == 0 and stmt.module:
                    modules.append(stmt.module)
                elif stmt.level > 0:
                    pkg_parts = py_file.relative_to(ROOT_DIR).parent.parts
                    base = pkg_parts[: len(pkg_parts) - (stmt.level - 1)]
                    if stmt.module:
                        modules.append(".".join([*base, stmt.module]))
                    else:
                        modules.append(".".join(base))
            for child_attr in ("body", "orelse", "finalbody", "handlers"):
                sub = getattr(stmt, child_attr, None)
                if isinstance(sub, list):
                    _walk(sub)

    _walk(tree.body)
    return modules


class TestTrackerStaticInvariants:
    def test_inv_orch_hook_latency_transitive_imports_and_no_gh_subprocesses(self) -> None:
        guard_path = ROOT_DIR / "tools" / "brigade" / "orchestrator_guard.py"
        visited_files: Set[Path] = set()
        discovered_modules: Set[str] = set()
        queue: List[Path] = [guard_path]

        while queue:
            current = queue.pop()
            if current in visited_files or not current.exists():
                continue
            visited_files.add(current)
            for mod in _collect_runtime_imports(current):
                discovered_modules.add(mod)
                if mod.startswith("tools."):
                    rel = Path(*mod.split("."))
                    candidate_py = ROOT_DIR / f"{rel}.py"
                    candidate_init = ROOT_DIR / rel / "__init__.py"
                    if candidate_py.exists():
                        queue.append(candidate_py)
                    elif candidate_init.exists():
                        queue.append(candidate_init)

        assert not any(m == "tools.tracker" or m.startswith("tools.tracker.") for m in discovered_modules)
        assert "tools.brigade.tasks_bridge" not in discovered_modules
        assert not any(m == "yaml" or m.startswith("yaml.") for m in discovered_modules)

        guard_tree = ast.parse(guard_path.read_text(encoding="utf-8"), filename=str(guard_path))
        for node in ast.walk(guard_tree):
            if isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
                        first = arg.elts[0]
                        if isinstance(first, ast.Constant) and first.value in {"gh", "gh-axi"}:
                            raise AssertionError(f"orchestrator_guard.py invokes {first.value}")
                    elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if re.search(r"\b(?:gh-axi|gh)\s+(?:issue|api|label)\b", arg.value):
                            raise AssertionError(f"orchestrator_guard.py contains gh command literal: {arg.value}")

    def test_inv_tracker_stdlib_only(self) -> None:
        targets = [ROOT_DIR / "tools" / "common" / "fs.py", *sorted((ROOT_DIR / "tools" / "tracker").glob("*.py"))]
        stdlib = sys.stdlib_module_names
        for py_file in targets:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        assert top in stdlib or top == "tools", f"Non-stdlib import '{alias.name}' in {py_file.name}"
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    top = node.module.split(".")[0]
                    assert top in stdlib or top == "tools", f"Non-stdlib import '{node.module}' in {py_file.name}"

    def test_inv_tracker_file_budget_and_cyclomatic_complexity(self) -> None:
        targets = [ROOT_DIR / "tools" / "common" / "fs.py", *sorted((ROOT_DIR / "tools" / "tracker").glob("*.py"))]
        for py_file in targets:
            lines = py_file.read_text(encoding="utf-8").splitlines()
            assert len(lines) <= 250, f"{py_file.name} exceeds 250 lines ({len(lines)})"

            tree = ast.parse("\n".join(lines), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cc = _ast_cc(node)
                    assert cc <= 10, f"{py_file.name}:{node.name} has CC={cc} > 10"
