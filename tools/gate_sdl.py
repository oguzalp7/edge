"""Differential SDL mutation gate helpers for Edge Verification Gate."""

import json
from pathlib import Path
from typing import List, Optional, Tuple

from tools.gate_static import GateResult, is_excluded_non_prod_path

_SDL_CORE_SUFFIXES: Tuple[str, ...] = (".ts", ".tsx", ".js", ".py")


def filter_core_sdl_files(repo_path: Path, changed_files: List[str]) -> List[str]:
    """Filter changed files down to existing src/core/ production files."""
    core_files: List[str] = []
    for raw in changed_files:
        norm = raw.strip().replace("\\", "/").lstrip("./")
        if not norm.startswith("src/core/") or is_excluded_non_prod_path(norm):
            continue
        if norm.endswith(_SDL_CORE_SUFFIXES) and (repo_path / norm).is_file() and norm not in core_files:
            core_files.append(norm)
    return core_files


def resolve_sdl_test_cmd(repo_path: Path, test_cmd: Optional[List[str]]) -> List[str]:
    """Resolve default test runner command for differential SDL execution."""
    if test_cmd:
        return list(test_cmd)
    pkg_file = repo_path / "package.json"
    if pkg_file.is_file():
        try:
            scripts = json.loads(pkg_file.read_text(encoding="utf-8")).get("scripts") or {}
            if isinstance(scripts, dict) and "test:unit" in scripts:
                return ["npm", "run", "test:unit"]
        except Exception:
            pass
    return ["pytest"]


def run_static_sdl_scan(repo_path: Path, core_files: List[str], base_ref: Optional[str]) -> GateResult:
    """Run static SDL deletion-site discovery without executing mutations."""
    from tools.mutator.runner_git import extract_git_diff_changed_lines
    from tools.mutator.sites import discover_mutation_sites

    total_sites = 0
    details: List[str] = []
    for rel in core_files:
        target = repo_path / rel
        diff_lines = extract_git_diff_changed_lines(repo_path, target, base_ref=base_ref)
        sites = discover_mutation_sites(target, rel, covered_lines=diff_lines, mode="sdl") if diff_lines else []
        total_sites += len(sites)
        details.extend(f"{rel}:{s.line} [{s.op_category}] {s.original[:60]}" for s in sites[:3])
    msg = f"Static differential SDL scan found {total_sites} deletion site(s) across {len(core_files)} src/core/ file(s)."
    return GateResult(1, "Differential SDL Mutation Gate", True, msg, details[:10])


def run_exec_sdl_scan(repo_path: Path, core_files: List[str], base_ref: Optional[str], resolved_cmd: List[str]) -> GateResult:
    """Execute differential SDL mutation testing and enforce >= 80% score."""
    from tools.mutator.runner import run_mutations

    failed_files: List[str] = []
    details: List[str] = []
    for rel in core_files:
        summary = run_mutations(repo_path, repo_path / rel, resolved_cmd, mode="sdl", diff_only=True, base_ref=base_ref, threshold=80.0)
        if not summary.passed:
            failed_files.append(rel)
            details.extend(f"{rel}:{o.site.line} SURVIVED {o.site.original[:50]}" for o in summary.outcomes if o.status != "KILLED")
    if failed_files:
        return GateResult(1, "Differential SDL Mutation Gate", False, f"Differential SDL mutation score below 80% on {len(failed_files)} file(s).", details[:10])
    return GateResult(1, "Differential SDL Mutation Gate", True, f"Differential SDL mutation gate passed across {len(core_files)} src/core/ file(s).", details[:10])


def check_differential_mutation_gate(
    repo_path: Path, changed_files: List[str], skip_verify: bool = False, base_ref: Optional[str] = None, test_cmd: Optional[List[str]] = None
) -> GateResult:
    """Run static SDL discovery (skip_verify=True) or differential SDL mutation testing on src/core/ changes."""
    repo = Path(repo_path).resolve()
    core_files = filter_core_sdl_files(repo, changed_files)
    if not core_files:
        return GateResult(1, "Differential SDL Mutation Gate", True, "No src/core/ production files changed; differential SDL gate bypassed.")
    if skip_verify:
        return run_static_sdl_scan(repo, core_files, base_ref)
    return run_exec_sdl_scan(repo, core_files, base_ref, resolve_sdl_test_cmd(repo, test_cmd))
