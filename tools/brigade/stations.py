"""
Station Registry & Dispatcher for Edge Brigade.
Manages persistent station worker registrations (conversation_ids)
and prepares hermetic, deterministic prompt payloads for each station.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
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
    # Station Prompt Generators
    # =========================================================================

    @staticmethod
    def build_surgeon_prompt(ticket: Ticket, base_branch: str) -> str:
        """Constructs a hermetic surgery ticket for the SURGEON station."""
        is_ui = getattr(ticket, "track", "core") == "ui"
        
        if is_ui:
            neg_constraints = "\n".join([f"- {c}" for c in ticket.negative_constraints]) or (
                "- MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations.\n"
                "- Structural Cleanliness: Consolidate repetitive markup into centralized primitives without unnecessary bloat.\n"
                "- Pure Tailwind Standard: Do NOT introduce external UI component libraries (no Radix, no shadcn).\n"
                "- Zero-Wrapper Left Behind: Delete legacy shallow wrappers (e.g. `ModalDialog.tsx`) and migrate callers directly.\n"
                "- Domain Purity: No hardcoded canonical arrays or raw <th> headers in UI components."
            )
            protocol = f"""1. Git Isolation: Check out isolated branch `{ticket.branch_name}`.
2. Baseline Verification: Run `{ticket.test_seam_command}` and `npx tsc --noEmit` before changes.
3. Surgery: Follow `skills/edge-ui-refactor/SKILL.md`. Consolidate repeated raw JSX in `{ticket.target_file}` into centralized primitive in `src/components/ui/`. If an unused legacy wrapper exists (e.g. `src/components/primitives/ModalDialog.tsx`), delete it (`git rm`).
4. Hermetic Verification: Run `npx tsc --noEmit` and `npm run test:unit`. Both must pass with exit code 0.
5. Deterministic Visual Parity: If dev server running, compare screenshots via `uv run --with pillow python -m tools.ui_audit.diff_image`.
6. Gate Verification: Run `python tools/gate.py . --track ui --base {base_branch}`.
7. Commit: Stage modified files and commit with message:
   `refactor(ui): {ticket.description.lower()} ({ticket.ticket_id})`
8. Output: Report git diff summary, test output, and line count change."""
        else:
            neg_constraints = "\n".join([f"- {c}" for c in ticket.negative_constraints]) or (
                "- MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations unless explicitly allowed.\n"
                "- Leak Elimination: Zero direct `db.select`, `db.insert`, `db.update`, `db.delete` in action controller.\n"
                "- Structural Cleanliness: Extract business and query logic cleanly into domain repository/services.\n"
                f"- Scaffolding Allowance: Up to +{ticket.scaffolding_allowance} lines allowed for new domain repository.\n"
                "- Zero-Wrapper Left Behind: Do not create 1-line pass-through services."
            )
            protocol = f"""1. Git Isolation: Check out isolated branch `{ticket.branch_name}`.
2. Characterization Test: Run `{ticket.test_seam_command}` to verify test baseline before changes.
3. Surgery: Extract queries/mutations to domain repository (`src/lib/{ticket.domain}/repository.ts`). Thin `{ticket.target_file}`.
4. Hermetic Verification: Run `{ticket.test_seam_command}` and `npx tsc --noEmit`. Both must pass with exit code 0.
5. Commit: Stage modified files (`git add {ticket.target_file} src/lib/{ticket.domain}/repository.ts`) and commit with message:
   `refactor({ticket.domain}): {ticket.description.lower()} ({ticket.ticket_id})`
6. Output: Report git diff summary, test output, and line count change."""

        return f"""You are the SURGEON station worker in Edge Brigade operating in `{base_branch}`.

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
- Scaffolding Allowance: +{ticket.scaffolding_allowance} lines
- Characterization Test Seam: `{ticket.test_seam_command}`

NEGATIVE CONSTRAINTS (STRICT):
{neg_constraints}

EXECUTION PROTOCOL:
{protocol}
"""

    @staticmethod
    def build_spec_writer_prompt(ticket: Ticket, user_story: str) -> str:
        """Constructs a prompt for the SPEC_WRITER station."""
        return f"""You are the SPEC_WRITER station worker in Edge Brigade.

MISSION:
Take the raw user story / requirements and author an INVEST-compliant vertical slice specification.

INPUT USER STORY:
\"\"\"
{user_story}
\"\"\"

STATION DIRECTIVES:
1. Ubiquitous Language: Identify core domain vocabulary and clarify any ambiguous terms.
2. Plain English Summary: Condense the entire feature/epic into 3 to 4 crisp sentences.
3. N-Spec Slicing: If the story contains multiple distinct capabilities (N-spec), decompose them into sequential, vertical micro-specs (DB -> API -> UI or UI -> API -> DB).
4. Vertical Slice Invariant (Pocock/Dexter Horthy Doctrine):
   - A feature spec CANNOT leave any tier dangling. It must address data, core logic, API endpoints, and user touchpoints.
   - If UI was not mentioned by the human, DO NOT guess: flag the gap for user interview (/grill-me).
5. Visual Approval Gate (lavish-axi Direct Ownership Loop):
   - If UI is touched or visual components are introduced:
     a. Author an interactive prototype at `.lavish/<feature>.html` using the project's design system or Tailwind/DaisyUI. If the human asks for design alternatives, author multiple variants (e.g. `variant-a.html`, `variant-b.html` or tabbed switcher).
     b. Run `lavish-axi .lavish/<feature>.html` via WSL bash to spin up the local Express server and generate the active session URL.
     c. Extract the session URL from stdout (e.g. `http://127.0.0.1:4387/session/<id>`) and announce it: `🎨 Lavish Oturumu Başlatıldı: <url>`.
     d. Immediately enter the listening loop by running `lavish-axi poll .lavish/<feature>.html`.
     e. Iterative Review Loop: When the poll returns user feedback (`session_ended: false`), update `.lavish/<feature>.html` and/or the spec, call `lavish-axi poll .lavish/<feature>.html --agent-reply "Değişiklikler uygulandı, sayfayı yenileyebilirsiniz."` and continue polling.
     f. Sealing (Send & End): When the user clicks "Send & End" in the browser, the poll returns `session_ended: true`. Incorporate the final approved design into the spec and deliver the approved package to Orchestrator via `send_message`.
     g. Invariant: Never complete station execution or sign off on a spec until `session_ended: true` is confirmed by the human.

"""

    @staticmethod
    def build_researcher_prompt(ticket: Ticket, research_topic: str) -> str:
        """Constructs a prompt for the RESEARCHER station."""
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
"""

    @staticmethod
    def build_seam_architect_prompt(ticket: Ticket, spec_summary: str) -> str:
        """Constructs a prompt for the SEAM_ARCHITECT station."""
        return f"""You are the SEAM_ARCHITECT station worker in Edge Brigade.

MISSION:
Architect the Michael Feathers seams, declare interface contracts, and write RED unit/contract tests for ticket `{ticket.ticket_id}`.

SPECIFICATION:
{spec_summary}

DIRECTIVES:
1. Identify Seams: Determine clean sensing/enabling seams (interfaces, repository abstractions, DTO contracts) in `{ticket.target_file}`.
2. Declare Contracts: Define explicit TypeScript interfaces and type signatures.
3. Write RED Unit/Contract Tests (TDD Anchor):
   - Author hermetic tests in `tests/` covering the acceptance criteria.
   - Run the test suite: verify that the newly written tests FAIL cleanly (RED baseline).
   - If the tests pass before any implementation code is written, the test is invalid!
4. Hand-off: Commit the red tests and interface declarations. The Coder worker will implement the code to turn them green.
"""

    @staticmethod
    def build_coder_prompt(ticket: Ticket, red_test_cmd: str) -> str:
        """Constructs a prompt for the CODER station."""
        return f"""You are the CODER station worker in Edge Brigade on branch `{ticket.branch_name}`.

MISSION:
Implement the minimal, robust production code to turn all RED tests GREEN for ticket `{ticket.ticket_id}`.

CONSTRAINTS (STRICT):
1. Test Immutability: You MUST NEVER modify, weaken, or delete the test files written by the Seam Architect.
2. Clean Implementation: Write production code in `src/` conforming strictly to the declared seam interfaces.
3. Hermetic Verification: Run `{red_test_cmd}` and `npx tsc --noEmit`. Both must pass with EXIT CODE 0.
4. Zero Leakage: Follow `coding_standards.md` (no raw leaks, explicit error handling, transaction safety).
5. Output: Report the test passing output and git diff summary.
"""

    @staticmethod
    def build_standards_review_prompt(ticket: Ticket, base_branch: str) -> str:
        """Constructs a standards review ticket for the STANDARDS_EXAMINER station."""
        return f"""You are the STANDARDS_EXAMINER station worker in Edge Brigade.

DIFF INSPECTION:
Target Diff: `git diff {base_branch}..HEAD`

STANDARDS SOURCES:
1. `coding_standards.md` in repository root.
2. Fowler Code Smell Baseline (Mysterious Name, Duplicated Code, Feature Envy, Data Clumps, Primitive Obsession, Message Chains, Middle Man).

TICKET CONTEXT:
- Refactoring Ticket: {ticket.ticket_id}
- Domain: {ticket.domain}
- Target File: {ticket.target_file}

REVIEW DIRECTIVE:
1. Verify if the diff complies with `coding_standards.md` (e.g. Â§4.3 no index signature tampering, explicit types, transaction safety).
2. Spot baseline smells in the diff.
3. Distinguish HARD VIOLATIONS from judgement calls. Skip anything automated tooling enforces.
4. Keep the report concise (under 300 words). If clean, state: 'STANDARDS REVIEW: PASS'.
"""

    @staticmethod
    def build_spec_review_prompt(ticket: Ticket, base_branch: str) -> str:
        """Constructs an architectural spec review ticket for the SPEC_EXAMINER station."""
        return f"""You are the SPEC_EXAMINER station worker in Edge Brigade.

DIFF INSPECTION:
Target Diff: `git diff {base_branch}..HEAD`

SPEC SOURCE:
`skills/edge-core-refactor/SKILL.md` (or `edge-ui-refactor/SKILL.md`)

TICKET CONTEXT:
- Refactoring Ticket: {ticket.ticket_id}
- Domain: {ticket.domain}
- Target File: {ticket.target_file}

ARCHITECTURAL INVARIANTS TO AUDIT:
1. MigrationGate Invariant: Did the diff touch any file in `src/db/schema/*` or `drizzle/*`? (Immediate failure).
2. Database Leak Elimination: Did any `db.select`, `db.insert`, `db.update`, `db.delete` remain in action controller?
3. Target File Contraction: Did `{ticket.target_file}` contract?
4. Zero-Wrapper: Are there useless pass-through services?
5. Scope Creep: Did the diff touch anything outside the ticket domain?

REVIEW DIRECTIVE:
Report missing requirements, scope creep, or invalid implementations.
Keep the report concise (under 300 words). If clean, state: 'SPEC REVIEW: PASS'.
"""

    @staticmethod
    def build_polish_prompt(ticket: Ticket, findings: List[ReviewFinding]) -> str:
        """Constructs remediation instructions for the SURGEON station."""
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
1. Address each finding strictly without violating MigrationGate or Target Contraction.
2. Run `{ticket.test_seam_command}` and `npx tsc --noEmit` to verify hermetic cleanliness.
3. Commit the changes:
   `git commit -am "refactor({ticket.domain}): polish review findings ({ticket.ticket_id})"`
4. Report the resulting git diff and test verification output.
"""

    @staticmethod
    def build_expediter_prompt(ticket: Ticket, base_branch: str) -> str:
        """Constructs delivery instructions for the EXPEDITER station."""
        return f"""You are the EXPEDITER station worker in Edge Brigade.

MISSION:
Finalize and deliver ticket `{ticket.ticket_id}` (`{ticket.branch_name}`) to `{base_branch}`.

EXECUTION PROTOCOL:
1. Checkout `{base_branch}`.
2. Squash-merge `{ticket.branch_name}`:
   `git merge --squash {ticket.branch_name}`
   `git commit -m "refactor({ticket.domain}): resolve {ticket.rule_id} in {ticket.target_file} ({ticket.ticket_id})"`
3. Refresh radar debt ledger:
   `python tools/radar/cli.py scan .`
4. Confirm monotonic health score improvement and that `{ticket.fingerprint}` is RESOLVED.
5. Delete temporary refactor branch:
   `git branch -D {ticket.branch_name}`
6. If PR creation requested, hand off to `no-mistakes` or open PR.
"""

    @staticmethod
    def build_qa_prompt(user_scenario_en: str, target_route: str = "http://localhost:3000", assertions: List[str] = None, scenario_slug: str = "qa_scenario") -> str:
        """Constructs an E2E Browser & Visual QA ticket for the QA_ENGINEER (Sommelier) station."""
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
\"\"\"
{user_scenario_en}
\"\"\"

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
"""


