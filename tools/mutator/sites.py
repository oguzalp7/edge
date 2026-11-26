"""
Mutation Sites Discovery and Patching Engine.
Discovers AST/regex operator and Statement Deletion (SDL) mutation sites in
TypeScript/JavaScript/Python source files and applies byte-accurate UTF-8 replacements.
"""

from pathlib import Path
from typing import List, Optional, Set, Union

from tools.mutator.sites_models import (
    MUTATION_MAP,
    TREE_SITTER_AVAILABLE,
    VALID_MODES,
    MutationSite,
    _TS_EXTS,
    _dedupe_and_sort_sites,
    _get_parser_for_ext,
    apply_mutation,
)
from tools.mutator.sites_py import (
    _discover_python_sdl_sites,
    _discover_python_sites_fallback,
    _discover_treesitter_operators,
)
from tools.mutator.sites_ts import _discover_ts_sdl_sites, _discover_with_regex_fallback


def _discover_python_file_sites(
    source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]], mode: str
) -> List[MutationSite]:
    sites: List[MutationSite] = []
    if mode in ("all", "operators"):
        parser = _get_parser_for_ext(".py")
        if parser is not None:
            sites.extend(_discover_treesitter_operators(parser, source_bytes, rel_path, covered_lines))
        else:
            sites.extend(_discover_python_sites_fallback(source_bytes, rel_path, covered_lines))
    if mode in ("all", "sdl"):
        sites.extend(_discover_python_sdl_sites(source_bytes, rel_path, covered_lines))
    return _dedupe_and_sort_sites(sites)


def _discover_ts_file_sites(
    ext: str, source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]], mode: str
) -> List[MutationSite]:
    parser = _get_parser_for_ext(ext)
    if parser is None:
        return _discover_with_regex_fallback(source_bytes, rel_path, covered_lines=covered_lines, mode=mode)
    sites: List[MutationSite] = []
    if mode in ("all", "operators"):
        sites.extend(_discover_treesitter_operators(parser, source_bytes, rel_path, covered_lines))
    if mode in ("all", "sdl"):
        sites.extend(_discover_ts_sdl_sites(source_bytes, rel_path, covered_lines))
    return _dedupe_and_sort_sites(sites)


def discover_mutation_sites(
    file_path: Union[Path, str], rel_path: str = "", covered_lines: Optional[Set[int]] = None, mode: str = "all"
) -> List[MutationSite]:
    """Discovers operator and/or SDL mutation candidate sites in TS/JS/Python files."""
    if mode not in VALID_MODES:
        raise ValueError(f"Invalid mutation mode '{mode}'. Expected one of {VALID_MODES}.")
    p = Path(file_path)
    if not p.exists():
        return []
    try:
        source_bytes = p.read_bytes()
    except Exception:
        return []
    eff_rel = rel_path or p.name
    ext = p.suffix.lower()
    if ext == ".py":
        return _discover_python_file_sites(source_bytes, eff_rel, covered_lines, mode)
    return _discover_ts_file_sites(ext, source_bytes, eff_rel, covered_lines, mode) if ext in _TS_EXTS else []
