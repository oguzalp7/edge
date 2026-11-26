"""Core backend, LCOV lookup, and action-layer SQL leak scanning for RadarScanner."""

from pathlib import Path
from typing import Any, Dict, List, Optional

from tools.audit.scanner import FileScanner
from tools.audit.ts_discipline import TsDisciplineAuditor
from tools.rules import SQL_LEAK_PATTERN
from .models import FindingSeverity, FindingStatus, LedgerItem, Track
from .scanner_rules import scan_dryer_clones, scan_function_metrics, scan_ts_and_seam


def _load_lcov(repo_path: Path) -> Dict[str, Any]:
    try:
        from tools.audit.crapper import discover_existing_lcov, parse_lcov
        lcov_file = discover_existing_lcov(repo_path)
        return parse_lcov(lcov_file.read_text(encoding="utf-8", errors="ignore")) if lcov_file else {}
    except Exception:
        return {}


def _resolve_file_lcov(lcov_records: Dict[str, Any], repo_path: Path, fmetric: Any, rel: str) -> Any:
    if not lcov_records:
        return None
    try:
        repo_rel = str(fmetric.path.relative_to(repo_path)).replace("\\", "/")
    except Exception:
        repo_rel = ""
    hit = lcov_records.get(repo_rel) or lcov_records.get(rel) or lcov_records.get(fmetric.path.name)
    if hit:
        return hit
    for lk, lrec in lcov_records.items():
        if (repo_rel and (lk.endswith(repo_rel) or repo_rel.endswith(lk))) or (rel and (lk.endswith(rel) or rel.endswith(lk))) or lk.endswith(fmetric.path.name):
            return lrec
    return None


def _scan_action_sql_leaks(fmetric: Any, rel: str, findings: List[LedgerItem]) -> None:
    if not rel.startswith(("src/actions/", "actions/")):
        return
    try:
        lines = fmetric.path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    for line_idx, line in enumerate(lines, start=1):
        if not SQL_LEAK_PATTERN.search(line):
            continue
        findings.append(LedgerItem(
            fingerprint=LedgerItem.generate_fingerprint("RULE-ACTION-DB-LEAK", rel, symbol="db_call", signature=str(line_idx)),
            track=Track.CORE.value, rule_id="RULE-ACTION-DB-LEAK",
            title=f"Raw SQL/DB operation in Server Action ({rel}:{line_idx})", file_path=rel, line_number=line_idx,
            symbol="db_call", severity=FindingSeverity.CRITICAL.value, status=FindingStatus.OPEN.value,
            details={"code_line": line.strip()},
            suggested_fix="Extract database transaction into domain repository under src/lib/<domain>/repository.ts.",
            first_seen_at="", last_seen_at="",
        ))
        return


def scan_core_findings(repo_path: Path, file_paths: Optional[List[str]] = None) -> List[LedgerItem]:
    """Scan backend actions and core source files for architectural smells."""
    target_dir = repo_path / "src"
    if not target_dir.exists() or (file_paths is not None and len(file_paths) == 0):
        return []
    from tools.common.profiles import has_profile_capability, is_stack_gate_enabled, resolve_active_profiles

    profiles = resolve_active_profiles(repo_path)
    explicit = profiles.source in ("explicit", "explicit_none")
    check_leaks = not explicit or is_stack_gate_enabled(profiles, "layer_leakage")
    check_ts = not explicit or has_profile_capability(profiles, "typescript")
    summary = FileScanner().scan(target_dir, scoped_files=file_paths)
    ts_auditor, lcov_records, findings = TsDisciplineAuditor(repo_path), _load_lcov(repo_path), []
    for fmetric in summary.file_results:
        rel = fmetric.rel_path[2:] if fmetric.rel_path.startswith("./") else fmetric.rel_path
        if file_paths is not None and rel not in file_paths:
            continue
        if check_leaks:
            _scan_action_sql_leaks(fmetric, rel, findings)
        scan_function_metrics(fmetric, rel, _resolve_file_lcov(lcov_records, repo_path, fmetric, rel), findings)
        scan_ts_and_seam(fmetric, rel, ts_auditor, check_ts, findings)
    scan_dryer_clones(target_dir, file_paths, findings)
    return findings
