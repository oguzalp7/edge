"""Pre-invocation station prompt injection handler (stdlib-only)."""

from pathlib import Path
import sys
from typing import Dict

from tools.brigade.guard.afk_guard import is_afk_session
from tools.brigade.guard.no_mistakes import is_no_mistakes_invocation
from tools.brigade.guard.post_tool import _resolve_repo_candidate
from tools.brigade.guard.role_detection import CANONICAL_ROLES, detect_session_role


def _resolve_active_tier_for_payload(payload: dict) -> str:
    repo = _resolve_repo_candidate(payload) or Path.cwd()
    try:
        from tools.brigade.tier import get_tier_status
        tier_name = str(get_tier_status(repo).tier).strip().lower()
        return tier_name if tier_name in ("pro", "ultra") else "pro"
    except Exception:
        return "pro"


def _build_orchestrator_ephemeral_message(payload: dict) -> str:
    tier_name = _resolve_active_tier_for_payload(payload)
    common_head = (
        "- You do NOT write production source code (only Antigravity brain artifacts and `.edge/**` checkpoints are permitted).\n"
        "- UI Visual Gate (`lavish-axi`): When SPEC_WRITER produces `.lavish/*.html`, present the active session URL to the human and run `lavish-axi poll <file>` in the background (WaitMsBeforeAsync: 1000, IsDaemon: false). Await user approval before advancing to SEAM_ARCHITECT.\n"
    )
    if tier_name == "ultra":
        return (
            "🚨 [EDGE ORCHESTRATOR ENFORCED — ULTRA SWARM MODE]: You are the Sovereign Commander (Orchestrator) in the Green Zone.\n" + common_head
            + "- Canonical Brigade Stations: SPEC_WRITER, RESEARCHER, SEAM_ARCHITECT, CODER, SURGEON, EXAMINER, QA_ENGINEER, SPEC_CRITIC.\n"
            + "- Ultra Swarm-Native Station Dispatch Protocol: Use `swarm(action=\"add\", name=\"<role>\", model=\"<ssot_model>\", brief=\"...\")` "
            + "governed by `tools/brigade/station_models.json` (canonical models: default `gemini-4-hydrogen-high`, `seam_architect`: `gemini-4-hydrogen-xhigh`, "
            + "`spec_critic`: `claude-opus-5-5-high`, `qa_engineer`: `gemini-4-hydrogen-medium`, `examiner`: `fork=\"spec_writer\"`). "
            + "Always reuse existing waiting/stopped swarm stations via `post_message` and read results via `read_board`. Spawning narrator or monitor daemons is strictly forbidden."
        )
    return (
        "🚨 [EDGE ORCHESTRATOR ENFORCED]: You are the Sovereign Commander (Orchestrator) in the Green Zone.\n" + common_head
        + "- Canonical Brigade Stations: SPEC_WRITER, RESEARCHER, SEAM_ARCHITECT, CODER, SURGEON, EXAMINER, QA_ENGINEER.\n"
        + "- Anti-Graveyard Protocol: ALWAYS check existing stations with `manage_subagents(Action: 'list')`. "
        + "If an active station exists for the role, REUSE it via `send_message`. Only call `invoke_subagent` if no station exists yet.\n"
        + "- Ultra Tier Note: Runtime switch to `Ultra Swarm-Native Station Dispatch Protocol` via `python3 tools/brigade/tier.py switch ultra` (branchless)."
    )


def handle_pre_invocation(payload: dict) -> dict:
    """Inject station role reminders on pre-invocation."""
    if is_no_mistakes_invocation(payload)[0]:
        return {"injectSteps": []}
    if is_afk_session(payload)[0]:
        return {}
    facade = sys.modules.get("tools.brigade.orchestrator_guard")
    role_fn = getattr(facade, "detect_session_role", detect_session_role) if facade else detect_session_role
    role, _ = role_fn(payload)
    if role == "ORCHESTRATOR":
        return {"injectSteps": [{"ephemeralMessage": _build_orchestrator_ephemeral_message(payload)}]}
    if role == "QA_ENGINEER":
        return {"injectSteps": [{"ephemeralMessage": (
            "🚨 [BRIGADE STATION ENFORCED - QA_ENGINEER]: You are the persistent Sommelier & E2E QA Engineer in Edge Brigade.\n"
            "- Multi-Agent Delegation: Delegate all browser actions to the built-in `browser` subagent (`invoke_subagent(TypeName='browser', Model='flash')`).\n"
            "- Lavish Parity & Staging: Stage `.lavish/*.html` to `<Artifact Directory>/browser_sandbox/references/` so the browser subagent can inspect DOM parity.\n"
            "- State Persistence: Verify DOM state retention after physical page reload, and execute DB/state cross-checks via WSL shell (`run_command`).\n"
            "- Proof Receipt Gate: Write verified results to `.edge/qa/proofs/<slug>.json` before calling `brigade advance`.\n"
            "- Negative Invariant: You CANNOT edit production code (`src/**`, `app/**`). Report code defects to CODER via POLISH."
        )}]}
    if role in CANONICAL_ROLES:
        return {"injectSteps": [{"ephemeralMessage": (
            f"🚨 [BRIGADE STATION ENFORCED - {role}]: You are operating as the persistent {role} station worker.\n"
            "Operate strictly within your station boundaries. When your task package is complete, report back cleanly."
        )}]}
    return {"injectSteps": []}
