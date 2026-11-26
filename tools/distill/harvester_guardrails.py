"""
Guardrail gap detection and rule inventory citation analysis for TranscriptGraphHarvester.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.distill.harvester_matching import _read_json_safe
from tools.distill.models import GuardrailGapSignal, RuleInventoryItem
from tools.distill.state import collect_budget_targets


def _collect_ci_and_hook_files(project_path: Path) -> Tuple[List[Path], List[Path]]:
    ci_files: List[Path] = []
    wf_dir = project_path / ".github" / "workflows"
    if wf_dir.is_dir():
        ci_files.extend(sorted(wf_dir.glob("*.yml")))
        ci_files.extend(sorted(wf_dir.glob("*.yaml")))

    hook_files: List[Path] = []
    husky_dir = project_path / ".husky"
    if husky_dir.is_dir():
        hook_files.extend(sorted(p for p in husky_dir.iterdir() if p.is_file()))
    pre_commit = project_path / ".git" / "hooks" / "pre-commit"
    if pre_commit.is_file():
        hook_files.append(pre_commit)
    return ci_files, hook_files


def _read_concatenated_text(paths: List[Path]) -> str:
    chunks: List[str] = []
    for p in paths:
        try:
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(chunks)


def _discover_pkg_checks(project_path: Path) -> List[Tuple[str, str]]:
    pkg = _read_json_safe(project_path / "package.json")
    scripts = pkg.get("scripts") if pkg else None
    if not isinstance(scripts, dict):
        return []
    return [("package.json", name) for name in ("lint", "typecheck", "check", "test") if name in scripts]


def _discover_pyproject_checks(project_path: Path) -> List[Tuple[str, str]]:
    pyproj = project_path / "pyproject.toml"
    if not pyproj.is_file():
        return []
    try:
        text = pyproj.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    pats = ((r"\[tool\.pytest\b", "pytest"), (r"\[tool\.ruff\b", "ruff"), (r"\[tool\.mypy\b", "mypy"))
    return [("pyproject.toml", name) for pat, name in pats if re.search(pat, text)]


def _discover_repo_checks(project_path: Path) -> List[Tuple[str, str]]:
    return _discover_pkg_checks(project_path) + _discover_pyproject_checks(project_path)


def _extract_guardrail_gaps(project_path: Path) -> List[GuardrailGapSignal]:
    """Deterministically discovers missing CI/hooks and unwired lint/typecheck/test scripts."""
    if not project_path.exists() or not project_path.is_dir():
        return []
    _read_json_safe(project_path / ".edge" / "brigade.json")
    ci_files, hook_files = _collect_ci_and_hook_files(project_path)
    gaps: List[GuardrailGapSignal] = []
    if not ci_files and not hook_files:
        gaps.append(
            GuardrailGapSignal(
                gap_type="MISSING_GUARDRAIL",
                source_file=".github/workflows",
                script_or_check="ci_and_precommit",
                summary="No CI workflows (.github/workflows/*.yml|yaml) or pre-commit hooks (.husky/*, .git/hooks/pre-commit) configured",
            )
        )

    ci_and_hook_text = _read_concatenated_text(ci_files + hook_files)
    for source_file, check_name in _discover_repo_checks(project_path):
        if re.search(rf"\b{re.escape(check_name)}\b", ci_and_hook_text):
            continue
        gaps.append(
            GuardrailGapSignal(
                gap_type="UNWIRED_GUARDRAIL",
                source_file=source_file,
                script_or_check=check_name,
                summary=f"Check '{check_name}' defined in {source_file} is not wired into CI workflows or pre-commit hooks",
            )
        )
    return gaps


def _collect_rule_inventory_targets(project_path: Path) -> List[Tuple[Path, Optional[int]]]:
    has_agents_dir = (project_path / "agents").is_dir()
    agents_resolved = (project_path / "agents").resolve()
    targets = [
        (fpath, limit)
        for fpath, limit in collect_budget_targets(project_path)
        if not (fpath.resolve().parent == agents_resolved and not has_agents_dir)
    ]
    cs_path = project_path / "coding_standards.md"
    if cs_path.is_file():
        targets.append((cs_path.resolve(), None))
    return targets


def _build_session_citation_blobs(
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
) -> List[str]:
    blobs: List[str] = []
    for cid in analyzed_sessions:
        for step in sessions_steps.get(cid, []):
            parts = [str(step.get("content", ""))]
            parts.extend(json.dumps(tc.get("args", {}), default=str) for tc in step.get("tool_calls", []))
            blobs.append(" ".join(parts).replace("\\", "/"))
    return blobs


def _count_file_citations(rel_path: str, fname: str, file_text: str, blobs: List[str]) -> int:
    cand_ids = set(re.findall(r"\bCAND-[A-Za-z0-9]+\b", file_text))
    count = 0
    for blob in blobs:
        if rel_path in blob:
            count += blob.count(rel_path)
        elif fname in blob:
            count += blob.count(fname)
        count += sum(blob.count(cid) for cid in cand_ids if cid in blob)
    return count


def _compute_rule_status(line_count: int, budget_limit: Optional[int], citation_count: int) -> str:
    if budget_limit is not None and line_count > budget_limit:
        return "OVER_BUDGET"
    return "ZERO_CITATIONS" if citation_count == 0 else "OK"


def _extract_rule_inventory(
    project_path: Path,
    analyzed_sessions: List[str],
    sessions_steps: Dict[str, List[Dict[str, Any]]],
    mode: str = "project",
) -> List[RuleInventoryItem]:
    """Inventories station/agent rubrics and coding_standards.md with line budgets and session citations."""
    if not project_path.exists() or not project_path.is_dir():
        return []
    resolved_root = project_path.resolve()
    blobs = _build_session_citation_blobs(analyzed_sessions, sessions_steps)
    items: List[RuleInventoryItem] = []
    for fpath, limit in _collect_rule_inventory_targets(project_path):
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            rel_path = fpath.resolve().relative_to(resolved_root).as_posix()
        except Exception:
            continue
        line_count = len(text.splitlines())
        citations = _count_file_citations(rel_path, fpath.name, text, blobs)
        items.append(
            RuleInventoryItem(
                file_path=rel_path,
                line_count=line_count,
                budget_limit=limit,
                citation_count=citations,
                status=_compute_rule_status(line_count, limit, citations),
            )
        )
    return items
