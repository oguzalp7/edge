"""TypeScript/JavaScript unit test purity and external I/O leakage analyzer."""

import os
from pathlib import Path
import re
from typing import Any, Dict, List, Tuple

_DB_IMPORT_PATS = (
    r"import\s+.*\{[^}]*\bdb\b[^}]*\}\s+from\s+['\"]@/db['\"]",
    r"import\s+.*\bdb\b.*\s+from\s+['\"]@/db['\"]",
    r"import\s+.*from\s+['\"]@/db/index['\"]",
    r"import\s+.*from\s+['\"]@/db['\"]",
)
_PURE_CORE_RE = re.compile(
    r"from\s+['\"]@/(?:core|domain|lib/[^'\"]+/(?:domain|core|engine|rules|calculator)"
    r"|lib/pricing/rate-resolver|lib/pricing/campaign-rules|lib/customers/qualification)(?:/[^'\"]*)?['\"]"
)


def get_test_files(target_dir: Path) -> List[Path]:
    """Collect JS/TS test files under target_dir."""
    if not target_dir.exists():
        return []
    if target_dir.is_file():
        return [target_dir] if target_dir.suffix in (".ts", ".tsx", ".js", ".jsx") else []
    results: List[Path] = []
    for walk_root, _, files in os.walk(target_dir):
        for fname in files:
            if fname.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                results.append(Path(walk_root) / fname)
    return sorted(results)


def _check_db_and_teardown(content: str, violations: List[Dict[str, Any]]) -> Tuple[int, bool]:
    delta = 0
    has_db_import = any(re.search(pat, content) for pat in _DB_IMPORT_PATS)
    if has_db_import:
        delta -= 35
        violations.append({"rule": "DB_CLIENT_IMPORT", "penalty": -35, "desc": "Direct database client (@/db) imported"})
    dml_matches = re.findall(r"\bdb\.(insert|update|delete|transaction|execute)\s*\(", content)
    if dml_matches:
        delta -= 25
        ops = ", ".join(f"db.{op}()" for op in sorted(set(dml_matches)))
        violations.append({"rule": "DB_DML_EXECUTION", "penalty": -25, "desc": f"Physical database manipulation ({len(dml_matches)} calls: {ops})"})
    seed_matches = re.findall(r"\b(seed[A-Z]\w*|ensure[A-Z]\w*Tables)\s*\(", content)
    if seed_matches:
        delta -= 20
        seeds = ", ".join(f"{s}()" for s in sorted(set(seed_matches)))
        violations.append({"rule": "DDL_OR_SEED_EXECUTION", "penalty": -20, "desc": f"DDL or Seed execution ({seeds})"})
    has_db_activity = has_db_import or bool(dml_matches)
    has_teardown = bool(re.search(r"\b(afterAll|afterEach)\s*\(", content))
    has_cleanup = bool(re.search(r"\bcleanup\w*\s*\(", content, re.IGNORECASE) or re.search(r"\bdelete\w*\s*\(", content))
    if has_db_activity and not has_teardown and not has_cleanup:
        delta -= 25
        violations.append({"rule": "NO_TEARDOWN", "penalty": -25, "desc": "Database manipulation present without afterAll/cleanup (DB poisoning risk)"})
    elif has_db_activity and has_teardown and not has_cleanup:
        delta -= 10
        violations.append({"rule": "WEAK_TEARDOWN", "penalty": -10, "desc": "afterAll present but lacks concrete cleanup/deletion"})
    return delta, has_db_import or bool(dml_matches)


def _check_actions_collisions_and_bonuses(
    content: str, root_dir: Path, has_db_activity: bool, has_db_import: bool,
    violations: List[Dict[str, Any]], bonuses: List[Dict[str, Any]],
) -> int:
    from tools.common.profiles import has_profile_capability, resolve_active_profiles

    delta = 0
    prof = resolve_active_profiles(root_dir)
    allow_actions = prof.source not in ("explicit", "explicit_none") or has_profile_capability(prof, "server_actions")
    action_matches = re.findall(r"from\s+['\"]@/actions/[^'\"]+['\"]", content) if allow_actions else []
    if action_matches:
        delta -= 15
        violations.append({"rule": "SERVER_ACTION_IMPORT", "penalty": -15, "desc": f"Direct dependency on Server Action layer ({len(action_matches)} imports)"})
    if has_db_activity and re.search(r"['\"](?:\+?[1-9]\d{9,14}|5[0-9]{9}|test@example\.com)['\"]", content):
        delta -= 5
        violations.append({"rule": "HARDCODED_DATA_COLLISION", "penalty": -5, "desc": "Static phone/credential used in DB write (Unique constraint collision risk)"})
    if re.search(r"\bvi\.(fn|mock|spyOn)\s*\(", content):
        delta += 10
        bonuses.append({"bonus": 10, "desc": "Isolated in-memory mock used (vi.mock / vi.fn)"})
    if _PURE_CORE_RE.search(content) and not has_db_import:
        delta += 15
        bonuses.append({"bonus": 15, "desc": "Pure Domain / Core engine test (Hermetic)"})
    return delta


def analyze_test_file(file_path: Path, root_dir: Path) -> Dict[str, Any]:
    """Score a single unit test file for DB/I/O purity."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"path": str(file_path), "score": 0, "badge": "🔴 ERROR", "category": "ERROR", "violations": [{"rule": "READ_ERROR", "penalty": -100, "desc": f"File could not be read: {exc}"}], "bonuses": []}
    try:
        rel_path = file_path.resolve().relative_to(root_dir).as_posix()
    except ValueError:
        rel_path = file_path.as_posix()
    violations: List[Dict[str, Any]] = []
    bonuses: List[Dict[str, Any]] = []
    d1, has_db_activity = _check_db_and_teardown(content, violations)
    has_db_import = any(v["rule"] == "DB_CLIENT_IMPORT" for v in violations)
    d2 = _check_actions_collisions_and_bonuses(content, root_dir, has_db_activity, has_db_import, violations, bonuses)
    score = max(0, min(100, 100 + d1 + d2))
    category, badge = ("RED_TOXIC", "🔴 TOXIC (LEAKY)") if score < 50 else (("YELLOW_MASKED", "🟡 MASKED INTEGRATION") if score < 85 else ("GREEN_PURE", "🟢 PURE UNIT"))
    return {"path": rel_path, "score": score, "badge": badge, "category": category, "violations": violations, "bonuses": bonuses}
