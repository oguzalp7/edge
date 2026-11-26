"""Type-escape and hermetic verification checks for Edge Verification Gate."""

from pathlib import Path
import re
from typing import Any, List, Optional, Set, Tuple

from tools.gate_git import get_changed_rel_paths
from tools.gate_static import (
    GateResult,
    collect_ts_diff_violations,
    find_type_escape_violations,
    get_added_line_numbers,
    is_eligible_prod_path,
)


def check_type_escapes(target_repo: Path, run_cmd: Any, base_ref: Optional[str] = "HEAD~1") -> GateResult:
    """Detect type escapes in changed .ts/.tsx files plus newly added TS discipline violations."""
    rel_paths, eff_base, err = get_changed_rel_paths(target_repo, run_cmd, base_ref or "HEAD~1")
    if rel_paths is None:
        return GateResult(1, "Type Escape Gate", False, f"Git diff failed: {err}")
    from tools.audit.ts_discipline import TsDisciplineAuditor

    ts_auditor = TsDisciplineAuditor(target_repo)
    violations: List[str] = []
    seen_keys: Set[Tuple[str, int]] = set()
    for rel_path in rel_paths:
        full_path = target_repo / rel_path
        if rel_path.endswith(".d.ts") or not is_eligible_prod_path(rel_path, (".ts", ".tsx"), require_src_prefix=False) or not full_path.is_file():
            continue
        content = full_path.read_text(encoding="utf-8", errors="replace")
        for hit in find_type_escape_violations(rel_path, content):
            violations.append(hit)
            lm = re.match(r"^.+?:(\d+)\s+-", hit)
            if lm:
                seen_keys.add((rel_path, int(lm.group(1))))
        added = get_added_line_numbers(run_cmd, eff_base, rel_path, len(content.splitlines()))
        violations.extend(collect_ts_diff_violations(ts_auditor, rel_path, content, added, seen_keys))
    if violations:
        return GateResult(1, "Type Escape Gate", False, f"Found {len(violations)} TypeScript type-safety escape(s).", violations[:10])
    return GateResult(1, "Type Escape Gate", True, "Zero TypeScript type-safety escapes detected.")


def check_verification(run_cmd: Any) -> GateResult:
    """Run tsc --noEmit and unit tests."""
    code, stdout, stderr = run_cmd(["npx", "tsc", "--noEmit"])
    if code != 0:
        details = [ln for ln in (stdout + stderr).splitlines() if "error TS" in ln][:8]
        return GateResult(1, "Hermetic Verification Gate", False, "TypeScript typecheck failed.", details)
    code, stdout, stderr = run_cmd(["npm", "run", "test:unit"], timeout=360)
    if code != 0:
        details = [ln for ln in (stdout + stderr).splitlines() if "FAIL" in ln or "Error" in ln][:8]
        return GateResult(1, "Hermetic Verification Gate", False, "Unit tests failed.", details)
    return GateResult(1, "Hermetic Verification Gate", True, "TypeScript clean and all unit tests passed.")
