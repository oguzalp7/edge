"""Examiner review and surgeon polish prompt builders."""

from pathlib import Path
from typing import List, Optional

from tools.brigade.models import ReviewFinding, Ticket
from tools.brigade.navigation import resolve_migration_paths
from tools.brigade.station_dispatch import _resolve_stage_target, _resolve_target_label
from tools.brigade.station_qa_params import _resolve_qa_slug
from tools.brigade.station_rubric import _with_navigation_context, load_station_rubric


def _examiner_axes_section(schema_glob: str, migration_glob: str, slug: str) -> str:
    return f"""3-AXIS EVIDENCE-FIRST REVIEW DIRECTIVES:
Axis 1 (Standards & Fowler Smells -- `--axis standards`):
1. Verify if the diff complies with `coding_standards.md` (explicit types, transaction safety, error boundaries, zero raw leaks).
2. Spot Fowler code smells in the diff and distinguish HARD VIOLATIONS from advisory guidance.

Axis 2 (Architectural & Spec Boundaries -- `--axis spec`):
1. MigrationGate Invariant: On refactor tracks, ensure `{schema_glob}` and `{migration_glob}` are untouched.
2. Layer Leakage & Max CC: Verify action controllers do not add DB leaks and functions stay within CC <= 10.
3. Zero-Wrapper & Scope Creep: Flag shallow pass-through services or out-of-domain changes.

Axis 3 (Multimodal Behavioral & Evidence Review -- `--axis evidence`):
1. Inspect `gate.py` verification status, `.edge/qa/visual/{slug}-diff.png` & baseline/refactored images (if `track == "ui"`), and `.edge/qa/proofs/{slug}.json` + referenced screenshots + `db_crosscheck` (if QA ran).
2. Verify implemented behavior and visual/DOM/DB evidence actually satisfy `.edge/specs/` and `.lavish/` contracts without stubs or superficial workarounds.
3. Record behavioral/evidence gaps via `brigade add-finding <repo> --axis evidence ...`.

MANDATORY SEAL & REPORT DISCIPLINE:
Keep findings concise (under 350 words). Categorize findings by severity (CRITICAL, WARNING, ADVISORY).
Before running `brigade advance`, you MUST seal your verdict via:
`brigade seal-review <repo> --verdict PASS|FAIL --summary "<concise summary>" --evidence-reviewed "<paths>"`
If clean, state: 'EXAMINER REVIEW: PASS' and seal `--verdict PASS`."""


def build_examiner_prompt(ticket: Ticket, base_branch: str, repo_path: Optional[Path] = None) -> str:
    """Constructs a unified 3-axis evidence-first review ticket for the EXAMINER station."""
    rubric = load_station_rubric("examiner", repo_path=repo_path)
    target_label = _resolve_target_label(ticket)
    schema_glob, migration_glob = resolve_migration_paths(repo_path)
    expected_line = f"\n- Expected Files: {', '.join(ticket.expected_files)}" if getattr(ticket, "expected_files", None) else ""
    slug = _resolve_qa_slug("qa_scenario", ticket)
    axes_block = _examiner_axes_section(schema_glob, migration_glob, slug)
    prompt = f"""You are the EXAMINER station worker in Edge Brigade.

DIFF INSPECTION:
Target Diff: `git diff {base_branch}..HEAD`

REVIEW SOURCES:
1. `coding_standards.md` in repository root.
2. Fowler Code Smell Baseline (Mysterious Name, Duplicated Code, Feature Envy, Data Clumps, Primitive Obsession, Message Chains, Middle Man).
3. Architectural Specification (`skills/edge-core-refactor/SKILL.md` or `edge-ui-refactor/SKILL.md` or `.edge/specs/`).
4. Physical Execution Evidence: `tools/gate.py` status, `.edge/qa/visual/{slug}-diff.png` (if `track == "ui"`), `.edge/qa/proofs/{slug}.json` + screenshots + `db_crosscheck`, and `.lavish/` contracts.

TICKET CONTEXT:
- Ticket ID: {ticket.ticket_id}
- Track: {getattr(ticket, 'track', 'core')}
- Domain: {ticket.domain}
- Target File: {target_label}{expected_line}

{axes_block}

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket)


def build_polish_prompt(ticket: Ticket, findings: List[ReviewFinding], repo_path: Optional[Path] = None) -> str:
    """Constructs remediation instructions for the SURGEON station."""
    rubric = load_station_rubric("surgeon", repo_path=repo_path)
    findings_text = "\n".join([
        f"- [{f.axis.upper()}] ({f.severity}) {f.file_path}:{f.line_number or 'N/A'}: {f.description}\n  Suggested Fix: {f.suggested_fix}"
        for f in findings
    ])

    prompt = f"""You are the SURGEON station worker in Edge Brigade.

MISSION:
Execute Polish Remediation on branch `{ticket.branch_name}` for ticket `{ticket.ticket_id}`.
Review stations identified the following findings that must be remediated:

FINDINGS TO FIX:
{findings_text}

INSTRUCTIONS:
1. Address each finding strictly without violating MigrationGate, Max CC Non-Regression, or Layer Leakage Gate.
2. Run `{ticket.test_seam_command}` to verify hermetic cleanliness.
3. Commit the changes:
   `git commit -am "refactor({ticket.domain}): polish review findings ({ticket.ticket_id})"`
4. Report the resulting git diff and test verification output.

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket, extra_paths=[f.file_path for f in findings])
