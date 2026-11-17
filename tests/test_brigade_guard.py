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
        self.assertEqual(guard.normalize_role("spec_critic"), "SPEC_CRITIC")
        self.assertEqual(guard.normalize_role("spec critic"), "SPEC_CRITIC")
        self.assertEqual(guard.normalize_role("spec-critic"), "SPEC_CRITIC")
        self.assertEqual(guard.normalize_role("goldfish_critic"), "SPEC_CRITIC")
        self.assertEqual(guard.normalize_role("goldfish critic"), "SPEC_CRITIC")
        self.assertEqual(guard.normalize_role("Goldfish Critic"), "SPEC_CRITIC")

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
        for examiner in ["EXAMINER", "RESEARCHER", "SPEC_CRITIC"]:
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
        # Step 1: No coder active yet -> invoke_subagent allowed
        payload_first = {
            "conversationId": "orch-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "Coder", "Prompt": "Implement feature"}])
                }
            }
        }
        res1 = guard.handle_pre_tool(payload_first)
        self.assertEqual(res1["decision"], "allow")

        # Step 2: Register the spawned coder subagent
        guard.register_station(
            conversation_id="conv-coder-456",
            role="CODER",
            parent_cid="orch-parent"
        )

        # Step 3: Second call to invoke_subagent for Coder -> HARD DENIAL
        payload_second = {
            "conversationId": "orch-parent",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": json.dumps([{"Role": "Coder", "Prompt": "Implement second slice"}])
                }
            }
        }
        res2 = guard.handle_pre_tool(payload_second)
        self.assertEqual(res2["decision"], "deny")
        self.assertIn("PERSISTENT STATION REUSE REQUIRED", res2["reason"])
        self.assertIn("conv-coder-456", res2["reason"])
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

    def test_qa_engineer_can_write_proof_receipt(self):
        payload = {
            "conversationId": "qa-1",
            "toolCall": {
                "name": "write_file",
                "args": {
                    "Path": ".edge/qa/proofs/test.json",
                    "Content": "{}",
                },
            },
        }
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "allow")

    def test_qa_engineer_denied_from_mutating_src(self):
        payload = {
            "conversationId": "qa-1",
            "toolCall": {
                "name": "write_file",
                "args": {
                    "Path": "src/App.tsx",
                    "Content": "export default function App() {}",
                },
            },
        }
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "deny")
            self.assertIn("QA BOUNDARY GUARD", res["reason"])

    def test_invoke_subagent_browser_allowed(self):
        payload = {
            "conversationId": "qa-parent-1",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "TypeName": "browser",
                    "Model": "flash",
                    "Role": "Browser Automation Subagent",
                    "Prompt": "Navigate to http://localhost:3000 and verify",
                },
            },
        }
        res = guard.handle_pre_tool(payload)
        self.assertEqual(res["decision"], "allow")
        self.assertIn("AUXILIARY_TOOL_AGENT", res.get("reason", ""))

    def test_browser_subagent_not_hijacked_by_antigraveyard(self):
        # Register persistent QA_ENGINEER
        guard.register_station(
            conversation_id="conv-qa-123",
            role="QA_ENGINEER",
            parent_cid="orch-parent",
        )
        # Calling invoke_subagent with TypeName="browser" from QA_ENGINEER session
        payload = {
            "conversationId": "conv-qa-123",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "TypeName": "browser",
                    "Model": "flash",
                    "Role": "Browser QA Subagent",
                    "Prompt": "Navigate to http://localhost:3000",
                },
            },
        }
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_tool(payload)
            self.assertEqual(res["decision"], "allow")
            self.assertIn("AUXILIARY_TOOL_AGENT", res.get("reason", ""))

    def test_qa_engineer_pre_invocation_injection(self):
        with patch.object(guard, "detect_session_role", return_value=("QA_ENGINEER", "test")):
            res = guard.handle_pre_invocation({})
            self.assertTrue(len(res.get("injectSteps", [])) > 0)
            msg = res["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("browser", msg)
            self.assertIn(".edge/qa/proofs/", msg)
            self.assertNotIn("chrome-dev-tools-axi", msg)
            self.assertNotIn("chrome-devtools-mcp", msg)

    def test_pre_invocation_injections(self):
        # Orchestrator
        with patch.object(guard, "detect_session_role", return_value=("ORCHESTRATOR", "test")):
            res = guard.handle_pre_invocation({})
            self.assertTrue(len(res["injectSteps"]) > 0)
            msg = res["injectSteps"][0]["ephemeralMessage"]
            self.assertIn("Sovereign Commander", msg)
            self.assertIn("Canonical Brigade Stations", msg)
            if hasattr(guard, "_handle_swarm_guard") or "ULTRA SWARM MODE" in msg:
                self.assertIn("Ultra Swarm-Native Station Dispatch Protocol", msg)
            else:
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

    def test_station_record_model_default_and_serialization(self):
        # 1. StationRecord default model == "flash"
        record = guard.StationRecord(
            conversation_id="c1",
            role="coder",
            canonical_role="CODER",
            parent_conversation_id="p1",
        )
        self.assertEqual(record.model, "flash")
        self.assertEqual(record.to_dict().get("model"), "flash")

        # 2. StationRecord custom model
        record_pro = guard.StationRecord(
            conversation_id="e1",
            role="examiner",
            canonical_role="EXAMINER",
            parent_conversation_id="p1",
            model="pro",
        )
        self.assertEqual(record_pro.model, "pro")
        self.assertEqual(record_pro.to_dict().get("model"), "pro")

        # 3. StationStore.register persists "model": "flash"
        rec_store = self.store.register("c1", "coder", "p1", model="flash")
        self.assertEqual(rec_store.model, "flash")
        envelope = self.store.load()
        self.assertEqual(envelope["stations"]["c1"].get("model"), "flash")

        # 4. StationStore.register with custom model
        rec_store_pro = self.store.register("e1", "examiner", "p1", model="pro")
        self.assertEqual(rec_store_pro.model, "pro")
        envelope_pro = self.store.load()
        self.assertEqual(envelope_pro["stations"]["e1"].get("model"), "pro")


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


class TestGoldfishStationRotation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.temp_dir.name) / "edge_active_stations.json"
        self.store = guard.StationStore(self.store_path)
        self.brain_root = Path(self.temp_dir.name) / "brain"
        self.brain_root.mkdir(parents=True, exist_ok=True)
        self.scanner = guard.TranscriptStationScanner(self.brain_root)
        self.orig_file = guard.ACTIVE_STATIONS_FILE
        guard.ACTIVE_STATIONS_FILE = self.store_path

    def tearDown(self):
        guard.ACTIVE_STATIONS_FILE = self.orig_file
        self.temp_dir.cleanup()

    def test_role_classification_sets(self):
        self.assertTrue(hasattr(guard, "PERSISTENT_ELEPHANT_ROLES"))
        self.assertTrue(hasattr(guard, "EPHEMERAL_GOLDFISH_ROLES"))
        self.assertEqual(
            guard.PERSISTENT_ELEPHANT_ROLES,
            frozenset({"SPEC_WRITER", "RESEARCHER", "SEAM_ARCHITECT", "CODER", "SURGEON", "QA_ENGINEER"})
        )
        self.assertEqual(
            guard.EPHEMERAL_GOLDFISH_ROLES,
            frozenset({"EXAMINER", "SPEC_CRITIC"})
        )
        self.assertTrue(guard.PERSISTENT_ELEPHANT_ROLES.isdisjoint(guard.EPHEMERAL_GOLDFISH_ROLES))

    def test_goldfish_examiner_and_spec_critic_bypass_reuse_and_rotate_previous(self):
        """Spawning EXAMINER or SPEC_CRITIC when active GREEN (<45k) instance exists returns allow and marks previous ROTATED."""
        for role_name in ["EXAMINER", "SPEC_CRITIC"]:
            cid_prev = f"cid-{role_name.lower()}-green"
            store_data = {
                "version": "1.0",
                "initializedAt": "2026-10-15T00:00:00Z",
                "sessions": {},
                "stations": {
                    cid_prev: {
                        "conversationId": cid_prev,
                        "role": role_name,
                        "canonicalRole": role_name,
                        "parentConversationId": "orch-parent",
                        "status": "IDLE",
                        "tokenHeat": {
                            "tokens": 12000,
                            "heatZone": "GREEN"
                        }
                    }
                }
            }
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(store_data, f)

            # Spawn goldfish role
            res = guard.StationSelector.evaluate_spawn_request(
                self.store, self.scanner, "orch-parent", role_name
            )
            self.assertEqual(res["decision"], "allow")
            self.assertIn("GOLDFISH_EPHEMERAL", res["reason"])
            self.assertIn(f"Fresh zero-context {role_name} spawn permitted", res["reason"])

            # Verify that previous instance is marked ROTATED in store
            envelope = self.store.load()
            self.assertEqual(envelope["stations"][cid_prev]["status"], "ROTATED")
            self.assertIn("lastActiveAt", envelope["stations"][cid_prev])

    def test_persistent_coder_and_surgeon_still_denied_when_green(self):
        """Spawning CODER or SURGEON when active GREEN instance exists STILL returns deny directing reuse via send_message."""
        for role_name in ["CODER", "SURGEON"]:
            cid_green = f"cid-{role_name.lower()}-active-green"
            store_data = {
                "version": "1.0",
                "initializedAt": "2026-10-15T00:00:00Z",
                "sessions": {},
                "stations": {
                    cid_green: {
                        "conversationId": cid_green,
                        "role": role_name,
                        "canonicalRole": role_name,
                        "parentConversationId": "orch-parent",
                        "status": "IDLE",
                        "tokenHeat": {
                            "tokens": 25000,
                            "heatZone": "GREEN"
                        }
                    }
                }
            }
            with open(self.store_path, "w", encoding="utf-8") as f:
                json.dump(store_data, f)

            res = guard.StationSelector.evaluate_spawn_request(
                self.store, self.scanner, "orch-parent", role_name
            )
            self.assertEqual(res["decision"], "deny")
            self.assertIn("PERSISTENT STATION REUSE REQUIRED", res["reason"])
            self.assertIn(cid_green, res["reason"])
            self.assertIn("send_message", res["reason"])

            # Verify that elephant instance status was NOT changed
            envelope = self.store.load()
            self.assertEqual(envelope["stations"][cid_green]["status"], "IDLE")

    def test_spec_critic_denied_file_mutations_in_handle_pre_tool(self):
        """SPEC_CRITIC is denied file mutations (write_file / edit_file) in handle_pre_tool."""
        mutation_tools = [
            ("write_file", {"Path": "src/actions/foo.ts", "Content": "// code"}),
            ("edit_file", {"Path": "specs/feature.md", "Target": "old", "Replacement": "new"}),
            ("write_to_file", {"TargetFile": "lib/utils.ts"}),
            ("replace_file_content", {"TargetFile": "package.json"}),
        ]
        for tool_name, args in mutation_tools:
            payload = {
                "conversationId": "critic-session-1",
                "toolCall": {
                    "name": tool_name,
                    "args": args
                }
            }
            with patch.object(guard, "detect_session_role", return_value=("SPEC_CRITIC", "test")):
                res = guard.handle_pre_tool(payload)
                self.assertEqual(res["decision"], "deny", f"Tool {tool_name} should be denied for SPEC_CRITIC")
                self.assertIn("salt-okunur", res["reason"])
                self.assertIn("SPEC_CRITIC", res["reason"])

    def test_station_store_mark_rotated_atomic(self):
        """StationStore.mark_rotated sets status to ROTATED and updates lastActiveAt."""
        cid = "cid-spec-critic-mark-rot"
        record = self.store.register(conversation_id=cid, role="SPEC_CRITIC", parent_cid="orch-parent")
        self.assertEqual(record.status, "IDLE")

        self.store.mark_rotated(cid)
        envelope = self.store.load()
        self.assertEqual(envelope["stations"][cid]["status"], "ROTATED")
        self.assertIn("lastActiveAt", envelope["stations"][cid])



class TestWslCwdAnchorAndQuotingHook(unittest.TestCase):
    """
    Hermetic contract and unit tests for:
    - Pre-Tool WSL Command Guard & Helper Presence (Scenario 1)
    - Transparent Auto-Anchor via --cd Injection & CWD Translation (Scenario 2)
    - Deterministic Deny Guard for PowerShell Variable Swallowing & Nested Quoting (Scenario 3)
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.orig_file = guard.ACTIVE_STATIONS_FILE
        guard.ACTIVE_STATIONS_FILE = Path(self.temp_dir.name) / "edge_active_stations.json"

    def tearDown(self):
        guard.ACTIVE_STATIONS_FILE = self.orig_file
        self.temp_dir.cleanup()

    # --- 1. evaluate_wsl_command_guard & Helper Functions Presence ---
    def test_wsl_guard_helpers_presence(self):
        """Verifies presence of evaluate_wsl_command_guard and its canonical helper subroutines."""
        self.assertTrue(
            hasattr(guard, "evaluate_wsl_command_guard"),
            "orchestrator_guard must define evaluate_wsl_command_guard",
        )
        self.assertTrue(
            hasattr(guard, "_is_wsl_invocation"),
            "orchestrator_guard must define _is_wsl_invocation",
        )
        self.assertTrue(
            hasattr(guard, "_check_powershell_var_swallowing"),
            "orchestrator_guard must define _check_powershell_var_swallowing",
        )
        self.assertTrue(
            hasattr(guard, "_check_nested_quoting_collision"),
            "orchestrator_guard must define _check_nested_quoting_collision",
        )
        self.assertTrue(
            hasattr(guard, "_resolve_wsl_anchor_path"),
            "orchestrator_guard must define _resolve_wsl_anchor_path",
        )
        self.assertTrue(
            hasattr(guard, "_transform_wsl_command_anchor"),
            "orchestrator_guard must define _transform_wsl_command_anchor",
        )

    def test_is_wsl_invocation(self):
        """Validates _is_wsl_invocation matches case-insensitive wsl/wsl.exe with leading spaces."""
        self.assertTrue(hasattr(guard, "_is_wsl_invocation"))
        self.assertTrue(guard._is_wsl_invocation("wsl bash"))
        self.assertTrue(guard._is_wsl_invocation("wsl.exe python3"))
        self.assertTrue(guard._is_wsl_invocation("  WSL pytest"))
        self.assertTrue(guard._is_wsl_invocation("wsl"))

        self.assertFalse(guard._is_wsl_invocation("git status"))
        self.assertFalse(guard._is_wsl_invocation("python3 -m unittest"))
        self.assertFalse(guard._is_wsl_invocation("echo wsl"))
        self.assertFalse(guard._is_wsl_invocation("git commit -m wsl"))
        self.assertFalse(guard._is_wsl_invocation(""))
        self.assertFalse(guard._is_wsl_invocation(None))

    def test_non_wsl_commands_passthrough(self):
        """Validates that non-WSL commands return None from guard and pass through handle_pre_tool."""
        self.assertTrue(hasattr(guard, "evaluate_wsl_command_guard"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("git status"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("python3 -m unittest"))

        payload = {
            "conversationId": "coder-session-1",
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "git status",
                },
            },
        }
        res = guard.handle_pre_tool(payload)
        self.assertEqual(res.get("decision"), "allow")
        self.assertNotIn("overwrite", res)

    # --- 2. Transparent Auto-Anchor (--cd Injection & CWD Resolution) ---
    def test_auto_anchor_inline_cd_extracted_and_rewritten(self):
        """Validates extraction of inline 'cd /path' and rewriting with 'wsl --cd /path'."""
        self.assertTrue(hasattr(guard, "evaluate_wsl_command_guard"))
        cmd = "wsl bash -c 'cd /home/oguz/proj && npm test'"
        res = guard.evaluate_wsl_command_guard(cmd)
        self.assertIsNotNone(res)
        self.assertEqual(res.get("decision"), "allow")
        self.assertIn("overwrite", res)
        new_cmd = res["overwrite"].get("CommandLine")
        self.assertIsNotNone(new_cmd)
        self.assertTrue(
            new_cmd.startswith("wsl --cd /home/oguz/proj"),
            f"Expected command to start with 'wsl --cd /home/oguz/proj', got: {new_cmd}",
        )

    def test_resolve_wsl_anchor_path_from_windows_and_unc_cwd(self):
        """Validates translation of Windows UNC, drive, and mapped paths to Linux paths."""
        self.assertTrue(hasattr(guard, "_resolve_wsl_anchor_path"))
        # UNC wsl.localhost
        p1 = guard._resolve_wsl_anchor_path("wsl npm test", cwd=r"\\wsl.localhost\Ubuntu-24.04\home\oguz\proj")
        self.assertEqual(p1, "/home/oguz/proj")

        # UNC wsl$
        p2 = guard._resolve_wsl_anchor_path("wsl npm test", cwd=r"\\wsl$\Ubuntu-24.04\home\oguz\proj")
        self.assertEqual(p2, "/home/oguz/proj")

        # Mapped network drive Z:/home/...
        p3 = guard._resolve_wsl_anchor_path("wsl npm test", cwd=r"Z:\home\oguz\proj")
        self.assertEqual(p3, "/home/oguz/proj")

        # Windows local drive C:\Users\...
        p4 = guard._resolve_wsl_anchor_path("wsl npm test", cwd=r"C:\Users\oguz_\proj")
        self.assertEqual(p4, "/mnt/c/Users/oguz_/proj")

        # Native Linux path
        p5 = guard._resolve_wsl_anchor_path("wsl npm test", cwd="/home/oguz/proj")
        self.assertEqual(p5, "/home/oguz/proj")

    def test_handle_pre_tool_argument_key_preservation(self):
        """Validates that overwrite preserves whether incoming arg was 'CommandLine' or 'command'."""
        self.assertTrue(hasattr(guard, "evaluate_wsl_command_guard"))
        # 1. Incoming CommandLine
        p_cl = {
            "conversationId": "coder-1",
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "wsl npm test",
                    "cwd": r"\\wsl.localhost\Ubuntu-24.04\home\oguz\proj",
                },
            },
        }
        res_cl = guard.handle_pre_tool(p_cl)
        self.assertEqual(res_cl.get("decision"), "allow")
        self.assertIn("overwrite", res_cl)
        self.assertIn("CommandLine", res_cl["overwrite"])
        self.assertNotIn("command", res_cl["overwrite"])
        self.assertEqual(res_cl["overwrite"]["CommandLine"], "wsl --cd /home/oguz/proj npm test")

        # 2. Incoming command
        p_c = {
            "conversationId": "coder-1",
            "toolCall": {
                "name": "run_command",
                "args": {
                    "command": "wsl npm test",
                    "cwd": r"\\wsl.localhost\Ubuntu-24.04\home\oguz\proj",
                },
            },
        }
        res_c = guard.handle_pre_tool(p_c)
        self.assertEqual(res_c.get("decision"), "allow")
        self.assertIn("overwrite", res_c)
        self.assertIn("command", res_c["overwrite"])
        self.assertNotIn("CommandLine", res_c["overwrite"])
        self.assertEqual(res_c["overwrite"]["command"], "wsl --cd /home/oguz/proj npm test")

    def test_existing_cd_or_management_flags_bypass(self):
        """Commands with existing --cd or management flags are not modified."""
        self.assertTrue(hasattr(guard, "evaluate_wsl_command_guard"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("wsl --cd /home/oguz/proj pytest"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("wsl --list"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("wsl -l -v"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("wsl --status"))
        self.assertIsNone(guard.evaluate_wsl_command_guard("wsl --shutdown"))

        payload = {
            "conversationId": "coder-1",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "wsl --cd /home/oguz/proj pytest"},
            },
        }
        res = guard.handle_pre_tool(payload)
        self.assertEqual(res.get("decision"), "allow")
        self.assertNotIn("overwrite", res)

    def test_distro_flag_positioning(self):
        """Validates that --cd is positioned after distribution flag (-d / --distribution)."""
        self.assertTrue(hasattr(guard, "evaluate_wsl_command_guard"))
        cmd = "wsl -d Ubuntu-24.04 pytest"
        res = guard.evaluate_wsl_command_guard(cmd, cwd="/home/oguz/proj")
        self.assertIsNotNone(res)
        self.assertEqual(
            res["overwrite"]["CommandLine"],
            "wsl -d Ubuntu-24.04 --cd /home/oguz/proj pytest",
        )

    # --- 3. Deterministic Deny Guard (PowerShell Var & Nested Quoting) ---
    def test_powershell_var_swallowing_denied_in_double_quotes(self):
        """Unescaped $var or ${var} inside double quotes is denied to prevent local swallowing."""
        self.assertTrue(hasattr(guard, "_check_powershell_var_swallowing"))
        cmd1 = 'wsl bash -c "for f in a b; do echo $f; done"'
        res1 = guard._check_powershell_var_swallowing(cmd1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get("decision"), "deny")
        self.assertIn("POWERSHELL VARIABLE SWALLOWING GUARD", res1.get("reason", ""))
        self.assertIn("$f", res1.get("reason", ""))

        cmd2 = 'wsl bash -c "echo ${TARGET_DIR}/bin"'
        res2 = guard._check_powershell_var_swallowing(cmd2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get("decision"), "deny")
        self.assertIn("${TARGET_DIR}", res2.get("reason", ""))

    def test_escaped_or_single_quoted_variables_allowed(self):
        """Variables in single quotes or escaped with backtick/backslash are allowed."""
        self.assertTrue(hasattr(guard, "_check_powershell_var_swallowing"))
        # Single quotes
        cmd_single = "wsl bash -c 'for f in a b; do echo $f; done'"
        self.assertIsNone(guard._check_powershell_var_swallowing(cmd_single))

        # Backtick escape
        cmd_backtick = 'wsl bash -c "echo `$f"'
        self.assertIsNone(guard._check_powershell_var_swallowing(cmd_backtick))

        # Backslash escape
        cmd_backslash = 'wsl bash -c "echo \\$f"'
        self.assertIsNone(guard._check_powershell_var_swallowing(cmd_backslash))

    def test_nested_quoting_and_metacharacter_collision_denied(self):
        """Nested quotes with shell metacharacters in bash -c are denied."""
        self.assertTrue(hasattr(guard, "_check_nested_quoting_collision"))
        cmd1 = 'wsl bash -c \'frontier-axi promote x --reason "Settled: (1) auto rebase"\''
        res1 = guard._check_nested_quoting_collision(cmd1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1.get("decision"), "deny")
        self.assertIn("NESTED QUOTING & METACHARACTER COLLISION GUARD", res1.get("reason", ""))

        cmd2 = 'wsl bash -c "python3 -c \\"import os; (os.exit(0))\\" && ls"'
        res2 = guard._check_nested_quoting_collision(cmd2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2.get("decision"), "deny")

    def test_clean_single_layer_bash_c_allowed(self):
        """bash -c without conflicting nested quotes and metacharacters is allowed."""
        self.assertTrue(hasattr(guard, "_check_nested_quoting_collision"))
        cmd = "wsl bash -c 'echo hello'"
        self.assertIsNone(guard._check_nested_quoting_collision(cmd))


class TestGuardRoleDetectionAndPostToolHardening(unittest.TestCase):
    """RED tests for Slice 3 Pillar 1: role detection precedence and post-tool CID hardening."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        self.temp_stations_file = self.temp_path / "edge_active_stations.json"
        self.orig_file = guard.ACTIVE_STATIONS_FILE
        guard.ACTIVE_STATIONS_FILE = self.temp_stations_file
        self.store = guard.StationStore(self.temp_stations_file)

    def tearDown(self):
        guard.ACTIVE_STATIONS_FILE = self.orig_file
        self.temp_dir.cleanup()

    def _write_transcript(self, filename: str, steps: list) -> Path:
        tp = self.temp_path / filename
        with open(tp, "w", encoding="utf-8") as f:
            for step in steps:
                f.write(json.dumps(step) + "\n")
        return tp

    def test_normalize_role_word_boundaries_and_preserved_aliases(self):
        # Preserved valid aliases
        self.assertEqual(guard.normalize_role("QA/E2E test agent"), "QA_ENGINEER")
        self.assertEqual(guard.normalize_role("Ecosystem & Recon Specialist"), "RESEARCHER")
        self.assertEqual(guard.normalize_role("Standards Examiner"), "EXAMINER")
        self.assertEqual(guard.normalize_role("Seam Architect"), "SEAM_ARCHITECT")
        self.assertEqual(guard.normalize_role("Goldfish Critic"), "SPEC_CRITIC")

        # Substring traps must NOT match canonical roles
        for non_role in ("recorder", "decoder", "forecast", "subcontract", "qatar", "coworker"):
            self.assertIsNone(
                guard.normalize_role(non_role),
                f"Word-boundary normalize_role must reject substring trap '{non_role}'",
            )

    def test_detect_session_role_explicit_first_and_tier_precedence(self):
        # 1. Explicit CODER prompt mentioning SEAM_ARCHITECT, red test, contract, tdd, Sovereign Commander
        tp_coder = self._write_transcript("coder_step0.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "type": "SYSTEM_MESSAGE",
            "content": (
                "[Message] timestamp=2026-11-17T22:00:00Z sender=orch-1 priority=MESSAGE_PRIORITY_HIGH "
                "content=You are the CODER station worker. Turn the SEAM_ARCHITECT red test and contract "
                "green under TDD without modifying tests. Report back to Sovereign Commander."
            ),
        }])
        role_c, src_c = guard.detect_session_role({"conversationId": "unreg-coder", "transcriptPath": str(tp_coder)})
        self.assertEqual(role_c, "CODER")
        self.assertEqual(src_c, "transcript_subagent_explicit")

        # 2. Explicit SPEC_CRITIC / EXAMINER mentioning SPEC_WRITER and CODER
        tp_critic = self._write_transcript("critic_step0.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] content=You are the SPEC_CRITIC station worker. Audit SPEC_WRITER draft before CODER starts.",
        }])
        role_cr, src_cr = guard.detect_session_role({"conversationId": "unreg-critic", "transcriptPath": str(tp_critic)})
        self.assertEqual(role_cr, "SPEC_CRITIC")
        self.assertEqual(src_cr, "transcript_subagent_explicit")

        tp_examiner = self._write_transcript("examiner_step0.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] content=Follow agents/examiner.md and review SPEC_WRITER and CODER work.",
        }])
        role_ex, src_ex = guard.detect_session_role({"conversationId": "unreg-exam", "transcriptPath": str(tp_examiner)})
        self.assertEqual(role_ex, "EXAMINER")
        self.assertEqual(src_ex, "transcript_subagent_explicit")

        # 3. Non-worker "You are the Sovereign Commander's assistant" ignored -> falls to agents/researcher.md
        tp_res = self._write_transcript("researcher_step0.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] content=You are the Sovereign Commander's helper. Read agents/researcher.md first.",
        }])
        role_res, _ = guard.detect_session_role({"conversationId": "unreg-res", "transcriptPath": str(tp_res)})
        self.assertEqual(role_res, "RESEARCHER")

        # 4. Tier 1 canonical token beats earlier Tier 2 alias
        tp_tier = self._write_transcript("tier_precedence.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] content=Verify the red test, contract, and tdd criteria for the CODER pipeline.",
        }])
        role_t1, src_t1 = guard.detect_session_role({"conversationId": "unreg-t1", "transcriptPath": str(tp_tier)})
        self.assertEqual(role_t1, "CODER")
        self.assertEqual(src_t1, "transcript_subagent_keyword")

        # 5. Earliest Tier 1 position wins (EXAMINER before SPEC_WRITER/CODER)
        tp_early_t1 = self._write_transcript("early_tier1.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] content=EXAMINER task: audit the SPEC_WRITER spec and CODER diff.",
        }])
        role_et1, _ = guard.detect_session_role({"conversationId": "unreg-et1", "transcriptPath": str(tp_early_t1)})
        self.assertEqual(role_et1, "EXAMINER")

        # 6. Earliest Tier 2 position wins when Tier 1 absent (refactor/SURGEON before contract/SEAM_ARCHITECT)
        tp_early_t2 = self._write_transcript("early_tier2.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] content=Please refactor the module to honor the contract.",
        }])
        role_et2, _ = guard.detect_session_role({"conversationId": "unreg-et2", "transcriptPath": str(tp_early_t2)})
        self.assertEqual(role_et2, "SURGEON")

        # 7. Header metadata isolated + word boundaries block substring traps
        tp_isolated = self._write_transcript("body_isolation.jsonl", [{
            "step_index": 0,
            "source": "SYSTEM",
            "content": "[Message] timestamp=2026-11-17T22:00:00Z sender=seam_architect-1 content=Inspect the recorder and forecast payload.",
        }])
        role_iso, _ = guard.detect_session_role({"conversationId": "unreg-iso", "transcriptPath": str(tp_isolated)})
        self.assertEqual(role_iso, "SUBAGENT_GENERIC")

        # 8. Multi-step Ultra Swarm parity returns transcript_swarm_keyword
        tp_swarm = self._write_transcript("swarm_two_step.jsonl", [
            {"step_index": 0, "source": "SYSTEM", "content": "[Message] content=[swarm] new board message #9"},
            {"step_index": 1, "source": "SYSTEM", "content": "[Message] content=For @coder: turn SEAM_ARCHITECT red test green"},
        ])
        role_sw, src_sw = guard.detect_session_role({"conversationId": "unreg-sw", "transcriptPath": str(tp_swarm)})
        self.assertEqual(role_sw, "CODER")
        self.assertEqual(src_sw, "transcript_swarm_keyword")

    def test_handle_post_tool_ignores_noise_steps_in_transcript_tail(self):
        existing_cid = "11111111-2222-3333-4444-555555555555"
        repo_dir = self.temp_path / "repo_noise"
        (repo_dir / ".edge").mkdir(parents=True, exist_ok=True)
        self.store.register(existing_cid, "SPEC_WRITER", "orch-parent")
        guard.sync_repo_brigade_station(repo_dir, "SPEC_WRITER", existing_cid)

        tp = self._write_transcript("noise_tail.jsonl", [
            {
                "step_index": 10,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "manage_subagents", "args": {"Action": "list"}}],
            },
            {
                "step_index": 11,
                "source": "MODEL",
                "type": "GENERIC",
                "content": f'Active subagent(s):\n- {existing_cid} ("conversationId": "{existing_cid}")',
            },
            {
                "step_index": 12,
                "source": "EPHEMERAL",
                "type": "EPHEMERAL_MESSAGE",
                "content": '{"conversationId": "22222222-2222-3333-4444-555555555555"}',
            },
            {
                "step_index": 13,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "send_message", "args": {"Recipient": "33333333-2222-3333-4444-555555555555"}}],
            },
            {
                "step_index": 14,
                "source": "MODEL",
                "type": "TOOL_RESULT",
                "content": '{"conversationId": "44444444-2222-3333-4444-555555555555"}',
            },
        ])

        payload = {
            "conversationId": "orch-parent",
            "transcriptPath": str(tp),
            "cwd": str(repo_dir),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {"Role": "SPEC_CRITIC", "Prompt": "Critique spec"},
            },
        }
        res = guard.handle_post_tool(payload)
        self.assertEqual(res, {})

        stations = self.store.load().get_stations()
        self.assertEqual(stations[existing_cid]["canonicalRole"], "SPEC_WRITER")
        for bogus_cid in (
            "22222222-2222-3333-4444-555555555555",
            "33333333-2222-3333-4444-555555555555",
            "44444444-2222-3333-4444-555555555555",
        ):
            self.assertNotIn(bogus_cid, stations)

        brigade_data = json.loads((repo_dir / ".edge" / "brigade.json").read_text(encoding="utf-8"))
        self.assertEqual(brigade_data["stations"]["SPEC_WRITER"]["conversation_id"], existing_cid)
        self.assertNotIn("SPEC_CRITIC", brigade_data["stations"])

    def test_handle_post_tool_window_edge_and_snake_case_cids(self):
        # 1. Window edge (preceding_planner is None) WITHOUT "Created the following subagent" -> rejected
        tp_reject = self._write_transcript("edge_reject.jsonl", [{
            "step_index": 50,
            "source": "MODEL",
            "type": "GENERIC",
            "content": '{"conversation_id": "55555555-2222-3333-4444-555555555555", "status": "ok"}',
        }])
        guard.handle_post_tool({
            "conversationId": "orch-parent",
            "transcriptPath": str(tp_reject),
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "CODER"}},
        })
        self.assertNotIn("55555555-2222-3333-4444-555555555555", self.store.load().get_stations())

        # 2. Window edge WITH singular "Created the following subagent" + snake_case conversation_id -> accepted
        cid_singular = "66666666-2222-3333-4444-555555555555"
        tp_singular = self._write_transcript("edge_singular.jsonl", [{
            "step_index": 51,
            "source": "MODEL",
            "type": "GENERIC",
            "content": f'Created the following subagent:\n{{"conversation_id": "{cid_singular}"}}',
        }])
        guard.handle_post_tool({
            "conversationId": "orch-parent",
            "transcriptPath": str(tp_singular),
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "CODER"}},
        })
        stations = self.store.load().get_stations()
        self.assertIn(cid_singular, stations)
        self.assertEqual(stations[cid_singular]["canonicalRole"], "CODER")

        # 3. Preceding PLANNER_RESPONSE with invoke_subagent allows TOOL_RESULT snake_case conversation_id
        cid_paired = "77777777-2222-3333-4444-555555555555"
        tp_paired = self._write_transcript("paired_snake.jsonl", [
            {
                "step_index": 52,
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "invoke_subagent", "args": {"Role": "EXAMINER"}}],
            },
            {
                "step_index": 53,
                "source": "MODEL",
                "type": "TOOL_RESULT",
                "content": f'{{"conversation_id": "{cid_paired}"}}',
            },
        ])
        guard.handle_post_tool({
            "conversationId": "orch-parent",
            "transcriptPath": str(tp_paired),
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "EXAMINER"}},
        })
        stations = self.store.load().get_stations()
        self.assertIn(cid_paired, stations)
        self.assertEqual(stations[cid_paired]["canonicalRole"], "EXAMINER")

        # 4. Primary extraction supports snake_case conversation_id in escaped output string
        cid_primary = "88888888-2222-3333-4444-555555555555"
        guard.handle_post_tool({
            "conversationId": "orch-parent",
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "RESEARCHER"}},
            "output": f'\\"conversation_id\\": \\"{cid_primary}\\"',
        })
        # Also JSON string in result
        cid_result = "88888888-aaaa-3333-4444-555555555555"
        guard.handle_post_tool({
            "conversationId": "orch-parent",
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "RESEARCHER"}},
            "result": f'{{"conversation_id": "{cid_result}"}}',
        })
        stations = self.store.load().get_stations()
        self.assertEqual(stations[cid_primary]["canonicalRole"], "RESEARCHER")
        self.assertEqual(stations[cid_result]["canonicalRole"], "RESEARCHER")

    def test_handle_post_tool_fallback_anti_overwrite_guard(self):
        existing_cid = "99999999-2222-3333-4444-555555555555"
        repo_dir = self.temp_path / "repo_anti_overwrite"
        (repo_dir / ".edge").mkdir(parents=True, exist_ok=True)
        self.store.register(existing_cid, "SPEC_WRITER", "orch-parent")
        guard.sync_repo_brigade_station(repo_dir, "SPEC_WRITER", existing_cid)

        tp = self._write_transcript("anti_overwrite.jsonl", [{
            "step_index": 60,
            "source": "MODEL",
            "type": "GENERIC",
            "content": f'Created the following subagents:\n{{"conversationId": "{existing_cid}"}}',
        }])
        res = guard.handle_post_tool({
            "conversationId": "orch-parent",
            "transcriptPath": str(tp),
            "cwd": str(repo_dir),
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "SPEC_CRITIC"}},
        })
        self.assertEqual(res, {})
        stations = self.store.load().get_stations()
        self.assertEqual(stations[existing_cid]["canonicalRole"], "SPEC_WRITER")
        brigade_data = json.loads((repo_dir / ".edge" / "brigade.json").read_text(encoding="utf-8"))
        self.assertNotIn("SPEC_CRITIC", brigade_data["stations"])

        # Placeholder STATION_WORKER record IS allowed to be upgraded via fallback
        placeholder_cid = "aaaaaaaa-2222-3333-4444-555555555555"
        self.store.register(placeholder_cid, "STATION_WORKER", "orch-parent")
        tp_upgrade = self._write_transcript("upgrade_placeholder.jsonl", [{
            "step_index": 61,
            "source": "MODEL",
            "type": "GENERIC",
            "content": f'Created the following subagent:\n{{"conversation_id": "{placeholder_cid}"}}',
        }])
        guard.handle_post_tool({
            "conversationId": "orch-parent",
            "transcriptPath": str(tp_upgrade),
            "cwd": str(repo_dir),
            "toolCall": {"name": "invoke_subagent", "args": {"Role": "SURGEON"}},
        })
        stations_after = self.store.load().get_stations()
        self.assertEqual(stations_after[placeholder_cid]["canonicalRole"], "SURGEON")


if __name__ == "__main__":
    unittest.main()


