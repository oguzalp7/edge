#!/usr/bin/env python3
"""
RED Contract & Integration Tests for:
- AC-1: Dual-Layer Refactor Ticketing & tasks-axi Bridge (tasks_bridge.py, templates/refactor-ticket.md, brigade/radar CLIs)
- AC-3: start-slice MigrationGate CLI Default Bugfix
- AC-4: 4-Seal Machine-Generated RefactorReceipt & RefactorReceiptVerifier & Ticket.surgeon_cid
- AC-5: Refactor One-Way Door Brakes (Exported API breaks, whole-segment auth paths, blast radius, dead wrapper deletion)
- AC-6: ship_prep.py Refactor Discovery, Plans, Split Branches & Metric Delta PR Body
- AC-7: BrigadeFSM._finish_slice_via_pr Hardening, AWAITING_MERGE & confirm-merge
(AC-2 tests live in tests/test_gate.py.)
"""

import argparse
import hashlib
import importlib
import inspect
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import patch

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import tools.brigade.cli as brigade_cli
import tools.brigade.models as brigade_models
from tools.brigade.fsm import BrigadeFSM
from tools.brigade.models import CycleState, ExaminerReceipt, Ticket
import tools.brigade.ship_prep as ship_prep
import tools.radar.cli as radar_cli
from tools.radar.ledger import LedgerEngine
from tools.radar.models import FindingSeverity, FindingStatus, LedgerItem, Track


_ORIG_SUBPROCESS_RUN = subprocess.run


def _parse_frontmatter(md_path: Path) -> Tuple[Dict[str, Any], str]:
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"Expected YAML frontmatter in {md_path}"
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"Unclosed YAML frontmatter in {md_path}"
    parsed = yaml.safe_load(parts[1])
    assert isinstance(parsed, dict), f"Frontmatter must be a mapping in {md_path}"
    return parsed, parts[2]


class _HermeticBrigadeGitTestCase(unittest.TestCase):
    """Isolated temporary git repository rooted on 'development'."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._worktrees: List[Path] = []
        self.repo_path = Path(self._tmp.name).resolve()
        self._git("init", "-b", "development")
        self._git("config", "user.email", "architect@edge.local")
        self._git("config", "user.name", "Edge Architect")
        self._write_and_commit(
            {
                ".gitignore": ".edge/\n",
                "README.md": "# Edge Test Repo\n",
            },
            "chore: initial commit",
        )

    def tearDown(self) -> None:
        for wt in self._worktrees:
            if self.repo_path.exists():
                _ORIG_SUBPROCESS_RUN(
                    ["git", "worktree", "remove", "--force", str(wt)],
                    cwd=self.repo_path,
                    capture_output=True,
                )
            shutil.rmtree(wt, ignore_errors=True)
        self._tmp.cleanup()

    def _git(self, *args: str, cwd: Optional[Path] = None) -> str:
        proc = _ORIG_SUBPROCESS_RUN(
            ["git", *args],
            cwd=cwd or self.repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    def _write_and_commit(
        self,
        files: Dict[str, str],
        message: str,
        cwd: Optional[Path] = None,
    ) -> str:
        base = cwd or self.repo_path
        for rel_path, content in files.items():
            full = base / rel_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        self._git("add", "-A", cwd=base)
        self._git("commit", "--no-gpg-sign", "-m", message, cwd=base)
        return self._git("rev-parse", "HEAD", cwd=base)

    def _create_worktree(self, branch_name: str, name: str = "wt") -> Path:
        wt_path = (self.repo_path.parent / f"{self.repo_path.name}-{name}").resolve()
        self._git("worktree", "add", "-b", branch_name, str(wt_path), "development")
        self._worktrees.append(wt_path)
        return wt_path

    @staticmethod
    def _build_valid_receipt_dict(
        slug: str,
        commit_sha: str,
        changed_files: List[str],
        *,
        ticket_id: str = "TICK-CORE-BOOKINGS",
        track: str = "core",
        door_type: str = "Two-way door (Reversible Code / Configuration Change)",
        one_way_reasons: Optional[List[str]] = None,
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        metric_targets: Optional[Dict[str, Any]] = None,
        all_passed: bool = True,
        verdict: str = "PASS",
        examiner_cid: Optional[str] = "cid-examiner-2",
        surgeon_cid: Optional[str] = "cid-surgeon-1",
        tasks_axi_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        rr_mod = importlib.import_module("tools.brigade.refactor_receipt")
        if hasattr(rr_mod, "compute_changed_files_hash"):
            files_hash = rr_mod.compute_changed_files_hash(changed_files)
        else:
            files_hash = hashlib.sha256("\n".join(sorted(changed_files)).encode("utf-8")).hexdigest()

        if examiner_cid and surgeon_cid:
            neutrality = "violated" if examiner_cid == surgeon_cid else "verified"
        else:
            neutrality = "unverified"

        eff_before = before if before is not None else {
            "db_leaks": 2,
            "max_cc": 12,
            "dryer_clones": 1,
            "type_score": 80,
            "sloc": 95,
        }
        eff_after = after if after is not None else {
            "db_leaks": 0,
            "max_cc": 6,
            "dryer_clones": 0,
            "type_score": 95,
            "sloc": 72,
        }
        eff_targets = metric_targets if metric_targets is not None else {
            "db_leaks": 0,
            "max_cc": 10,
        }
        return {
            "schema_version": "1.0.0",
            "slug": slug,
            "ticket_id": ticket_id,
            "track": track,
            "seal_1_intent": {
                "ticket_id": ticket_id,
                "slug": slug,
                "track": track,
                "target_rules": ["RULE-ACTION-DB-LEAK"],
                "target_files": list(changed_files),
                "changed_files": list(changed_files),
                "changed_files_hash": files_hash,
                "commit_sha": commit_sha,
                "behavior_preserved": True,
                "door_type": door_type,
                "one_way_reasons": list(one_way_reasons or []),
                "ticket_path": f".edge/tickets/refactor/{slug}.md",
                "tasks_axi_id": tasks_axi_id,
            },
            "seal_2_metrics": {
                "before": eff_before,
                "after": eff_after,
                "metric_targets": eff_targets,
            },
            "seal_3_gate": {
                "all_passed": all_passed,
                "stages": [
                    {"stage_num": 0, "name": "Ghost Root Directory Sanitizer Gate", "passed": True, "message": "ok"},
                    {"stage_num": 1, "name": "Layer Leakage Gate", "passed": all_passed, "message": "ok" if all_passed else "leak"},
                ],
                "commit_sha": commit_sha,
                "base_branch": "development",
                "track": track,
            },
            "seal_4_examiner": {
                "verdict": verdict,
                "examiner_cid": examiner_cid,
                "surgeon_cid": surgeon_cid,
                "neutrality": neutrality,
                "sealed_at": "2026-11-21T00:00:00+00:00",
                "summary": "3-axis refactor audit passed",
                "evidence_reviewed": list(changed_files),
            },
        }


# =============================================================================
# AC-1: Dual-Layer Refactor Ticketing & tasks-axi Bridge
# =============================================================================
class TestAC1RefactorTicketingAndTasksBridge(_HermeticBrigadeGitTestCase):
    def test_refactor_ticket_template_exists_with_required_frontmatter_fields(self) -> None:
        template_path = REPO_ROOT / "templates" / "refactor-ticket.md"
        self.assertTrue(template_path.is_file(), f"Missing template: {template_path}")
        raw = template_path.read_text(encoding="utf-8")
        for key in (
            "ticket_id",
            "track",
            "target_rules",
            "target_files",
            "metric_targets",
            "door_type",
            "behavior_preserved",
            "tasks_axi_id",
        ):
            self.assertIn(key, raw, f"templates/refactor-ticket.md missing frontmatter key '{key}'")

    def test_create_refactor_ticket_writes_frontmatter_and_pins_to_target_repo(self) -> None:
        tasks_bridge = importlib.import_module("tools.brigade.tasks_bridge")
        wt_path = self._create_worktree("refactor/bookings-leak", name="wt-ac1")

        ok, ticket_path, tasks_id = tasks_bridge.create_refactor_ticket(
            repo_path=wt_path,
            slug="bookings-db-leak",
            track="core",
            target_rules=["RULE-ACTION-DB-LEAK"],
            target_files=["src/actions/bookings.ts"],
            metric_targets={"db_leaks": 0, "max_cc": 10},
            door_type="two-way",
            sync_tasks=False,
            hold_captain=False,
        )

        self.assertTrue(ok)
        self.assertIsNone(tasks_id)
        expected_path = self.repo_path / ".edge" / "tickets" / "refactor" / "bookings-db-leak.md"
        self.assertEqual(Path(ticket_path).resolve(), expected_path.resolve())
        self.assertTrue(expected_path.is_file(), "Ticket must be pinned under target_repo/.edge/tickets/refactor/")
        self.assertFalse((wt_path / ".edge" / "tickets" / "refactor" / "bookings-db-leak.md").exists())

        fm, body = _parse_frontmatter(expected_path)
        self.assertTrue(str(fm.get("ticket_id", "")).startswith("TICK-"))
        self.assertEqual(fm.get("track"), "core")
        self.assertEqual(fm.get("target_rules"), ["RULE-ACTION-DB-LEAK"])
        self.assertEqual(fm.get("target_files"), ["src/actions/bookings.ts"])
        self.assertEqual(fm.get("metric_targets"), {"db_leaks": 0, "max_cc": 10})
        self.assertEqual(fm.get("door_type"), "two-way")
        self.assertIs(fm.get("behavior_preserved"), True)
        self.assertIn("tasks_axi_id", fm)
        self.assertTrue(body.strip())

    def test_create_refactor_ticket_sync_tasks_and_hold_captain_with_mocked_subprocess(self) -> None:
        tasks_bridge = importlib.import_module("tools.brigade.tasks_bridge")
        recorded_cmds: List[str] = []

        def fake_run(cmd, *args, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            recorded_cmds.append(cmd_str)
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout='{"id": "ref-bookings-a1"}\n',
                stderr="",
            )

        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok, ticket_path, tasks_id = tasks_bridge.create_refactor_ticket(
                repo_path=self.repo_path,
                slug="bookings-sync",
                track="core",
                target_rules=["RULE-ACTION-DB-LEAK"],
                target_files=["src/actions/bookings.ts"],
                metric_targets={"db_leaks": 0},
                door_type="two-way",
                sync_tasks=True,
                hold_captain=True,
            )

        self.assertTrue(ok)
        self.assertTrue(tasks_id, "Expected non-empty tasks_axi_id when sync_tasks=True")
        self.assertTrue(
            any("tasks-axi" in c and "add" in c and "--hold" in c and "captain" in c for c in recorded_cmds),
            f"Expected tasks-axi add with --hold captain, got: {recorded_cmds}",
        )
        fm, _ = _parse_frontmatter(ticket_path)
        self.assertEqual(fm.get("tasks_axi_id"), tasks_id)

    def test_create_refactor_ticket_missing_tasks_axi_binary_degrades_gracefully(self) -> None:
        tasks_bridge = importlib.import_module("tools.brigade.tasks_bridge")
        with (
            patch("shutil.which", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError("tasks-axi")),
        ):
            ok, ticket_path, tasks_id = tasks_bridge.create_refactor_ticket(
                repo_path=self.repo_path,
                slug="bookings-offline",
                track="ui",
                target_rules=["RULE-ZERO-WRAPPERS"],
                target_files=["src/components/OldModal.tsx"],
                metric_targets={"max_cc": 8},
                sync_tasks=True,
                hold_captain=True,
            )

        self.assertTrue(ok)
        self.assertTrue(ticket_path.is_file())
        self.assertIsNone(tasks_id)

    def test_complete_linked_task_runs_done_with_pr_and_degrades_gracefully(self) -> None:
        tasks_bridge = importlib.import_module("tools.brigade.tasks_bridge")
        recorded_cmds: List[str] = []

        def fake_run(cmd, *args, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            recorded_cmds.append(cmd_str)
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="done\n", stderr="")

        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok, msg = tasks_bridge.complete_linked_task("ref-bookings-a1", "https://github.com/org/repo/pull/77")
            self.assertTrue(ok, msg)
            self.assertTrue(
                any(
                    "tasks-axi" in c and "done" in c and "ref-bookings-a1" in c and "--pr" in c and "https://github.com/org/repo/pull/77" in c
                    for c in recorded_cmds
                ),
                f"Expected tasks-axi done <id> --pr <url>, got: {recorded_cmds}",
            )

            # Empty / None ID must skip subprocess invocation without crashing
            recorded_cmds.clear()
            res_empty = tasks_bridge.complete_linked_task("", "https://github.com/org/repo/pull/77")
            res_none = tasks_bridge.complete_linked_task(None, "https://github.com/org/repo/pull/77")
            self.assertIsInstance(res_empty, tuple)
            self.assertIsInstance(res_none, tuple)
            self.assertEqual(recorded_cmds, [])

        # Missing binary must degrade gracefully without raising
        with (
            patch("shutil.which", return_value=None),
            patch("subprocess.run", side_effect=FileNotFoundError("tasks-axi")),
        ):
            res_missing = tasks_bridge.complete_linked_task("ref-bookings-a1", "https://github.com/org/repo/pull/77")
            self.assertIsInstance(res_missing, tuple)
            self.assertEqual(len(res_missing), 2)
            self.assertIsInstance(res_missing[0], bool)
            self.assertIsInstance(res_missing[1], str)

    def test_brigade_cli_create_refactor_ticket_command(self) -> None:
        recorded_cmds: List[str] = []

        def fake_run(cmd, *args, **kwargs):
            cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
            if "tasks-axi" in cmd_str:
                recorded_cmds.append(cmd_str)
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout='{"id": "cli-task-1"}\n', stderr="")
            return _ORIG_SUBPROCESS_RUN(cmd, *args, **kwargs)

        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
            patch.object(
                sys,
                "argv",
                [
                    "brigade",
                    "create-refactor-ticket",
                    str(self.repo_path),
                    "--slug",
                    "clients-cc",
                    "--track",
                    "core",
                    "--rules",
                    "RULE-MAX-CC",
                    "--files",
                    "src/core/clients.ts",
                    "--targets",
                    "max_cc=8,db_leaks=0",
                    "--sync-tasks",
                    "--hold-captain",
                ],
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc = brigade_cli.main()

        self.assertEqual(rc, 0)
        ticket_file = self.repo_path / ".edge" / "tickets" / "refactor" / "clients-cc.md"
        self.assertTrue(ticket_file.is_file())
        fm, _ = _parse_frontmatter(ticket_file)
        self.assertEqual(fm.get("track"), "core")
        self.assertIn("RULE-MAX-CC", fm.get("target_rules", []))
        self.assertIn("src/core/clients.ts", fm.get("target_files", []))
        self.assertTrue(any("--hold" in c and "captain" in c for c in recorded_cmds))

    def test_radar_export_tasks_converts_open_ledger_items_deduplicated_and_skips_resolved(self) -> None:
        ledger = LedgerEngine(self.repo_path)
        items = [
            LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-ACTION-DB-LEAK", "src/actions/bookings.ts", "createBooking"),
                track=Track.CORE.value,
                rule_id="RULE-ACTION-DB-LEAK",
                title="Direct DB query in bookings action",
                file_path="src/actions/bookings.ts",
                line_number=42,
                symbol="createBooking",
                severity=FindingSeverity.CRITICAL.value,
                status=FindingStatus.OPEN.value,
                details={"db_leaks": 2},
                suggested_fix="Move query to repository",
                first_seen_at="2026-11-20T00:00:00Z",
                last_seen_at="2026-11-21T00:00:00Z",
            ),
            LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-HIGH-CC", "src/core/pricing.ts", "calcPrice"),
                track=Track.CORE.value,
                rule_id="RULE-HIGH-CC",
                title="High CC in pricing engine",
                file_path="src/core/pricing.ts",
                line_number=18,
                symbol="calcPrice",
                severity=FindingSeverity.WARNING.value,
                status=FindingStatus.OPEN.value,
                details={"max_cc": 16},
                suggested_fix="Extract helpers",
                first_seen_at="2026-11-20T00:00:00Z",
                last_seen_at="2026-11-21T00:00:00Z",
            ),
            LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-DEEP-NESTING", "src/lib/old.ts", "legacy"),
                track=Track.CORE.value,
                rule_id="RULE-DEEP-NESTING",
                title="Already resolved item",
                file_path="src/lib/old.ts",
                line_number=5,
                symbol="legacy",
                severity=FindingSeverity.ADVISORY.value,
                status=FindingStatus.RESOLVED.value,
                details={},
                suggested_fix="None",
                first_seen_at="2026-11-19T00:00:00Z",
                last_seen_at="2026-11-20T00:00:00Z",
                resolved_at="2026-11-21T00:00:00Z",
            ),
        ]
        ledger.sync_channel("core", items)

        tickets_dir = self.repo_path / ".edge" / "tickets" / "refactor"
        with (
            patch.object(sys, "argv", ["radar", "export-tasks", str(self.repo_path), "--track", "core", "--top", "10"]),
            redirect_stdout(io.StringIO()),
        ):
            radar_cli.main()

        exported = sorted(tickets_dir.glob("*.md"))
        self.assertEqual(len(exported), 2, f"Expected 2 OPEN items exported (excluding RESOLVED), got: {exported}")
        for md in exported:
            fm, _ = _parse_frontmatter(md)
            self.assertEqual(fm.get("track"), "core")
            self.assertIs(fm.get("behavior_preserved"), True)
            self.assertNotIn("src/lib/old.ts", fm.get("target_files", []))

        # Second export must deduplicate cleanly without creating extra files
        with (
            patch.object(sys, "argv", ["radar", "export-tasks", str(self.repo_path), "--track", "core", "--top", "10"]),
            redirect_stdout(io.StringIO()),
        ):
            radar_cli.main()
        self.assertEqual(len(list(tickets_dir.glob("*.md"))), 2)

        # --top 1 on clean export dir limits to 1 file
        for f in tickets_dir.glob("*.md"):
            f.unlink()
        with (
            patch.object(sys, "argv", ["radar", "export-tasks", str(self.repo_path), "--track", "core", "--top", "1"]),
            redirect_stdout(io.StringIO()),
        ):
            radar_cli.main()
        self.assertEqual(len(list(tickets_dir.glob("*.md"))), 1)


# =============================================================================
# AC-3: start-slice MigrationGate CLI Default Bugfix
# =============================================================================
class TestAC3StartSliceMigrationGateDefaults(_HermeticBrigadeGitTestCase):
    def test_fsm_start_slice_preserves_python_default_allow_schema_migration_true(self) -> None:
        sig = inspect.signature(BrigadeFSM.start_slice)
        self.assertIn("allow_schema_migration", sig.parameters)
        self.assertIs(sig.parameters["allow_schema_migration"].default, True)

    def test_cli_start_slice_defaults_allow_migration_false_for_core_and_ui_and_blocks_schema_edits(self) -> None:
        self._write_and_commit(
            {
                "src/actions/bookings.ts": "export function run() { return 1; }\n",
                "src/db/schema/bookings.ts": "export const bookingsTable = {};\n",
            },
            "chore: seed action and schema",
        )

        for track in ("core", "ui"):
            with self.subTest(track=track):
                try:
                    with (
                        patch("tools.brigade.fsm.is_treehouse_installed", return_value=False),
                        patch.object(
                            sys,
                            "argv",
                            [
                                "brigade",
                                "start-slice",
                                str(self.repo_path),
                                "--name",
                                f"slice-{track}",
                                "--track",
                                track,
                                "--target-file",
                                "src/actions/bookings.ts",
                            ],
                        ),
                        redirect_stdout(io.StringIO()),
                    ):
                        rc = brigade_cli.main()

                    self.assertEqual(rc, 0)
                    fsm = BrigadeFSM(self.repo_path)
                    ticket = fsm.state.active_ticket
                    self.assertIsNotNone(ticket)
                    self.assertFalse(
                        ticket.allow_schema_migration,
                        f"CLI start-slice --track {track} MUST default allow_schema_migration=False",
                    )
                    self.assertIsInstance(ticket.before_metrics, dict)

                    # Touch forbidden schema file -> MigrationGate MUST block!
                    (self.repo_path / "src" / "db" / "schema" / "bookings.ts").write_text(
                        "export const bookingsTable = { v: 2 };\n",
                        encoding="utf-8",
                    )
                    ok, msg, details = fsm.guard_surgery_to_verify()
                    self.assertFalse(ok, f"MigrationGate must block schema edit on --track {track}")
                    self.assertIn("MigrationGate", msg)
                    self.assertIn("src/db/schema/bookings.ts", details.get("schema_violations", []))
                finally:
                    self._git("checkout", "--", "src/db/schema/bookings.ts")
                    BrigadeFSM(self.repo_path).abort("reset after subtest")

    def test_cli_start_slice_feature_defaults_true_and_explicit_allow_migration_overrides_core(self) -> None:
        with (
            patch("tools.brigade.fsm.is_treehouse_installed", return_value=False),
            patch.object(
                sys,
                "argv",
                ["brigade", "start-slice", str(self.repo_path), "--name", "feat-a", "--track", "feature"],
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc_feat = brigade_cli.main()
        self.assertEqual(rc_feat, 0)
        fsm_feat = BrigadeFSM(self.repo_path)
        self.assertTrue(fsm_feat.state.active_ticket.allow_schema_migration)
        fsm_feat.abort("cleanup")

        with (
            patch("tools.brigade.fsm.is_treehouse_installed", return_value=False),
            patch.object(
                sys,
                "argv",
                ["brigade", "start-slice", str(self.repo_path), "--name", "core-mig", "--track", "core", "--allow-migration"],
            ),
            redirect_stdout(io.StringIO()),
        ):
            rc_over = brigade_cli.main()
        self.assertEqual(rc_over, 0)
        fsm_over = BrigadeFSM(self.repo_path)
        self.assertTrue(fsm_over.state.active_ticket.allow_schema_migration)
        fsm_over.abort("cleanup")

        # Direct cmd_start_slice invocation with allow_migration=None on core resolves False
        args_none = argparse.Namespace(
            repo=str(self.repo_path),
            name="core-direct-none",
            track="core",
            target_file="src/actions/bookings.ts",
            domain="bookings",
            test_cmd="npm run test:unit",
            allow_migration=None,
        )
        with patch("tools.brigade.fsm.is_treehouse_installed", return_value=False), redirect_stdout(io.StringIO()):
            rc_dir = brigade_cli.cmd_start_slice(args_none)
        self.assertEqual(rc_dir, 0)
        self.assertIs(BrigadeFSM(self.repo_path).state.active_ticket.allow_schema_migration, False)


# =============================================================================
# AC-4: 4-Seal Machine-Generated RefactorReceipt & RefactorReceiptVerifier
# =============================================================================
class TestAC4RefactorReceiptAndVerifier(_HermeticBrigadeGitTestCase):
    def test_models_ticket_and_cycle_state_extensions_and_backward_compat(self) -> None:
        self.assertTrue(hasattr(CycleState, "AWAITING_MERGE"))
        self.assertEqual(CycleState.AWAITING_MERGE.value, "AWAITING_MERGE")

        legacy_ticket_dict = {
            "ticket_id": "TICK-LEGACY-1",
            "track": "core",
            "domain": "bookings",
            "rule_id": "RULE-DB-LEAK",
            "severity": "CRITICAL",
            "target_file": "src/actions/bookings.ts",
            "line_number": 10,
            "fingerprint": "fp-legacy",
            "description": "legacy",
            "suggested_fix": "extract",
        }
        legacy_restored = Ticket.from_dict(legacy_ticket_dict)
        self.assertEqual(legacy_restored.ticket_id, "TICK-LEGACY-1")

        t = Ticket(
            **legacy_ticket_dict,
            tasks_axi_id="task-123",
            metric_targets={"db_leaks": 0, "max_cc": 10},
            refactor_ticket_path=".edge/tickets/refactor/bookings.md",
            before_metrics={"db_leaks": 2, "max_cc": 12, "sloc": 80},
            surgeon_cid="cid-surgeon-1",
            pr_url="https://github.com/org/repo/pull/55",
        )
        roundtrip = Ticket.from_dict(t.to_dict())
        self.assertEqual(roundtrip.tasks_axi_id, "task-123")
        self.assertEqual(roundtrip.metric_targets, {"db_leaks": 0, "max_cc": 10})
        self.assertEqual(roundtrip.refactor_ticket_path, ".edge/tickets/refactor/bookings.md")
        self.assertEqual(roundtrip.before_metrics, {"db_leaks": 2, "max_cc": 12, "sloc": 80})
        self.assertEqual(roundtrip.surgeon_cid, "cid-surgeon-1")
        self.assertEqual(roundtrip.pr_url, "https://github.com/org/repo/pull/55")

    def test_advance_gate_to_review_and_review_to_staging_synthesizes_4_seal_receipt_pinned_to_target_repo(self) -> None:
        rr_mod = importlib.import_module("tools.brigade.refactor_receipt")
        RefactorReceiptVerifier = rr_mod.RefactorReceiptVerifier

        self._write_and_commit(
            {
                "src/actions/bookings.ts": (
                    "export async function listBookings() {\n"
                    "    return db.select().from(bookings);\n"
                    "}\n"
                ),
            },
            "chore: add leaky action on development",
        )

        fsm = BrigadeFSM(self.repo_path)
        fsm.registry.register(brigade_models.StationRole.SURGEON, "cid-surgeon-1", "Surgeon")
        fsm.registry.register(brigade_models.StationRole.EXAMINER, "cid-examiner-2", "Examiner")
        fsm.save()

        wt_path = self._create_worktree("refactor/bookings-leak", name="wt-ac4")
        with (
            patch("tools.brigade.fsm.is_treehouse_installed", return_value=True),
            patch("tools.brigade.fsm.acquire_worktree", return_value=(True, str(wt_path), "")),
        ):
            ok_start, ticket, msg_start = fsm.start_slice(
                name="bookings-leak",
                track="core",
                target_file="src/actions/bookings.ts",
                allow_schema_migration=False,
            )
        self.assertTrue(ok_start, msg_start)
        self.assertIsNotNone(ticket.before_metrics)
        self.assertGreaterEqual(ticket.before_metrics.get("db_leaks", 0), 1)
        ticket.metric_targets = {"db_leaks": 0, "max_cc": 10}
        ticket.surgeon_cid = ticket.surgeon_cid or "cid-surgeon-1"
        fsm.save()

        # Perform clean refactor inside isolated worktree and commit
        self._write_and_commit(
            {
                "src/lib/bookings/repository.ts": "export async function fetchBookings() { return []; }\n",
                "src/actions/bookings.ts": (
                    "import { fetchBookings } from '../lib/bookings/repository';\n"
                    "export async function listBookings() {\n"
                    "    return fetchBookings();\n"
                    "}\n"
                ),
            },
            "refactor: extract bookings repository",
            cwd=wt_path,
        )

        with patch.object(fsm, "_run_hermetic_verification", return_value=(True, "ok")):
            ok1, st1, m1 = fsm.advance()
            self.assertTrue(ok1, m1)
            self.assertEqual(st1, CycleState.VERIFY)

            ok2, st2, m2 = fsm.advance()
            self.assertTrue(ok2, m2)
            self.assertEqual(st2, CycleState.GATE)

            # GATE -> REVIEW synthesizes 4-seal receipt under target_repo/.edge/receipts/refactor/
            ok3, st3, m3 = fsm.advance()
            self.assertTrue(ok3, m3)
            self.assertEqual(st3, CycleState.REVIEW)

        receipts_dir = self.repo_path / ".edge" / "receipts" / "refactor"
        json_files = list(receipts_dir.glob("*.json"))
        md_files = list(receipts_dir.glob("*.md"))
        self.assertEqual(len(json_files), 1, f"Expected 1 receipt JSON under {receipts_dir}, got {json_files}")
        self.assertEqual(len(md_files), 1, f"Expected 1 receipt MD under {receipts_dir}, got {md_files}")
        self.assertFalse((wt_path / ".edge" / "receipts" / "refactor").exists())

        receipt_data = json.loads(json_files[0].read_text(encoding="utf-8"))
        self.assertIs(receipt_data["seal_1_intent"]["behavior_preserved"], True)
        self.assertEqual(receipt_data["seal_2_metrics"]["after"]["db_leaks"], 0)
        self.assertIs(receipt_data["seal_3_gate"]["all_passed"], True)
        self.assertTrue(receipt_data["seal_1_intent"]["changed_files_hash"])

        # Seal Examiner PASS with distinct CID and advance REVIEW -> STAGING (refreshes Seal 4)
        with patch.object(
            sys,
            "argv",
            [
                "brigade",
                "seal-review",
                str(self.repo_path),
                "--verdict",
                "PASS",
                "--summary",
                "Clean 3-axis refactor audit",
                "--evidence-reviewed",
                "src/actions/bookings.ts,src/lib/bookings/repository.ts",
                "--examiner-cid",
                "cid-examiner-2",
            ],
        ), redirect_stdout(io.StringIO()):
            rc_seal = brigade_cli.main()
        self.assertEqual(rc_seal, 0)

        fsm_reloaded = BrigadeFSM(self.repo_path)
        with patch.object(fsm_reloaded, "_run_hermetic_verification", return_value=(True, "ok")):
            ok4, st4, m4 = fsm_reloaded.advance()
        self.assertTrue(ok4, m4)
        self.assertEqual(st4, CycleState.STAGING)

        refreshed = json.loads(json_files[0].read_text(encoding="utf-8"))
        seal4 = refreshed["seal_4_examiner"]
        self.assertEqual(seal4["verdict"], "PASS")
        self.assertEqual(seal4["examiner_cid"], "cid-examiner-2")
        self.assertEqual(seal4["surgeon_cid"], "cid-surgeon-1")
        self.assertEqual(seal4["neutrality"], "verified")

        v_ok, v_msg, _ = RefactorReceiptVerifier.verify_receipt_file(
            json_files[0],
            repo_path=self.repo_path,
            base_ref="development",
            work_dir=wt_path,
        )
        self.assertTrue(v_ok, v_msg)

    def test_cli_seal_refactor_creates_receipt(self) -> None:
        rr_mod = importlib.import_module("tools.brigade.refactor_receipt")
        self._write_and_commit(
            {"src/actions/clients.ts": "export async function getClients() { return db.select().from(clients); }\n"},
            "chore: add client action",
        )
        self._git("checkout", "-b", "refactor/clients-clean")
        self._write_and_commit(
            {"src/actions/clients.ts": "export async function getClients() { return []; }\n"},
            "refactor: remove direct sql from clients action",
        )

        fsm = BrigadeFSM(self.repo_path)
        fsm.state.base_branch = "development"
        fsm.state.active_ticket = Ticket(
            ticket_id="TICK-CORE-CLIENTS",
            track="core",
            domain="clients",
            rule_id="RULE-ACTION-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/clients.ts",
            line_number=1,
            fingerprint="fp-clients",
            description="Extract client db query",
            suggested_fix="Move to repository",
            branch_name="refactor/clients-clean",
            metric_targets={"db_leaks": 0, "max_cc": 10},
            before_metrics={"db_leaks": 1, "max_cc": 2, "sloc": 1},
            surgeon_cid="cid-surg-10",
        )
        fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="PASS",
            summary="Verified cleanly",
            ticket_id="TICK-CORE-CLIENTS",
            evidence_reviewed=["src/actions/clients.ts"],
            examiner_cid="cid-exam-20",
        )
        fsm.save()

        with patch.object(
            sys,
            "argv",
            ["brigade", "seal-refactor", str(self.repo_path), "--slug", "clients-clean", "--base", "development"],
        ), redirect_stdout(io.StringIO()):
            rc = brigade_cli.main()

        self.assertEqual(rc, 0)
        json_path = self.repo_path / ".edge" / "receipts" / "refactor" / "clients-clean.json"
        md_path = self.repo_path / ".edge" / "receipts" / "refactor" / "clients-clean.md"
        self.assertTrue(json_path.is_file())
        self.assertTrue(md_path.is_file())

        ok, msg, _ = rr_mod.RefactorReceiptVerifier.verify_receipt_file(
            json_path,
            repo_path=self.repo_path,
            base_ref="development",
        )
        self.assertTrue(ok, msg)

    def test_verifier_rejects_non_improving_or_null_target_metric(self) -> None:
        rr_mod = importlib.import_module("tools.brigade.refactor_receipt")
        Verifier = rr_mod.RefactorReceiptVerifier
        head_sha = self._git("rev-parse", "HEAD")

        # 1. Target metric db_leaks > target (non-improving)
        bad_leak = self._build_valid_receipt_dict(
            "bad-leak",
            head_sha,
            ["src/actions/bookings.ts"],
            after={"db_leaks": 1, "max_cc": 5, "dryer_clones": 0, "type_score": 95, "sloc": 40},
            metric_targets={"db_leaks": 0, "max_cc": 10},
        )
        ok_leak, _, _ = Verifier.verify_metric_delta(bad_leak)
        self.assertFalse(ok_leak, "Verifier must reject non-improving db_leaks > target")

        # 2. Target metric type_score < target
        bad_types = self._build_valid_receipt_dict(
            "bad-types",
            head_sha,
            ["src/actions/bookings.ts"],
            after={"db_leaks": 0, "max_cc": 5, "dryer_clones": 0, "type_score": 70, "sloc": 40},
            metric_targets={"type_score": 90},
        )
        ok_types, _, _ = Verifier.verify_metric_delta(bad_types)
        self.assertFalse(ok_types, "Verifier must reject type_score below target")

        # 3. Null value for any required metric_targets key (e.g. missing tree-sitter)
        null_metric = self._build_valid_receipt_dict(
            "null-dryer",
            head_sha,
            ["src/actions/bookings.ts"],
            after={"db_leaks": 0, "max_cc": 5, "dryer_clones": None, "type_score": 95, "sloc": 40},
            metric_targets={"dryer_clones": 0},
        )
        ok_null, _, _ = Verifier.verify_metric_delta(null_metric)
        self.assertFalse(ok_null, "Verifier MUST reject None (null) for any required metric_targets key")
        ok_full, _, _ = Verifier.verify_receipt(null_metric)
        self.assertFalse(ok_full)

    def test_verifier_enforces_surgeon_examiner_neutrality(self) -> None:
        rr_mod = importlib.import_module("tools.brigade.refactor_receipt")
        Verifier = rr_mod.RefactorReceiptVerifier
        head_sha = self._git("rev-parse", "HEAD")

        # Violated: examiner_cid == surgeon_cid
        violated = self._build_valid_receipt_dict(
            "violated",
            head_sha,
            ["src/actions/bookings.ts"],
            examiner_cid="cid-same",
            surgeon_cid="cid-same",
        )
        self.assertEqual(violated["seal_4_examiner"]["neutrality"], "violated")
        ok_v, _, _ = Verifier.verify_examiner_seal(violated, strict=True)
        self.assertFalse(ok_v)
        ok_vr, _, _ = Verifier.verify_receipt(violated, strict=True)
        self.assertFalse(ok_vr)

        # Unverified: missing surgeon_cid or examiner_cid -> hard block in strict mode
        for ex_cid, su_cid in ((None, "cid-surg"), ("cid-exam", None), ("", "cid-surg")):
            unverified = self._build_valid_receipt_dict(
                "unverified",
                head_sha,
                ["src/actions/bookings.ts"],
                examiner_cid=ex_cid,
                surgeon_cid=su_cid,
            )
            ok_u, _, _ = Verifier.verify_examiner_seal(unverified, strict=True)
            self.assertFalse(ok_u, f"Missing CID ({ex_cid}, {su_cid}) must hard-block in strict mode")

        # Verified: distinct non-empty CIDs
        verified = self._build_valid_receipt_dict(
            "verified",
            head_sha,
            ["src/actions/bookings.ts"],
            examiner_cid="cid-exam-1",
            surgeon_cid="cid-surg-2",
        )
        ok_ok, msg_ok, _ = Verifier.verify_examiner_seal(verified, strict=True)
        self.assertTrue(ok_ok, msg_ok)

    def test_verifier_rejects_stale_commit_sha_and_changed_files_hash(self) -> None:
        rr_mod = importlib.import_module("tools.brigade.refactor_receipt")
        Verifier = rr_mod.RefactorReceiptVerifier

        self._git("checkout", "-b", "refactor/stale-test")
        sha1 = self._write_and_commit({"src/a.ts": "export const a = 1;\n"}, "refactor: commit 1")

        receipt = self._build_valid_receipt_dict("stale-test", sha1, ["src/a.ts"])
        receipt_file = self.repo_path / ".edge" / "receipts" / "refactor" / "stale-test.json"
        receipt_file.parent.mkdir(parents=True, exist_ok=True)
        receipt_file.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

        # Valid against current commit sha1
        ok_now, msg_now, _ = Verifier.verify_receipt_file(receipt_file, repo_path=self.repo_path, base_ref="development")
        self.assertTrue(ok_now, msg_now)

        # Tampered changed_files_hash -> rejected
        tampered = json.loads(json.dumps(receipt))
        tampered["seal_1_intent"]["changed_files_hash"] = "0" * 64
        ok_hash, _, _ = Verifier.verify_intent_and_door(tampered, repo_path=self.repo_path, base_ref="development")
        self.assertFalse(ok_hash, "Tampered/mismatched changed_files_hash must be rejected")

        # Advance HEAD with a new commit -> receipt bound to sha1 is now stale and MUST be rejected
        self._write_and_commit({"src/b.ts": "export const b = 2;\n"}, "refactor: commit 2")
        ok_stale, _, _ = Verifier.verify_receipt_file(receipt_file, repo_path=self.repo_path, base_ref="development")
        self.assertFalse(ok_stale, "Stale receipt with outdated commit_sha / diff must be rejected")


# =============================================================================
# AC-5: Refactor One-Way Door Brakes in ship_prep.py
# =============================================================================
class TestAC5RefactorOneWayDoorBrakes(_HermeticBrigadeGitTestCase):
    def test_exported_public_api_breaks_vs_reformatted_exports_and_comments(self) -> None:
        cases_one_way = [
            (
                "function signature change",
                "\n".join([
                    "diff --git a/src/lib/pricing.ts b/src/lib/pricing.ts",
                    "--- a/src/lib/pricing.ts",
                    "+++ b/src/lib/pricing.ts",
                    "@@ -1,3 +1,3 @@",
                    "-export function calcPrice(a: number): number {",
                    "+export function calcPrice(a: number, b: number): number {",
                    "     return a;",
                    " }",
                ]),
                ["src/lib/pricing.ts"],
            ),
            (
                "export { a, b } removal",
                "\n".join([
                    "diff --git a/src/lib/index.ts b/src/lib/index.ts",
                    "--- a/src/lib/index.ts",
                    "+++ b/src/lib/index.ts",
                    "@@ -1 +1 @@",
                    "-export { alpha, beta } from './core';",
                    "+export { alpha } from './core';",
                ]),
                ["src/lib/index.ts"],
            ),
            (
                "export * from removal",
                "\n".join([
                    "diff --git a/src/lib/barrel.ts b/src/lib/barrel.ts",
                    "--- a/src/lib/barrel.ts",
                    "+++ b/src/lib/barrel.ts",
                    "@@ -1,2 +1 @@",
                    "-export * from './legacy';",
                    " export const version = 2;",
                ]),
                ["src/lib/barrel.ts"],
            ),
            (
                "export default removal",
                "\n".join([
                    "diff --git a/src/components/Card.tsx b/src/components/Card.tsx",
                    "--- a/src/components/Card.tsx",
                    "+++ b/src/components/Card.tsx",
                    "@@ -1,2 +1,2 @@",
                    "-export default function Card() { return null; }",
                    "+export function Card() { return null; }",
                ]),
                ["src/components/Card.tsx"],
            ),
            (
                "module.exports break",
                "\n".join([
                    "diff --git a/src/legacy/util.js b/src/legacy/util.js",
                    "--- a/src/legacy/util.js",
                    "+++ b/src/legacy/util.js",
                    "@@ -1 +1 @@",
                    "-module.exports = { foo, bar };",
                    "+module.exports = { foo };",
                ]),
                ["src/legacy/util.js"],
            ),
        ]

        for label, diff_text, files in cases_one_way:
            with self.subTest(case=label):
                door, blast = ship_prep.classify_merge_danger(
                    files,
                    diff_stat="1 file changed, 1 insertion(+), 1 deletion(-)",
                    diff_text=diff_text,
                    is_refactor=True,
                )
                self.assertTrue(door.startswith("One-way door"), f"{label} must trigger One-way door, got: {door} ({blast})")
                self.assertTrue(blast.get("one_way_reasons"), f"Expected one_way_reasons for {label}")

        # Reformatted/moved export preserving symbol & signature stays Two-way door
        reformatted_diff = "\n".join([
            "diff --git a/src/lib/pricing.ts b/src/lib/pricing.ts",
            "--- a/src/lib/pricing.ts",
            "+++ b/src/lib/pricing.ts",
            "@@ -1,3 +1,7 @@",
            "-export function calcPrice(a: number, b: number): number {",
            "+export function calcPrice(",
            "+  a: number,",
            "+  b: number,",
            "+): number {",
            "     return a + b;",
            " }",
        ])
        door_reformat, blast_reformat = ship_prep.classify_merge_danger(
            ["src/lib/pricing.ts"],
            diff_stat="1 file changed, 4 insertions(+), 1 deletion(-)",
            diff_text=reformatted_diff,
            is_refactor=True,
        )
        self.assertTrue(
            door_reformat.startswith("Two-way door"),
            f"Reformatted export preserving signature must stay Two-way door, got: {door_reformat} ({blast_reformat})",
        )

        # Commented-out export line removal stays Two-way door
        comment_diff = "\n".join([
            "diff --git a/src/lib/pricing.ts b/src/lib/pricing.ts",
            "--- a/src/lib/pricing.ts",
            "+++ b/src/lib/pricing.ts",
            "@@ -1,2 +1 @@",
            "-// export function oldRemovedInComment(x: number) {}",
            " export function calcPrice(a: number): number { return a; }",
        ])
        door_comment, _ = ship_prep.classify_merge_danger(
            ["src/lib/pricing.ts"],
            diff_stat="1 file changed, 1 deletion(-)",
            diff_text=comment_diff,
            is_refactor=True,
        )
        self.assertTrue(door_comment.startswith("Two-way door"), f"Comment removal must stay Two-way door, got: {door_comment}")

    def test_auth_security_whole_segment_paths_vs_safe_substrings(self) -> None:
        for auth_path in (
            "src/auth/login.ts",
            "src/middleware.ts",
            "src/lib/rbac/check.ts",
            "src/lib/permissions.ts",
        ):
            with self.subTest(auth_path=auth_path):
                door, blast = ship_prep.classify_merge_danger([auth_path], is_refactor=True)
                self.assertTrue(door.startswith("One-way door"), f"Auth path '{auth_path}' must trigger One-way door, got: {door}")
                self.assertTrue(blast.get("one_way_reasons"))

        for safe_path in (
            "src/utils/sessionStorage.ts",
            "src/components/authorName.tsx",
        ):
            with self.subTest(safe_path=safe_path):
                door, _ = ship_prep.classify_merge_danger([safe_path], is_refactor=True)
                self.assertTrue(
                    door.startswith("Two-way door"),
                    f"Safe substring path '{safe_path}' must NOT trigger One-way door, got: {door}",
                )

    def test_blast_radius_thresholds_15_files_and_500_lines(self) -> None:
        files_16 = [f"src/lib/mod_{i}.ts" for i in range(16)]
        door_16, blast_16 = ship_prep.classify_merge_danger(files_16, diff_stat="16 files changed, 32 insertions(+)", is_refactor=True)
        self.assertTrue(door_16.startswith("One-way door"), f">15 files must trigger One-way door, got: {door_16}")
        self.assertTrue(blast_16.get("one_way_reasons"))

        files_15 = [f"src/lib/mod_{i}.ts" for i in range(15)]
        door_15, _ = ship_prep.classify_merge_danger(files_15, diff_stat="15 files changed, 30 insertions(+)", is_refactor=True)
        self.assertTrue(door_15.startswith("Two-way door"), f"<=15 files must stay Two-way door, got: {door_15}")

        door_501, blast_501 = ship_prep.classify_merge_danger(
            ["src/lib/big.ts"],
            diff_stat="1 file changed, 300 insertions(+), 201 deletions(-)",
            is_refactor=True,
        )
        self.assertTrue(door_501.startswith("One-way door"), f">500 lines must trigger One-way door, got: {door_501}")
        self.assertTrue(blast_501.get("one_way_reasons"))

        door_500, _ = ship_prep.classify_merge_danger(
            ["src/lib/big.ts"],
            diff_stat="1 file changed, 300 insertions(+), 200 deletions(-)",
            is_refactor=True,
        )
        self.assertTrue(door_500.startswith("Two-way door"), f"<=500 lines must stay Two-way door, got: {door_500}")

    def test_pure_dead_wrapper_file_deletion_stays_two_way_door(self) -> None:
        self._write_and_commit(
            {
                "src/lib/deadWrapper.ts": (
                    "function legacyInternalWrapper(x: number): number {\n"
                    "    return x + 1;\n"
                    "}\n"
                ),
            },
            "chore: add dead wrapper",
        )
        self._git("checkout", "-b", "refactor/prune-dead-wrapper")
        self._git("rm", "src/lib/deadWrapper.ts")
        self._git("commit", "--no-gpg-sign", "-m", "refactor: delete unused deadWrapper")

        ok, res, err = ship_prep.prepare_ship_payload(self.repo_path, base_branch="development")
        self.assertTrue(ok, err)
        self.assertTrue(
            res.door_type.startswith("Two-way door"),
            f"Pure dead file deletion with no exported API break must stay Two-way door, got: {res.door_type}",
        )


# =============================================================================
# AC-6: ship_prep.py Refactor Discovery, Plans, Split Branches & Metric Table
# =============================================================================
class TestAC6ShipPrepRefactorDiscoveryPlansSplitAndPrBody(_HermeticBrigadeGitTestCase):
    def test_clean_pr_title_kind_refactor_vs_spec_default(self) -> None:
        self.assertEqual(
            ship_prep._clean_pr_title("bookings-leak", "Extract bookings repository"),
            "feat(bookings-leak): Extract bookings repository",
        )
        self.assertEqual(
            ship_prep._clean_pr_title("bookings-leak", "Extract bookings repository", kind="refactor"),
            "refactor(bookings-leak): Extract bookings repository",
        )

    def test_ship_prep_discovers_valid_refactor_receipt_filters_stale_and_renders_metric_delta_table(self) -> None:
        self._write_and_commit(
            {"src/actions/bookings.ts": "export async function run() { return db.select().from(bookings); }\n"},
            "chore: seed action",
        )
        self._git("checkout", "-b", "refactor/bookings-leak")
        head_sha = self._write_and_commit(
            {
                "src/lib/bookings/repository.ts": "export async function fetchBookings() { return []; }\n",
                "src/actions/bookings.ts": "import { fetchBookings } from '../lib/bookings/repository';\nexport async function run() { return fetchBookings(); }\n",
            },
            "refactor: extract bookings repository",
        )

        receipts_dir = self.repo_path / ".edge" / "receipts" / "refactor"
        receipts_dir.mkdir(parents=True, exist_ok=True)

        # Stale receipt from an earlier unrelated slice MUST be filtered out
        stale_receipt = self._build_valid_receipt_dict(
            "old-stale-slice",
            "0000000000000000000000000000000000000000",
            ["src/old/unrelated.ts"],
            ticket_id="TICK-CORE-OLD",
        )
        (receipts_dir / "old-stale-slice.json").write_text(json.dumps(stale_receipt, indent=2), encoding="utf-8")

        # Valid receipt bound to current HEAD & diff
        changed_files = ["src/actions/bookings.ts", "src/lib/bookings/repository.ts"]
        valid_receipt = self._build_valid_receipt_dict(
            "bookings-leak",
            head_sha,
            changed_files,
            ticket_id="TICK-CORE-BOOKINGS",
            before={"db_leaks": 2, "max_cc": 12, "dryer_clones": 1, "type_score": 80, "sloc": 95},
            after={"db_leaks": 0, "max_cc": 6, "dryer_clones": 0, "type_score": 95, "sloc": 72},
            metric_targets={"db_leaks": 0, "max_cc": 10},
        )
        (receipts_dir / "bookings-leak.json").write_text(json.dumps(valid_receipt, indent=2), encoding="utf-8")

        ok, res, err = ship_prep.prepare_ship_payload(self.repo_path, base_branch="development")
        self.assertTrue(ok, f"prepare_ship_payload failed: {err}")

        slugs = [p.spec_slug for p in res.spec_plans]
        self.assertNotIn("old-stale-slice", slugs, "Stale gitignored refactor receipt must be ignored")
        self.assertIn("bookings-leak", slugs)

        plan = next(p for p in res.spec_plans if p.spec_slug == "bookings-leak")
        self.assertEqual(plan.kind, "refactor")
        self.assertIsNotNone(plan.refactor_receipt)
        self.assertTrue(plan.pr_title.startswith("refactor(bookings-leak):"), f"Unexpected PR title: {plan.pr_title}")

        # 2-section PR body: ## Summary (Door lock + Before/After Metric Delta table) and ## Evidence (Receipt, Gate, Examiner)
        for body in (plan.pr_body, res.pr_body):
            self.assertIn("## Summary", body)
            self.assertIn("## Evidence", body)
            self.assertNotIn("## Merge Danger", body)
            self.assertIn("Two-way door", body)
            # Metric delta table assertions
            self.assertIn("db_leaks", body)
            self.assertIn("max_cc", body)
            self.assertIn("|", body)
            # Evidence assertions
            self.assertIn(".edge/receipts/refactor/bookings-leak.json", body)
            self.assertIn("Examiner 3-Axis Seal", body)
            self.assertIn("Gate", body)

    def test_ship_prep_blocks_matching_invalid_refactor_receipt(self) -> None:
        self._git("checkout", "-b", "refactor/invalid-receipt")
        head_sha = self._write_and_commit(
            {"src/actions/bookings.ts": "export const x = 1;\n"},
            "refactor: clean bookings",
        )
        receipts_dir = self.repo_path / ".edge" / "receipts" / "refactor"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        bad_receipt = self._build_valid_receipt_dict(
            "invalid-receipt",
            head_sha,
            ["src/actions/bookings.ts"],
            examiner_cid="cid-same",
            surgeon_cid="cid-same",
        )
        (receipts_dir / "invalid-receipt.json").write_text(json.dumps(bad_receipt, indent=2), encoding="utf-8")

        ok, _, err = ship_prep.prepare_ship_payload(self.repo_path, base_branch="development")
        self.assertFalse(ok, f"Invalid refactor receipt (neutrality violated) must hard-block ship_prep: {err}")

    def test_ship_prep_split_branches_assigns_refactor_commits_and_avoids_slug_collision(self) -> None:
        self._git("checkout", "-b", "feat/combined-milestone")

        # Commit 1: Spec slice 'bookings'
        self._write_and_commit(
            {
                ".edge/specs/bookings.md": (
                    "---\n"
                    "slug: bookings\n"
                    "expected_files:\n"
                    "  - src/bookings/feature.ts\n"
                    "---\n\n"
                    "# Bookings Feature Spec\n\n"
                    "Summary: Deliver bookings feature.\n"
                ),
                "src/bookings/feature.ts": "export const bookingFeature = true;\n",
            },
            "feat(bookings): deliver bookings feature [TICK-FEAT-BOOKINGS]",
        )

        # Commit 2: Refactor slice ALSO slugged 'bookings' -> collision!
        commit2_sha = self._write_and_commit(
            {
                "src/actions/bookings.ts": "export async function cleanBookings() { return []; }\n",
            },
            "refactor: extract bookings repo\n\nTicket: TICK-CORE-BOOKINGS",
        )

        receipts_dir = self.repo_path / ".edge" / "receipts" / "refactor"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        ref_receipt = self._build_valid_receipt_dict(
            "bookings",
            commit2_sha,
            ["src/actions/bookings.ts"],
            ticket_id="TICK-CORE-BOOKINGS",
        )
        (receipts_dir / "bookings.json").write_text(json.dumps(ref_receipt, indent=2), encoding="utf-8")

        ok, res, err = ship_prep.prepare_ship_payload(
            self.repo_path,
            base_branch="development",
            split_branches=True,
        )
        self.assertTrue(ok, f"prepare_ship_payload(split_branches=True) failed: {err}")

        spec_plans = [p for p in res.spec_plans if p.kind == "spec"]
        ref_plans = [p for p in res.spec_plans if p.kind == "refactor"]
        self.assertEqual(len(spec_plans), 1)
        self.assertEqual(len(ref_plans), 1)
        self.assertEqual(spec_plans[0].pr_branch, "ship/bookings")
        self.assertEqual(ref_plans[0].pr_branch, "ship/refactor-bookings")
        self.assertIn("ship/bookings", res.split_branches_created)
        self.assertIn("ship/refactor-bookings", res.split_branches_created)
        self.assertIn(commit2_sha, ref_plans[0].commit_shas)

        # Verify ship/refactor-bookings branch contains Commit 2's file and NOT Commit 1's spec file
        ref_files = self._git("diff", "--name-only", "development..ship/refactor-bookings").splitlines()
        self.assertIn("src/actions/bookings.ts", ref_files)
        self.assertNotIn("src/bookings/feature.ts", ref_files)


# =============================================================================
# AC-7: BrigadeFSM._finish_slice_via_pr Hardening & AWAITING_MERGE
# =============================================================================
class TestAC7FinishSliceViaPrHardeningAndAwaitingMerge(_HermeticBrigadeGitTestCase):
    def _setup_core_staging_slice(
        self,
        *,
        slug: str = "bookings-clean",
        files: Optional[Dict[str, str]] = None,
        state: CycleState = CycleState.STAGING,
        examiner_receipt: Optional[ExaminerReceipt] = None,
        write_receipt: bool = True,
        receipt_overrides: Optional[Dict[str, Any]] = None,
        tasks_axi_id: Optional[str] = "task-99",
        surgeon_cid: Optional[str] = "cid-surgeon-1",
    ) -> Tuple[BrigadeFSM, str]:
        self._git("checkout", "-B", f"refactor/{slug}", "development")
        payload_files = files or {"src/actions/bookings.ts": "export async function ok() { return []; }\n"}
        head_sha = self._write_and_commit(payload_files, f"refactor: {slug}")

        fsm = BrigadeFSM(self.repo_path)
        fsm.state.base_branch = "development"
        fsm.state.current_state = state
        fsm.state.active_branch = f"refactor/{slug}"
        fsm.state.active_ticket = Ticket(
            ticket_id="TICK-CORE-BOOKINGS",
            track="core",
            domain="bookings",
            rule_id="RULE-ACTION-DB-LEAK",
            severity="CRITICAL",
            target_file=list(payload_files.keys())[0],
            line_number=1,
            fingerprint="fp-bookings",
            description="Clean bookings action",
            suggested_fix="Extract repo",
            branch_name=f"refactor/{slug}",
            metric_targets={"db_leaks": 0, "max_cc": 10},
            before_metrics={"db_leaks": 2, "max_cc": 12, "sloc": 50},
            tasks_axi_id=tasks_axi_id,
            surgeon_cid=surgeon_cid,
        )
        fsm.state.examiner_receipt = examiner_receipt
        fsm.save()

        if write_receipt:
            receipts_dir = self.repo_path / ".edge" / "receipts" / "refactor"
            receipts_dir.mkdir(parents=True, exist_ok=True)
            rec = self._build_valid_receipt_dict(
                slug,
                head_sha,
                list(payload_files.keys()),
                surgeon_cid=surgeon_cid,
                examiner_cid=examiner_receipt.examiner_cid if examiner_receipt else "cid-examiner-2",
                tasks_axi_id=tasks_axi_id,
                **(receipt_overrides or {}),
            )
            (receipts_dir / f"{slug}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return fsm, head_sha

    def _run_with_mocked_gh_and_tasks(
        self,
        *,
        push_code: int = 0,
        pr_create_url: str = "https://github.com/org/repo/pull/99",
        pr_merge_code: int = 0,
        pr_view_state: str = "OPEN",
    ):
        recorded: Dict[str, List[List[str]]] = {"git_push": [], "gh": [], "tasks_axi": []}

        def fake_subprocess_run(cmd, *args, **kwargs):
            cmd_list = [str(c) for c in cmd] if isinstance(cmd, (list, tuple)) else str(cmd).split()
            if cmd_list[:2] == ["git", "push"]:
                recorded["git_push"].append(cmd_list)
                return subprocess.CompletedProcess(cmd, push_code, stdout="" if push_code == 0 else "", stderr="push rejected" if push_code else "")
            if cmd_list and Path(cmd_list[0]).name == "gh":
                recorded["gh"].append(cmd_list)
                if "create" in cmd_list:
                    return subprocess.CompletedProcess(cmd, 0, stdout=f"{pr_create_url}\n", stderr="")
                if "merge" in cmd_list:
                    return subprocess.CompletedProcess(
                        cmd,
                        pr_merge_code,
                        stdout="auto-merge enabled\n" if pr_merge_code == 0 else "",
                        stderr="merge blocked" if pr_merge_code else "",
                    )
                if "view" in cmd_list:
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout=json.dumps({"state": pr_view_state, "url": pr_create_url}),
                        stderr="",
                    )
            if cmd_list and Path(cmd_list[0]).name == "tasks-axi":
                recorded["tasks_axi"].append(cmd_list)
                return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}\n', stderr="")
            if cmd_list and Path(cmd_list[0]).name == "treehouse":
                return subprocess.CompletedProcess(cmd, 0, stdout="returned", stderr="")
            return _ORIG_SUBPROCESS_RUN(cmd, *args, **kwargs)

        return recorded, fake_subprocess_run

    def test_finish_slice_via_pr_core_blocks_when_not_staging_or_missing_examiner_or_bad_receipt(self) -> None:
        # 1. Not in STAGING
        fsm_rev, _ = self._setup_core_staging_slice(
            slug="not-staging",
            state=CycleState.REVIEW,
            examiner_receipt=ExaminerReceipt(verdict="PASS", summary="ok", ticket_id="TICK-CORE-BOOKINGS", examiner_cid="cid-e"),
        )
        recorded, fake_run = self._run_with_mocked_gh_and_tasks()
        with patch("subprocess.run", side_effect=fake_run):
            ok_rev, msg_rev = fsm_rev.finish_slice(open_pr=True)
        self.assertFalse(ok_rev, f"core track outside STAGING must block finish_slice(open_pr=True): {msg_rev}")
        self.assertEqual(recorded["git_push"], [])
        self.assertEqual(recorded["gh"], [])

        # 2. Missing ExaminerReceipt in STAGING
        fsm_no_ex, _ = self._setup_core_staging_slice(
            slug="no-examiner",
            state=CycleState.STAGING,
            examiner_receipt=None,
        )
        recorded2, fake_run2 = self._run_with_mocked_gh_and_tasks()
        with patch("subprocess.run", side_effect=fake_run2):
            ok_ex, msg_ex = fsm_no_ex.finish_slice(open_pr=True)
        self.assertFalse(ok_ex, f"core track without ExaminerReceipt PASS must block: {msg_ex}")
        self.assertEqual(recorded2["gh"], [])

        # 3. Missing RefactorReceipt in STAGING
        fsm_no_rr, _ = self._setup_core_staging_slice(
            slug="no-receipt",
            state=CycleState.STAGING,
            examiner_receipt=ExaminerReceipt(verdict="PASS", summary="ok", ticket_id="TICK-CORE-BOOKINGS", examiner_cid="cid-e"),
            write_receipt=False,
        )
        recorded3, fake_run3 = self._run_with_mocked_gh_and_tasks()
        with patch("subprocess.run", side_effect=fake_run3):
            ok_rr, msg_rr = fsm_no_rr.finish_slice(open_pr=True)
        self.assertFalse(ok_rr, f"core track without valid RefactorReceipt must block: {msg_rr}")
        self.assertEqual(recorded3["gh"], [])

    def test_finish_slice_via_pr_aborts_cleanly_on_prepare_ship_push_or_merge_failures(self) -> None:
        # Subcase A: prepare_ship_payload fails -> aborts without pushing or creating PR
        fsm_a, _ = self._setup_core_staging_slice(
            slug="fail-ship",
            examiner_receipt=ExaminerReceipt(verdict="PASS", summary="ok", ticket_id="TICK-CORE-BOOKINGS", examiner_cid="cid-e"),
        )
        recorded_a, fake_run_a = self._run_with_mocked_gh_and_tasks()
        with (
            patch("tools.brigade.ship_prep.prepare_ship_payload", return_value=(False, ship_prep._empty_result("development"), "Simulated ship_prep failure")),
            patch("subprocess.run", side_effect=fake_run_a),
        ):
            ok_a, msg_a = fsm_a.finish_slice(open_pr=True)
        self.assertFalse(ok_a, msg_a)
        self.assertEqual(recorded_a["git_push"], [])
        self.assertEqual(recorded_a["gh"], [])

        # Subcase B: git push fails -> aborts without creating PR or resetting FSM
        recorded_b, fake_run_b = self._run_with_mocked_gh_and_tasks(push_code=1)
        with patch("subprocess.run", side_effect=fake_run_b):
            ok_b, msg_b = fsm_a.finish_slice(open_pr=True)
        self.assertFalse(ok_b, msg_b)
        self.assertEqual(recorded_b["gh"], [])
        self.assertEqual(fsm_a.state.current_state, CycleState.STAGING)

        # Subcase C: gh pr merge fails -> aborts without calling tasks-axi done or resetting FSM
        recorded_c, fake_run_c = self._run_with_mocked_gh_and_tasks(pr_merge_code=1)
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run_c),
        ):
            ok_c, msg_c = fsm_a.finish_slice(open_pr=True, auto_merge_two_way=True)
        self.assertFalse(ok_c, msg_c)
        self.assertEqual(recorded_c["tasks_axi"], [])
        self.assertNotEqual(fsm_a.state.current_state, CycleState.IDLE)

    def test_finish_slice_via_pr_queued_auto_merge_enters_awaiting_merge_then_confirm_merge_completes(self) -> None:
        fsm, _ = self._setup_core_staging_slice(
            slug="queued-auto",
            examiner_receipt=ExaminerReceipt(verdict="PASS", summary="ok", ticket_id="TICK-CORE-BOOKINGS", examiner_cid="cid-e"),
            tasks_axi_id="task-99",
        )
        recorded, fake_run = self._run_with_mocked_gh_and_tasks(
            pr_create_url="https://github.com/org/repo/pull/99",
            pr_view_state="OPEN",
        )
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok, msg = fsm.finish_slice(open_pr=True, auto_merge_two_way=True)

        self.assertTrue(ok, msg)
        self.assertEqual(fsm.state.current_state, CycleState.AWAITING_MERGE)
        self.assertIsNotNone(fsm.state.active_ticket)
        self.assertEqual(fsm.state.active_ticket.pr_url, "https://github.com/org/repo/pull/99")
        self.assertEqual(recorded["tasks_axi"], [], "Must NOT call tasks-axi done while PR is still OPEN (auto-merge queued)")

        # While still OPEN, confirm_merge returns False and keeps AWAITING_MERGE
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok_still_open, _ = fsm.confirm_merge()
        self.assertFalse(ok_still_open)
        self.assertEqual(fsm.state.current_state, CycleState.AWAITING_MERGE)
        self.assertEqual(recorded["tasks_axi"], [])

        # Once PR is MERGED, brigade confirm-merge completes linked task and resets FSM to IDLE
        recorded_m, fake_run_m = self._run_with_mocked_gh_and_tasks(
            pr_create_url="https://github.com/org/repo/pull/99",
            pr_view_state="MERGED",
        )
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run_m),
            patch.object(sys, "argv", ["brigade", "confirm-merge", str(self.repo_path)]),
            redirect_stdout(io.StringIO()),
        ):
            rc = brigade_cli.main()

        self.assertEqual(rc, 0)
        self.assertTrue(
            any("done" in c and "task-99" in c and "https://github.com/org/repo/pull/99" in c for c in recorded_m["tasks_axi"]),
            f"Expected tasks-axi done task-99 --pr ..., got: {recorded_m['tasks_axi']}",
        )
        reloaded = BrigadeFSM(self.repo_path)
        self.assertEqual(reloaded.state.current_state, CycleState.IDLE)
        self.assertIsNone(reloaded.state.active_ticket)

    def test_finish_slice_via_pr_immediate_merge_completes_tasks_axi_and_resets(self) -> None:
        fsm, _ = self._setup_core_staging_slice(
            slug="immediate-merge",
            examiner_receipt=ExaminerReceipt(verdict="PASS", summary="ok", ticket_id="TICK-CORE-BOOKINGS", examiner_cid="cid-e"),
            tasks_axi_id="task-100",
        )
        recorded, fake_run = self._run_with_mocked_gh_and_tasks(
            pr_create_url="https://github.com/org/repo/pull/100",
            pr_view_state="MERGED",
        )
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok, msg = fsm.finish_slice(open_pr=True, auto_merge_two_way=True)

        self.assertTrue(ok, msg)
        self.assertEqual(fsm.state.current_state, CycleState.IDLE)
        self.assertIsNone(fsm.state.active_ticket)
        self.assertTrue(
            any("done" in c and "task-100" in c and "https://github.com/org/repo/pull/100" in c for c in recorded["tasks_axi"]),
            f"Expected tasks-axi done on confirmed merge, got: {recorded['tasks_axi']}",
        )

    def test_finish_slice_via_pr_one_way_door_holds_open_with_reasons_and_never_merges(self) -> None:
        fsm, _ = self._setup_core_staging_slice(
            slug="auth-refactor",
            files={"src/auth/login.ts": "export async function login() { return true; }\n"},
            examiner_receipt=ExaminerReceipt(verdict="PASS", summary="ok", ticket_id="TICK-CORE-BOOKINGS", examiner_cid="cid-e"),
            receipt_overrides={
                "door_type": "One-way door (Security/Auth Path Touched)",
                "one_way_reasons": ["Security/auth path touched: src/auth/login.ts"],
            },
            tasks_axi_id="task-101",
        )
        recorded, fake_run = self._run_with_mocked_gh_and_tasks(
            pr_create_url="https://github.com/org/repo/pull/101",
        )
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok, msg = fsm.finish_slice(open_pr=True, auto_merge_two_way=True)

        self.assertTrue(ok, msg)
        create_calls = [c for c in recorded["gh"] if "create" in c]
        merge_calls = [c for c in recorded["gh"] if "merge" in c]
        self.assertEqual(len(create_calls), 1)
        self.assertEqual(len(merge_calls), 0, "One-Way Door must NEVER invoke gh pr merge")
        self.assertEqual(recorded["tasks_axi"], [], "One-Way Door must NOT mark tasks-axi done")
        self.assertIn("[ONE-WAY DOOR]", " ".join(create_calls[0]).upper())
        self.assertIn("src/auth/login.ts", msg)

    def test_finish_slice_via_pr_diffs_leased_worktree_while_loading_receipt_from_target_repo(self) -> None:
        # target_repo remains on 'development', while worktree has the committed refactor branch!
        self._write_and_commit(
            {"src/actions/bookings.ts": "export async function run() { return db.select().from(bookings); }\n"},
            "chore: base leaky action",
        )
        wt_path = self._create_worktree("refactor/wt-slice", name="wt-ac7")
        head_sha = self._write_and_commit(
            {
                "src/lib/bookings/repository.ts": "export async function fetchBookings() { return []; }\n",
                "src/actions/bookings.ts": "import { fetchBookings } from '../lib/bookings/repository';\nexport async function run() { return fetchBookings(); }\n",
            },
            "refactor: extract repo in worktree",
            cwd=wt_path,
        )

        # Receipt lives ONLY under target_repo/.edge/receipts/refactor/ (never in wt_path/.edge/)
        receipts_dir = self.repo_path / ".edge" / "receipts" / "refactor"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        rec = self._build_valid_receipt_dict(
            "wt-slice",
            head_sha,
            ["src/actions/bookings.ts", "src/lib/bookings/repository.ts"],
            before={"db_leaks": 1, "max_cc": 6, "dryer_clones": 0, "type_score": 85, "sloc": 40},
            after={"db_leaks": 0, "max_cc": 3, "dryer_clones": 0, "type_score": 100, "sloc": 32},
            tasks_axi_id="task-wt",
        )
        (receipts_dir / "wt-slice.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")

        fsm = BrigadeFSM(self.repo_path)
        fsm.state.base_branch = "development"
        fsm.state.current_state = CycleState.STAGING
        fsm.state.active_branch = "refactor/wt-slice"
        fsm.state.active_worktree = str(wt_path)
        fsm.state.active_ticket = Ticket(
            ticket_id="TICK-CORE-BOOKINGS",
            track="core",
            domain="bookings",
            rule_id="RULE-ACTION-DB-LEAK",
            severity="CRITICAL",
            target_file="src/actions/bookings.ts",
            line_number=1,
            fingerprint="fp-wt",
            description="Extract repo in worktree",
            suggested_fix="Extract",
            branch_name="refactor/wt-slice",
            worktree_path=str(wt_path),
            metric_targets={"db_leaks": 0, "max_cc": 10},
            before_metrics={"db_leaks": 1, "max_cc": 6, "sloc": 40},
            tasks_axi_id="task-wt",
            surgeon_cid="cid-surgeon-1",
        )
        fsm.state.examiner_receipt = ExaminerReceipt(
            verdict="PASS",
            summary="Worktree slice clean",
            ticket_id="TICK-CORE-BOOKINGS",
            examiner_cid="cid-examiner-2",
        )
        fsm.save()

        recorded, fake_run = self._run_with_mocked_gh_and_tasks(
            pr_create_url="https://github.com/org/repo/pull/102",
            pr_view_state="MERGED",
        )
        with (
            patch("shutil.which", return_value="/usr/local/bin/tasks-axi"),
            patch("subprocess.run", side_effect=fake_run),
        ):
            ok, msg = fsm.finish_slice(open_pr=True, auto_merge_two_way=True)

        self.assertTrue(ok, msg)
        create_calls = [c for c in recorded["gh"] if "create" in c]
        self.assertEqual(len(create_calls), 1)
        body_idx = create_calls[0].index("--body") + 1
        pr_body = create_calls[0][body_idx]
        self.assertIn(".edge/receipts/refactor/wt-slice.json", pr_body)
        self.assertIn("db_leaks", pr_body)


if __name__ == "__main__":
    unittest.main()
