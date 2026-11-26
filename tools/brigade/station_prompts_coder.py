"""Coder feature and polish prompt builders."""

from pathlib import Path
from typing import List, Optional

from tools.brigade.models import ReviewFinding, Ticket
from tools.brigade.station_dispatch import _resolve_stage_target, _resolve_target_label
from tools.brigade.station_rubric import _with_navigation_context, load_station_rubric

def build_coder_prompt(ticket: Ticket, red_test_cmd: str, repo_path: Optional[Path] = None) -> str:
    """Constructs a prompt for the CODER station to make the red test green."""
    rubric = load_station_rubric("coder", repo_path=repo_path)
    wt_block = ""
    if ticket.worktree_path:
        wt_block = f"""
WORKTREE WORKING DIRECTORY (CRITICAL ZERO-TOUCH INVARIANT):
- Assigned Isolated Worktree: `{ticket.worktree_path}`
- YOU MUST EXECUTE ALL COMMANDS, TESTS, AND FILE EDITS STRICTLY INSIDE: `{ticket.worktree_path}`
- NEVER MODIFY FILES OR RUN BUILDS DIRECTLY IN THE PRIMARY REPO CHECKOUT.
"""
    else:
        wt_block = """
⚠️ WARNING: No isolated worktree assigned!
Before mutating production code, ensure an isolated worktree is leased to preserve zero-touch primary isolation.
"""

    prompt = f"""You are the CODER station worker in Edge Brigade on branch `{ticket.branch_name}`.
{wt_block}
MISSION:
Implement the minimal, robust production code to turn all RED tests GREEN for ticket `{ticket.ticket_id}`.

CONSTRAINTS (STRICT):
1. Zero-Touch Primary Invariant: If a worktree is assigned, edit files strictly inside `{ticket.worktree_path}`.
2. Test Immutability: You MUST NEVER modify, weaken, or delete the test files written by the Seam Architect.
3. Clean Implementation: Write production code in `src/` conforming strictly to the declared seam interfaces.
4. Hermetic Verification: Run `{red_test_cmd}`. Passes with EXIT CODE 0.
5. Zero Leakage: Follow `coding_standards.md` (no raw leaks, explicit error handling, transaction safety).
6. Output: Report the test passing output and git diff summary.

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket)


def build_coder_polish_prompt(ticket: Ticket, findings: List[ReviewFinding], repo_path: Optional[Path] = None) -> str:
    """Constructs polish remediation instructions for the CODER station on feature tracks."""
    rubric = load_station_rubric("coder", repo_path=repo_path)
    findings_text = "\n".join([
        f"- [{f.axis.upper()}] ({f.severity}) {f.file_path}:{f.line_number or 'N/A'}: {f.description}\n  Suggested Fix: {f.suggested_fix}"
        for f in findings
    ])

    wt_block = ""
    if ticket.worktree_path:
        wt_block = f"""
WORKTREE WORKING DIRECTORY (CRITICAL ZERO-TOUCH INVARIANT):
- Assigned Isolated Worktree: `{ticket.worktree_path}`
- YOU MUST EXECUTE ALL COMMANDS, TESTS, AND FILE EDITS STRICTLY INSIDE: `{ticket.worktree_path}`
- NEVER MODIFY FILES OR RUN BUILDS DIRECTLY IN THE PRIMARY REPO CHECKOUT.
"""
    else:
        wt_block = """
⚠️ WARNING: No isolated worktree assigned!
Before mutating production code, ensure an isolated worktree is leased to preserve zero-touch primary isolation.
"""

    prompt = f"""You are the CODER station worker in Edge Brigade on branch `{ticket.branch_name}`.
{wt_block}
MISSION:
Execute Polish Remediation on branch `{ticket.branch_name}` for feature ticket `{ticket.ticket_id}`.
Review stations identified the following findings that must be remediated:

FINDINGS TO FIX:
{findings_text}

CONSTRAINTS & INSTRUCTIONS (STRICT):
1. Zero-Touch Primary Invariant: If a worktree is assigned, edit files strictly inside `{ticket.worktree_path}`.
2. Test Immutability: You MUST NEVER modify, weaken, or delete tests authored by the Seam Architect (`tests/**` or `*.test.*`). Address review findings strictly in production code!
3. Clean Remediation: Implement each fix without regressing existing functionality or introducing code smells.
4. Hermetic Verification: Run `{ticket.test_seam_command}`. Passes with EXIT CODE 0.
5. Commit: Stage modified production files and commit:
   `git commit -am "fix({ticket.domain}): polish review findings ({ticket.ticket_id})"`
6. Output: Report the test passing output and git diff summary.

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket, extra_paths=[f.file_path for f in findings])
