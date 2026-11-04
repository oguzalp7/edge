#!/usr/bin/env python3
"""
Unit Tests for edge-distill v2: Zero-Token Harvester, State Watermark & Candidate Pool.
Tests v2 models, TOON serialization, zero-token transcript graph harvesting,
state watermark tracking, LexicalStackGate, CandidatePool incubation/promotion,
and modern CLI interfaces. Preserves TestSessionMiner.
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

# Retain legacy models for backward compatibility tests
from tools.distill.models import (
    RescueLoop,
    NegativeConstraint,
    DiffPattern,
    DistillReport,
)
from tools.distill.session_miner import SessionMiner, INTENT_DEFINITIONS, extract_project_from_path
from tools.distill.cli import main as distill_main
from tools.brigade.cli import main as brigade_main


class TestLegacyDistillRetirement(unittest.TestCase):
    def setUp(self):
        self.tools_distill = Path(__file__).resolve().parents[1] / "tools" / "distill"

    def test_legacy_files_deleted(self):
        """Spec Refinement 1: journal.py, generator.py, and miner.py must be deleted in v2."""
        journal_file = self.tools_distill / "journal.py"
        generator_file = self.tools_distill / "generator.py"
        miner_file = self.tools_distill / "miner.py"
        self.assertFalse(journal_file.exists(), f"{journal_file} should be deleted in Distill v2")
        self.assertFalse(generator_file.exists(), f"{generator_file} should be deleted in Distill v2")
        self.assertFalse(miner_file.exists(), f"{miner_file} should be deleted in Distill v2")


class TestDistillV2ModelsAndToon(unittest.TestCase):
    def test_station_escape_signal_serialization_and_toon(self):
        from tools.distill.models import StationEscapeSignal

        sig = StationEscapeSignal(
            signal_id="SIG-ESC-001",
            station_role="EXAMINER",
            escape_type="ESCAPED_DEFECT",
            description="Examiner passed code that failed verification gate",
            evidence="gate.py returned exit code 1 due to type error",
            timestamp="2026-11-04T00:00:00Z",
            conversation_id="cid-parent-12345678",
            step_index=14,
            ticket_id="TICK-101",
            metadata={"gate_code": 1},
        )
        d = sig.to_dict()
        self.assertEqual(d["signal_id"], "SIG-ESC-001")
        self.assertEqual(d["station_role"], "EXAMINER")
        self.assertEqual(d["escape_type"], "ESCAPED_DEFECT")
        self.assertEqual(d["step_index"], 14)

        restored = StationEscapeSignal.from_dict(d)
        self.assertEqual(restored.signal_id, "SIG-ESC-001")
        self.assertEqual(restored.station_role, "EXAMINER")
        self.assertEqual(restored.metadata, {"gate_code": 1})

        toon = sig.to_toon()
        self.assertIn("[ESCAPE:EXAMINER]", toon)
        self.assertIn("ESCAPED_DEFECT", toon)
        self.assertIn("step 14", toon)
        self.assertIn("cid-pare", toon)

    def test_tool_friction_signal_serialization_and_toon(self):
        from tools.distill.models import ToolFrictionSignal

        tf = ToolFrictionSignal(
            signal_id="SIG-TOOL-001",
            tool_name="run_command",
            command_or_args="git checkout -b feat/checkout-fix",
            error_output="fatal: a branch named 'feat/checkout-fix' already exists",
            conversation_id="cid-subagent-999",
            step_index=5,
            timestamp="2026-11-04T00:01:00Z",
            exit_code=128,
            error_type="COMMAND_FAILURE",
            retry_count=2,
        )
        d = tf.to_dict()
        self.assertEqual(d["signal_id"], "SIG-TOOL-001")
        self.assertEqual(d["tool_name"], "run_command")
        self.assertEqual(d["exit_code"], 128)
        self.assertEqual(d["retry_count"], 2)

        restored = ToolFrictionSignal.from_dict(d)
        self.assertEqual(restored.signal_id, "SIG-TOOL-001")
        self.assertEqual(restored.error_output, tf.error_output)

        toon = tf.to_toon()
        self.assertIn("[TOOL:run_command]", toon)
        self.assertIn("exit=128", toon)
        self.assertIn("retries=2", toon)
        self.assertIn("git checkout", toon)

    def test_repeated_escalation_serialization_and_toon(self):
        from tools.distill.models import RepeatedEscalation

        esc = RepeatedEscalation(
            escalation_id="ESC-001",
            category="USER_INSTRUCTION_REPETITION",
            pattern_key="do not touch tests",
            occurrence_count=3,
            occurrences=[
                {"conversation_id": "cid-1", "step_index": 2, "text": "Don't touch tests", "timestamp": "2026-11-04T00:02:00Z"},
                {"conversation_id": "cid-2", "step_index": 4, "text": "Testi bozma", "timestamp": "2026-11-04T00:05:00Z"},
                {"conversation_id": "cid-3", "step_index": 1, "text": "Never loosen or delete tests", "timestamp": "2026-11-04T00:10:00Z"},
            ],
            rule_recommendation="Test Immutability Invariant: NEVER modify existing tests created by Seam Architect",
            target_role="coder",
        )
        d = esc.to_dict()
        self.assertEqual(d["escalation_id"], "ESC-001")
        self.assertEqual(d["occurrence_count"], 3)
        self.assertEqual(d["target_role"], "coder")

        restored = RepeatedEscalation.from_dict(d)
        self.assertEqual(restored.escalation_id, "ESC-001")
        self.assertEqual(len(restored.occurrences), 3)

        toon = esc.to_toon()
        self.assertIn("[ESCALATION:USER_INSTRUCTION_REPETITION]", toon)
        self.assertIn("count=3", toon)
        self.assertIn("target=coder", toon)
        self.assertIn("Test Immutability Invariant", toon)

    def test_candidate_rule_serialization_and_toon(self):
        from tools.distill.models import CandidateRule

        cand = CandidateRule(
            candidate_id="CAND-abcd1234",
            fingerprint="hash1234567890",
            rule_text="Always run characterization tests before surgery",
            target_role="surgeon",
            scope_class="PLUGIN_CANDIDATE",
            stack_tokens_matched=[],
            first_seen_at="2026-11-01T00:00:00Z",
            last_seen_at="2026-11-04T00:00:00Z",
            source_projects=["/home/oguz/repo-a", "/home/oguz/repo-b"],
            occurrence_count=2,
            status="READY_FOR_PROMOTION",
            evidence=[{"cid": "cid-1", "reason": "repeated surgery failures"}],
        )
        d = cand.to_dict()
        self.assertEqual(d["candidate_id"], "CAND-abcd1234")
        self.assertEqual(d["status"], "READY_FOR_PROMOTION")
        self.assertEqual(len(d["source_projects"]), 2)

        restored = CandidateRule.from_dict(d)
        self.assertEqual(restored.candidate_id, "CAND-abcd1234")
        self.assertEqual(restored.scope_class, "PLUGIN_CANDIDATE")

        toon = cand.to_toon()
        self.assertIn("[CANDIDATE:CAND-abcd1234]", toon)
        self.assertIn("role=surgeon", toon)
        self.assertIn("status=READY_FOR_PROMOTION", toon)
        self.assertIn("projects=2", toon)

    def test_watermark_state_serialization(self):
        from tools.distill.models import DistillWatermarkState

        state = DistillWatermarkState(
            version="2.0",
            last_harvested_at="2026-11-04T00:00:00Z",
            processed_sessions=["cid-1", "cid-2"],
            project_sessions={"repo-a": ["cid-1"], "repo-b": ["cid-2"]},
            metrics={"total_harvested": 2},
        )
        d = state.to_dict()
        self.assertEqual(d["version"], "2.0")
        self.assertEqual(d["processed_sessions"], ["cid-1", "cid-2"])

        restored = DistillWatermarkState.from_dict(d)
        self.assertEqual(restored.processed_sessions, ["cid-1", "cid-2"])
        self.assertEqual(restored.metrics["total_harvested"], 2)

    def test_friction_digest_serialization_and_toon_budget_cap(self):
        from tools.distill.models import (
            FrictionDigest,
            StationEscapeSignal,
            ToolFrictionSignal,
            RepeatedEscalation,
        )

        escapes = [
            StationEscapeSignal(
                signal_id=f"ESC-{i}",
                station_role="SURGEON" if i % 2 == 0 else "EXAMINER",
                escape_type="REVIEW_POLISH_BOUNCE" if i % 2 == 0 else "ESCAPED_DEFECT",
                description=f"Detailed escape description number {i} with extensive diagnostic notes and traces",
                evidence=f"Stack trace evidence snippet {i} " * 10,
                timestamp="2026-11-04T00:00:00Z",
                conversation_id=f"cid-esc-{i}",
                step_index=i,
            )
            for i in range(25)
        ]

        tool_frictions = [
            ToolFrictionSignal(
                signal_id=f"TOOL-{i}",
                tool_name="run_command",
                command_or_args="git checkout -b feat/branch",
                error_output=f"fatal: branch feat/branch already exists (occurrence {i})",
                conversation_id=f"cid-tool-{i % 5}",
                step_index=i,
                timestamp="2026-11-04T00:00:00Z",
                exit_code=128,
            )
            for i in range(60)
        ]

        escalations = [
            RepeatedEscalation(
                escalation_id=f"REP-{i}",
                category="USER_INSTRUCTION_REPETITION",
                pattern_key=f"Critical repeated directive {i}",
                occurrence_count=i + 2,
                occurrences=[{"cid": f"cid-{i}", "step_index": 1, "text": f"Instruction {i}"}],
                rule_recommendation=f"Rule recommendation text for directive {i}",
                target_role="coder",
            )
            for i in range(6)
        ]

        digest = FrictionDigest(
            digest_id="DIGEST-TEST-001",
            project_path="/home/oguz/my-app",
            project_name="my-app",
            generated_at="2026-11-04T00:00:00Z",
            sessions_analyzed=["cid-1", "cid-2", "cid-3"],
            station_escapes=escapes,
            tool_frictions=tool_frictions,
            repeated_escalations=escalations,
            flight_recorder_insights=[{"dead_end": f"dead end {i}", "severity": "HIGH"} for i in range(15)],
            git_churn=[{"commit": "abc1234", "message": "revert previous change"}],
            critique_findings=[{"spec": "slice.md", "finding": "missing edge case"}],
        )

        d = digest.to_dict()
        self.assertEqual(d["digest_id"], "DIGEST-TEST-001")
        self.assertEqual(len(d["station_escapes"]), 25)
        self.assertEqual(len(d["tool_frictions"]), 60)
        self.assertEqual(len(d["repeated_escalations"]), 6)

        restored = FrictionDigest.from_dict(d)
        self.assertEqual(restored.digest_id, "DIGEST-TEST-001")
        self.assertEqual(len(restored.station_escapes), 25)

        # TOON token cap check: <= 8000 characters (~2000 tokens)
        toon = digest.to_toon(max_tokens=2000)
        self.assertIsInstance(toon, str)
        self.assertLessEqual(len(toon), 8000, f"TOON output length ({len(toon)}) exceeded 8,000 char budget!")
        self.assertLessEqual(len(toon) // 4, 2000, "Estimated token count exceeded 2,000 tokens!")

        # Truncation priority invariant:
        # 1. Repeated escalations must ALL be preserved
        for esc in escalations:
            self.assertIn(esc.pattern_key, toon, f"Missing repeated escalation in TOON: {esc.pattern_key}")

        # 2. Duplicate tool frictions must be collapsed/aggregated
        self.assertIn("git checkout", toon)


class TestTranscriptGraphHarvester(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_harvester_")
        self.brain_root = Path(self.temp_dir) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(self.temp_dir) / "project_alpha"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.active_stations_file = Path(self.temp_dir) / "edge_active_stations.json"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session(self, conv_id: str, steps: List[Dict[str, Any]]) -> Path:
        sess_dir = self.brain_root / conv_id / ".system_generated" / "logs"
        sess_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = sess_dir / "transcript.jsonl"
        with open(transcript_path, "w", encoding="utf-8") as f:
            for s in steps:
                f.write(json.dumps(s) + "\n")
        return transcript_path

    def test_parent_child_session_graph_reconstruction(self):
        """
        Tests multi-tool turn pairing resilience (Spec Refinement 2):
        Parallel invoke_subagent calls in a single PLANNER_RESPONSE paired sequentially
        with subsequent result steps and child Step 0 sender=<parent_cid>.
        """
        from tools.distill.harvester import TranscriptGraphHarvester

        parent_cid = "parent-session-100"
        child_cid_1 = "child-session-surgeon-101"
        child_cid_2 = "child-session-critic-102"

        # Parent transcript with parallel invoke_subagent calls
        parent_steps = [
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-11-04T00:00:00Z",
                "content": "Start surgery on billing module",
                "workspaceUris": [f"file://{self.repo_dir.as_posix()}"],
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-04T00:01:00Z",
                "tool_calls": [
                    {"name": "invoke_subagent", "args": {"TypeName": "surgeon", "Role": "Surgeon Specialist"}},
                    {"name": "invoke_subagent", "args": {"TypeName": "spec_critic", "Role": "Spec Critic Auditor"}},
                ],
            },
            {
                "step_index": 2,
                "source": "GENERIC",
                "type": "TOOL_RESULT",
                "created_at": "2026-11-04T00:01:05Z",
                "content": f'Created the following subagent:\n{{"conversationId": "{child_cid_1}"}}',
            },
            {
                "step_index": 3,
                "source": "GENERIC",
                "type": "TOOL_RESULT",
                "created_at": "2026-11-04T00:01:10Z",
                "content": f'Created the following subagent:\n{{"conversationId": "{child_cid_2}"}}',
            },
        ]
        self._create_session(parent_cid, parent_steps)

        # Child 1: Surgeon subagent
        child_1_steps = [
            {
                "step_index": 0,
                "source": "SYSTEM",
                "type": "SYSTEM_MESSAGE",
                "created_at": "2026-11-04T00:01:15Z",
                "content": f"[Message] timestamp=2026-11-04T00:01:15Z sender={parent_cid} priority=HIGH content=Execute surgery",
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-04T00:02:00Z",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "git diff"}}],
            },
            {
                "step_index": 2,
                "source": "GENERIC",
                "type": "TOOL_RESULT",
                "created_at": "2026-11-04T00:02:05Z",
                "content": "fatal: not a git repository",
            },
        ]
        self._create_session(child_cid_1, child_1_steps)

        stations_data = {
            "stations": {
                child_cid_1: {"role": "SURGEON", "parentConversationId": parent_cid},
                child_cid_2: {"role": "SPEC_CRITIC", "parentConversationId": parent_cid},
            }
        }
        self.active_stations_file.write_text(json.dumps(stations_data), encoding="utf-8")

        harvester = TranscriptGraphHarvester(
            brain_roots=[self.brain_root],
            active_stations_file=self.active_stations_file,
            repo_path=self.repo_dir,
        )
        digest = harvester.harvest(project_path=self.repo_dir)

        self.assertIn(parent_cid, digest.sessions_analyzed)
        self.assertIn(child_cid_1, digest.sessions_analyzed)
        self.assertTrue(len(digest.tool_frictions) > 0)
        self.assertTrue(any(f.conversation_id == child_cid_1 for f in digest.tool_frictions))

    def test_autonomous_single_session_harvesting(self):
        """Free-form session without subagents extracts friction and escalations cleanly."""
        from tools.distill.harvester import TranscriptGraphHarvester

        free_cid = "freeform-session-001"
        steps = [
            {
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-11-04T00:00:00Z",
                "content": "Refactor the payment controller",
                "workspaceUris": [f"file://{self.repo_dir.as_posix()}"],
            },
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "created_at": "2026-11-04T00:01:00Z",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "npm test"}}],
            },
            {
                "step_index": 2,
                "source": "GENERIC",
                "type": "TOOL_RESULT",
                "created_at": "2026-11-04T00:01:05Z",
                "content": "FAIL src/payment.test.ts\nCommand failed with exit code 1",
            },
            {
                "step_index": 3,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "created_at": "2026-11-04T00:02:00Z",
                "content": "Hayır öyle değil, testi bozma!",
            },
        ]
        self._create_session(free_cid, steps)

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        digest = harvester.harvest(project_path=self.repo_dir)

        self.assertIn(free_cid, digest.sessions_analyzed)
        self.assertTrue(len(digest.tool_frictions) > 0)
        self.assertTrue(any("npm test" in f.command_or_args for f in digest.tool_frictions))

    def test_watermark_filtering_and_reprocess(self):
        from tools.distill.harvester import TranscriptGraphHarvester
        from tools.distill.models import DistillWatermarkState

        self._create_session("sess-wm-1", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])
        self._create_session("sess-wm-2", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])
        self._create_session("sess-wm-3", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])

        watermark = DistillWatermarkState(processed_sessions=["sess-wm-1"])

        harvester = TranscriptGraphHarvester(
            brain_roots=[self.brain_root],
            repo_path=self.repo_dir,
            watermark_state=watermark,
        )

        # 1. Normal harvest skips sess-wm-1
        digest = harvester.harvest(project_path=self.repo_dir, reprocess=False)
        self.assertNotIn("sess-wm-1", digest.sessions_analyzed)
        self.assertIn("sess-wm-2", digest.sessions_analyzed)
        self.assertIn("sess-wm-3", digest.sessions_analyzed)

        # 2. reprocess=True analyzes all
        digest_reprocess = harvester.harvest(project_path=self.repo_dir, reprocess=True)
        self.assertIn("sess-wm-1", digest_reprocess.sessions_analyzed)

        # 3. current_session_id forces inclusion of that session even if processed
        digest_single = harvester.harvest(project_path=self.repo_dir, current_session_id="sess-wm-1")
        self.assertIn("sess-wm-1", digest_single.sessions_analyzed)

    def test_downstream_station_escapes_extraction(self):
        """Tests extraction of EXAMINER ESCAPED_DEFECT, SPEC_WRITER SPEC_AMBIGUITY, and MEAT_PROXY."""
        from tools.distill.harvester import TranscriptGraphHarvester

        cid = "sess-escapes-001"
        steps = [
            {"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]},
            # Examiner passes code
            {"step_index": 1, "source": "MODEL", "content": "EXAMINER REVIEW: PASS\nAll standards adhered to."},
            # Immediate gate failure follows
            {"step_index": 2, "source": "MODEL", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "python gate.py"}}]},
            {"step_index": 3, "source": "GENERIC", "content": "gate.py: FAILED with exit code 1 (uncontained data leak)"},
            # Meat-proxy handoff: user pasting terminal output 3 times
            {"step_index": 4, "source": "USER_EXPLICIT", "content": "Here is the terminal error:\nTraceback (most recent call last):\nFile 'app.py', line 10"},
            {"step_index": 5, "source": "USER_EXPLICIT", "content": "Here is the second output:\nError TS2322 in types.ts"},
            {"step_index": 6, "source": "USER_EXPLICIT", "content": "Here is the third output:\nFAIL test_core.py"},
        ]
        self._create_session(cid, steps)

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        digest = harvester.harvest(project_path=self.repo_dir)

        escape_types = [e.escape_type for e in digest.station_escapes]
        self.assertIn("ESCAPED_DEFECT", escape_types)
        self.assertIn("MEAT_PROXY", escape_types)

    def test_repeated_user_escalations_extraction(self):
        """User repeating corrective directives across steps/sessions generates RepeatedEscalation."""
        from tools.distill.harvester import TranscriptGraphHarvester

        self._create_session("sess-rep-1", [
            {"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]},
            {"step_index": 1, "source": "USER_EXPLICIT", "content": "testi bozma, kırmızı testi geçecek kod yaz"},
        ])

        self._create_session("sess-rep-2", [
            {"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]},
            {"step_index": 1, "source": "USER_EXPLICIT", "content": "sana testi bozma dedim, assertionları silme"},
        ])

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        digest = harvester.harvest(project_path=self.repo_dir)

        self.assertTrue(len(digest.repeated_escalations) > 0)
        top_escalation = digest.repeated_escalations[0]
        self.assertGreaterEqual(top_escalation.occurrence_count, 2)
        self.assertEqual(top_escalation.target_role, "coder")

    def test_flight_recorder_and_critique_extraction(self):
        from tools.distill.harvester import TranscriptGraphHarvester

        fr_dir = self.repo_dir / ".edge" / "flight-recorder"
        fr_dir.mkdir(parents=True, exist_ok=True)
        fr_json = fr_dir / "TICK-001.json"
        fr_json.write_text(json.dumps({
            "ticket_id": "TICK-001",
            "dead_ends": [{"approach": "Raw DB query in action", "reason": "Deadlock"}],
            "guard_failures": [{"state": "VERIFY", "message": "pytest exit 1"}],
            "review_findings": [{"axis": "standards", "description": "Missing transaction"}],
        }), encoding="utf-8")

        specs_dir = self.repo_dir / ".edge" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        (specs_dir / "slice-critique.md").write_text("# Spec Critique\nParaphrase check passed.", encoding="utf-8")

        self._create_session("sess-fr-1", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        digest = harvester.harvest(project_path=self.repo_dir)

        self.assertTrue(len(digest.flight_recorder_insights) > 0)
        self.assertTrue(len(digest.critique_findings) > 0)


class TestDistillStateAndCandidatePool(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_state_")
        self.state_file = Path(self.temp_dir) / "test_state.json"
        self.candidates_file = Path(self.temp_dir) / "test_candidates.json"
        self.plugin_root = Path(self.temp_dir) / "mock_plugin"
        (self.plugin_root / "agents").mkdir(parents=True, exist_ok=True)
        (self.plugin_root / "agents" / "surgeon.md").write_text("# Persona: Surgeon\n\nDirectives:\n1. Zero behavior change\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hermetic_storage_overrides(self):
        from tools.distill.state import DistillStateManager, CandidatePool

        manager = DistillStateManager(state_file_override=self.state_file)
        manager.mark_session_processed("session-alpha", project_path="/home/oguz/proj1")
        self.assertTrue(self.state_file.exists())
        data = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertIn("session-alpha", data["processed_sessions"])

        pool = CandidatePool(candidates_file_override=self.candidates_file)
        pool.record_candidate(
            rule_text="Always wrap transactions in db.transaction()",
            target_role="surgeon",
            project_path="/home/oguz/proj1",
        )
        self.assertTrue(self.candidates_file.exists())
        cand_data = json.loads(self.candidates_file.read_text(encoding="utf-8"))
        self.assertEqual(len(cand_data["candidates"]), 1)

    def test_lexical_stack_gate_classification(self):
        from tools.distill.state import LexicalStackGate

        cls1, tokens1 = LexicalStackGate.classify("Extract queries into Drizzle repositories")
        self.assertEqual(cls1, "REPO_LOCAL")
        self.assertIn("drizzle", tokens1)

        cls2, tokens2 = LexicalStackGate.classify("Use Tailwind utility classes instead of CSS")
        self.assertEqual(cls2, "REPO_LOCAL")
        self.assertIn("tailwind", tokens2)

        cls3, tokens3 = LexicalStackGate.classify("Move component from src/components/ to src/app/page.tsx")
        self.assertEqual(cls3, "REPO_LOCAL")
        self.assertTrue(any(".tsx" in t or "src/app/" in t for t in tokens3))

        cls4, tokens4 = LexicalStackGate.classify("Always verify characterization test passes before refactoring")
        self.assertEqual(cls4, "PLUGIN_CANDIDATE")
        self.assertEqual(tokens4, [])

    def test_lexical_stack_gate_word_boundary_safety(self):
        """
        Spec Refinement 3: Words like 'tests' (containing 'ts') or 'expresses' (containing 'express')
        must NOT trigger REPO_LOCAL classification.
        """
        from tools.distill.state import LexicalStackGate

        cls_tests, tokens_tests = LexicalStackGate.classify("Ensure unit tests verify edge-case boundaries thoroughly")
        self.assertEqual(cls_tests, "PLUGIN_CANDIDATE", f"Word 'tests' falsely triggered: {tokens_tests}")
        self.assertEqual(tokens_tests, [])

        cls_expr, tokens_expr = LexicalStackGate.classify("The specification clearly expresses the system invariants")
        self.assertEqual(cls_expr, "PLUGIN_CANDIDATE", f"Word 'expresses' falsely triggered: {tokens_expr}")
        self.assertEqual(tokens_expr, [])

    def test_candidate_pool_incubation_and_multi_project_graduation(self):
        from tools.distill.state import CandidatePool

        pool = CandidatePool(candidates_file_override=self.candidates_file)

        # 1. First project records rule -> INCUBATING
        cand = pool.record_candidate(
            rule_text="Never touch test files during surgery",
            target_role="surgeon",
            project_path="/home/oguz/repo-alpha",
        )
        self.assertEqual(cand.status, "INCUBATING")
        self.assertEqual(cand.source_projects, ["/home/oguz/repo-alpha"])
        self.assertEqual(cand.occurrence_count, 1)

        # 2. Same project records again -> remains INCUBATING, count increments
        cand2 = pool.record_candidate(
            rule_text="Never touch test files during surgery",
            target_role="surgeon",
            project_path="/home/oguz/repo-alpha",
        )
        self.assertEqual(cand2.status, "INCUBATING")
        self.assertEqual(cand2.occurrence_count, 2)
        self.assertEqual(cand2.source_projects, ["/home/oguz/repo-alpha"])

        # 3. Second distinct project records same rule -> transitions to READY_FOR_PROMOTION
        cand3 = pool.record_candidate(
            rule_text="Never touch test files during surgery",
            target_role="surgeon",
            project_path="/home/oguz/repo-beta",
        )
        self.assertEqual(cand3.status, "READY_FOR_PROMOTION")
        self.assertEqual(len(cand3.source_projects), 2)
        self.assertIn("/home/oguz/repo-alpha", cand3.source_projects)
        self.assertIn("/home/oguz/repo-beta", cand3.source_projects)

    def test_candidate_pool_promotion_and_dead_path_resilience(self):
        """
        Spec Refinement 4: Promotion appends to agents/<role>.md, deletes duplicate
        .edge/stations/<role>.md in active projects, and skips deleted/missing historical repos cleanly.
        """
        from tools.distill.state import CandidatePool

        repo_alpha = Path(self.temp_dir) / "repo_alpha"
        alpha_stations = repo_alpha / ".edge" / "stations"
        alpha_stations.mkdir(parents=True, exist_ok=True)
        alpha_overlay = alpha_stations / "surgeon.md"
        alpha_overlay.write_text("### Local Rule\nNever mutate tests during surgery\n", encoding="utf-8")

        repo_beta_dead = Path(self.temp_dir) / "repo_beta_nonexistent"

        pool = CandidatePool(candidates_file_override=self.candidates_file, plugin_root=self.plugin_root)
        cand = pool.record_candidate(
            rule_text="Never mutate tests during surgery",
            target_role="surgeon",
            project_path=str(repo_alpha),
        )
        cand = pool.record_candidate(
            rule_text="Never mutate tests during surgery",
            target_role="surgeon",
            project_path=str(repo_beta_dead),
        )
        self.assertEqual(cand.status, "READY_FOR_PROMOTION")

        promoted = pool.promote_candidate(cand.candidate_id, force=False)
        self.assertTrue(promoted)

        surgeon_rubric = (self.plugin_root / "agents" / "surgeon.md").read_text(encoding="utf-8")
        self.assertIn("Never mutate tests during surgery", surgeon_rubric)

        alpha_text = alpha_overlay.read_text(encoding="utf-8")
        self.assertNotIn("Never mutate tests during surgery", alpha_text)

    def test_check_line_budget_thresholds(self):
        from tools.distill.state import check_line_budget

        agent_ok = Path(self.temp_dir) / "agent_ok.md"
        agent_ok.write_text("\n".join([f"line {i}" for i in range(58)]), encoding="utf-8")
        ok, count, limit = check_line_budget(agent_ok, max_lines=60)
        self.assertTrue(ok)
        self.assertEqual(count, 58)
        self.assertEqual(limit, 60)

        agent_exceeded = Path(self.temp_dir) / "agent_exceeded.md"
        agent_exceeded.write_text("\n".join([f"line {i}" for i in range(65)]), encoding="utf-8")
        ok_exc, count_exc, limit_exc = check_line_budget(agent_exceeded, max_lines=60)
        self.assertFalse(ok_exc)
        self.assertEqual(count_exc, 65)

        station_ok = Path(self.temp_dir) / "station_ok.md"
        station_ok.write_text("\n".join([f"line {i}" for i in range(35)]), encoding="utf-8")
        ok_st, count_st, limit_st = check_line_budget(station_ok, max_lines=40)
        self.assertTrue(ok_st)
        self.assertEqual(count_st, 35)
        self.assertEqual(limit_st, 40)


class TestDistillCLICommands(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_cli_")
        self.repo_dir = Path(self.temp_dir) / "mock_project"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.cli_path = Path(__file__).resolve().parents[1] / "tools" / "distill" / "cli.py"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cli_harvest_positional_and_project_flag(self):
        """Spec Refinement 5: Both 'harvest <repo>' and 'harvest --project <repo>' succeed."""
        import subprocess

        # Positional repo
        proc1 = subprocess.run(
            [sys.executable, str(self.cli_path), "harvest", str(self.repo_dir), "--format", "json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc1.returncode, 0, f"harvest <repo> failed: {proc1.stderr}")

        # --project flag
        proc2 = subprocess.run(
            [sys.executable, str(self.cli_path), "harvest", "--project", str(self.repo_dir), "--format", "toon"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc2.returncode, 0, f"harvest --project failed: {proc2.stderr}")

    def test_cli_candidates_list_and_record(self):
        import subprocess

        proc_rec = subprocess.run(
            [
                sys.executable,
                str(self.cli_path),
                "candidates",
                "record",
                "--rule",
                "Always run unit tests before refactoring",
                "--role",
                "surgeon",
                "--project",
                str(self.repo_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_rec.returncode, 0, f"candidates record failed: {proc_rec.stderr}")

        proc_list = subprocess.run(
            [sys.executable, str(self.cli_path), "candidates", "list", "--format", "toon"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_list.returncode, 0, f"candidates list failed: {proc_list.stderr}")

    def test_cli_promote_candidate(self):
        import subprocess

        proc = subprocess.run(
            [sys.executable, str(self.cli_path), "promote", "--candidate", "CAND-test1234", "--force"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"promote candidate failed: {proc.stderr}")

    def test_cli_mark_processed(self):
        """Spec Refinement 5: mark-processed accepts --session <cid> and optional --project <repo>."""
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(self.cli_path),
                "mark-processed",
                "--session",
                "cid-session-123",
                "--project",
                str(self.repo_dir),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"mark-processed failed: {proc.stderr}")

    def test_cli_check_budget(self):
        """check-budget exits 0 on compliant budget and 1 on violation."""
        import subprocess

        good_file = self.repo_dir / "good.md"
        good_file.write_text("\n".join(["line" for _ in range(30)]), encoding="utf-8")
        proc_good = subprocess.run(
            [sys.executable, str(self.cli_path), "check-budget", str(good_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_good.returncode, 0)

        bad_file = self.repo_dir / "bad.md"
        bad_file.write_text("\n".join(["line" for _ in range(80)]), encoding="utf-8")
        proc_bad = subprocess.run(
            [sys.executable, str(self.cli_path), "check-budget", str(bad_file)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_bad.returncode, 1)

    def test_brigade_cli_distill_bridge(self):
        import subprocess
        brigade_cli_path = Path(__file__).resolve().parents[1] / "tools" / "brigade" / "cli.py"

        proc = subprocess.run(
            [sys.executable, str(brigade_cli_path), "distill", "harvest", str(self.repo_dir)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"brigade distill harvest bridge failed: {proc.stderr}")


class TestSessionMiner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_distill_miner_")
        self.brain_root = Path(self.temp_dir) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(self.temp_dir) / "mock_repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session(self, conv_id: str, lines: Any) -> Path:
        sess_dir = self.brain_root / conv_id / ".system_generated" / "logs"
        sess_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = sess_dir / "transcript.jsonl"
        with open(transcript_path, "w", encoding="utf-8") as f:
            for item in lines:
                if isinstance(item, str):
                    f.write(item + "\n")
                else:
                    f.write(json.dumps(item) + "\n")
        return transcript_path

    def test_zero_crash_streaming_and_malformed_json(self):
        lines = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z", "content": "Proje için plan yapalım"},
            "{malformed json line",
            "",
            "   ",
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-13T10:05:00Z", "tool_calls": [{"name": "run_command", "args": {"Cwd": "C:\\Users\\oguz_\\.gemini\\config\\plugins\\edge"}}]},
            "12345",  # valid JSON but not a dict
            '{"step_index": 2, truncated line...',
            {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:15:00Z", "content": "Teşekkürler"},
        ]
        tpath = self._create_session("sess-malformed", lines)
        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        parsed = miner.parse_transcript(tpath)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["conversation_id"], "sess-malformed")
        self.assertEqual(parsed["total_steps"], 3)  # Only 3 valid dict steps
        self.assertEqual(parsed["human_turns"], 2)
        self.assertEqual(parsed["duration_minutes"], 15)
        self.assertEqual(parsed["project"], "edge")

    def test_project_classification_hierarchy(self):
        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)

        # 1. Priority 1: workspaceUris wins over tool call args
        tpath1 = self._create_session("sess-ws", [
            {"step_index": 0, "workspaceUris": ["file:///c:/Users/oguz_/.gemini/config/plugins/edge"], "created_at": "2026-10-13T10:00:00Z"},
            {"step_index": 1, "tool_calls": [{"name": "run_command", "args": {"Cwd": "/home/oguz/MS-Randevu-monolith"}}]},
        ])
        p1 = miner.parse_transcript(tpath1)
        self.assertEqual(p1["project"], "edge")

        # 2. Priority 2: No workspaceUris, tool call arguments determine project
        tpath2 = self._create_session("sess-tools", [
            {"step_index": 0, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "cd /home/oguz/MS-Randevu-monolith && pytest"}}]},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "/home/oguz/MS-Randevu-monolith/src/main.ts"}}]},
        ])
        p2 = miner.parse_transcript(tpath2)
        self.assertEqual(p2["project"], "MS-Randevu-monolith")

        # 3. Priority 3: Only internal brain scratch paths -> UNASSIGNED / SCRATCH
        tpath3 = self._create_session("sess-scratch", [
            {"step_index": 0, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "C:\\Users\\oguz_\\.gemini\\antigravity\\brain\\abc\\plan.md"}}]},
        ])
        p3 = miner.parse_transcript(tpath3)
        self.assertEqual(p3["project"], "UNASSIGNED / SCRATCH")

    def test_chronological_ordering(self):
        # Create 3 sessions for same project with disordered start timestamps
        self._create_session("sess-late", [
            {"step_index": 0, "source": "USER_EXPLICIT", "created_at": "2026-10-14T12:00:00Z", "content": "Late session"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])
        self._create_session("sess-early", [
            {"step_index": 0, "source": "USER_EXPLICIT", "created_at": "2026-10-10T08:00:00Z", "content": "Early session"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])
        self._create_session("sess-middle", [
            {"step_index": 0, "source": "USER_EXPLICIT", "created_at": "2026-10-12T10:00:00Z", "content": "Middle session"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])

        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        data = miner.mine_sessions()

        self.assertIn("edge", data["projects"])
        sessions = data["projects"]["edge"]["sessions"]
        self.assertEqual(len(sessions), 3)

        # Check chronological order
        ordered_ids = [s["conversation_id"] for s in sessions]
        self.assertEqual(ordered_ids, ["sess-early", "sess-middle", "sess-late"])
        self.assertTrue(sessions[0]["start_time"] < sessions[1]["start_time"] < sessions[2]["start_time"])

    def test_intent_detection_and_clustering(self):
        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)

        # Human messages targeting all 5 intents
        lines = [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z",
             "content": "Balon penceresini temiz tutmak adına bu görevi alt ajan ile çöz, bağlam boğulmasın."},
            {"step_index": 1, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:05:00Z",
             "content": "Uçtan uca dikey dilim istiyorum, sadece db katmanı yazıp bırakma."},
            {"step_index": 2, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:10:00Z",
             "content": "Feathers dikiş yeri aç, repository interface sözleşme kur."},
            {"step_index": 3, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:15:00Z",
             "content": "Önce test yazılmalı, kırmızı test olmadan koda dokunma, testi bozma hile yapma."},
            {"step_index": 4, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:20:00Z",
             "content": "Arayüz için lavish prototip hazırla ve görsel olarak bana göster."},
            # Model message should NOT trigger intent detection
            {"step_index": 5, "source": "MODEL", "type": "PLANNER_RESPONSE", "created_at": "2026-10-13T10:25:00Z",
             "content": "Anladım, balon pencereni temiz tutuyorum ve lavish ile görsel arayüzü açıyorum."},
            {"step_index": 6, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/code-manor/SKILL.md"}}]},
        ]
        tpath = self._create_session("sess-intents", lines)
        parsed = miner.parse_transcript(tpath)

        expected_intents = ["Context Hygiene", "Seam & Contracts", "Test Immutability", "Vertical Slice", "Visual Gate"]
        self.assertEqual(parsed["detected_intents"], expected_intents)
        self.assertTrue(len(parsed["quotes_by_intent"]) == 5)
        self.assertIn("temiz tutmak", parsed["quotes_by_intent"]["Context Hygiene"].lower())
        self.assertIn("dikey dilim", parsed["quotes_by_intent"]["Vertical Slice"].lower())

    def test_json_output_schema_and_persistence(self):
        self._create_session("sess-1", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z", "content": "Balon pencereni temiz tut alt ajan delege et."},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])

        miner = SessionMiner(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        data = miner.mine_sessions()

        self.assertIn("generated_at", data)
        self.assertEqual(data["total_sessions"], 1)
        self.assertIn("projects", data)
        self.assertIn("edge", data["projects"])
        self.assertEqual(data["projects"]["edge"]["session_count"], 1)

        sess_obj = data["projects"]["edge"]["sessions"][0]
        self.assertEqual(sess_obj["conversation_id"], "sess-1")
        self.assertIn("Context Hygiene", sess_obj["detected_intents"])

        self.assertIn("intent_summary", data)
        for intent_name in INTENT_DEFINITIONS.keys():
            self.assertIn(intent_name, data["intent_summary"])
            self.assertIn("session_frequency", data["intent_summary"][intent_name])
            self.assertIn("sample_quote", data["intent_summary"][intent_name])

        self.assertEqual(data["intent_summary"]["Context Hygiene"]["session_frequency"], 1)
        self.assertTrue(len(data["intent_summary"]["Context Hygiene"]["sample_quote"]) > 0)

        # Test save
        out_file = miner.save_sessions_json(data)
        self.assertTrue(out_file.exists())
        loaded = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual(loaded["total_sessions"], 1)

    def test_cli_sessions_and_intents_commands(self):
        self._create_session("sess-cli", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-10-13T10:00:00Z", "content": "Görsel arayüz için lavish prototip hazırla"},
            {"step_index": 1, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": "plugins/edge/SKILL.md"}}]},
        ])

        custom_json = self.repo_dir / "custom_sessions.json"

        # 1. edge-distill sessions
        with patch.object(sys, "argv", [
            "edge-distill", "sessions", str(self.repo_dir),
            "--brain-roots", str(self.brain_root),
            "--output", str(custom_json)
        ]):
            code = distill_main()
            self.assertEqual(code, 0)
            self.assertTrue(custom_json.exists())

        # 2. edge-distill sessions --by-project
        with patch.object(sys, "argv", [
            "edge-distill", "sessions", str(self.repo_dir),
            "--by-project",
            "--brain-roots", str(self.brain_root),
            "--output", str(custom_json)
        ]):
            code = distill_main()
            self.assertEqual(code, 0)

        # 3. edge-distill intents
        with patch.object(sys, "argv", [
            "edge-distill", "intents", str(self.repo_dir),
            "--brain-roots", str(self.brain_root),
            "--output", str(custom_json)
        ]):
            code = distill_main()
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
