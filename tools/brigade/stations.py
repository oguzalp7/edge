"""
Station Registry & Dispatcher for Edge Brigade.
Manages persistent station worker registrations (conversation_ids)
and prepares hermetic, deterministic prompt payloads for each station.
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Tuple
from datetime import datetime, timezone

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from .models import Station, StationRole, Ticket, ReviewFinding, BrigadeState
    from .navigation import build_navigation_context
except ImportError:
    from tools.brigade.models import Station, StationRole, Ticket, ReviewFinding, BrigadeState
    from tools.brigade.navigation import build_navigation_context


def _resolve_target_label(ticket: Ticket) -> str:
    if ticket.target_file:
        return ticket.target_file
    if getattr(ticket, "expected_files", None):
        return ", ".join(ticket.expected_files)
    return "(dynamic-slice)"


def _resolve_stage_target(ticket: Ticket) -> str:
    if ticket.target_file:
        return ticket.target_file
    if getattr(ticket, "expected_files", None):
        return " ".join(ticket.expected_files)
    return "-u"


class StationRegistry:
    def __init__(self, state: BrigadeState):
        self.state = state

    @property
    def stations(self) -> Dict[str, Station]:
        return self.state.stations

    @staticmethod
    def format_kitchen_roster(stations: Dict[str, Station]) -> str:
        """Renders a clean Markdown block listing registered stations and P2P handoff rules."""
        if not stations:
            return (
                "### 📋 ACTIVE KITCHEN ROSTER\n"
                "No persistent station workers currently registered.\n"
                "Register stations with: brigade register <repo> --role <role> --conversation-id <id>\n"
            )
        return StationRegistry._render_roster_table(stations)

    @staticmethod
    def _render_roster_table(stations: Dict[str, Station]) -> str:
        lines = [
            "### 📋 ACTIVE KITCHEN ROSTER",
            "| Role | Station Name | Conversation ID | Model | Status |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]
        for role_slug, st in sorted(stations.items()):
            lines.append(StationRegistry._format_roster_row(st))
        lines.extend([
            "",
            "🤝 **PEER-TO-PEER HANDOFF RULES (Autonomous Kitchen Relay):**",
            "- `seam_architect` -> `coder`: Red tests passing -> advance to `SURGERY`, message `coder` directly.",
            "- `coder`/`surgeon` -> `gate`: Verify passing -> advance to `GATE` (runs `tools/gate.py` & UI `diff_image.py`).",
            "- `gate` -> `qa_engineer` (if QA needed) or `examiner` (`REVIEW`).",
            "- `qa_engineer` -> `examiner`: Proof receipt verified -> advance to `REVIEW`, message `examiner` directly.",
            "- `examiner` -> `coder`/`surgeon` (`POLISH`) or `@orchestrator` (`STAGING` after `brigade seal-review`).",
            "- **Green-Zone Invariant:** Message `@orchestrator` ONLY upon reaching `STAGING` (`[READY_FOR_STAGING]`) or unresolvable `[ESCALATION]`!",
        ])
        return "\n".join(lines)

    @staticmethod
    def _format_roster_row(st: Station) -> str:
        name = st.name if st.name else f"{st.role.replace('_', ' ').title()} Station"
        cid = f"`{st.conversation_id}`" if st.conversation_id else "*none*"
        model = getattr(st, "model", None) or "flash"
        status = getattr(st, "status", None) or "IDLE"
        return f"| `{st.role}` | {name} | {cid} | `{model}` | {status} |"

    def register(
        self,
        role: StationRole,
        conversation_id: str,
        name: Optional[str] = None,
        model: str = "flash",
    ) -> Station:
        station_name = name or f"{role.value.replace('_', ' ').title()} Station"
        station = Station(
            role=role.value,
            conversation_id=conversation_id,
            name=station_name,
            status="IDLE",
            model=model or "flash",
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
    def _collect_nav_paths(ticket: Ticket, extra_paths: Optional[List[str]] = None) -> List[str]:
        raw_paths: List[str] = []
        candidates = [
            ticket.target_file,
            *(getattr(ticket, "expected_files", None) or []),
            *(extra_paths or []),
        ]
        for p in candidates:
            if p and p not in raw_paths:
                raw_paths.append(p)
        return raw_paths

    @staticmethod
    def _inject_nav_block(prompt: str, nav: str) -> str:
        if "\n---\n\n# " in prompt:
            head, tail = prompt.rsplit("\n---\n\n# ", 1)
            return f"{head}\n\n{nav}\n\n---\n\n# {tail}"
        if "\n---\n\n" in prompt:
            head, tail = prompt.rsplit("\n---\n\n", 1)
            return f"{head}\n\n{nav}\n\n---\n\n{tail}"
        return f"{prompt.rstrip()}\n\n{nav}\n"

    @staticmethod
    def _with_navigation_context(
        prompt: str,
        repo_path: Optional[Path],
        ticket: Ticket,
        extra_paths: Optional[List[str]] = None,
    ) -> str:
        """Injects deterministic navigation context before the trailing rubric separator."""
        raw_paths = StationRegistry._collect_nav_paths(ticket, extra_paths)
        nav = build_navigation_context(
            repo_path,
            target_paths=raw_paths,
            domain=ticket.domain or "",
            spec_path=getattr(ticket, "spec_path", None) or "",
        )
        if not nav:
            return prompt
        return StationRegistry._inject_nav_block(prompt, nav)

    @staticmethod
    def build_surgeon_prompt(ticket: Ticket, base_branch: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a hermetic surgery ticket for the SURGEON station."""
        is_ui = getattr(ticket, "track", "core") == "ui"
        rubric = StationRegistry.load_station_rubric("surgeon", repo_path=repo_path)
        target_label = _resolve_target_label(ticket)
        stage_target = _resolve_stage_target(ticket)

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
3. Surgery: Follow `skills/edge-ui-refactor/SKILL.md`. Consolidate repeated raw JSX in `{target_label}` into centralized primitives per `coding_standards.md`. If an unused legacy shallow wrapper exists, delete it (`git rm`).
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
3. Surgery: Extract queries/mutations to domain repository (`src/lib/{ticket.domain}/repository.ts`). Thin `{target_label}`.
4. Hermetic Verification: Run `{ticket.test_seam_command}`. Passes with exit code 0.
5. Gate Verification: Run `python tools/gate.py . --track core --base {base_branch}`.
6. Commit: Stage modified files (`git add {stage_target} src/lib/{ticket.domain}/repository.ts`) and commit with message:
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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket)

    @staticmethod
    def build_spec_writer_prompt(ticket: Ticket, user_story: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the SPEC_WRITER station."""
        rubric = StationRegistry.load_station_rubric("spec-writer", repo_path=repo_path)
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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket)

    @staticmethod
    def build_researcher_prompt(ticket: Ticket, research_topic: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the RESEARCHER station."""
        rubric = StationRegistry.load_station_rubric("researcher", repo_path=repo_path)
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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket)

    @staticmethod
    def build_seam_architect_prompt(ticket: Ticket, spec_summary: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a prompt for the SEAM_ARCHITECT station."""
        rubric = StationRegistry.load_station_rubric("seam-architect", repo_path=repo_path)
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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket)

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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket)

    @staticmethod
    def build_examiner_prompt(ticket: Ticket, base_branch: str, repo_path: Optional[Path] = None) -> str:
        """Constructs a unified 3-axis evidence-first review ticket for the EXAMINER station."""
        rubric = StationRegistry.load_station_rubric("examiner", repo_path=repo_path)
        target_label = _resolve_target_label(ticket)
        expected_line = (
            f"\n- Expected Files: {', '.join(ticket.expected_files)}"
            if getattr(ticket, "expected_files", None)
            else ""
        )
        slug = StationRegistry._resolve_qa_slug("qa_scenario", ticket)
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

3-AXIS EVIDENCE-FIRST REVIEW DIRECTIVES:
Axis 1 (Standards & Fowler Smells -- `--axis standards`):
1. Verify if the diff complies with `coding_standards.md` (explicit types, transaction safety, error boundaries, zero raw leaks).
2. Spot Fowler code smells in the diff and distinguish HARD VIOLATIONS from advisory guidance.

Axis 2 (Architectural & Spec Boundaries -- `--axis spec`):
1. MigrationGate Invariant: On refactor tracks, ensure `src/db/schema/*` and `drizzle/*` are untouched.
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
If clean, state: 'EXAMINER REVIEW: PASS' and seal `--verdict PASS`.

---

{rubric}
"""
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket)

    @staticmethod
    def build_polish_prompt(ticket: Ticket, findings: List[ReviewFinding], repo_path: Optional[Path] = None) -> str:
        """Constructs remediation instructions for the SURGEON station."""
        rubric = StationRegistry.load_station_rubric("surgeon", repo_path=repo_path)
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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket, extra_paths=[f.file_path for f in findings])

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
        return StationRegistry._with_navigation_context(prompt, repo_path, ticket, extra_paths=[f.file_path for f in findings])

    @staticmethod
    def _resolve_qa_scenario(user_scenario_en: str, ticket: Optional[Ticket]) -> str:
        if user_scenario_en:
            return user_scenario_en
        if ticket and ticket.description:
            return ticket.description
        return "E2E UI & user flow verification"

    @staticmethod
    def _resolve_qa_lavish(lavish_path: Optional[str], ticket: Optional[Ticket]) -> Optional[str]:
        if lavish_path:
            return lavish_path
        if ticket:
            return getattr(ticket, "lavish_path", None)
        return None

    @staticmethod
    def _clean_slug(val: Optional[str]) -> str:
        return (val or "").strip().lower().replace("_", "-")

    @staticmethod
    def _strip_branch_prefix(branch: str) -> str:
        s = branch.strip()
        for prefix in ("feat/", "refactor/", "hotfix/", "chore/"):
            if s.startswith(prefix):
                return s[len(prefix):]
        return s

    @staticmethod
    def _resolve_ticket_slug(ticket: Ticket) -> Optional[str]:
        if (ticket.domain or "").strip():
            return StationRegistry._clean_slug(ticket.domain)
        if (ticket.branch_name or "").strip():
            stripped = StationRegistry._strip_branch_prefix(ticket.branch_name)
            return StationRegistry._clean_slug(stripped)
        if (ticket.ticket_id or "").strip():
            return StationRegistry._clean_slug(ticket.ticket_id)
        return None

    @staticmethod
    def _resolve_qa_slug(
        scenario_slug: str = "qa_scenario",
        ticket: Optional[Ticket] = None,
    ) -> str:
        """
        Deterministically resolves the scenario slug used for proof receipt lookup.
        Priority:
        1. Explicit scenario_slug if not default 'qa_scenario'
        2. ticket.domain (lowercased, '_' replaced with '-')
        3. ticket.branch_name (prefixes stripped, lowercased, '_' replaced with '-')
        4. ticket.ticket_id (lowercased, '_' replaced with '-')
        5. Fallback: 'qa_scenario'
        """
        clean_scenario = StationRegistry._clean_slug(scenario_slug)
        if clean_scenario and clean_scenario != "qa-scenario":
            return clean_scenario
        if ticket:
            tslug = StationRegistry._resolve_ticket_slug(ticket)
            if tslug:
                return tslug
        return "qa_scenario" 

    @staticmethod
    def _resolve_qa_prompt_params(
        user_scenario_en: str,
        ticket: Optional[Ticket],
        lavish_path: Optional[str],
        scenario_slug: str,
    ) -> Tuple[str, Optional[str], str]:
        """Resolves scenario text, lavish prototype path, and scenario slug for QA prompt."""
        scenario = StationRegistry._resolve_qa_scenario(user_scenario_en, ticket)
        lavish = StationRegistry._resolve_qa_lavish(lavish_path, ticket)
        slug = StationRegistry._resolve_qa_slug(scenario_slug, ticket)
        return scenario, lavish, slug

    @staticmethod
    def _build_qa_lavish_section(eff_lavish: Optional[str]) -> str:
        if not eff_lavish:
            return ""
        return f"""
LAVISH-TO-REALITY PARITY & TIER-1 CONSOLE/SMOKE GATE:
- Approved Lavish Prototype: {eff_lavish}
- Inspect {eff_lavish} prior to launching browser verification.
- Verify that every interactive control, state, button, and layout from the Lavish prototype exists in the live DOM.
- TIER-1 CONSOLE/SMOKE GATE: Zero tolerance for unhandled exceptions, console.error messages, React hydration failures, or unexpected 4xx/5xx network responses. Any occurrence fails the QA gate (CRITICAL).
"""

    @staticmethod
    def _build_qa_assertions(assertions: Optional[List[str]], eff_lavish: Optional[str]) -> str:
        if assertions:
            return "\n".join(f"- {a}" for a in assertions)

        items = [
            "Target flow completes with expected UI transitions.",
            "Zero unhandled exceptions or console errors in devtools (Tier-1 Zero Tolerance).",
            "Network requests return status 200/expected HTTP responses.",
            "Visual state matches design expectations (screenshot captured).",
        ]
        if eff_lavish:
            items.insert(0, f"Full structural and visual parity verified against {eff_lavish}.")
        return "\n".join(f"- {a}" for a in items)

    @staticmethod
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
        rubric = StationRegistry.load_station_rubric("qa-engineer", repo_path=repo_path)
        q3 = chr(34) * 3

        eff_scenario, eff_lavish, eff_slug = StationRegistry._resolve_qa_prompt_params(
            user_scenario_en, ticket, lavish_path, scenario_slug
        )
        lavish_section = StationRegistry._build_qa_lavish_section(eff_lavish)
        assertions_str = StationRegistry._build_qa_assertions(assertions, eff_lavish)

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

EXECUTION PROTOCOL: 4-STEP BEHAVIORAL PROOF CHAIN:
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
   - If critical bugs exist, record a CRITICAL review finding (`--axis qa`) to automatically route to `POLISH`.

NEGATIVE BOUNDARY (STRICT):
- You CANNOT edit or mutate production code (`src/**`, `app/**`, `lib/**`, `db/**`).

---

{rubric}
"""
