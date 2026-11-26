"""Ship-prep submodule: spec_expected."""

from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.constants import _INLINE_PATH_RE, _REPO_PREFIXES, _TABLE_SEP_RE
from tools.brigade.ship.paths import _norm_rel_path
from tools.brigade.ship.spec_expected_sections import _extract_frontmatter_expected, _extract_section_expected

def _clean_path_candidate(raw: str) -> Optional[str]:
    cand = _norm_rel_path(raw.strip("`',\";: "))
    if cand.endswith(")") and cand.count(")") > cand.count("("):
        cand = cand[:-1]
    if not cand or " " in cand or "..." in cand:
        return None
    return cand if cand.startswith(_REPO_PREFIXES) else None


def _extract_table_paths(lines: List[str]) -> List[str]:
    """Scans all Markdown table rows and inline code spans for repo-prefixed file paths."""
    found: List[str] = []
    for raw in lines:
        s = raw.strip()
        if not s.startswith("|") or _TABLE_SEP_RE.match(s):
            continue
        spans = re.findall(r"`([^`]+)`", s)
        for tok in [*spans, *_INLINE_PATH_RE.findall(s)]:
            cand = _clean_path_candidate(tok)
            if cand and cand not in found:
                found.append(cand)
    return found


def _append_glob_matches(pat: str, norm_changed: List[str], expanded: List[str]) -> None:
    for cf in norm_changed:
        if fnmatch(cf, pat) and cf not in expanded:
            expanded.append(cf)


def _expand_expected_globs(patterns: List[str], changed_files: List[str]) -> List[str]:
    """Expands globbed spec patterns (e.g. 0017_*.sql) against changed files."""
    expanded: List[str] = []
    norm_changed = [_norm_rel_path(cf) for cf in changed_files]
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            _append_glob_matches(pat, norm_changed, expanded)
        elif pat not in expanded:
            expanded.append(pat)
    return expanded


def _extract_spec_expected_files(spec_file: Path) -> List[str]:
    if not spec_file.is_file():
        return []
    text = spec_file.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    found = [
        *_extract_frontmatter_expected(text),
        *_extract_section_expected(lines),
        *_extract_table_paths(lines),
    ]
    return list(dict.fromkeys(found))
