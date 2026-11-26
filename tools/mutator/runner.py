"""
Differential Core Mutation Runner, Recursive Scanner, TOON Reporter & Result Cache.
"""

import hashlib
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from .overlay import cleanup_worker_overlay, create_worker_overlay
from .runner_git import (
    _load_mutator_cache,
    _save_mutator_cache,
    _to_repo_rel_posix,
    discover_recursive_targets,
    enforce_core_scope,
    extract_git_diff_changed_lines,
)
from .runner_report import (
    MutantOutcome,
    MutationSummary,
    RecursiveMutationSummary,
    format_mutation_report,
)
from .sites import MutationSite, apply_mutation, discover_mutation_sites


def _execute_single_mutant(
    repo: Path, rel_path: str, orig_bytes: bytes, site: MutationSite, test_cmd: List[str], timeout_sec: float
) -> MutantOutcome:
    overlay = create_worker_overlay(repo, rel_path, apply_mutation(orig_bytes, site))
    t0 = time.time()
    try:
        res = subprocess.run(test_cmd, cwd=str(overlay), capture_output=True, text=True, timeout=timeout_sec)
        duration = round(time.time() - t0, 3)
        status = "KILLED" if res.returncode != 0 else "SURVIVED"
    except subprocess.TimeoutExpired:
        duration = timeout_sec
        status = "TIMED_OUT"
    finally:
        cleanup_worker_overlay(overlay)
    return MutantOutcome(site=site, status=status, duration_sec=duration)


def _resolve_effective_lines(
    repo: Path, target: Path, diff_only: bool, base_ref: Optional[str], covered_lines: Optional[Set[int]]
) -> Optional[Set[int]]:
    if not diff_only:
        return covered_lines
    diff_lines = extract_git_diff_changed_lines(repo, target, base_ref=base_ref)
    return (covered_lines & diff_lines) if covered_lines is not None else diff_lines


def _run_sites_with_cache(
    repo: Path, rel_path: str, orig_bytes: bytes, sites: List[MutationSite], test_cmd: List[str], timeout_sec: float
) -> List[MutantOutcome]:
    target_sha = hashlib.sha256(orig_bytes).hexdigest()
    metrics_dir = repo / ".edge" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    cache_file = metrics_dir / "mutator.json"
    cache = _load_mutator_cache(cache_file)
    file_cache: Dict[str, dict] = cache.get(rel_path, {})
    outcomes: List[MutantOutcome] = []
    for site in sites:
        site_key = f"{site.function_name}:{site.line}:{site.start_byte}:{site.op_category}:{site.original}->{site.mutant}"
        cached = file_cache.get(site_key)
        if cached and cached.get("status") == "KILLED" and cached.get("sha") == target_sha:
            outcomes.append(MutantOutcome(site=site, status="KILLED", duration_sec=cached.get("duration", 0.0)))
            continue
        outcome = _execute_single_mutant(repo, rel_path, orig_bytes, site, test_cmd, timeout_sec)
        outcomes.append(outcome)
        file_cache[site_key] = {"status": outcome.status, "sha": target_sha, "duration": outcome.duration_sec, "category": site.category}
    cache[rel_path] = file_cache
    _save_mutator_cache(metrics_dir, cache_file, cache)
    return outcomes


def run_mutations(
    repo_root: Union[Path, str],
    target_file: Union[Path, str],
    test_cmd: List[str],
    timeout_sec: float = 15.0,
    allow_non_core: bool = False,
    mode: str = "all",
    diff_only: bool = False,
    base_ref: Optional[str] = None,
    covered_lines: Optional[Set[int]] = None,
    threshold: float = 80.0,
) -> MutationSummary:
    """Runs differential operator/SDL mutation testing against target_file."""
    repo = Path(repo_root).resolve()
    target = (Path(target_file) if Path(target_file).is_absolute() else (repo / target_file)).resolve()
    rel_path = _to_repo_rel_posix(repo, target)
    enforce_core_scope(rel_path, allow_non_core=allow_non_core)
    eff_lines = _resolve_effective_lines(repo, target, diff_only, base_ref, covered_lines)
    if eff_lines is not None and not eff_lines:
        return MutationSummary(0, 0, 0, 0, 100.0, [], file_path=rel_path, mode=mode, passed=True)
    sites = discover_mutation_sites(target, rel_path, covered_lines=eff_lines, mode=mode)
    if not sites:
        return MutationSummary(0, 0, 0, 0, 100.0, [], file_path=rel_path, mode=mode, passed=True)

    outcomes = _run_sites_with_cache(repo, rel_path, target.read_bytes(), sites, test_cmd, timeout_sec)
    total = len(outcomes)
    killed = sum(1 for o in outcomes if o.status == "KILLED")
    survived = sum(1 for o in outcomes if o.status == "SURVIVED")
    timed_out = sum(1 for o in outcomes if o.status == "TIMED_OUT")
    score_pct = round(killed / total * 100.0, 1) if total > 0 else 100.0
    return MutationSummary(total, killed, survived, timed_out, score_pct, outcomes, file_path=rel_path, mode=mode, passed=(score_pct >= threshold))


def run_mutation_suite(
    repo_root: Union[Path, str], target_file: Union[Path, str], test_cmd: List[str], timeout_sec: float = 15.0, allow_non_core: bool = False
) -> MutationSummary:
    """Backward-compatible wrapper delegating to run_mutations."""
    return run_mutations(repo_root, target_file, test_cmd, timeout_sec=timeout_sec, allow_non_core=allow_non_core)


def run_recursive_mutations(
    repo_root: Union[Path, str], test_cmd: List[str], target_dir: Optional[Path] = None,
    timeout_sec: float = 15.0, allow_non_core: bool = False, mode: str = "all",
    diff_only: bool = False, base_ref: Optional[str] = None, threshold: float = 80.0,
) -> RecursiveMutationSummary:
    """Executes run_mutations across all discovered core files and aggregates totals."""
    repo = Path(repo_root).resolve()
    targets = discover_recursive_targets(repo, target_dir=target_dir, diff_only=diff_only, base_ref=base_ref, allow_non_core=allow_non_core)
    summaries = [
        run_mutations(repo, tf, test_cmd, timeout_sec=timeout_sec, allow_non_core=allow_non_core, mode=mode, diff_only=diff_only, base_ref=base_ref, threshold=threshold)
        for tf in targets
    ]
    total = sum(s.total for s in summaries)
    killed = sum(s.killed for s in summaries)
    survived = sum(s.survived for s in summaries)
    timed_out = sum(s.timed_out for s in summaries)
    score_pct = round(killed / total * 100.0, 1) if total > 0 else 100.0
    return RecursiveMutationSummary(len(summaries), total, killed, survived, timed_out, score_pct, (score_pct >= threshold), summaries)
