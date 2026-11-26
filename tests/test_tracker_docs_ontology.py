"""
Hermetic RED contract tests for Slice 4 (`tracker-docs-ontology-alignment`).

Covers `.edge/specs/tracker-docs-ontology-alignment.md`:
- `INV-ONTOLOGY-ZERO-ERRORS`: `validate_ontology(REPO_ROOT)` == 0 issues and zero
  `CODE_LEAK_IN_DOMAIN_DOC` leaks across `docs/{brigade,delivery,drift,orchestration}/DOMAIN.md`
- `INV-GLOSSARY-SYMBOL-BINDING`: `CONTEXT.md` Domain Map ownership + Closed Concept Glossary
  rows (`github-issues-ssot`, `fail-fast-tracker-auth`, `ephemeral-spec-cache`) bound to real
  AST-verified symbols in `tools/tracker/` and `tools/brigade/tracker_hooks.py`
- `INV-RUBRIC-LINE-BUDGET`: `ok, n, limit = check_line_budget(..., max_lines=60)` unpacked
  on `agents/{spec-writer,examiner,qa-engineer}.md` + tracker workflow alignment
- `INV-PRESERVED-TEST-TOKENS`: rules & skills aligned to `tools/tracker/`, `spec:approved`,
  `status:done`, `Closes #`, `--issue`/`--parent-issue`, soft deprecation of `tasks-axi` /
  `frontier-axi`, while preserving every existing regression assertion token
"""

import ast
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.distill.state import check_line_budget
from tools.drift.models import (
    matches_tracked_paths,
    parse_canonical_domain_doc,
    parse_context_glossary,
)
from tools.drift.scanner import validate_ontology


def _read_utf8(rel_path: str) -> str:
    path = ROOT_DIR / rel_path
    assert path.is_file(), f"Missing expected file: {rel_path}"
    return path.read_text(encoding="utf-8-sig")


def _extract_glossary_rows(context_text: str) -> Dict[str, tuple[str, str]]:
    rows: Dict[str, tuple[str, str]] = {}
    in_glossary = False
    for line in context_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_glossary = "Closed Concept Glossary" in stripped
            continue
        if not in_glossary or not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 3 or cells[0].startswith("---") or cells[0].lower() == "concept":
            continue
        concept = cells[0].strip("`").strip()
        if concept:
            rows[concept] = (cells[1], cells[2])
    return rows


def _ast_defined_symbols(py_path: Path) -> Set[str]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


class TestTrackerDocsOntologyAlignment:
    def test_inv_ontology_zero_errors_and_domain_alignment(self) -> None:
        report = validate_ontology(ROOT_DIR)
        assert not report.skipped, "Repo ontology validation must not be skipped"
        assert not report.has_errors, f"Ontology errors found: {report.issues}"
        assert report.issues == [], f"Expected 0 ontology issues, got: {report.issues}"
        assert len(report.domain_docs) == 6

        for domain in ("brigade", "delivery", "drift", "orchestration"):
            rel = f"docs/{domain}/DOMAIN.md"
            text = _read_utf8(rel)
            assert ".edge/" not in text, f"{rel} leaked .edge/ path"
            assert "`GitHub`" not in text, f"{rel} leaked backticked PascalCase `GitHub`"
            assert "- **Paths:**" not in text, f"{rel} must not declare - **Paths:**"

        brigade_doc = parse_canonical_domain_doc(
            _read_utf8("docs/brigade/DOMAIN.md"),
            doc_path="docs/brigade/DOMAIN.md",
            fallback_domain="brigade",
        )
        assert {
            "github-issues-ssot",
            "fail-fast-tracker-auth",
            "ephemeral-spec-cache",
        }.issubset(set(brigade_doc.concepts))

        delivery_low = _read_utf8("docs/delivery/DOMAIN.md").lower()
        assert "parent" in delivery_low and ("auto-close" in delivery_low or "child" in delivery_low)

        drift_low = _read_utf8("docs/drift/DOMAIN.md").lower()
        assert "cache" in drift_low and "issue" in drift_low and "consolidat" in drift_low

        orch_low = _read_utf8("docs/orchestration/DOMAIN.md").lower()
        assert "parent" in orch_low and "issue" in orch_low and ("soft-deprecat" in orch_low or "legacy" in orch_low)

    def test_inv_glossary_symbol_binding(self) -> None:
        context_text = _read_utf8("CONTEXT.md")
        context_globs, context_concepts = parse_context_glossary(context_text)

        assert matches_tracked_paths(
            [
                "tools/tracker/cli.py",
                "tools/tracker/models.py",
                "tools/brigade/tracker_hooks.py",
            ],
            context_globs["brigade"],
        ) == [
            "tools/tracker/cli.py",
            "tools/tracker/models.py",
            "tools/brigade/tracker_hooks.py",
        ]
        assert matches_tracked_paths(
            ["tools/brigade/ship_tracker.py"],
            context_globs["delivery"],
        ) == ["tools/brigade/ship_tracker.py"]

        glossary_rows = _extract_glossary_rows(context_text)
        expected_bindings = {
            "github-issues-ssot": ("resolve_backend", "GhAxiBackend", "LocalTrackerBackend"),
            "fail-fast-tracker-auth": ("TrackerAuthError", "preflight_ticket_tracker"),
            "ephemeral-spec-cache": ("cache_issue_spec", "resolve_slice_issue_spec"),
        }
        all_tracker_files = [
            *sorted((ROOT_DIR / "tools" / "tracker").glob("*.py")),
            ROOT_DIR / "tools" / "brigade" / "tracker_hooks.py",
        ]
        available_by_file: Dict[str, Set[str]] = {
            p.relative_to(ROOT_DIR).as_posix(): _ast_defined_symbols(p)
            for p in all_tracker_files
            if p.is_file()
        }

        for concept, req_symbols in expected_bindings.items():
            assert concept in context_concepts, f"CONTEXT.md missing glossary concept '{concept}'"
            assert concept in glossary_rows, f"CONTEXT.md missing glossary table row for '{concept}'"
            symbol_col, _meaning = glossary_rows[concept]
            cited_files = re.findall(r"tools/[a-zA-Z0-9_/]+\.py", symbol_col)
            assert cited_files, f"Glossary row '{concept}' must cite real tools/*.py file paths"
            for rel_file in cited_files:
                assert rel_file in available_by_file, f"Glossary row '{concept}' cites unknown file '{rel_file}'"
            cited_symbol_pool: Set[str] = set()
            for rel_file in cited_files:
                cited_symbol_pool.update(available_by_file[rel_file])
            for sym in req_symbols:
                assert sym in symbol_col, f"Glossary row '{concept}' missing symbol '{sym}'"
                assert sym in cited_symbol_pool, f"Symbol '{sym}' not found in AST of {cited_files}"

    def test_inv_rubric_line_budget_and_tracker_alignment(self) -> None:
        for rel in ("agents/spec-writer.md", "agents/examiner.md", "agents/qa-engineer.md"):
            ok, line_count, limit = check_line_budget(ROOT_DIR / rel, max_lines=60)
            assert ok, f"{rel} exceeded 60-line budget ({line_count}/{limit})"
            assert limit == 60
            assert line_count <= 60

        spec_writer = _read_utf8("agents/spec-writer.md")
        assert "tools/tracker" in spec_writer
        assert "spec:draft" in spec_writer and "spec:approved" in spec_writer
        assert ".edge/cache/issues/" in spec_writer
        for tok in ("200", "value sourcing", "pagination", "idempotency", "abac", "4-state"):
            assert tok in spec_writer.lower()
        next_sw = _read_utf8("profiles/nextjs-drizzle-tailwind/agents/spec-writer.md")
        assert "force-dynamic" in next_sw.lower()

        examiner = _read_utf8("agents/examiner.md")
        assert ".edge/cache/issues/" in examiner
        for tok in ("Axis 3", "seal-review", "[READY_FOR_STAGING]"):
            assert tok in examiner

        qa_eng = _read_utf8("agents/qa-engineer.md")
        assert "qa-inspect --frontier" in qa_eng
        assert "tools/tracker" in qa_eng or "type:frontier" in qa_eng
        for tok in ("double-submit", "reload", "pagination", "4-state", "dark"):
            assert tok in qa_eng.lower()

    def test_rules_alignment_and_preserved_tokens(self) -> None:
        agents_rule = _read_utf8("rules/AGENTS.md")
        agents_low = agents_rule.lower()
        assert "tools/tracker/" in agents_rule
        assert ".edge/issues/" in agents_rule
        assert "soft-deprecated" in agents_low or "soft deprecated" in agents_low
        assert "tasks-axi" in agents_rule and "frontier-axi" in agents_rule
        assert ".edge/stations/" in agents_rule
        assert "swarm-vs-brigade.md" in agents_rule
        assert "<domain>-playbook.md" not in agents_rule

        feature_rule = _read_utf8("rules/feature.md")
        feature_low = feature_rule.lower()
        for tok in (
            "CycleState.QA",
            "Lavish varsa QA yap, yoksa es geç",
            "critique-spec --issue",
            "start-slice --issue",
            "qa-inspect --frontier",
            "spec:approved",
            "status:done",
            "Closes #",
        ):
            assert tok in feature_rule, f"rules/feature.md missing '{tok}'"
        assert "soft-deprecated" in feature_low or "soft deprecated" in feature_low

        refactor_rule = _read_utf8("rules/refactor.md")
        refactor_low = refactor_rule.lower()
        for tok in ("tools/tracker", "status:done", "confirm-merge", "Closes #"):
            assert tok in refactor_rule, f"rules/refactor.md missing '{tok}'"
        assert "soft-deprecated" in refactor_low or "soft deprecated" in refactor_low

    def test_skills_alignment_and_preserved_tokens(self) -> None:
        orch = _read_utf8("skills/edge-orchestrator/SKILL.md")
        orch_low = orch.lower()
        assert "tools/tracker" in orch or "--issue" in orch
        assert "qa-inspect --frontier" in orch or "type:frontier" in orch
        assert "grill-with-docs" in orch_low and "fork" in orch_low
        phase0_idx = orch_low.find("phase 0") if "phase 0" in orch_low else orch_low.find("faz 0")
        phase1_idx = orch_low.find("phase 1") if "phase 1" in orch_low else orch_low.find("invest")
        assert 0 <= phase0_idx < phase1_idx

        brigade = _read_utf8("skills/edge-brigade/SKILL.md")
        brigade_low = brigade.lower()
        for tok in (
            "tools/tracker",
            "start-slice --issue",
            "--parent-issue",
            "critique-spec --issue",
            "spec:approved",
            "status:done",
            ".edge/cache/issues/",
        ):
            assert tok in brigade, f"skills/edge-brigade/SKILL.md missing '{tok}'"
        assert "soft-deprecated" in brigade_low or "soft deprecated" in brigade_low

        ship = _read_utf8("skills/edge-ship/SKILL.md")
        for tok in (
            "--issue",
            "--parent-issue",
            "Closes #",
            "status:done",
            "--split-branches",
            "gh pr checks",
            "gh pr create",
            "--base staging",
        ):
            assert tok in ship, f"skills/edge-ship/SKILL.md missing '{tok}'"
        assert "1-minute briefing" in ship.lower()
        assert "no-mistakes axi run" not in ship

        drift = _read_utf8("skills/edge-drift/SKILL.md")
        drift_low = drift.lower()
        assert "consolidate" in drift and "--issue" in drift
        assert ".edge/cache/issues/" in drift
        assert "tools/tracker" in drift
        assert "soft-deprecated" in drift_low or "soft deprecated" in drift_low

        radar = _read_utf8("skills/edge-radar/SKILL.md")
        radar_low = radar.lower()
        assert "export-tasks" in radar and "--parent-issue" in radar
        assert "tools/tracker" in radar
        assert "soft-deprecated" in radar_low or "soft deprecated" in radar_low

        no_mistakes = _read_utf8("skills/edge-no-mistakes/SKILL.md")
        nm_low = no_mistakes.lower()
        assert "gh issue create" in no_mistakes
        assert "frontier-axi" in no_mistakes
        assert "tools/tracker" in no_mistakes
        assert "soft-deprecated" in nm_low or "soft deprecated" in nm_low

        # Untouched edge-distill invariants stay intact
        distill = _read_utf8("skills/edge-distill/SKILL.md")
        for tok in ("Commander Decision Card", "Channel B", "tasks-axi", "frontier-axi"):
            assert tok in distill
