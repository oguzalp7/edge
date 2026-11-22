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



class TestCanonicalDomainAndContextParsing(unittest.TestCase):
    def test_parse_canonical_domain_doc_fields_and_bullet_invariants(self):
        import tools.drift as drift_pkg
        from tools.drift.models import CanonicalDomainDoc, parse_canonical_domain_doc

        self.assertIs(drift_pkg.CanonicalDomainDoc, CanonicalDomainDoc)
        self.assertIs(drift_pkg.parse_canonical_domain_doc, parse_canonical_domain_doc)

        content = """# Domain: quality-gates

- **Paths:** `tools/gate.py`, `tools/audit/**`
- **Owner / DRI:** @quality-team
- **Concepts:** `deterministic-gate`, `complexity-ceiling`

## Core Invariants
- **[INV-QG-MIGRATION-LOCK]** Never mutate migrations during refactor (see cross-ref [INV-BRIGADE-ATOMIC-STATE] and [PAT-OTHER-REF]).
  *Enforced by:* `tests/test_gate.py::TestGate::test_migration_lock`, `tools/gate.py`
- **[INV-QG-CC-CEILING]** Maintain CC <= 10 on clean files.
  *Enforced by:* `tests/test_crapper.py::test_cc`

## Adopted Patterns
- **[PAT-QG-DETERMINISTIC-GATE]** Pure Python gate before LLM audit (related to [INV-INLINE-IGNORED]).
  *Enforced by:* `tools/rules.py`

## Notes
Prose mentioning [INV-PROSE-IGNORED] and [PAT-PROSE-IGNORED] must not be collected.
"""
        doc = parse_canonical_domain_doc(
            content,
            doc_path="docs/quality-gates/DOMAIN.md",
            fallback_domain="fallback",
        )
        self.assertIsInstance(doc, CanonicalDomainDoc)
        self.assertEqual(doc.domain, "quality-gates")
        self.assertEqual(doc.doc_path, "docs/quality-gates/DOMAIN.md")
        self.assertEqual(doc.tracked_paths, ["tools/gate.py", "tools/audit/**"])
        self.assertEqual(doc.owner, "@quality-team")
        self.assertEqual(doc.concepts, ["deterministic-gate", "complexity-ceiling"])
        self.assertEqual(doc.invariant_ids, ["INV-QG-MIGRATION-LOCK", "INV-QG-CC-CEILING"])
        self.assertEqual(doc.pattern_ids, ["PAT-QG-DETERMINISTIC-GATE"])
        self.assertEqual(
            doc.enforced_by,
            ["tests/test_gate.py", "tools/gate.py", "tests/test_crapper.py", "tools/rules.py"],
        )

        # Fallback domain when # Domain: heading is omitted
        fallback_doc = parse_canonical_domain_doc(
            "- **Paths:** `tools/foo/**`\n",
            doc_path="docs/foo/DOMAIN.md",
            fallback_domain="foo",
        )
        self.assertEqual(fallback_doc.domain, "foo")
        self.assertEqual(fallback_doc.tracked_paths, ["tools/foo/**"])

    def test_parse_context_glossary_scoped_to_closed_concept_glossary(self):
        import tools.drift as drift_pkg
        from tools.drift.models import parse_context_glossary

        self.assertIs(drift_pkg.parse_context_glossary, parse_context_glossary)

        bullet_context = """# Edge Context

## Domain Map

| Domain | Paths | Owner |
| :--- | :--- | :--- |
| `drift` | `tools/drift/**`, `skills/edge-drift/**` | @drift-dri |
| `brigade` | `tools/brigade/cli.py` | @brigade-dri |

## Closed Concept Glossary

- `zero-token-gate`: Skip LLM audit when tracked code diff is empty (`tools/drift/scanner.py`)
- `domain-deed`: Canonical domain contract in `DOMAIN.md` (`tools/drift/models.py`)

## Other Reference
- `outside-glossary`: Must never be parsed as a closed concept (`tools/foo.py`)
"""
        domain_globs, concept_ids = parse_context_glossary(bullet_context)
        self.assertEqual(
            domain_globs,
            {
                "drift": ["tools/drift/**", "skills/edge-drift/**"],
                "brigade": ["tools/brigade/cli.py"],
            },
        )
        self.assertEqual(concept_ids, ["zero-token-gate", "domain-deed"])
        for leaked in ("drift", "brigade", "tools/drift/**", "outside-glossary"):
            self.assertNotIn(leaked, concept_ids)

        table_context = """# Edge Context

## Domain Map

| Domain | Paths |
| :--- | :--- |
| `drift` | `tools/drift/**` |

## Closed Concept Glossary

| Concept | Symbol | Meaning |
| :--- | :--- | :--- |
| `atomic-state` | `DriftStateStore.save` | Temp write and os.replace |
| `exit-code-fsm` | `BrigadeFSM` | Deterministic FSM |
"""
        table_globs, table_concepts = parse_context_glossary(table_context)
        self.assertEqual(table_globs, {"drift": ["tools/drift/**"]})
        self.assertEqual(table_concepts, ["atomic-state", "exit-code-fsm"])


class TestDualDiscoveryAndDriftCheck(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_discover_specs_dual_layout_preference_and_collision_rejection(self):
        # Canonical docs/<domain>/DOMAIN.md + legacy duplicate for bookings
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n- **Paths:** `src/bookings/**`\n",
            encoding="utf-8",
        )
        (self.repo / "docs" / "domains").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "domains" / "bookings.md").write_text(
            '---\ndomain: bookings\ntracked_paths: ["src/legacy/**"]\n---\n',
            encoding="utf-8",
        )
        # Legacy-only domain
        (self.repo / "docs" / "domains" / "orders.md").write_text(
            '---\ndomain: orders\ntracked_paths: ["src/orders/**"]\n---\n',
            encoding="utf-8",
        )
        # Collision trap: docs/domains/DOMAIN.md must be rejected as canonical domain "domains"
        (self.repo / "docs" / "domains" / "DOMAIN.md").write_text(
            "# Domain: domains\n- **Paths:** `src/**`\n",
            encoding="utf-8",
        )
        # Ephemeral candidates
        (self.repo / ".edge" / "specs").mkdir(parents=True, exist_ok=True)
        (self.repo / ".edge" / "specs" / "slice-auth.md").write_text("spec", encoding="utf-8")
        (self.repo / "docs" / "guides").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "guides" / "setup.md").write_text("guide", encoding="utf-8")

        report = discover_specs(self.repo)
        self.assertEqual(
            report.domain_contracts,
            ["docs/bookings/DOMAIN.md", "docs/domains/orders.md"],
        )
        self.assertNotIn("docs/domains/bookings.md", report.domain_contracts)
        self.assertNotIn("docs/domains/DOMAIN.md", report.domain_contracts)
        self.assertEqual(
            set(report.ephemeral_candidates),
            {".edge/specs/slice-auth.md", "docs/guides/setup.md"},
        )
        self.assertNotIn("docs/bookings/DOMAIN.md", report.ephemeral_candidates)
        self.assertNotIn("docs/domains/DOMAIN.md", report.ephemeral_candidates)

    @patch("tools.drift.scanner.run_command")
    def test_check_drift_canonical_domain_doc_zero_token_and_empty_sha_error(
        self, mock_run_command
    ):
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n- **Paths:** `src/bookings/**`\n",
            encoding="utf-8",
        )
        # Legacy duplicate with different path + collision trap
        (self.repo / "docs" / "domains").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "domains" / "bookings.md").write_text(
            '---\ndomain: bookings\ntracked_paths: ["src/other/**"]\n---\n',
            encoding="utf-8",
        )
        (self.repo / "docs" / "domains" / "DOMAIN.md").write_text(
            "# Domain: domains\n- **Paths:** `src/**`\n",
            encoding="utf-8",
        )

        store = DriftStateStore.load_from_repo(self.repo)
        store.update_record(
            domain="bookings",
            sha="sha_old",
            doc_path="docs/bookings/DOMAIN.md",
            tracked_paths=["src/bookings/**"],
        )

        def mock_disjoint(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_new", "")
            if cmd == ["git", "diff", "--name-only", "sha_old..HEAD"]:
                # Matches legacy path src/other/**, NOT canonical src/bookings/**
                return (0, "src/other/file.py", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                self.fail("Canonical DOMAIN.md preference violated: agy invoked on legacy path")
            return (1, "", "Unknown")

        mock_run_command.side_effect = mock_disjoint
        results = check_drift(self.repo)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].domain, "bookings")
        self.assertEqual(results[0].status, "CLEAN")
        self.assertFalse(results[0].llm_invoked)
        self.assertEqual(
            DriftStateStore.load_from_repo(self.repo).get_record("bookings").last_checked_sha,
            "sha_new",
        )

        # Empty HEAD SHA (e.g. git dubious ownership) must return ERROR, never CLEAN
        def mock_empty_head(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (128, "", "fatal: detected dubious ownership")
            return (1, "", "")

        mock_run_command.side_effect = mock_empty_head
        err_results = check_drift(self.repo)
        self.assertTrue(err_results)
        self.assertTrue(any(r.status == "ERROR" for r in err_results))
        self.assertFalse(any(r.status == "CLEAN" for r in err_results))
        self.assertEqual(
            DriftStateStore.load_from_repo(self.repo).get_record("bookings").last_checked_sha,
            "sha_new",
        )


class TestOntologyValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_validate_ontology_skip_gate_when_no_context_or_canonical_domains(self):
        import tools.drift as drift_pkg
        from tools.drift.models import OntologyIssue, OntologyReport
        from tools.drift.scanner import validate_ontology

        self.assertIs(drift_pkg.OntologyIssue, OntologyIssue)
        self.assertIs(drift_pkg.OntologyReport, OntologyReport)
        self.assertIs(drift_pkg.validate_ontology, validate_ontology)

        (self.repo / "docs" / "domains").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "domains" / "bookings.md").write_text(
            '---\ndomain: bookings\ntracked_paths: ["src/bookings/**"]\n---\n',
            encoding="utf-8",
        )
        (self.repo / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "bookings" / "svc.py").write_text(
            '"""\n@inputs bogus\n@concepts unknown\n"""\n',
            encoding="utf-8",
        )

        report = validate_ontology(self.repo)
        self.assertIsInstance(report, OntologyReport)
        self.assertTrue(report.skipped)
        self.assertFalse(report.has_errors)
        self.assertEqual(report.issues, [])

    @patch("tools.drift.scanner.run_command")
    def test_validate_ontology_flags_unknown_concepts_invariants_and_legacy_tags(
        self, mock_run_command
    ):
        from tools.drift.scanner import validate_ontology

        mock_run_command.side_effect = AssertionError("validate_ontology must use os.walk, not git")

        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths |
| :--- | :--- |
| `bookings` | `src/bookings/**` |

## Closed Concept Glossary
- `valid-concept`: Valid concept (`src/bookings/good.py`)
""",
            encoding="utf-8",
        )
        (self.repo / "tests").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests" / "test_bookings.py").write_text("def test_ok(): pass\n", encoding="utf-8")
        (self.repo / "tests" / "ignored_fixture.py").write_text(
            '"""\n@inputs ignored_in_tests\n"""\n',
            encoding="utf-8",
        )
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            """# Domain: bookings

- **Paths:** `src/bookings/**`
- **Owner / DRI:** @team
- **Concepts:** `valid-concept`

## Core Invariants
- **[INV-BOOK-ATOMIC]** Hold slot inside transaction.
""",
            encoding="utf-8",
        )

        (self.repo / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        # Good Python file with shebang, coding cookie, BOM, and @dataclass after code start
        (self.repo / "src" / "bookings" / "good.py").write_text(
            "\n".join([
                "#!/usr/bin/env python3",
                "# -*- coding: utf-8 -*-",
                '"""',
                "Booking service.",
                "@intent Manage booking slots",
                "@concepts valid-concept",
                "@invariants [INV-BOOK-ATOMIC]",
                '"""',
                "from dataclasses import dataclass",
                "",
                "@dataclass",
                "class Slot:",
                "    id: int",
                "",
            ]),
            encoding="utf-8-sig",
        )
        # Good JS file with 'use strict'; directive + // header comments
        (self.repo / "src" / "bookings" / "good_js.js").write_text(
            "\n".join([
                "'use strict';",
                "// @intent Clean JS helper",
                "// @concepts valid-concept",
                "export function ok() { return true; }",
                "",
            ]),
            encoding="utf-8",
        )
        # Safe Python file mirroring ship_prep.py / smoke_routes.py regex literals
        (self.repo / "src" / "bookings" / "regex_safe.py").write_text(
            "\n".join([
                '"""Safe module without ontology tags."""',
                "import re",
                "from dataclasses import dataclass",
                "",
                'INDEX_TOKEN_RE = re.compile(r"(@route|@module|@spec|Page:)")',
                'INDEX_ROUTE_RE = re.compile(r"@route\\s+([^\\s|]+)")',
                "",
                "@dataclass",
                "class Item:",
                '    email: str = "dev@inputs.example.com"',
                "",
            ]),
            encoding="utf-8",
        )
        # Clean TS file with prose email & in-body comment
        (self.repo / "src" / "bookings" / "comment_prose.ts").write_text(
            "\n".join([
                '"use client";',
                "// Clean helper; contact support@route.example.com",
                "export function helper() {",
                "  // @inputs inside function body should not be scanned",
                '  return "dev@spec.org";',
                "}",
                "",
            ]),
            encoding="utf-8",
        )
        # Bad Python file with unknown concept, unknown invariant, 7 legacy error tags + @module warning
        (self.repo / "src" / "bookings" / "bad_py.py").write_text(
            "\n".join([
                '"""',
                "@concepts valid-concept, missing-concept",
                "@invariants [INV-BOOK-ATOMIC], [INV-NONEXISTENT-1]",
                "@inputs raw_req",
                "@outputs response",
                "@glossary old_term",
                "@route /bookings",
                "@spec specs/old.md",
                "@base_commit abc123",
                "@domain_jargon foo",
                "@module bookings_mod",
                '"""',
                "",
            ]),
            encoding="utf-8",
        )
        # Bad TS file with "use client"; + JSDoc unknown concept + @module warning
        (self.repo / "src" / "bookings" / "bad_ts.ts").write_text(
            "\n".join([
                '"use client";',
                "/**",
                " * @concepts bogus-ts-concept",
                " * @module ts_mod",
                " */",
                "export const x = 1;",
                "",
            ]),
            encoding="utf-8",
        )

        report = validate_ontology(self.repo)
        self.assertFalse(report.skipped)
        self.assertTrue(report.has_errors)

        issue_files = {i.file_path.replace("\\", "/") for i in report.issues}
        for clean_file in (
            "src/bookings/good.py",
            "src/bookings/good_js.js",
            "src/bookings/regex_safe.py",
            "src/bookings/comment_prose.ts",
            "tests/ignored_fixture.py",
        ):
            self.assertNotIn(clean_file, issue_files, f"False positive on {clean_file}: {report.issues}")

        py_issues = [i for i in report.issues if i.file_path.replace("\\", "/") == "src/bookings/bad_py.py"]
        ts_issues = [i for i in report.issues if i.file_path.replace("\\", "/") == "src/bookings/bad_ts.ts"]

        self.assertTrue(any(i.code == "UNKNOWN_CONCEPT" and i.severity == "ERROR" and "missing-concept" in i.detail for i in py_issues))
        self.assertTrue(any(i.code == "UNKNOWN_INVARIANT" and i.severity == "ERROR" and "INV-NONEXISTENT-1" in i.detail for i in py_issues))
        for tag in ("@inputs", "@outputs", "@glossary", "@route", "@spec", "@base_commit", "@domain_jargon"):
            self.assertTrue(
                any(i.code == "LEGACY_TAG" and i.severity == "ERROR" and tag in i.detail for i in py_issues),
                f"Missing ERROR LEGACY_TAG for {tag}",
            )
        self.assertTrue(any(i.code == "LEGACY_TAG" and i.severity == "WARNING" and "@module" in i.detail for i in py_issues))
        self.assertTrue(any(i.code == "UNKNOWN_CONCEPT" and i.severity == "ERROR" and "bogus-ts-concept" in i.detail for i in ts_issues))
        self.assertTrue(any(i.code == "LEGACY_TAG" and i.severity == "WARNING" and "@module" in i.detail for i in ts_issues))

    def test_validate_ontology_bom_domain_unknown_concept_code_leak_and_glob_mismatch(self):
        from tools.drift.scanner import validate_ontology

        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths |
| :--- | :--- |
| `bookings` | `src/old_globs/**` |

## Closed Concept Glossary
- `known-concept`: Known concept
""",
            encoding="utf-8-sig",
        )
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        domain_file = self.repo / "docs" / "bookings" / "DOMAIN.md"
        domain_file.write_text(
            """# Domain: bookings

- **Paths:** `src/bookings/**`
- **Owner / DRI:** @team
- **Concepts:** `known-concept`, `ghost-domain-concept`

## Living Invariants
- **[INV-BOOK-1]** Rule.
  *Enforced by:* `tests/does_not_exist.py::TestMissing`
""",
            encoding="utf-8-sig",
        )

        report = validate_ontology(self.repo)
        self.assertFalse(report.skipped)
        self.assertTrue(report.has_errors)
        codes = {(i.code, i.severity) for i in report.issues}
        self.assertIn(("GLOB_MISMATCH", "WARNING"), codes)
        self.assertIn(("CODE_LEAK_IN_DOMAIN_DOC", "ERROR"), codes)
        self.assertIn(("UNKNOWN_CONCEPT", "ERROR"), codes)
        self.assertNotIn("MISSING_ENFORCER", {i.code for i in report.issues})

        # Warning-only GLOB_MISMATCH when DOMAIN.md declares differing Paths: without code leaks
        domain_file.write_text(
            """# Domain: bookings

- **Paths:** `src/bookings/**`
- **Owner / DRI:** @team
- **Concepts:** `known-concept`

## Living Invariants
- **[INV-BOOK-1]** Hold slot inside a single reservation window.
""",
            encoding="utf-8-sig",
        )
        warn_only_report = validate_ontology(self.repo)
        self.assertFalse(warn_only_report.skipped)
        self.assertFalse(warn_only_report.has_errors)
        self.assertEqual(
            {(i.code, i.severity) for i in warn_only_report.issues},
            {("GLOB_MISMATCH", "WARNING")},
        )

        # Canonical v1.1 DOMAIN.md omits Paths: -> GLOB_MISMATCH must NOT fire
        domain_file.write_text(
            """# Domain: bookings

- **Owner / DRI:** @team
- **Concepts:** `known-concept`

## Living Invariants
- **[INV-BOOK-1]** Hold slot inside a single reservation window.
""",
            encoding="utf-8-sig",
        )
        clean_v11_report = validate_ontology(self.repo)
        self.assertFalse(clean_v11_report.skipped)
        self.assertFalse(clean_v11_report.has_errors)
        self.assertEqual(clean_v11_report.issues, [])


class TestDriftCliOntologyAndCanonical(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.drift.scanner.run_command")
    def test_cli_ontology_only_exit_codes_and_zero_llm_calls(self, mock_run_command):
        mock_run_command.side_effect = AssertionError("--ontology-only must not invoke git or agy")

        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths |
| :--- | :--- |
| `bookings` | `src/bookings/**` |

## Closed Concept Glossary
- `known-concept`: Known concept
""",
            encoding="utf-8",
        )
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n- **Owner / DRI:** @team\n- **Concepts:** `known-concept`\n",
            encoding="utf-8",
        )
        (self.repo / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "bookings" / "app.py").write_text(
            '"""\n@concepts known-concept\n"""\n',
            encoding="utf-8",
        )

        code_ok = run_drift(["check", str(self.repo), "--ontology-only"])
        self.assertEqual(code_ok, 0)

        (self.repo / "src" / "bookings" / "bad.py").write_text(
            '"""\n@concepts unknown-concept\n@inputs legacy\n"""\n',
            encoding="utf-8",
        )
        code_err = run_drift(["check", str(self.repo), "--ontology-only"])
        self.assertEqual(code_err, 1)

    @patch("tools.drift.scanner.run_command")
    def test_cli_check_auto_runs_ontology_validation_and_fails_on_ontology_error(
        self, mock_run_command
    ):
        def mock_clean_git(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_clean", "")
            if cmd == ["git", "diff", "--name-only", "sha_old..HEAD"]:
                return (0, "src/unrelated/other.py", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                self.fail("agy should not run on disjoint diff")
            return (0, "", "")

        mock_run_command.side_effect = mock_clean_git
        (self.repo / "CONTEXT.md").write_text(
            "# Context\n\n## Domain Map\n| Domain | Paths |\n| :--- | :--- |\n| `bookings` | `src/bookings/**` |\n\n## Closed Concept Glossary\n- `known-concept`: Known\n",
            encoding="utf-8",
        )
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n- **Paths:** `src/bookings/**`\n",
            encoding="utf-8",
        )
        store = DriftStateStore.load_from_repo(self.repo)
        store.update_record("bookings", "sha_old", "docs/bookings/DOMAIN.md", ["src/bookings/**"])
        (self.repo / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "bookings" / "bad.py").write_text(
            '"""\n@concepts unknown-concept\n"""\n',
            encoding="utf-8",
        )

        self.assertEqual(run_drift(["check", str(self.repo)]), 1)

    @patch("tools.drift.cli.get_head_sha")
    def test_cli_mark_clean_canonical_fallback_all_and_empty_sha_error(self, mock_head_sha):
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n- **Paths:** `src/bookings/**`\n",
            encoding="utf-8",
        )
        (self.repo / "docs" / "domains").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "domains" / "bookings.md").write_text(
            '---\ndomain: bookings\ntracked_paths: ["src/legacy/**"]\n---\n',
            encoding="utf-8",
        )
        (self.repo / "docs" / "domains" / "orders.md").write_text(
            '---\ndomain: orders\ntracked_paths: ["src/orders/**"]\n---\n',
            encoding="utf-8",
        )

        mock_head_sha.return_value = "sha_head_1"
        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "bookings"]), 0)
        store = DriftStateStore.load_from_repo(self.repo)
        rec_b = store.get_record("bookings")
        self.assertIsNotNone(rec_b)
        self.assertEqual(rec_b.doc_path, "docs/bookings/DOMAIN.md")
        self.assertEqual(rec_b.last_checked_sha, "sha_head_1")
        self.assertEqual(rec_b.tracked_paths, ["src/bookings/**"])

        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "orders"]), 0)
        store = DriftStateStore.load_from_repo(self.repo)
        rec_o = store.get_record("orders")
        self.assertIsNotNone(rec_o)
        self.assertEqual(rec_o.doc_path, "docs/domains/orders.md")
        self.assertEqual(rec_o.last_checked_sha, "sha_head_1")

        # --mark-clean all updates both canonical and legacy-only contracts
        mock_head_sha.return_value = "sha_head_all"
        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "all"]), 0)
        store = DriftStateStore.load_from_repo(self.repo)
        self.assertEqual(store.get_record("bookings").last_checked_sha, "sha_head_all")
        self.assertEqual(store.get_record("orders").last_checked_sha, "sha_head_all")

        # Empty HEAD SHA must fail and not overwrite last_checked_sha
        mock_head_sha.return_value = ""
        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "bookings"]), 1)
        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "all"]), 1)
        store = DriftStateStore.load_from_repo(self.repo)
        self.assertEqual(store.get_record("bookings").last_checked_sha, "sha_head_all")


class TestDependencyInversionV11(unittest.TestCase):
    """RED contracts for Context System v1.1: CONTEXT.md Domain Map SSOT, CODE_LEAK_IN_DOMAIN_DOC, and invariant_index."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.drift.cli.get_head_sha")
    @patch("tools.drift.scanner.run_command")
    def test_context_domain_map_resolves_globs_in_check_drift_and_cli_mark_clean_without_domain_paths(
        self, mock_run_command, mock_cli_head_sha
    ):
        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths | Owner |
| :--- | :--- | :--- |
| `bookings` | `src/bookings/**` | @bookings |
| `override` | `src/new_override/**` | @override |

## Closed Concept Glossary
- `known-concept`: Known concept (`src/bookings/svc.py`)
""",
            encoding="utf-8",
        )
        # Canonical DOMAIN.md with ZERO - **Paths:** lines
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            """# Domain: bookings

- **Owner / DRI:** @bookings
- **Concepts:** `known-concept`

## Living Invariants
- **[INV-BOOK-1]** Hold slot inside reservation boundary.
""",
            encoding="utf-8",
        )
        # Canonical DOMAIN.md where CONTEXT.md must override stale DOMAIN.md Paths:
        (self.repo / "docs" / "override").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "override" / "DOMAIN.md").write_text(
            """# Domain: override

- **Paths:** `src/old_override/**`
- **Owner / DRI:** @override
- **Concepts:** `known-concept`
""",
            encoding="utf-8",
        )
        # Fallback domain absent from CONTEXT.md Domain Map -> uses DOMAIN.md Paths:
        (self.repo / "docs" / "legacy").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "legacy" / "DOMAIN.md").write_text(
            """# Domain: legacy

- **Paths:** `src/legacy/**`
- **Owner / DRI:** @legacy
- **Concepts:** `known-concept`
""",
            encoding="utf-8",
        )

        # 1. cli.py --mark-clean resolves CONTEXT.md globs first, then falls back to DOMAIN.md Paths:
        mock_cli_head_sha.return_value = "sha_v11_1"
        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "bookings"]), 0)
        self.assertEqual(run_drift(["check", str(self.repo), "--mark-clean", "all"]), 0)
        store = DriftStateStore.load_from_repo(self.repo)
        self.assertEqual(store.get_record("bookings").tracked_paths, ["src/bookings/**"])
        self.assertEqual(store.get_record("override").tracked_paths, ["src/new_override/**"])
        self.assertEqual(store.get_record("legacy").tracked_paths, ["src/legacy/**"])

        # 2. check_drift() uses CONTEXT.md globs: change in src/old_override/other.py is disjoint for override
        agy_domains = []

        def mock_cmd(cmd, cwd=None, timeout=None):
            if cmd == ["git", "rev-parse", "HEAD"]:
                return (0, "sha_v11_2", "")
            if cmd == ["git", "diff", "--name-only", "sha_v11_1..HEAD"]:
                return (0, "src/bookings/svc.py\nsrc/old_override/ignored.py", "")
            if isinstance(cmd, list) and cmd[0] == "agy":
                prompt = cmd[-1]
                for dom in ("bookings", "override", "legacy"):
                    if f"'{dom}'" in prompt:
                        agy_domains.append(dom)
                return (0, "NO_DRIFT", "")
            return (1, "", "Unknown")

        mock_run_command.side_effect = mock_cmd
        results = check_drift(self.repo)
        by_dom = {r.domain: r for r in results}
        self.assertEqual(by_dom["bookings"].status, "CLEAN")
        self.assertTrue(by_dom["bookings"].llm_invoked)
        self.assertEqual(by_dom["override"].status, "CLEAN")
        self.assertFalse(by_dom["override"].llm_invoked)
        self.assertEqual(by_dom["legacy"].status, "CLEAN")
        self.assertFalse(by_dom["legacy"].llm_invoked)
        self.assertEqual(agy_domains, ["bookings"])

    def test_validate_ontology_scopes_code_walk_via_context_domain_map_without_domain_paths(self):
        from tools.drift.scanner import validate_ontology

        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths |
| :--- | :--- |
| `bookings` | `src/bookings/**` |

## Closed Concept Glossary
- `valid-concept`: Valid concept
""",
            encoding="utf-8",
        )
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            """# Domain: bookings

- **Owner / DRI:** @team
- **Concepts:** `valid-concept`

## Living Invariants
- **[INV-BOOK-1]** Reservations cannot overlap.
""",
            encoding="utf-8",
        )
        (self.repo / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "bookings" / "bad.py").write_text(
            '"""\n@concepts bogus-concept\n"""\n',
            encoding="utf-8",
        )
        # Untracked path outside CONTEXT.md Domain Map must NOT be walked as if tracked_globs=[]
        (self.repo / "src" / "untracked").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "untracked" / "other.py").write_text(
            '"""\n@inputs legacy_untracked\n@concepts bogus-untracked\n"""\n',
            encoding="utf-8",
        )

        report = validate_ontology(self.repo)
        self.assertFalse(report.skipped)
        self.assertTrue(report.has_errors)
        issue_files = {i.file_path.replace("\\", "/") for i in report.issues}
        self.assertIn("src/bookings/bad.py", issue_files)
        self.assertNotIn("src/untracked/other.py", issue_files)
        self.assertNotIn("GLOB_MISMATCH", {i.code for i in report.issues})

    def test_code_leak_in_domain_doc_flags_leaks_and_allows_abstract_mermaid_and_concepts(self):
        from tools.drift.scanner import validate_ontology

        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths |
| :--- | :--- |
| `drift` | `src/drift/**` |

## Closed Concept Glossary
- `zero-token-drift-gate`: Deterministic diff gate
""",
            encoding="utf-8",
        )
        drift_dir = self.repo / "docs" / "drift"
        drift_dir.mkdir(parents=True, exist_ok=True)
        domain_file = drift_dir / "DOMAIN.md"

        # 1. Clean abstract DOMAIN.md with Mermaid, pseudo, pseudocode, prose traps, concepts, UPPER tokens, and constraints
        domain_file.write_text(
            """# Domain: drift

- **Owner / DRI:** @edge-drift
- **Concepts:** `zero-token-drift-gate`

## Living Invariants
- **[INV-DRIFT-ZERO-TOKEN]** Enforce invariant(s) and pattern(s) from `CONTEXT.md` (`v1.1`, e.g. business rules/policies and read/write isolation).
- **[INV-DRIFT-NO-FAKE-CLEAN]** Reject empty revisions; keep `CODER`, `RED_TEST`, and `PASS` deterministic with `CC <= 10`, `<= 60`, `Treehouse`, `--ontology-only`, and `/edge-drift`.

## Flow

```mermaid
flowchart LR
  RED_TEST --> SURGERY --> PASS
```

```pseudo
IF tracked files unchanged THEN return CLEAN
ELSE audit domain contract
```

```PSEUDOCODE
FOR EACH domain IN scope:
  CHECK invariant state
```
""",
            encoding="utf-8",
        )
        clean_report = validate_ontology(self.repo)
        self.assertFalse(clean_report.skipped)
        self.assertFalse(clean_report.has_errors, f"Unexpected leaks in clean doc: {clean_report.issues}")
        self.assertEqual(clean_report.issues, [])

        # 2. Every CODE_LEAK_IN_DOMAIN_DOC pattern must emit ERROR
        leak_cases = [
            ("python_fence", "```python\nx = 1\n```"),
            ("ts_fence", "```ts\nconst x = 1;\n```"),
            ("bare_fence", "```\nraw block\n```"),
            ("tilde_fence", "~~~\ntilde block\n~~~"),
            ("unclosed_fence", "```mermaid\ngraph TD\nA --> B"),
            ("py_ext_in_prose", "Do not inspect scanner.py directly."),
            ("json_ext_in_prose", "Config lives in hooks.json."),
            ("dot_edge_json", "Never write `.edge/brigade.json` directly."),
            ("path_in_mermaid", "```mermaid\nflowchart LR\n  A[tools/drift/scanner.py] --> B[DONE]\n```"),
            ("docs_dir_path", "Look under docs/ for details."),
            ("enforced_by_line", "  *Enforced by:* `tests/test_drift.py`"),
            ("enforced_by_bold", "**Enforced by:** domain rules"),
            ("func_call_backtick", "Runs `validate_ontology()` on changes."),
            ("snake_case_backtick", "Stores `last_checked_sha` atomically."),
            ("camel_case_backtick", "Calls `checkDrift` before merge."),
            ("pascal_case_backtick", "Uses `DriftStateStore` persistence."),
            ("dotted_member_backtick", "Uses `os.replace` for atomic writes."),
        ]

        header = (
            "# Domain: drift\n\n"
            "- **Owner / DRI:** @edge-drift\n"
            "- **Concepts:** `zero-token-drift-gate`\n\n"
            "## Living Invariants\n"
            "- **[INV-DRIFT-ZERO-TOKEN]** Base rule.\n\n"
        )
        for case_name, body_snippet in leak_cases:
            with self.subTest(case=case_name):
                domain_file.write_text(header + body_snippet + "\n", encoding="utf-8")
                rep = validate_ontology(self.repo)
                leak_errors = [
                    i
                    for i in rep.issues
                    if i.code == "CODE_LEAK_IN_DOMAIN_DOC" and i.severity == "ERROR"
                ]
                self.assertTrue(
                    leak_errors,
                    f"Expected CODE_LEAK_IN_DOMAIN_DOC ERROR for case '{case_name}', got: {rep.issues}",
                )

    def test_invariant_index_reverse_indexes_code_and_tests_without_legacy_tag_checks_on_tests(self):
        from tools.drift.scanner import validate_ontology

        (self.repo / "CONTEXT.md").write_text(
            """# Context

## Domain Map
| Domain | Paths |
| :--- | :--- |
| `bookings` | `src/bookings/**` |

## Closed Concept Glossary
- `booking-slot`: Reservation slot
""",
            encoding="utf-8",
        )
        (self.repo / "docs" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "docs" / "bookings" / "DOMAIN.md").write_text(
            """# Domain: bookings

- **Owner / DRI:** @bookings
- **Concepts:** `booking-slot`

## Living Invariants
- **[INV-BOOK-ATOMIC]** Hold slot inside single transaction.
- **[INV-BOOK-CANCEL]** Record cancellation audit reason.
""",
            encoding="utf-8",
        )
        (self.repo / "src" / "bookings").mkdir(parents=True, exist_ok=True)
        (self.repo / "src" / "bookings" / "service.py").write_text(
            '"""\n@intent Booking service\n@concepts booking-slot\n@invariants [INV-BOOK-ATOMIC]\n"""\n',
            encoding="utf-8",
        )
        (self.repo / "tests").mkdir(parents=True, exist_ok=True)
        (self.repo / "tests" / "test_bookings_contract.py").write_text(
            '"""\n@inputs ignored_legacy_in_tests\n@invariants [INV-BOOK-ATOMIC], [INV-BOOK-CANCEL]\n"""\n',
            encoding="utf-8",
        )
        (self.repo / "tests" / "test_bad_inv.py").write_text(
            '"""\n@invariants [INV-UNKNOWN-99]\n"""\n',
            encoding="utf-8",
        )

        report = validate_ontology(self.repo)
        self.assertFalse(report.skipped)
        self.assertTrue(hasattr(report, "invariant_index"), "OntologyReport must expose invariant_index")
        self.assertEqual(
            report.invariant_index.get("INV-BOOK-ATOMIC"),
            ["src/bookings/service.py", "tests/test_bookings_contract.py"],
        )
        self.assertEqual(
            report.invariant_index.get("INV-BOOK-CANCEL"),
            ["tests/test_bookings_contract.py"],
        )

        # @inputs inside tests/ must NOT trigger LEGACY_TAG; unknown @invariants in tests/ MUST trigger UNKNOWN_INVARIANT
        contract_issues = [
            i for i in report.issues if i.file_path.replace("\\", "/") == "tests/test_bookings_contract.py"
        ]
        self.assertEqual(contract_issues, [], f"Unexpected issues on test file with @inputs: {contract_issues}")

        bad_test_issues = [
            i for i in report.issues if i.file_path.replace("\\", "/") == "tests/test_bad_inv.py"
        ]
        self.assertTrue(
            any(i.code == "UNKNOWN_INVARIANT" and i.severity == "ERROR" and "INV-UNKNOWN-99" in i.detail for i in bad_test_issues),
            f"Expected UNKNOWN_INVARIANT ERROR on tests/test_bad_inv.py, got: {bad_test_issues}",
        )

if __name__ == "__main__":
    unittest.main()
