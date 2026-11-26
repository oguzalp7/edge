"""Submodule: discover."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from tools.brigade.smoke.constants import _INDEX_ROUTE_RE, _NEXT_EXTS, _SKIP_DIRS
from tools.brigade.smoke.models import DiscoveredRoute
from tools.brigade.smoke.route_params import _has_skipped_segment, _is_dynamic_route, _normalize_route_path, _requires_auth_route, _resolve_concrete_url, _strip_route_groups

def _make_discovered_route(
    route_pattern: str,
    source_file: str,
    framework: str,
    params: Dict[str, str],
    visited_paths: List[str],
) -> DiscoveredRoute:
    norm_pat = _normalize_route_path(route_pattern)
    concrete = _resolve_concrete_url(norm_pat, params, visited_paths)
    return DiscoveredRoute(
        route_pattern=norm_pat,
        concrete_url_path=concrete,
        source_file=source_file,
        framework=framework,
        is_dynamic=_is_dynamic_route(norm_pat),
        requires_auth=_requires_auth_route(norm_pat),
    )


def _discover_nextjs_app(repo_path: Path) -> List[tuple[str, str, str]]:
    found: List[tuple[str, str, str]] = []
    for root_rel in ("src/app", "app"):
        base = repo_path / root_rel
        if not base.is_dir():
            continue
        for fpath in sorted(base.rglob("page.*")):
            if fpath.suffix not in _NEXT_EXTS or not fpath.is_file():
                continue
            parts = fpath.relative_to(base).parts[:-1]
            if _has_skipped_segment(parts):
                continue
            segs = _strip_route_groups(parts)
            pat = "/" + "/".join(segs) if segs else "/"
            found.append((pat, fpath.relative_to(repo_path).as_posix(), "nextjs-app"))
    return found


def _discover_page_files(
    repo_path: Path,
    roots: tuple[str, ...],
    exts: tuple[str, ...],
    framework: str,
) -> List[tuple[str, str, str]]:
    found: List[tuple[str, str, str]] = []
    for root_rel in roots:
        base = repo_path / root_rel
        if not base.is_dir():
            continue
        for fpath in sorted(base.rglob("*")):
            if not fpath.is_file() or fpath.suffix not in exts:
                continue
            rel_parts = fpath.relative_to(base).parts
            if _has_skipped_segment(rel_parts):
                continue
            stem = fpath.stem
            dirs = list(rel_parts[:-1])
            segs = dirs if stem == "index" else [*dirs, stem]
            pat = "/" + "/".join(segs) if segs else "/"
            found.append((pat, fpath.relative_to(repo_path).as_posix(), framework))
    return found


def _discover_sveltekit(repo_path: Path) -> List[tuple[str, str, str]]:
    base = repo_path / "src" / "routes"
    if not base.is_dir():
        return []
    found: List[tuple[str, str, str]] = []
    for fpath in sorted(base.rglob("+page.svelte")):
        if not fpath.is_file():
            continue
        parts = fpath.relative_to(base).parts[:-1]
        if _has_skipped_segment(parts):
            continue
        segs = _strip_route_groups(parts)
        pat = "/" + "/".join(segs) if segs else "/"
        found.append((pat, fpath.relative_to(repo_path).as_posix(), "sveltekit"))
    return found


def _file_to_custom_route(rel_parts: tuple[str, ...], stem: str) -> str:
    trimmed = list(rel_parts)
    for prefix in (("src", "app"), ("src", "routes"), ("src", "pages"), ("app",), ("pages",)):
        if tuple(trimmed[: len(prefix)]) == prefix:
            trimmed = trimmed[len(prefix) :]
            break
    dirs = _strip_route_groups(tuple(trimmed[:-1]))
    segs = dirs if stem in ("page", "+page", "index") else [*dirs, stem]
    return "/" + "/".join(segs) if segs else "/"


def _discover_custom(repo_path: Path, pattern: Optional[str]) -> List[tuple[str, str, str]]:
    if not pattern:
        return []
    found: List[tuple[str, str, str]] = []
    for fpath in sorted(repo_path.glob(pattern)):
        if not fpath.is_file():
            continue
        rel = fpath.relative_to(repo_path)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        pat = _file_to_custom_route(rel.parts, fpath.stem)
        found.append((pat, rel.as_posix(), "custom"))
    return found


def _discover_index_routes(repo_path: Path) -> List[tuple[str, str, str]]:
    index_file = repo_path / "specs" / "INDEX.md"
    if not index_file.is_file():
        return []
    found: List[tuple[str, str, str]] = []
    text = index_file.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        match = _INDEX_ROUTE_RE.search(line)
        if match:
            found.append((match.group(1).strip(), "specs/INDEX.md", "index"))
    return found
