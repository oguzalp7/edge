"""
Deterministic AFK prompt synthesis with embedded boundaries and verification gates.
"""

from pathlib import Path
from typing import Optional


def get_edge_gate_path() -> str:
    """Returns absolute posix path to edge plugin's gate.py."""
    gate_file = Path(__file__).resolve().parent.parent / "gate.py"
    return gate_file.as_posix()


def _format_test_instruction(test_cmd: Optional[str]) -> str:
    if test_cmd:
        return f"- Run unit tests: `{test_cmd}`"
    return "- Run existing unit tests for changed files."


def _format_mode_boundary(mode: str) -> str:
    if mode == "strict":
        return "- STRICT MODE: You cannot edit tests (tests/**) or database schemas (db/schema/**, drizzle/**)."
    return "- YOLO MODE: You may edit tests and schemas if strictly necessary for the objective."


def build_gnhf_prompt(
    objective: str,
    mode: str = "strict",
    track: str = "all",
    test_cmd: Optional[str] = None
) -> str:
    """
    Synthesizes the deterministic AFK prompt with objective on 1st line (for gnhf branch slug),
    followed by [EDGE_AFK:<mode>] header, atomic step constraints, blocker triage, and quality gate commands.
    """
    clean_obj = objective.strip()
    gate_path = get_edge_gate_path()
    test_instruction = _format_test_instruction(test_cmd)
    mode_boundary = _format_mode_boundary(mode)

    return f"""{clean_obj}
[EDGE_AFK:{mode}]

OBJECTIVE:
{clean_obj}

OPERATIONAL CONSTRAINTS (AFK Autonomous Session):
1. ATOMIC ITERATION: Take exactly ONE atomic, verifiable refactor/fix step per turn.
2. BEHAVIORAL PRESERVATION: Preserve 100% of existing external behavior. Do not alter public API contracts.
3. PHYSICAL BOUNDARIES:
   - Mode is '{mode}'.
   {mode_boundary}
   - You CANNOT invoke subagents (`invoke_subagent` is hard blocked).
   - You CANNOT edit `.edge/*.json` coordination files.
4. BLOCKER TRIAGE:
   - If blocked or stuck after 2 attempts on any file, DO NOT loop endlessly.
   - Append to `.gnhf/notes.md`: `[SKIPPED-NEEDS-HITL] <file>: <reason>` and move to the next item.
5. VERIFICATION GATE:
   - Run type checks / build checks.
   {test_instruction}
   - Run Edge Quality Gate: `python3 {gate_path} . --track {track} --skip-verify`
   - All gates must pass before committing.
"""
