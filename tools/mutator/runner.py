"""
Differential Core Mutation Runner, Recursive Scanner, TOON Reporter & Result Cache.
Executes test commands inside isolated overlays for discovered operator/SDL sites,
records killed/survived outcomes, and differentially caches results.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from .overlay import cleanup_worker_overlay, create_worker_overlay
from .sites import MutationSite, apply_mutation, discover_mutation_sites


_ALLOWED_CORE_PREFIXES = ("src/core/", "core/", "tools/")
_CORE_EXACT_DIRS = {"src/core", "core", "tools"}
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_REC_EXTENSIONS = {".ts", ".tsx", ".js", ".py"}
_REC_IGNORED_DIRS = {"tests", "__tests__", "node_modules", ".edge", "__pycache__", ".git", ".next", "dist", "build"}


@dataclass
class MutantOutcome:
    site: MutationSite
    status: str  # "KILLED" | "SURVIVED" | "TIMED_OUT"
    duration_sec: float = 0.0
    duration_ms: Optional[float] = None

    def __post_init__(self) -> None:
        if self.duration_ms is not None and self.duration_sec == 0.0:
            self.duration_sec = round(float(self.duration_ms) / 1000.0, 3)


@dataclass
class MutationSummary:
    total: int
    killed: int
    survived: int
    timed_out: int
    score_pct: float
    outcomes: List[MutantOutcome]
    file_path: str = ""
    mode: str = "all"
    passed: bool = True


@dataclass
class RecursiveMutationSummary:
    files_scanned: int
    total: int
    killed: int
    survived: int
    timed_out: int
    score_pct: float
    passed: bool
    file_summaries: List[MutationSummary]


def enforce_core_scope(rel_path: str, allow_non_core: bool = False) -> bool:
    """Ensures mutation testing only targets pure business logic unless allow_non_core=True."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    if any(norm.startswith(p) for p in _ALLOWED_CORE_PREFIXES) or norm in _CORE_EXACT_DIRS or allow_non_core:
        return True
    raise ValueError(
        f"Mutation testing restricted to core logic ({_ALLOWED_CORE_PREFIXES}). "
        f"Target '{rel_path}' is outside core scope. Pass allow_non_core=True to override."
    )


def _to_repo_rel_posix(repo: Path, target_path: Path) -> str:
    resolved = target_path if target_path.is_absolute() else (repo / target_path)
    try:
        return str(resolved.resolve().relative_to(repo.resolve())).replace("\\", "/")
    except ValueError:
        return resolved.name


def _all_file_lines(file_path: Path) -> Set[int]:
    if not file_path.is_file():
        return set()
    lines = file_path.read_bytes().splitlines()
    return set(range(1, len(lines) + 1))


def _parse_diff_hunks(diff_text: str) -> Set[int]:
    changed: Set[int] = set()
    for line in diff_text.splitlines():
        m = _DIFF_HUNK_RE.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = 1 if m.group(2) is None else int(m.group(2))
        if count > 0:
            changed.update(range(start, start + count))
    return changed


def _run_git_diff_cmd(repo: Path, args: List[str]) -> Tuple[int, str]:
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=15)
        return proc.returncode, proc.stdout
    except Exception:
        return 1, ""


def extract_git_diff_changed_lines(
    repo_root: Path,
    target_path: Path,
    base_ref: Optional[str] = None,
) -> Set[int]:
    """Extracts 1-based changed/added line numbers from git diff -U0 hunk headers (or all lines if untracked)."""
    repo = Path(repo_root).resolve()
    target = (Path(target_path) if Path(target_path).is_absolute() else (repo / target_path)).resolve()
    rel = _to_repo_rel_posix(repo, target)

    ls_rc, _ = _run_git_diff_cmd(repo, ["ls-files", "--error-unmatch", "--", rel])
    if ls_rc != 0:
        return _all_file_lines(target)

    if base_ref:
        rc, out = _run_git_diff_cmd(repo, ["diff", "-U0", base_ref, "--", rel])
        return _parse_diff_hunks(out) if rc == 0 else set()

    rc, out = _run_git_diff_cmd(repo, ["diff", "-U0", "HEAD", "--", rel])
    if rc != 0:
        _, out = _run_git_diff_cmd(repo, ["diff", "-U0", "--", rel])
    return _parse_diff_hunks(out)


def _is_recursive_candidate(path: Path, rel_posix: str) -> bool:
    if not path.is_file() or path.suffix not in _REC_EXTENSIONS:
        return False
    parts = set(path.parts)
    if parts & _REC_IGNORED_DIRS:
        return False
    name = path.name
    if name.startswith("test_") or "_test." in name or ".test." in name or ".spec." in name:
        return False
    return True


def _resolve_recursive_base(repo: Path, target_dir: Optional[Path], allow_non_core: bool) -> Path:
    if target_dir is not None:
        cand = (Path(target_dir) if Path(target_dir).is_absolute() else (repo / target_dir)).resolve()
        rel = _to_repo_rel_posix(repo, cand)
        if cand != repo:
            enforce_core_scope(rel, allow_non_core=allow_non_core)
        return cand
    for sub in ("src/core", "core", "tools"):
        d = repo / sub
        if d.is_dir():
            return d
    enforce_core_scope(".", allow_non_core=allow_non_core)
    return repo


def _git_changed_rel_set(repo: Path, base_ref: Optional[str]) -> Set[str]:
    args = ["diff", "--name-only", base_ref] if base_ref else ["diff", "--name-only", "HEAD"]
    rc, out = _run_git_diff_cmd(repo, args)
    if rc != 0 and not base_ref:
        _, out = _run_git_diff_cmd(repo, ["diff", "--name-only"])
    changed = {ln.strip().replace("\\", "/").lstrip("./") for ln in out.splitlines() if ln.strip()}
    _, untracked = _run_git_diff_cmd(repo, ["ls-files", "--others", "--exclude-standard"])
    changed.update(ln.strip().replace("\\", "/").lstrip("./") for ln in untracked.splitlines() if ln.strip())
    return changed


def discover_recursive_targets(
    repo_root: Path,
    target_dir: Optional[Path] = None,
    diff_only: bool = False,
    base_ref: Optional[str] = None,
    allow_non_core: bool = False,
) -> List[Path]:
    """Walks target_dir (or src/core) returning non-test source files, optionally filtered to git diff."""
    repo = Path(repo_root).resolve()
    base = _resolve_recursive_base(repo, target_dir, allow_non_core)
    if not base.is_dir():
        return []
    diff_set = _git_changed_rel_set(repo, base_ref) if diff_only else None
    targets: List[Path] = []
    for p in sorted(base.rglob("*")):
        rel = _to_repo_rel_posix(repo, p)
        if not _is_recursive_candidate(p, rel):
            continue
        if diff_set is not None and rel not in diff_set:
            continue
        targets.append(p)
    return targets


def _load_mutator_cache(cache_file: Path) -> Dict[str, Any]:
    if not cache_file.exists():
        return {}
    try:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_mutator_cache(metrics_dir: Path, cache_file: Path, cache: Dict[str, Any]) -> None:
    try:
        tmp_cache = metrics_dir / f"mutator.json.tmp.{os.getpid()}"
        tmp_cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        tmp_cache.replace(cache_file)
    except Exception:
        pass


def _execute_single_mutant(
    repo: Path,
    rel_path: str,
    orig_bytes: bytes,
    site: MutationSite,
    test_cmd: List[str],
    timeout_sec: float,
) -> MutantOutcome:
    mutated_bytes = apply_mutation(orig_bytes, site)
    overlay = create_worker_overlay(repo, rel_path, mutated_bytes)
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
    repo: Path,
    target: Path,
    diff_only: bool,
    base_ref: Optional[str],
    covered_lines: Optional[Set[int]],
) -> Optional[Set[int]]:
    if not diff_only:
        return covered_lines
    diff_lines = extract_git_diff_changed_lines(repo, target, base_ref=base_ref)
    return (covered_lines & diff_lines) if covered_lines is not None else diff_lines


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

    orig_bytes = target.read_bytes()
    target_sha = hashlib.sha256(orig_bytes).hexdigest()
    metrics_dir = repo / ".edge" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    cache_file = metrics_dir / "mutator.json"
    cache = _load_mutator_cache(cache_file)
    file_cache = cache.get(rel_path, {})

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
        outcomes=outcomes,
        file_path=rel_path,
        mode=mode,
        passed=(score_pct >= threshold),
    )


def run_mutation_suite(
    repo_root: Union[Path, str],
    target_file: Union[Path, str],
    test_cmd: List[str],
    timeout_sec: float = 15.0,
    allow_non_core: bool = False,
) -> MutationSummary:
    """Backward-compatible wrapper delegating to run_mutations."""
    return run_mutations(repo_root, target_file, test_cmd, timeout_sec=timeout_sec, allow_non_core=allow_non_core)


def run_recursive_mutations(
    repo_root: Union[Path, str],
    test_cmd: List[str],
    target_dir: Optional[Path] = None,
    timeout_sec: float = 15.0,
    allow_non_core: bool = False,
    mode: str = "all",
    diff_only: bool = False,
    base_ref: Optional[str] = None,
    threshold: float = 80.0,
) -> RecursiveMutationSummary:
    """Executes run_mutations across all discovered core files and aggregates totals."""
    repo = Path(repo_root).resolve()
    targets = discover_recursive_targets(repo, target_dir=target_dir, diff_only=diff_only, base_ref=base_ref, allow_non_core=allow_non_core)
    summaries = [
        run_mutations(
            repo,
            tf,
            test_cmd,
            timeout_sec=timeout_sec,
            allow_non_core=allow_non_core,
            mode=mode,
            diff_only=diff_only,
            base_ref=base_ref,
            threshold=threshold,
        )
        for tf in targets
    ]
    total = sum(s.total for s in summaries)
    killed = sum(s.killed for s in summaries)
    survived = sum(s.survived for s in summaries)
    timed_out = sum(s.timed_out for s in summaries)
    score_pct = round(killed / total * 100.0, 1) if total > 0 else 100.0
    return RecursiveMutationSummary(
        files_scanned=len(summaries),
        total=total,
        killed=killed,
        survived=survived,
        timed_out=timed_out,
        score_pct=score_pct,
        passed=(score_pct >= threshold),
        file_summaries=summaries,
    )


def _clip_inline(text: str, limit: int = 60) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else (flat[: limit - 3] + "...")


def _collect_all_outcomes(summary: Union[MutationSummary, RecursiveMutationSummary]) -> List[MutantOutcome]:
    if isinstance(summary, RecursiveMutationSummary):
        items: List[MutantOutcome] = []
        for fs in summary.file_summaries:
            items.extend(fs.outcomes)
        return items
    return summary.outcomes


def _format_mutator_toon(summary: Union[MutationSummary, RecursiveMutationSummary], mode: str) -> str:
    is_rec = isinstance(summary, RecursiveMutationSummary)
    target_label = f"{summary.files_scanned}_files" if is_rec else (summary.file_path or "target")
    eff_mode = mode if is_rec else (summary.mode or mode)
    header = (
        f"mutator[{summary.total}]"
        f"{{target:{target_label},mode:{eff_mode},killed:{summary.killed},"
        f"survived:{summary.survived},timed_out:{summary.timed_out},"
        f"score_pct:{summary.score_pct},passed:{str(summary.passed).lower()}}}:"
    )
    cols = "  file:line | op | original | mutated | status" if is_rec else "  line | op | original | mutated | status"
    lines = [header, cols]
    for o in _collect_all_outcomes(summary):
        loc = f"{o.site.file_path}:{o.site.line}" if is_rec else str(o.site.line)
        lines.append(f"  {loc} | {o.site.category} | {_clip_inline(o.site.original)} | {_clip_inline(o.site.mutant)} | {o.status}")
    return "\n".join(lines)


def _format_mutator_human(summary: Union[MutationSummary, RecursiveMutationSummary]) -> str:
    target_label = f"{summary.files_scanned} file(s)" if isinstance(summary, RecursiveMutationSummary) else (summary.file_path or "target")
    lines = [
        "=" * 70,
        "🧬  EDGE MUTATOR REPORT",
        f"   Target: {target_label}",
        f"   Total Mutants: {summary.total} | Killed: {summary.killed} | Survived: {summary.survived} | Timed Out: {summary.timed_out}",
        f"   Mutation Score: {summary.score_pct:.1f}%",
        "=" * 70,
    ]
    for o in _collect_all_outcomes(summary):
        icon = "✔" if o.status == "KILLED" else "✖"
        lines.append(
            f"   {icon} [{o.status:9s}] {o.site.file_path}:{o.site.line}: "
            f"{_clip_inline(o.site.original, 40)} -> {_clip_inline(o.site.mutant, 40)}"
        )
    return "\n".join(lines)


def format_mutation_report(
    summary: Union[MutationSummary, RecursiveMutationSummary],
    fmt: str = "toon",
    mode: str = "all",
) -> str:
    """Formats MutationSummary or RecursiveMutationSummary as 'toon' (default), 'json', or 'human'."""
    style = (fmt or "toon").strip().lower()
    if style == "json":
        return json.dumps(asdict(summary), indent=2, ensure_ascii=False)
    if style == "human":
        return _format_mutator_human(summary)
    return _format_mutator_toon(summary, mode)
