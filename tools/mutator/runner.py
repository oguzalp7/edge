"""
Differential Core Mutation Runner and Result Cache.
Executes test commands inside isolated overlays for discovered mutation sites,
records killed/survived outcomes, and differentially caches results.
"""

import sys
import os
import time
import json
import hashlib
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional, Union

from .sites import MutationSite, discover_mutation_sites, apply_mutation
from .overlay import create_worker_overlay, cleanup_worker_overlay


@dataclass
class MutantOutcome:
    site: MutationSite
    status: str  # "KILLED" | "SURVIVED" | "TIMED_OUT"
    duration_sec: float


@dataclass
class MutationSummary:
    total: int
    killed: int
    survived: int
    timed_out: int
    score_pct: float
    outcomes: List[MutantOutcome]


def enforce_core_scope(rel_path: str, allow_non_core: bool = False) -> bool:
    """
    Ensures mutation testing only targets pure business logic:
    src/core/, core/, or tools/.
    Raises ValueError if non-core path is provided without allow_non_core=True.
    """
    norm = rel_path.replace("\\", "/").lstrip("./")
    allowed_prefixes = ("src/core/", "core/", "tools/")
    if any(norm.startswith(p) for p in allowed_prefixes) or allow_non_core:
        return True
    raise ValueError(
        f"Mutation testing restricted to core logic ({allowed_prefixes}). "
        f"Target '{rel_path}' is outside core scope. Pass allow_non_core=True to override."
    )


def run_mutation_suite(
    repo_root: Union[Path, str],
    target_file: Union[Path, str],
    test_cmd: List[str],
    timeout_sec: float = 15.0,
    allow_non_core: bool = False
) -> MutationSummary:
    """
    Runs mutation testing against target_file:
    1. Enforces core scope boundary.
    2. Discovers AST mutation sites.
    3. Leverages differential cache in .edge/metrics/mutator.json for previously killed mutants.
    4. Executes tests inside isolated worker overlays.
    5. Returns overall MutationSummary.
    """
    repo = Path(repo_root).resolve()
    target = Path(target_file).resolve()

    try:
        rel_path = str(target.relative_to(repo)).replace("\\", "/")
    except ValueError:
        rel_path = target.name

    enforce_core_scope(rel_path, allow_non_core=allow_non_core)

    # 1. Discover mutation sites
    sites = discover_mutation_sites(target, rel_path)
    if not sites:
        return MutationSummary(
            total=0,
            killed=0,
            survived=0,
            timed_out=0,
            score_pct=100.0,
            outcomes=[]
        )

    orig_bytes = target.read_bytes()
    target_sha = hashlib.sha256(orig_bytes).hexdigest()

    # 2. Load cache
    metrics_dir = repo / ".edge" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    cache_file = metrics_dir / "mutator.json"
    cache: Dict[str, Any] = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    file_cache = cache.get(rel_path, {})
    outcomes: List[MutantOutcome] = []

    # 3. Test each mutation site
    for site in sites:
        site_key = f"{site.function_name}:{site.line}:{site.start_byte}:{site.original}->{site.mutant}"
        cached_entry = file_cache.get(site_key)

        if cached_entry and cached_entry.get("status") == "KILLED" and cached_entry.get("sha") == target_sha:
            outcomes.append(MutantOutcome(
                site=site,
                status="KILLED",
                duration_sec=cached_entry.get("duration", 0.0)
            ))
            continue

        mutated_bytes = apply_mutation(orig_bytes, site)
        overlay = create_worker_overlay(repo, rel_path, mutated_bytes)

        t0 = time.time()
        try:
            res = subprocess.run(
                test_cmd,
                cwd=str(overlay),
                capture_output=True,
                text=True,
                timeout=timeout_sec
            )
            duration = round(time.time() - t0, 3)
            # A non-zero exit code means tests failed -> mutant was caught (KILLED)
            status = "KILLED" if res.returncode != 0 else "SURVIVED"
        except subprocess.TimeoutExpired:
            duration = timeout_sec
            status = "TIMED_OUT"
        finally:
            cleanup_worker_overlay(overlay)

        outcome = MutantOutcome(
            site=site,
            status=status,
            duration_sec=duration
        )
        outcomes.append(outcome)

        file_cache[site_key] = {
            "status": status,
            "sha": target_sha,
            "duration": duration,
            "category": site.category,
        }

    # 4. Save cache
    cache[rel_path] = file_cache
    try:
        tmp_cache = metrics_dir / f"mutator.json.tmp.{os.getpid()}"
        tmp_cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        tmp_cache.replace(cache_file)
    except Exception:
        pass

    # 5. Summarize
    total = len(outcomes)
    killed = sum(1 for o in outcomes if o.status == "KILLED")
    survived = sum(1 for o in outcomes if o.status == "SURVIVED")
    timed_out = sum(1 for o in outcomes if o.status == "TIMED_OUT")
    score_pct = round(killed / total * 100.0, 1) if total > 0 else 100.0

    return MutationSummary(
        total=total,
        killed=killed,
        survived=survived,
        timed_out=timed_out,
        score_pct=score_pct,
        outcomes=outcomes
    )
