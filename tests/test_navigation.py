#!/usr/bin/env python3
"""
RED Unit & Contract Tests for Slice 2:
- Isolated Navigation Resolver (tools/brigade/navigation.py)
- Minimal Station Wiring (tools/brigade/stations.py)
- Agent Rubric Navigation Pointers (agents/researcher.md, agents/spec-writer.md)
"""

import os
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import List

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.brigade.models import Ticket, ReviewFinding
from tools.brigade.stations import StationRegistry


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo: Path) -> None:
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Edge Test")


class TestNavigationContextResolver(unittest.TestCase):
    """Contracts for tools.brigade.navigation.build_navigation_context."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_nav_"))
        self.repo_dir = self.temp_dir / "repo"
        self.repo_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_null_nonexistent_and_empty_repo_return_empty(self):
        from tools.brigade.navigation import build_navigation_context

        self.assertEqual(build_navigation_context(None), "")
        self.assertEqual(build_navigation_context(self.temp_dir / "nonexistent"), "")
        self.assertEqual(build_navigation_context(self.repo_dir), "")

    def test_index_glossary_deed_slicing_and_15_line_priority_truncation(self):
        from tools.brigade.navigation import build_navigation_context

        # Create real targets referenced in nav docs
        (self.repo_dir / "src" / "lib" / "bookings").mkdir(parents=True)
        (self.repo_dir / "src" / "lib" / "bookings" / "repo.ts").write_text("export const x = 1;\n", encoding="utf-8")

        # 1. specs/INDEX.md with 8 matching rows + unrelated row
        (self.repo_dir / "specs").mkdir(parents=True)
        index_rows = [
            "| Domain | File | Notes |",
            "| :--- | :--- | :--- |",
        ] + [
            f"| bookings | [repo.ts](../src/lib/bookings/repo.ts) | Row {i} |"
            for i in range(8)
        ] + [
            "| billing | [invoice.ts](../src/lib/billing/invoice.ts) | Unrelated |"
        ]
        (self.repo_dir / "specs" / "INDEX.md").write_text("\n".join(index_rows) + "\n", encoding="utf-8")

        # 2. CONTEXT.md with 6 matching glossary rows
        glossary_rows = [f"- **bookings term {i}**: domain rule {i}" for i in range(6)] + [
            "- **billing term**: unrelated"
        ]
        (self.repo_dir / "CONTEXT.md").write_text("\n".join(glossary_rows) + "\n", encoding="utf-8")

        # 3. docs/domains/bookings.md with 5 invariant lines
        (self.repo_dir / "docs" / "domains").mkdir(parents=True)
        (self.repo_dir / "docs" / "domains" / "bookings.md").write_text(
            "---\n"
            "domain: bookings\n"
            "tracked_paths:\n"
            "  - src/lib/bookings/**\n"
            "---\n\n"
            "# Bookings Domain\n"
            "- Invariant 1: Hold slot inside transaction\n"
            "- Invariant 2: Reject double booking\n"
            "- Invariant 3: Audit status change\n"
            "- Invariant 4: Exceeds 3-line deed cap\n"
            "- Invariant 5: Exceeds 3-line deed cap\n",
            encoding="utf-8",
        )

        # 4. Real git co-changes (6 neighbors -> top 5)
        _init_git_repo(self.repo_dir)
        for i in range(6):
            (self.repo_dir / "src" / "lib" / "bookings" / f"helper_{i}.ts").write_text("export {};\n", encoding="utf-8")
        for c in range(2):
            (self.repo_dir / "src" / "lib" / "bookings" / "repo.ts").write_text(f"export const x = {c};\n", encoding="utf-8")
            for i in range(6):
                (self.repo_dir / "src" / "lib" / "bookings" / f"helper_{i}.ts").write_text(f"export const h = {c};\n", encoding="utf-8")
            _run_git(self.repo_dir, "add", ".")
            _run_git(self.repo_dir, "commit", "-m", f"commit {c}")

        out = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/bookings/repo.ts"],
            domain="bookings",
        )
        non_empty_lines = [ln for ln in out.splitlines() if ln.strip()]
        self.assertTrue(non_empty_lines, "Expected non-empty navigation output")
        self.assertEqual(non_empty_lines[0], "### 🧭 NAVIGATION & DOMAIN CONTEXT")
        self.assertLessEqual(len(non_empty_lines), 15, f"Exceeded 15-line cap:\n{out}")

        # Priority order: Index (<=5) and Deeds (<=3) must not be starved by Glossary
        self.assertIn("Row 0", out)
        self.assertIn("Row 4", out)
        self.assertNotIn("Row 5", out)
        self.assertNotIn("Unrelated", out)
        self.assertIn("Invariant 1", out)
        self.assertIn("Invariant 3", out)
        self.assertNotIn("Invariant 4", out)
        self.assertIn("(co-changed 2x)", out)

        # Without co-changes and with small index/deed, Glossary (<= 4 rows) renders
        shutil.rmtree(self.repo_dir / ".git", ignore_errors=True)
        (self.repo_dir / "specs" / "INDEX.md").write_text(
            "| bookings | [repo.ts](../src/lib/bookings/repo.ts) | SingleRow |\n",
            encoding="utf-8",
        )
        out_with_glossary = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/bookings/repo.ts"],
            domain="bookings",
        )
        self.assertIn("bookings term 0", out_with_glossary)
        self.assertIn("bookings term 3", out_with_glossary)
        self.assertNotIn("bookings term 4", out_with_glossary)
        self.assertNotIn("billing term", out_with_glossary)

    def test_existence_pointer_fallback_when_zero_row_hits_even_with_cochanges(self):
        from tools.brigade.navigation import build_navigation_context

        (self.repo_dir / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
        (self.repo_dir / "specs").mkdir(parents=True)
        (self.repo_dir / "specs" / "INDEX.md").write_text("- unrelated: alpha\n", encoding="utf-8")
        (self.repo_dir / "CONTEXT.md").write_text("- unrelated: beta\n", encoding="utf-8")
        (self.repo_dir / "docs" / "domains").mkdir(parents=True)
        (self.repo_dir / "docs" / "domains" / "alpha.md").write_text(
            "---\ndomain: alpha\ntracked_paths: [\"src/alpha/**\"]\n---\n- Alpha only\n",
            encoding="utf-8",
        )

        # Initialize git repo with co-changed neighbor for src/target.ts
        (self.repo_dir / "src").mkdir(parents=True)
        _init_git_repo(self.repo_dir)
        (self.repo_dir / "src" / "target.ts").write_text("export const a = 1;\n", encoding="utf-8")
        (self.repo_dir / "src" / "neighbor.ts").write_text("export const b = 1;\n", encoding="utf-8")
        _run_git(self.repo_dir, "add", "src/target.ts", "src/neighbor.ts")
        _run_git(self.repo_dir, "commit", "-m", "cochange pair")

        out = build_navigation_context(
            self.repo_dir,
            target_paths=["src/target.ts"],
            domain="zeta",
        )
        self.assertIn("### 🧭 NAVIGATION & DOMAIN CONTEXT", out)
        self.assertIn("Navigation docs available:", out)
        self.assertIn("AGENTS.md", out)
        self.assertIn("specs/INDEX.md", out)
        self.assertIn("CONTEXT.md", out)
        self.assertIn("docs/domains/", out)
        self.assertIn("src/neighbor.ts (co-changed 1x)", out)
        non_empty = [ln for ln in out.splitlines() if ln.strip()]
        self.assertLessEqual(len(non_empty), 15)

    def test_stale_link_checker_balanced_parens_backticks_fragments_and_absolute_paths(self):
        from tools.brigade.navigation import build_navigation_context

        # Valid targets on disk
        dash_page = self.repo_dir / "src" / "app" / "(dashboard)" / "dashboard" / "page.tsx"
        dash_page.parent.mkdir(parents=True)
        dash_page.write_text("export default function Page() { return null; }\n", encoding="utf-8")

        repo_ts = self.repo_dir / "src" / "lib" / "bookings" / "repo.ts"
        repo_ts.parent.mkdir(parents=True)
        repo_ts.write_text("export const repo = true;\n", encoding="utf-8")

        (self.repo_dir / "specs").mkdir(parents=True)
        (self.repo_dir / "specs" / "INDEX.md").write_text(
            "\n".join([
                '- Valid route group: [Dash](../src/app/(dashboard)/dashboard/page.tsx#L12 "Dash")',
                "- Valid external & anchor: [Site](https://example.com/x) [Mail](mailto:a@b.com) [Top](#top)",
                "- Paired code span ignored: `[Ghost](missing/file.ts)` [Repo](../src/lib/bookings/repo.ts)",
                "- Missing relative: [Missing](../src/lib/bookings/nope.ts)",
                "- Escaping root: [Escape](../../../etc/passwd) bookings",
                "- Root posix absolute: [PosixRoot](/etc/passwd) bookings",
                "- Drive letter path: [WinDrive](C:/Users/dev/bookings.ts)",
                "- Unclosed backtick graceful: `trailing code [Repo](../src/lib/bookings/repo.ts)",
            ]) + "\n",
            encoding="utf-8",
        )

        # Deed link resolves relative to docs/domains/
        (self.repo_dir / "docs" / "domains").mkdir(parents=True)
        (self.repo_dir / "docs" / "domains" / "bookings.md").write_text(
            "---\ndomain: bookings\ntracked_paths: [\"src/lib/bookings/**\"]\n---\n"
            "- Valid from deed dir: [Repo](../../src/lib/bookings/repo.ts)\n"
            "- Wrong relative from deed dir: [Wrong](src/lib/bookings/repo.ts)\n",
            encoding="utf-8",
        )

        out = build_navigation_context(
            self.repo_dir,
            target_paths=["src/app/(dashboard)/dashboard/page.tsx", "src/lib/bookings/repo.ts"],
            domain="bookings",
        )
        lines = out.splitlines()

        dash_line = next((ln for ln in lines if "Valid route group" in ln), "")
        self.assertTrue(dash_line, f"Missing route group line in:\n{out}")
        self.assertNotIn("[STALE]", dash_line)

        ext_line = next((ln for ln in lines if "Valid external" in ln), "")
        if ext_line:
            self.assertNotIn("[STALE]", ext_line)

        code_line = next((ln for ln in lines if "Paired code span ignored" in ln), "")
        self.assertTrue(code_line)
        self.assertNotIn("[STALE]", code_line)

        missing_line = next((ln for ln in lines if "Missing relative" in ln), "")
        self.assertIn("[STALE]", missing_line)

        escape_line = next((ln for ln in lines if "Escaping root" in ln), "")
        self.assertIn("[STALE]", escape_line)

        posix_line = next((ln for ln in lines if "Root posix absolute" in ln), "")
        self.assertIn("[STALE]", posix_line)

        win_line = next((ln for ln in lines if "Drive letter path" in ln), "")
        self.assertIn("[STALE]", win_line)

        # Check deed directory resolution
        valid_deed = next((ln for ln in lines if "Valid from deed dir" in ln), "")
        self.assertTrue(valid_deed)
        self.assertNotIn("[STALE]", valid_deed)

        wrong_deed = next((ln for ln in lines if "Wrong relative from deed dir" in ln), "")
        self.assertIn("[STALE]", wrong_deed)

    def test_git_cochange_normalization_top5_and_exclusions(self):
        from tools.brigade.navigation import build_navigation_context

        _init_git_repo(self.repo_dir)
        (self.repo_dir / "src").mkdir(parents=True)
        (self.repo_dir / ".edge").mkdir(parents=True)
        (self.repo_dir / "node_modules" / "pkg").mkdir(parents=True)

        anchor = self.repo_dir / "src" / "anchor.ts"
        top_neighbors = ["src/a.ts", "src/b.ts", "src/c.ts", "src/d.ts", "src/e.ts", "src/f.ts"]
        excluded_files = [
            ".edge/brigade.json",
            "node_modules/pkg/index.js",
            "package-lock.json",
            "uv.lock",
            "yarn.lock",
            "pnpm-lock.yaml",
            "Cargo.lock",
            "poetry.lock",
        ]

        # Commit 1: anchor + all 6 neighbors + all excluded files
        anchor.write_text("v1\n", encoding="utf-8")
        for rel in top_neighbors + excluded_files:
            p = self.repo_dir / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("v1\n", encoding="utf-8")
        _run_git(self.repo_dir, "add", "-f", ".")
        _run_git(self.repo_dir, "commit", "-m", "c1")

        # Commit 2 & 3: anchor + src/a.ts (3x total), src/b.ts (2x total)
        anchor.write_text("v2\n", encoding="utf-8")
        (self.repo_dir / "src" / "a.ts").write_text("v2\n", encoding="utf-8")
        (self.repo_dir / "src" / "b.ts").write_text("v2\n", encoding="utf-8")
        _run_git(self.repo_dir, "add", ".")
        _run_git(self.repo_dir, "commit", "-m", "c2")

        anchor.write_text("v3\n", encoding="utf-8")
        (self.repo_dir / "src" / "a.ts").write_text("v3\n", encoding="utf-8")
        _run_git(self.repo_dir, "add", ".")
        _run_git(self.repo_dir, "commit", "-m", "c3")

        # Pass absolute path with backslashes / ./ prefix to verify normalization
        out = build_navigation_context(
            self.repo_dir,
            target_paths=[f"./src\\anchor.ts", str(anchor)],
        )
        cochange_lines = [ln for ln in out.splitlines() if "(co-changed " in ln]
        self.assertEqual(len(cochange_lines), 5, f"Expected top 5 co-changes, got:\n{out}")
        self.assertIn("src/a.ts (co-changed 3x)", cochange_lines[0])
        self.assertIn("src/b.ts (co-changed 2x)", cochange_lines[1])
        self.assertNotIn("src/anchor.ts (co-changed", out)
        for ex in excluded_files:
            self.assertNotIn(ex, out)


class TestStationNavigationWiringAndRubrics(unittest.TestCase):
    """Contracts for StationRegistry._with_navigation_context and agent rubrics."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_station_nav_"))
        self.repo_dir = self.temp_dir / "repo"
        self.repo_dir.mkdir(parents=True)
        (self.repo_dir / "src" / "actions").mkdir(parents=True)
        (self.repo_dir / "src" / "actions" / "bookings.ts").write_text("export async function book() {}\n", encoding="utf-8")
        (self.repo_dir / "specs").mkdir(parents=True)
        (self.repo_dir / "specs" / "INDEX.md").write_text(
            "| bookings | [bookings.ts](../src/actions/bookings.ts) | Booking actions |\n",
            encoding="utf-8",
        )
        (self.repo_dir / "docs" / "domains").mkdir(parents=True)
        (self.repo_dir / "docs" / "domains" / "bookings.md").write_text(
            "---\ndomain: bookings\ntracked_paths: [\"src/actions/bookings.ts\"]\n---\n"
            "- Use transaction wrapper for bookings\n",
            encoding="utf-8",
        )
        self.ticket = Ticket(
            ticket_id="TICK-NAV-1",
            track="feature",
            domain="bookings",
            rule_id="FEAT",
            severity="INFO",
            target_file="src/actions/bookings.ts",
            line_number=1,
            fingerprint="fp-nav",
            description="Add booking validation",
            suggested_fix="Add validation",
            branch_name="feat/bookings",
            test_seam_command="pytest",
            expected_files=["src/actions/bookings.ts"],
        )
        self.finding = ReviewFinding(
            axis="spec",
            severity="WARNING",
            file_path="src/actions/bookings.ts",
            rule="bookings.md",
            description="Missing check",
            suggested_fix="Add check",
            line_number=1,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_all_8_station_builders_inject_navigation_before_trailing_rubric_preserving_spec_dashes(self):
        body_with_dashes = "Section Alpha\n---\n\nSection Beta"
        prompts = {
            "researcher": StationRegistry.build_researcher_prompt(self.ticket, body_with_dashes, repo_path=self.repo_dir),
            "spec_writer": StationRegistry.build_spec_writer_prompt(self.ticket, body_with_dashes, repo_path=self.repo_dir),
            "seam_architect": StationRegistry.build_seam_architect_prompt(self.ticket, body_with_dashes, repo_path=self.repo_dir),
            "coder": StationRegistry.build_coder_prompt(self.ticket, "pytest", repo_path=self.repo_dir),
            "surgeon": StationRegistry.build_surgeon_prompt(self.ticket, "development", repo_path=self.repo_dir),
            "examiner": StationRegistry.build_examiner_prompt(self.ticket, "development", repo_path=self.repo_dir),
            "polish": StationRegistry.build_polish_prompt(self.ticket, [self.finding], repo_path=self.repo_dir),
            "coder_polish": StationRegistry.build_coder_polish_prompt(self.ticket, [self.finding], repo_path=self.repo_dir),
        }

        for name, prompt in prompts.items():
            self.assertIn("### 🧭 NAVIGATION & DOMAIN CONTEXT", prompt, f"{name} missing navigation header")
            self.assertIn("Use transaction wrapper for bookings", prompt, f"{name} missing domain deed line")
            nav_pos = prompt.index("### 🧭 NAVIGATION & DOMAIN CONTEXT")
            rubric_pos = prompt.index("\n---\n\n# ")
            self.assertLess(nav_pos, rubric_pos, f"{name} injected navigation after rubric instead of before")

        for name in ("researcher", "spec_writer", "seam_architect"):
            p = prompts[name]
            self.assertIn(body_with_dashes, p, f"{name} internal '---' in spec/story was split or corrupted")
            self.assertLess(p.index(body_with_dashes), p.index("### 🧭 NAVIGATION & DOMAIN CONTEXT"))

        # build_qa_prompt remains excluded
        qa_prompt = StationRegistry.build_qa_prompt("checkout flow", repo_path=self.repo_dir, ticket=self.ticket)
        self.assertNotIn("### 🧭 NAVIGATION & DOMAIN CONTEXT", qa_prompt)

        # repo_path=None and empty repo leave prompts untouched
        empty_dir = self.temp_dir / "empty_repo"
        empty_dir.mkdir()
        self.assertNotIn("### 🧭 NAVIGATION & DOMAIN CONTEXT", StationRegistry.build_coder_prompt(self.ticket, "pytest", repo_path=None))
        self.assertNotIn("### 🧭 NAVIGATION & DOMAIN CONTEXT", StationRegistry.build_coder_prompt(self.ticket, "pytest", repo_path=empty_dir))

    def test_researcher_and_spec_writer_rubrics_reference_navigation_docs_within_budget(self):
        for fname in ("researcher.md", "spec-writer.md"):
            fpath = root_dir / "agents" / fname
            self.assertTrue(fpath.is_file(), f"Missing {fpath}")
            text = fpath.read_text(encoding="utf-8")
            lines = text.splitlines()
            self.assertLessEqual(len(lines), 60, f"{fname} exceeded 60-line budget ({len(lines)} lines)")
            self.assertIn("specs/INDEX.md", text, f"{fname} must reference specs/INDEX.md")
            self.assertIn("CONTEXT.md", text, f"{fname} must reference CONTEXT.md")
            self.assertIn("AGENTS.md", text, f"{fname} must reference AGENTS.md")
            self.assertIn("docs/domains/", text, f"{fname} must reference docs/domains/")

    def test_resolve_migration_paths_from_drizzle_config_agents_md_and_env_md(self):
        import tools.brigade.navigation as nav_mod

        self.assertTrue(
            hasattr(nav_mod, "resolve_migration_paths"),
            "tools.brigade.navigation must export resolve_migration_paths(repo_path)",
        )
        resolve_migration_paths = nav_mod.resolve_migration_paths

        # 1. Default when unconfigured or None
        unconfigured = self.temp_dir / "unconfigured_repo"
        unconfigured.mkdir()
        self.assertEqual(resolve_migration_paths(None), ("src/db/schema/*", "drizzle/*"))
        self.assertEqual(resolve_migration_paths(unconfigured), ("src/db/schema/*", "drizzle/*"))

        # 2. Resolved via drizzle.config.ts (out: "./src/db/migrations")
        repo_drizzle = self.temp_dir / "repo_drizzle"
        repo_drizzle.mkdir()
        (repo_drizzle / "drizzle.config.ts").write_text(
            'export default {\n  schema: "./src/db/schema",\n  out: "./src/db/migrations",\n};\n',
            encoding="utf-8",
        )
        self.assertEqual(
            resolve_migration_paths(repo_drizzle),
            ("src/db/schema/*", "src/db/migrations/*"),
        )

        # 3. Resolved via AGENTS.md (## 🌍 Repo Environment & Verification Facts)
        repo_agents = self.temp_dir / "repo_agents"
        repo_agents.mkdir()
        (repo_agents / "AGENTS.md").write_text(
            "# Project Agents\n\n"
            "## 🌍 Repo Environment & Verification Facts\n"
            "- Migrations live in `src/db/migrations/*` (never `drizzle/*`).\n"
            "- Unit tests: `npm run test:unit`.\n",
            encoding="utf-8",
        )
        self.assertEqual(
            resolve_migration_paths(repo_agents),
            ("src/db/schema/*", "src/db/migrations/*"),
        )

        # 4. Resolved via .edge/env.md
        repo_env = self.temp_dir / "repo_env"
        (repo_env / ".edge").mkdir(parents=True)
        (repo_env / ".edge" / "env.md").write_text(
            "- Schema: `src/db/schema/*`\n- Migrations: `src/db/migrations/*`\n",
            encoding="utf-8",
        )
        self.assertEqual(
            resolve_migration_paths(repo_env),
            ("src/db/schema/*", "src/db/migrations/*"),
        )

    def test_surgeon_and_examiner_prompts_dynamically_inject_resolved_migration_path(self):
        (self.repo_dir / "drizzle.config.ts").write_text(
            'export default { schema: "./src/db/schema", out: "./src/db/migrations" };\n',
            encoding="utf-8",
        )
        core_ticket = Ticket(
            ticket_id="TICK-MIG-1",
            track="core",
            domain="bookings",
            rule_id="RULE-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/bookings.ts",
            line_number=10,
            fingerprint="fp-mig",
            description="Extract DB queries",
            suggested_fix="Move to repository",
            branch_name="refactor/bookings",
            test_seam_command="npm run test:unit",
        )

        surgeon_prompt = StationRegistry.build_surgeon_prompt(
            core_ticket, "development", repo_path=self.repo_dir
        )
        examiner_prompt = StationRegistry.build_examiner_prompt(
            core_ticket, "development", repo_path=self.repo_dir
        )

        self.assertIn("src/db/migrations/*", surgeon_prompt)
        self.assertNotIn("or `drizzle/` migrations", surgeon_prompt)
        self.assertIn("src/db/migrations/*", examiner_prompt)
        self.assertNotIn("or `drizzle/*`", examiner_prompt)

    def test_build_navigation_context_extracts_repo_env_facts_into_station_prompts_within_15_line_cap(self):
        from tools.brigade.navigation import build_navigation_context

        # 1. Extract from AGENTS.md under '## 🌍 Repo Environment & Verification Facts'
        (self.repo_dir / "AGENTS.md").write_text(
            "# Agents Constitution\n\n"
            "## 🌍 Repo Environment & Verification Facts\n"
            "- Migrations path: `src/db/migrations/*` (do not create `drizzle/`).\n"
            "- Dual-theme invariant: pair `bg-white` with `dark:bg-zinc-900`.\n"
            "- Scoped unit tests: `npx vitest run <path>`.\n\n"
            "## Other Section\n"
            "- Unrelated bullet that should not be extracted as env fact.\n",
            encoding="utf-8",
        )

        nav_out = build_navigation_context(
            self.repo_dir,
            target_paths=["src/actions/bookings.ts"],
            domain="bookings",
        )
        non_empty = [ln for ln in nav_out.splitlines() if ln.strip()]
        self.assertLessEqual(len(non_empty), 15, f"Exceeded 15-line cap:\n{nav_out}")
        self.assertIn("src/db/migrations/*", nav_out)
        self.assertIn("dark:bg-zinc-900", nav_out)
        self.assertNotIn("Unrelated bullet that should not be extracted", nav_out)

        # Verify injection into station prompt via StationRegistry._with_navigation_context
        coder_prompt = StationRegistry.build_coder_prompt(
            self.ticket, "npx vitest run", repo_path=self.repo_dir
        )
        self.assertIn("### 🧭 NAVIGATION & DOMAIN CONTEXT", coder_prompt)
        self.assertIn("src/db/migrations/*", coder_prompt)
        self.assertIn("dark:bg-zinc-900", coder_prompt)

        # 2. Extract from .edge/env.md when present
        env_repo = self.temp_dir / "env_only_repo"
        (env_repo / ".edge").mkdir(parents=True)
        (env_repo / ".edge" / "env.md").write_text(
            "- Env fact 1: Drizzle migrations at `src/db/migrations/*`\n"
            "- Env fact 2: App port 3005\n",
            encoding="utf-8",
        )
        env_nav = build_navigation_context(env_repo, target_paths=["src/index.ts"], domain="core")
        env_lines = [ln for ln in env_nav.splitlines() if ln.strip()]
        self.assertLessEqual(len(env_lines), 15)
        self.assertIn("Env fact 1: Drizzle migrations at `src/db/migrations/*`", env_nav)
        self.assertIn("Env fact 2: App port 3005", env_nav)



class TestCanonicalDomainAndScopedGlossaryNavigation(unittest.TestCase):
    """Contracts for canonical docs/<domain>/DOMAIN.md and scoped CONTEXT.md glossary."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_nav_canon_"))
        self.repo_dir = self.temp_dir / "repo"
        self.repo_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_canonical_domain_md_discovered_alongside_legacy_and_relative_links_checked(self):
        from tools.brigade.navigation import build_navigation_context

        (self.repo_dir / "src" / "lib" / "bookings").mkdir(parents=True)
        (self.repo_dir / "src" / "lib" / "bookings" / "repo.ts").write_text(
            "export const repo = true;\n", encoding="utf-8"
        )
        (self.repo_dir / "src" / "lib" / "orders").mkdir(parents=True)
        (self.repo_dir / "src" / "lib" / "orders" / "svc.ts").write_text(
            "export const svc = true;\n", encoding="utf-8"
        )

        # Canonical docs/<domain>/DOMAIN.md
        (self.repo_dir / "docs" / "bookings").mkdir(parents=True)
        (self.repo_dir / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n\n"
            "- **Paths:** `src/lib/bookings/**`\n"
            "- **Owner / DRI:** @bookings\n"
            "- **Concepts:** `booking-slot`\n\n"
            "## Core Invariants\n"
            "- **[INV-BOOK-SLOT]** Hold slot inside transaction ([Repo](../../src/lib/bookings/repo.ts))\n"
            "- Bad relative link ([Wrong](src/lib/bookings/repo.ts))\n",
            encoding="utf-8",
        )

        # Legacy docs/domains/orders.md + docs/domains/DOMAIN.md collision trap
        (self.repo_dir / "docs" / "domains").mkdir(parents=True)
        (self.repo_dir / "docs" / "domains" / "orders.md").write_text(
            '---\ndomain: orders\ntracked_paths: ["src/lib/orders/**"]\n---\n'
            "- Orders legacy invariant\n",
            encoding="utf-8",
        )
        (self.repo_dir / "docs" / "domains" / "DOMAIN.md").write_text(
            "# Domain: domains\n- **Paths:** `src/lib/bookings/**`\n- COLLISION_DOMAIN_LEAK\n",
            encoding="utf-8",
        )

        out_bookings = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/bookings/repo.ts"],
            domain="bookings",
        )
        self.assertIn("INV-BOOK-SLOT", out_bookings)
        self.assertNotIn("COLLISION_DOMAIN_LEAK", out_bookings)
        valid_line = next((ln for ln in out_bookings.splitlines() if "INV-BOOK-SLOT" in ln), "")
        self.assertTrue(valid_line)
        self.assertNotIn("[STALE]", valid_line)
        wrong_line = next((ln for ln in out_bookings.splitlines() if "Bad relative link" in ln), "")
        self.assertIn("[STALE]", wrong_line)

        out_orders = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/orders/svc.ts"],
            domain="orders",
        )
        self.assertIn("Orders legacy invariant", out_orders)

        # Existence-pointer fallback when only canonical docs/<domain>/DOMAIN.md exists
        canon_only = self.temp_dir / "canon_only"
        (canon_only / "docs" / "bookings").mkdir(parents=True)
        (canon_only / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n- **Paths:** `src/bookings/**`\n- **[INV-B-1]** Hold slot\n",
            encoding="utf-8",
        )
        out_fallback = build_navigation_context(
            canon_only,
            target_paths=["src/unrelated.ts"],
            domain="unknown",
        )
        self.assertIn("Navigation docs available:", out_fallback)
        self.assertIn("DOMAIN.md", out_fallback)

    def test_context_md_glossary_scoped_without_domain_map_leak(self):
        from tools.brigade.navigation import build_navigation_context

        (self.repo_dir / "src" / "lib" / "bookings").mkdir(parents=True)
        (self.repo_dir / "src" / "lib" / "bookings" / "slot.ts").write_text(
            "export const slot = 1;\n", encoding="utf-8"
        )
        (self.repo_dir / "CONTEXT.md").write_text(
            "# Project Context\n\n"
            "## Domain Map\n\n"
            "| Domain | Paths | Owner |\n"
            "| :--- | :--- | :--- |\n"
            "| `bookings` | `src/lib/bookings/**` | DOMAIN_MAP_LEAK_SENTINEL |\n"
            "| `billing` | `src/lib/billing/**` | BILLING_MAP_SENTINEL |\n\n"
            "## Closed Concept Glossary\n\n"
            "- `booking-slot`: Canonical bookings reservation slot (`src/lib/bookings/slot.ts`)\n"
            "- `billing-invoice`: Canonical billing invoice (`src/lib/billing/invoice.ts`)\n",
            encoding="utf-8",
        )

        out = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/bookings/slot.ts"],
            domain="bookings",
        )
        self.assertIn("booking-slot", out)
        self.assertNotIn("DOMAIN_MAP_LEAK_SENTINEL", out)
        self.assertNotIn("BILLING_MAP_SENTINEL", out)
        self.assertNotIn("billing-invoice", out)

    def test_canonical_domain_globs_resolved_from_context_md_when_domain_md_omits_paths(self):
        from tools.brigade.navigation import build_navigation_context

        (self.repo_dir / "src" / "lib" / "bookings").mkdir(parents=True)
        (self.repo_dir / "src" / "lib" / "bookings" / "handler.ts").write_text(
            "export const handle = true;\n", encoding="utf-8"
        )
        (self.repo_dir / "src" / "lib" / "orders").mkdir(parents=True)
        (self.repo_dir / "src" / "lib" / "orders" / "order.ts").write_text(
            "export const order = true;\n", encoding="utf-8"
        )

        # CONTEXT.md defines bookings globs; orders is absent so falls back to orders/DOMAIN.md Paths:
        (self.repo_dir / "CONTEXT.md").write_text(
            "# Project Context\n\n"
            "## Domain Map\n"
            "| Domain | Paths | Owner |\n"
            "| :--- | :--- | :--- |\n"
            "| `bookings` | `src/lib/bookings/**` | @bookings |\n\n"
            "## Closed Concept Glossary\n"
            "- `booking-slot`: Reservation slot (`src/lib/bookings/handler.ts`)\n",
            encoding="utf-8",
        )
        (self.repo_dir / "docs" / "bookings").mkdir(parents=True)
        (self.repo_dir / "docs" / "bookings" / "DOMAIN.md").write_text(
            "# Domain: bookings\n\n"
            "- **Owner / DRI:** @bookings\n"
            "- **Concepts:** `booking-slot`\n\n"
            "## Living Invariants\n"
            "- **[INV-BOOK-CTX]** Hold booking slot across retries.\n",
            encoding="utf-8",
        )
        (self.repo_dir / "docs" / "orders").mkdir(parents=True)
        (self.repo_dir / "docs" / "orders" / "DOMAIN.md").write_text(
            "# Domain: orders\n\n"
            "- **Paths:** `src/lib/orders/**`\n"
            "- **Owner / DRI:** @orders\n\n"
            "## Living Invariants\n"
            "- **[INV-ORD-FALLBACK]** Validate order currency.\n",
            encoding="utf-8",
        )

        # Passing domain="" ensures matching relies strictly on CONTEXT.md path globs
        out_ctx = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/bookings/handler.ts"],
            domain="",
        )
        self.assertIn("INV-BOOK-CTX", out_ctx)

        out_fallback = build_navigation_context(
            self.repo_dir,
            target_paths=["src/lib/orders/order.ts"],
            domain="",
        )
        self.assertIn("INV-ORD-FALLBACK", out_fallback)

if __name__ == "__main__":
    unittest.main()
