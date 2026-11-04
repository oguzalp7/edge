"""
Station Registry & Dispatcher for Edge Brigade.
Manages persistent station worker registrations (conversation_ids)
and prepares hermetic, deterministic prompt payloads for each station.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from .models import Station, StationRole, Ticket, ReviewFinding, BrigadeState
except ImportError:
    from tools.brigade.models import Station, StationRole, Ticket, ReviewFinding, BrigadeState


class StationRegistry:
    def __init__(self, state: BrigadeState):
        self.state = state

    @property
    def stations(self) -> Dict[str, Station]:
        return self.state.stations

    def register(self, role: StationRole, conversation_id: str, name: Optional[str] = None) -> Station:
        station_name = name or f"{role.value.replace('_', ' ').title()} Station"
        station = Station(
            role=role.value,
            conversation_id=conversation_id,
            name=station_name,
            status="IDLE",
            registered_at=datetime.now(timezone.utc).isoformat(),
            last_active_at=datetime.now(timezone.utc).isoformat(),
        )
        self.state.stations[role.value] = station
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        return station

    def unregister(self, role: StationRole) -> bool:
        if role.value in self.state.stations:
            del self.state.stations[role.value]
            self.state.updated_at = datetime.now(timezone.utc).isoformat()
            return True
        return False

    def get_station(self, role: StationRole) -> Optional[Station]:
        return self.state.stations.get(role.value)

    def mark_active(self, role: StationRole) -> None:
        station = self.get_station(role)
        if station:
            station.status = "BUSY"
            station.last_active_at = datetime.now(timezone.utc).isoformat()
            self.state.updated_at = datetime.now(timezone.utc).isoformat()

    def mark_idle(self, role: StationRole) -> None:
        station = self.get_station(role)
        if station:
            station.status = "IDLE"
            station.last_active_at = datetime.now(timezone.utc).isoformat()
            self.state.updated_at = datetime.now(timezone.utc).isoformat()

    # =========================================================================
    # Station Rubric Loader (2-Layer SSOT)
    # =========================================================================

    @staticmethod
    def _read_file_candidates(dir_path: Path, filenames: List[str]) -> Optional[str]:
        for fn in filenames:
            p = dir_path / fn
            if p.is_file():
                text = p.read_text(encoding="utf-8").strip()
                if text:
                    return text
        return None

    @staticmethod
    def load_station_rubric(role_slug: Any, repo_path: Optional[Path] = None) -> str:
        """
        Loads Layer 1 rubric from agents/<role-slug>.md.
        If repo_path provided and <repo_path>/.edge/stations/<role-slug>.md exists,
        appends it under '## REPOSITORY-LOCAL STATION OVERLAY'.
        """
        raw_slug = str(role_slug.value if hasattr(role_slug, "value") else role_slug).lower().strip()
        slug = raw_slug.removeprefix("stationrole.")
        files = [slug.replace("_", "-") + ".md", slug.replace("-", "_") + ".md"]

        plugin_agents = Path(__file__).resolve().parents[2] / "agents"
        content = StationRegistry._read_file_candidates(plugin_agents, files)
        if not content:
            role_upper = slug.upper()
            content = (
                f"# Persona: {role_upper}\n\n"
                f"You are the {role_upper} station worker in Edge Brigade.\n"
                f"Adhere to coding_standards.md and your designated operational boundaries."
            )

        if repo_path:
            overlay = StationRegistry._read_file_candidates(Path(repo_path) / ".edge" / "stations", files)
            if overlay:
                content = f"{content}\n\n## REPOSITORY-LOCAL STATION OVERLAY\n{overlay}"

        return content

    # =========================================================================
    # Station Prompt Generators
    # =========================================================================

    @staticmethod
    def build_surgeon_prompt(ticket: Ticket, base_branch: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a hermetic surgery ticket for the SURGEON station."""
        is_ui = getattr(ticket, "track", "core") == "ui"
        rubric = StationRegistry.load_station_rubric("surgeon", repo_path=repo_path)

        if is_ui:
            neg_constraints = "\n".join([f"- {c}" for c in ticket.negative_constraints]) or (
                "- MigrationGate Invariant: NEVER touch database schema or migration files.\n"
                "- Max CC Non-Regression: Modified/extracted functions must not regress max cyclomatic complexity (healthy ceiling CC <= 10 for clean/new files).\n"
                "- Project Design System Standard: Use centralized UI primitives or vanilla classes per `coding_standards.md`.\n"
                "- Zero-Wrapper Left Behind: Delete legacy shallow wrappers and migrate callers directly.\n"
                "- Domain Purity: No hardcoded canonical arrays or raw <th> headers in UI components."
            )
            protocol = f"""1. Git Isolation: Check out isolated branch `{ticket.branch_name}`.
2. Baseline Verification: Run `{ticket.test_seam_command}` before changes.
3. Surgery: Follow `skills/edge-ui-refactor/SKILL.md`. Consolidate repeated raw JSX in `{ticket.target_file}` into centralized primitives per `coding_standards.md`. If an unused legacy shallow wrapper exists, delete it (`git rm`).
4. Hermetic Verification: Run project tests and compiler. Both must pass with exit code 0.
5. Deterministic Visual Parity: If dev server running, compare screenshots via visual audit tools.
6. Gate Verification: Run `python tools/gate.py . --track ui --base {base_branch}`.
7. Commit: Stage modified files and commit with message:
   `refactor(ui): {ticket.description.lower()} ({ticket.ticket_id})`
8. Output: Report git diff summary, test output, and gate verification status."""
        else:
            neg_constraints = "\n".join([f"- {c}" for c in ticket.negative_constraints]) or (
                "- MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations unless explicitly allowed.\n"
                "- Layer Leakage Gate: Action controllers must not introduce direct DB calls (`after_leaks <= before_leaks`, 0 leaks in new actions).\n"
                "- Max CC Non-Regression: Modified/extracted functions must not regress max cyclomatic complexity (healthy ceiling CC <= 10 for clean/new files).\n"
                "- Structural Cleanliness: Extract business and query logic cleanly into domain repository/services.\n"
                "- Zero-Wrapper Left Behind: Do not create 1-line pass-through services."
            )
            protocol = f"""1. Git Isolation: Check out isolated branch `{ticket.branch_name}`.
2. Characterization Test: Run `{ticket.test_seam_command}` to verify test baseline before changes.
3. Surgery: Extract queries/mutations to domain repository (`src/lib/{ticket.domain}/repository.ts`). Thin `{ticket.target_file}`.
4. Hermetic Verification: Run `{ticket.test_seam_command}`. Passes with exit code 0.
5. Gate Verification: Run `python tools/gate.py . --track core --base {base_branch}`.
6. Commit: Stage modified files (`git add {ticket.target_file} src/lib/{ticket.domain}/repository.ts`) and commit with message:
   `refactor({ticket.domain}): {ticket.description.lower()} ({ticket.ticket_id})`
7. Output: Report git diff summary, test output, and gate verification status."""

        wt_block = ""
        if ticket.worktree_path:
            wt_block = f"""
WORKTREE WORKING DIRECTORY (CRITICAL ZERO-TOUCH INVARIANT):
- Assigned Treehouse Worktree: `{ticket.worktree_path}`
- YOU MUST EXECUTE ALL COMMANDS, TESTS, AND FILE EDITS STRICTLY INSIDE: `{ticket.worktree_path}`
- NEVER MODIFY FILES OR RUN BUILDS DIRECTLY IN THE PRIMARY REPO CHECKOUT.
"""
        else:
            wt_block = """
⚠️ WARNING: No isolated worktree assigned!
Before mutating production code, ensure a Treehouse worktree is leased to preserve zero-touch primary isolation.
"""

        return f"""You are the SURGEON station worker in Edge Brigade operating in `{base_branch}`.
{wt_block}
MISSION:
Execute the bounded refactor ticket `{ticket.ticket_id}` targeting `{ticket.rule_id}` in `{ticket.target_file}` (line {ticket.line_number}).

TICKET SPECIFICATION:
- Ticket ID: {ticket.ticket_id}
- Track: {getattr(ticket, 'track', 'core')}
- Domain: {ticket.domain}
- Target File: {ticket.target_file}
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

    @staticmethod
    def build_spec_writer_prompt(ticket: Ticket, user_story: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the SPEC_WRITER station."""
        rubric = StationRegistry.load_station_rubric("spec-writer", repo_path=repo_path)
        q3 = chr(34) * 3
        return f"""You are the SPEC_WRITER station worker in Edge Brigade.

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

    @staticmethod
    def build_researcher_prompt(ticket: Ticket, research_topic: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the RESEARCHER station."""
        rubric = StationRegistry.load_station_rubric("researcher", repo_path=repo_path)
        return f"""You are the RESEARCHER station worker in Edge Brigade.

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

    @staticmethod
    def build_seam_architect_prompt(ticket: Ticket, spec_summary: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the SEAM_ARCHITECT station."""
        rubric = StationRegistry.load_station_rubric("seam-architect", repo_path=repo_path)
        return f"""You are the SEAM_ARCHITECT station worker in Edge Brigade.

MISSION:
Architect the Michael Feathers seams, declare interface contracts, and write RED unit/contract tests for ticket `{ticket.ticket_id}`.

SPECIFICATION:
{spec_summary}

DIRECTIVES:
1. Identify Seams: Determine clean sensing/enabling seams (interfaces, repository abstractions, DTO contracts) in `{ticket.target_file}`.
2. Declare Contracts: Define explicit interfaces and type signatures.
3. Write RED Unit/Contract Tests (TDD Anchor):
   - Author hermetic tests in `tests/` covering the acceptance criteria.
   - Run the test suite: verify that the newly written tests FAIL cleanly (RED baseline).
   - If the tests pass before any implementation code is written, the test is invalid!
4. Hand-off: Commit the red tests and interface declarations. The Coder worker will implement the code to turn them green.

---

{rubric}
"""

    @staticmethod
    def build_seam_prompt(ticket: Ticket, spec_summary: str, repo_path: Optional[Path] = None) -> str:
        """Alias for build_seam_architect_prompt."""
        return StationRegistry.build_seam_architect_prompt(ticket, spec_summary, repo_path=repo_path)

    @staticmethod
    def build_coder_prompt(ticket: Ticket, red_test_cmd: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the CODER station to make the red test green."""
        rubric = StationRegistry.load_station_rubric("coder", repo_path=repo_path)
        wt_block = ""
        if ticket.worktree_path:
            wt_block = f"""
WORKTREE WORKING DIRECTORY (CRITICAL ZERO-TOUCH INVARIANT):
- Assigned Treehouse Worktree: `{ticket.worktree_path}`
- YOU MUST EXECUTE ALL COMMANDS, TESTS, AND FILE EDITS STRICTLY INSIDE: `{ticket.worktree_path}`
- NEVER MODIFY FILES OR RUN BUILDS DIRECTLY IN THE PRIMARY REPO CHECKOUT.
"""
        else:
            wt_block = """
⚠️ WARNING: No isolated worktree assigned!
Before mutating production code, ensure a Treehouse worktree is leased to preserve zero-touch primary isolation.
"""

        return f"""You are the CODER station worker in Edge Brigade on branch `{ticket.branch_name}`.
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

    @staticmethod
    def build_examiner_prompt(ticket: Ticket, base_branch: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a unified dual-axis review ticket for the EXAMINER station."""
        rubric = StationRegistry.load_station_rubric("examiner", repo_path=repo_path)
        return f"""You are the EXAMINER station worker in Edge Brigade.

DIFF INSPECTION:
Target Diff: `git diff {base_branch}..HEAD`

REVIEW SOURCES:
1. `coding_standards.md` in repository root.
2. Fowler Code Smell Baseline (Mysterious Name, Duplicated Code, Feature Envy, Data Clumps, Primitive Obsession, Message Chains, Middle Man).
3. Architectural Specification (`skills/edge-core-refactor/SKILL.md` or `edge-ui-refactor/SKILL.md`).

TICKET CONTEXT:
- Refactoring Ticket: {ticket.ticket_id}
- Domain: {ticket.domain}
- Target File: {ticket.target_file}

DUAL-AXIS REVIEW DIRECTIVES:
Axis 1 (Standards & Fowler Smells):
1. Verify if the diff complies with `coding_standards.md` (explicit types, transaction safety, error boundaries, zero raw leaks).
2. Spot Fowler code smells in the diff.
3. Distinguish HARD VIOLATIONS from advisory guidance; skip deterministic checks already enforced by gate.py or compiler.

Axis 2 (Architectural & Spec Boundaries):
1. MigrationGate Invariant: Did the diff touch any file in `src/db/schema/*` or `drizzle/*`? (Immediate failure).
2. Layer Leakage Gate: Did any direct queries increase in action controllers (`after_leaks <= before_leaks`, 0 in new actions)?
3. Max CC Non-Regression: Did modified/new files stay within cyclomatic complexity bounds (no regression above baseline hotspot CC; CC <= 10 ceiling for clean/new files)?
4. Zero-Wrapper: Are there useless pass-through services?
5. Scope Creep: Did the diff touch anything outside the ticket domain?

REPORT DISCIPLINE:
Keep findings concise (under 350 words). Categorize findings by severity (CRITICAL, WARNING, ADVISORY).
If clean, state: 'EXAMINER REVIEW: PASS'.

---

{rubric}
"""

    @staticmethod
    def build_polish_prompt(ticket: Ticket, findings: List[ReviewFinding], repo_path: Optional[Path] = None) -> str:
        """Constructs remediation instructions for the SURGEON station."""
        rubric = StationRegistry.load_station_rubric("surgeon", repo_path=repo_path)
        findings_text = "\n".join([
            f"- [{f.axis.upper()}] ({f.severity}) {f.file_path}:{f.line_number or 'N/A'}: {f.description}\n  Suggested Fix: {f.suggested_fix}"
            for f in findings
        ])

        return f"""You are the SURGEON station worker in Edge Brigade.

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

    @staticmethod
    def build_coder_polish_prompt(ticket: Ticket, findings: List[ReviewFinding], repo_path: Optional[Path] = None) -> str:
        """Constructs polish remediation instructions for the CODER station on feature tracks."""
        rubric = StationRegistry.load_station_rubric("coder", repo_path=repo_path)
        findings_text = "\n".join([
            f"- [{f.axis.upper()}] ({f.severity}) {f.file_path}:{f.line_number or 'N/A'}: {f.description}\n  Suggested Fix: {f.suggested_fix}"
            for f in findings
        ])

        wt_block = ""
        if ticket.worktree_path:
            wt_block = f"""
WORKTREE WORKING DIRECTORY (CRITICAL ZERO-TOUCH INVARIANT):
- Assigned Treehouse Worktree: `{ticket.worktree_path}`
- YOU MUST EXECUTE ALL COMMANDS, TESTS, AND FILE EDITS STRICTLY INSIDE: `{ticket.worktree_path}`
- NEVER MODIFY FILES OR RUN BUILDS DIRECTLY IN THE PRIMARY REPO CHECKOUT.
"""
        else:
            wt_block = """
⚠️ WARNING: No isolated worktree assigned!
Before mutating production code, ensure a Treehouse worktree is leased to preserve zero-touch primary isolation.
"""

        return f"""You are the CODER station worker in Edge Brigade on branch `{ticket.branch_name}`.
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

    @staticmethod
    def build_qa_prompt(
        user_scenario_en: str,
        target_route: str = "http://localhost:3000",
        assertions: Optional[List[str]] = None,
        scenario_slug: str = "qa_scenario",
        repo_path: Optional[Path] = None,
    ) -> str:
        """Constructs an E2E Browser & Visual QA ticket for the QA_ENGINEER (Sommelier) station."""
        rubric = StationRegistry.load_station_rubric("qa-engineer", repo_path=repo_path)
        q3 = chr(34) * 3
        assertions_str = "\n".join([f"- {a}" for a in (assertions or [])]) or (
            "- Target flow completes with expected UI transitions.\n"
            "- Zero unhandled exceptions or console errors in devtools.\n"
            "- Network requests return status 200/expected HTTP responses.\n"
            "- Visual state matches design expectations (screenshot captured)."
        )
        return f"""You are the QA_ENGINEER (Sommelier) station worker in Edge Brigade.

MISSION:
Execute end-to-end browser verification for the translated user scenario against the active application.

TARGET ROUTE:
{target_route}

SCENARIO SLUG:
{scenario_slug}

TRANSLATED USER SCENARIO (UBIQUITOUS DOMAIN SPEC):
{q3}
{user_scenario_en}
{q3}

VERIFICATION ASSERTIONS (CRITERIA):
{assertions_str}

EXECUTION PROTOCOL & TOOL HIERARCHY:
1. Primary Tool: `chrome-devtools-axi` (WSL /usr/local/bin/chrome-devtools-axi) or `chrome-devtools-mcp`.
2. Fast-Forward Replay (Codegen-Style Replay):
   - Check if `.edge/qa/replays/{scenario_slug}.axi.js` exists from a previous partial run.
     - If it exists: Run `chrome-devtools-axi run < .edge/qa/replays/{scenario_slug}.axi.js` to instantly fast-forward browser state to the failure seam without spending LLM tokens on re-discovering preambles!
   - As you execute new actions, continuously record the JavaScript commands into `.edge/qa/replays/{scenario_slug}.axi.js` using the standard `chrome-devtools-axi run` API:
     `await page.open("{target_route}");`
     `await page.click("<selector>");`
     `await page.fill("<selector>", "<value>");`
     `await page.wait("<selector>");`
3. Scraper-Style UX Anomaly Journaling ([e2e-journal] -> frontier-axi):
   - If you spot non-blocking visual/UX defects (text wrapping/orphan words, dark mode contrast leaks, container overflows, alignment shifts):
     - DO NOT FAIL the functional ticket for micro-glitches!
     - Use the deterministic React Fiber locator tool to pinpoint the exact React component, source file, line number, and stage into frontier-axi in one shot:
       `python tools/brigade/cli.py qa-inspect "<css_or_text_query>" <repo_path> --issue "<issue_description>" --category <contrast|overflow|layout|visual-regression|misalignment> --frontier`
     - Example:
       `python tools/brigade/cli.py qa-inspect "text:Giriş Yap" . --issue "Dark modda buton metni container dışına taşıyor" --category overflow --frontier`
     - Also append the finding to `.edge/qa/ux_defects.json`.
4. Negative Boundary (STRICT):
   - You CANNOT edit or mutate production code (`src/**`, `app/**`, `lib/**`, `db/**`).
   - If a blocking business logic bug is detected: DO NOT patch it. Document exact reproduction steps, network payload, and console log.
5. Reporting:
   - Deliver a crisp QA report: Status (PASS / FAIL / DEFECT_DETECTED), execution steps, replay script location, parked UX items, and screenshots.

---

{rubric}
"""
