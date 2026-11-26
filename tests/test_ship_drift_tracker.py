"""
Hermetic RED contract tests for Slice 3 (`ship-drift-tracker-bridge`).

Covers `.edge/specs/ship-drift-tracker-bridge.md`:
- `ship_tracker` (`discover_tracker_spec_candidates`, `resolve_pr_issue_refs`, `format_pr_issue_links`)
- `INV-NO-FALSE-CACHE-ANCHOR` (`issue-<N>` slugging, no commit-SHA `"42"` false anchor,
  worktree primary-root cache resolution without `relative_to()` crashes)
- `prepare-ship --issue --parent-issue --offline` (`SpecDigest`, `expected_files`,
  single `Closes #<C>` + `Parent Spec: #<P>`, never `Closes #<P>`, `--split-branches`
  scoping, zero trailing newlines when empty, coexistence with `.edge/specs/*.md`)
- `drift/tracker_specs.py` + `discover_specs` (outer-repo cache isolation, excludes
  `*-critique.md` & `meta.json`) + `consolidate --issue --archive-sources` (`INV-CACHE-NO-ARCHIVE`)
- Fail-fast `TrackerAuthError` exit `2` in both `brigade prepare-ship` and `drift consolidate`
- Static invariants (`INV-ORCH-HOOK-LATENCY`, `ship_tracker.py <= 200`L/`CC <= 10`, `tracker_specs.py <= 150`L/`CC <= 10`)
"""

import ast
import io
import json
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.brigade import cli as brigade_cli
from tools.brigade import ship_prep, ship_tracker
from tools.brigade.models import CycleState, Ticket
from tools.drift import cli as drift_cli
from tools.drift import scanner as drift_scanner
from tools.drift import tracker_specs
from tools.tracker.local_backend import LocalTrackerBackend

TRACKER_SPEC_BODY = (
    "---\n"
    "expected_files:\n"
    "  - src/core/billing.ts\n"
    "---\n\n"
    "# Spec: Billing Engine\n\n"
    "## 1. Intent\n\n"
    "Compute deterministic invoice totals.\n\n"
    "## 2. Acceptance Criteria\n"
    "- Handles currency rounding.\n"
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
    _git(repo_dir, "commit", "-m", "initial commit")
    if remote_url:
        _git(repo_dir, "remote", "add", "origin", remote_url)
    return repo_dir


# =============================================================================
# 1. ship_tracker Unit Contracts
# =============================================================================


class TestShipTrackerHelpers:
    def test_format_pr_issue_links_never_closes_parent_and_handles_empty(self) -> None:
        assert ship_tracker.format_pr_issue_links([], None) == ""
        assert ship_tracker.format_pr_issue_links([10], parent_issue=10) == "Parent Spec: #10"
        links = ship_tracker.format_pr_issue_links([42, 42, 43], parent_issue=10)
        assert "Closes #42" in links
        assert "Closes #43" in links
        assert links.count("Closes #42") == 1
        assert "Parent Spec: #10" in links
        assert "Closes #10" not in links

    def test_discover_tracker_spec_candidates_explicit_and_brigade_fallback(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        p = local.create_issue("Parent Spec", body=TRACKER_SPEC_BODY, labels=["type:frontier"])
        c1 = local.create_issue("Child 1", body=TRACKER_SPEC_BODY, parent_number=p.number)

        cands = ship_tracker.discover_tracker_spec_candidates(
            repo, issue_numbers=[c1.number], parent_issue=p.number, offline=True
        )
        assert f".edge/cache/issues/{c1.number}.md" in cands
        assert (repo / ".edge" / "cache" / "issues" / f"{c1.number}.md").is_file()

        # Fallback from .edge/brigade.json when explicit args omitted
        (repo / ".edge").mkdir(parents=True, exist_ok=True)
        brigade_state = {
            "base_branch": "development",
            "current_state": CycleState.REVIEW.value,
            "active_ticket": Ticket(
                ticket_id="TICK-FEAT-BILLING",
                track="feature",
                domain="billing",
                rule_id="SLICE-BILLING",
                severity="NORMAL",
                target_file="src/core/billing.ts",
                line_number=1,
                fingerprint="fp-billing",
                description="Billing",
                suggested_fix="Fix",
                issue_number=c1.number,
                parent_issue=p.number,
                tracker_offline=True,
            ).to_dict(),
        }
        (repo / ".edge" / "brigade.json").write_text(json.dumps(brigade_state), encoding="utf-8")

        from_state = ship_tracker.discover_tracker_spec_candidates(repo)
        assert f".edge/cache/issues/{c1.number}.md" in from_state

        refs_unscoped, out_parent = ship_tracker.resolve_pr_issue_refs(repo)
        assert refs_unscoped == [c1.number]
        assert out_parent == p.number

        refs_scoped, _ = ship_tracker.resolve_pr_issue_refs(
            repo, issue_numbers=[42, 43], parent_issue=10, spec_rel=".edge/cache/issues/43.md"
        )
        assert refs_scoped == [43]


# =============================================================================
# 2. Ship Prep Integration & Invariants
# =============================================================================


class TestShipPrepTrackerBridge:
    def test_inv_no_false_cache_anchor_on_commit_42_and_worktree_cache_resolution(self, tmp_path: Path) -> None:
        primary = _init_repo(tmp_path / "primary")
        # Create unrelated cached issue 42 on disk (not referenced by --issue or brigade.json)
        cache_dir = primary / ".edge" / "cache" / "issues"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "42.md").write_text(TRACKER_SPEC_BODY, encoding="utf-8")
        (cache_dir / "42-critique.md").write_text("# Critique\n", encoding="utf-8")

        _git(primary, "checkout", "-b", "feat/unrelated-work")
        (primary / "src" / "core").mkdir(parents=True, exist_ok=True)
        (primary / "src" / "core" / "billing.ts").write_text("export const x = 42;\n", encoding="utf-8")
        _git(primary, "add", "src/core/billing.ts")
        # Commit message deliberately contains "42"
        _git(primary, "commit", "-m", "feat: tweak constant 42 in billing")

        ok, res, err = ship_prep.prepare_ship_payload(primary, base_branch="development")
        assert ok, err
        assert "issue-42" not in [p.spec_slug for p in res.spec_plans]
        assert not any("42" in s for s in res.specs_linked)
        assert not res.pr_body.endswith("\n\n")

        # Now run from inside a leased git worktree with explicit issue #42 (no relative_to crash!)
        local = LocalTrackerBackend(primary)
        created = local.create_issue("Billing Spec", body=TRACKER_SPEC_BODY, labels=["spec:approved"])
        wt = tmp_path / "leased-wt"
        _git(primary, "worktree", "add", str(wt), "-b", "feat/wt-billing", "feat/unrelated-work")

        ok_wt, res_wt, err_wt = ship_prep.prepare_ship_payload(
            wt, base_branch="development", issue_numbers=[created.number], offline=True
        )
        assert ok_wt, err_wt
        assert [p.spec_slug for p in res_wt.spec_plans] == [f"issue-{created.number}"]
        assert res_wt.spec_plans[0].expected_files == ["src/core/billing.ts"]

    def test_prepare_ship_cli_single_footer_no_double_emit_and_legacy_coexistence(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        parent = local.create_issue("Parent Epic", body="# Epic\nOverview", labels=["type:frontier"])
        child = local.create_issue("Billing Spec", body=TRACKER_SPEC_BODY, labels=["status:in-progress"], parent_number=parent.number)
        assert child.number == 2

        # Coexist with legacy .edge/specs/*.md
        legacy_dir = repo / ".edge" / "specs"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "legacy-auth.md").write_text(
            "---\nexpected_files:\n  - src/core/auth.ts\n---\n\n# Spec: Legacy Auth\n",
            encoding="utf-8",
        )

        _git(repo, "checkout", "-b", "feat/ship-both")
        (repo / "src" / "core").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "core" / "billing.ts").write_text("export const b = 1;\n", encoding="utf-8")
        (repo / "src" / "core" / "auth.ts").write_text("export const a = 1;\n", encoding="utf-8")
        _git(repo, "add", "src/core/billing.ts", "src/core/auth.ts")
        _git(repo, "commit", "-m", "feat(legacy-auth): implement billing and auth")

        # 1. Single PR with --issue 2 --parent-issue 1 --offline
        buf = io.StringIO()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "brigade",
                "prepare-ship",
                str(repo),
                "--base",
                "development",
                "--issue",
                str(child.number),
                "--parent-issue",
                str(parent.number),
                "--offline",
                "--format",
                "json",
            ],
        )
        with redirect_stdout(buf):
            rc = brigade_cli.main()
        assert rc == 0
        payload = json.loads(buf.getvalue())
        slugs = {p["spec_slug"] for p in payload["spec_plans"]}
        assert {f"issue-{child.number}", "legacy-auth"}.issubset(slugs)
        pr_body = payload["pr_body"]
        assert pr_body.count(f"Closes #{child.number}") == 1
        assert pr_body.count(f"Parent Spec: #{parent.number}") == 1
        assert f"Closes #{parent.number}" not in pr_body

        # 2. Selecting --spec issue-2 with --format show-me does NOT double-emit and puts links before ## Ship Command
        buf_show = io.StringIO()
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "brigade",
                "prepare-ship",
                str(repo),
                "--base",
                "development",
                "--spec",
                f"issue-{child.number}",
                "--issue",
                str(child.number),
                "--parent-issue",
                str(parent.number),
                "--offline",
                "--format",
                "show-me",
            ],
        )
        with redirect_stdout(buf_show):
            assert brigade_cli.main() == 0
        show_text = buf_show.getvalue()
        assert show_text.count(f"Closes #{child.number}") == 1
        assert show_text.index(f"Closes #{child.number}") < show_text.index("## Ship Command")

    def test_prepare_ship_split_branches_scopes_closes_per_plan(self, tmp_path: Path) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        p = local.create_issue("Parent", body="# Epic", labels=["type:frontier"])
        c1 = local.create_issue(
            "Alpha",
            body="---\nexpected_files:\n  - src/alpha.ts\n---\n\n# Alpha\n",
            parent_number=p.number,
        )
        c2 = local.create_issue(
            "Beta",
            body="---\nexpected_files:\n  - src/beta.ts\n---\n\n# Beta\n",
            parent_number=p.number,
        )

        _git(repo, "checkout", "-b", "feat/split-issues")
        (repo / "src").mkdir(parents=True, exist_ok=True)
        (repo / "src" / "alpha.ts").write_text("export const alpha = 1;\n", encoding="utf-8")
        _git(repo, "add", "src/alpha.ts")
        _git(repo, "commit", "-m", "feat: alpha")

        (repo / "src" / "beta.ts").write_text("export const beta = 2;\n", encoding="utf-8")
        _git(repo, "add", "src/beta.ts")
        _git(repo, "commit", "-m", "feat: beta")

        ok, res, err = ship_prep.prepare_ship_payload(
            repo,
            base_branch="development",
            split_branches=True,
            issue_numbers=[c1.number, c2.number],
            parent_issue=p.number,
            offline=True,
        )
        assert ok, err
        by_slug = {plan.spec_slug: plan for plan in res.spec_plans}
        assert f"issue-{c1.number}" in by_slug and f"issue-{c2.number}" in by_slug

        plan1 = by_slug[f"issue-{c1.number}"]
        plan2 = by_slug[f"issue-{c2.number}"]
        assert f"Closes #{c1.number}" in plan1.pr_body
        assert f"Closes #{c2.number}" not in plan1.pr_body
        assert f"Parent Spec: #{p.number}" in plan1.pr_body
        assert f"Closes #{p.number}" not in plan1.pr_body

        assert f"Closes #{c2.number}" in plan2.pr_body
        assert f"Closes #{c1.number}" not in plan2.pr_body


# =============================================================================
# 3. Drift Discovery, Consolidation & Cache Preservation
# =============================================================================


class TestDriftTrackerSpecs:
    def test_list_cached_issue_specs_isolated_and_excludes_critique_and_meta(self, tmp_path: Path) -> None:
        # Uninitialized tmp_path subdir MUST NOT leak an outer git repo's cache
        outer = _init_repo(tmp_path / "outer_git")
        outer_cache = outer / ".edge" / "cache" / "issues"
        outer_cache.mkdir(parents=True, exist_ok=True)
        (outer_cache / "999.md").write_text("# Outer leak\n", encoding="utf-8")

        isolated = outer / "nested_uninit_dir"
        isolated.mkdir(parents=True)
        assert tracker_specs.list_cached_issue_specs(isolated) == []
        assert ".edge/cache/issues/999.md" not in drift_scanner.discover_specs(isolated).ephemeral_candidates

        # Local cache includes <N>.md, excludes *-critique.md and meta.json
        local_cache = isolated / ".edge" / "cache" / "issues"
        local_cache.mkdir(parents=True, exist_ok=True)
        (local_cache / "42.md").write_text("# Issue 42\n", encoding="utf-8")
        (local_cache / "42-critique.md").write_text("# Critique\n", encoding="utf-8")
        (local_cache / "meta.json").write_text("{}", encoding="utf-8")

        assert tracker_specs.list_cached_issue_specs(isolated) == [".edge/cache/issues/42.md"]
        report = drift_scanner.discover_specs(isolated)
        assert ".edge/cache/issues/42.md" in report.ephemeral_candidates
        assert ".edge/cache/issues/42-critique.md" not in report.ephemeral_candidates
        assert ".edge/cache/issues/meta.json" not in report.ephemeral_candidates
        assert ".edge/cache/issues/42.md" not in drift_scanner.discover_specs(isolated, include_cached_issues=False).ephemeral_candidates

    def test_drift_consolidate_issue_preserves_cache_and_archives_legacy(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo")
        local = LocalTrackerBackend(repo)
        issue = local.create_issue("Billing Domain Spec", body=TRACKER_SPEC_BODY, labels=["spec:approved"])

        legacy_spec = repo / ".edge" / "specs" / "legacy-billing.md"
        legacy_spec.parent.mkdir(parents=True, exist_ok=True)
        legacy_spec.write_text("# Legacy Billing\n", encoding="utf-8")

        monkeypatch.setattr(
            drift_scanner,
            "run_command",
            lambda cmd, **_kw: (0, "deadbeef" if cmd[:2] == ["git", "rev-parse"] else "---\ndomain: billing\ntracked_paths:\n  - src/core/billing.ts\n---\n\n# Billing Domain Contract\n", ""),
        )

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = drift_cli.main(
                [
                    "consolidate",
                    str(repo),
                    "--domain",
                    "billing",
                    "--paths",
                    "src/core/billing.ts",
                    "--sources",
                    str(legacy_spec),
                    "--issue",
                    str(issue.number),
                    "--archive-sources",
                    "--offline",
                ]
            )
        assert rc == 0

        cached_issue = repo / ".edge" / "cache" / "issues" / f"{issue.number}.md"
        assert cached_issue.is_file()
        assert not (repo / ".edge" / "archive" / "specs" / f"{issue.number}.md").exists()
        assert not legacy_spec.exists()
        assert (repo / ".edge" / "archive" / "specs" / "legacy-billing.md").is_file()

        # Direct call to archive_ephemeral_spec with non-normalized `..` cache path also refuses to move
        assert drift_scanner.archive_ephemeral_spec(repo, cached_issue.parent / ".." / "issues" / f"{issue.number}.md") is None
        assert cached_issue.is_file()


# =============================================================================
# 4. Fail-Fast Auth Exit 2 & Static Invariants
# =============================================================================


class TestSlice3FailFastAndInvariants:
    def test_auth_failure_exits_2_in_prepare_ship_and_drift_consolidate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = _init_repo(tmp_path / "repo", remote_url="https://github.com/acme/widgets.git")
        _git(repo, "checkout", "-b", "feat/auth-fail")
        (repo / "src.ts").write_text("export const x = 1;\n", encoding="utf-8")
        _git(repo, "add", "src.ts")
        _git(repo, "commit", "-m", "feat")

        monkeypatch.delenv("EDGE_TRACKER", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _name, *_a, **_kw: None)

        monkeypatch.setattr(
            sys,
            "argv",
            ["brigade", "prepare-ship", str(repo), "--base", "development", "--issue", "42"],
        )
        with redirect_stdout(io.StringIO()):
            assert brigade_cli.main() == 2

        with redirect_stdout(io.StringIO()):
            rc_drift = drift_cli.main(
                [
                    "consolidate",
                    str(repo),
                    "--domain",
                    "billing",
                    "--paths",
                    "src.ts",
                    "--issue",
                    "42",
                ]
            )
        assert rc_drift == 2

    def test_inv_orch_hook_latency_and_companion_budgets(self) -> None:
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

        def _runtime_imports(py_file: Path) -> List[str]:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            mods: List[str] = []
            for stmt in tree.body:
                if isinstance(stmt, ast.Import):
                    mods.extend(a.name for a in stmt.names)
                elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
                    mods.append(stmt.module)
            return mods

        guard_path = ROOT_DIR / "tools" / "brigade" / "orchestrator_guard.py"
        visited: Set[Path] = set()
        imported: Set[str] = set()
        queue: List[Path] = [guard_path]
        while queue:
            cur = queue.pop()
            if cur in visited or not cur.exists():
                continue
            visited.add(cur)
            for mod in _runtime_imports(cur):
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
        assert "tools.brigade.ship_tracker" not in imported
        assert "tools.drift.tracker_specs" not in imported

        for rel_path, max_lines in (
            ("tools/brigade/ship_tracker.py", 200),
            ("tools/drift/tracker_specs.py", 150),
        ):
            target = ROOT_DIR / rel_path
            lines = target.read_text(encoding="utf-8").splitlines()
            assert len(lines) <= max_lines, f"{rel_path} exceeds {max_lines} lines ({len(lines)})"
            tree = ast.parse("\n".join(lines), filename=str(target))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cc = _ast_cc(node)
                    assert cc <= 10, f"{rel_path}:{node.name} has CC={cc} > 10"
