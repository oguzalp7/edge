"""Submodule: ledger."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import hashlib
import subprocess

from tools.brigade.security.models import CoverageUnit, SecurityFinding
from tools.brigade.security.validate import _classify_surface_and_boundary
from tools.brigade.security.scanners_sinks import _scan_single_file
from tools.brigade.security.ledger_select import _finding_rel_path

def _build_coverage_unit(
    rel: str,
    sha: str,
    status: str,
    last_audited_at: str,
    content: str,
    allow_server_actions: bool = True,
) -> CoverageUnit:
    surface, boundary = _classify_surface_and_boundary(rel, content, allow_server_actions=allow_server_actions)
    cid = f"COV-{hashlib.sha256(rel.encode('utf-8')).hexdigest()[:8].upper()}"
    return CoverageUnit(
        coverage_id=cid,
        file_path=rel,
        file_sha256=sha,
        surface=surface,
        boundary=boundary,
        attack_class="ALL_4_CLASSES",
        status=status,
        last_audited_at=last_audited_at,
    )


def _merge_ledger_and_findings(
    sources: Dict[str, Path],
    shas: Dict[str, str],
    active: Set[str],
    prior_units: Dict[str, CoverageUnit],
    prior_findings: List[SecurityFinding],
    now_iso: str,
    allow_server_actions: bool = True,
) -> Tuple[List[CoverageUnit], List[SecurityFinding]]:
    units: List[CoverageUnit] = []
    preserved_files: Set[str] = set()
    scanned_findings: List[SecurityFinding] = []

    for rel, path in sources.items():
        content = path.read_text(encoding="utf-8", errors="ignore")
        if rel in active:
            scanned_findings.extend(_scan_single_file(rel, path, allow_server_actions=allow_server_actions))
            units.append(_build_coverage_unit(rel, shas[rel], "covered", now_iso, content, allow_server_actions=allow_server_actions))
        else:
            prev = prior_units.get(rel)
            if prev and prev.status == "covered" and prev.file_sha256 == shas[rel]:
                preserved_files.add(rel)
                units.append(prev)
            else:
                prev_ts = prev.last_audited_at if prev else ""
                units.append(_build_coverage_unit(rel, shas[rel], "out_of_scope", prev_ts, content, allow_server_actions=allow_server_actions))

    merged_findings = [f for f in prior_findings if _finding_rel_path(f) in preserved_files]
    merged_findings.extend(scanned_findings)
    return units, merged_findings


def _ensure_security_dir_excluded(repo: Path) -> None:
    """Marks .edge/security/ excluded locally when inside a git repo without .edge gitignore."""
    exclude_file = repo / ".git" / "info" / "exclude"
    if not (repo / ".git").is_dir():
        return
    try:
        chk = subprocess.run(
            ["git", "check-ignore", "-q", ".edge/security/coverage-ledger.json"],
            cwd=str(repo),
            capture_output=True,
            timeout=5,
        )
        if chk.returncode == 0:
            return
    except Exception:
        return
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_file.read_text(encoding="utf-8", errors="ignore") if exclude_file.is_file() else ""
    if ".edge/security/" not in existing.splitlines():
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        exclude_file.write_text(f"{existing}{prefix}.edge/security/\n", encoding="utf-8")
