"""Planning station prompt builders (spec-writer, researcher, seam-architect)."""

from pathlib import Path
from typing import Optional

from tools.brigade.models import Ticket
from tools.brigade.station_dispatch import _resolve_target_label
from tools.brigade.station_rubric import _with_navigation_context, load_station_rubric

def build_spec_writer_prompt(ticket: Ticket, user_story: str, repo_path: Optional[Path] = None) -> str:
    """Constructs a prompt for the SPEC_WRITER station."""
    rubric = load_station_rubric("spec-writer", repo_path=repo_path)
    q3 = chr(34) * 3
    prompt = f"""You are the SPEC_WRITER station worker in Edge Brigade.

MISSION:
Take the raw user story / requirements and author an INVEST-compliant vertical slice specification.

INPUT USER STORY:
{q3}
{user_story}
{q3}

STATION DIRECTIVES:
1. Ubiquitous Language: Identify core domain vocabulary and clarify any ambiguous terms.
2. Plain English Summary: Condense the entire feature/epic into 3 to 4 crisp sentences.
3. N-Spec Slicing: If the story contains multiple distinct capabilities (N-spec), decompose them into sequential, vertical micro-specs (DB -> API -> UI or UI -> API -> DB).
4. Vertical Slice Invariant (Pocock/Dexter Horthy Doctrine):
   - A feature spec CANNOT leave any tier dangling. It must address data, core logic, API endpoints, and user touchpoints.
   - If UI was not mentioned by the human, DO NOT guess: flag the gap for user interview (/grill-me).
5. Visual Approval Gate (lavish-axi Direct Ownership Loop):
   - If UI is touched or visual components are introduced:
 a. Author an interactive prototype at `.lavish/<feature>.html` using the project design system per `coding_standards.md`. If the human asks for design alternatives, author multiple variants (e.g. `variant-a.html`, `variant-b.html` or tabbed switcher).
 b. Run `lavish-axi .lavish/<feature>.html` via WSL bash to spin up the local preview server and generate the active session URL.
 c. Extract the session URL from stdout (e.g. `http://127.0.0.1:4387/session/<id>`) and announce it: `🎨 Lavish Oturumu Başlatıldı: <url>`.
 d. Immediately enter the listening loop by running `lavish-axi poll .lavish/<feature>.html`.
 e. Iterative Review Loop: When the poll returns user feedback (`session_ended: false`), update `.lavish/<feature>.html` and/or the spec, call `lavish-axi poll .lavish/<feature>.html --agent-reply "Değişiklikler uygulandı, sayfayı yenileyebilirsiniz."` and continue polling.
 f. Sealing (Send & End): When the user clicks "Send & End" in the browser, the poll returns `session_ended: true`. Incorporate the final approved design into the spec and deliver the approved package to Orchestrator via `send_message`.
 g. Invariant: Never complete station execution or sign off on a spec until `session_ended: true` is confirmed by the human.

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket)


def build_researcher_prompt(ticket: Ticket, research_topic: str, repo_path: Optional[Path] = None) -> str:
    """Constructs a prompt for the RESEARCHER station."""
    rubric = load_station_rubric("researcher", repo_path=repo_path)
    prompt = f"""You are the RESEARCHER station worker in Edge Brigade.

MISSION:
Investigate and resolve the technical ambiguity or root cause for ticket `{ticket.ticket_id}`.

RESEARCH TOPIC:
{research_topic}

DIRECTIVES:
1. Hermetic Exploration: Traverse the codebase to map call trees, affected flows, and dependencies.
2. Root Cause Analysis (RCA): Pinpoint exact file locations, function symbols, and edge-case triggers.
3. External Grounding: If 3rd-party APIs or libraries are involved, verify against authoritative documentation.
4. Output: Provide an evidence-backed summary with exact file paths, line numbers, and proposed seams. Do NOT mutate production code.

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket)


def build_seam_architect_prompt(ticket: Ticket, spec_summary: str, repo_path: Optional[Path] = None) -> str:
    """Constructs a prompt for the SEAM_ARCHITECT station."""
    rubric = load_station_rubric("seam-architect", repo_path=repo_path)
    target_label = _resolve_target_label(ticket)
    prompt = f"""You are the SEAM_ARCHITECT station worker in Edge Brigade.

MISSION:
Architect the Michael Feathers seams, declare interface contracts, and write RED unit/contract tests for ticket `{ticket.ticket_id}`.

SPECIFICATION:
{spec_summary}

DIRECTIVES:
1. Identify Seams: Determine clean sensing/enabling seams (interfaces, repository abstractions, DTO contracts) in '{target_label}'.
2. Declare Contracts: Define explicit interfaces and type signatures.
3. Write RED Unit/Contract Tests (TDD Anchor):
   - Author hermetic tests in `tests/` covering the acceptance criteria.
   - Run the test suite: verify that the newly written tests FAIL cleanly (RED baseline).
   - If the tests pass before any implementation code is written, the test is invalid!
4. Hand-off: Commit the red tests and interface declarations. The Coder worker will implement the code to turn them green.

---

{rubric}
"""
    return _with_navigation_context(prompt, repo_path, ticket)


def build_seam_prompt(ticket: Ticket, spec_summary: str, repo_path: Optional[Path] = None) -> str:
    """Alias for build_seam_architect_prompt."""
    return build_seam_architect_prompt(ticket, spec_summary, repo_path=repo_path)
