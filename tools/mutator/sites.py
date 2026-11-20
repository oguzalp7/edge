"""
Mutation Sites Discovery and Patching Engine.
Discovers AST/regex operator and Statement Deletion (SDL) mutation sites in
TypeScript/JavaScript/Python source files and applies byte-accurate UTF-8 replacements.
"""

from dataclasses import dataclass
import io
from pathlib import Path
import re
import tokenize
from typing import Any, List, Optional, Set, Tuple, Union

try:
    import tree_sitter  # noqa: F401
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


VALID_MODES = ("all", "sdl", "operators")
_TS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

MUTATION_MAP = {
    "+": ("-", "Arithmetic"),
    "-": ("+", "Arithmetic"),
    "*": ("/", "Multiplicative"),
    "/": ("*", "Multiplicative"),
    ">": (">=", "Relational"),
    ">=": (">", "Relational"),
    "<": ("<=", "Relational"),
    "<=": ("<", "Relational"),
    "===": ("!==", "Equality"),
    "!==": ("===", "Equality"),
    "==": ("!=", "Equality"),
    "!=": ("==", "Equality"),
    "&&": ("||", "Logical"),
    "||": ("&&", "Logical"),
    "and": ("or", "Logical"),
    "or": ("and", "Logical"),
    "??": ("||", "Nullish"),
    "true": ("false", "Boolean"),
    "false": ("true", "Boolean"),
    "True": ("False", "Boolean"),
    "False": ("True", "Boolean"),
}

_TS_ORDERED_OPS: Tuple[str, ...] = (
    "===", "!==", ">=", "<=", "&&", "||", "??", "==", "!=", "+", "-", "*", "/", ">", "<"
)
_TS_BOOL_RE = re.compile(r"\b(true|false)\b")
_TS_MASK_RE = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`"
)
_TS_FN_DECL_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")
_TS_ARROW_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:\(|[A-Za-z_$])")
_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")

_TS_SKIP_PREFIXES = (
    "//", "/*", "*", "*/", "import ", "export type ", "export interface ", "interface ", "type ",
)
_TS_PURE_BRACES = {"{", "}", "});", "};", ");", "});", "],", "];"}
_TS_GUARD_IF_RE = re.compile(r"^if\s*\([^)]*\)\s*(?:return|throw)\b.*;$")
_TS_THROW_RE = re.compile(r"^throw\s+.+;$")
_TS_VALIDATOR_CALL_RE = re.compile(r"^(?:await\s+)?(?:assert|require|validate|check)[A-Za-z0-9_]*\([^;]*\);$")
_TS_SIDE_EFFECT_RE = re.compile(r"^(?:await\s+)?[A-Za-z_$][A-Za-z0-9_$.]*\([^;]*\);$")
_TS_REASSIGN_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$.]*\s*[+\-*/]?=\s*[^=].*;$")
_TS_NON_SDL_PREFIXES = (
    "const ", "let ", "var ", "return ", "export ", "type ", "interface ",
    "if ", "if(", "else", "for ", "for(", "while ", "while(", "switch ", "case ", "try", "catch", "finally",
)

_PY_GUARD_IF_RE = re.compile(r"^if\s+.+:\s*(?:return\b.*|raise\b.*)$")
_PY_RAISE_RE = re.compile(r"^raise\b.*$")
_PY_ASSERT_RE = re.compile(r"^assert\b.*$")
_PY_CALL_RE = re.compile(r"^(?:await\s+)?[A-Za-z_][A-Za-z0-9_.]*\(.*\)$")
_PY_SKIP_PREFIXES = ("#", "import ", "from ", "def ", "async def ", "class ", "@")


@dataclass(frozen=True)
class MutationSite:
    file_path: str
    function_name: str
    line: int
    start_byte: int
    end_byte: int
    original: str
    mutant: str
    category: str
    op_category: str = "operators"


def apply_mutation(source_bytes: bytes, site: MutationSite) -> bytes:
    """Replaces exact byte range [start_byte:end_byte] with site.mutant."""
    mutant_bytes = site.mutant.encode("utf-8")
    return source_bytes[:site.start_byte] + mutant_bytes + source_bytes[site.end_byte:]


def _get_parser_for_ext(ext: str) -> Any:
    if not TREE_SITTER_AVAILABLE:
        return None
    low = ext.lower()
    if low == ".ts":
        return tslp.get_parser("typescript")
    if low in (".tsx", ".jsx"):
        return tslp.get_parser("tsx")
    if low in (".js", ".mjs", ".cjs"):
        return tslp.get_parser("javascript")
    if low == ".py":
        return tslp.get_parser("python")
    return None


def _compute_line_offsets(source_bytes: bytes) -> Tuple[List[bytes], List[int]]:
    lines = source_bytes.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))
    return lines, starts


def _mask_match_bytes(match: re.Match[str]) -> str:
    out: List[str] = []
    for ch in match.group(0):
        if ch == "\n":
            out.append("\n")
        else:
            out.extend(" " * len(ch.encode("utf-8")))
    return "".join(out)


def _mask_ts_comments_and_strings(source_bytes: bytes) -> bytes:
    text = source_bytes.decode("utf-8", errors="replace")
    masked = _TS_MASK_RE.sub(_mask_match_bytes, text)
    return masked.encode("utf-8", errors="replace")


def _update_ts_fn_name(line_text: str, current_fn: str) -> str:
    m_decl = _TS_FN_DECL_RE.search(line_text)
    if m_decl:
        return m_decl.group(1)
    m_arrow = _TS_ARROW_RE.search(line_text)
    if m_arrow:
        return m_arrow.group(1)
    return current_fn


def _is_ts_skippable_line(stripped: str) -> bool:
    if not stripped or stripped in _TS_PURE_BRACES:
        return True
    return stripped.startswith(_TS_SKIP_PREFIXES) or bool(re.match(r"^export\s+\{", stripped))


def _is_ts_sdl_candidate(stripped: str) -> bool:
    if _TS_GUARD_IF_RE.match(stripped) or _TS_THROW_RE.match(stripped) or _TS_VALIDATOR_CALL_RE.match(stripped):
        return True
    if stripped.startswith(_TS_NON_SDL_PREFIXES):
        return False
    return bool(_TS_SIDE_EFFECT_RE.match(stripped) or _TS_REASSIGN_RE.match(stripped))


def _make_line_sdl_site(
    line_bytes: bytes,
    line_start: int,
    line_num: int,
    rel_path: str,
    fn_name: str,
    replacement: str,
) -> Optional[MutationSite]:
    raw_no_eol = line_bytes.rstrip(b"\r\n")
    text = raw_no_eol.decode("utf-8", errors="replace")
    stripped = text.strip()
    if not stripped:
        return None
    leading = text[: len(text) - len(text.lstrip())]
    start_b = line_start + len(leading.encode("utf-8"))
    end_b = start_b + len(stripped.encode("utf-8"))
    return MutationSite(
        file_path=rel_path,
        function_name=fn_name,
        line=line_num,
        start_byte=start_b,
        end_byte=end_b,
        original=stripped,
        mutant=replacement,
        category="SDL",
        op_category="sdl",
    )


def _discover_ts_sdl_sites(
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None,
) -> List[MutationSite]:
    lines, starts = _compute_line_offsets(source_bytes)
    sites: List[MutationSite] = []
    fn_name = "top_level"
    for idx, line_bytes in enumerate(lines, start=1):
        stripped = line_bytes.decode("utf-8", errors="replace").strip()
        fn_name = _update_ts_fn_name(stripped, fn_name)
        if covered_lines is not None and idx not in covered_lines:
            continue
        if _is_ts_skippable_line(stripped) or not _is_ts_sdl_candidate(stripped):
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
        if nxt == "/" or nxt.isalpha() or nxt == "_":
            return True
    return False


def _scan_ts_line_operators(
    masked_line: str,
    line_start: int,
    line_num: int,
    rel_path: str,
    fn_name: str,
) -> List[MutationSite]:
    sites: List[MutationSite] = []
    claimed: Set[int] = set()
    for op in _TS_ORDERED_OPS:
        start = 0
        while True:
            pos = masked_line.find(op, start)
            if pos < 0:
                break
            start = pos + len(op)
            if any(p in claimed for p in range(pos, pos + len(op))):
                continue
            if _is_non_operator_angle(masked_line, pos, op):
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
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None,
) -> List[MutationSite]:
    masked_lines, starts = _compute_line_offsets(_mask_ts_comments_and_strings(source_bytes))
    sites: List[MutationSite] = []
    fn_name = "top_level"
    for idx, m_bytes in enumerate(masked_lines, start=1):
        line_str = m_bytes.rstrip(b"\r\n").decode("utf-8", errors="replace")
        stripped = line_str.strip()
        fn_name = _update_ts_fn_name(stripped, fn_name)
        if covered_lines is not None and idx not in covered_lines:
            continue
        if _is_ts_skippable_line(stripped):
            continue
        sites.extend(_scan_ts_line_operators(line_str, starts[idx - 1], idx, rel_path, fn_name))
    return sites


def _dedupe_and_sort_sites(sites: List[MutationSite]) -> List[MutationSite]:
    seen: Set[Tuple[int, int, str]] = set()
    out: List[MutationSite] = []
    for s in sorted(sites, key=lambda x: (x.line, x.start_byte, x.op_category)):
        key = (s.start_byte, s.end_byte, s.mutant)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def _discover_with_regex_fallback(
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None,
    mode: str = "all",
) -> List[MutationSite]:
    """Zero-dependency TS/JS regex/line scanner used when tree-sitter is unavailable."""
    sites: List[MutationSite] = []
    if mode in ("all", "operators"):
        sites.extend(_discover_ts_operator_fallback(source_bytes, rel_path, covered_lines))
    if mode in ("all", "sdl"):
        sites.extend(_discover_ts_sdl_sites(source_bytes, rel_path, covered_lines))
    return _dedupe_and_sort_sites(sites)


def _is_py_sdl_candidate(stripped: str) -> bool:
    if not stripped or stripped.startswith(_PY_SKIP_PREFIXES):
        return False
    if _PY_GUARD_IF_RE.match(stripped) or _PY_RAISE_RE.match(stripped) or _PY_ASSERT_RE.match(stripped):
        return True
    if stripped.startswith("return "):
        return False
    return bool(_PY_CALL_RE.match(stripped))


def _update_py_docstring_state(stripped: str, in_doc: Optional[str]) -> Tuple[Optional[str], bool]:
    for quote in ('"""', "'''"):
        cnt = stripped.count(quote)
        if in_doc == quote:
            return (None if cnt % 2 == 1 else quote), True
        if in_doc is None and stripped.startswith(quote):
            return (quote if cnt % 2 == 1 else None), True
    return in_doc, in_doc is not None


def _discover_python_sdl_sites(
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None,
) -> List[MutationSite]:
    lines, starts = _compute_line_offsets(source_bytes)
    sites: List[MutationSite] = []
    fn_name = "py_func"
    in_doc: Optional[str] = None
    for idx, line_bytes in enumerate(lines, start=1):
        raw_text = line_bytes.decode("utf-8", errors="replace")
        stripped = raw_text.strip()
        m_def = _PY_DEF_RE.match(raw_text)
        if m_def:
            fn_name = m_def.group(1)
        in_doc, skip_doc = _update_py_docstring_state(stripped, in_doc)
        if skip_doc or (covered_lines is not None and idx not in covered_lines):
            continue
        if _is_py_sdl_candidate(stripped):
            site = _make_line_sdl_site(line_bytes, starts[idx - 1], idx, rel_path, fn_name, "pass  # [SDL-DELETED]")
            if site is not None:
                sites.append(site)
    return sites


def _discover_python_sites_fallback(
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None,
) -> List[MutationSite]:
    lines, line_start_bytes = _compute_line_offsets(source_bytes)
    try:
        tokens = list(tokenize.tokenize(io.BytesIO(source_bytes).readline))
    except Exception:
        return []
    sites: List[MutationSite] = []
    for t in tokens:
        token_str = t.string
        if token_str not in MUTATION_MAP:
            continue
        s_line, s_col = t.start
        if s_line != t.end[0] or (covered_lines is not None and s_line not in covered_lines):
            continue
        line_bytes = lines[s_line - 1]
        start_byte = line_start_bytes[s_line - 1] + len(
            line_bytes.decode("utf-8", errors="replace")[:s_col].encode("utf-8")
        )
        mutant, cat = MUTATION_MAP[token_str]
        sites.append(
            MutationSite(rel_path, "py_func", s_line, start_byte, start_byte + len(token_str.encode("utf-8")), token_str, mutant, cat, "operators")
        )
    return sites


def _extract_ts_fn_name(node: Any, source_bytes: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
    p_node = node.parent
    if p_node and p_node.type == "variable_declarator":
        v_name = p_node.child_by_field_name("name")
        if v_name:
            return source_bytes[v_name.start_byte:v_name.end_byte].decode("utf-8", errors="ignore")
    for c in node.children:
        if c.type in ("identifier", "property_identifier"):
            return source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore")
    return "anonymous"


def _find_op_child(node: Any, source_bytes: bytes) -> Any:
    op_node = node.child_by_field_name("operator")
    if op_node:
        return op_node
    for c in node.children:
        if source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip() in MUTATION_MAP:
            return c
    return None


def _discover_treesitter_operators(
    parser: Any,
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None,
) -> List[MutationSite]:
    root = parser.parse(source_bytes).root_node
    sites: List[MutationSite] = []
    fn_types = {"function_declaration", "function_definition", "arrow_function", "method_definition", "function_expression"}
    bin_types = {"binary_expression", "binary_operator", "comparison_operator", "boolean_operator"}

    def _walk(node: Any, current_fn: str) -> None:
        fn_name = _extract_ts_fn_name(node, source_bytes) if node.type in fn_types else current_fn
        target_node = _find_op_child(node, source_bytes) if node.type in bin_types else (
            node if node.type in ("true", "false") or (node.type == "identifier" and source_bytes[node.start_byte:node.end_byte] in (b"True", b"False")) else None
        )
        if target_node is not None:
            token = source_bytes[target_node.start_byte:target_node.end_byte].decode("utf-8", errors="ignore").strip()
            line = target_node.start_point[0] + 1
            if token in MUTATION_MAP and (covered_lines is None or line in covered_lines):
                mutant, cat = MUTATION_MAP[token]
                sites.append(MutationSite(rel_path, fn_name, line, target_node.start_byte, target_node.end_byte, token, mutant, cat, "operators"))
        for child in node.children:
            _walk(child, fn_name)

    _walk(root, "top_level")
    return sites


def _discover_python_file_sites(
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]],
    mode: str,
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
    ext: str,
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]],
    mode: str,
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
    file_path: Union[Path, str],
    rel_path: str = "",
    covered_lines: Optional[Set[int]] = None,
    mode: str = "all",
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
    if ext in _TS_EXTS:
        return _discover_ts_file_sites(ext, source_bytes, eff_rel, covered_lines, mode)
    return []
