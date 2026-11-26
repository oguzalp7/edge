"""
Python SDL and tokenize fallback mutation site discovery helpers.
"""

import io
import re
import tokenize
from typing import List, Optional, Set, Tuple

from tools.mutator.sites_ast import _discover_treesitter_operators
from tools.mutator.sites_models import MUTATION_MAP, MutationSite, _compute_line_offsets
from tools.mutator.sites_ts import _make_line_sdl_site

_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_PY_GUARD_IF_RE = re.compile(r"^if\s+.+:\s*(?:return\b.*|raise\b.*)$")
_PY_RAISE_RE = re.compile(r"^raise\b.*$")
_PY_ASSERT_RE = re.compile(r"^assert\b.*$")
_PY_CALL_RE = re.compile(r"^(?:await\s+)?[A-Za-z_][A-Za-z0-9_.]*\(.*\)$")
_PY_SKIP_PREFIXES = ("#", "import ", "from ", "def ", "async def ", "class ", "@")


def _is_py_sdl_candidate(stripped: str) -> bool:
    if not stripped or stripped.startswith(_PY_SKIP_PREFIXES):
        return False
    if _PY_GUARD_IF_RE.match(stripped) or _PY_RAISE_RE.match(stripped) or _PY_ASSERT_RE.match(stripped):
        return True
    return False if stripped.startswith("return ") else bool(_PY_CALL_RE.match(stripped))


def _update_py_docstring_state(stripped: str, in_doc: Optional[str]) -> Tuple[Optional[str], bool]:
    for quote in (chr(34) * 3, chr(39) * 3):
        cnt = stripped.count(quote)
        if in_doc == quote:
            return (None if cnt % 2 == 1 else quote), True
        if in_doc is None and stripped.startswith(quote):
            return (quote if cnt % 2 == 1 else None), True
    return in_doc, in_doc is not None


def _discover_python_sdl_sites(
    source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    lines, starts = _compute_line_offsets(source_bytes)
    sites: List[MutationSite] = []
    fn_name = "py_func"
    in_doc: Optional[str] = None
    for idx, line_bytes in enumerate(lines, start=1):
        raw_text = line_bytes.decode("utf-8", errors="replace")
        stripped = raw_text.strip()
        if (m_def := _PY_DEF_RE.match(raw_text)):
            fn_name = m_def.group(1)
        in_doc, skip_doc = _update_py_docstring_state(stripped, in_doc)
        if skip_doc or (covered_lines is not None and idx not in covered_lines) or not _is_py_sdl_candidate(stripped):
            continue
        site = _make_line_sdl_site(line_bytes, starts[idx - 1], idx, rel_path, fn_name, "pass  # [SDL-DELETED]")
        if site is not None:
            sites.append(site)
    return sites


def _discover_python_sites_fallback(
    source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    lines, line_start_bytes = _compute_line_offsets(source_bytes)
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(source_bytes).readline))
    except Exception:
        return []
    sites: List[MutationSite] = []
    fn_name = "py_func"
    for i, t in enumerate(tokens):
        if t.string == "def" and i + 1 < len(tokens):
            fn_name = tokens[i + 1].string
        if t.string not in MUTATION_MAP:
            continue
        s_line, s_col = t.start
        if s_line != t.end[0] or (covered_lines is not None and s_line not in covered_lines):
            continue
        line_str = lines[s_line - 1].decode("utf-8", errors="replace")
        start_byte = line_start_bytes[s_line - 1] + len(line_str[:s_col].encode("utf-8"))
        tok_bytes = t.string.encode("utf-8")
        mutant, cat = MUTATION_MAP[t.string]
        sites.append(MutationSite(rel_path, fn_name, s_line, start_byte, start_byte + len(tok_bytes), t.string, mutant, cat, "operators"))
    return sites
