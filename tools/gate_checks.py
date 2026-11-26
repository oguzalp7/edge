"""Core backend, complexity, and fallback purity checks for Edge Verification Gate."""

from pathlib import Path
from typing import Any, Optional

from tools.gate_cc import compute_source_max_cc
from tools.gate_git import get_changed_rel_paths, read_changed_prod_files
from tools.gate_static import (
    PRODUCTION_CODE_SUFFIXES,
    GateResult,
    count_sql_leaks,
    find_mock_fallback_violations,
    is_action_controller_path,
    is_excluded_non_prod_path,
)


def check_migration_gate(run_cmd: Any, base_ref: str = "HEAD~1") -> GateResult:
    """Enforce MigrationGate: zero schema or migration file modifications."""
    code, stdout, stderr = run_cmd(["git", "diff", "--name-only", base_ref])
    if code != 0:
        code, stdout, stderr = run_cmd(["git", "diff", "--name-only", "HEAD"])
        if code != 0:
            code, stdout, stderr = run_cmd(["git", "diff", "--name-only"])
            if code != 0:
                return GateResult(1, "MigrationGate Invariant Gate", False, f"Git diff failed: {stderr.strip()}")
    violations = [raw.strip().replace("\\", "/") for raw in stdout.strip().splitlines() if raw.strip().replace("\\", "/").startswith(("src/db/schema", "drizzle/"))]
    if violations:
        return GateResult(
            1, "MigrationGate Invariant Gate", False,
            "MigrationGate VIOLATION: Database schemas or migrations were modified during a refactor task!",
            [f"Forbidden modified file: {v}" for v in violations],
        )
    return GateResult(1, "MigrationGate Invariant Gate", True, "Database schema and migrations preserved (0 schema/migration files touched).")


def check_complexity_non_regression(target_repo: Path, run_cmd: Any, base_ref: str = "HEAD~1", healthy_cc_ceiling: int = 10) -> GateResult:
    """Enforce per-function cyclomatic complexity non-regression across changed files."""
    rel_paths, eff_base, err = get_changed_rel_paths(target_repo, run_cmd, base_ref)
    if rel_paths is None:
        return GateResult(1, "Max CC Non-Regression Gate", False, f"Git diff failed: {err}")
    violations, inspected = [], []
    for rel_path in rel_paths:
        suffix = Path(rel_path).suffix.lower()
        full_path = target_repo / rel_path
        if is_excluded_non_prod_path(rel_path) or suffix not in PRODUCTION_CODE_SUFFIXES or not full_path.is_file():
            continue
        after_cc, after_sym = compute_source_max_cc(full_path.read_text(encoding="utf-8", errors="replace"), suffix)
        show_code, before_text, _ = run_cmd(["git", "show", f"{eff_base}:{rel_path}"])
        if show_code != 0:
            inspected.append(f"{rel_path} (new): max_cc={after_cc} ({after_sym})")
            if after_cc > healthy_cc_ceiling:
                violations.append(f"{rel_path}: new production file \x27{after_sym}\x27 has CC={after_cc} > ceiling {healthy_cc_ceiling}.")
            continue
        before_cc, _ = compute_source_max_cc(before_text, suffix)
        inspected.append(f"{rel_path}: max_cc {before_cc} -> {after_cc} ({after_sym})")
        if after_cc > max(before_cc, healthy_cc_ceiling):
            violations.append(f"{rel_path}: max CC regressed {before_cc} -> {after_cc} ({after_sym}), exceeds ceiling of {healthy_cc_ceiling}")
    if violations:
        return GateResult(1, "Max CC Non-Regression Gate", False, f"Cyclomatic complexity violation(s) detected in {len(violations)} production file(s).", violations)
    return GateResult(1, "Max CC Non-Regression Gate", True, f"Max CC non-regression satisfied across {len(inspected)} production file(s) (healthy ceiling: {healthy_cc_ceiling}).", inspected[:8])


def check_layer_leakage(target_repo: Path, run_cmd: Any, base_ref: str = "HEAD~1") -> GateResult:
    """Enforce action/controller DB layer leakage non-regression."""
    rel_paths, eff_base, err = get_changed_rel_paths(target_repo, run_cmd, base_ref)
    if rel_paths is None:
        return GateResult(1, "Layer Leakage Gate", False, f"Git diff failed: {err}")
    violations, inspected = [], []
    for rel_path in rel_paths:
        full_path = target_repo / rel_path
        if not is_action_controller_path(rel_path) or not full_path.is_file():
            continue
        after_leaks = count_sql_leaks(full_path.read_text(encoding="utf-8", errors="replace"))
        show_code, before_text, _ = run_cmd(["git", "show", f"{eff_base}:{rel_path}"])
        if show_code != 0:
            inspected.append(f"{rel_path} (new action): {after_leaks} direct DB call(s)")
            if after_leaks > 0:
                violations.append(f"{rel_path}: newly created action controller contains {after_leaks} direct DB leak(s) (0 allowed).")
            continue
        before_leaks = count_sql_leaks(before_text)
        inspected.append(f"{rel_path}: direct DB leaks {before_leaks} -> {after_leaks}")
        if after_leaks > before_leaks:
            violations.append(f"{rel_path}: DB layer leakage increased {before_leaks} -> {after_leaks} direct DB call(s).")
    if violations:
        return GateResult(1, "Layer Leakage Gate", False, f"Action/controller DB layer leakage detected in {len(violations)} file(s).", violations)
    return GateResult(1, "Layer Leakage Gate", True, f"Controller layer DB leakage check passed across {len(inspected)} action file(s).", inspected[:8])


def check_mock_fallbacks(target_repo: Path, run_cmd: Any, base_ref: Optional[str] = "HEAD~1") -> GateResult:
    """Detect DEFAULT_* and MOCK_* synthetic fallbacks in changed production src/ files."""
    files, err = read_changed_prod_files(target_repo, run_cmd, base_ref, (".ts", ".tsx", ".js", ".jsx"), require_src_prefix=True)
    if files is None:
        return GateResult(1, "Mock Fallback Purity Gate", False, f"Git diff failed: {err}")
    violations = [v for rel, content in files for v in find_mock_fallback_violations(rel, content)]
    if violations:
        return GateResult(1, "Mock Fallback Purity Gate", False, f"Found {len(violations)} synthetic mock/default fallback violation(s) in production code.", violations[:10])
    return GateResult(1, "Mock Fallback Purity Gate", True, "Zero production DEFAULT_*/MOCK_* fallbacks detected.")
