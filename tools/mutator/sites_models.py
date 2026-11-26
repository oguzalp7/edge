"""
MutationSite contract, operator map, and byte-level patching helpers.
"""

from dataclasses import dataclass
from typing import Any, List, Set, Tuple

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
    return source_bytes[:site.start_byte] + site.mutant.encode("utf-8") + source_bytes[site.end_byte:]


def _get_parser_for_ext(ext: str) -> Any:
    if not TREE_SITTER_AVAILABLE:
        return None
    mapping = {".ts": "typescript", ".tsx": "tsx", ".jsx": "tsx", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".py": "python"}
    lang = mapping.get(ext.lower())
    return tslp.get_parser(lang) if lang else None


def _compute_line_offsets(source_bytes: bytes) -> Tuple[List[bytes], List[int]]:
    lines = source_bytes.splitlines(keepends=True)
    starts: List[int] = []
    pos = 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln)
    return lines, starts


def _dedupe_and_sort_sites(sites: List[MutationSite]) -> List[MutationSite]:
    seen: Set[Tuple[int, int, str]] = set()
    out: List[MutationSite] = []
    for s in sorted(sites, key=lambda x: (x.line, x.start_byte, x.op_category)):
        key = (s.start_byte, s.end_byte, s.mutant)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out
