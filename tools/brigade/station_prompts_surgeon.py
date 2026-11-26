"""Surgeon station prompt builder."""

from pathlib import Path
from typing import Optional

from tools.brigade.models import Ticket
from tools.brigade.navigation import resolve_migration_paths
from tools.brigade.station_dispatch import _resolve_stage_target, _resolve_target_label
from tools.brigade.station_rubric import _with_navigation_context, load_station_rubric


def _surgeon_track_details(ticket: Ticket, base_branch: str, target_label: str, stage_target: str, repo_path: Optional[Path]) -> tuple[str, str]:
    if getattr(ticket, "track", "core") == "ui":
        neg = "\n".join([f"- {c}" for c in ticket.negative_constraints]) or (
            "- MigrationGate Invariant: NEVER touch database schema or migration files.\n"
            "- Max CC Non-Regression: Modified/extracted functions must not regress max cyclomatic complexity (healthy ceiling CC <= 10 for clean/new files).\n"
            "- Project Design System Standard: Use centralized UI primitives or vanilla classes per `coding_standards.md`.\n"
            "- Zero-Wrapper Left Behind: Delete legacy shallow wrappers and migrate callers directly.\n"
            "- Domain Purity: No hardcoded canonical arrays or raw <th> headers in UI components."
        )
        proto = f"""1. Git Isolation: Check out isolated branch `{ticket.branch_name}`.
2. Baseline Verification: Run `{ticket.test_seam_command}` before changes.
3. Surgery: Follow `skills/edge-ui-refactor/SKILL.md`. Consolidate repeated raw JSX in `{target_label}` into centralized primitives per `coding_standards.md`. If an unused legacy shallow wrapper exists, delete it (`git rm`).
4. Hermetic Verification: Run project tests and compiler. Both must pass with exit code 0.
5. Deterministic Visual Parity: If dev server running, compare screenshots via visual audit tools.
6. Gate Verification: Run `python tools/gate.py . --track ui --base {base_branch}`.
7. Commit: Stage modified files and commit with message:
   `refactor(ui): {ticket.description.lower()} ({ticket.ticket_id})`
8. Output: Report git diff summary, test output, and gate verification status."""
        return neg, proto
    schema_glob, migration_glob = resolve_migration_paths(repo_path)
    neg = "\n".join([f"- {c}" for c in ticket.negative_constraints]) or (
        f"- MigrationGate Invariant: NEVER touch `{schema_glob}` or `{migration_glob}` migrations unless explicitly allowed.\n"
        "- Layer Leakage Gate: Action controllers must not introduce direct DB calls (`after_leaks <= before_leaks`, 0 leaks in new actions).\n"
        "- Max CC Non-Regression: Modified/extracted functions must not regress max cyclomatic complexity (healthy ceiling CC <= 10 for clean/new files).\n"
        "- Structural Cleanliness: Extract business and query logic cleanly into domain repository/services.\n"
        "- Zero-Wrapper Left Behind: Do not create 1-line pass-through services."
    )
    proto = f"""1. Git Isolation: Check out isolated branch `{ticket.branch_name}`.
2. Characterization Test: Run `{ticket.test_seam_command}` to verify test baseline before changes.
3. Surgery: Extract queries/mutations to domain repository (`src/lib/{ticket.domain}/repository.ts`). Thin `{target_label}`.
4. Hermetic Verification: Run `{ticket.test_seam_command}`. Passes with exit code 0.
5. Gate Verification: Run `python tools/gate.py . --track core --base {base_branch}`.
6. Commit: Stage modified files (`git add {stage_target} src/lib/{ticket.domain}/repository.ts`) and commit with message:
   `refactor({ticket.domain}): {ticket.description.lower()} ({ticket.ticket_id})`
7. Output: Report git diff summary, test output, and gate verification status."""
    return neg, proto


def _surgeon_worktree_block(ticket: Ticket) -> str:
    if ticket.worktree_path:
        return f"""
WORKTREE WORKING DIRECTORY (CRITICAL ZERO-TOUCH INVARIANT):
- Assigned Treehouse Worktree: `{ticket.worktree_path}`
- YOU MUST EXECUTE ALL COMMANDS, TESTS, AND FILE EDITS STRICTLY INSIDE: `{ticket.worktree_path}`
- NEVER MODIFY FILES OR RUN BUILDS DIRECTLY IN THE PRIMARY REPO CHECKOUT.
"""
    return """
⚠️ WARNING: No isolated worktree assigned!
Before mutating production code, ensure a Treehouse worktree is leased to preserve zero-touch primary isolation.
"""


def build_surgeon_prompt(ticket: Ticket, base_branch: str, repo_path: Optional[Path] = None) -> str:
    """Constructs a hermetic surgery ticket for the SURGEON station."""
    rubric = load_station_rubric("surgeon", repo_path=repo_path)
    target_label = _resolve_target_label(ticket)
    neg_constraints, protocol = _surgeon_track_details(ticket, base_branch, target_label, _resolve_stage_target(ticket), repo_path)
    wt_block = _surgeon_worktree_block(ticket)
    prompt = f"""You are the SURGEON station worker in Edge Brigade operating in `{base_branch}`.
{wt_block}
MISSION:
Execute the bounded refactor ticket `{ticket.ticket_id}` targeting `{ticket.rule_id}` in '{target_label}' (line {ticket.line_number}).

TICKET SPECIFICATION:
- Ticket ID: {ticket.ticket_id}
- Track: {getattr(ticket, 'track', 'core')}
- Domain: {ticket.domain}
- Target File: {target_label}
- Target Symbol: {ticket.target_symbol or 'N/A'}
- Severity: {ticket.severity}
- Description: {ticket.description}
- Suggested Fix: {ticket.suggested_fix}
- Branch Name: {ticket.branch_name}
- Worktree Path: {ticket.worktree_path or 'Primary'}
- Characterization Test Seam: `{ticket.test_seam_command}`

NEGATIVE CONSTRAINTS (STRICT):
{neg_constraints}

EXECUTION PROTOCOL:
{protocol}

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket)
