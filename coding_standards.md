# 🛡️ Edge Plugin Coding Standards & Architectural Invariants

This document establishes the mandatory engineering standards, lifecycle invariants, and architectural conventions for the `edge` plugin codebase.

---

## 🐍 1. Python Architecture & Language Standards

1. **Python Version:** Python >= 3.11 is required.
2. **Data Modeling:** Use `@dataclass` (with `field(default_factory=...)` where appropriate) and standard library `asdict` / `from_dict` methods for data contracts and state representations.
3. **Path Handling:** Always use `pathlib.Path` for filesystem operations. Do not concatenate paths with raw string operations.
4. **Type Annotations:** Explicit type annotations (`typing.Dict`, `typing.List`, `typing.Optional`, `typing.Union`, `typing.Any`, `typing.Tuple`) must be declared across all function arguments, return types, and class attributes.
5. **Deterministic CLI Exit Codes:** CLI tools must return deterministic process exit codes:
   - `0`: Success / Passed / Allowed.
   - Non-zero (`1` or specific error code): Failure / Blocked / Verification Gate Violation.

---

## 🐧 2. WSL2-First Execution & Path Normalization

1. **WSL2 Runtime Environment:** All execution, build, and test steps run under Linux WSL2 (`/home/oguz/...`). Antigravity terminal execution must invoke WSL via `wsl bash -lc "cd <worktree-path> && ..."`.
2. **Path Normalization:**
   - Use `tools.common.paths` (`normalize_target_path`, `to_wsl_path`, `is_wsl_path`) to translate transparently between Windows UNC paths (`\\wsl.localhost\Ubuntu-24.04\...`) and Linux WSL paths (`/home/oguz/...`).
   - Tools must never assume a single OS path separator or drive format.

---

## ⚡ 3. Lifecycle Hook Performance & Zero Heavy Dependencies

1. **Sub-50ms Hook Execution:** Lifecycle hooks (specifically `tools/brigade/orchestrator_guard.py` for `pre_tool`, `post_tool`, and `pre_invocation`) are in the critical interactive path and MUST complete in under 50ms.
2. **Standard Library Only:** Hook scripts must rely exclusively on Python standard library modules (`sys`, `os`, `json`, `re`, `pathlib`, `dataclasses`, `datetime`, `typing`). No external packages may be imported in `orchestrator_guard.py`.
3. **Ephemeral Execution for Heavy Tooling:** Heavy AST analysis, linters, or formatting tools must be run on-demand via `uv run` in isolated sub-processes, never imported into lifecycle hook entry points.

---

## 💾 4. Atomic Persistence & State Integrity

1. **Atomic File Writes:** State files under `.edge/*.json` (such as `brigade.json`, `checkpoint.json`, `ux_defects.json`) must be persisted atomically:
   - Write serialized payload to a temporary file in the target directory (`<filename>.tmp.<pid>`).
   - Atomically replace the destination file using `os.replace()` or `Path.rename()` to eliminate partial-write or concurrency corruption risks.
2. **Schema Resilience:** Deserializers (`from_dict`) must gracefully tolerate schema migrations and ignore or map legacy station roles to maintain backward compatibility across plugin upgrades.

---

## 🧑‍🍳 5. The 7 Canonical Brigade Stations & Deterministic Merge

Edge Brigade operates with exactly **7 persistent station workers** governed by a deterministic Python FSM:

1. **`SPEC_WRITER` (`spec_writer`):** INVEST-compliant vertical slice specification author & visual approval manager (`lavish-axi`).
2. **`RESEARCHER` (`researcher`):** Deep code exploration and root cause analysis (RCA). Strictly read-only (`write_file` and `edit_file` denied).
3. **`SEAM_ARCHITECT` (`seam_architect`):** Feathers seams, interface contracts (`src/types/**`), and RED unit/contract tests author (TDD anchor).
4. **`CODER` (`coder`):** Production code implementer turning RED tests GREEN (`src/**`). Never modifies or weakens tests (Test Immutability Invariant).
5. **`SURGEON` (`surgeon`):** Refactoring and database leak extraction specialist. Bound by the **MigrationGate Invariant** (never mutates `src/db/schema/**` or `drizzle/**` on refactor tracks).
6. **`EXAMINER` (`examiner`):** Unified dual-axis reviewer combining coding standards/Fowler code-smell auditing with architectural invariants and scope-creep boundaries in a single concise pass. Strictly read-only.
7. **`QA_ENGINEER` (`qa_engineer`):** Sommelier for E2E browser verification and visual quality assurance. Strictly read-only on production code.

### Deterministic Delivery (`finish-slice`)
- The legacy `EXPEDITER` agent station is deprecated and removed.
- Staging, squash-merging, and fast-forward delivery are managed deterministically by the Python FSM via `brigade finish-slice <repo>` rather than stochastic LLM prompts.

---

## 🧪 6. Hermetic Testing & Test Isolation

1. **Test Runner:** Tests are run with `pytest` using `uv run --with pytest pytest -q`.
2. **Hermetic Fixtures:** Unit tests must operate on hermetic temporary fixtures (e.g. `tmp_path` or `tempfile.TemporaryDirectory()`).
3. **Repository State Immutability:** Unit tests MUST NEVER modify, delete, or create files within the active repository's `.git`, `.edge`, or working directory. Any global file pointers or environment variables must be patched and cleanly restored in `tearDown`.
