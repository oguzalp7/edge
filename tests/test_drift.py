#!/usr/bin/env python3
"""
Unit Tests for edge-drift:
Tests frontmatter parsing, recursive path matching, Zero-Token Invariant,
triggered LLM drift audit, spec discovery, ephemeral spec archiving,
domain consolidation, and CLI entry points.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, List, Dict
from unittest.mock import patch, MagicMock

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.drift.models import (
    DomainContract,
    DomainDriftRecord,
    DriftCheckResult,
    SpecDiscoveryReport,
    DriftStateStore,
    parse_domain_frontmatter,
    matches_tracked_paths,
)
from tools.drift.scanner import (
    DRIFT_MODEL,
    archive_ephemeral_spec,
    check_drift,
    discover_specs,
    consolidate_domain,
    get_head_sha,
    get_changed_files_since,
)
from tools.drift.cli import run_drift


class TestFrontmatterAndPathMatching(unittest.TestCase):
    def test_parse_frontmatter_block_list(self):
        content = """---
domain: bookings
tracked_paths:
  - src/lib/bookings/**
  - src/actions/bookings.ts
---
# Bookings Domain
Core rules here.
"""
        domain, paths, body = parse_domain_frontmatter(content, fallback_domain="fallback")
        self.assertEqual(domain, "bookings")
        self.assertEqual(paths, ["src/lib/bookings/**", "src/actions/bookings.ts"])
        self.assertIn("# Bookings Domain", body)

    def test_parse_frontmatter_inline_list(self):
        content = """---
domain: "orders"
tracked_paths: ["src/lib/orders/**", "src/actions/orders.ts"]
---
# Orders Domain
"""
        domain, paths, body = parse_domain_frontmatter(content, fallback_domain="fallback")
        self.assertEqual(domain, "orders")
        self.assertEqual(paths, ["src/lib/orders/**", "src/actions/orders.ts"])
        self.assertIn("# Orders Domain", body)

    def test_parse_frontmatter_fallback_domain(self):
        content = """---
tracked_paths:
  - src/lib/users/**
---
# Users
"""
        domain, paths, body = parse_domain_frontmatter(content, fallback_domain="users")
        self.assertEqual(domain, "users")
        self.assertEqual(paths, ["src/lib/users/**"])

    def test_parse_frontmatter_no_frontmatter(self):
        content = "# Raw Document without frontmatter\nBody text"
        domain, paths, body = parse_domain_frontmatter(content, fallback_domain="raw")
        self.assertEqual(domain, "raw")
        self.assertEqual(paths, [])
        self.assertEqual(body, content)

    def test_matches_tracked_paths_exact(self):
        files = ["src/actions/bookings.ts", "src/actions/users.ts"]
        tracked = ["src/actions/bookings.ts"]
        matched = matches_tracked_paths(files, tracked)
        self.assertEqual(matched, ["src/actions/bookings.ts"])

    def test_matches_tracked_paths_recursive_glob(self):
        files = [
            "src/lib/bookings/repo.ts",
            "src/lib/bookings/deep/util.ts",
            "src/lib/bookings/nested/very/deep/file.ts",
            "src/lib/other/service.ts",
        ]
        tracked = ["src/lib/bookings/**"]
        matched = matches_tracked_paths(files, tracked)
        self.assertEqual(
            matched,
            [
                "src/lib/bookings/repo.ts",
                "src/lib/bookings/deep/util.ts",
                "src/lib/bookings/nested/very/deep/file.ts",
            ],
        )

    def test_matches_tracked_paths_windows_backslashes(self):
        files = [r"src\lib\bookings\repo.ts", r"src\other\file.ts"]
        tracked = ["src/lib/bookings/**"]
        matched = matches_tracked_paths(files, tracked)
        self.assertEqual(matched, [r"src\lib\bookings\repo.ts"])

    def test_matches_tracked_paths_leading_dot_slash(self):
        files = ["./src/lib/bookings/repo.ts"]
        tracked = ["./src/lib/bookings/**"]
        matched = matches_tracked_paths(files, tracked)
        self.assertEqual(matched, ["./src/lib/bookings/repo.ts"])

    def test_matches_tracked_paths_disjoint(self):
        files = ["src/components/Button.tsx", "src/styles/main.css"]
        tracked = ["src/lib/bookings/**", "src/actions/bookings.ts"]
        matched = matches_tracked_paths(files, tracked)
        self.assertEqual(matched, [])


class TestDriftStateStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_load_record(self):
        store = DriftStateStore.load_from_repo(self.repo)
        self.assertEqual(len(store.records), 0)

        rec = store.update_record(
            domain="bookings",
            sha="abcdef123456",
            doc_path="docs/domains/bookings.md",
            tracked_paths=["src/lib/bookings/**"],
        )
        self.assertEqual(rec.domain, "bookings")
        self.assertEqual(rec.last_checked_sha, "abcdef123456")

        # Reload from disk
        store2 = DriftStateStore.load_from_repo(self.repo)
        loaded_rec = store2.get_record("bookings")
        self.assertIsNotNone(loaded_rec)
        self.assertEqual(loaded_rec.domain, "bookings")
        self.assertEqual(loaded_rec.last_checked_sha, "abcdef123456")
        self.assertEqual(loaded_rec.tracked_paths, ["src/lib/bookings/**"])


class TestDriftScanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

        # Create docs/domains/bookings.md
        domains_dir = self.repo / "docs" / "domains"
        domains_dir.mkdir(parents=True, exist_ok=True)
        self.contract_file = domains_dir / "bookings.md"
        self.contract_file.write_text(
            """---
domain: bookings
tracked_paths:
  - src/lib/bookings/**
  - src/actions/bookings.ts
---
# Bookings Domain Contract
## Core Invariants
1. Slots cannot overlap.
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.drift.scanner.run_command")
    def test_zero_token_invariant_when_sha_changed_but_no_tracked_files_changed(
        self, mock_run_command
    ):
        """
        Critical Zero-Token Invariant:
        When HEAD advances from sha_old to sha_new, but git diff shows changes
        strictly in other domains (e.g. src/users/profile.ts), agy MUST NOT be invoked.
        last_checked_sha must advance to sha_new with 0 LLM tokens.
        """
        # Seed state store with sha_old
        state_store = DriftStateStore.load_from_repo(self.repo)
        state_store.update_record(
            domain="bookings",
            sha="sha_old",
            doc_path="docs/domains/bookings.md",
            tracked_paths=["src/lib/bookings/**", "src/actions/bookings.ts"],
        )

        def mock_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_new", "")
            if cmd == ["git", "diff", "--name-only", "sha_old..HEAD"]:
                # Changes in an unrelated domain
                return (0, "src/users/profile.ts\nsrc/components/navbar.tsx", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                self.fail("Zero-Token Invariant VIOLATED: agy was invoked!")
            return (1, "", "Unknown command")

        mock_run_command.side_effect = mock_cmd

        results = check_drift(self.repo)
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.domain, "bookings")
        self.assertEqual(res.status, "CLEAN")
        self.assertFalse(res.llm_invoked)
        self.assertEqual(res.summary, "CLEAN (no tracked code changes)")

        # Verify state store advanced to sha_new
        store_after = DriftStateStore.load_from_repo(self.repo)
        rec = store_after.get_record("bookings")
        self.assertEqual(rec.last_checked_sha, "sha_new")

    @patch("tools.drift.scanner.run_command")
    def test_zero_token_when_sha_unchanged(self, mock_run_command):
        """
        When HEAD SHA has not changed at all, return CLEAN immediately with 0 git diffs and 0 LLM calls.
        """
        state_store = DriftStateStore.load_from_repo(self.repo)
        state_store.update_record(
            domain="bookings",
            sha="sha_same",
            doc_path="docs/domains/bookings.md",
            tracked_paths=["src/lib/bookings/**"],
        )

        def mock_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_same", "")
            self.fail(f"Unexpected command executed when SHA is unchanged: {cmd}")

        mock_run_command.side_effect = mock_cmd

        results = check_drift(self.repo)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "CLEAN")
        self.assertFalse(results[0].llm_invoked)
        self.assertEqual(results[0].summary, "CLEAN (no code changes)")

    @patch("tools.drift.scanner.run_command")
    def test_triggered_drift_audit_with_findings(self, mock_run_command):
        """
        When git diff includes files matching tracked_paths, agy is invoked.
        If findings exist, mark DRIFT_DETECTED and write latest-drift-report.md.
        """
        state_store = DriftStateStore.load_from_repo(self.repo)
        state_store.update_record(
            domain="bookings",
            sha="sha_old",
            doc_path="docs/domains/bookings.md",
            tracked_paths=["src/lib/bookings/**", "src/actions/bookings.ts"],
        )

        llm_called = []

        def mock_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_new", "")
            if cmd == ["git", "diff", "--name-only", "sha_old..HEAD"]:
                return (0, "src/lib/bookings/service.ts\nsrc/other/test.ts", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                llm_called.append(cmd)
                return (
                    0,
                    "- [BROKEN_INVARIANT] Direct DB mutation bypasses repository in src/lib/bookings/service.ts",
                    "",
                )
            return (1, "", "Unknown")

        mock_run_command.side_effect = mock_cmd

        results = check_drift(self.repo)
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.domain, "bookings")
        self.assertEqual(res.status, "DRIFT_DETECTED")
        self.assertTrue(res.llm_invoked)
        self.assertEqual(len(llm_called), 1)
        agy_cmd = llm_called[0]
        self.assertEqual(len(agy_cmd), 7)
        self.assertEqual(agy_cmd[:5], ["agy", "--mode", "plan", "--model", DRIFT_MODEL])
        self.assertEqual(agy_cmd[5], "-p")
        self.assertIn("bookings", agy_cmd[-1])
        self.assertIn("BROKEN_INVARIANT", res.findings_markdown)

        # Verify report was written
        report_file = self.repo / ".edge" / "drift" / "latest-drift-report.md"
        self.assertTrue(report_file.exists())
        report_text = report_file.read_text(encoding="utf-8")
        self.assertIn("DRIFT_DETECTED", report_text)
        self.assertIn("BROKEN_INVARIANT", report_text)

    @patch("tools.drift.scanner.run_command")
    def test_triggered_drift_audit_clean_no_drift(self, mock_run_command):
        """
        When live code changes, agy audits and reports NO_DRIFT.
        Contract marks CLEAN and advances last_checked_sha.
        """
        state_store = DriftStateStore.load_from_repo(self.repo)
        state_store.update_record(
            domain="bookings",
            sha="sha_old",
            doc_path="docs/domains/bookings.md",
            tracked_paths=["src/lib/bookings/**"],
        )

        def mock_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_new", "")
            if cmd == ["git", "diff", "--name-only", "sha_old..HEAD"]:
                return (0, "src/lib/bookings/repo.ts", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                return (0, "NO_DRIFT", "")
            return (1, "", "Unknown")

        mock_run_command.side_effect = mock_cmd

        results = check_drift(self.repo)
        self.assertEqual(len(results), 1)
        res = results[0]
        self.assertEqual(res.status, "CLEAN")
        self.assertTrue(res.llm_invoked)
        self.assertEqual(res.summary, "CLEAN (audit verified no drift)")

        # State updated
        store_after = DriftStateStore.load_from_repo(self.repo)
        self.assertEqual(store_after.get_record("bookings").last_checked_sha, "sha_new")

    def test_untracked_contract_skipped(self):
        """A contract without tracked_paths is marked UNTRACKED with 0 LLM calls."""
        untracked_file = self.repo / "docs" / "domains" / "untracked.md"
        untracked_file.write_text("# Untracked Domain\nNo frontmatter.", encoding="utf-8")

        with patch("tools.drift.scanner.run_command") as mock_run:
            mock_run.return_value = (0, "sha_123", "")
            results = check_drift(self.repo)

        untracked_res = [r for r in results if r.domain == "untracked"][0]
        self.assertEqual(untracked_res.status, "UNTRACKED")
        self.assertFalse(untracked_res.llm_invoked)


class TestSpecDiscoveryAndArchiving(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_discover_specs_filtering(self):
        # Create canonical domain doc
        (self.repo / "docs" / "domains").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "domains" / "bookings.md").write_text("domain deed", encoding="utf-8")

        # Create ephemeral slice specs
        (self.repo / ".edge" / "specs").mkdir(parents=True, exist_ok=True)
        (self.repo / ".edge" / "specs" / "slice-auth.md").write_text("spec", encoding="utf-8")

        (self.repo / "specs").mkdir(parents=True, exist_ok=True)
        (self.repo / "specs" / "task-order.md").write_text("spec", encoding="utf-8")

        # Create general docs
        (self.repo / "docs" / "guides").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "guides" / "setup.md").write_text("guide", encoding="utf-8")

        # Create excluded standard files
        (self.repo / "README.md").write_text("readme", encoding="utf-8")
        (self.repo / "docs" / "ARCHITECTURE.md").write_text("arch", encoding="utf-8")
        (self.repo / "coding_standards.md").write_text("standards", encoding="utf-8")

        # Create archived spec (must be ignored)
        (self.repo / ".edge" / "archive" / "specs").mkdir(parents=True, exist_ok=True)
        (self.repo / ".edge" / "archive" / "specs" / "old-slice.md").write_text("old", encoding="utf-8")

        report = discover_specs(self.repo)
        self.assertEqual(report.domain_contracts, ["docs/domains/bookings.md"])

        expected_candidates = {
            ".edge/specs/slice-auth.md",
            "specs/task-order.md",
            "docs/guides/setup.md",
        }
        self.assertEqual(set(report.ephemeral_candidates), expected_candidates)
        # Excluded docs must not be candidates
        self.assertNotIn("docs/ARCHITECTURE.md", report.ephemeral_candidates)
        self.assertNotIn(".edge/archive/specs/old-slice.md", report.ephemeral_candidates)

    def test_archive_ephemeral_spec(self):
        specs_dir = self.repo / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        spec_file = specs_dir / "slice-feature.md"
        spec_file.write_text("# Feature Spec", encoding="utf-8")

        dest = archive_ephemeral_spec(self.repo, spec_file)
        self.assertIsNotNone(dest)
        self.assertTrue(dest.exists())
        self.assertFalse(spec_file.exists())
        self.assertEqual(dest.name, "slice-feature.md")
        self.assertEqual(dest.parent, self.repo / ".edge" / "archive" / "specs")

        # Test collision handling: archiving another file with same name appends timestamp
        spec_file.write_text("# Second Feature Spec", encoding="utf-8")
        dest2 = archive_ephemeral_spec(self.repo, spec_file)
        self.assertIsNotNone(dest2)
        self.assertTrue(dest2.exists())
        self.assertNotEqual(dest, dest2)
        self.assertTrue(dest2.name.startswith("slice-feature_"))


class TestDomainConsolidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.drift.scanner.run_command")
    def test_consolidate_domain_with_archiving(self, mock_run_command):
        # Create an ephemeral spec
        specs_dir = self.repo / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        source_spec = specs_dir / "slice-orders.md"
        source_spec.write_text("# Slice Orders", encoding="utf-8")

        mock_generated_doc = """---
domain: orders
tracked_paths:
  - src/lib/orders/**
  - src/actions/orders.ts
---
# Orders Domain Contract

## Core Invariants
1. Order total cannot be negative.

## Domain Boundaries
- Owns: Orders, Line Items.

## Intentional Anchors & Deferred Scope
- Subscription orders deferred to Phase 2.
"""

        agy_cmds = []

        def mock_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_initial", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                agy_cmds.append(cmd)
                return (0, mock_generated_doc, "")
            return (1, "", "Unknown")

        mock_run_command.side_effect = mock_cmd

        success, target_path, msg = consolidate_domain(
            repo_path=self.repo,
            domain="orders",
            tracked_paths=["src/lib/orders/**", "src/actions/orders.ts"],
            source_specs=[source_spec],
            archive_sources=True,
        )

        self.assertTrue(success)
        self.assertEqual(len(agy_cmds), 1)
        agy_cmd = agy_cmds[0]
        self.assertEqual(len(agy_cmd), 7)
        self.assertEqual(agy_cmd[:5], ["agy", "--mode", "plan", "--model", DRIFT_MODEL])
        self.assertEqual(agy_cmd[5], "-p")
        self.assertIn("orders", agy_cmd[-1])
        self.assertTrue(target_path.exists())
        self.assertIn("orders.md", str(target_path))

        # Check source spec was archived
        self.assertFalse(source_spec.exists())
        archived_spec = self.repo / ".edge" / "archive" / "specs" / "slice-orders.md"
        self.assertTrue(archived_spec.exists())

        # Check drift state store was updated
        store = DriftStateStore.load_from_repo(self.repo)
        rec = store.get_record("orders")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.last_checked_sha, "sha_initial")


class TestDriftCli(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

        # Setup canonical domain
        domains_dir = self.repo / "docs" / "domains"
        domains_dir.mkdir(parents=True, exist_ok=True)
        (domains_dir / "bookings.md").write_text(
            """---
domain: bookings
tracked_paths:
  - src/lib/bookings/**
---
# Bookings
""",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_discover(self):
        code = run_drift(["discover", str(self.repo)])
        self.assertEqual(code, 0)

    @patch("tools.drift.cli.get_head_sha")
    def test_cli_mark_clean(self, mock_head_sha):
        mock_head_sha.return_value = "sha_marked_head"

        code = run_drift(["check", str(self.repo), "--mark-clean", "bookings"])
        self.assertEqual(code, 0)

        store = DriftStateStore.load_from_repo(self.repo)
        rec = store.get_record("bookings")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.last_checked_sha, "sha_marked_head")

    @patch("tools.drift.scanner.run_command")
    def test_cli_check_returns_exit_codes(self, mock_run_command):
        # 1. Clean check returns 0
        def mock_clean_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_clean", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                return (0, "NO_DRIFT", "")
            return (0, "", "")

        mock_run_command.side_effect = mock_clean_cmd
        code = run_drift(["check", str(self.repo)])
        self.assertEqual(code, 0)

        # 2. Drift check returns 1
        def mock_drift_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_drift", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                return (0, "- [BROKEN_INVARIANT] Schema leak", "")
            return (0, "", "")

        # Invalidate state record to trigger audit
        (self.repo / ".edge" / "drift_state.json").unlink(missing_ok=True)
        mock_run_command.side_effect = mock_drift_cmd
        code_drift = run_drift(["check", str(self.repo)])
        self.assertEqual(code_drift, 1)


if __name__ == "__main__":
    unittest.main()
