#!/usr/bin/env python3
"""
Contract and Self-Ontology Tests for Edge Context System v1.0 ([AC-01]..[AC-06], [AC-10]).
"""

import sys
import unittest
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

CANONICAL_DOMAINS = (
    "orchestration",
    "brigade",
    "distill",
    "drift",
    "quality-gates",
    "delivery",
)


class TestContextSystemContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]

    def test_ac01_constitution_and_agents_link(self):
        rule_path = self.repo_root / "rules" / "context-system.md"
        self.assertTrue(rule_path.is_file(), f"Missing {rule_path}")
        rule_text = rule_path.read_text(encoding="utf-8")
        rule_lower = rule_text.lower()

        self.assertIn("design system", rule_lower)
        self.assertIn("program system", rule_lower)
        self.assertIn("context system", rule_lower)
        self.assertTrue(
            "diátaxis" in rule_lower or "diataxis" in rule_lower,
            "rules/context-system.md must reference Diátaxis",
        )
        self.assertIn("CONTEXT.md", rule_text)
        self.assertIn("DOMAIN.md", rule_text)
        for tag in ("@intent", "@concepts", "@invariants"):
            self.assertIn(tag, rule_text)
        self.assertIn("dependency inversion", rule_lower)
        self.assertIn("CODE_LEAK_IN_DOMAIN_DOC", rule_text)

        agents_path = self.repo_root / "rules" / "AGENTS.md"
        self.assertTrue(agents_path.is_file(), f"Missing {agents_path}")
        agents_text = agents_path.read_text(encoding="utf-8")
        self.assertIn("context-system.md", agents_text)
        self.assertIn("CONTEXT.md", agents_text)
        self.assertIn("grill-with-docs", agents_text)

    def test_ac01_ac10_self_ontology_docs_and_validation(self):
        from tools.drift.models import (
            matches_tracked_paths,
            parse_canonical_domain_doc,
            parse_context_glossary,
        )
        from tools.drift.scanner import validate_ontology
        from tools.drift.cli import run_drift

        context_path = self.repo_root / "CONTEXT.md"
        self.assertTrue(context_path.is_file(), f"Missing {context_path}")
        context_text = context_path.read_text(encoding="utf-8-sig")
        self.assertIn("## Domain Map", context_text)
        self.assertIn("## Closed Concept Glossary", context_text)
        context_globs, context_concepts = parse_context_glossary(context_text)
        self.assertTrue(context_concepts)

        for domain in CANONICAL_DOMAINS:
            self.assertIn(domain, context_globs, f"CONTEXT.md missing Domain Map globs for {domain}")
            self.assertTrue(context_globs[domain], f"Empty globs in CONTEXT.md for {domain}")
            dom_path = self.repo_root / "docs" / domain / "DOMAIN.md"
            self.assertTrue(dom_path.is_file(), f"Missing canonical deed {dom_path}")
            parsed = parse_canonical_domain_doc(
                dom_path.read_text(encoding="utf-8-sig"),
                doc_path=f"docs/{domain}/DOMAIN.md",
                fallback_domain=domain,
            )
            self.assertEqual(parsed.domain, domain)
            self.assertEqual(parsed.tracked_paths, [], f"{dom_path} must NOT declare - **Paths:** in v1.1")
            self.assertEqual(parsed.enforced_by, [], f"{dom_path} must NOT declare *Enforced by:* in v1.1")
            self.assertTrue(parsed.owner, f"{dom_path} missing Owner / DRI:")
            self.assertTrue(parsed.concepts, f"{dom_path} missing Concepts:")
            self.assertGreaterEqual(len(parsed.invariant_ids), 2, f"{dom_path} needs >=2 [INV-*]")
            self.assertGreaterEqual(len(parsed.pattern_ids), 1, f"{dom_path} needs >=1 [PAT-*]")

        # §4 ownership invariants resolved via CONTEXT.md Domain Map SSOT
        self.assertEqual(
            matches_tracked_paths(
                ["skills/edge-technical-writing/SKILL.md", "skills/edge-gnhf/SKILL.md"],
                context_globs["orchestration"],
            ),
            ["skills/edge-technical-writing/SKILL.md", "skills/edge-gnhf/SKILL.md"],
        )
        self.assertEqual(
            matches_tracked_paths(
                ["tools/brigade/cli.py", "tools/brigade/fsm.py"],
                context_globs["delivery"],
            ),
            [],
        )

        report = validate_ontology(self.repo_root)
        self.assertFalse(report.skipped, "Repo ontology validation must not be skipped")
        self.assertFalse(report.has_errors, f"Repo ontology validation failed: {report.issues}")
        self.assertEqual(report.issues, [], f"Expected 0 errors and 0 warnings on repo: {report.issues}")
        self.assertEqual(len(report.domain_docs), 6)
        self.assertGreater(len(report.context_concepts), 0)
        self.assertTrue(getattr(report, "invariant_index", None), "Repo invariant_index must be non-empty")

        indexed_files = {p for paths in report.invariant_index.values() for p in paths}
        for anchor_file in (
            "tools/drift/scanner.py",
            "tools/brigade/ship_prep.py",
            "tools/brigade/navigation.py",
        ):
            self.assertIn(anchor_file, indexed_files, f"Expected live @invariants anchor in {anchor_file}")

        self.assertEqual(run_drift(["check", str(self.repo_root), "--ontology-only"]), 0)

    def test_ac02_technical_writing_skill(self):
        skill_path = self.repo_root / "skills" / "edge-technical-writing" / "SKILL.md"
        self.assertTrue(skill_path.is_file(), f"Missing {skill_path}")
        text = skill_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLess(len(lines), 120, f"SKILL.md must be < 120 lines (got {len(lines)})")

        self.assertTrue(text.startswith("---"), "SKILL.md must start with YAML frontmatter")
        parts = text.split("---", 2)
        self.assertGreaterEqual(len(parts), 3)
        fm = parts[1]
        self.assertIn("name: edge-technical-writing", fm)
        self.assertIn("disable-model-invocation: true", fm)

        low = text.lower()
        self.assertTrue("diátaxis" in low or "diataxis" in low, "Must cover Diátaxis")
        self.assertTrue(
            ("single-term" in low or "single term" in low) and "symbol" in low,
            "Must cover single-term / real-symbol discipline",
        )
        self.assertIn("1-minute briefing", low)
        self.assertTrue(
            "self-verifying" in low or ("verify" in low and "count" in low),
            "Must cover self-verifying counts",
        )
        self.assertIn("dependency inversion", low)
        self.assertIn("CODE_LEAK_IN_DOMAIN_DOC", text)

    def test_ac03_orchestrator_phase_0_intake(self):
        orch_path = self.repo_root / "skills" / "edge-orchestrator" / "SKILL.md"
        self.assertTrue(orch_path.is_file(), f"Missing {orch_path}")
        text = orch_path.read_text(encoding="utf-8")
        low = text.lower()

        self.assertIn("grill-with-docs", low)
        self.assertIn("CONTEXT.md", text)

        phase0_pos = low.find("phase 0") if "phase 0" in low else low.find("faz 0")
        self.assertNotEqual(phase0_pos, -1, "Must define Phase 0 intake step")
        grill_pos = low.find("grill-with-docs")
        phase1_pos = low.find("phase 1") if "phase 1" in low else low.find("invest")
        self.assertNotEqual(phase1_pos, -1, "Must define Phase 1 / INVEST step")
        self.assertLess(phase0_pos, phase1_pos, "Phase 0 must precede Phase 1")
        self.assertLess(grill_pos, phase1_pos, "grill-with-docs glossary lock must precede Phase 1")

        # Preserve existing test_brigade.py invariants
        self.assertIn("fork", low)
        self.assertTrue("spec_writer" in text and "researcher" in text)

    def test_ac04_ac05_distill_commander_decision_card(self):
        distill_path = self.repo_root / "skills" / "edge-distill" / "SKILL.md"
        self.assertTrue(distill_path.is_file(), f"Missing {distill_path}")
        text = distill_path.read_text(encoding="utf-8")
        low = text.lower()

        self.assertIn("commander decision card", low)
        for token in ("what failed", "rule diff", "risk if rejected", "possible conflict"):
            self.assertIn(token, low, f"4-Line Commander Decision Card missing '{token}'")
        self.assertIn("REJECT", text)
        self.assertNotIn(
            "| # | Channel | Target | Budget | Description | Evidence Citation |",
            text,
            "Legacy 6-column table must be replaced by the 4-Line Commander Decision Card",
        )
        self.assertIn("docs/<domain>/DOMAIN.md", text)

        for preserved in (
            "Channel A",
            "Channel B",
            "tasks-axi",
            "frontier-axi",
            "/schedule",
            "ask_question",
            "Navigation & Tool Economy",
            "Guardrail Gaps",
            "Rule Inventory",
        ):
            self.assertIn(preserved, text)

    def test_ac06_ship_one_minute_briefing(self):
        ship_path = self.repo_root / "skills" / "edge-ship" / "SKILL.md"
        self.assertTrue(ship_path.is_file(), f"Missing {ship_path}")
        text = ship_path.read_text(encoding="utf-8")
        self.assertIn("1-minute briefing", text.lower())

        for preserved in (
            "Spec Expectations vs. Realization",
            "Examiner 3-Axis Seal",
            "Tier 1",
            "Tier 2",
            "--base development",
            "smoke-routes",
            "--require-smoke",
            "TICK-PERF-",
            "--settle-budget-ms",
            "--allow-topology-override",
            "--stage-branch",
            "security-audit",
            "Security & ABAC Audit",
        ):
            self.assertIn(preserved, text)


if __name__ == "__main__":
    unittest.main()
