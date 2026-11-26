"""
TypeScript/JavaScript regex fallback operator and SDL site discovery.
"""

import re
from typing import List, Optional, Set

from tools.mutator.sites_models import (
    MUTATION_MAP,
    MutationSite,
    _compute_line_offsets,
    _dedupe_and_sort_sites,
)

_TS_ORDERED_OPS = ("===", "!==", ">=", "<=", "&&", "||", "??", "==", "!=", "+", "-", "*", "/", ">", "<")
_TS_BOOL_RE = re.compile(r"\b(true|false)\b")
_TS_MASK_RE = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`")
_TS_FN_DECL_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
_TS_ARROW_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\(|[A-Za-z_$])")
_TS_SKIP_PREFIXES = ("//", "/*", "*", "*/", "import ", "export type ", "export interface ", "interface ", "type ")
_TS_PURE_BRACES = {"{", "}", "});", "};", ");", "],", "];"}
_TS_GUARD_IF_RE = re.compile(r"^if\s*\([^)]*\)\s*(?:return|throw)\b.*;$")
_TS_THROW_RE = re.compile(r"^throw\s+.+;$")
_TS_VALIDATOR_CALL_RE = re.compile(r"^(?:await\s+)?(?:assert|require|validate|check)[A-Za-z0-9_]*\([^;]*\);$")
_TS_SIDE_EFFECT_RE = re.compile(r"^(?:await\s+)?[A-Za-z_$][A-Za-z0-9_$.]*\([^;]*\);$")
_TS_REASSIGN_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.]*\s*[+\-*/]?=\s*[^=].*;$")
_TS_NON_SDL_PREFIXES = (
    "const ", "let ", "var ", "return ", "export ", "type ", "interface ",
    "if ", "if(", "else", "for ", "for(", "while ", "while(", "switch ", "case ", "try", "catch", "finally",
)


def _mask_match_bytes(match: re.Match[str]) -> str:
    return "".join(ch if ch in ("\n", "\r") else " " for ch in match.group(0))


def _mask_ts_comments_and_strings(source_bytes: bytes) -> bytes:
    masked = _TS_MASK_RE.sub(_mask_match_bytes, source_bytes.decode("utf-8", errors="replace"))
    return masked.encode("utf-8")


def _update_ts_fn_name(line_text: str, current_fn: str) -> str:
    m_decl = _TS_FN_DECL_RE.search(line_text)
    if m_decl:
        return m_decl.group(1)
    m_arrow = _TS_ARROW_RE.search(line_text)
    return m_arrow.group(1) if m_arrow else current_fn


def _is_ts_skippable_line(stripped: str) -> bool:
    return (not stripped or stripped in _TS_PURE_BRACES or stripped.startswith(_TS_SKIP_PREFIXES) or bool(re.match(r"^export\s+\{", stripped)))


def _is_ts_sdl_candidate(stripped: str) -> bool:
    if _TS_GUARD_IF_RE.match(stripped) or _TS_THROW_RE.match(stripped) or _TS_VALIDATOR_CALL_RE.match(stripped):
        return True
    if stripped.startswith(_TS_NON_SDL_PREFIXES):
        return False
    return bool(_TS_SIDE_EFFECT_RE.match(stripped) or _TS_REASSIGN_RE.match(stripped))


def _make_line_sdl_site(
    line_bytes: bytes, line_start: int, line_num: int, rel_path: str, fn_name: str, replacement: str
) -> Optional[MutationSite]:
    text = line_bytes.rstrip(b"\r\n").decode("utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        return None
    leading = text[: len(text) - len(text.lstrip())]
    start_b = line_start + len(leading.encode("utf-8"))
    end_b = start_b + len(stripped.encode("utf-8"))
    return MutationSite(rel_path, fn_name, line_num, start_b, end_b, stripped, replacement, "SDL", "sdl")


def _discover_ts_sdl_sites(
    source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    lines, starts = _compute_line_offsets(source_bytes)
    sites: List[MutationSite] = []
    fn_name = "top_level"
    for idx, line_bytes in enumerate(lines, start=1):
        stripped = line_bytes.decode("utf-8", errors="replace").strip()
        fn_name = _update_ts_fn_name(stripped, fn_name)
        if (covered_lines is not None and idx not in covered_lines) or _is_ts_skippable_line(stripped) or not _is_ts_sdl_candidate(stripped):
            continue
        site = _make_line_sdl_site(line_bytes, starts[idx - 1], idx, rel_path, fn_name, "/* [SDL-DELETED] */")
        if site is not None:
            sites.append(site)
    return sites


def _is_non_operator_angle(line_str: str, pos: int, op: str) -> bool:
    if op == ">" and pos > 0 and line_str[pos - 1] in ("=", "/"):
        return True
    if op == "<" and pos + 1 < len(line_str):
        nxt = line_str[pos + 1]
        return nxt == "/" or nxt.isalpha() or nxt == "_"
    return False


def _scan_ts_line_operators(
    masked_line: str, line_start: int, line_num: int, rel_path: str, fn_name: str
) -> List[MutationSite]:
    sites: List[MutationSite] = []
    claimed: Set[int] = set()
    for op in _TS_ORDERED_OPS:
        start = 0
        while (pos := masked_line.find(op, start)) >= 0:
            start = pos + len(op)
            if any(p in claimed for p in range(pos, pos + len(op))) or _is_non_operator_angle(masked_line, pos, op):
                continue
            claimed.update(range(pos, pos + len(op)))
            mutant, cat = MUTATION_MAP[op]
            b_start = line_start + len(masked_line[:pos].encode("utf-8"))
            sites.append(MutationSite(rel_path, fn_name, line_num, b_start, b_start + len(op), op, mutant, cat, "operators"))
    for bm in _TS_BOOL_RE.finditer(masked_line):
        tok = bm.group(1)
        mutant, cat = MUTATION_MAP[tok]
        b_start = line_start + len(masked_line[: bm.start(1)].encode("utf-8"))
        sites.append(MutationSite(rel_path, fn_name, line_num, b_start, b_start + len(tok), tok, mutant, cat, "operators"))
    return sites


def _discover_ts_operator_fallback(
    source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    masked_lines, starts = _compute_line_offsets(_mask_ts_comments_and_strings(source_bytes))
    sites: List[MutationSite] = []
    fn_name = "top_level"
    for idx, m_bytes in enumerate(masked_lines, start=1):
        line_str = m_bytes.rstrip(b"\r\n").decode("utf-8", errors="replace")
        stripped = line_str.strip()
        fn_name = _update_ts_fn_name(stripped, fn_name)
        if (covered_lines is not None and idx not in covered_lines) or _is_ts_skippable_line(stripped):
            continue
        sites.extend(_scan_ts_line_operators(line_str, starts[idx - 1], idx, rel_path, fn_name))
    return sites


def _discover_with_regex_fallback(
    source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]] = None, mode: str = "all"
) -> List[MutationSite]:
    """Zero-dependency TS/JS regex/line scanner used when tree-sitter is unavailable."""
    sites: List[MutationSite] = []
    if mode in ("all", "operators"):
        sites.extend(_discover_ts_operator_fallback(source_bytes, rel_path, covered_lines))
    if mode in ("all", "sdl"):
        sites.extend(_discover_ts_sdl_sites(source_bytes, rel_path, covered_lines))
    return _dedupe_and_sort_sites(sites)
