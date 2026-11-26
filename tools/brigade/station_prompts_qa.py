"""QA engineer (Sommelier) browser prompt builder."""

from pathlib import Path
from typing import List, Optional

from tools.brigade.models import Ticket
from tools.brigade.station_qa_params import _build_qa_assertions, _build_qa_lavish_section, _resolve_qa_prompt_params
from tools.brigade.station_rubric import load_station_rubric


def _qa_protocol_section(target_route: str, eff_slug: str, eff_lavish: Optional[str]) -> str:
    return f"""EXECUTION PROTOCOL: 4-STEP BEHAVIORAL PROOF CHAIN:
1. Step 1: Reference Ingestion & Stage Preparation:
   - If an approved Lavish prototype exists ({eff_lavish or "none"}), copy it to:
     `<Artifact Directory>/browser_sandbox/references/{eff_slug}.html`
   - If scenario mutates data, query baseline database/API state via WSL shell (`run_command`).

2. Step 2: Browser Subagent Delegation:
   - Delegate physical browser interactions to the built-in browser subagent:
     `invoke_subagent(TypeName="browser", Model="flash", Role="Browser Automation Subagent", Prompt="...")`
   - Instruct it to navigate to {target_route}, read the staged Lavish reference, execute actions, and capture screenshots.
   - On completion, cross-verify visited URLs and screenshot paths against host-injected `BROWSER_HOST_FACTS`.

3. Step 3: State Persistence & Reload Verification:
   - Message the browser subagent (`send_message`) to perform a physical page reload (`page.reload`).
   - Confirm that user state persists in the DOM post-reload.
   - Run WSL shell command (`run_command`) to verify persistent database records (DB Cross-Check).
   - Both DOM reload and DB check MUST pass for `persistence_verified: true`.

4. Step 4: Proof Receipt Synthesis & Relay:
   - If non-blocking UX/visual defects are found, log them via:
     `python tools/brigade/cli.py qa-inspect "<query>" . --issue "<desc>" --category <category> --frontier`
   - Write `.edge/qa/proofs/{eff_slug}.json` adhering to ProofVerifier schema:
     `visited_urls`, `user_actions_executed`, `persistence_verified: true`, `console_clean: true`, `screenshot_paths`, `host_facts_verified: true`, `db_crosscheck: {{...}}`.
   - Run `python tools/brigade/cli.py advance .` to transition to `REVIEW` (`EXAMINER`).
   - If critical bugs exist, record a CRITICAL review finding (`--axis qa`) to automatically route to `POLISH`."""


def build_qa_prompt(
    user_scenario_en: str = "",
    target_route: str = "http://localhost:3000",
    assertions: Optional[List[str]] = None,
    scenario_slug: str = "qa_scenario",
    repo_path: Optional[Path] = None,
    ticket: Optional[Ticket] = None,
    lavish_path: Optional[str] = None,
) -> str:
    """Constructs an E2E Browser & Visual QA ticket for the QA_ENGINEER (Sommelier) station."""
    rubric = load_station_rubric("qa-engineer", repo_path=repo_path)
    q3 = chr(34) * 3
    eff_scenario, eff_lavish, eff_slug = _resolve_qa_prompt_params(user_scenario_en, ticket, lavish_path, scenario_slug)
    lavish_section = _build_qa_lavish_section(eff_lavish)
    assertions_str = _build_qa_assertions(assertions, eff_lavish)
    protocol_section = _qa_protocol_section(target_route, eff_slug, eff_lavish)
    return f"""You are the QA_ENGINEER (Sommelier) station worker in Edge Brigade.

MISSION:
Execute end-to-end browser verification and synthesize the physical Behavioral Proof Receipt for the translated user scenario.

TARGET ROUTE:
{target_route}

SCENARIO SLUG:
{eff_slug}
{lavish_section}
TRANSLATED USER SCENARIO (UBIQUITOUS DOMAIN SPEC):
{q3}
{eff_scenario}
{q3}

VERIFICATION ASSERTIONS (CRITERIA):
{assertions_str}

{protocol_section}

NEGATIVE BOUNDARY (STRICT):
- You CANNOT edit or mutate production code (`src/**`, `app/**`, `lib/**`, `db/**`).

---

{rubric}
"""
