"""Submodule: ledger_select."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json

from tools.brigade.security.models import CoverageLedger, CoverageUnit, SecurityFinding
from tools.brigade.security.validate import _expand_scopes, _git_diff_rel_files, _matches_scope

def _load_prior_ledger(sec_dir: Path) -> Dict[str, CoverageUnit]:
    ledger_path = sec_dir / "coverage-ledger.json"
    if not ledger_path.is_file():
        return {}
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        return {u.file_path: u for u in CoverageLedger.from_dict(raw).units}
    except Exception:
        return {}


def _load_prior_findings(sec_dir: Path) -> List[SecurityFinding]:
    findings_path = sec_dir / "findings.json"
    if not findings_path.is_file():
        return []
    try:
        raw = json.loads(findings_path.read_text(encoding="utf-8"))
        items = raw.get("findings") if isinstance(raw, dict) else raw
        return [SecurityFinding.from_dict(f) for f in (items or []) if isinstance(f, dict)]
    except Exception:
        return []


def _resolve_diff_set(
    repo: Path,
    diff_only: bool,
    base_ref: Optional[str],
    changed_files: Optional[List[str]],
) -> Optional[Set[str]]:
    if changed_files is not None:
        return {f.strip().replace("\\", "/").lstrip("./") for f in changed_files if f.strip()}
    if diff_only:
        return _git_diff_rel_files(repo, base_ref)
    return None


def _is_target_selected(
    rel: str,
    sha: str,
    prior: Optional[CoverageUnit],
    scan_all: bool,
    scope_tokens: List[str],
    diff_set: Optional[Set[str]],
) -> bool:
    if prior and prior.status == "covered" and prior.file_sha256 != sha:
        return True
    if scan_all:
        return True
    if scope_tokens and _matches_scope(rel, scope_tokens):
        return True
    return diff_set is not None and rel in diff_set


def _select_active_targets(
    sources: Dict[str, Path],
    shas: Dict[str, str],
    prior_units: Dict[str, CoverageUnit],
    scopes: Optional[List[str]],
    diff_only: bool,
    base_ref: Optional[str],
    recursive: bool,
    changed_files: Optional[List[str]],
    repo: Path,
) -> Set[str]:
    scope_tokens = _expand_scopes(scopes)
    diff_set = _resolve_diff_set(repo, diff_only, base_ref, changed_files)
    scan_all = recursive or (not scope_tokens and diff_set is None)
    return {
        rel for rel in sources
        if _is_target_selected(rel, shas[rel], prior_units.get(rel), scan_all, scope_tokens, diff_set)
    }


def _finding_rel_path(finding: SecurityFinding) -> str:
    if finding.fix_target:
        return finding.fix_target
    ep = str(finding.trace.get("entrypoint") or "")
    return ep.split(":", 1)[0]


def _build_scope_label(scopes: Optional[List[str]], diff_only: bool, changed_files: Optional[List[str]]) -> str:
    if scopes:
        return ",".join(_expand_scopes(scopes))
    if diff_only or changed_files is not None:
        return "diff"
    return "recursive"
