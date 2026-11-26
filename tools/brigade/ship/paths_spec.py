"""Ship-prep submodule: paths_spec."""

from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.tasks_bridge import resolve_target_repo_root
from tools.brigade.ship.paths import _clean_slug, _norm_rel_path

def _is_critique_spec(path_str: str) -> bool:
    low = path_str.strip().lower()
    return "critique" in Path(low).name


def _spec_slug_from_rel(spec_rel: str) -> str:
    norm = _norm_rel_path(spec_rel)
    stem = Path(norm).stem
    if norm.startswith(".edge/cache/issues/") and stem.isdigit():
        return f"issue-{stem}"
    return _clean_slug(stem)


def _resolve_spec_file_path(repo: Path, spec_rel: str) -> Path:
    direct = repo / spec_rel
    if direct.is_file():
        return direct
    if _norm_rel_path(spec_rel).startswith(".edge/cache/issues/"):
        primary_cand = resolve_target_repo_root(repo) / spec_rel
        if primary_cand.is_file():
            return primary_cand
    return direct


def _is_valid_spec_candidate(path_str: str) -> bool:
    norm = _norm_rel_path(path_str)
    low = norm.lower()
    if not low.endswith(".md") or _is_critique_spec(low) or low.endswith("index.md"):
        return False
    return norm.startswith((".edge/specs/", ".edge/archive/specs/", ".edge/cache/issues/", "specs/"))


def _resolve_spec_on_disk(repo: Path, raw_path: str) -> Optional[str]:
    norm = _norm_rel_path(raw_path)
    if norm.startswith(".edge/cache/issues/"):
        if (repo / norm).is_file() or (resolve_target_repo_root(repo) / norm).is_file():
            return norm
        return None
    name = Path(norm).name
    arch = repo / ".edge" / "archive" / "specs" / name
    if arch.is_file():
        return f".edge/archive/specs/{name}"
    active = repo / ".edge" / "specs" / name
    if active.is_file():
        return f".edge/specs/{name}"
    direct = repo / norm
    if direct.is_file():
        return norm
    return None


def _is_broad_path(pat: str, repo: Optional[Path] = None) -> bool:
    norm = _norm_rel_path(pat)
    if norm.endswith(("/", "/*", "/**")) or "/**" in norm:
        return True
    name = Path(norm).name
    if name in ("*", "**"):
        return True
    if "*" not in norm and "." not in name:
        return not (repo is not None and (repo / norm).is_file())
    return False


def _is_meta_spec_or_index(path_str: str, spec_path: str) -> bool:
    norm = _norm_rel_path(path_str)
    if norm == _norm_rel_path(spec_path) or norm == "specs/INDEX.md":
        return True
    return norm.startswith((".edge/specs/", ".edge/archive/specs/"))


def _matches_any_expected(path_str: str, expected_files: List[str]) -> bool:
    norm = _norm_rel_path(path_str)
    return any(fnmatch(norm, pat) or norm == pat for pat in expected_files)
