#!/usr/bin/env python3
"""
Contract and Invariant Tests for Edge Distill v2 Skill, References, and Documentation Sync.
Validates SKILL.md 5-step self-improving software factory protocol, Cold Goldfish
reference lens rubrics and prompt-injection guardrails, and ARCHITECTURE.md / INSTRUCTIONS.md sync.
"""

import os
import re
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))


class TestEdgeDistillSkillV2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.skill_path = cls.repo_root / "skills" / "edge-distill" / "SKILL.md"

    def test_skill_file_exists_and_frontmatter(self):
        self.assertTrue(self.skill_path.is_file(), f"Missing {self.skill_path}")
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"), "SKILL.md must start with YAML frontmatter delimiter '---'")
        parts = text.split("---", 2)
        self.assertGreaterEqual(len(parts), 3, "Invalid frontmatter structure in SKILL.md")
        fm = parts[1]
        self.assertIn("name: edge-distill", fm)
        self.assertIn("suggested_skills:", fm)
        self.assertIn("edge-orchestrator", fm)
        self.assertIn("edge-brigade", fm)

    def test_zero_legacy_flight_recorder_references(self):
        text = self.skill_path.read_text(encoding="utf-8")
        text_lower = text.lower()
        self.assertNotIn("incident flight recorder", text_lower)
        self.assertNotIn("rules/playbooks/proposals", text_lower)
        self.assertNotIn("operational journaler", text_lower)

        # Legacy CLI commands
        for cmd in ["cli.py start", "cli.py log", "cli.py resolve", "cli.py propose"]:
            self.assertNotIn(cmd, text_lower, f"Legacy command '{cmd}' must not be present in SKILL.md")

    def test_exact_v2_cli_contracts(self):
        """
        Spec Refinement 1: Exact CLI syntax alignment with Slice 2:
        - python3 tools/distill/cli.py harvest --project <repo_path> --format toon (or harvest <repo_path> --format toon)
        - python3 tools/distill/cli.py candidates list
        - python3 tools/distill/cli.py candidates record --rule "<rule>" --role <role> --project <repo_path>
        - python3 tools/distill/cli.py promote --candidate <id>
        - python3 tools/distill/cli.py check-budget
        - python3 tools/distill/cli.py mark-processed --session <cid>
        Zero invalid CLI syntax like 'candidates <repo' before 'list' or 'record'.
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("harvest", text)
        self.assertIn("--format toon", text)
        self.assertIn("candidates list", text)
        self.assertIn("candidates record", text)
        self.assertIn("promote", text)
        self.assertIn("--candidate", text)
        self.assertIn("check-budget", text)
        self.assertIn("mark-processed", text)
        self.assertIn("--session", text)

        # Disallow malformed 'candidates <repo> list' or 'candidates <repo> record'
        self.assertFalse(
            bool(re.search(r"candidates\s+<[^>]+>\s+(?:list|record)", text)),
            "Found invalid CLI syntax: '<repo>' should not be placed between 'candidates' and 'list'/'record'",
        )

    def test_cold_goldfish_synthesis_and_lens_requirements(self):
        """
        Verifies Cold Goldfish requirements in Step 2:
        - Model: "flash"
        - Role: "Examiner"
        - Explicit read_file rubric injection
        - <untrusted_telemetry_digest>
        - --deep 3-lens fan-out
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn('Model: "flash"', text)
        self.assertIn('Role: "Examiner"', text)
        self.assertIn("read_file", text)
        self.assertIn("<untrusted_telemetry_digest>", text)
        self.assertIn("--deep", text)
        self.assertIn("judgment-lens.md", text)
        self.assertIn("tooling-lens.md", text)
        self.assertIn("divergent-lens.md", text)
        self.assertIn("synthesizer.md", text)

    def test_poteto_routing_and_line_budget_caps(self):
        """
        Verifies Step 3 Poteto 4-level routing, LexicalStackGate, and 60/40 line caps.
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("LexicalStackGate", text)
        self.assertIn("REPO_LOCAL", text)
        self.assertIn("PLUGIN_CANDIDATE", text)
        self.assertIn("60", text)
        self.assertIn("40", text)

    def test_dual_channel_delivery_and_unattended_scheduling(self):
        """
        Verifies Step 4 Dual-Channel Delivery (tasks-axi for structural/tooling)
        and Step 5 unattended /schedule guidance (not blocking on ask_question).
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("tasks-axi", text)
        self.assertIn("Channel A", text)
        self.assertIn("Channel B", text)
        self.assertIn("/schedule", text)
        self.assertIn("ask_question", text)
        self.assertIn("unattended", text.lower())


    def test_project_mode_vs_factory_mode_boundaries(self):
        """
        Spec Section 4.1 & Section 8.1:
        SKILL.md must document PROJECT_MODE vs FACTORY_MODE:
        - In PROJECT_MODE: writes restricted to .edge/stations/ or coding_standards.md;
          strictly forbids writing to edge plugin directory (agents/*.md, skills/**).
          Harness signals queued to edge_factory_inbox.json.
        - In FACTORY_MODE: modifies agents/*.md and skills/**, verified by check-budget,
          pytest, and sealed in atomic git commit.
        - Documents --mode auto|project|factory and --clear-factory-inbox.
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("PROJECT_MODE", text)
        self.assertIn("FACTORY_MODE", text)
        self.assertIn("edge_factory_inbox.json", text)
        self.assertIn("--clear-factory-inbox", text)
        self.assertIn("--mode", text)
        text_lower = text.lower()
        self.assertIn("coding_standards.md", text)
        self.assertIn("atomic git commit", text_lower)

    def test_frontier_first_channel_b_default_gate(self):
        """
        Spec Section 4.2 & AXI Rule 1.A:
        Channel B structural/tooling proposals must default to frontier-axi parking lot.
        Direct tasks-axi creation occurs ONLY upon explicit Captain selection/escalation.
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("frontier-axi", text)
        self.assertIn("frontier-axi add", text)
        self.assertIn("parking lot", text.lower())

    def test_navigation_lens_and_telemetry_sections_in_skill(self):
        """
        Slice 1 Pillar 5:
        SKILL.md must integrate navigation-lens.md, the new TOON digest sections
        (Navigation & Tool Economy, Guardrail Gaps, Rule Inventory), and
        docs/<domain>/DOMAIN.md Context Pointer output.
        """
        text = self.skill_path.read_text(encoding="utf-8")
        self.assertIn("navigation-lens.md", text)
        self.assertIn("Navigation & Tool Economy", text)
        self.assertIn("Guardrail Gaps", text)
        self.assertIn("Rule Inventory", text)
        self.assertIn("docs/<domain>/DOMAIN.md", text)


class TestDistillReferenceRubrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.refs_dir = cls.repo_root / "skills" / "edge-distill" / "references"
        cls.expected_files = [
            "synthesizer.md",
            "judgment-lens.md",
            "tooling-lens.md",
            "divergent-lens.md",
            "navigation-lens.md",
        ]

    def test_all_reference_files_exist_and_budget(self):
        for fname in self.expected_files:
            fpath = self.refs_dir / fname
            self.assertTrue(fpath.is_file(), f"Missing reference file: {fpath}")
            content = fpath.read_text(encoding="utf-8").strip()
            self.assertTrue(len(content) > 0, f"Reference file {fname} is empty")
            lines = content.splitlines()
            self.assertLessEqual(
                len(lines),
                80,
                f"Reference file {fname} exceeds 80 lines budget: {len(lines)} lines",
            )

    def test_untrusted_telemetry_guardrail_present_in_all_references(self):
        for fname in self.expected_files:
            fpath = self.refs_dir / fname
            self.assertTrue(fpath.is_file(), f"Missing reference file: {fpath}")
            text = fpath.read_text(encoding="utf-8")
            self.assertIn(
                "<untrusted_telemetry_digest>",
                text,
                f"{fname} missing mandatory '<untrusted_telemetry_digest>' tag",
            )
            self.assertIn(
                "UNTRUSTED TELEMETRY GUARDRAIL",
                text,
                f"{fname} missing 'UNTRUSTED TELEMETRY GUARDRAIL' header/section",
            )

    def test_lens_specific_domain_coverage(self):
        # 1. judgment-lens.md covers downstream station escapes & repeated user corrections
        j_path = self.refs_dir / "judgment-lens.md"
        self.assertTrue(j_path.is_file(), f"Missing reference file: {j_path}")
        j_text = j_path.read_text(encoding="utf-8")
        self.assertIn("SPEC_WRITER", j_text)
        self.assertIn("SPEC_CRITIC", j_text)
        self.assertIn("EXAMINER", j_text)
        self.assertIn("SURGEON", j_text)
        self.assertIn("CODER", j_text)
        self.assertIn("escapes", j_text.lower())

        # 2. tooling-lens.md covers tool friction / meat-proxy, guardrail gaps & TOKEN_BLOAT
        t_path = self.refs_dir / "tooling-lens.md"
        self.assertTrue(t_path.is_file(), f"Missing reference file: {t_path}")
        t_text = t_path.read_text(encoding="utf-8")
        self.assertIn("meat-proxy", t_text.lower())
        self.assertIn("tasks-axi", t_text)
        self.assertIn("friction", t_text.lower())
        self.assertIn("Guardrail Gaps", t_text)
        self.assertIn("UNWIRED_GUARDRAIL", t_text)
        self.assertIn("MISSING_GUARDRAIL", t_text)
        self.assertIn("TOKEN_BLOAT", t_text)
        self.assertIn("frontier-axi", t_text)

        # 3. divergent-lens.md covers No-Op pruning / bloat compaction & Rule Inventory
        d_path = self.refs_dir / "divergent-lens.md"
        self.assertTrue(d_path.is_file(), f"Missing reference file: {d_path}")
        d_text = d_path.read_text(encoding="utf-8")
        self.assertIn("no-op", d_text.lower())
        self.assertIn("budget", d_text.lower())
        self.assertIn("prun", d_text.lower())
        self.assertIn("Rule Inventory", d_text)
        self.assertIn("citation_count", d_text)
        self.assertIn("package.json", d_text)

        # 4. synthesizer.md covers Judgment, Tooling, and Navigation & Context-Pointer axes
        s_path = self.refs_dir / "synthesizer.md"
        self.assertTrue(s_path.is_file(), f"Missing reference file: {s_path}")
        s_text = s_path.read_text(encoding="utf-8")
        self.assertIn("Judgment", s_text)
        self.assertIn("Tooling", s_text)
        self.assertIn("tasks-axi", s_text)
        self.assertIn("Navigation & Tool Economy", s_text)
        self.assertIn("Guardrail Gaps", s_text)
        self.assertIn("Rule Inventory", s_text)
        self.assertIn("docs/<domain>/DOMAIN.md", s_text)
        self.assertIn("1-command", s_text.lower())

        # 5. navigation-lens.md covers Context Pointers, 1-command anti-cache, and 3-way routing
        n_path = self.refs_dir / "navigation-lens.md"
        self.assertTrue(n_path.is_file(), f"Missing reference file: {n_path}")
        n_text = n_path.read_text(encoding="utf-8")
        self.assertIn("docs/<domain>/DOMAIN.md", n_text)
        self.assertIn("1-command", n_text.lower())
        self.assertIn("package.json", n_text)
        self.assertIn("EXPLORATION_BURST", n_text)
        self.assertIn("REDUNDANT_READ", n_text)
        self.assertIn("EMPTY_SEARCH_CHAIN", n_text)
        self.assertIn("UNWIRED_GUARDRAIL", n_text)
        self.assertIn("MISSING_GUARDRAIL", n_text)
        self.assertIn("frontier-axi", n_text)
        self.assertIn("tasks-axi", n_text)
        self.assertIn(".edge/stations/", n_text)


class TestDistillDocsSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.arch_path = cls.repo_root / "ARCHITECTURE.md"
        cls.inst_path = cls.repo_root / "INSTRUCTIONS.md"

    def test_architecture_md_synced(self):
        self.assertTrue(self.arch_path.is_file(), f"Missing {self.arch_path}")
        text = self.arch_path.read_text(encoding="utf-8")

        # Zero legacy v1 commands or file leaks
        self.assertNotIn("bookings-playbook.md", text)
        self.assertNotIn("customers-playbook.md", text)
        self.assertNotIn("distill/cli.py start", text)
        self.assertNotIn("distill/cli.py propose", text)
        self.assertNotIn("rules/playbooks/generated", text)

        # Contains v2 self-improving factory terminology
        text_lower = text.lower()
        self.assertIn("self-improving", text_lower)
        self.assertIn("harvester", text_lower)

    def test_instructions_md_synced(self):
        self.assertTrue(self.inst_path.is_file(), f"Missing {self.inst_path}")
        text = self.inst_path.read_text(encoding="utf-8")

        # Zero legacy v1 references
        self.assertNotIn("bookings-playbook.md", text)
        self.assertNotIn("customers-playbook.md", text)
        self.assertNotIn("distill/cli.py start", text)
        self.assertNotIn("distill/cli.py propose", text)
        self.assertNotIn("rules/playbooks/generated", text)

        # References v2 commands: harvest, candidates, check-budget
        self.assertIn("harvest", text)
        self.assertIn("candidates", text)
        self.assertIn("check-budget", text)


if __name__ == "__main__":
    unittest.main()
