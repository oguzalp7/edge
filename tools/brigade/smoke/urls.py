"""Submodule: urls."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
import json

from tools.brigade.smoke.constants import _ASTRO_EXTS, _NEXT_EXTS
from tools.brigade.smoke.models import DiscoveredRoute
from tools.brigade.smoke.route_params import _normalize_route_path
from tools.brigade.smoke.discover import _discover_custom, _discover_index_routes, _discover_nextjs_app, _discover_page_files, _discover_sveltekit, _make_discovered_route

def _collect_visited_paths(repo_path: Path) -> List[str]:
    proofs_dir = repo_path / ".edge" / "qa" / "proofs"
    if not proofs_dir.is_dir():
        return []
    paths: List[str] = []
    for pf in sorted(proofs_dir.glob("*.json")):
        if pf.name.endswith("-visual.json"):
            continue
        _append_proof_visited_paths(pf, paths)
    return paths


def _append_proof_visited_paths(proof_file: Path, dest: List[str]) -> None:
    try:
        data = json.loads(proof_file.read_text(encoding="utf-8"))
    except Exception:
        return
    for raw_url in data.get("visited_urls") or []:
        parsed = urlparse(str(raw_url).strip())
        path = _normalize_route_path(parsed.path or "/")
        if path and path not in dest:
            dest.append(path)


def discover_project_routes(
    repo_path: Path,
    pattern: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
) -> List[DiscoveredRoute]:
    """Discovers routes across Next.js, SvelteKit, Astro, custom globs, and specs/INDEX.md."""
    repo = Path(repo_path)
    param_map = dict(params or {})
    visited_paths = _collect_visited_paths(repo)
    raw_entries: List[tuple[str, str, str]] = []
    raw_entries.extend(_discover_nextjs_app(repo))
    raw_entries.extend(_discover_page_files(repo, ("src/pages", "pages"), _NEXT_EXTS, "nextjs-pages"))
    raw_entries.extend(_discover_sveltekit(repo))
    raw_entries.extend(_discover_page_files(repo, ("src/pages",), _ASTRO_EXTS, "astro"))
    raw_entries.extend(_discover_custom(repo, pattern))
    raw_entries.extend(_discover_index_routes(repo))

    by_pattern: Dict[str, DiscoveredRoute] = {}
    for raw_pat, src, fw in raw_entries:
        norm_pat = _normalize_route_path(raw_pat)
        if norm_pat not in by_pattern:
            by_pattern[norm_pat] = _make_discovered_route(norm_pat, src, fw, param_map, visited_paths)
    return list(by_pattern.values())
