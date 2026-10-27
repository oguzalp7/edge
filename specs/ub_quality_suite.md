# 🏛️ Edge Uncle Bob Quality Suite: Deterministic AST Clone Detection, CRAP Risk Engine, Dead-Code Elimination & Alias-Aware Mutation Gate

> **Document ID:** `SPEC-EDGE-QUALITY-002`  
> **Status:** `APPROVED / AUTHORITATIVE`  
> **Author:** `SPEC_WRITER Station Worker`  
> **Target Subsystems:**
> - `tools/brigade/orchestrator_guard.py` (SSOT station sync, 45k rotation cap)
> - `tools/brigade/fsm.py` (Heat zone constants, gate skip-verify deduplication)
> - `tools/audit/dryer.py` (Tree-sitter AST clone and duplication detector)
> - `tools/audit/crapper.py` (Tree-sitter cyclomatic complexity + LCOV branch risk engine)
> - `tools/audit/dead_code.py` (Knip runner, fallback orphan scanner, eslint mechanical pre-sweep)
> - `tools/audit/cli.py` (`--track clones`, `--track dead-code`, unified `--track all`)
> - `tools/audit/adapters/typescript.py` (Tree-sitter AST function extraction upgrade)
> - `tools/radar/scanner.py` (`RULE-AST-DUPLICATE`, `RULE-HIGH-CRAP`, mechanical suppression)
> - `tools/mutator/sites.py` (Tree-sitter mutation site discovery and patching)
> - `tools/mutator/overlay.py` (Next.js `@/` alias-aware isolated worker overlay)
> - `tools/mutator/runner.py` (Differential mutation engine, scoped core runner)
> - `tools/mutator/cli.py` (Mutation gate CLI)  
> **Target Test Suites:**
> - `tests/test_brigade_guard.py`
> - `tests/test_dryer.py`
> - `tests/test_crapper.py`
> - `tests/test_dead_code.py`
> - `tests/test_mutator.py`
> - `tests/test_radar_quality_rules.py`  
> **Operating Environment:** WSL2 Ubuntu-24.04 (`/home/oguz/.treehouse/edge-10a21d/1/edge`) on branch `feat/ub-quality-suite`

---

## 📑 Table of Contents
1. [Executive Summary & Clean Code Architecture](#1-executive-summary--clean-code-architecture)
2. [Ubiquitous Language & Domain Invariants](#2-ubiquitous-language--domain-invariants)
3. [Vertical Slice F1: Guard SSOT, 45k Token Rotation Cap & Gate Verification De-duplication](#3-vertical-slice-f1-guard-ssot-45k-token-rotation-cap--gate-verification-de-duplication)
   - [3.1 Rationale & Problem Statement](#31-rationale--problem-statement)
   - [3.2 45k / 75k Context Heat Rotation Policy](#32-45k--75k-context-heat-rotation-policy)
   - [3.3 Immediate Tool Response Conversation ID Extraction](#33-immediate-tool-response-conversation-id-extraction)
   - [3.4 Workspace `.edge/brigade.json` Station Synchronization](#34-workspace-edgebrigadejson-station-synchronization)
   - [3.5 Verification De-duplication (`--skip-verify` in Gate)](#35-verification-de-duplication---skip-verify-in-gate)
4. [Vertical Slice F2: DRYER — Tree-Sitter Structural AST Clone Detector](#4-vertical-slice-f2-dryer--tree-sitter-structural-ast-clone-detector)
   - [4.1 Why Text Hashing Fails & The AST Solution](#41-why-text-hashing-fails--the-ast-solution)
   - [4.2 Language Parsing & Tree-Sitter Integration](#42-language-parsing--tree-sitter-integration)
   - [4.3 AST Normalization Algorithm (`normalize_ast`)](#43-ast-normalization-algorithm-normalize_ast)
   - [4.4 Fingerprinting & Jaccard Subtree Similarity](#44-fingerprinting--jaccard-subtree-similarity)
   - [4.5 Clone Clustering Engine](#45-clone-clustering-engine)
   - [4.6 Radar & CLI Integration Contracts](#46-radar--cli-integration-contracts)
5. [Vertical Slice F3: CRAPPER — Tree-Sitter Complexity + LCOV Branch Risk Engine](#5-vertical-slice-f3-crapper--tree-sitter-complexity--lcov-branch-risk-engine)
   - [5.1 The Change Risk Anti-Patterns (CRAP) Formula](#51-the-change-risk-anti-patterns-crap-formula)
   - [5.2 Robust LCOV Branch Coverage Parsing](#52-robust-lcov-branch-coverage-parsing)
   - [5.3 Tree-Sitter Function Extraction & Complexity (Fixing Brace-Counting Bugs)](#53-tree-sitter-function-extraction--complexity-fixing-brace-counting-bugs)
   - [5.4 TypeScript Adapter Upgrade & Seamless Fallback](#54-typescript-adapter-upgrade--seamless-fallback)
   - [5.5 Radar Integration & Fat Function Suppression](#55-radar-integration--fat-function-suppression)
6. [Vertical Slice F4: Knip Dead-Code Pre-Sweep & Mechanical Debt De-pollution](#6-vertical-slice-f4-knip-dead-code-pre-sweep--mechanical-debt-de-pollution)
   - [6.1 The "Build the Lever" Invariant](#61-the-build-the-lever-invariant)
   - [6.2 Knip JSON Execution & Graceful Fallback](#62-knip-json-execution--graceful-fallback)
   - [6.3 Zero-Token Mechanical Pre-Sweep (`eslint --fix`)](#63-zero-token-mechanical-pre-sweep-eslint---fix)
   - [6.4 Radar UI Ledger De-pollution Protocol](#64-radar-ui-ledger-de-pollution-protocol)
7. [Vertical Slice F5: MUTATOR — Alias-Aware Differential Core Mutation Gate](#7-vertical-slice-f5-mutator--alias-aware-differential-core-mutation-gate)
   - [7.1 Core Scope Boundary Guard](#71-core-scope-boundary-guard)
   - [7.2 AST Mutation Site Operators & Byte Replacement](#72-ast-mutation-site-operators--byte-replacement)
   - [7.3 The Next.js `@/` Path Alias & Vitest Config Symlink Solution](#73-the-nextjs--path-alias--vitest-config-symlink-solution)
   - [7.4 Safe Overlay Materialization & Cleanup](#74-safe-overlay-materialization--cleanup)
   - [7.5 Differential Result Caching Engine](#75-differential-result-caching-engine)
   - [7.6 Mutator CLI Contract](#76-mutator-cli-contract)
8. [Concrete Python Seam Contracts (Single Source of Truth)](#8-concrete-python-seam-contracts-single-source-of-truth)
9. [Formal Acceptance Criteria (Gherkin Scenarios)](#9-formal-acceptance-criteria-gherkin-scenarios)
10. [Comprehensive Test Plan](#10-comprehensive-test-plan)
11. [Execution Sequence for SEAM_ARCHITECT and CODER](#11-execution-sequence-for-seam_architect-and-coder)

---

## 1. Executive Summary & Clean Code Architecture

Robert C. Martin's ("Uncle Bob") Clean Code principles state:
1. **Don't Repeat Yourself (DRY):** Duplicate code is the root of all evil in software design.
2. **Small, Focused Functions:** Functions must do one thing well. High cyclomatic complexity coupled with low test coverage creates hazardous maintenance minefields.
3. **Build the Lever (Mechanical Automation):** Do not spend cognitive cycles (or costly LLM prompt tokens) on mechanical tasks that static analyzers and linters can execute deterministically in milliseconds.
4. **Tests Are the True Safety Net:** High test coverage without assertion verification is an illusion. Mutation testing verifies that tests actually fail when logic is broken.

In the Edge Brigade ecosystem, prior tools suffered from four critical operational bottlenecks:
- **Token Rotation Inflation & Verification Loops:** The cognitive heat thresholds were set too high (180k/250k tokens), allowing subagents to degrade into hallucination before rotating. Simultaneously, the state machine executed three redundant full test runs (`VERIFY`, `POLISH`, and `GATE`), frequently triggering 120-second subprocess timeouts (`exit 124`).
- **Naive Text Matching for Code Duplication:** Line-based matching failed whenever variables were renamed, comments were added, or JSX elements were wrapped in styling divs.
- **Brace-Counting Regex Bugs & Lack of Coverage Correlation:** Regex-based complexity parsing broke on strings containing `{` or `}`, truncated functions over 500 lines, and penalized well-tested complex algorithms while ignoring untested risky branches.
- **Next.js `@/` Path Alias Breakage in Mutation Sandboxes:** Naive file replacement or full directory symlinking caused Vitest to fail module resolution or leak modifications directly into the primary working tree.

This specification establishes the **Uncle Bob Quality Suite** (`ub-quality-suite`) across five vertical slices (F1–F5). Every module, dataclass, function signature, and exit code is formalized below.

---

## 2. Ubiquitous Language & Domain Invariants

| Term | Domain Definition |
| :--- | :--- |
| **Heat Zone (Rotasyon Eşiği)** | Real-time cognitive load tracking of subagents. **GREEN** (< 45,000 tokens), **YELLOW** (45,000 - 75,000 tokens), and **RED** (> 75,000 tokens). Saturated agents are retired without memory compaction. |
| **SSOT Station Registry** | Single Source of Truth for station allocations across runtime memory, Antigravity session store (`edge_active_stations.json`), and target repo state (`<repo>/.edge/brigade.json`). |
| **AST Unit (Soyut Sözdizim Birimi)** | A normalized structural unit (function, method, block, or JSX subtree) extracted via tree-sitter AST parsing. |
| **Structural Clone** | Code duplicate whose AST structures match with Jaccard similarity $\ge 0.82$, regardless of variable names, literals, or whitespace. |
| **CRAP Index (Change Risk Anti-Patterns)** | A metric measuring the maintenance risk of a function based on cyclomatic complexity and code coverage: $CRAP = CC^2 \times (1 - cov)^3 + CC$. |
| **Mechanical Debt** | Trivial, deterministic codebase smells (e.g., unused imports, missing semicolons, dead variable declarations) that must be remediated by deterministic linters (`eslint --fix`) without generating agent tickets. |
| **Materialized Overlay** | An isolated directory workspace where the mutated file and all its relative and aliased importers (`@/*`) are physically copied, while untouchable assets and `node_modules` are safely symlinked. |
| **Differential Mutation Cache** | A persistent metric ledger storing mutation test outcomes keyed by `(file_path, function_hash, site_signature)` to avoid redundant test executions on unchanged code. |

---

## 3. Vertical Slice F1: Guard SSOT, 45k Token Rotation Cap & Gate Verification De-duplication

### 3.1 Rationale & Problem Statement
1. **45k Cognitive Cap:** Empirical testing demonstrated that subagents operating past 45k tokens exhibit increased context amnesia, file path truncation, and hallucinated test fixtures. The previous thresholds (`180,000` / `250,000`) caused subagents to run too long in saturated states.
2. **Async Transcript Race Condition:** In `orchestrator_guard.py:handle_post_tool`, subagents were registered by reading `transcript.jsonl`. Because Antigravity flushes transcripts asynchronously, `handle_post_tool` frequently executed before the file was written, missing the registration and allowing duplicate subagents to spawn.
3. **Repository State Disconnect:** Station registrations stored in Antigravity's global temp directory (`edge_active_stations.json`) were not synced to the target repository's `.edge/brigade.json`, preventing offline or CLI-based brigade commands from knowing active station IDs.
4. **Triple Test Run Redundancy:** When advancing from `VERIFY` $\rightarrow$ `REVIEW` $\rightarrow$ `POLISH` $\rightarrow$ `GATE` $\rightarrow$ `STAGING`, the test suite ran in `VERIFY`, ran again in `POLISH`, and ran a 3rd time in `GATE` via `tools/gate.py`. On large suites, this caused 120-second timeouts (`exit 124`).

### 3.2 45k / 75k Context Heat Rotation Policy
Constants must be formalized as Single Source of Truth in `tools/brigade/orchestrator_guard.py` and `tools/brigade/fsm.py`:

```python
GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000
```

- In `tools/brigade/orchestrator_guard.py`:
  - `TranscriptStationScanner.calculate_subagent_heat()`:
    - If `total_tokens < GREEN_HEAT_THRESHOLD`: `"GREEN"`
    - Else if `total_tokens <= YELLOW_HEAT_THRESHOLD`: `"YELLOW"`
    - Else: `"RED"`
  - `StationSelector.evaluate_spawn_request()`:
    - Candidate is considered green if `tokens < GREEN_HEAT_THRESHOLD and heat_zone == "GREEN"`.
    - If all matching candidates have `tokens >= GREEN_HEAT_THRESHOLD` or `heat_zone in ("YELLOW", "RED")`, they are marked exhausted and rotation is permitted.
- In `tools/brigade/fsm.py`:
  - `BrigadeFSM.get_heat_zone(token_count: int) -> Tuple[ContextHeatZone, str]`:
    - If `token_count < GREEN_HEAT_THRESHOLD`: `ContextHeatZone.GREEN`
    - Else if `token_count <= YELLOW_HEAT_THRESHOLD`: `ContextHeatZone.YELLOW`
    - Else: `ContextHeatZone.RED`

### 3.3 Immediate Tool Response Conversation ID Extraction
In `tools/brigade/orchestrator_guard.py:handle_post_tool(payload: dict) -> dict`:
When `tool_name == "invoke_subagent"`, the engine MUST extract the newly created `conversationId` directly from the runtime tool response payload before attempting any disk read:
1. Inspect `payload.get("toolResponse")`, `payload.get("result")`, and `payload.get("output")`.
2. If the field is a dictionary: extract `field.get("conversationId")` or `field.get("id")`.
3. If the field is a string: execute regex `re.search(r'["\']?conversationId["\']?\s*[:=]\s*["\']([a-f0-9\-]+)["\']', text)`.
4. If a valid UUID string is obtained: register the station immediately via `register_station(created_cid, role, parent_cid)` and sync to repo `.edge/brigade.json`.
5. Only if direct payload extraction yields nothing does it fall back to reading `transcript.jsonl`.

### 3.4 Workspace `.edge/brigade.json` Station Synchronization
A new synchronization helper must be implemented in `tools/brigade/orchestrator_guard.py`:
```python
def sync_repo_brigade_station(repo_path: Path, role: str, conversation_id: str) -> bool
```
- If `repo_path / ".edge" / "brigade.json"` exists or can be created:
  - Load existing JSON safely.
  - Set `stations[role] = {"role": role, "conversation_id": conversation_id, "updated_at": <iso8601>}`.
  - Write atomically via `.tmp` rename.
- In `StationSelector.evaluate_spawn_request()`:
  - If `store.load()` returns no active worker for `canonical`, consult `repo_path / ".edge" / "brigade.json"`. If a station exists for that role and its token count is green, reuse it.

### 3.5 Verification De-duplication (`--skip-verify` in Gate)
In `tools/brigade/fsm.py:BrigadeFSM.guard_gate_to_staging()`:
Both the WSL command list and Windows subprocess command list for `gate.py` must append `"--skip-verify"`:
```python
cmd = [
    "python3",
    wsl_gate,
    wsl_target,
    "--base", base_to_compare,
    "--track", ticket.track,
    "--allow-scaffolding", str(ticket.scaffolding_allowance),
    "--skip-verify",  # Deduplicate verification already completed in VERIFY / POLISH
] + target_file_flag + no_refactor_flag
```
This guarantees that `gate.py` runs invariant static checks, git hygiene, and scaffolding allowances without triggering a redundant 120s test run.

---

## 4. Vertical Slice F2: DRYER — Tree-Sitter Structural AST Clone Detector

### 4.1 Why Text Hashing Fails & The AST Solution
Regex and line-based clone detection fail because:
- Renaming local variables (`const total = a + b` vs `const sum = x + y`) changes line hashes.
- Changing quotes, adding trailing commas, or formatting changes character hashes.
- Adding TypeScript type annotations (`(x: number) => x * 2` vs `(x) => x * 2`) changes signatures.

`DRYER` uses Tree-Sitter concrete syntax trees (CST) to construct normalized Abstract Syntax Trees (AST) that abstract away identifier names, literal values, and comments while strictly preserving structural control flow, operators, JSX element hierarchies, and call relationships.

### 4.2 Language Parsing & Tree-Sitter Integration
Located at `tools/audit/dryer.py`.
- Graceful Import Handling:
```python
try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False
```
If `TREE_SITTER_AVAILABLE` is `False`, `DryerScanner.scan_path()` returns an empty list `[]` and emits an informational warning to stderr:
`"⚠️ tree-sitter or tree-sitter-language-pack not found. Run with 'uv run --with tree-sitter --with tree-sitter-language-pack' to enable AST clone detection."`
- Supported Extensions:
  - `.ts`: `tslp.get_parser("typescript")`
  - `.tsx`: `tslp.get_parser("tsx")`
  - `.js`, `.mjs`, `.cjs`: `tslp.get_parser("javascript")`
  - `.jsx`: `tslp.get_parser("tsx")` (or `javascript`)
  - `.py`: `tslp.get_parser("python")`

### 4.3 AST Normalization Algorithm (`normalize_ast`)
Signature:
```python
def normalize_ast(node: Any, source_bytes: bytes) -> Optional[Tuple[Any, ...]]
```
Rules:
1. **Ignored Nodes (Returns `None`):** `comment`, `line_comment`, `block_comment`, `type_annotation`, `type_arguments`, `accessibility_modifier`.
2. **Preserved Value Nodes:**
   - Call expressions and method names: keep original name token bytes.
   - JSX tag names: `<CardHeader>` vs `<CardFooter>` must NOT be collapsed together; keep tag name token.
   - Operators: `+`, `-`, `*`, `/`, `&&`, `||`, `===`, `!==`, `??`, `map`, `filter`.
3. **Normalized Replacement Nodes:**
   - Identifiers in declaration or local value position: return `"$ID"`.
   - String, number, and boolean literals: return `"$LIT"`.
   - Type definitions: return `"$TYPE"`.
4. **Composite Nodes:** Recursively normalize non-ignored children into an immutable tuple: `(node.type, *(child_tuples))`.

### 4.4 Fingerprinting & Jaccard Subtree Similarity
From each normalized AST tuple, generate a set of k-shingles (sub-tree paths of depth 2 to 3) encoded as string hashes:
`fingerprints: frozenset[str]`

Given two AST units $U_A$ and $U_B$:
```python
def jaccard_similarity(fp_a: frozenset[str], fp_b: frozenset[str]) -> float:
    if not fp_a or not fp_b:
        return 0.0
    intersection = len(fp_a & fp_b)
    union = len(fp_a | fp_b)
    return round(float(intersection) / float(union), 4) if union > 0 else 0.0
```

### 4.5 Clone Clustering Engine
`class DryerScanner`:
- Configurable parameters:
  - `threshold: float = 0.82` (minimum Jaccard similarity for a clone pair)
  - `min_lines: int = 5` (ignore trivial 1-4 line one-liners)
  - `min_nodes: int = 20` (ignore tiny expression blocks)
- `scan_path(target_path: Path, scoped_files: Optional[List[str]] = None) -> List[ClonePair]`:
  - Ignores `.test.`, `.spec.`, `node_modules`, `.venv`, `.git`, `dist`, `.next`, `build`.
  - Extracts candidate AST units: top-level functions, arrow functions, class methods, and substantive JSX container blocks.
  - Avoids nesting duplicates: if a parent function is already identified as a clone, do not report its internal 5-line if-block as a separate clone pair.
  - Compares all pairs $(U_i, U_j)$ where $U_i \neq U_j$.
- `cluster_clones(pairs: List[ClonePair]) -> List[CloneCluster]`:
  - Groups pairs into connected components (equivalence clusters) using Disjoint Set Union (DSU) or breadth-first search.
  - Assigns deterministic cluster IDs: `CLONE-xxxxxx` (SHA-256 of sorted member symbols).

### 4.6 Radar & CLI Integration Contracts
1. **`tools/audit/cli.py`:**
   - Add argument `--track clones`: executes `DryerScanner().scan_path(target_path)` and formats findings via `format_clones_report(pairs, clusters, format)`.
   - Update `--track all`: run clones track when `TREE_SITTER_AVAILABLE` is True and append as Track 4/4.
2. **`tools/radar/scanner.py`:**
   - In `scan_core()` and `scan_ui()`, if `tree-sitter` is available, run `DryerScanner`.
   - For every `ClonePair`:
     - Severity: `FindingSeverity.WARNING.value` if $0.82 \le score < 0.92$; `FindingSeverity.CRITICAL.value` if $score \ge 0.92$.
     - Fingerprint: `LedgerItem.generate_fingerprint("RULE-AST-DUPLICATE", rel_path, symbol, str(round(pair.score, 2)))`.

---

## 5. Vertical Slice F3: CRAPPER — Tree-Sitter Complexity + LCOV Branch Risk Engine

### 5.1 The Change Risk Anti-Patterns (CRAP) Formula
The CRAP metric, developed by Alberto Savoia and Bob Evans, quantifies the risk of changing a method:
$$\text{CRAP}(m) = \text{CC}(m)^2 \times \left(1 - \frac{\text{cov}(m)}{100}\right)^3 + \text{CC}(m)$$
Where:
- $\text{CC}(m)$ is the Cyclomatic Complexity of method $m$.
- $\text{cov}(m)$ is the percentage of test coverage (clamped to $[0.0, 100.0]$).

```python
def compute_crap(cc: int, coverage_pct: float) -> float:
    cov_clamped = max(0.0, min(100.0, float(coverage_pct)))
    risk_factor = (1.0 - (cov_clamped / 100.0)) ** 3
    crap = (cc ** 2) * risk_factor + cc
    return round(float(crap), 2)
```

**Interpretation Thresholds:**
- $CRAP < 15.0$: **Clean / Well-Tested.** High complexity is tolerated if backed by extensive tests.
- $15.0 \le CRAP < 30.0$: **Moderate Risk.** Requires refactoring or additional companion tests.
- $CRAP \ge 30.0$: **CRITICAL CRAP SMELL.** The function is both complex and untested. Immediate refactoring or red test seam required.

### 5.2 Robust LCOV Branch Coverage Parsing
Module: `tools/audit/crapper.py`
```python
def parse_lcov(lcov_content: str) -> Dict[str, Dict[str, Any]]
```
Parses standard LCOV output:
- `SF:<path>`: Marks source file. Normalized to relative path without `./`.
- `DA:<line>,<execution_count>`: Line execution hits. Stored in `lines: Dict[int, int]`.
- `BRDA:<line>,<block>,<branch>,<taken>`: Branch execution hits. Taken is `-` (unreachable) or an integer $\ge 0$. Stored in `branches: List[Tuple[int, int]]` where tuple is `(line, taken_count)`.
- `end_of_record`: Commits record.

```python
def function_coverage_from_lcov(file_cov: Dict[str, Any], start_line: int, end_line: int) -> float
```
- If branch records exist within `[start_line, end_line]`:
  - $\text{coverage} = \frac{\text{branches taken } (> 0)}{\text{total branches in range}} \times 100.0$
- Else, falls back to line coverage within `[start_line, end_line]`:
  - $\text{coverage} = \frac{\text{lines with hits } (> 0)}{\text{instrumented lines in range}} \times 100.0$
- If file or line range has 0 instrumented lines/branches: returns `0.0`.

### 5.3 Tree-Sitter Function Extraction & Complexity (Fixing Brace-Counting Bugs)
Functions extracted via AST node queries:
- Node Types: `function_declaration`, `method_definition`, `arrow_function`, `function_expression`, `generator_function`.
- Start and End Lines: Accurately derived from `node.start_point[0] + 1` and `node.end_point[0] + 1` (1-indexed).
- **Cyclomatic Complexity:** Computed by visiting AST nodes within the function scope. Counts:
  - Branching nodes: `if_statement`, `while_statement`, `for_statement`, `for_in_statement`, `catch_clause`, `switch_case`, `ternary_expression`.
  - Binary logical operators: `&&`, `||`, `??`, `and`, `or`.
  - Optional chaining: `?.`
  - Base complexity: starts at `1`.

### 5.4 TypeScript Adapter Upgrade & Seamless Fallback
In `tools/audit/adapters/typescript.py`:
- `_find_functions(self, lines: List[str]) -> List[FunctionMetrics]`:
  - If `TREE_SITTER_AVAILABLE`: delegates function extraction to `analyze_file_crap(path, rel_path)`.
  - Converts `FunctionCrapMetric` into `FunctionMetrics(name, start_line, end_line, sloc, complexity, is_exported)`.
  - Completely eliminates the 500-line truncation limit and string-brace counting errors!
  - If `TREE_SITTER_AVAILABLE` is `False`: falls back to the original regex implementation.

### 5.5 Radar Integration & Fat Function Suppression
In `tools/radar/scanner.py:scan_core()`:
1. Discover existing LCOV report via `discover_existing_lcov(self.repo_path)`:
   - Check `coverage/lcov.info`, `.coverage/lcov.info`, `target/coverage/lcov.info`.
2. If LCOV report exists:
   - Calculate CRAP scores for all functions.
   - If $crap\_score \ge 30.0$: emit `RULE-HIGH-CRAP` (`severity=FindingSeverity.CRITICAL.value`, `suggested_fix="Break function into smaller units or write missing branch tests."`).
   - For standard `RULE-FAT-FUNCTION`: if the function has $crap\_score < 15.0$, **SUPPRESS** the finding! A 60-line function with 100% branch coverage is clean code, not an emergency.

---

## 6. Vertical Slice F4: Knip Dead-Code Pre-Sweep & Mechanical Debt De-pollution

### 6.1 The "Build the Lever" Invariant
In large codebases, linting warnings (such as unused imports or orphaned variables) frequently generate dozens of tickets. When generalist LLMs are asked to clean them up:
- The LLM consumes 5,000 to 15,000 prompt tokens per ticket.
- The LLM risks altering surrounding business logic.
- Total cycle time expands exponentially.

**Invariant:** Mechanical dead code must be removed by automated tooling with **zero LLM intervention**. The Brigade's radar ledger must remain pristine for true architectural refactoring.

### 6.2 Knip JSON Execution & Graceful Fallback
Module: `tools/audit/dead_code.py`
```python
def run_dead_code_scan(repo_root: Path, timeout_sec: int = 60) -> DeadCodeReport:
    """
    Executes 'npx --no-install knip --reporter json' if package.json exists.
    If knip is missing or fails, falls back cleanly to GraphBuilder orphan scan.
    """
```
- If `package.json` exists:
  - Run `["npx", "--no-install", "knip", "--reporter", "json"]` in `repo_root`.
  - If return code is 0 or knip reports issues: parse JSON via `parse_knip_json(raw_json)`.
  - Sets `engine="knip"`.
- If `knip` is not installed or execution fails:
  - Run internal `GraphBuilder(repo_root).build_graph()` to find orphan components.
  - Sets `engine="fallback"`.

### 6.3 Zero-Token Mechanical Pre-Sweep (`eslint --fix`)
```python
def run_mechanical_presweep(repo_root: Path) -> Tuple[int, str]:
    """
    Runs 'npx eslint --fix' on TypeScript/JavaScript source files to eliminate
    unused imports and formatting smells mechanically without consuming LLM tokens.
    """
```
- Executes `["npx", "eslint", "--fix", "src/"]` (or scoped files).
- Returns `(exit_code, stdout_or_stderr)`.

### 6.4 Radar UI Ledger De-pollution Protocol
In `tools/radar/scanner.py:scan_ui()`:
- Update signature:
```python
def scan_ui(self, file_paths: Optional[List[str]] = None, include_mechanical: bool = False) -> List[LedgerItem]:
```
- By default (`include_mechanical=False`):
  - Do NOT generate `RULE-DEAD-IMPORT` items into the ledger!
  - Unused imports are diverted to `run_mechanical_presweep()` during the `PRE_SWEEP` pipeline phase.
- CLI Integration:
  - In `tools/audit/cli.py`, add `--track dead-code` to execute `run_dead_code_scan` and print unused files, exports, and types.

---

## 7. Vertical Slice F5: MUTATOR — Alias-Aware Differential Core Mutation Gate

### 7.1 Core Scope Boundary Guard
Mutation testing executes test suites repeatedly. Running mutation tests against UI components, database seeds, or end-to-end flows is prohibitively slow and produces false timeouts.
```python
def enforce_core_scope(rel_path: str, allow_non_core: bool = False) -> bool:
    """
    Ensures mutation testing only targets pure business logic:
    src/core/, core/, or tools/.
    Raises ValueError if non-core path is provided without allow_non_core=True.
    """
    norm = rel_path.replace("\\", "/").lstrip("./")
    allowed_prefixes = ("src/core/", "core/", "tools/")
    if any(norm.startswith(p) for p in allowed_prefixes) or allow_non_core:
        return True
    raise ValueError(
        f"Mutation testing restricted to core logic ({allowed_prefixes}). "
        f"Target '{rel_path}' is outside core scope. Pass allow_non_core=True to override."
    )
```

### 7.2 AST Mutation Site Operators & Byte Replacement
Module: `tools/mutator/sites.py`
Using Tree-Sitter, find exact syntax node tokens and generate `MutationSite` records:

| Category | Original Operator | Mutant Replacement | Node Types |
| :--- | :--- | :--- | :--- |
| **Arithmetic** | `+` $\leftrightarrow$ `-` | `-` / `+` | `binary_expression` |
| **Multiplicative** | `*` $\leftrightarrow$ `/` | `/` / `*` | `binary_expression` |
| **Relational** | `>` $\leftrightarrow$ `>=` | `>=` / `>` | `binary_expression` |
| **Relational** | `<` $\leftrightarrow$ `<=` | `<=` / `<` | `binary_expression` |
| **Equality** | `===` $\leftrightarrow$ `!==` | `!==` / `===` | `binary_expression` |
| **Equality** | `==` $\leftrightarrow$ `!=` | `!=` / `==` | `binary_expression` |
| **Logical** | `&&` $\leftrightarrow$ `\|\|` | `\|\|` / `&&` | `binary_expression` |
| **Nullish** | `??` $\rightarrow$ `\|\|` | `\|\|` | `binary_expression` |
| **Boolean** | `true` $\leftrightarrow$ `false` | `false` / `true` | `true`, `false`, `boolean` |

```python
def apply_mutation(source_bytes: bytes, site: MutationSite) -> bytes:
    """Replaces exact byte range [start_byte:end_byte] with site.mutant."""
    return source_bytes[:site.start_byte] + site.mutant.encode("utf-8") + source_bytes[site.end_byte:]
```

### 7.3 The Next.js `@/` Path Alias & Vitest Config Symlink Solution
Why naive overlays fail:
- Vitest and Vite use `tsconfig.json` or `vite.config.ts` to map `@/*` to `src/*`.
- If an overlay symlinks `src/` to the real repository, writing a mutated file inside the overlay's `src/` mutates the real repo!
- If the overlay only copies `src/core/math.ts`, but `src/core/calc.ts` or `tests/calc.test.ts` imports `@/core/math`, Vite attempts to resolve through `tsconfig.json`. If `vitest.config.ts` was not copied or symlinks are resolved via `realpath`, Vite imports the unmutated original!

**The Materialized Overlay Architecture:**
Module: `tools/mutator/overlay.py`
```python
def create_worker_overlay(
    repo_root: Path,
    target_rel_path: str,
    mutated_bytes: bytes,
    work_root: Optional[Path] = None
) -> Path
```
1. Create isolated worker folder: `.edge/mutation-workers/worker-<uuid>/`.
2. **Physical Copy of Build/Test Configs:**
   Copy `vitest.config.ts`, `vitest.config.mts`, `vitest.config.js`, `vite.config.ts`, `tsconfig.json`, `package.json`, `pyproject.toml`, `pytest.ini`.
3. **Write Mutated File:**
   Write `mutated_bytes` into `overlay_path / target_rel_path`.
4. **Recursive Materialization of Importers:**
   Scan repo files. Any module or test that imports `target_rel_path` via relative paths (`./`, `../`) OR TypeScript path aliases (`@/...` resolved via `tsconfig.json paths`, defaulting `@/*` to `src/*`) is physically copied into the overlay, preserving directory hierarchy.
5. **Symlink Untouched Assets:**
   All other non-dependent directories (e.g. `node_modules`, `public`, unrelated domains) are symlinked into the overlay.

### 7.4 Safe Overlay Materialization & Cleanup
```python
def cleanup_worker_overlay(overlay_path: Path) -> None:
    """
    Safely tears down the worker overlay without traversing symlinks into the real repository.
    Unlinks directory and file symlinks directly, then deletes copied files.
    """
```

### 7.5 Differential Result Caching Engine
Module: `tools/mutator/runner.py`
- Cache file: `<repo>/.edge/metrics/mutator.json`.
- Cache Key: `(rel_path, function_hash, site_signature)`
- If a mutant was previously `KILLED` and neither the target function AST nor the companion test file has changed (matching SHA-256 hash), reuse the cached `KILLED` status without running the test suite.

### 7.6 Mutator CLI Contract
Module: `tools/mutator/cli.py`
Command Arguments:
- `--target <path>`: Target file to mutate (e.g., `src/core/pricing.ts`).
- `--test-cmd <cmd>`: Command to execute tests (e.g. `npm run test:unit -- src/core/pricing.test.ts`).
- `--threshold <pct>`: Minimum mutation score percentage (default: `80.0`). Exits with `code 1` if score is below threshold.
- `--scan-only`: Discover mutation sites and print them without executing tests.
- `--allow-non-core`: Permit targeting files outside core scope.

---

## 8. Concrete Python Seam Contracts (Single Source of Truth)

All classes and functions must strictly adhere to the following Python 3.10+ types and contracts:

### 8.1 Slice F1: `tools/brigade/orchestrator_guard.py` & `fsm.py`
```python
# tools/brigade/orchestrator_guard.py
GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000

def sync_repo_brigade_station(repo_path: Path, role: str, conversation_id: str) -> bool: ...
def handle_post_tool(payload: dict) -> dict: ...

# tools/brigade/fsm.py
GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000

class BrigadeFSM:
    @staticmethod
    def get_heat_zone(token_count: int) -> Tuple[ContextHeatZone, str]: ...
    def guard_gate_to_staging(self) -> Tuple[bool, str, Dict[str, Any]]: ...
```

### 8.2 Slice F2: `tools/audit/dryer.py`
```python
# tools/audit/dryer.py
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, Any

@dataclass
class AstUnit:
    file_path: str
    symbol: str
    kind: str  # "function" | "method" | "block" | "jsx"
    start_line: int
    end_line: int
    node_count: int
    fingerprints: frozenset[str]

@dataclass
class ClonePair:
    score: float
    language: str
    left: AstUnit
    right: AstUnit

@dataclass
class CloneCluster:
    cluster_id: str
    language: str
    max_score: float
    members: List[AstUnit]
    distinct_files: List[str]

def normalize_ast(node: Any, source_bytes: bytes) -> Optional[Tuple[Any, ...]]: ...
def jaccard_similarity(fp_a: frozenset[str], fp_b: frozenset[str]) -> float: ...

class DryerScanner:
    def __init__(self, threshold: float = 0.82, min_lines: int = 5, min_nodes: int = 20): ...
    def scan_path(self, target_path: Path, scoped_files: Optional[List[str]] = None) -> List[ClonePair]: ...
    def cluster_clones(self, pairs: List[ClonePair]) -> List[CloneCluster]: ...
```

### 8.3 Slice F3: `tools/audit/crapper.py`
```python
# tools/audit/crapper.py
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

@dataclass
class FunctionCrapMetric:
    file_path: str
    name: str
    start_line: int
    end_line: int
    complexity: int
    coverage_pct: Optional[float]
    crap_score: Optional[float]

def compute_crap(cc: int, coverage_pct: float) -> float: ...
def parse_lcov(lcov_content: str) -> Dict[str, Dict[str, Any]]: ...
def function_coverage_from_lcov(file_cov: Dict[str, Any], start_line: int, end_line: int) -> float: ...
def analyze_file_crap(file_path: Path, rel_path: str, lcov_data: Optional[Dict[str, Any]] = None) -> List[FunctionCrapMetric]: ...
def discover_existing_lcov(repo_root: Path) -> Optional[Path]: ...
```

### 8.4 Slice F4: `tools/audit/dead_code.py`
```python
# tools/audit/dead_code.py
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Tuple

@dataclass
class DeadCodeReport:
    unused_files: List[str]
    unused_exports: List[Dict[str, Any]]
    unused_types: List[Dict[str, Any]]
    engine: str  # "knip" | "fallback"

def parse_knip_json(raw_json: str) -> DeadCodeReport: ...
def run_dead_code_scan(repo_root: Path, timeout_sec: int = 60) -> DeadCodeReport: ...
def run_mechanical_presweep(repo_root: Path) -> Tuple[int, str]: ...
```

### 8.5 Slice F5: `tools/mutator/`
```python
# tools/mutator/sites.py
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Set

@dataclass(frozen=True)
class MutationSite:
    file_path: str
    function_name: str
    line: int
    start_byte: int
    end_byte: int
    original: str
    mutant: str
    category: str

def discover_mutation_sites(file_path: Path, rel_path: str, covered_lines: Optional[Set[int]] = None) -> List[MutationSite]: ...
def apply_mutation(source_bytes: bytes, site: MutationSite) -> bytes: ...

# tools/mutator/overlay.py
def create_worker_overlay(repo_root: Path, target_rel_path: str, mutated_bytes: bytes, work_root: Optional[Path] = None) -> Path: ...
def cleanup_worker_overlay(overlay_path: Path) -> None: ...

# tools/mutator/runner.py
@dataclass
class MutantOutcome:
    site: MutationSite
    status: str  # "KILLED" | "SURVIVED" | "TIMED_OUT"
    duration_sec: float

@dataclass
class MutationSummary:
    total: int
    killed: int
    survived: int
    timed_out: int
    score_pct: float
    outcomes: List[MutantOutcome]

def enforce_core_scope(rel_path: str, allow_non_core: bool = False) -> bool: ...
def run_mutation_suite(
    repo_root: Path,
    target_file: Path,
    test_cmd: List[str],
    timeout_sec: float = 15.0,
    allow_non_core: bool = False
) -> MutationSummary: ...
```

---

## 9. Formal Acceptance Criteria (Gherkin Scenarios)

### Scenario 1 (F1): Subagent Rotates at 45k Tokens
```gherkin
Given a persistent station worker exists for role "CODER" with conversationId "cid-101"
And the subagent transcript contains 46,000 processed tokens
When the Orchestrator evaluates a spawn request for role "CODER"
Then the StationSelector marks worker "cid-101" as EXHAUSTED
And the decision returns "allow" with reason "ROTATION: Worker saturated"
```

### Scenario 2 (F1): Direct Response Conversation ID Extraction
```gherkin
Given a toolCall "invoke_subagent" with role "SURGEON" completes
And the runtime payload contains toolResponse `{"conversationId": "cid-surgeon-999"}`
And the transcript.jsonl file on disk has not flushed yet
When handle_post_tool is executed with the payload
Then station "SURGEON" is registered immediately with conversationId "cid-surgeon-999"
And the workspace file ".edge/brigade.json" is updated with the new station
```

### Scenario 3 (F1): Verification De-duplication in Gate
```gherkin
Given BrigadeFSM is in state POLISH
And characterization tests and tsc have already passed
When the state machine advances to GATE and executes guard_gate_to_staging
Then the command invoked for gate.py includes the argument "--skip-verify"
And gate.py completes without re-executing unit tests or timing out
```

### Scenario 4 (F2): Structural AST Clone Detection with Variable Renaming
```gherkin
Given file "src/core/tax_a.ts" contains function calculateTax with local variables (amount, rate)
And file "src/core/tax_b.ts" contains identical control flow but local variables (price, pct)
When DryerScanner scans the repository
Then a ClonePair is detected between tax_a.ts and tax_b.ts with score >= 0.82
And the ClonePair is clustered into a CloneCluster
```

### Scenario 5 (F3): CRAP Score Calculation and Fat Function Suppression
```gherkin
Given function "processOrders" has cyclomatic complexity 12 and 100% branch coverage
When compute_crap is calculated for processOrders
Then the CRAP score is 12.0
And RadarScanner suppresses the RULE-FAT-FUNCTION finding because crap_score < 15.0
```

### Scenario 6 (F3): Untested Complex Function Flagged as High CRAP
```gherkin
Given function "legacyDispatcher" has cyclomatic complexity 10 and 0% test coverage
When compute_crap is calculated for legacyDispatcher
Then the CRAP score is 110.0
And RadarScanner emits finding "RULE-HIGH-CRAP" with severity "CRITICAL"
```

### Scenario 7 (F4): Mechanical Debt De-pollution via ESLint Fix
```gherkin
Given file "src/components/Header.tsx" contains 5 unused import symbols
When run_mechanical_presweep is executed
Then "npx eslint --fix" removes the unused imports
And RadarScanner scan_ui with include_mechanical=False emits 0 tickets for RULE-DEAD-IMPORT
```

### Scenario 8 (F5): Core Scope Boundary Enforcement
```gherkin
Given a user attempts to run mutation testing on "src/components/Modal.tsx"
When enforce_core_scope is invoked without allow_non_core=True
Then a ValueError is raised specifying that mutation testing is restricted to core logic
```

### Scenario 9 (F5): Next.js `@/` Path Alias Resolution in Worker Overlay
```gherkin
Given file "src/core/billing.ts" is targeted for mutation
And file "tests/billing.test.ts" imports billing via "import { calc } from '@/core/billing'"
And "tsconfig.json" maps "@/*" to "src/*"
When create_worker_overlay is executed
Then "tests/billing.test.ts" is physically copied into the overlay
And "tsconfig.json" and "vitest.config.ts" are physically copied into the overlay
And running the test command inside the overlay resolves the mutated file
And cleanup_worker_overlay tears down the overlay without modifying the primary repository
```

---

## 10. Comprehensive Test Plan

All test files must reside in `tests/` and be executable via:
`uv run --with pytest pytest tests/`

### 10.1 `tests/test_brigade_guard.py` (Update for F1)
- `test_45k_green_heat_threshold_rotation()`: Verify that a worker with 44,999 tokens is reused (`deny`), while 45,001 tokens triggers rotation (`allow`).
- `test_handle_post_tool_direct_response_extraction()`: Mock payloads with dict and string responses; assert registration succeeds without reading `transcript.jsonl`.
- `test_sync_repo_brigade_station()`: Verify atomic creation and updates to `.edge/brigade.json`.
- `test_fsm_gate_appends_skip_verify()`: Mock `_run_cmd` in `BrigadeFSM.guard_gate_to_staging` and assert `"--skip-verify"` is present in the argument list.

### 10.2 `tests/test_dryer.py` (New Suite for F2)
- `test_ast_normalization_variable_renaming()`: Verify normalized AST tuples match for renamed identifiers.
- `test_ast_normalization_jsx_tag_preservation()`: Verify `<Card>` and `<Button>` are not conflated.
- `test_jaccard_similarity()`: Verify boundary conditions (`0.0`, `1.0`, empty sets).
- `test_dryer_scan_and_cluster()`: Run on synthetic TypeScript/Python snippets; verify connected component clusters.
- `test_dryer_graceful_import_error()`: Mock `TREE_SITTER_AVAILABLE = False`; assert `scan_path` returns `[]` safely.

### 10.3 `tests/test_crapper.py` (New Suite for F3)
- `test_compute_crap_formula()`: Test matrix:
  - CC=1, Cov=100% $\rightarrow$ CRAP=1.0
  - CC=10, Cov=100% $\rightarrow$ CRAP=10.0
  - CC=10, Cov=0% $\rightarrow$ CRAP=110.0
  - CC=30, Cov=50% $\rightarrow$ CRAP=142.5
- `test_parse_lcov_branches_and_lines()`: Parse sample LCOV text; verify line hits and branch hits extraction.
- `test_function_coverage_branch_priority()`: Verify branch coverage takes priority over line coverage when branches exist.
- `test_tree_sitter_complexity_extraction()`: Verify function extraction on large functions (> 500 lines) without string-brace truncation.

### 10.4 `tests/test_dead_code.py` (New Suite for F4)
- `test_parse_knip_json()`: Parse sample Knip JSON report into `DeadCodeReport`.
- `test_run_dead_code_fallback()`: Test fallback to `GraphBuilder` when knip is unavailable.
- `test_mechanical_presweep()`: Verify command construction for `npx eslint --fix`.

### 10.5 `tests/test_mutator.py` (New Suite for F5)
- `test_enforce_core_scope()`: Verify allowed prefixes (`src/core/`, `core/`, `tools/`) and rejection of `src/components/`.
- `test_discover_mutation_sites()`: Verify discovery of arithmetic, relational, and boolean sites.
- `test_apply_mutation_byte_offset()`: Verify clean byte replacement without offset drifting.
- `test_create_and_cleanup_worker_overlay()`: Verify physical config copies, importer materialization, alias resolution, and leak-free cleanup.
- `test_differential_cache_hit_and_miss()`: Verify cache prevents re-execution of unchanged killed mutants.

### 10.6 `tests/test_radar_quality_rules.py` (Integration Suite)
- `test_radar_suppresses_fat_function_when_crap_clean()`: Verify `RULE-FAT-FUNCTION` is not emitted when CRAP < 15.0.
- `test_radar_emits_rule_high_crap()`: Verify `RULE-HIGH-CRAP` is emitted when CRAP >= 30.0.
- `test_radar_ui_omits_mechanical_dead_import_by_default()`: Verify `scan_ui` does not flood ledger with `RULE-DEAD-IMPORT`.

---

## 11. Execution Sequence for SEAM_ARCHITECT and CODER

```
┌────────────────────────────────────────────────────────────────────────┐
│                      UB-QUALITY-SUITE EXECUTION                        │
│                                                                        │
│   [Slice F1: Guard SSOT & Rotation] ──► RED Tests ──► GREEN Impl       │
│                  │                                                     │
│   [Slice F2: DRYER Clone Engine]    ──► RED Tests ──► GREEN Impl       │
│                  │                                                     │
│   [Slice F3: CRAPPER Risk Engine]   ──► RED Tests ──► GREEN Impl       │
│                  │                                                     │
│   [Slice F4: Knip De-pollution]     ──► RED Tests ──► GREEN Impl       │
│                  │                                                     │
│   [Slice F5: MUTATOR Core Gate]     ──► RED Tests ──► GREEN Impl       │
│                  │                                                     │
│   [Full Suite & Regression Check]   ──► pytest (100% Passing)          │
└────────────────────────────────────────────────────────────────────────┘
```

1. **Step 1: Slice F1**
   - Implement `GREEN_HEAT_THRESHOLD = 45000` & `YELLOW_HEAT_THRESHOLD = 75000` in `orchestrator_guard.py` & `fsm.py`.
   - Update `handle_post_tool` direct response extraction & `sync_repo_brigade_station`.
   - Append `"--skip-verify"` in `guard_gate_to_staging()`.
   - Validate `tests/test_brigade_guard.py` and `tests/test_brigade.py`.
2. **Step 2: Slice F2**
   - Create `tools/audit/dryer.py`.
   - Integrate with `tools/audit/cli.py` (`--track clones`) and `tools/radar/scanner.py`.
   - Validate `tests/test_dryer.py`.
3. **Step 3: Slice F3**
   - Create `tools/audit/crapper.py`.
   - Upgrade `tools/audit/adapters/typescript.py` to use AST extraction.
   - Integrate CRAP metric and fat-function suppression into `tools/radar/scanner.py`.
   - Validate `tests/test_crapper.py`.
4. **Step 4: Slice F4**
   - Create `tools/audit/dead_code.py`.
   - Update `tools/radar/scanner.py` (`include_mechanical=False`).
   - Add `--track dead-code` in `tools/audit/cli.py`.
   - Validate `tests/test_dead_code.py`.
5. **Step 5: Slice F5**
   - Create `tools/mutator/sites.py`, `overlay.py`, `runner.py`, `cli.py`, `__init__.py`.
   - Implement alias-aware overlay materialization and differential caching.
   - Validate `tests/test_mutator.py`.
6. **Step 6: Gate Verification**
   - Run unified `uv run --with pytest pytest tests/` to confirm zero regressions across all 140+ existing tests and new suites.
