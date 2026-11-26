"""
Git diff line extraction, core scope enforcement, and recursive target discovery for Edge Mutator.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_ALLOWED_CORE_PREFIXES = ("src/core/", "core/", "tools/")
_CORE_EXACT_DIRS = {"src/core", "core", "tools"}
_DIFF_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_REC_EXTENSIONS = {".ts", ".tsx", ".js", ".py"}
_REC_IGNORED_DIRS = {"tests", "__tests__", "node_modules", ".edge", "__pycache__", ".git", ".next", "dist", "build"}


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
    return set(range(1, len(file_path.read_bytes().splitlines()) + 1)) if file_path.is_file() else set()


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


def extract_git_diff_changed_lines(repo_root: Path, target_path: Path, base_ref: Optional[str] = None) -> Set[int]:
    """Extracts 1-based changed/added line numbers from git diff -U0 hunk headers."""
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


def _is_recursive_candidate(path: Path) -> bool:
    if not path.is_file() or path.suffix not in _REC_EXTENSIONS or (set(path.parts) & _REC_IGNORED_DIRS):
        return False
    name = path.name
    return not (name.startswith("test_") or "_test." in name or ".test." in name or ".spec." in name)


def _resolve_recursive_base(repo: Path, target_dir: Optional[Path], allow_non_core: bool) -> Path:
    if target_dir is not None:
        cand = (Path(target_dir) if Path(target_dir).is_absolute() else (repo / target_dir)).resolve()
        if cand != repo:
            enforce_core_scope(_to_repo_rel_posix(repo, cand), allow_non_core=allow_non_core)
        return cand
    for sub in ("src/core", "core", "tools"):
        if (d := repo / sub).is_dir():
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
    repo_root: Path, target_dir: Optional[Path] = None, diff_only: bool = False, base_ref: Optional[str] = None, allow_non_core: bool = False
) -> List[Path]:
    """Walks target_dir returning non-test source files, optionally filtered to git diff."""
    repo = Path(repo_root).resolve()
    base = _resolve_recursive_base(repo, target_dir, allow_non_core)
    if not base.is_dir():
        return []
    diff_set = _git_changed_rel_set(repo, base_ref) if diff_only else None
    return [
        p for p in sorted(base.rglob("*"))
        if _is_recursive_candidate(p) and (diff_set is None or _to_repo_rel_posix(repo, p) in diff_set)
    ]


def _load_mutator_cache(cache_file: Path) -> Dict[str, Any]:
    try:
        return json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.exists() else {}
    except Exception:
        return {}


def _save_mutator_cache(metrics_dir: Path, cache_file: Path, cache: Dict[str, Any]) -> None:
    try:
        tmp_cache = metrics_dir / f"mutator.json.tmp.{os.getpid()}"
        tmp_cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        tmp_cache.replace(cache_file)
    except Exception:
        pass
