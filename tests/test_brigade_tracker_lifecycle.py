"""
Hermetic RED contract tests for Slice 2 (`brigade-tracker-lifecycle`).

Covers `.edge/specs/brigade-tracker-lifecycle.md`:
- `Ticket` backward-compatible `issue_number`, `parent_issue`, `tracker_offline`
- `tools/brigade/tracker_hooks.py` (`resolve_slice_issue_spec` Captain A2 rule,
  `mark_issue_in_progress`, `preflight_ticket_tracker`, `complete_ticket_tracker_issue`)
- `start-slice` -> `finish_slice` -> `confirm_merge` lifecycle & `INV-CACHE-NO-ARCHIVE`
- `finish_slice` pre-merge `TrackerAuthError` block vs post-merge soft-fail + IDLE reset
- `tasks_bridge` (`create_refactor_ticket`, `complete_linked_task`), `--no-sync-tasks`,
  legacy `tasks-axi` fallback, and `radar export-tasks --parent-issue`
- `critique-spec --issue` (`--no-post-comment`, missing args exit `1`)
- `qa_fiber.stage_to_frontier` + `cmd_qa_inspect` (dedupe, `"Staged to tracker frontier:"`, exit `0`/`2`)
- Static invariants (`INV-ORCH-HOOK-LATENCY`, `INV-MODULAR-FSM` <= 200L & CC <= 10)
"""

import ast
import io
import re
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pytest
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.brigade import cli as brigade_cli
from tools.brigade import qa_fiber, spec_critic, tasks_bridge, tracker_hooks
from tools.brigade.fsm import BrigadeFSM
from tools.brigade.models import CycleState, Ticket
from tools.radar import cli as radar_cli
from tools.radar.ledger import FindingSeverity, FindingStatus, LedgerEngine, LedgerItem, Track
from tools.tracker.local_backend import LocalTrackerBackend
from tools.tracker.models import TrackerAuthError, TrackerError

SPEC_BODY_WITH_EXPECTED_FILES = (
    "---\n"
    "expected_files:\n"
    "  - src/core/widget.ts\n"
    "  - tests/widget.test.ts\n"
    "---\n\n"
    "# Spec: Parent Epic\n\n"
    "Structured specification body.\n"
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


def _init_repo(repo_dir: Path, *, branch: str = "development", remote_url: Optional[str] = None) -> Path:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(repo_dir, "init", "-b", branch)
    _git(repo_dir, "config", "user.email", "test@example.com")
    _git(repo_dir, "config", "user.name", "Edge Test")
    (repo_dir / ".gitignore").write_text(".edge/\n", encoding="utf-8")
    (repo_dir / "README.md").write_text("# repo\n", encoding="utf-8")
    _git(repo_dir, "add", ".gitignore", "README.md")
    _git(repo_dir, "commit", "-m", "init")
    if remote_url:
        _git(repo_dir, "remote", "add", "origin", remote_url)
    return repo_dir


def _parse_frontmatter(md_path: Path) -> tuple[Dict[str, Any], str]:
    raw = md_path.read_text(encoding="utf-8")
    assert raw.startswith("---")
    parts = raw.split("---", 2)
    return yaml.safe_load(parts[1]) or {}, parts[2]


def _make_ticket(
    *,
    ticket_id: str = "TICK-FEAT-DEMO",
    branch_name: str = "feat/demo",
    issue_number: Optional[int] = None,
    parent_issue: Optional[int] = None,
    tracker_offline: bool = False,
    tasks_axi_id: Optional[str] = None,
    spec_path: Optional[str] = None,
) -> Ticket:
    return Ticket(
        ticket_id=ticket_id,
        track="feature",
        domain="demo",
        rule_id="SLICE-DEMO",
        severity="NORMAL",
        target_file="src/demo.ts",
        line_number=1,
        fingerprint="slice-demo",
        description="Demo slice",
        suggested_fix="Implement demo",
        branch_name=branch_name,
        issue_number=issue_number,
        parent_issue=parent_issue,
        tracker_offline=tracker_offline,
        tasks_axi_id=tasks_axi_id,
        spec_path=spec_path,
    )


# =============================================================================
# 1. Ticket Model & tracker_hooks Contract
# =============================================================================


class TestTicketModelAndTrackerHooks:
    def test_ticket_from_dict_backward_compatibility_and_defaults(self) -> None:
        legacy = Ticket.from_dict(
            {
                "ticket_id": "TICK-CORE-LEGACY",
                "track": "core",
                "domain": "auth",
                "rule_id": "RULE-1",
                "severity": "CRITICAL",
                "target_file": "src/auth.ts",
                "line_number": 10,
                "fingerprint": "fp-1",
                "description": "legacy",
                "suggested_fix": "fix",
                "tasks_axi_id": "tx-99",
            }
        )
        assert legacy.issue_number is None
        assert legacy.parent_issue is None
        assert legacy.tracker_offline is False
        assert legacy.tasks_axi_id == "tx-99"

        modern = Ticket.from_dict(
            {
                **legacy.to_dict(),
                "issue_number": 14,
                "parent_issue": 10,
                "tracker_offline": True,
            }
        )
        assert modern.issue_number == 14
        assert modern.parent_issue == 10
        assert modern.tracker_offline is True
        assert modern.to_dict()["issue_number"] == 14
        assert modern.to_dict()["parent_issue"] == 10
        assert modern.to_dict()["tracker_offline"] is True

    def test_resolve_slice_issue_spec_captain_a2_parent_child_rules(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        parent = local.create_issue("Parent Spec", body=SPEC_BODY_WITH_EXPECTED_FILES, labels=["type:frontier", "spec:approved"])
        child = local.create_issue("Child Ticket", body="child only", labels=["status:ready"], parent_number=parent.number)

        # Case A: both --issue C and --parent-issue P -> caches P for spec SSOT, keeps issue_number=C
        eff_spec, out_issue, out_parent = tracker_hooks.resolve_slice_issue_spec(
            repo, issue_number=child.number, parent_issue=parent.number, spec_path=None, offline=True
        )
        assert out_issue == child.number
        assert out_parent == parent.number
        assert eff_spec is not None
        cached_parent = repo / ".edge" / "cache" / "issues" / f"{parent.number}.md"
        assert cached_parent.is_file()
        assert (repo / eff_spec).resolve() == cached_parent.resolve()
        assert not (repo / ".edge" / "cache" / "issues" / f"{child.number}.md").exists()

        # Case B: only --parent-issue P -> caches P, keeps issue_number=None so finish never closes P
        eff_spec_p, out_issue_p, out_parent_p = tracker_hooks.resolve_slice_issue_spec(
            repo, issue_number=None, parent_issue=parent.number, spec_path=None, offline=True
        )
        assert out_issue_p is None
        assert out_parent_p == parent.number
        assert eff_spec_p is not None

        # Case C: explicit --spec preserved even when --issue given
        explicit_spec = ".edge/specs/custom.md"
        eff_custom, out_c, _ = tracker_hooks.resolve_slice_issue_spec(
            repo, issue_number=child.number, parent_issue=None, spec_path=explicit_spec, offline=True
        )
        assert eff_custom == explicit_spec
        assert out_c == child.number

        # Case D: neither issue nor parent -> pass-through
        assert tracker_hooks.resolve_slice_issue_spec(repo, None, None, None, offline=True) == (None, None, None)

    def test_mark_issue_in_progress_swaps_label_only_when_issue_set(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        issue = local.create_issue("Slice Ticket", labels=["status:ready", "track:core"])

        # No-op when issue_number is None
        tracker_hooks.mark_issue_in_progress(repo, None, offline=True)

        tracker_hooks.mark_issue_in_progress(repo, issue.number, offline=True)
        updated = LocalTrackerBackend(repo).get_issue(issue.number)
        assert "status:in-progress" in updated.labels
        assert "status:ready" not in updated.labels
        assert "track:core" in updated.labels

    def test_preflight_and_complete_ticket_tracker_issue(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo", remote_url="https://github.com/acme/widgets.git")
        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _name, *_a, **_kw: None)

        no_issue_ticket = _make_ticket(issue_number=None)
        tracker_hooks.preflight_ticket_tracker(repo, no_issue_ticket, offline=False)

        online_ticket = _make_ticket(issue_number=7, tracker_offline=False)
        with pytest.raises(TrackerAuthError) as exc:
            tracker_hooks.preflight_ticket_tracker(repo, online_ticket, offline=False)
        assert exc.value.exit_code == 2

        # Offline flag or persisted tracker_offline bypasses remote auth failure
        local = LocalTrackerBackend(repo)
        created = local.create_issue("Ticket 1", labels=["status:in-progress"])
        offline_ticket = _make_ticket(issue_number=created.number, tracker_offline=True)
        tracker_hooks.preflight_ticket_tracker(repo, offline_ticket, offline=False)

        ok, msg = tracker_hooks.complete_ticket_tracker_issue(
            repo,
            offline_ticket,
            pr_url="https://github.com/acme/widgets/pull/12",
            offline=False,
        )
        assert ok is True, msg
        closed = LocalTrackerBackend(repo).get_issue(created.number)
        assert closed.state == "closed"
        assert "status:done" in closed.labels
        assert "status:in-progress" not in closed.labels


# =============================================================================
# 2. Brigade Start/Finish Lifecycle & Merge/Cache Invariants
# =============================================================================


class TestBrigadeSliceLifecycle:
    def test_start_and_finish_slice_parent_spec_closes_child_keeps_parent_and_cache(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        parent = local.create_issue("Parent Epic", body=SPEC_BODY_WITH_EXPECTED_FILES, labels=["type:frontier", "spec:approved"])
        child = local.create_issue("Sub Slice", body="implement widget", labels=["status:ready"], parent_number=parent.number)

        monkeypatch.setattr("tools.brigade.fsm.is_treehouse_installed", lambda: False)
        monkeypatch.setattr("tools.brigade.fsm.BrigadeFSM._run_radar_rescan", lambda self: None)
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "brigade",
                "start-slice",
                str(repo),
                "--name",
                "widget-core",
                "--track",
                "feature",
                "--issue",
                str(child.number),
                "--parent-issue",
                str(parent.number),
                "--offline",
            ],
        )
        with redirect_stdout(io.StringIO()):
            rc_start = brigade_cli.main()
        assert rc_start == 0

        fsm = BrigadeFSM(repo)
        ticket = fsm.state.active_ticket
        assert ticket is not None
        assert ticket.issue_number == child.number
        assert ticket.parent_issue == parent.number
        assert ticket.tracker_offline is True
        assert ticket.expected_files == ["src/core/widget.ts", "tests/widget.test.ts"]

        cached_spec = repo / ".edge" / "cache" / "issues" / f"{parent.number}.md"
        assert cached_spec.is_file()
        assert LocalTrackerBackend(repo).get_issue(child.number).labels == ["status:in-progress"]
        assert "status:ready" not in LocalTrackerBackend(repo).get_issue(child.number).labels

        # Create fast-forward slice branch and advance FSM to STAGING
        _git(repo, "checkout", "-b", ticket.branch_name)
        (repo / "src" / "core").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "core" / "widget.ts").write_text("export const w = 1;\n", encoding="utf-8")
        _git(repo, "add", "src/core/widget.ts")
        _git(repo, "commit", "-m", "feat: widget")
        _git(repo, "checkout", "development")

        fsm.state.current_state = CycleState.STAGING
        fsm.save()

        monkeypatch.setattr(sys, "argv", ["brigade", "finish-slice", str(repo), "--offline"])
        with redirect_stdout(io.StringIO()):
            rc_finish = brigade_cli.main()
        assert rc_finish == 0

        after_fsm = BrigadeFSM(repo)
        assert after_fsm.state.current_state == CycleState.IDLE
        assert after_fsm.state.active_ticket is None

        # Child closed with status:done; Parent stays OPEN; cache file NOT archived (`INV-CACHE-NO-ARCHIVE`)
        child_after = LocalTrackerBackend(repo).get_issue(child.number)
        parent_after = LocalTrackerBackend(repo).get_issue(parent.number)
        assert child_after.state == "closed"
        assert "status:done" in child_after.labels
        assert parent_after.state == "open"
        assert cached_spec.is_file()
        assert not (repo / ".edge" / "archive" / "specs" / f"{parent.number}.md").exists()

        # Contrast check: _archive_ticket_spec never touches .edge/cache/ but still archives .edge/specs/
        legacy_spec = repo / ".edge" / "specs" / "legacy-slice.md"
        legacy_spec.parent.mkdir(parents=True, exist_ok=True)
        legacy_spec.write_text("# Legacy Spec\n", encoding="utf-8")
        after_fsm._archive_ticket_spec(_make_ticket(branch_name="feat/legacy-slice", spec_path=".edge/cache/issues/1.md"))
        assert cached_spec.is_file()
        assert not legacy_spec.exists()
        assert (repo / ".edge" / "archive" / "specs" / "legacy-slice.md").is_file()

    def test_start_slice_parent_only_never_closes_parent_on_finish(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        parent = LocalTrackerBackend(repo).create_issue(
            "Parent Only",
            body=SPEC_BODY_WITH_EXPECTED_FILES,
            labels=["type:frontier", "spec:approved"],
        )

        monkeypatch.setattr("tools.brigade.fsm.is_treehouse_installed", lambda: False)
        monkeypatch.setattr("tools.brigade.fsm.BrigadeFSM._run_radar_rescan", lambda self: None)

        fsm = BrigadeFSM(repo)
        ok, ticket, msg = fsm.start_slice(
            name="parent-only",
            track="feature",
            parent_issue=parent.number,
            offline=True,
        )
        assert ok and ticket is not None, msg
        assert ticket.issue_number is None
        assert ticket.parent_issue == parent.number
        assert ticket.expected_files == ["src/core/widget.ts", "tests/widget.test.ts"]

        _git(repo, "checkout", "-b", ticket.branch_name)
        (repo / "README.md").write_text("# updated\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "update")
        _git(repo, "checkout", "development")

        fsm.state.current_state = CycleState.STAGING
        fsm.save()
        ok_fin, msg_fin = fsm.finish_slice(offline=True)
        assert ok_fin, msg_fin
        assert LocalTrackerBackend(repo).get_issue(parent.number).state == "open"

    def test_finish_slice_preflight_blocks_before_git_merge_on_auth_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo", remote_url="https://github.com/acme/widgets.git")
        _git(repo, "checkout", "-b", "feat/preflight-auth")
        (repo / "feature.txt").write_text("new\n", encoding="utf-8")
        _git(repo, "add", "feature.txt")
        _git(repo, "commit", "-m", "feat")
        _git(repo, "checkout", "development")
        head_before = _git(repo, "rev-parse", "HEAD")

        fsm = BrigadeFSM(repo)
        fsm.state.current_state = CycleState.STAGING
        fsm.state.active_branch = "feat/preflight-auth"
        fsm.state.active_ticket = _make_ticket(
            branch_name="feat/preflight-auth",
            issue_number=42,
            tracker_offline=False,
        )
        fsm.save()

        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _name, *_a, **_kw: None)

        with pytest.raises(TrackerAuthError) as exc:
            fsm.finish_slice()
        assert exc.value.exit_code == 2
        assert _git(repo, "rev-parse", "HEAD") == head_before
        assert BrigadeFSM(repo).state.current_state == CycleState.STAGING

        monkeypatch.setattr(sys, "argv", ["brigade", "finish-slice", str(repo)])
        with redirect_stdout(io.StringIO()):
            rc = brigade_cli.main()
        assert rc == 2
        assert _git(repo, "rev-parse", "HEAD") == head_before

    def test_finish_slice_post_merge_close_failure_warns_and_resets_fsm_to_idle(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        child = LocalTrackerBackend(repo).create_issue("Post Merge Test", labels=["status:in-progress"])
        _git(repo, "checkout", "-b", "feat/post-merge")
        (repo / "post.txt").write_text("ok\n", encoding="utf-8")
        _git(repo, "add", "post.txt")
        _git(repo, "commit", "-m", "post merge")
        _git(repo, "checkout", "development")

        fsm = BrigadeFSM(repo)
        fsm.state.current_state = CycleState.STAGING
        fsm.state.active_branch = "feat/post-merge"
        fsm.state.active_ticket = _make_ticket(
            branch_name="feat/post-merge",
            issue_number=child.number,
            tracker_offline=True,
        )
        fsm.save()

        monkeypatch.setattr("tools.brigade.fsm.BrigadeFSM._run_radar_rescan", lambda self: None)

        def boom_close(*_args, **_kwargs):
            raise TrackerError("simulated post-merge API outage")

        monkeypatch.setattr(LocalTrackerBackend, "close_issue", boom_close)

        buf = io.StringIO()
        with redirect_stdout(buf):
            ok, msg = fsm.finish_slice(offline=True)

        assert ok is True, msg
        assert (repo / "post.txt").is_file()
        assert BrigadeFSM(repo).state.current_state == CycleState.IDLE
        assert BrigadeFSM(repo).state.active_ticket is None
        assert "warn" in (buf.getvalue() + msg).lower()

    def test_confirm_merge_completes_tracker_issue_with_offline_flag(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        child = LocalTrackerBackend(repo).create_issue("PR Child", labels=["status:in-progress"])

        fsm = BrigadeFSM(repo)
        fsm.state.current_state = CycleState.AWAITING_MERGE
        fsm.state.active_branch = "feat/pr-child"
        fsm.state.active_ticket = _make_ticket(
            branch_name="feat/pr-child",
            issue_number=child.number,
            tracker_offline=False,
        )
        fsm.state.active_ticket.pr_url = "https://github.com/acme/widgets/pull/88"
        fsm.save()

        monkeypatch.setattr(
            "tools.brigade.fsm.run_command",
            lambda *_a, **_kw: (0, '{"state": "MERGED", "url": "https://github.com/acme/widgets/pull/88"}', ""),
        )
        monkeypatch.setattr(sys, "argv", ["brigade", "confirm-merge", str(repo), "--offline"])
        with redirect_stdout(io.StringIO()):
            rc = brigade_cli.main()

        assert rc == 0
        assert BrigadeFSM(repo).state.current_state == CycleState.IDLE
        closed = LocalTrackerBackend(repo).get_issue(child.number)
        assert closed.state == "closed"
        assert "status:done" in closed.labels


# =============================================================================
# 3. Tasks Bridge, Refactor Tickets, Radar Export & Legacy Fallback
# =============================================================================


class TestTasksBridgeAndRadarExport:
    def test_create_refactor_ticket_tracker_default_parent_hold_and_no_sync(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        parent = LocalTrackerBackend(repo).create_issue("Refactor Epic", labels=["type:frontier"])

        # Default sync_tasks=None -> syncs tracker
        ok, ticket_path, issue_id = tasks_bridge.create_refactor_ticket(
            repo_path=repo,
            slug="bookings-cc",
            track="core",
            target_rules=["RULE-MAX-CC"],
            target_files=["src/core/bookings.ts"],
            metric_targets={"max_cc": 8},
            parent_issue=parent.number,
            offline=True,
            hold_captain=True,
        )
        assert ok is True
        assert issue_id == "2"
        fm, _ = _parse_frontmatter(ticket_path)
        assert fm["issue_number"] == 2
        assert fm["parent_issue"] == parent.number
        assert fm["tasks_axi_id"] is None

        issue = LocalTrackerBackend(repo).get_issue(2)
        assert issue.parent_number == parent.number
        assert {"track:core", "status:ready", "hold:captain"}.issubset(set(issue.labels))

        # CLI default (neither --sync-tasks nor --no-sync-tasks) -> syncs tracker
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "brigade",
                "create-refactor-ticket",
                str(repo),
                "--slug",
                "cli-default-sync",
                "--track",
                "ui",
                "--rules",
                "RULE-UI",
                "--files",
                "src/ui/Card.tsx",
                "--parent-issue",
                str(parent.number),
                "--offline",
            ],
        )
        with redirect_stdout(io.StringIO()):
            assert brigade_cli.main() == 0
        fm_cli, _ = _parse_frontmatter(repo / ".edge" / "tickets" / "refactor" / "cli-default-sync.md")
        assert fm_cli["issue_number"] == 3

        # CLI --no-sync-tasks -> skips tracker issue creation
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "brigade",
                "create-refactor-ticket",
                str(repo),
                "--slug",
                "cli-no-sync",
                "--track",
                "core",
                "--no-sync-tasks",
                "--offline",
            ],
        )
        with redirect_stdout(io.StringIO()):
            assert brigade_cli.main() == 0
        fm_nosync, _ = _parse_frontmatter(repo / ".edge" / "tickets" / "refactor" / "cli-no-sync.md")
        assert fm_nosync.get("issue_number") is None
        assert len(LocalTrackerBackend(repo).list_issues(state="all")) == 3

    def test_complete_linked_task_tracker_and_legacy_fallback(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        issue = LocalTrackerBackend(repo).create_issue("Refactor #1", labels=["status:ready", "track:core"])

        ok, msg = tasks_bridge.complete_linked_task(
            None,
            pr_url="https://github.com/acme/widgets/pull/5",
            repo_path=repo,
            issue_number=issue.number,
            offline=True,
        )
        assert ok is True, msg
        done_issue = LocalTrackerBackend(repo).get_issue(issue.number)
        assert done_issue.state == "closed"
        assert "status:done" in done_issue.labels
        assert "status:ready" not in done_issue.labels
        assert any("pull/5" in c.body for c in done_issue.comments)

        # Legacy tasks-axi fallback ONLY when issue_number is None and tasks_axi_id is set
        recorded: List[List[str]] = []
        monkeypatch.setattr(shutil, "which", lambda name, *_a, **_kw: "/usr/local/bin/tasks-axi" if name == "tasks-axi" else None)

        def fake_run(cmd, **_kw):
            recorded.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "done\n", "")

        monkeypatch.setattr(subprocess, "run", fake_run)
        ok_leg, _ = tasks_bridge.complete_linked_task("legacy-task-7", pr_url="https://github.com/acme/widgets/pull/6")
        assert ok_leg is True
        assert any(cmd[:3] == ["tasks-axi", "done", "legacy-task-7"] for cmd in recorded)

    def test_radar_export_tasks_parent_issue_and_offline_default_sync(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        parent = LocalTrackerBackend(repo).create_issue("Radar Debt Parent", labels=["type:frontier"])

        ledger = LedgerEngine(repo)
        ledger.sync_channel(
            "core",
            [
                LedgerItem(
                    fingerprint=LedgerItem.generate_fingerprint("RULE-MAX-CC", "src/core/calc.ts", "compute"),
                    track=Track.CORE.value,
                    rule_id="RULE-MAX-CC",
                    title="High cyclomatic complexity",
                    file_path="src/core/calc.ts",
                    line_number=12,
                    symbol="compute",
                    severity=FindingSeverity.WARNING.value,
                    status=FindingStatus.OPEN.value,
                    details={"max_cc": 14},
                    suggested_fix="Extract helper functions",
                    first_seen_at="2026-11-25T00:00:00Z",
                    last_seen_at="2026-11-25T00:00:00Z",
                )
            ],
        )

        buf = io.StringIO()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "radar",
                "export-tasks",
                str(repo),
                "--parent-issue",
                str(parent.number),
                "--offline",
            ],
        )
        with redirect_stdout(buf):
            radar_cli.main()

        out = buf.getvalue()
        assert "#2" in out
        exported = LocalTrackerBackend(repo).get_issue(2)
        assert exported.parent_number == parent.number
        assert "track:core" in exported.labels


# =============================================================================
# 4. Spec Critic & QA Fiber Frontier Cutover
# =============================================================================


class TestSpecCriticAndQaFrontier:
    def test_critique_spec_issue_caches_writes_report_and_posts_comment(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        issue1 = local.create_issue("Spec One", body="# Spec One\nContent", labels=["type:frontier", "spec:draft"])
        issue2 = local.create_issue("Spec Two", body="# Spec Two\nContent", labels=["type:frontier", "spec:draft"])

        monkeypatch.setattr(
            spec_critic,
            "run_command",
            lambda *_a, **_kw: (0, "## Paraphrase\nCritique looks clean.", ""),
        )

        # Missing both --spec and --issue -> exit 1
        monkeypatch.setattr(sys, "argv", ["brigade", "critique-spec", str(repo)])
        with redirect_stdout(io.StringIO()):
            assert brigade_cli.main() == 1

        # --issue 1 -> caches, writes .edge/cache/issues/1-critique.md, posts comment on #1
        monkeypatch.setattr(sys, "argv", ["brigade", "critique-spec", str(repo), "--issue", str(issue1.number), "--offline"])
        with redirect_stdout(io.StringIO()):
            rc1 = brigade_cli.main()
        assert rc1 == 0
        assert (repo / ".edge" / "cache" / "issues" / f"{issue1.number}.md").is_file()
        crit_file1 = repo / ".edge" / "cache" / "issues" / f"{issue1.number}-critique.md"
        assert crit_file1.is_file()
        assert len(LocalTrackerBackend(repo).get_issue(issue1.number).comments) == 1
        assert "Critique looks clean." in LocalTrackerBackend(repo).get_issue(issue1.number).comments[0].body

        # --no-post-comment -> writes report, skips comment on #2
        monkeypatch.setattr(
            sys,
            "argv",
            ["brigade", "critique-spec", str(repo), "--issue", str(issue2.number), "--offline", "--no-post-comment"],
        )
        with redirect_stdout(io.StringIO()):
            rc2 = brigade_cli.main()
        assert rc2 == 0
        assert (repo / ".edge" / "cache" / "issues" / f"{issue2.number}-critique.md").is_file()
        assert LocalTrackerBackend(repo).get_issue(issue2.number).comments == []

    def test_qa_fiber_and_cmd_qa_inspect_stage_dedupe_and_handle_auth_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        comp_dir = repo / "src" / "components"
        comp_dir.mkdir(parents=True, exist_ok=True)
        (comp_dir / "SaveCard.tsx").write_text(
            "export function SaveCard() {\n  return <button className='save'>Kaydet</button>;\n}\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(
            qa_fiber,
            "execute_browser_eval",
            lambda _js: {
                "success": True,
                "tag": "BUTTON",
                "text": "Kaydet",
                "classes": "save",
                "hierarchy": ["button", "SaveCard"],
                "debugSource": {"fileName": "src/components/SaveCard.tsx", "lineNumber": 2},
            },
        )

        buf = io.StringIO()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "brigade",
                "qa-inspect",
                "button.save",
                str(repo),
                "--issue",
                "Button overflows container",
                "--category",
                "overflow",
                "--offline",
            ],
        )
        with redirect_stdout(buf):
            rc = brigade_cli.main()

        assert rc == 0
        assert "Staged to tracker frontier:" in buf.getvalue()
        assert not (repo / ".frontier.toml").exists()

        issues = LocalTrackerBackend(repo).list_issues(state="open", labels=["type:frontier"])
        assert len(issues) == 1
        assert "track:ui" in issues[0].labels
        assert "Button overflows container" in issues[0].title

        # Second staging call with same anomaly dedupes cleanly
        second_res = qa_fiber.stage_to_frontier(
            repo_path=repo,
            file_path="src/components/SaveCard.tsx",
            line_number=2,
            component="SaveCard",
            issue="Button overflows container",
            category="overflow",
            offline=True,
        )
        assert second_res["success"] is True
        assert len(LocalTrackerBackend(repo).list_issues(state="open", labels=["type:frontier"])) == 1

        # GitHub remote with missing auth/binary -> cmd_qa_inspect exits 2 cleanly without traceback
        gh_repo = _init_repo(tmp_path / "gh_repo", remote_url="https://github.com/acme/widgets.git")
        (gh_repo / "src" / "components").mkdir(parents=True, exist_ok=True)
        (gh_repo / "src" / "components" / "SaveCard.tsx").write_text(
            "export function SaveCard() {\n  return <button className='save'>Kaydet</button>;\n}\n",
            encoding="utf-8",
        )
        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _name, *_a, **_kw: None)
        monkeypatch.setattr(
            sys,
            "argv",
            ["brigade", "qa-inspect", "button.save", str(gh_repo), "--issue", "Button clips"],
        )
        err_buf = io.StringIO()
        with redirect_stdout(err_buf):
            rc_auth = brigade_cli.main()
        assert rc_auth == 2


# =============================================================================
# 5. Static Invariants (`INV-ORCH-HOOK-LATENCY` & `INV-MODULAR-FSM`)
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

    def _is_type_checking(test: ast.AST) -> bool:
        return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
            isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
        )

    def _walk(stmts: List[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, ast.If) and _is_type_checking(stmt.test):
                continue
            if isinstance(stmt, ast.Import):
                modules.extend(alias.name for alias in stmt.names)
            elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
                modules.append(stmt.module)
            for attr in ("body", "orelse", "finalbody", "handlers"):
                sub = getattr(stmt, attr, None)
                if isinstance(sub, list):
                    _walk(sub)

    _walk(tree.body)
    return modules


class TestSlice2StaticInvariants:
    def test_inv_orch_hook_latency_no_tracker_hooks_or_yaml(self) -> None:
        guard_path = ROOT_DIR / "tools" / "brigade" / "orchestrator_guard.py"
        visited: Set[Path] = set()
        imported: Set[str] = set()
        queue: List[Path] = [guard_path]

        while queue:
            current = queue.pop()
            if current in visited or not current.exists():
                continue
            visited.add(current)
            for mod in _collect_runtime_imports(current):
                imported.add(mod)
                if mod.startswith("tools."):
                    rel = Path(*mod.split("."))
                    cand_py = ROOT_DIR / f"{rel}.py"
                    cand_init = ROOT_DIR / rel / "__init__.py"
                    if cand_py.exists():
                        queue.append(cand_py)
                    elif cand_init.exists():
                        queue.append(cand_init)

        assert not any(m == "tools.tracker" or m.startswith("tools.tracker.") for m in imported)
        assert "tools.brigade.tasks_bridge" not in imported
        assert "tools.brigade.tracker_hooks" not in imported
        assert not any(m == "yaml" or m.startswith("yaml.") for m in imported)

    def test_inv_modular_fsm_tracker_hooks_budget_and_cc(self) -> None:
        hooks_path = ROOT_DIR / "tools" / "brigade" / "tracker_hooks.py"
        lines = hooks_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 200, f"tracker_hooks.py exceeds 200 lines ({len(lines)})"

        tree = ast.parse("\n".join(lines), filename=str(hooks_path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cc = _ast_cc(node)
                assert cc <= 10, f"tracker_hooks.py:{node.name} has CC={cc} > 10"
