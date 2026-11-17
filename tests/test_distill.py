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
from typing import Any, List, Dict, Optional, Set, Tuple
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


    def test_real_antigravity_generic_tool_result_matching(self):
        """
        Spec Section 3.1, 3.2 & Section 8.3:
        Real Antigravity transcripts output tool execution results as:
        {"source": "MODEL", "type": "GENERIC", "content": "..."}
        Harvester must extract non-zero exit codes and 'Encountered error in tool execution'.
        """
        from tools.distill.harvester import TranscriptGraphHarvester

        steps = [
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {
                        "name": "run_command",
                        "args": {"CommandLine": "npm test", "toolSummary": "Run test suite"},
                    }
                ],
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Created At: 2026-11-04T00:00:00Z\nCommand exited with code 1.\nerror TS2322: Type 'string' is not assignable to type 'number'.",
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {
                        "name": "edit_file",
                        "args": {"Path": "/home/oguz/app/src/index.ts", "Target": "foo", "Replacement": "bar"},
                    }
                ],
            },
            {
                "step_index": 4,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Encountered error in tool execution: target content not found in file",
            },
        ]

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        sessions_steps = {"cid-generic-result": steps}
        frictions, escapes, escalations = harvester._collect_signals(["cid-generic-result"], sessions_steps)

        self.assertGreaterEqual(len(frictions), 2, "Expected at least 2 tool frictions extracted from GENERIC type steps")
        exit_codes = [f.exit_code for f in frictions if f.tool_name == "run_command"]
        self.assertIn(1, exit_codes, "Exit code 1 was not extracted from 'Command exited with code 1.'")
        tool_errs = [f for f in frictions if "target content not found" in f.error_output]
        self.assertGreaterEqual(len(tool_errs), 1, "Encountered error in tool execution was not captured")

    def test_zero_exit_code_never_flagged_and_turn_window_isolation(self):
        """
        Spec Section 3.2 & Section 8.3:
        1. 'Command exited with code 0' is NEVER flagged as friction, even if output contains 'error' in logs.
        2. Turn-window isolation: A successful tool call at step N must break immediately on next PLANNER_RESPONSE
           and never inherit error text from step N+3.
        """
        from tools.distill.harvester import TranscriptGraphHarvester

        steps = [
            {
                "step_index": 1,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "npm test"}}],
            },
            {
                "step_index": 2,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Command exited with code 0.\nTests passed. 0 errors, 0 warnings.",
            },
            {
                "step_index": 3,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "run_command", "args": {"CommandLine": "git push"}}],
            },
            {
                "step_index": 4,
                "source": "MODEL",
                "type": "GENERIC",
                "content": "Command exited with code 128.\nfatal: remote rejected",
            },
        ]

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        sessions_steps = {"cid-turn-window": steps}
        frictions, escapes, escalations = harvester._collect_signals(["cid-turn-window"], sessions_steps)

        self.assertEqual(len(frictions), 1, f"Expected exactly 1 friction, found {len(frictions)}: {[f.command for f in frictions]}")
        self.assertEqual(frictions[0].exit_code, 128)
        self.assertIn("git push", frictions[0].command)

    def test_multilingual_turkish_and_english_repeated_escalations(self):
        """
        Spec Section 3.3 & Section 8.5:
        Multi-lingual user corrective messages (Turkish & English) must be extracted into RepeatedEscalation
        when >= 2 occurrences exist. Defaults target_role="coder" unless station keywords present.
        """
        from tools.distill.harvester import TranscriptGraphHarvester

        steps_coder = [
            {
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Hayır, yanlış yaklaştın, o dosyayı silme",
            },
            {
                "step_index": 5,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Bozma testleri, hayır yanlış yapıyorsun",
            },
        ]

        harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        sessions_steps = {"cid-escalate-coder": steps_coder}
        frictions, escapes, escalations = harvester._collect_signals(["cid-escalate-coder"], sessions_steps)

        self.assertGreaterEqual(len(escalations), 1, "Failed to extract multi-lingual repeated escalation")
        esc = escalations[0]
        self.assertGreaterEqual(esc.occurrence_count, 2)
        self.assertEqual(esc.target_role, "coder", "Default target_role must be 'coder'")

        steps_surgeon = [
            {
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Hayır, yanlış! Surgeon ameliyatı eksik yaptı, worktree temiz değil",
            },
            {
                "step_index": 4,
                "source": "USER_EXPLICIT",
                "type": "USER_INPUT",
                "content": "Hatalı yöntem, surgeon station kurallarına uy",
            },
        ]
        _, _, escalations_s = harvester._collect_signals(["cid-escalate-surgeon"], {"cid-escalate-surgeon": steps_surgeon})
        self.assertGreaterEqual(len(escalations_s), 1)
        self.assertEqual(escalations_s[0].target_role, "surgeon", "Target role must be mapped to 'surgeon' when keyword present")

    def test_project_mode_signal_split_and_silent_factory_inbox_queue(self):
        """
        Spec Section 3.4, 5.2 (Scenario 3) & Section 8.1:
        In PROJECT_MODE (mode="project"):
        - FrictionDigest contains strictly PROJECT_SIGNALS (tsc/repo compile errors).
        - HARNESS_SIGNALS (brigade/treehouse errors, station escapes, WSL relay) are excluded from digest.
        - HARNESS_SIGNALS are silently queued into edge_factory_inbox.json.
        - digest.harness_signals_queued is set to count of queued harness signals.
        """
        from tools.distill.harvester import TranscriptGraphHarvester

        inbox_file = Path(self.temp_dir) / "test_factory_inbox.json"
        with patch.dict(os.environ, {"EDGE_DISTILL_FACTORY_INBOX_FILE": str(inbox_file)}):
            harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)

            steps = [
                {
                    "step_index": 1,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [{"name": "run_command", "args": {"CommandLine": "npx tsc --noEmit"}}],
                },
                {
                    "step_index": 2,
                    "source": "MODEL",
                    "type": "GENERIC",
                    "content": "Command exited with code 1.\nsrc/app.ts(10,5): error TS2304: Cannot find name 'foo'.",
                },
                {
                    "step_index": 3,
                    "source": "MODEL",
                    "type": "PLANNER_RESPONSE",
                    "tool_calls": [{"name": "run_command", "args": {"CommandLine": "treehouse get --lease -b feat/test"}}],
                },
                {
                    "step_index": 4,
                    "source": "MODEL",
                    "type": "GENERIC",
                    "content": "Command exited with code 1.\ntreehouse: error: pool locked by another process",
                },
            ]

            with patch.object(harvester, "_discover_transcripts", return_value={"cid-proj-mode": Path("/mock/t.jsonl")}):
                with patch.object(harvester, "_load_transcripts", return_value=({"cid-proj-mode": steps}, {}, {})):
                    with patch.object(harvester, "_find_matched_sessions", return_value=["cid-proj-mode"]):
                        digest = harvester.harvest(project_path=self.repo_dir, mode="project", reprocess=True)

            self.assertTrue(hasattr(digest, "harness_signals_queued"), "FrictionDigest missing harness_signals_queued field")
            self.assertEqual(digest.harness_signals_queued, 1)
            self.assertEqual(len(digest.tool_frictions), 1)
            self.assertIn("error TS2304", digest.tool_frictions[0].error_output)

            self.assertTrue(inbox_file.is_file(), "Harness signals were not written to factory inbox file")
            inbox_data = json.loads(inbox_file.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(inbox_data.get("signals", [])), 1)
            self.assertIn("treehouse", inbox_data["signals"][0]["summary"].lower())

    def test_factory_mode_drains_inbox_and_renders_toon(self):
        """
        Spec Section 2.3, 5.2 (Scenario 4) & Section 8.1:
        In FACTORY_MODE (mode="factory"):
        - Pending signals from edge_factory_inbox.json are included in digest.factory_inbox_signals.
        - FrictionDigest.to_toon() includes '## Factory Inbox Signals'.
        """
        from tools.distill.harvester import TranscriptGraphHarvester

        inbox_file = Path(self.temp_dir) / "test_factory_inbox.json"
        inbox_file.write_text(
            json.dumps({
                "signals": [
                    {
                        "signal_id": "SIG-INBOX-001",
                        "fingerprint": "abc12345def67890",
                        "kind": "HARNESS_FRICTION",
                        "source_project": "/home/oguz/app",
                        "role_or_tool": "brigade",
                        "summary": "Brigade FSM abort in SURGERY",
                        "created_at": "2026-11-04T00:00:00Z",
                        "resolved": False,
                    }
                ]
            }),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"EDGE_DISTILL_FACTORY_INBOX_FILE": str(inbox_file)}):
            harvester = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
            with patch.object(harvester, "_discover_transcripts", return_value={}):
                with patch.object(harvester, "_load_transcripts", return_value=({}, {}, {})):
                    with patch.object(harvester, "_find_matched_sessions", return_value=[]):
                        digest = harvester.harvest(project_path=self.repo_dir, mode="factory")

            self.assertTrue(hasattr(digest, "factory_inbox_signals"), "FrictionDigest missing factory_inbox_signals field")
            self.assertEqual(len(digest.factory_inbox_signals), 1)
            self.assertIn("Brigade FSM abort", digest.factory_inbox_signals[0]["summary"])

            toon_output = digest.to_toon()
            self.assertIn("## Factory Inbox Signals", toon_output)
            self.assertIn("SIG-INBOX-001", toon_output)


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


    def test_factory_inbox_atomic_persistence_and_sha256_dedup(self):
        """
        Spec Section 2.3, 5.2 (Scenario 4) & Section 8.2:
        FactoryInbox manages atomic persistence to edge_factory_inbox.json,
        supports EDGE_DISTILL_FACTORY_INBOX_FILE override, and enforces
        SHA-256 fingerprint deduplication:
        fingerprint = sha256(f"{kind}:{role_or_tool}:{summary}".lower().encode("utf-8")).hexdigest()[:16]
        """
        from tools.distill.state import FactoryInbox

        inbox_file = Path(self.temp_dir) / "test_factory_inbox.json"
        inbox = FactoryInbox(inbox_file_override=inbox_file)

        signal1 = {
            "kind": "HARNESS_FRICTION",
            "source_project": "/home/oguz/app",
            "role_or_tool": "treehouse",
            "summary": "Treehouse lease failed: slot busy",
        }
        signal2 = {
            "kind": "HARNESS_FRICTION",
            "source_project": "/home/oguz/app",
            "role_or_tool": "treehouse",
            "summary": "Treehouse lease failed: slot busy",
        }
        signal3 = {
            "kind": "STATION_ESCAPE",
            "source_project": "/home/oguz/app",
            "role_or_tool": "surgeon",
            "summary": "Surgeon escaped to triage",
        }

        inbox.append_signals([signal1, signal2, signal3])
        self.assertTrue(inbox_file.is_file(), "Factory inbox file was not created")

        data = json.loads(inbox_file.read_text(encoding="utf-8"))
        self.assertIn("signals", data)
        self.assertEqual(len(data["signals"]), 2, f"Expected 2 deduplicated signals, found {len(data['signals'])}")

        sig = data["signals"][0]
        self.assertIn("signal_id", sig)
        self.assertIn("fingerprint", sig)
        self.assertIn("kind", sig)
        self.assertIn("source_project", sig)
        self.assertIn("role_or_tool", sig)
        self.assertIn("summary", sig)
        self.assertIn("created_at", sig)
        self.assertIn("resolved", sig)
        self.assertFalse(sig["resolved"])

        pending = inbox.load_pending()
        self.assertEqual(len(pending), 2)
        inbox.clear()
        self.assertEqual(len(inbox.load_pending()), 0)

    def test_watermark_state_dual_mode_segregation(self):
        """
        Spec Section 2.2, Section 8.4 & 8.5:
        DistillWatermarkState supports factory_processed_sessions.
        Deserialization provides safe default for factory_processed_sessions=[].
        """
        from tools.distill.models import DistillWatermarkState

        legacy_data = {
            "version": "2.0",
            "last_harvested_at": "2026-11-04T00:00:00Z",
            "processed_sessions": ["cid-1"],
            "project_sessions": {"/home/oguz/app": ["cid-1"]},
        }
        state = DistillWatermarkState.from_dict(legacy_data)
        self.assertTrue(hasattr(state, "factory_processed_sessions"), "DistillWatermarkState missing factory_processed_sessions field")
        self.assertEqual(state.factory_processed_sessions, [])

        state.factory_processed_sessions.append("cid-factory-1")
        d = state.to_dict()
        self.assertIn("factory_processed_sessions", d)
        self.assertIn("cid-factory-1", d["factory_processed_sessions"])


class TestDistillCLICommands(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_cli_")
        self.repo_dir = Path(self.temp_dir) / "mock_project"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.cli_path = Path(__file__).resolve().parents[1] / "tools" / "distill" / "cli.py"
        self.state_file = Path(self.temp_dir) / "distill_state.json"
        self.candidates_file = Path(self.temp_dir) / "distill_candidates.json"
        self.factory_inbox_file = Path(self.temp_dir) / "edge_factory_inbox.json"
        self.env = {
            **os.environ,
            "EDGE_DISTILL_STATE_FILE": str(self.state_file),
            "EDGE_DISTILL_CANDIDATES_FILE": str(self.candidates_file),
            "EDGE_DISTILL_FACTORY_INBOX_FILE": str(self.factory_inbox_file),
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _run_cli(self, args, **kwargs):
        import subprocess
        env = kwargs.pop("env", self.env)
        return subprocess.run(
            [sys.executable, str(self.cli_path)] + args,
            capture_output=True,
            text=True,
            env=env,
            **kwargs,
        )

    def test_cli_harvest_positional_and_project_flag(self):
        """Spec Refinement 5: Both 'harvest <repo>' and 'harvest --project <repo>' succeed."""
        proc1 = self._run_cli(["harvest", str(self.repo_dir), "--format", "json"])
        self.assertEqual(proc1.returncode, 0, f"harvest <repo> failed: {proc1.stderr}")

        proc2 = self._run_cli(["harvest", "--project", str(self.repo_dir), "--format", "toon"])
        self.assertEqual(proc2.returncode, 0, f"harvest --project failed: {proc2.stderr}")

    def test_cli_candidates_list_and_record(self):
        proc_rec = self._run_cli([
            "candidates",
            "record",
            "--rule",
            "Always run unit tests before refactoring",
            "--role",
            "surgeon",
            "--project",
            str(self.repo_dir),
        ])
        self.assertEqual(proc_rec.returncode, 0, f"candidates record failed: {proc_rec.stderr}")

        proc_list = self._run_cli(["candidates", "list", "--format", "toon"])
        self.assertEqual(proc_list.returncode, 0, f"candidates list failed: {proc_list.stderr}")

    def test_cli_promote_candidate(self):
        proc = self._run_cli(["promote", "--candidate", "CAND-test1234", "--force"])
        self.assertEqual(proc.returncode, 0, f"promote candidate failed: {proc.stderr}")

    def test_cli_mark_processed(self):
        """Spec Refinement 5: mark-processed accepts --session <cid> and optional --project <repo>."""
        proc = self._run_cli([
            "mark-processed",
            "--session",
            "cid-session-123",
            "--project",
            str(self.repo_dir),
        ])
        self.assertEqual(proc.returncode, 0, f"mark-processed failed: {proc.stderr}")

    def test_cli_check_budget(self):
        """check-budget exits 0 on compliant budget and 1 on violation."""
        good_file = self.repo_dir / "good.md"
        good_file.write_text(chr(10).join(["line" for _ in range(30)]), encoding="utf-8")
        proc_good = self._run_cli(["check-budget", str(good_file)])
        self.assertEqual(proc_good.returncode, 0)

        bad_file = self.repo_dir / "bad.md"
        bad_file.write_text(chr(10).join(["line" for _ in range(80)]), encoding="utf-8")
        proc_bad = self._run_cli(["check-budget", str(bad_file)])
        self.assertEqual(proc_bad.returncode, 1)

    def test_brigade_cli_distill_bridge(self):
        import subprocess
        brigade_cli_path = Path(__file__).resolve().parents[1] / "tools" / "brigade" / "cli.py"

        proc = subprocess.run(
            [sys.executable, str(brigade_cli_path), "distill", "harvest", str(self.repo_dir)],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(proc.returncode, 0, f"brigade distill harvest bridge failed: {proc.stderr}")

    def test_cli_hermetic_isolation_does_not_touch_home_antigravity(self):
        """
        Slice 4 Hermetic Isolation:
        CLI operations run with temporary env overrides must NOT write or touch
        files in Path.home() / '.gemini' / 'antigravity'.
        """
        home_antigravity = Path.home() / ".gemini" / "antigravity"
        home_antigravity.mkdir(parents=True, exist_ok=True)
        files_before = {p: p.stat().st_mtime_ns for p in home_antigravity.iterdir() if p.is_file()}

        proc_cand = self._run_cli([
            "candidates",
            "record",
            "--rule",
            "Always write hermetic unit tests",
            "--role",
            "seam_architect",
            "--project",
            str(self.repo_dir),
        ])
        self.assertEqual(proc_cand.returncode, 0, f"candidates record failed: {proc_cand.stderr}")

        proc_mark = self._run_cli([
            "mark-processed",
            "--session",
            "cid-hermetic-123",
            "--project",
            str(self.repo_dir),
        ])
        self.assertEqual(proc_mark.returncode, 0, f"mark-processed failed: {proc_mark.stderr}")

        self.assertTrue(self.candidates_file.exists(), "Hermetic candidates file was not created in temp_dir")
        self.assertTrue(self.state_file.exists(), "Hermetic state file was not created in temp_dir")

        files_after = {p: p.stat().st_mtime_ns for p in home_antigravity.iterdir() if p.is_file()}
        new_files = set(files_after.keys()) - set(files_before.keys())
        self.assertEqual(new_files, set(), f"Hermetic violation: new files created in home directory: {new_files}")
        for p, mtime_before in files_before.items():
            self.assertEqual(files_after[p], mtime_before, f"Hermetic violation: file modified in home: {p}")

    def test_cli_harvest_mode_auto_and_json_stdout_purity(self):
        """
        Spec Section 2.1 & Section 8.1:
        cli.py harvest supports --mode {auto,project,factory}.
        When run on application repo with --format json, stdout is pure valid JSON.
        """
        proc = self._run_cli([
            "harvest",
            str(self.repo_dir),
            "--mode",
            "auto",
            "--format",
            "json",
        ])
        self.assertEqual(proc.returncode, 0, f"harvest --mode auto failed: {proc.stderr}")
        try:
            data = json.loads(proc.stdout)
            self.assertIsInstance(data, dict)
            self.assertIn("digest_id", data)
        except json.JSONDecodeError as e:
            self.fail(f"stdout is not valid JSON (polluted by logs): {e}\nstdout: {proc.stdout}")

    def test_cli_mark_processed_clear_factory_inbox_standalone(self):
        """
        Spec Section 8.4:
        mark-processed accepts --mode {project,factory} and --clear-factory-inbox.
        --clear-factory-inbox can be executed standalone without --session.
        """
        proc_clear = self._run_cli([
            "mark-processed",
            "--clear-factory-inbox",
        ])
        self.assertEqual(proc_clear.returncode, 0, f"mark-processed --clear-factory-inbox failed: {proc_clear.stderr}")

        proc_factory_mode = self._run_cli([
            "mark-processed",
            "--session",
            "cid-factory-mode-test",
            "--mode",
            "factory",
        ])
        self.assertEqual(proc_factory_mode.returncode, 0, f"mark-processed --mode factory failed: {proc_factory_mode.stderr}")


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



class TestDistillWatermarkAndRoleHyphenFix(unittest.TestCase):
    """
    Hermetic contract and unit tests for Distill v2.1 Slice 1:
    - CLI Harvest Watermark Injection & Persistence (Scenarios 1-2)
    - Hyphenated / Underscored Agent Role File Resolution (Scenarios 3-5)
    - FactoryInbox Dynamic Entropy Sanitization & Ephemeral Path Filter (Scenarios 6-8)
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_watermark_slice_")
        self.brain_root = Path(self.temp_dir) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(self.temp_dir) / "project_beta"
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_root = Path(self.temp_dir) / "plugin_edge"
        self.plugin_root.mkdir(parents=True, exist_ok=True)
        (self.plugin_root / "agents").mkdir(parents=True, exist_ok=True)

        self.state_file = Path(self.temp_dir) / "distill_state.json"
        self.candidates_file = Path(self.temp_dir) / "distill_candidates.json"
        self.factory_inbox_file = Path(self.temp_dir) / "edge_factory_inbox.json"

        self.orig_env = dict(os.environ)
        os.environ["GEMINI_BRAIN_ROOT"] = str(self.brain_root)
        os.environ["EDGE_DISTILL_STATE_FILE"] = str(self.state_file)
        os.environ["EDGE_DISTILL_CANDIDATES_FILE"] = str(self.candidates_file)
        os.environ["EDGE_DISTILL_FACTORY_INBOX_FILE"] = str(self.factory_inbox_file)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.orig_env)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session(self, conv_id: str, steps: List[Dict[str, Any]]) -> Path:
        sess_dir = self.brain_root / conv_id / ".system_generated" / "logs"
        sess_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = sess_dir / "transcript.jsonl"
        with open(transcript_path, "w", encoding="utf-8") as f:
            for s in steps:
                f.write(json.dumps(s) + "\n")
        return transcript_path

    # --- 1. cmd_harvest Watermark Injection & Persistence ---
    def test_cmd_harvest_injects_watermark_and_skips_processed_sessions(self):
        """
        Scenario 1:
        cmd_harvest loads DistillStateManager.load_state() and passes watermark_state
        to TranscriptGraphHarvester so previously processed sessions are skipped.
        """
        from tools.distill.cli import cmd_harvest
        from tools.distill.state import DistillStateManager
        from tools.distill.models import DistillWatermarkState
        import argparse

        # Create two sessions for project_beta
        self._create_session("sess-wm-old", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])
        self._create_session("sess-wm-new", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])

        # Pre-seed watermark with sess-wm-old
        state_mgr = DistillStateManager(self.state_file)
        initial_state = DistillWatermarkState(
            processed_sessions=["sess-wm-old"],
            project_sessions={str(self.repo_dir.resolve()): ["sess-wm-old"]},
        )
        state_mgr.save_state(initial_state)

        # Run cmd_harvest with output directed to temp file
        out_file = Path(self.temp_dir) / "digest.json"
        args = argparse.Namespace(
            project=str(self.repo_dir),
            format="json",
            output=str(out_file),
            mode="project",
            reprocess=False,
            current=None,
            max_sessions=50,
        )

        ret = cmd_harvest(args)
        self.assertEqual(ret, 0)
        self.assertTrue(out_file.exists())
        data = json.loads(out_file.read_text(encoding="utf-8"))

        # sess-wm-old MUST be skipped, only sess-wm-new analyzed
        self.assertNotIn("sess-wm-old", data.get("sessions_analyzed", []))
        self.assertIn("sess-wm-new", data.get("sessions_analyzed", []))
        self.assertEqual(len(data.get("sessions_analyzed", [])), 1)

    def test_cmd_harvest_persists_updated_watermark_to_state(self):
        """
        Scenario 2:
        cmd_harvest updates and commits newly analyzed sessions to DistillStateManager.
        """
        from tools.distill.cli import cmd_harvest
        from tools.distill.state import DistillStateManager
        import argparse

        self._create_session("sess-wm-commit", [{"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]}])

        out_file = Path(self.temp_dir) / "digest2.json"
        args = argparse.Namespace(
            project=str(self.repo_dir),
            format="json",
            output=str(out_file),
            mode="project",
            reprocess=False,
            current=None,
            max_sessions=50,
        )

        ret = cmd_harvest(args)
        self.assertEqual(ret, 0)

        # Verify state was committed
        state_mgr = DistillStateManager(self.state_file)
        loaded = state_mgr.load_state()
        self.assertIn("sess-wm-commit", loaded.processed_sessions)
        p_sessions = loaded.project_sessions.get(str(self.repo_dir.resolve()), [])
        self.assertIn("sess-wm-commit", p_sessions)
        self.assertTrue(loaded.last_harvested_at, "last_harvested_at should be updated")

    # --- 2. Hyphen / Underscore Role File Resolution ---
    def test_resolve_agent_rubric_path_canonical_precedence(self):
        """
        Scenario 3:
        _resolve_agent_rubric_path prioritizes hyphenated files (e.g. 'spec-writer.md')
        over underscored ones ('spec_writer.md').
        """
        from tools.distill import state

        self.assertTrue(
            hasattr(state, "_resolve_agent_rubric_path"),
            "tools.distill.state must define _resolve_agent_rubric_path",
        )

        # 1. Existing hyphenated file is selected for underscored query
        hyphen_file = self.plugin_root / "agents" / "spec-writer.md"
        hyphen_file.write_text("# Spec Writer\n", encoding="utf-8")
        resolved = state._resolve_agent_rubric_path(self.plugin_root, "spec_writer")
        self.assertEqual(resolved, hyphen_file)

        # 2. Existing underscored file fallback when hyphen absent
        legacy_file = self.plugin_root / "agents" / "spec_critic.md"
        legacy_file.write_text("# Spec Critic\n", encoding="utf-8")
        resolved_legacy = state._resolve_agent_rubric_path(self.plugin_root, "spec_critic")
        self.assertEqual(resolved_legacy, legacy_file)

        # 3. Default to canonical hyphen path when neither exists
        resolved_new = state._resolve_agent_rubric_path(self.plugin_root, "qa_engineer")
        self.assertEqual(resolved_new, self.plugin_root / "agents" / "qa-engineer.md")

    def test_promote_candidate_hyphenated_rubric_target(self):
        """
        Scenario 4:
        promote_candidate writes to canonical hyphenated agent rubric ('agents/spec-writer.md')
        even when target_role is underscored ('spec_writer') and does NOT create 'agents/spec_writer.md'.
        """
        from tools.distill.state import CandidatePool
        from tools.distill.models import CandidateRule

        canonical_file = self.plugin_root / "agents" / "spec-writer.md"
        canonical_file.write_text("# Spec Writer\n\n## Rubrics\n", encoding="utf-8")

        pool = CandidatePool(
            candidates_file_override=self.candidates_file,
            plugin_root=self.plugin_root,
        )
        cand = CandidateRule(
            candidate_id="CAND-SPEC-1",
            fingerprint="fp-spec-1",
            rule_text="Always write hermetic Gherkin acceptance criteria.",
            target_role="spec_writer",
            scope_class="ROLE_OVERLAY",
            source_projects=[str(self.repo_dir)],
            status="READY_FOR_PROMOTION",
        )
        pool.save_candidates([cand])

        promoted = pool.promote_candidate("CAND-SPEC-1", plugin_root=self.plugin_root, force=True)
        self.assertTrue(promoted)

        # Verify appended to canonical hyphenated file
        content = canonical_file.read_text(encoding="utf-8")
        self.assertIn("Always write hermetic Gherkin acceptance criteria.", content)

        # Verify orphan underscored file was NOT created
        orphan_file = self.plugin_root / "agents" / "spec_writer.md"
        self.assertFalse(orphan_file.exists(), f"Orphan underscored file should not exist: {orphan_file}")

    def test_clean_rule_from_all_projects_dual_variant_cleanup(self):
        """
        Scenario 5:
        _clean_rule_from_all_projects removes candidate rule from both hyphenated ('seam-architect.md')
        and underscored ('seam_architect.md') station overlays across projects.
        """
        from tools.distill import state
        from tools.distill.models import CandidateRule

        proj_a = Path(self.temp_dir) / "proj_alpha"
        proj_b = Path(self.temp_dir) / "proj_bravo"
        stations_a = proj_a / ".edge" / "stations"
        stations_b = proj_b / ".edge" / "stations"
        stations_a.mkdir(parents=True, exist_ok=True)
        stations_b.mkdir(parents=True, exist_ok=True)

        rule_text = "Always define characterization tests first."
        cand = CandidateRule(
            candidate_id="CAND-SEAM-1",
            fingerprint="fp-seam-1",
            rule_text=rule_text,
            target_role="seam_architect",
            scope_class="ROLE_OVERLAY",
            source_projects=[str(proj_a), str(proj_b)],
            status="READY_FOR_PROMOTION",
        )

        # Hyphenated overlay in Proj A
        overlay_a = stations_a / "seam-architect.md"
        overlay_a.write_text(f"# Seam Architect\n\n- {rule_text}\n- Keep CC under 8\n", encoding="utf-8")

        # Underscored overlay in Proj B
        overlay_b = stations_b / "seam_architect.md"
        overlay_b.write_text(f"# Seam Architect\n\n- {rule_text}\n- Isolate repositories\n", encoding="utf-8")

        state._clean_rule_from_all_projects([str(proj_a), str(proj_b)], cand)

        content_a = overlay_a.read_text(encoding="utf-8")
        content_b = overlay_b.read_text(encoding="utf-8")
        self.assertNotIn(rule_text, content_a, "Rule was not removed from hyphenated overlay")
        self.assertNotIn(rule_text, content_b, "Rule was not removed from underscored overlay")
        self.assertIn("Keep CC under 8", content_a)
        self.assertIn("Isolate repositories", content_b)

    # --- 3. FactoryInbox Sanitization & Ephemeral Path Filter ---
    def test_sanitize_signal_summary_deterministic_fingerprint(self):
        """
        Scenario 6 & 7:
        _sanitize_signal_summary strips dynamic entropy (Created At, ISO timestamps, WSL PIDs, temp paths)
        ensuring identical SHA-256 fingerprints and deduplication in FactoryInbox.
        """
        from tools.distill import state
        from tools.distill.state import FactoryInbox

        self.assertTrue(
            hasattr(state, "_sanitize_signal_summary"),
            "tools.distill.state must define _sanitize_signal_summary",
        )

        summary_a = (
            "Created At: 2026-11-11T23:20:26-05:00\n"
            "WSL (12345 - Relay) failed\n"
            "TypeScript error in /tmp/pytest-run-1/code.ts: syntax error"
        )
        summary_b = (
            "Created At: 2026-11-12T01:15:00Z\n"
            "WSL (98765 - Relay) failed\n"
            "TypeScript error in /tmp/pytest-run-2/code.ts: syntax error"
        )

        inbox = FactoryInbox(inbox_file_override=self.factory_inbox_file)
        raw_a = {"kind": "HARNESS_FRICTION", "role_or_tool": "wsl", "summary": summary_a}
        raw_b = {"kind": "HARNESS_FRICTION", "role_or_tool": "wsl", "summary": summary_b}

        rec_a, fp_a = inbox._build_signal_record(raw_a)
        rec_b, fp_b = inbox._build_signal_record(raw_b)

        self.assertEqual(fp_a, fp_b, f"Fingerprints must match after sanitization: {fp_a} != {fp_b}")
        self.assertEqual(len(fp_a), 16)

        # Appending both to inbox must result in 1 added (deduplicated)
        added = inbox.append_signals([raw_a, raw_b])
        self.assertEqual(added, 1)
        self.assertEqual(len(inbox.load_signals()), 1)

    def test_is_ephemeral_test_path_detection(self):
        """
        Scenario 8a:
        _is_ephemeral_test_path detects paths generated by pytest/unittest/tmp fixtures.
        """
        from tools.distill import state

        self.assertTrue(
            hasattr(state, "_is_ephemeral_test_path"),
            "tools.distill.state must define _is_ephemeral_test_path",
        )

        self.assertTrue(state._is_ephemeral_test_path("/tmp/pytest-of-oguz/pytest-12/repo"))
        self.assertTrue(state._is_ephemeral_test_path("/tmp/test_dir_abc/project"))
        self.assertTrue(state._is_ephemeral_test_path(r"C:\Users\oguz_\AppData\Local\Temp\tmp_test\repo"))
        self.assertTrue(state._is_ephemeral_test_path("/var/folders/xx/yy/T/temp_fixture"))

        self.assertFalse(state._is_ephemeral_test_path("/home/oguz/projects/my-app"))
        self.assertFalse(state._is_ephemeral_test_path("/mnt/c/Users/oguz_/workspace/edge"))
        self.assertFalse(state._is_ephemeral_test_path(""))

    def test_factory_inbox_drops_ephemeral_test_path_on_prod_inbox(self):
        """
        Scenario 8b:
        When FactoryInbox uses the default production path, append_signals drops signals
        originating from ephemeral test fixture paths.
        """
        from tools.distill import state
        from tools.distill.state import FactoryInbox

        # Point default path to our temp file for safe verification
        with patch.object(state, "_default_factory_inbox_path", return_value=self.factory_inbox_file.resolve()):
            inbox = FactoryInbox(inbox_file_override=self.factory_inbox_file)

            raw_test = {
                "kind": "HARNESS_FRICTION",
                "role_or_tool": "run_command",
                "summary": "Mock test failure",
                "source_project": "/tmp/pytest-1234/test_fixture_project",
            }
            raw_real = {
                "kind": "HARNESS_FRICTION",
                "role_or_tool": "run_command",
                "summary": "Real app failure",
                "source_project": "/home/oguz/real-app",
            }

            added = inbox.append_signals([raw_test, raw_real])
            self.assertEqual(added, 1, "Only real project signal should be accepted into production inbox")
            signals = inbox.load_signals()
            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0]["source_project"], "/home/oguz/real-app")



class TestDistillHarvesterBackgroundHangTelemetry(unittest.TestCase):
    """
    Hermetic contract and unit tests for Distill v2.1 Slice 2:
    - --since-hours sliding window filter (Scenarios 1)
    - Cycle-safe BFS multi-level subagent lineage expansion (Scenarios 2-3)
    - manage_task & background log tail telemetry (Scenarios 4-5)
    - Two-layer workspace affiliation & harness keyword routing (Scenarios 6-8)
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_hang_telemetry_")
        self.brain_root = Path(self.temp_dir) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.repo_dir = Path(self.temp_dir) / "target_repo"
        self.repo_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session(self, conv_id: str, steps: List[Dict[str, Any]], mtime_offset: Optional[float] = None) -> Path:
        import time
        sess_dir = self.brain_root / conv_id / ".system_generated" / "logs"
        sess_dir.mkdir(parents=True, exist_ok=True)
        transcript_path = sess_dir / "transcript.jsonl"
        with open(transcript_path, "w", encoding="utf-8") as f:
            for s in steps:
                f.write(json.dumps(s) + "\n")
        if mtime_offset is not None:
            new_mtime = time.time() - mtime_offset
            root_sess = self.brain_root / conv_id
            os.utime(root_sess, (new_mtime, new_mtime))
            os.utime(transcript_path, (new_mtime, new_mtime))
        return self.brain_root / conv_id

    # --- 1. --since-hours CLI & Mtime Filter ---
    def test_cli_build_parser_and_cmd_harvest_since_hours(self):
        """Validates that build_parser accepts --since-hours and passes it to TranscriptGraphHarvester."""
        from tools.distill import cli
        from tools.distill.harvester import TranscriptGraphHarvester
        import argparse

        parser = cli.build_parser()
        args = parser.parse_args(["harvest", str(self.repo_dir), "--since-hours", "24"])
        self.assertEqual(args.since_hours, 24)

        args_default = parser.parse_args(["harvest", str(self.repo_dir)])
        self.assertIsNone(args_default.since_hours)

        # Verify TranscriptGraphHarvester accepts since_hours
        harvester = TranscriptGraphHarvester(repo_path=self.repo_dir, since_hours=12)
        self.assertEqual(getattr(harvester, "since_hours", None), 12)

    def test_discover_candidates_since_hours_mtime_filter(self):
        """Validates that _discover_candidates filters out sessions older than since_hours."""
        import time
        from tools.distill.harvester import TranscriptGraphHarvester

        recent_dir = self._create_session("sess-recent", [{"step_index": 0}], mtime_offset=3600)
        old_dir = self._create_session("sess-old", [{"step_index": 0}], mtime_offset=172800)

        # 1. With since_hours=24: sess-old MUST be pruned
        h_filtered = TranscriptGraphHarvester(brain_roots=[self.brain_root], since_hours=24)
        candidates = h_filtered._discover_candidates()
        cand_names = [c.name for c in candidates]
        self.assertIn("sess-recent", cand_names)
        self.assertNotIn("sess-old", cand_names)

        # 2. With since_hours=None: both sessions returned
        h_all = TranscriptGraphHarvester(brain_roots=[self.brain_root], since_hours=None)
        all_cands = [c.name for c in h_all._discover_candidates()]
        self.assertIn("sess-recent", all_cands)
        self.assertIn("sess-old", all_cands)

    # --- 2. Cycle-Safe BFS Multi-Level Graph Expansion ---
    def test_expand_connected_session_graph_multi_level_lineage(self):
        """Validates BFS discovers descendants and ancestors across arbitrary depths (R -> C1 -> G1 -> GG1)."""
        from tools.distill import harvester

        self.assertTrue(
            hasattr(harvester, "_expand_connected_session_graph"),
            "harvester module must define _expand_connected_session_graph",
        )

        parent_to_children = {
            "R": ["C1"],
            "C1": ["G1"],
            "G1": ["GG1"],
        }
        child_to_parent = {
            "C1": "R",
            "G1": "C1",
            "GG1": "G1",
        }

        # Downward expansion from Root
        expanded_down = harvester._expand_connected_session_graph({"R"}, parent_to_children, child_to_parent)
        self.assertEqual(expanded_down, {"R", "C1", "G1", "GG1"})

        # Upward expansion from Great-Grandchild
        expanded_up = harvester._expand_connected_session_graph({"GG1"}, parent_to_children, child_to_parent)
        self.assertEqual(expanded_up, {"R", "C1", "G1", "GG1"})

    def test_expand_connected_session_graph_cycle_safety(self):
        """Validates BFS terminates cleanly on cyclic parent-child links (A <-> B) without looping."""
        from tools.distill import harvester

        self.assertTrue(hasattr(harvester, "_expand_connected_session_graph"))

        parent_to_children = {"A": ["B"], "B": ["A"]}
        child_to_parent = {"B": "A", "A": "B"}

        result = harvester._expand_connected_session_graph({"A"}, parent_to_children, child_to_parent)
        self.assertEqual(result, {"A", "B"})

    # --- 3. manage_task & Background Log Telemetry ---
    def test_extract_background_task_hangs_task_killed(self):
        """Validates extraction of TASK_KILLED signal with log tail when manage_task kill is invoked."""
        from tools.distill import harvester

        self.assertTrue(
            hasattr(harvester, "_extract_background_task_hangs"),
            "harvester module must define _extract_background_task_hangs",
        )
        self.assertTrue(
            hasattr(harvester, "_read_task_log_tail"),
            "harvester module must define _read_task_log_tail",
        )

        sess_dir = self.brain_root / "sess-kill-1"
        tasks_dir = sess_dir / ".system_generated" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)
        log_file = tasks_dir / "task-42.log"
        log_file.write_text("Build started\nCompiling TS\nFatal error: Out of memory\nKilled by supervisor\n", encoding="utf-8")

        # Test log tail helper directly
        tail = harvester._read_task_log_tail(sess_dir, "task-42", max_lines=2)
        self.assertEqual(tail, "Fatal error: Out of memory\nKilled by supervisor")

        step = {
            "created_at": "2026-11-12T05:00:00Z",
            "tool_calls": [
                {
                    "name": "manage_task",
                    "args": {"Action": "kill", "TaskId": "task-42"},
                }
            ],
        }

        signals = harvester._extract_background_task_hangs([step], sess_dir, "sess-kill-1")
        self.assertEqual(len(signals), 1)
        sig = signals[0]
        self.assertEqual(sig.error_type, "TASK_KILLED")
        self.assertEqual(sig.exit_code, -9)
        self.assertIn("task-42", sig.command_or_args)
        self.assertIn("Killed by supervisor", sig.error_output)

    def test_extract_background_task_hangs_consecutive_status_polling(self):
        """Validates that >= 3 consecutive status checks on same TaskId trigger BACKGROUND_HANG signal."""
        from tools.distill import harvester

        self.assertTrue(hasattr(harvester, "_extract_background_task_hangs"))

        sess_dir = self.brain_root / "sess-hang-1"
        sess_dir.mkdir(parents=True, exist_ok=True)

        steps = [
            {"tool_calls": [{"name": "manage_task", "args": {"Action": "status", "TaskId": "task-99"}}]},
            {"tool_calls": [{"name": "manage_task", "args": {"Action": "status", "TaskId": "task-99"}}]},
            {"tool_calls": [{"name": "manage_task", "args": {"Action": "status", "TaskId": "task-99"}}]},
            {"tool_calls": [{"name": "manage_task", "args": {"Action": "status", "TaskId": "task-99"}}]},
        ]

        # 2 checks: under threshold (count < 3) -> 0 signals
        sigs_2 = harvester._extract_background_task_hangs(steps[:2], sess_dir, "sess-hang-1")
        self.assertEqual(len(sigs_2), 0)

        # 3 checks: triggers BACKGROUND_HANG signal with retry_count=3
        sigs_3 = harvester._extract_background_task_hangs(steps[:3], sess_dir, "sess-hang-1")
        self.assertEqual(len(sigs_3), 1)
        self.assertEqual(sigs_3[0].error_type, "BACKGROUND_HANG")
        self.assertEqual(sigs_3[0].retry_count, 3)
        self.assertIn("task-99", sigs_3[0].command_or_args)
        self.assertIn("hung or required excessive polling", sigs_3[0].error_output)

        # 4 checks: does not double emit (only emitted at count == 3)
        sigs_4 = harvester._extract_background_task_hangs(steps, sess_dir, "sess-hang-1")
        self.assertEqual(len(sigs_4), 1)

    # --- 4. Two-Layer Workspace Affiliation & Routing ---
    def test_session_matches_project_layer1_workspace_uris(self):
        """Validates Layer 1: Authoritative workspaceUris match or reject with cross-workspace isolation."""
        from tools.distill import harvester

        self.assertTrue(
            hasattr(harvester, "_session_matches_project"),
            "harvester module must define _session_matches_project",
        )

        target_path = Path("/home/oguz/target-project")

        # 1. Matching workspaceUris returns True
        steps_match = [
            {"workspaceUris": ["file:///home/oguz/target-project"]},
            {"tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls"}}]},
        ]
        self.assertTrue(harvester._session_matches_project(steps_match, target_path))

        # 2. Foreign workspaceUris rejects even if a single tool call accesses target repo file
        steps_foreign = [
            {"workspaceUris": ["file:///home/oguz/other-project"]},
            {
                "tool_calls": [
                    {
                        "name": "read_file",
                        "args": {"Path": "/home/oguz/target-project/src/index.ts"},
                    }
                ]
            },
        ]
        self.assertFalse(
            harvester._session_matches_project(steps_foreign, target_path),
            "Cross-workspace read must NOT claim foreign workspace session",
        )

    def test_session_matches_project_layer2_dominant_step_ratio(self):
        """Validates Layer 2: Without workspaceUris, requires >= 30% tool-bearing steps matching target."""
        from tools.distill import harvester

        self.assertTrue(hasattr(harvester, "_session_matches_project"))
        target_path = Path("/home/oguz/target-project")

        # 10 tool steps: 1 step matches (10% < 30%) -> False
        steps_low = [
            {"tool_calls": [{"name": "run_command", "args": {"CommandLine": f"cat /home/oguz/target-project/foo"}}]}
        ] + [
            {"tool_calls": [{"name": "run_command", "args": {"CommandLine": "npm test"}}]} for _ in range(9)
        ]
        self.assertFalse(harvester._session_matches_project(steps_low, target_path))

        # 10 tool steps: 4 steps match (40% >= 30%) -> True
        steps_high = [
            {"tool_calls": [{"name": "run_command", "args": {"CommandLine": f"cat /home/oguz/target-project/file_{i}"}}]}
            for i in range(4)
        ] + [
            {"tool_calls": [{"name": "run_command", "args": {"CommandLine": "echo ok"}}]} for _ in range(6)
        ]
        self.assertTrue(harvester._session_matches_project(steps_high, target_path))

    def test_split_project_signals_classifies_hang_and_killed_as_harness(self):
        """Validates that manage_task, BACKGROUND_HANG, and TASK_KILLED route to harness/factory signals."""
        from tools.distill.harvester import TranscriptGraphHarvester
        from tools.distill.models import ToolFrictionSignal

        h = TranscriptGraphHarvester(repo_path=self.repo_dir)

        sig_kill = ToolFrictionSignal(
            signal_id="SIG-1",
            tool_name="manage_task",
            command_or_args="manage_task kill TaskId=task-1",
            error_output="Task task-1 was forcefully killed",
            error_type="TASK_KILLED",
            conversation_id="c1",
            step_index=1,
            timestamp="2026-11-12T00:00:00Z",
            exit_code=-9,
        )
        sig_hang = ToolFrictionSignal(
            signal_id="SIG-2",
            tool_name="manage_task",
            command_or_args="manage_task status TaskId=task-2 (polled 3x)",
            error_output="Background task task-2 hung",
            error_type="BACKGROUND_HANG",
            conversation_id="c1",
            step_index=2,
            timestamp="2026-11-12T00:00:00Z",
        )
        sig_app = ToolFrictionSignal(
            signal_id="SIG-3",
            tool_name="run_command",
            command_or_args="npm run test",
            error_output="AssertionError: expected true",
            error_type="TEST_FAILURE",
            conversation_id="c1",
            step_index=3,
            timestamp="2026-11-12T00:00:00Z",
            exit_code=1,
        )

        proj_sigs, harness_sigs = h._split_project_signals([sig_kill, sig_hang, sig_app], project_name="target_repo")

        # sig_kill and sig_hang MUST be routed to harness_sigs
        harness_ids = {s.signal_id for s in harness_sigs}
        self.assertIn("SIG-1", harness_ids)
        self.assertIn("SIG-2", harness_ids)

        # Only sig_app should be in proj_sigs
        proj_ids = {s.signal_id for s in proj_sigs}
        self.assertIn("SIG-3", proj_ids)
        self.assertNotIn("SIG-1", proj_ids)
        self.assertNotIn("SIG-2", proj_ids)


class TestDistillNavigationModelsAndToon(unittest.TestCase):
    """RED tests for Slice 1 Pillars 1, 2, 4 models & TOON rendering contracts."""

    def test_navigation_friction_signal_roundtrip_and_toon(self):
        from tools.distill.models import NavigationFrictionSignal

        sig = NavigationFrictionSignal(
            signal_type="EXPLORATION_BURST",
            session_id="sess-nav-12345678",
            role="coder",
            step_index=9,
            file_paths=["src/a.py", "src/b.py"],
            count=8,
            metric_value=8,
            summary="8 reads before first edit",
        )
        d = sig.to_dict()
        self.assertEqual(d["signal_type"], "EXPLORATION_BURST")
        self.assertEqual(d["role"], "coder")
        self.assertEqual(d["count"], 8)

        restored = NavigationFrictionSignal.from_dict({
            "signal_type": "REDUNDANT_READ",
            "session_id": "sess-min-01",
        })
        self.assertEqual(restored.role, "unknown")
        self.assertEqual(restored.file_paths, [])
        self.assertEqual(restored.metric_value, 0)

        toon = sig.to_toon()
        self.assertNotIn("\n", toon)
        self.assertIn("[NAV:EXPLORATION_BURST]", toon)
        self.assertIn("role=coder", toon)
        self.assertIn("step=9", toon)
        self.assertIn("count=8", toon)
        self.assertIn("metric=8", toon)

    def test_guardrail_gap_signal_roundtrip_and_toon(self):
        from tools.distill.models import GuardrailGapSignal

        gap = GuardrailGapSignal(
            gap_type="UNWIRED_GUARDRAIL",
            source_file="package.json",
            script_or_check="typecheck",
            summary="Script 'typecheck' not wired into CI or pre-commit hooks",
        )
        d = gap.to_dict()
        restored = GuardrailGapSignal.from_dict(d)
        self.assertEqual(restored.gap_type, "UNWIRED_GUARDRAIL")
        self.assertEqual(restored.script_or_check, "typecheck")
        self.assertEqual(
            gap.to_toon(),
            "- [GUARDRAIL:UNWIRED_GUARDRAIL] package.json (typecheck): Script 'typecheck' not wired into CI or pre-commit hooks",
        )

    def test_rule_inventory_item_roundtrip_and_toon(self):
        from tools.distill.models import RuleInventoryItem

        item = RuleInventoryItem(
            file_path=".edge/stations/coder.md",
            line_count=22,
            budget_limit=40,
            citation_count=3,
            status="OK",
        )
        d = item.to_dict()
        restored = RuleInventoryItem.from_dict(d)
        self.assertEqual(restored.file_path, ".edge/stations/coder.md")
        self.assertEqual(restored.budget_limit, 40)
        self.assertEqual(restored.status, "OK")
        toon = item.to_toon()
        self.assertIn(".edge/stations/coder.md", toon)
        self.assertIn("22", toon)
        self.assertIn("40", toon)
        self.assertIn("OK", toon)

    def test_friction_digest_new_fields_legacy_compat_and_fair_toon_budget(self):
        from tools.distill.models import (
            FrictionDigest,
            NavigationFrictionSignal,
            GuardrailGapSignal,
            RuleInventoryItem,
            ToolFrictionSignal,
            StationEscapeSignal,
            RepeatedEscalation,
        )

        # Legacy payload omitting new Slice 1 fields must deserialize cleanly
        legacy_restored = FrictionDigest.from_dict({
            "digest_id": "DIG-LEG",
            "project_path": "/home/oguz/app",
            "project_name": "app",
            "generated_at": "2026-11-17T00:00:00Z",
        })
        self.assertEqual(legacy_restored.navigation_frictions, [])
        self.assertEqual(legacy_restored.guardrail_gaps, [])
        self.assertEqual(legacy_restored.rule_inventory, [])

        # Massive distinct tool_frictions + station_escapes must NOT starve new sections
        distinct_frictions = [
            ToolFrictionSignal(
                signal_id=f"TF-{i}",
                tool_name="run_command",
                command_or_args=f"npm run check-module-{i:03d} --strict",
                error_output=f"Error TS2304 in module_{i:03d}.ts: cannot find name Foo{i}",
                conversation_id=f"cid-{i}",
                step_index=i,
                timestamp="2026-11-17T00:00:00Z",
                exit_code=1,
            )
            for i in range(60)
        ]
        distinct_escapes = [
            StationEscapeSignal(
                signal_id=f"ESC-{i}",
                station_role="EXAMINER",
                escape_type="ESCAPED_DEFECT",
                description=f"Defect escape {i} with long diagnostic explanation " + ("detail " * 8),
                evidence="gate failed",
                timestamp="2026-11-17T00:00:00Z",
                conversation_id=f"cid-esc-{i}",
                step_index=i,
            )
            for i in range(30)
        ]
        escalations = [
            RepeatedEscalation(
                escalation_id="REP-1",
                category="USER_INSTRUCTION_REPETITION",
                pattern_key="user corrective directive for coder",
                occurrence_count=3,
                occurrences=[{"cid": "c1", "step_index": 1, "text": "Never modify RED tests"}],
                rule_recommendation="Coder Invariant: Never modify RED tests",
                target_role="coder",
            )
        ]
        digest = FrictionDigest(
            digest_id="DIG-FAIR-01",
            project_path="/home/oguz/app",
            project_name="app",
            generated_at="2026-11-17T00:00:00Z",
            sessions_analyzed=["cid-1", "cid-2"],
            station_escapes=distinct_escapes,
            tool_frictions=distinct_frictions,
            repeated_escalations=escalations,
            total_tokens_estimate=12500,
            navigation_frictions=[
                NavigationFrictionSignal(
                    signal_type="EXPLORATION_BURST",
                    session_id="cid-1",
                    role="coder",
                    step_index=10,
                    file_paths=["src/a.ts"],
                    count=9,
                    metric_value=9,
                    summary="9 pre-edit reads",
                )
            ],
            guardrail_gaps=[
                GuardrailGapSignal(
                    gap_type="UNWIRED_GUARDRAIL",
                    source_file="package.json",
                    script_or_check="typecheck",
                    summary="typecheck not in CI",
                )
            ],
            rule_inventory=[
                RuleInventoryItem(
                    file_path=".edge/stations/coder.md",
                    line_count=18,
                    budget_limit=40,
                    citation_count=0,
                    status="ZERO_CITATIONS",
                )
            ],
        )

        roundtrip = FrictionDigest.from_dict(digest.to_dict())
        self.assertEqual(len(roundtrip.navigation_frictions), 1)
        self.assertEqual(len(roundtrip.guardrail_gaps), 1)
        self.assertEqual(len(roundtrip.rule_inventory), 1)

        toon = digest.to_toon(max_tokens=2000)
        self.assertLessEqual(len(toon), 8000)
        self.assertIn("user corrective directive for coder", toon)
        self.assertIn("## Navigation & Tool Economy", toon)
        self.assertIn("## Guardrail Gaps", toon)
        self.assertIn("## Rule Inventory", toon)
        self.assertTrue("12500" in toon or "12,500" in toon, "Expected non-zero total_tokens_estimate in TOON")
        self.assertIn("EXPLORATION_BURST", toon)
        self.assertIn("typecheck", toon)
        self.assertIn(".edge/stations/coder.md", toon)

    def test_repeated_escalation_to_toon_quote_snippets(self):
        from tools.distill.models import RepeatedEscalation

        long_quote = "Never\nmodify   existing\tRED tests " + ("x" * 100)
        esc = RepeatedEscalation(
            escalation_id="ESC-CODER-001",
            category="USER_INSTRUCTION_REPETITION",
            pattern_key="user corrective directive for coder",
            occurrence_count=3,
            occurrences=[
                {"cid": "c1", "step_index": 1, "text": long_quote},
                {"cid": "c2", "step_index": 2, "text": "Stop deleting assertions"},
                {"cid": "c3", "step_index": 3, "text": "Third quote should not overflow"},
            ],
            rule_recommendation="Coder Invariant: Adhere to TDD boundaries",
            target_role="coder",
        )
        toon = esc.to_toon()
        self.assertIn("count=3", toon)
        self.assertIn("target=coder", toon)
        self.assertIn("user corrective directive for coder", toon)
        self.assertIn("Coder Invariant: Adhere to TDD boundaries", toon)
        self.assertIn("| quotes:", toon)
        self.assertIn("Never modify existing RED tests", toon)
        self.assertIn("Stop deleting assertions", toon)
        self.assertNotIn("Third quote should not overflow", toon)
        self.assertNotIn("x" * 81, toon)

    def test_tool_friction_log_tail_last_meaningful_error_line(self):
        from tools.distill.models import ToolFrictionSignal, _render_tool_frictions_toon

        sig = ToolFrictionSignal(
            signal_id="SIG-KILL-1",
            tool_name="manage_task",
            command_or_args="manage_task kill TaskId=task-42",
            error_output=(
                "Task task-42 was forcefully killed by agent. Log tail:\n"
                "2026-11-17T01:00:00Z INFO Booting test worker\n"
                "Running pytest suite...\n"
                "\n"
                "AssertionError: expected status 200 got 500\n"
                "   \n"
            ),
            conversation_id="cid-kill-1",
            step_index=7,
            timestamp="2026-11-17T01:00:00Z",
            exit_code=-9,
            error_type="TASK_KILLED",
        )
        sig_toon = sig.to_toon()
        sec_toon = _render_tool_frictions_toon([sig]) or ""
        self.assertIn("AssertionError: expected status 200 got 500", sig_toon)
        self.assertIn("AssertionError: expected status 200 got 500", sec_toon)

    def test_render_insights_toon_dead_ends_and_guard_failures(self):
        from tools.distill.models import _render_insights_toon

        insights = [
            {
                "kind": "dead_end",
                "title": "Direct SQL in action",
                "reason": "Caused pool deadlock",
                "prohibited_rule": "Use repository.ts",
                "dead_end": "Direct SQL in action",
            },
            {
                "dead_end": "Legacy string approach without kind",
                "severity": "HIGH",
            },
            {
                "kind": "guard_failure",
                "state": "VERIFY",
                "message": "pytest failed with exit 1",
                "details": {"failed": 2, "file": "tests/test_app.py"},
            },
        ]
        rendered = _render_insights_toon(insights) or ""
        self.assertNotIn("- [INSIGHT] \n", rendered)
        self.assertFalse(rendered.rstrip().endswith("- [INSIGHT]"))
        self.assertIn("[DEAD_END]", rendered)
        self.assertIn("Direct SQL in action", rendered)
        self.assertIn("Caused pool deadlock", rendered)
        self.assertIn("Use repository.ts", rendered)
        self.assertIn("Legacy string approach without kind", rendered)
        self.assertIn("[GUARD_FAIL]", rendered)
        self.assertIn("VERIFY", rendered)
        self.assertIn("pytest failed with exit 1", rendered)


class TestDistillNavigationTelemetryHarvesters(unittest.TestCase):
    """RED tests for Slice 1 Pillar 1 deterministic navigation & token harvesters."""

    def test_exploration_burst_pre_edit_threshold_8_vs_7(self):
        from tools.distill.harvester import _extract_navigation_frictions_from_steps

        def _make_reads(n: int) -> List[Dict[str, Any]]:
            return [
                {"step_index": i, "tool_calls": [{"name": "read_file", "args": {"Path": f"src/file_{i}.py"}}]}
                for i in range(n)
            ]

        steps_7 = _make_reads(7) + [
            {"step_index": 7, "tool_calls": [{"name": "edit_file", "args": {"Path": "src/file_0.py"}}]}
        ]
        bursts_7 = [s for s in _extract_navigation_frictions_from_steps("cid-7", steps_7, role="coder") if s.signal_type == "EXPLORATION_BURST"]
        self.assertEqual(bursts_7, [])

        steps_8 = _make_reads(8) + [
            {"step_index": 8, "tool_calls": [{"name": "edit_file", "args": {"Path": "src/file_0.py"}}]}
        ]
        bursts_8 = [s for s in _extract_navigation_frictions_from_steps("cid-8", steps_8, role="coder") if s.signal_type == "EXPLORATION_BURST"]
        self.assertEqual(len(bursts_8), 1)
        self.assertEqual(bursts_8[0].count, 8)
        self.assertEqual(bursts_8[0].metric_value, 8)
        self.assertEqual(bursts_8[0].step_index, 8)
        self.assertEqual(bursts_8[0].role, "coder")
        self.assertLessEqual(len(bursts_8[0].file_paths), 5)

    def test_exploration_burst_zero_edit_threshold_10_vs_9(self):
        from tools.distill.harvester import _extract_navigation_frictions_from_steps

        steps_9 = [
            {"step_index": i, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": f"src/m{i}.py"}}]}
            for i in range(9)
        ]
        bursts_9 = [s for s in _extract_navigation_frictions_from_steps("cid-z9", steps_9) if s.signal_type == "EXPLORATION_BURST"]
        self.assertEqual(bursts_9, [])

        steps_10 = [
            {"step_index": i, "tool_calls": [{"name": "view_file", "args": {"AbsolutePath": f"src/m{i}.py"}}]}
            for i in range(10)
        ]
        bursts_10 = [s for s in _extract_navigation_frictions_from_steps("cid-z10", steps_10, role="researcher") if s.signal_type == "EXPLORATION_BURST"]
        self.assertEqual(len(bursts_10), 1)
        self.assertEqual(bursts_10[0].count, 10)
        self.assertEqual(bursts_10[0].metric_value, 10)
        self.assertEqual(bursts_10[0].step_index, 9)
        self.assertEqual(bursts_10[0].role, "researcher")

    def test_exploration_burst_run_command_anchored_vs_flag_argument_negative(self):
        from tools.distill.harvester import _extract_navigation_frictions_from_steps

        # 6 real reads + 3 non-search commands whose arguments contain 'grep'/'find' -> total 6 (< 8)
        steps_neg = [
            {"step_index": i, "tool_calls": [{"name": "read_file", "args": {"Path": f"src/f{i}.py"}}]}
            for i in range(6)
        ] + [
            {"step_index": 6, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "pytest -k grep"}}]},
            {"step_index": 7, "tool_calls": [{"name": "run_command", "args": {"CommandLine": 'git commit -m "find bug"'}}]},
            {"step_index": 8, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "uv run pytest -q tests/test_find.py"}}]},
            {"step_index": 9, "tool_calls": [{"name": "edit_file", "args": {"Path": "src/f0.py"}}]},
        ]
        bursts_neg = [s for s in _extract_navigation_frictions_from_steps("cid-cmd-neg", steps_neg) if s.signal_type == "EXPLORATION_BURST"]
        self.assertEqual(bursts_neg, [], "pytest -k grep and commit messages must NOT count as search calls")

        # 5 reads + 3 anchored WSL/chained search commands -> 8 (>= 8)
        steps_pos = [
            {"step_index": i, "tool_calls": [{"name": "read_file", "args": {"Path": f"src/f{i}.py"}}]}
            for i in range(5)
        ] + [
            {"step_index": 5, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "wsl --cd /home/oguz/app rg foo src/"}}]},
            {"step_index": 6, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "cd /home/oguz/app && git grep bar"}}]},
            {"step_index": 7, "tool_calls": [{"name": "run_command", "args": {"CommandLine": "wsl bash -c 'find src -name *.py'"}}]},
            {"step_index": 8, "tool_calls": [{"name": "write_file", "args": {"Path": "src/new.py"}}]},
        ]
        bursts_pos = [s for s in _extract_navigation_frictions_from_steps("cid-cmd-pos", steps_pos) if s.signal_type == "EXPLORATION_BURST"]
        self.assertEqual(len(bursts_pos), 1)
        self.assertEqual(bursts_pos[0].count, 8)

    def test_redundant_read_same_tuple_vs_chunked_ranges_and_post_edit_reset(self):
        from tools.distill.harvester import _extract_navigation_frictions_from_steps

        # 1. Chunked reads of distinct line ranges MUST NOT emit REDUNDANT_READ
        chunked_steps = [
            {"step_index": 0, "tool_calls": [{"name": "read_file", "args": {"Path": "src/big.py", "StartLine": 1, "EndLine": 100}}]},
            {"step_index": 1, "tool_calls": [{"name": "read_file", "args": {"Path": "src/big.py", "StartLine": 101, "EndLine": 200}}]},
            {"step_index": 2, "tool_calls": [{"name": "read_file", "args": {"Path": "src/big.py", "StartLine": 201, "EndLine": 300}}]},
        ]
        self.assertEqual(
            [s for s in _extract_navigation_frictions_from_steps("cid-chunk", chunked_steps) if s.signal_type == "REDUNDANT_READ"],
            [],
        )

        # 2. Read -> edit_file -> single post-edit read resets streak -> MUST NOT emit REDUNDANT_READ
        post_edit_steps = [
            {"step_index": 0, "tool_calls": [{"name": "read_file", "args": {"Path": "src/target.py", "StartLine": 1, "EndLine": 50}}]},
            {"step_index": 1, "tool_calls": [{"name": "edit_file", "args": {"Path": "src/target.py", "Target": "a", "Replacement": "b"}}]},
            {"step_index": 2, "tool_calls": [{"name": "read_file", "args": {"Path": "src/target.py", "StartLine": 1, "EndLine": 50}}]},
        ]
        self.assertEqual(
            [s for s in _extract_navigation_frictions_from_steps("cid-post-edit", post_edit_steps) if s.signal_type == "REDUNDANT_READ"],
            [],
        )

        # 3. Same (norm_path, start, end) read >= 2 without edit emits REDUNDANT_READ
        redundant_steps = [
            {"step_index": 0, "tool_calls": [{"name": "read_file", "args": {"Path": "src\\dup.py", "StartLine": 10, "EndLine": 40}}]},
            {"step_index": 3, "tool_calls": [{"name": "read_file", "args": {"Path": "src/dup.py", "StartLine": 10, "EndLine": 40}}]},
        ]
        red_sigs = [s for s in _extract_navigation_frictions_from_steps("cid-dup", redundant_steps) if s.signal_type == "REDUNDANT_READ"]
        self.assertEqual(len(red_sigs), 1)
        self.assertEqual(red_sigs[0].count, 2)
        self.assertEqual(red_sigs[0].metric_value, 2)
        self.assertEqual(red_sigs[0].file_paths, ["src/dup.py"])
        self.assertEqual(red_sigs[0].step_index, 3)

    def test_empty_search_chain_consecutive_turns_vs_single_and_mixed(self):
        from tools.distill.harvester import _extract_navigation_frictions_from_steps

        # 1. Single empty search turn followed by matching turn -> NO signal
        single_empty = [
            {"step_index": 0, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "grep_search", "args": {"Query": "foo"}}]},
            {"step_index": 1, "type": "GENERIC", "content": "Created At: 2026-11-17T00:00:00Z\nNo results found\n"},
            {"step_index": 2, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "grep_search", "args": {"Query": "bar"}}]},
            {"step_index": 3, "type": "GENERIC", "content": "src/bar.py:12: def bar():\n"},
        ]
        self.assertEqual(
            [s for s in _extract_navigation_frictions_from_steps("cid-es-1", single_empty) if s.signal_type == "EMPTY_SEARCH_CHAIN"],
            [],
        )

        # 2. Mixed parallel turn (1 empty + 1 matching) resets streak -> NO signal
        mixed_parallel = [
            {"step_index": 0, "type": "PLANNER_RESPONSE", "tool_calls": [
                {"name": "grep_search", "args": {"Query": "nope"}},
                {"name": "grep_search", "args": {"Query": "found"}},
            ]},
            {"step_index": 1, "type": "TOOL_RESULT", "content": "0 matches"},
            {"step_index": 2, "type": "TOOL_RESULT", "content": "src/found.py:5: found = True"},
            {"step_index": 3, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "find_by_name", "args": {"Pattern": "*missing*"}}]},
            {"step_index": 4, "type": "TOOL_RESULT", "content": "0 files"},
        ]
        self.assertEqual(
            [s for s in _extract_navigation_frictions_from_steps("cid-es-mix", mixed_parallel) if s.signal_type == "EMPTY_SEARCH_CHAIN"],
            [],
        )

        # 3. 3 consecutive empty search turns -> emits 1 EMPTY_SEARCH_CHAIN
        chain_steps = [
            {"step_index": 0, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "grep_search", "args": {"Query": "alpha"}}]},
            {"step_index": 1, "type": "GENERIC", "content": "Created At: 2026-11-17T00:00:00Z\nNo matches found\n"},
            {"step_index": 2, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "rg beta src/"}}]},
            {"step_index": 3, "type": "GENERIC", "content": "Command exited with code 1.\n"},
            {"step_index": 4, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "find_by_name", "args": {"Pattern": "*gamma*"}}]},
            {"step_index": 5, "type": "GENERIC", "content": "0 files"},
        ]
        chains = [s for s in _extract_navigation_frictions_from_steps("cid-es-3", chain_steps) if s.signal_type == "EMPTY_SEARCH_CHAIN"]
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0].count, 3)
        self.assertEqual(chains[0].metric_value, 3)
        self.assertEqual(chains[0].step_index, 0)

    def test_token_bloat_single_step_and_total_tokens_estimate(self):
        from tools.distill.harvester import _extract_navigation_frictions_from_steps, _estimate_sessions_tokens

        huge_output = "A" * 12000
        under_threshold = "B" * 11999
        steps = [
            {
                "step_index": 0,
                "type": "PLANNER_RESPONSE",
                "content": "reading two files",
                "tool_calls": [
                    {"name": "read_file", "args": {"Path": "src/a.py"}},
                    {"name": "read_file", "args": {"Path": "src/b.py"}},
                ],
            },
            {"step_index": 1, "type": "TOOL_RESULT", "content": huge_output},
            {"step_index": 2, "type": "TOOL_RESULT", "content": under_threshold},
        ]
        bloats = [s for s in _extract_navigation_frictions_from_steps("cid-bloat", steps) if s.signal_type == "TOKEN_BLOAT"]
        self.assertEqual(len(bloats), 1, "Must emit single TOKEN_BLOAT per oversized result step, not per parallel call")
        self.assertEqual(bloats[0].count, 1)
        self.assertEqual(bloats[0].metric_value, 12000)

        expected_chars = sum(
            len(str(st.get("content", "")))
            + sum(len(json.dumps(tc.get("args", {}), default=str)) + len(str(tc.get("name", ""))) for tc in st.get("tool_calls", []))
            for st in steps
        )
        est = _estimate_sessions_tokens(["cid-bloat"], {"cid-bloat": steps})
        self.assertEqual(est, expected_chars // 4)
        self.assertGreater(est, 0)

    def test_zero_exit_run_command_backward_compatibility(self):
        from tools.distill.harvester import _extract_tool_frictions_from_steps

        steps = [
            {"step_index": 0, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "rg missing src/"}}]},
            {"step_index": 1, "type": "GENERIC", "content": "Command exited with code 0.\n0 matches"},
        ]
        self.assertEqual(_extract_tool_frictions_from_steps("cid-z0", steps), [])


class TestDistillGuardrailAndRuleInventory(unittest.TestCase):
    """RED tests for Slice 1 Pillars 2 & 4.3 deterministic scanners."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_guardrails_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_guardrail_gaps_unwired_vs_wired_package_json(self):
        from tools.distill.harvester import _extract_guardrail_gaps

        (self.temp_dir / "package.json").write_text(
            json.dumps({"scripts": {"lint": "eslint .", "typecheck": "tsc --noEmit"}}),
            encoding="utf-8",
        )
        wf_dir = self.temp_dir / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("jobs:\n  test:\n    steps:\n      - run: npm run lint\n", encoding="utf-8")

        gaps = _extract_guardrail_gaps(self.temp_dir)
        unwired = [g for g in gaps if g.gap_type == "UNWIRED_GUARDRAIL"]
        missing = [g for g in gaps if g.gap_type == "MISSING_GUARDRAIL"]
        self.assertEqual(missing, [])
        self.assertEqual([g.script_or_check for g in unwired], ["typecheck"])
        self.assertEqual(unwired[0].source_file, "package.json")

    def test_extract_guardrail_gaps_pyproject_and_husky_hooks(self):
        from tools.distill.harvester import _extract_guardrail_gaps

        (self.temp_dir / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n\n[tool.ruff]\nline-length = 100\n\n[tool.mypy]\nstrict = true\n",
            encoding="utf-8",
        )
        husky_internal = self.temp_dir / ".husky" / "_"
        husky_internal.mkdir(parents=True)
        (husky_internal / "husky.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.temp_dir / ".husky" / "pre-commit").write_text("ruff check .\npytest -q\n", encoding="utf-8")

        gaps = _extract_guardrail_gaps(self.temp_dir)
        self.assertEqual([g.gap_type for g in gaps], ["UNWIRED_GUARDRAIL"])
        self.assertEqual(gaps[0].script_or_check, "mypy")
        self.assertEqual(gaps[0].source_file, "pyproject.toml")

    def test_extract_guardrail_gaps_missing_ci_and_precommit(self):
        from tools.distill.harvester import _extract_guardrail_gaps

        (self.temp_dir / "package.json").write_text(json.dumps({"scripts": {"test": "vitest"}}), encoding="utf-8")
        hooks_dir = self.temp_dir / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        (hooks_dir / "pre-commit.sample").write_text("#!/bin/sh\n", encoding="utf-8")

        gaps = _extract_guardrail_gaps(self.temp_dir)
        missing = [g for g in gaps if g.gap_type == "MISSING_GUARDRAIL"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].source_file, ".github/workflows")
        self.assertEqual(missing[0].script_or_check, "ci_and_precommit")

    def test_extract_guardrail_gaps_nonexistent_and_malformed_json_safe(self):
        from tools.distill.harvester import _extract_guardrail_gaps

        self.assertEqual(_extract_guardrail_gaps(self.temp_dir / "does-not-exist"), [])

        (self.temp_dir / "package.json").write_text("{broken json", encoding="utf-8")
        edge_dir = self.temp_dir / ".edge"
        edge_dir.mkdir(parents=True)
        (edge_dir / "brigade.json").write_text("{broken brigade", encoding="utf-8")

        gaps = _extract_guardrail_gaps(self.temp_dir)
        self.assertIsInstance(gaps, list)

    def test_extract_rule_inventory_project_vs_factory_mode_and_citations(self):
        from tools.distill.harvester import _extract_rule_inventory

        # 1. PROJECT_MODE: no agents/ dir -> scans .edge/stations/*.md + coding_standards.md
        proj_dir = self.temp_dir / "app_repo"
        stations_dir = proj_dir / ".edge" / "stations"
        stations_dir.mkdir(parents=True)
        (stations_dir / "coder.md").write_text("\n".join([f"rule {i}" for i in range(10)]), encoding="utf-8")
        (stations_dir / "surgeon.md").write_text("\n".join([f"rule {i}" for i in range(45)]), encoding="utf-8")
        (proj_dir / "coding_standards.md").write_text("\n".join([f"std {i}" for i in range(15)]), encoding="utf-8")

        sessions_steps = {
            "s1": [
                {"step_index": 0, "content": "Read .edge/stations/coder.md", "tool_calls": [
                    {"name": "read_file", "args": {"Path": str(stations_dir / "coder.md")}}
                ]},
            ]
        }
        items = _extract_rule_inventory(proj_dir, ["s1"], sessions_steps, mode="project")
        by_path = {it.file_path.replace("\\", "/"): it for it in items}
        self.assertFalse(any("agents/" in p for p in by_path), "PROJECT_MODE repo without agents/ must not include plugin agents/*.md")
        self.assertEqual(by_path[".edge/stations/coder.md"].line_count, 10)
        self.assertEqual(by_path[".edge/stations/coder.md"].budget_limit, 40)
        self.assertGreaterEqual(by_path[".edge/stations/coder.md"].citation_count, 1)
        self.assertEqual(by_path[".edge/stations/coder.md"].status, "OK")
        self.assertEqual(by_path[".edge/stations/surgeon.md"].line_count, 45)
        self.assertEqual(by_path[".edge/stations/surgeon.md"].status, "OVER_BUDGET")
        self.assertIsNone(by_path["coding_standards.md"].budget_limit)
        self.assertEqual(by_path["coding_standards.md"].citation_count, 0)
        self.assertEqual(by_path["coding_standards.md"].status, "ZERO_CITATIONS")

        # 2. FACTORY_MODE: agents/ dir exists -> scans agents/*.md (budget=60) + CAND-<id> citations
        fac_dir = self.temp_dir / "plugin_repo"
        (fac_dir / "agents").mkdir(parents=True)
        (fac_dir / "agents" / "coder.md").write_text("\n".join([f"line {i}" for i in range(65)]), encoding="utf-8")
        (fac_dir / "agents" / "examiner.md").write_text("CAND-1234abcd\nline 2\n", encoding="utf-8")
        fac_sessions = {
            "s2": [{"step_index": 0, "content": "Enforcing CAND-1234abcd during review"}]
        }
        fac_items = _extract_rule_inventory(fac_dir, ["s2"], fac_sessions, mode="factory")
        fac_by_path = {it.file_path.replace("\\", "/"): it for it in fac_items}
        self.assertEqual(fac_by_path["agents/coder.md"].budget_limit, 60)
        self.assertEqual(fac_by_path["agents/coder.md"].status, "OVER_BUDGET")
        self.assertEqual(fac_by_path["agents/examiner.md"].budget_limit, 60)
        self.assertGreaterEqual(fac_by_path["agents/examiner.md"].citation_count, 1)
        self.assertEqual(fac_by_path["agents/examiner.md"].status, "OK")


class TestDistillSwarmLinkingAndWorktreeMatching(unittest.TestCase):
    """RED tests for Slice 1 Pillar 3 & Pillar 4.1 harvester integration."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_swarm_"))
        self.brain_root = self.temp_dir / "brain"
        self.brain_root.mkdir(parents=True)
        self.repo_dir = self.temp_dir / "target-project"
        self.repo_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session(self, conv_id: str, steps: List[Dict[str, Any]]) -> Path:
        logs_dir = self.brain_root / conv_id / ".system_generated" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with open(logs_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
            for st in steps:
                f.write(json.dumps(st) + "\n")
        return self.brain_root / conv_id

    def test_inspect_step_relations_snake_case_multi_spawn_and_dedup(self):
        from tools.distill.harvester import TranscriptGraphHarvester

        h = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        c2p: Dict[str, str] = {}
        p2c: Dict[str, List[str]] = {}
        steps = [
            {
                "step_index": 1,
                "content": (
                    'Spawned {"conversation_id": "child-1111"} and {"conversation_id": "child-2222"} '
                    'and self {"conversation_id": "parent-0000"}'
                ),
            },
            {
                "step_index": 2,
                "content": 'Repeated {"conversation_id": "child-1111"} and camel {"conversationId": "child-3333"}',
            },
        ]
        h._inspect_step_relations(steps, "parent-0000", c2p, p2c)
        self.assertEqual(c2p.get("child-1111"), "parent-0000")
        self.assertEqual(c2p.get("child-2222"), "parent-0000")
        self.assertEqual(c2p.get("child-3333"), "parent-0000")
        self.assertNotIn("parent-0000", c2p)
        self.assertEqual(p2c.get("parent-0000"), ["child-1111", "child-2222", "child-3333"])

    def test_inspect_step_relations_swarm_two_step_role_and_uuid_vs_coordinator(self):
        from tools.distill.harvester import TranscriptGraphHarvester

        parent_uuid = "11111111-2222-3333-4444-555555555555"
        worker_cid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        coord_worker_cid = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"

        h = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        c2p: Dict[str, str] = {}
        p2c: Dict[str, List[str]] = {}

        worker_steps = [
            {"step_index": 0, "content": "[swarm] new board message"},
            {"step_index": 1, "content": f"Message for **@coder**: implement slice\nsender={parent_uuid}"},
        ]
        h._inspect_step_relations(worker_steps, worker_cid, c2p, p2c)
        self.assertEqual(c2p.get(worker_cid), parent_uuid)
        self.assertIn(worker_cid, p2c.get(parent_uuid, []))
        self.assertEqual(getattr(h, "_session_roles", {}).get(worker_cid), "coder")

        coord_steps = [
            {"step_index": 0, "content": "[swarm] new board message"},
            {"step_index": 1, "content": "Message for @examiner: review slice\nsender=coordinator"},
        ]
        h._inspect_step_relations(coord_steps, coord_worker_cid, c2p, p2c)
        self.assertNotIn(coord_worker_cid, c2p, "Generic sender=coordinator must NOT merge unrelated swarms")
        self.assertEqual(getattr(h, "_session_roles", {}).get(coord_worker_cid), "examiner")

    def test_session_matches_project_brigade_active_worktree_and_none_guard(self):
        from tools.distill.harvester import TranscriptGraphHarvester, _collect_worktree_aliases

        edge_dir = self.repo_dir / ".edge"
        edge_dir.mkdir(parents=True)

        # None active_worktree must not raise
        (edge_dir / "brigade.json").write_text(
            json.dumps({"active_worktree": None, "active_ticket": {"worktree_path": ""}}),
            encoding="utf-8",
        )
        self.assertEqual(_collect_worktree_aliases(self.repo_dir), [])

        # Windows UNC active_worktree matches WSL workspaceUri session
        wt_wsl = "/home/oguz/.treehouse/edge-10a21d/4/my-custom-wt"
        wt_unc = r"\\wsl.localhost\Ubuntu-24.04\home\oguz\.treehouse\edge-10a21d\4\my-custom-wt"
        (edge_dir / "brigade.json").write_text(
            json.dumps({"active_worktree": wt_unc}),
            encoding="utf-8",
        )
        aliases = _collect_worktree_aliases(self.repo_dir)
        self.assertIn(wt_wsl.lower(), aliases)

        self._create_session("sess-wt-match", [{"step_index": 0, "workspaceUris": [f"file://{wt_wsl}"]}])
        self._create_session("sess-wt-foreign", [{"step_index": 0, "workspaceUris": ["file:///home/oguz/other-project"]}])

        h = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        transcripts = h._discover_transcripts()
        sessions_steps, c2p, p2c = h._load_transcripts(transcripts)
        matched = h._find_matched_sessions(sessions_steps, self.repo_dir, p2c, c2p)
        self.assertIn("sess-wt-match", matched)
        self.assertNotIn("sess-wt-foreign", matched)

    def test_session_matches_project_symmetric_unc_and_treehouse_slot(self):
        from tools.distill.harvester import _session_matches_project, _matches_treehouse_slot

        target_path = Path("/home/oguz/target-project")

        self.assertTrue(_matches_treehouse_slot("/home/oguz/.treehouse/pool/slot-4/target-project", "target-project"))
        self.assertFalse(_matches_treehouse_slot("/home/oguz/.treehouse/pool/slot-4/other-project", "target-project"))
        self.assertFalse(_matches_treehouse_slot("/home/oguz/.treehouse/pool/slot-4/target-project-v2", "target-project"))

        # Symmetric UNC workspaceUri matching
        steps_unc = [{"step_index": 0, "workspaceUris": ["file://wsl.localhost/Ubuntu-24.04/home/oguz/target-project"]}]
        self.assertTrue(_session_matches_project(steps_unc, target_path))

        # Treehouse pool slot matching
        steps_slot = [{"step_index": 0, "workspaceUris": ["file:///home/oguz/.treehouse/pool/slot-2/target-project"]}]
        self.assertTrue(_session_matches_project(steps_slot, target_path))

        # Foreign Treehouse pool slot rejected
        steps_foreign_slot = [{"step_index": 0, "workspaceUris": ["file:///home/oguz/.treehouse/pool/slot-2/other-project"]}]
        self.assertFalse(_session_matches_project(steps_foreign_slot, target_path))

    def test_extract_flight_recorder_and_end_to_end_harvest_integration(self):
        from tools.distill.harvester import TranscriptGraphHarvester
        from tools.distill.models import _render_insights_toon

        fr_dir = self.repo_dir / ".edge" / "flight-recorder"
        fr_dir.mkdir(parents=True)
        (fr_dir / "TICK-42.json").write_text(
            json.dumps({
                "dead_ends": [
                    {"title": "Mutate primary repo", "reason": "Violates zero-touch", "prohibited_rule": "Use treehouse"}
                ],
                "guard_failures": [
                    {"state": "RED_TEST", "message": "collection error exit 2", "details": {"file": "tests/test_distill.py"}}
                ],
            }),
            encoding="utf-8",
        )
        (self.repo_dir / "package.json").write_text(json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8")

        steps = [
            {"step_index": 0, "workspaceUris": [f"file://{self.repo_dir.as_posix()}"]},
            {"step_index": 1, "tool_calls": [{"name": "read_file", "args": {"Path": "src/a.ts"}}]},
            {"step_index": 2, "tool_calls": [{"name": "read_file", "args": {"Path": "src/a.ts"}}]},
        ]
        self._create_session("sess-e2e-1", steps)

        h = TranscriptGraphHarvester(brain_roots=[self.brain_root], repo_path=self.repo_dir)
        digest = h.harvest(project_path=self.repo_dir)

        self.assertGreater(digest.total_tokens_estimate, 0)
        self.assertTrue(any(n.signal_type == "REDUNDANT_READ" for n in digest.navigation_frictions))
        self.assertTrue(any(g.gap_type == "MISSING_GUARDRAIL" for g in digest.guardrail_gaps))
        insights_toon = _render_insights_toon(digest.flight_recorder_insights) or ""
        self.assertIn("[DEAD_END]", insights_toon)
        self.assertIn("Mutate primary repo", insights_toon)
        self.assertIn("[GUARD_FAIL]", insights_toon)
        self.assertIn("RED_TEST", insights_toon)
        self.assertIn("collection error exit 2", insights_toon)


if __name__ == "__main__":
    unittest.main()
