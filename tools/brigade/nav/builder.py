"""Navigation submodule: builder."""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from tools.brigade.nav.constants import NAV_HEADER
from tools.brigade.nav.links import _collect_target_tokens
from tools.brigade.nav.docs import _extract_glossary_rows, _extract_index_rows
from tools.brigade.nav.deeds import _extract_domain_deed_rows, _inventory_nav_docs
from tools.brigade.nav.migrations import _extract_repo_env_rows
from tools.brigade.nav.cochanges import _extract_git_cochanges

def _assemble_prioritized_lines(
    index_or_pointer: List[str],
    deed_rows: List[str],
    cochange_rows: List[str],
    glossary_rows: List[str],
    env_rows: Tuple[str, ...] = (),
    max_lines: int = 15,
) -> str:
    body_buckets = (index_or_pointer, deed_rows, list(env_rows), cochange_rows, glossary_rows)
    if not any(body_buckets):
        return ""
    lines: List[str] = [NAV_HEADER]
    for bucket in body_buckets:
        room = max_lines - len(lines)
        if room <= 0:
            break
        lines.extend(bucket[:room])
    return "\n".join(lines)


def build_navigation_context(
    repo_path: Optional[Path],
    target_paths: Optional[List[str]] = None,
    domain: str = "",
    spec_path: str = "",
) -> str:
    """
    Builds a bounded <=15-line navigation and domain context block from repository docs
    and git co-change history. Returns '' when repo is invalid or no signals exist.
    """
    if repo_path is None:
        return ""
    root = Path(repo_path)
    if not root.exists() or not root.is_dir():
        return ""

    rel_paths, tokens, dom_clean = _collect_target_tokens(root, target_paths, domain, spec_path)
    index_rows = _extract_index_rows(root, tokens, limit=5)
    deed_rows = _extract_domain_deed_rows(root, rel_paths, dom_clean, limit=3)
    glossary_rows = _extract_glossary_rows(root, tokens, limit=4)
    env_rows = _extract_repo_env_rows(root, limit=4)
    cochange_rows = _extract_git_cochanges(root, rel_paths, limit=5)

    index_or_pointer = list(index_rows)
    if not any((index_rows, deed_rows, glossary_rows, env_rows)):
        available = _inventory_nav_docs(root)
        if available:
            index_or_pointer = [f"Navigation docs available: {', '.join(available)}"]

    return _assemble_prioritized_lines(
        index_or_pointer, deed_rows, cochange_rows, glossary_rows, tuple(env_rows)
    )
