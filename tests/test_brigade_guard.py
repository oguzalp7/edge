#!/usr/bin/env python3
"""
Unit Tests for Brigade Guard & Station Persistence Protocol.
"""

import unittest
from unittest.mock import patch
import os
import json
import tempfile
from pathlib import Path
import sys

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.brigade import orchestrator_guard as guard


class TestBrigadeGuard(unittest.TestCase):
    def setUp(self):
        # Create an isolated temporary file for active stations
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_stations_file = Path(self.temp_dir.name) / "edge_active_stations.json"
        self.orig_file = guard.ACTIVE_STATIONS_FILE
        guard.ACTIVE_STATIONS_FILE = self.temp_stations_file

    def tearDown(self):
        guard.ACTIVE_STATIONS_FILE = self.orig_file
        self.temp_dir.cleanup()

    def test_normalize_role(self):
        self.assertIsNone(guard.normalize_role("expediter"))
        self.assertEqual(guard.normalize_role("Standards Examiner"), "EXAMINER")
        self.assertEqual(guard.normalize_role("spec_examiner"), "EXAMINER")
        self.assertEqual(guard.normalize_role("Examiner"), "EXAMINER")
        self.assertEqual(guard.normalize_role("Code Reviewer"), "EXAMINER")
        self.assertEqual(guard.normalize_role("Sous Chef"), "EXAMINER")
        self.assertEqual(guard.normalize_role("Maitre d"), "EXAMINER")
        self.assertEqual(guard.normalize_role("Refactor Surgeon"), "SURGEON")
        self.assertEqual(guard.normalize_role("Coder"), "CODER")
        self.assertEqual(guard.normalize_role("Seam Architect"), "SEAM_ARCHITECT")
        self.assertEqual(guard.normalize_role("Spec Writer"), "SPEC_WRITER")
        self.assertEqual(guard.normalize_role("Ecosystem & Recon Specialist"), "RESEARCHER")
        self.assertEqual(guard.normalize_role("QA/E2E test agent"), "QA_ENGINEER")
        self.assertEqual(guard.normalize_role("Sommelier"), "QA_ENGINEER")
        self.assertEqual(guard.normalize_role("e2e_tester"), "QA_ENGINEER")

    def test_orchestrator_denied_write(self):
        payload = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/actions/foo.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("Yeşil Alandadır", res["reason"])

    def test_antigravity_orchestrator_denied_write_file_and_edit_file(self):
        # Native write_file with Path
        payload_write = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": "src/actions/foo.ts", "Content": "code"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_write)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("Yeşil Alandadır", res["reason"])

        # Native edit_file with Path
        payload_edit = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "edit_file",
                "args": {"Path": "src/components/bookings/PhoneBookingManager.tsx", "Target": "foo", "Replacement": "bar"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_edit)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("Yeşil Alandadır", res["reason"])

    def test_antigravity_orchestrator_read_file_lean_context_guard(self):
        # Denied reading production code
        payload_read_code = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "read_file",
                "args": {"Path": "src/components/bookings/PhoneBookingManager.tsx"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_read_code)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("EDGE ORCHESTRATOR LEAN CONTEXT GUARD", res["reason"])
            self.assertIn("RESEARCHER", res["reason"])

        # Denied reading test files
        payload_read_test = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "read_file",
                "args": {"Path": "tests/unit/bookings/phone-booking.test.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_read_test)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("EDGE ORCHESTRATOR LEAN CONTEXT GUARD", res["reason"])

        # Allowed reading specs and .edge state
        payload_read_spec = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "read_file",
                "args": {"Path": "specs/feature-01.md"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_read_spec)
            self.assertEqual(res["decision"], "allow")

        # Allowed reading coding_standards
        payload_read_standards = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "read_file",
                "args": {"Path": "coding_standards.md"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_read_standards)
            self.assertEqual(res["decision"], "allow")

        # Allowed reading brain artifacts
        payload_read_brain = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "read_file",
                "args": {"Path": "C:/Users/oguz_/.gemini/antigravity/brain/sess-1/plan.md"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_read_brain)
            self.assertEqual(res["decision"], "allow")

    def test_antigravity_native_invoke_subagent_role_extraction(self):
        # Native invoke_subagent with Role parameter
        payload_spawn = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Role": "Seam Architect", "TypeName": "self", "Prompt": "Write red test"}
            }
        }
        res = guard.handle_pre_tool(payload_spawn)
        self.assertEqual(res["decision"], "allow")

    def test_orchestrator_allowed_artifact_write(self):
        payload_artifact = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "C:/Users/oguz_/.gemini/antigravity/brain/orch-1/plan.md"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_artifact)
            self.assertEqual(res["decision"], "allow")

        payload_edge = {
            "conversationId": "orch-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": ".edge/checkpoint.json"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_tool(payload_edge)
            self.assertEqual(res["decision"], "allow")

    def test_examiners_denied_any_write(self):
        for examiner in ["EXAMINER", "RESEARCHER"]:
            payload = {
                "conversationId": "exam-1",
                "toolCall": {
                    "name": "replace_file_content",
                    "args": {"TargetFile": "anything.ts"}
                }
            }
            with patch.object(guard, "detect_session_role", return_value=(examiner, "test")):
                res = guard.handle_pre_tool(payload)
                self.assertEqual(res["decision"], "deny")
                self.assertIn("salt-okunur", res["reason"])

    def test_examiner_legacy_aliases_normalized_and_denied_write(self):
        for legacy_role in ["standards_examiner", "spec_examiner", "sous chef", "maitre d"]:
            canonical = guard.normalize_role(legacy_role)
            self.assertEqual(canonical, "EXAMINER")
            payload = {
                "conversationId": "exam-legacy",
                "toolCall": {
                    "name": "write_file",
                    "args": {"TargetFile": "src/actions/booking.ts"}
                }
            }
            with patch.object(guard, "detect_session_role", return_value=(canonical, "test")):
                res = guard.handle_pre_tool(payload)
                self.assertEqual(res["decision"], "deny")
                self.assertIn("salt-okunur", res["reason"])

    def test_spec_writer_boundary(self):
        # Denied in src/
        payload_deny = {
            "conversationId": "spec-w-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/components/modal.tsx"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SPEC_WRITER", "test")):
            res = guard.handle_pre_tool(payload_deny)
            self.assertEqual(res["decision"], "deny")

        # Allowed in .lavish/
        payload_allow = {
            "conversationId": "spec-w-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": ".lavish/booking.html"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SPEC_WRITER", "test")):
            res = guard.handle_pre_tool(payload_allow)
            self.assertEqual(res["decision"], "allow")

    def test_seam_architect_boundary(self):
        # Denied in src/ implementation
        payload_deny = {
            "conversationId": "seam-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/actions/impl.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SEAM_ARCHITECT", "test")):
            res = guard.handle_pre_tool(payload_deny)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("TDD SEAM GUARD", res["reason"])

        # Allowed in tests/
        payload_allow_test = {
            "conversationId": "seam-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "tests/unit/booking.test.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SEAM_ARCHITECT", "test")):
            res = guard.handle_pre_tool(payload_allow_test)
            self.assertEqual(res["decision"], "allow")

        # Allowed in src/types/ contracts
        payload_allow_contract = {
            "conversationId": "seam-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/types/booking.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SEAM_ARCHITECT", "test")):
            res = guard.handle_pre_tool(payload_allow_contract)
            self.assertEqual(res["decision"], "allow")

    def test_coder_test_immutability(self):
        # Denied in tests/
        payload_deny = {
            "conversationId": "coder-1",
            "toolCall": {
                "name": "replace_file_content",
                "args": {"TargetFile": "tests/unit/booking.test.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("CODER", "test")):
            res = guard.handle_pre_tool(payload_deny)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("TEST IMMUTABILITY GUARD", res["reason"])

        # Allowed in src/
        payload_allow = {
            "conversationId": "coder-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/actions/booking.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("CODER", "test")):
            res = guard.handle_pre_tool(payload_allow)
            self.assertEqual(res["decision"], "allow")

    def test_surgeon_migration_gate(self):
        # Denied in src/db/schema/
        payload_deny = {
            "conversationId": "surg-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/db/schema/users.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SURGEON", "test")):
            res = guard.handle_pre_tool(payload_deny)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("MIGRATIONGATE GUARD", res["reason"])

        # Allowed in src/lib/repo.ts
        payload_allow = {
            "conversationId": "surg-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/lib/users/repository.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("SURGEON", "test")):
            res = guard.handle_pre_tool(payload_allow)
            self.assertEqual(res["decision"], "allow")

    def test_anti_graveyard_station_reuse(self):
        # Step 1: No examiner active yet -> invoke_subagent allowed
        payload_first = {
            "conversationId": "orch-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "Examiner", "Prompt": "Review diff"}])
                }
            }
        }
        res1 = guard.handle_pre_tool(payload_first)
        self.assertEqual(res1["decision"], "allow")

        # Step 2: Register the spawned examiner subagent
        guard.register_station(
            conversation_id="conv-exam-456",
            role="EXAMINER",
            parent_cid="orch-parent"
        )

        # Step 3: Second call to invoke_subagent for Examiner (using legacy alias) -> HARD DENIAL
        payload_second = {
            "conversationId": "orch-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "Standards Examiner", "Prompt": "Check standards"}])
                }
            }
        }
        res2 = guard.handle_pre_tool(payload_second)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("PERSISTENT STATION REUSE REQUIRED", res2["reason"])
        self.assertIn("conv-exam-456", res2["reason"])
        self.assertIn("send_message", res2["reason"])

        # Step 4: Spawning another role (e.g. Surgeon) is allowed
        payload_surgeon = {
            "conversationId": "orch-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "Surgeon", "Prompt": "Refactor repository"}])
                }
            }
        }
        res3 = guard.handle_pre_tool(payload_surgeon)
        self.assertEqual(res3["decision"], "allow")


    def test_qa_engineer_boundary(self):
        # Denied in src/
        payload_deny = {
            "conversationId": "qa-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "src/actions/booking.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_tool(payload_deny)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("QA BOUNDARY GUARD", res["reason"])

        # Allowed in tests/e2e/ or .edge/qa/
        payload_allow = {
            "conversationId": "qa-1",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "tests/e2e/booking.spec.ts"}
            }
        }
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_tool(payload_allow)
            self.assertEqual(res["decision"], "allow")

    def test_pre_invocation_injections(self):
        # Orchestrator
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_invocation({})
            self.assertTrue(len(res["injectSteps"]) > 0)
            msg = res["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("Sovereign Commander", msg)
            self.assertIn("Canonical Brigade Stations", msg)
            self.assertIn("Anti-Graveyard Protocol", msg)

        # Examiner station worker
        with patch.object(guard, "detect_session_role", return_value=("EXAMINER", "test")):
            res = guard.handle_pre_invocation({})
            self.assertTrue(len(res["injectSteps"]) > 0)
            msg = res["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("persistent EXAMINER station worker", msg)

        # QA Engineer station worker
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_invocation({})
            self.assertTrue(len(res["injectSteps"]) > 0)
            msg = res["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("Sommelier & E2E QA Engineer", msg)

    def test_post_tool_subagent_registration(self):
        # Create mock transcript with real escaped JSONL
        transcript_file = Path(self.temp_dir.name) / "transcript.jsonl"
        subagent_cid = "13ab377f-3853-4635-8a03-672240001766"
        parent_cid = "orch-parent-123"

        real_line = json.dumps({
            "step_index": 257,
            "source": "MODEL",
            "type": "GENERIC",
            "status": "DONE",
            "created_at": "2026-10-14T06:06:24-04:00",
            "content": f'Created the following subagents:\n{{\n  "conversationId": "{subagent_cid}",\n  "logAbsoluteUri": "..."\n}}'
        })

        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(real_line + "\n")

        payload = {
            "conversationId": parent_cid,
            "transcriptPath": str(transcript_file),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "SPEC_WRITER", "Prompt": "Write spec"}])
                }
            }
        }

        # 1. Run handle_post_tool
        res = guard.handle_post_tool(payload)
        self.assertEqual(res, {})

        # 2. Check if station was registered
        match = guard.find_active_station("SPEC_WRITER", parent_cid=parent_cid)
        self.assertIsNotNone(match, "Station SPEC_WRITER should have been registered by handle_post_tool!")
        cid, info = match
        self.assertEqual(cid, subagent_cid)
        self.assertEqual(info["role"], "SPEC_WRITER")

        # 3. Verify that next invoke_subagent for SPEC_WRITER is DENIED
        pre_payload = {
            "conversationId": parent_cid,
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "SPEC_WRITER", "Prompt": "Update spec"}])
                }
            }
        }
        pre_res = guard.handle_pre_tool(pre_payload)
        self.assertEqual(pre_res["decision"], "deny")
        self.assertIn("PERSISTENT STATION REUSE REQUIRED", pre_res["reason"])
        self.assertIn(subagent_cid, pre_res["reason"])
        self.assertIn("send_message", pre_res["reason"])


class TestStationStorePersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp_dir.name) / "edge_active_stations.json"
        self.store = guard.StationStore(self.store_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_atomic_initialization_on_missing_file(self):
        # Ensure file does not exist initially
        self.assertFalse(self.store_path.exists())

        # Loading missing file must trigger atomic baseline template creation
        data = self.store.load()

        # Verify file now exists on disk
        self.assertTrue(self.store_path.exists(), "Station store file should be created on disk when missing")

        # Verify envelope and disk content conform to v1.0 schema
        self.assertEqual(data.get("version"), "1.0")
        self.assertIn("initializedAt", data)
        self.assertEqual(data.get("sessions"), {})
        self.assertEqual(data.get("stations"), {})

        # Verify raw JSON on disk
        with open(self.store_path, "r", encoding="utf-8") as f:
            disk_json = json.load(f)
        self.assertEqual(disk_json.get("version"), "1.0")
        self.assertIn("initializedAt", disk_json)
        self.assertEqual(disk_json.get("sessions"), {})
        self.assertEqual(disk_json.get("stations"), {})

    def test_legacy_flat_dictionary_migration(self):
        # Seed store with legacy flat format (no version, stations at root)
        legacy_data = {
            "legacy-cid-1": {
                "role": "EXPEDITER",
                "parentConversationId": "orch-1",
                "status": "IDLE"
            }
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        # Load should migrate to v1.0 template while preserving transparent access
        data = self.store.load()

        # 1. Transparent dictionary access (legacy compatibility)
        self.assertIn("legacy-cid-1", data)
        self.assertEqual(data["legacy-cid-1"]["role"], "EXPEDITER")
        self.assertEqual(data.get_stations()["legacy-cid-1"]["role"], "EXPEDITER")

        # 2. V1.0 structure
        self.assertEqual(data.get("version"), "1.0")
        self.assertIn("sessions", data)
        self.assertIn("stations", data)

        # 3. Disk migration verification
        with open(self.store_path, "r", encoding="utf-8") as f:
            migrated_disk = json.load(f)
        self.assertEqual(migrated_disk.get("version"), "1.0")
        self.assertIn("legacy-cid-1", migrated_disk.get("stations", {}))
        self.assertNotIn("legacy-cid-1", [k for k in migrated_disk if k not in ("version", "initializedAt", "sessions", "stations")])


class TestTranscriptStationScanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.brain_root = Path(self.temp_dir.name) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.scanner = guard.TranscriptStationScanner(self.brain_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_invoke_subagent_pairing(self):
        parent_dir = self.brain_root / "orch-parent-456"
        parent_dir.mkdir(parents=True, exist_ok=True)
        parent_transcript = parent_dir / "transcript.jsonl"
        subagent_cid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

        lines = [
            json.dumps({
                "step_index": 10,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [
                    {
                        "name": "invoke_subagent",
                        "args": {
                            "Subagents": [{"Role": "Refactor Surgeon", "Prompt": "Refactor repository"}]
                        }
                    }
                ]
            }),
            json.dumps({
                "step_index": 11,
                "source": "MODEL",
                "type": "GENERIC",
                "content": f'Created the following subagents:\n{{\n  "conversationId": "{subagent_cid}",\n  "logAbsoluteUri": "..."\n}}'
            })
        ]
        with open(parent_transcript, "w", encoding="utf-8") as f:
            for l in lines:
                f.write(l + "\n")

        pairs = self.scanner.discover_session_stations(parent_transcript)
        self.assertEqual(len(pairs), 1)
        cid, role = pairs[0]
        self.assertEqual(cid, subagent_cid)
        self.assertEqual(guard.normalize_role(role), "SURGEON")

    def test_calculate_token_heat_exact(self):
        # 1. GREEN Zone (< 45k tokens)
        sub_green_cid = "subagent-green-111"
        green_log_dir = self.brain_root / sub_green_cid / ".system_generated" / "logs"
        green_log_dir.mkdir(parents=True, exist_ok=True)
        green_transcript = green_log_dir / "transcript.jsonl"
        with open(green_transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 42,
                "source": "MODEL",
                "content": "Finished ticket",
                "input_tokens": 20000,
                "cache_read_tokens": 10000
            }) + "\n")

        heat_green = self.scanner.calculate_subagent_heat(sub_green_cid)
        self.assertEqual(heat_green.tokens, 30000)
        self.assertEqual(heat_green.heat_zone, "GREEN")

        # 2. YELLOW Zone (45k - 75k tokens)
        sub_yellow_cid = "subagent-yellow-222"
        yellow_log_dir = self.brain_root / sub_yellow_cid / ".system_generated" / "logs"
        yellow_log_dir.mkdir(parents=True, exist_ok=True)
        yellow_transcript = yellow_log_dir / "transcript.jsonl"
        with open(yellow_transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 80,
                "source": "MODEL",
                "content": "Working...",
                "input_tokens": 40000,
                "cache_read_tokens": 15000
            }) + "\n")

        heat_yellow = self.scanner.calculate_subagent_heat(sub_yellow_cid)
        self.assertEqual(heat_yellow.tokens, 55000)
        self.assertEqual(heat_yellow.heat_zone, "YELLOW")

        # 3. RED Zone (> 75k tokens)
        sub_red_cid = "subagent-red-333"
        red_log_dir = self.brain_root / sub_red_cid / ".system_generated" / "logs"
        red_log_dir.mkdir(parents=True, exist_ok=True)
        red_transcript = red_log_dir / "transcript.jsonl"
        with open(red_transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 120,
                "source": "MODEL",
                "content": "Saturated...",
                "input_tokens": 60000,
                "cache_read_tokens": 25000
            }) + "\n")

        heat_red = self.scanner.calculate_subagent_heat(sub_red_cid)
        self.assertEqual(heat_red.tokens, 85000)
        self.assertEqual(heat_red.heat_zone, "RED")


class TestStationSelectorRotation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp_dir.name) / "edge_active_stations.json"
        self.store = guard.StationStore(self.store_path)
        self.brain_root = Path(self.temp_dir.name) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.scanner = guard.TranscriptStationScanner(self.brain_root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_case_a_unassigned_role_spawn_allowed(self):
        empty_data = {
            "version": "1.0",
            "initializedAt": "2026-10-15T00:00:00Z",
            "sessions": {},
            "stations": {}
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(empty_data, f)

        res = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "Seam Architect"
        )
        self.assertEqual(res["decision"], "allow")

    def test_case_b_green_station_denied_with_redirection(self):
        store_data = {
            "version": "1.0",
            "initializedAt": "2026-10-15T00:00:00Z",
            "sessions": {},
            "stations": {
                "cid-coder-1": {
                    "conversationId": "cid-coder-1",
                    "role": "CODER",
                    "canonicalRole": "CODER",
                    "parentConversationId": "orch-parent",
                    "status": "IDLE",
                    "tokenHeat": {
                        "tokens": 30000,
                        "heatZone": "GREEN"
                    }
                }
            }
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(store_data, f)

        res = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "Coder"
        )
        self.assertEqual(res["decision"], "deny")
        self.assertIn("PERSISTENT STATION REUSE REQUIRED", res["reason"])
        self.assertIn("cid-coder-1", res["reason"])
        self.assertIn("send_message", res["reason"])

    def test_case_b_multi_worker_selects_greenest(self):
        store_data = {
            "version": "1.0",
            "initializedAt": "2026-10-15T00:00:00Z",
            "sessions": {},
            "stations": {
                "cid-qa-heavy": {
                    "conversationId": "cid-qa-heavy",
                    "role": "QA_ENGINEER",
                    "canonicalRole": "QA_ENGINEER",
                    "parentConversationId": "orch-parent",
                    "status": "IDLE",
                    "tokenHeat": {
                        "tokens": 40000,
                        "heatZone": "GREEN"
                    }
                },
                "cid-qa-fresh": {
                    "conversationId": "cid-qa-fresh",
                    "role": "QA_ENGINEER",
                    "canonicalRole": "QA_ENGINEER",
                    "parentConversationId": "orch-parent",
                    "status": "IDLE",
                    "tokenHeat": {
                        "tokens": 22000,
                        "heatZone": "GREEN"
                    }
                }
            }
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(store_data, f)

        res = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "QA_ENGINEER"
        )
        self.assertEqual(res["decision"], "deny")
        self.assertIn("cid-qa-fresh", res["reason"])
        self.assertNotIn("cid-qa-heavy", res["reason"])

    def test_case_c_saturated_worker_allows_rotation(self):
        store_data = {
            "version": "1.0",
            "initializedAt": "2026-10-15T00:00:00Z",
            "sessions": {},
            "stations": {
                "cid-spec-exhausted": {
                    "conversationId": "cid-spec-exhausted",
                    "role": "SPEC_WRITER",
                    "canonicalRole": "SPEC_WRITER",
                    "parentConversationId": "orch-parent",
                    "status": "IDLE",
                    "tokenHeat": {
                        "tokens": 55000,
                        "heatZone": "YELLOW"
                    }
                }
            }
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(store_data, f)

        res = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "Spec Writer"
        )
        self.assertEqual(res["decision"], "allow")

        envelope = self.store.load()
        self.assertIn(
            envelope["stations"]["cid-spec-exhausted"]["status"],
            ["EXHAUSTED", "ROTATED"]
        )

    def test_constants_ssot_heat_thresholds(self):
        self.assertTrue(hasattr(guard, "GREEN_HEAT_THRESHOLD"), "GREEN_HEAT_THRESHOLD must be defined in orchestrator_guard")
        self.assertTrue(hasattr(guard, "YELLOW_HEAT_THRESHOLD"), "YELLOW_HEAT_THRESHOLD must be defined in orchestrator_guard")
        self.assertEqual(guard.GREEN_HEAT_THRESHOLD, 45_000)
        self.assertEqual(guard.YELLOW_HEAT_THRESHOLD, 75_000)

    def test_45k_green_heat_threshold_rotation(self):
        # 1. Worker with 44,999 tokens in transcript is GREEN and must be reused (deny spawn)
        cid = "cid-coder-sub45"
        log_dir = self.brain_root / cid / ".system_generated" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 1,
                "source": "MODEL",
                "input_tokens": 40_000,
                "cache_read_tokens": 4_999
            }) + "\n")

        store_data = {
            "version": "1.0",
            "initializedAt": "2026-10-15T00:00:00Z",
            "sessions": {},
            "stations": {
                cid: {
                    "conversationId": cid,
                    "role": "CODER",
                    "canonicalRole": "CODER",
                    "parentConversationId": "orch-parent",
                    "status": "IDLE"
                }
            }
        }
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(store_data, f)

        res = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "Coder"
        )
        self.assertEqual(res["decision"], "deny")
        self.assertIn(cid, res["reason"])

        # 2. Worker with 45,001 tokens in transcript is saturated (YELLOW) and must allow rotation (spawn allowed, marked EXHAUSTED)
        with open(log_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 2,
                "source": "MODEL",
                "input_tokens": 40_000,
                "cache_read_tokens": 5_001
            }) + "\n")

        res_rot = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "Coder"
        )
        self.assertEqual(res_rot["decision"], "allow")
        envelope = self.store.load()
        self.assertIn(
            envelope["stations"][cid]["status"],
            ["EXHAUSTED", "ROTATED"]
        )

    def test_handle_post_tool_direct_response_extraction_dict(self):
        # Must extract conversationId directly from payload["toolResponse"] dict
        # without requiring transcript.jsonl to exist on disk!
        with patch.object(guard, "ACTIVE_STATIONS_FILE", self.store_path):
            payload = {
                "toolCall": {
                    "name": "invoke_subagent",
                    "args": {"role": "SURGEON"}
                },
                "toolResponse": {
                    "conversationId": "cid-surgeon-direct-999"
                },
                "conversationId": "orch-parent"
            }
            res = guard.handle_post_tool(payload)
            envelope = self.store.load()
            self.assertIn("cid-surgeon-direct-999", envelope["stations"])
            st = envelope["stations"]["cid-surgeon-direct-999"]
            self.assertEqual(st["canonicalRole"], "SURGEON")

    def test_handle_post_tool_direct_response_extraction_str(self):
        # Must extract conversationId directly from payload["toolResponse"] string
        # without requiring transcript.jsonl to exist on disk!
        with patch.object(guard, "ACTIVE_STATIONS_FILE", self.store_path):
            payload = {
                "toolCall": {
                    "name": "invoke_subagent",
                    "args": {"role": "CODER"}
                },
                "toolResponse": '{"conversationId": "cid-coder-str-888", "status": "started"}',
                "conversationId": "orch-parent"
            }
            res = guard.handle_post_tool(payload)
            envelope = self.store.load()
            self.assertIn("cid-coder-str-888", envelope["stations"])
            st = envelope["stations"]["cid-coder-str-888"]
            self.assertEqual(st["canonicalRole"], "CODER")

    def test_sync_repo_brigade_station(self):
        # sync_repo_brigade_station atomically creates/updates <repo>/.edge/brigade.json
        self.assertTrue(hasattr(guard, "sync_repo_brigade_station"), "sync_repo_brigade_station must exist")
        repo_dir = Path(self.temp_dir.name) / "test_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)

        ok = guard.sync_repo_brigade_station(repo_dir, "SURGEON", "cid-surgeon-sync-777")
        self.assertTrue(ok)

        brigade_json_path = repo_dir / ".edge" / "brigade.json"
        self.assertTrue(brigade_json_path.exists())
        with open(brigade_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("stations", data)
        self.assertIn("SURGEON", data["stations"])
        self.assertEqual(data["stations"]["SURGEON"]["conversation_id"], "cid-surgeon-sync-777")

    def test_station_selector_repo_fallback(self):
        # When runtime store has no record, but <repo>/.edge/brigade.json does,
        # StationSelector fallback detects the green station and denies spawn
        repo_dir = Path(self.temp_dir.name) / "fallback_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        guard.sync_repo_brigade_station(repo_dir, "CODER", "cid-repo-coder-555")

        # Mock scanner to return green tokens for this repo station
        self.scanner.calculate_subagent_heat = MagicMock(
            return_value=guard.TokenHeat(tokens=20_000, heat_zone="GREEN")
        )

        res = guard.StationSelector.evaluate_spawn_request(
            self.store, self.scanner, "orch-parent", "Coder", repo_path=repo_dir
        )
        self.assertEqual(res["decision"], "deny")
        self.assertIn("cid-repo-coder-555", res["reason"])


class TestAfkSessionArmor(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.copy()
        os.environ.pop("EDGE_AFK", None)
        os.environ.pop("EDGE_AFK_MODE", None)

        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.temp_stations_file = self.temp_path / "edge_active_stations.json"
        self.orig_file = guard.ACTIVE_STATIONS_FILE
        guard.ACTIVE_STATIONS_FILE = self.temp_stations_file

        self.store = guard.StationStore(self.temp_stations_file)

    def tearDown(self):
        guard.ACTIVE_STATIONS_FILE = self.orig_file
        self.temp_dir.cleanup()
        os.environ.clear()
        os.environ.update(self.orig_env)

    # 1. Dual-Signal Detection & Mode Resolution
    def test_afk_detection_via_signal_a_env_default_strict(self):
        self.assertTrue(hasattr(guard, "is_afk_session"), "guard.is_afk_session must exist")
        os.environ["EDGE_AFK"] = "1"
        is_afk, mode = guard.is_afk_session({})
        self.assertTrue(is_afk)
        self.assertEqual(mode, "strict")

    def test_afk_detection_via_signal_a_env_yolo_mode(self):
        self.assertTrue(hasattr(guard, "is_afk_session"), "guard.is_afk_session must exist")
        os.environ["EDGE_AFK"] = "1"
        os.environ["EDGE_AFK_MODE"] = "yolo"
        is_afk, mode = guard.is_afk_session({})
        self.assertTrue(is_afk)
        self.assertEqual(mode, "yolo")

    def test_afk_detection_via_signal_b_transcript_strict(self):
        self.assertTrue(hasattr(guard, "is_afk_session"), "guard.is_afk_session must exist")
        transcript_file = self.temp_path / "transcript.jsonl"
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "content": "[EDGE_AFK:strict]\nOBJECTIVE: Refactor billing actions"
            }) + "\n")

        payload = {"transcriptPath": str(transcript_file)}
        is_afk, mode = guard.is_afk_session(payload)
        self.assertTrue(is_afk)
        self.assertEqual(mode, "strict")

    def test_afk_detection_via_signal_b_transcript_yolo(self):
        self.assertTrue(hasattr(guard, "is_afk_session"), "guard.is_afk_session must exist")
        transcript_file = self.temp_path / "transcript.jsonl"
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "content": "[EDGE_AFK:yolo]\nOBJECTIVE: Overhaul tests and migrations"
            }) + "\n")

        payload = {"transcriptPath": str(transcript_file)}
        is_afk, mode = guard.is_afk_session(payload)
        self.assertTrue(is_afk)
        self.assertEqual(mode, "yolo")

    def test_afk_detection_non_afk_session(self):
        self.assertTrue(hasattr(guard, "is_afk_session"), "guard.is_afk_session must exist")
        transcript_file = self.temp_path / "transcript.jsonl"
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 1,
                "source": "USER_EXPLICIT",
                "content": "Please check the status of our project"
            }) + "\n")

        payload = {"transcriptPath": str(transcript_file)}
        is_afk, mode = guard.is_afk_session(payload)
        self.assertFalse(is_afk)

    # 2. Universal AFK Denials in Both Strict and YOLO Modes
    def test_afk_universal_blocks_invoke_subagent_in_strict_and_yolo(self):
        for mode in ("strict", "yolo"):
            os.environ["EDGE_AFK"] = "1"
            os.environ["EDGE_AFK_MODE"] = mode
            payload = {
                "conversationId": "afk-session-1",
                "toolCall": {
                    "name": "invoke_subagent",
                    "args": {"Role": "CODER", "Prompt": "Write some code"}
                }
            }
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "deny", f"Mode {mode} must deny invoke_subagent")
            self.assertIn("[EDGE AFK GUARD]", res["reason"])

    def test_afk_universal_blocks_hitl_state_files(self):
        protected_files = [
            ".edge/brigade.json",
            "foo/.edge/brigade.json",
            ".edge/checkpoint.json",
            "edge_active_stations.json",
            "/home/oguz/.gemini/antigravity/edge_active_stations.json",
        ]
        tool_names = ["write_file", "edit_file", "write_to_file", "replace_file_content"]

        for mode in ("strict", "yolo"):
            os.environ["EDGE_AFK"] = "1"
            os.environ["EDGE_AFK_MODE"] = mode
            for filepath in protected_files:
                for tool in tool_names:
                    arg_key = "Path" if tool in ("write_file", "edit_file") else "TargetFile"
                    payload = {
                        "conversationId": "afk-session-1",
                        "toolCall": {
                            "name": tool,
                            "args": {arg_key: filepath, "Content": "{}"}
                        }
                    }
                    res = guard.handle_pre_tool(payload)
                    self.assertEqual(res["decision"], "deny", f"Mode {mode} with tool {tool} on {filepath} must be denied")
                    self.assertIn("[EDGE AFK STATE GUARD]", res["reason"])

    def test_afk_post_tool_never_registers_station(self):
        os.environ["EDGE_AFK"] = "1"
        repo_dir = self.temp_path / "mock_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)

        payload = {
            "conversationId": "afk-session-1",
            "cwd": str(repo_dir),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"role": "CODER"}
            },
            "toolResponse": {
                "conversationId": "afk-subagent-999"
            }
        }
        guard.handle_post_tool(payload)
        envelope = self.store.load()
        self.assertNotIn("afk-subagent-999", envelope["stations"])
        self.assertNotIn("afk-session-1", envelope["stations"])

        brigade_json = repo_dir / ".edge" / "brigade.json"
        self.assertFalse(brigade_json.exists())

    def test_afk_pre_invocation_never_injects_orchestrator(self):
        os.environ["EDGE_AFK"] = "1"
        transcript_file = self.temp_path / "transcript.jsonl"
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "content": "[EDGE_AFK:strict]\nOBJECTIVE: Autonomous loop"
            }) + "\n")

        payload = {
            "conversationId": "afk-session-root",
            "transcriptPath": str(transcript_file),
        }
        res = guard.handle_pre_invocation(payload)
        injected = res.get("injectSteps", [])
        for step in injected:
            msg = step.get("ephemeralMessage", "")
            self.assertNotIn("ORCHESTRATOR", msg)
            self.assertNotIn("Sovereign Commander", msg)
            self.assertNotIn("Canonical Brigade Stations", msg)

    # 3. Strict Mode File Boundaries
    def test_afk_strict_denies_schema_and_migrations(self):
        os.environ["EDGE_AFK"] = "1"
        os.environ["EDGE_AFK_MODE"] = "strict"
        schema_targets = [
            "src/db/schema/users.ts",
            "db/schema/posts.ts",
            "drizzle/0001_initial.sql",
            "drizzle/meta/_journal.json",
        ]
        for target in schema_targets:
            payload = {
                "conversationId": "afk-session-strict",
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": target, "Content": "export const users = ..."}
                }
            }
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "deny", f"Strict mode must deny schema target {target}")
            self.assertIn("[MIGRATIONGATE GUARD]", res["reason"])

    def test_afk_strict_denies_tests(self):
        os.environ["EDGE_AFK"] = "1"
        os.environ["EDGE_AFK_MODE"] = "strict"
        test_targets = [
            "tests/unit/billing.test.ts",
            "src/services/billing.spec.ts",
            "test/integration/auth.test.js",
        ]
        for target in test_targets:
            payload = {
                "conversationId": "afk-session-strict",
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": target, "Target": "foo", "Replacement": "bar"}
                }
            }
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "deny", f"Strict mode must deny test target {target}")
            self.assertIn("[TEST IMMUTABILITY GUARD]", res["reason"])

    def test_afk_strict_allows_implementation_and_scratchpad(self):
        # Even when running as root session (which standard guard treats as ORCHESTRATOR),
        # an AFK session must be allowed to read and write implementation files and scratchpad.
        os.environ["EDGE_AFK"] = "1"
        os.environ["EDGE_AFK_MODE"] = "strict"

        transcript_file = self.temp_path / "transcript.jsonl"
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(json.dumps({
                "step_index": 0,
                "source": "USER_EXPLICIT",
                "content": "[EDGE_AFK:strict]\nOBJECTIVE: Refactor services"
            }) + "\n")

        allowed_targets = [
            "src/services/billing.ts",
            "lib/utils.ts",
            "app/api/route.ts",
            ".gnhf/notes.md",
        ]
        for target in allowed_targets:
            payload_write = {
                "conversationId": "afk-session-strict-root",
                "transcriptPath": str(transcript_file),
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": target, "Content": "// refactored"}
                }
            }
            res_write = guard.handle_pre_tool(payload_write)
            self.assertEqual(res_write.get("decision"), "allow", f"Strict mode must allow writing {target}")

            payload_read = {
                "conversationId": "afk-session-strict-root",
                "transcriptPath": str(transcript_file),
                "toolCall": {
                    "name": "read_file",
                    "args": {"Path": target}
                }
            }
            res_read = guard.handle_pre_tool(payload_read)
            self.assertEqual(res_read.get("decision"), "allow", f"Strict mode must allow reading {target}")

    # 4. YOLO Mode File Boundaries
    def test_afk_yolo_allows_implementation_tests_and_schemas_but_blocks_subagents_and_state(self):
        os.environ["EDGE_AFK"] = "1"
        os.environ["EDGE_AFK_MODE"] = "yolo"

        targets = [
            "src/services/billing.ts",
            "tests/unit/foo.test.ts",
            "src/foo.spec.ts",
            "src/db/schema/users.ts",
            "drizzle/0001.sql",
        ]
        for target in targets:
            payload = {
                "conversationId": "afk-session-yolo",
                "toolCall": {
                    "name": "edit_file",
                    "args": {"Path": target, "Target": "old", "Replacement": "new"}
                }
            }
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res.get("decision"), "allow", f"YOLO mode must allow editing {target}")

        # Subagents still denied in YOLO
        payload_subagent = {
            "conversationId": "afk-session-yolo",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Role": "CODER"}
            }
        }
        res_sub = guard.handle_pre_tool(payload_subagent)
        self.assertEqual(res_sub["decision"], "deny")
        self.assertIn("[EDGE AFK GUARD]", res_sub["reason"])

        # State files still denied in YOLO
        payload_state = {
            "conversationId": "afk-session-yolo",
            "toolCall": {
                "name": "write_file",
                "args": {"Path": ".edge/brigade.json", "Content": "{}"}
            }
        }
        res_state = guard.handle_pre_tool(payload_state)
        self.assertEqual(res_state["decision"], "deny")
        self.assertIn("[EDGE AFK STATE GUARD]", res_state["reason"])


if __name__ == "__main__":
    unittest.main()


