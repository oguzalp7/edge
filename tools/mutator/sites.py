"""
Mutation Sites Discovery and Patching Engine.
Discovers AST mutation sites in TypeScript/JavaScript/Python source files
and applies byte-accurate UTF-8 replacements.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Set, Any, Union

try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


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


MUTATION_MAP = {
    # Arithmetic
    "+": ("-", "Arithmetic"),
    "-": ("+", "Arithmetic"),
    "*": ("/", "Multiplicative"),
    "/": ("*", "Multiplicative"),
    # Relational
    ">": (">=", "Relational"),
    ">=": (">", "Relational"),
    "<": ("<=", "Relational"),
    "<=": ("<", "Relational"),
    # Equality
    "===": ("!==", "Equality"),
    "!==": ("===", "Equality"),
    "==": ("!=", "Equality"),
    "!=": ("==", "Equality"),
    # Logical
    "&&": ("||", "Logical"),
    "||": ("&&", "Logical"),
    "and": ("or", "Logical"),
    "or": ("and", "Logical"),
    # Nullish
    "??": ("||", "Nullish"),
    # Boolean
    "true": ("false", "Boolean"),
    "false": ("true", "Boolean"),
    "True": ("False", "Boolean"),
    "False": ("True", "Boolean"),
}


def apply_mutation(source_bytes: bytes, site: MutationSite) -> bytes:
    """Replaces exact byte range [start_byte:end_byte] with site.mutant."""
    mutant_bytes = site.mutant.encode("utf-8")
    return source_bytes[:site.start_byte] + mutant_bytes + source_bytes[site.end_byte:]


def _get_parser_for_ext(ext: str):
    if not TREE_SITTER_AVAILABLE:
        return None
    ext = ext.lower()
    if ext in (".ts",):
        return tslp.get_parser("typescript")
    elif ext in (".tsx", ".jsx"):
        return tslp.get_parser("tsx")
    elif ext in (".js", ".mjs", ".cjs"):
        return tslp.get_parser("javascript")
    elif ext in (".py",):
        return tslp.get_parser("python")
    return None


def _discover_python_sites_fallback(
    source_bytes: bytes,
    rel_path: str,
    covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    import tokenize
    import io

    sites = []
    lines = source_bytes.splitlines(keepends=True)
    line_start_bytes = [0]
    for l in lines:
        line_start_bytes.append(line_start_bytes[-1] + len(l))

    try:
        tokens = list(tokenize.tokenize(io.BytesIO(source_bytes).readline))
    except Exception:
        return []

    for t in tokens:
        token_str = t.string
        if token_str in MUTATION_MAP:
            s_line, s_col = t.start
            e_line, e_col = t.end
            if s_line != e_line:
                continue
            if covered_lines is not None and s_line not in covered_lines:
                continue

            line_start_byte = line_start_bytes[s_line - 1]
            line_bytes = lines[s_line - 1]
            start_byte = line_start_byte + len(line_bytes.decode("utf-8", errors="replace")[:s_col].encode("utf-8"))
            end_byte = start_byte + len(token_str.encode("utf-8"))

            mutant, cat = MUTATION_MAP[token_str]
            sites.append(MutationSite(
                file_path=rel_path,
                function_name="py_func",
                line=s_line,
                start_byte=start_byte,
                end_byte=end_byte,
                original=token_str,
                mutant=mutant,
                category=cat
            ))
    return sites


def discover_mutation_sites(
    file_path: Union[Path, str],
    rel_path: str,
    covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    """
    Discovers mutation candidate sites in the given source file using tree-sitter AST.
    If covered_lines is provided, only sites occurring on covered lines are returned.
    """
    p = Path(file_path)
    if not p.exists():
        return []

    try:
        source_bytes = p.read_bytes()
    except Exception:
        return []

    if not TREE_SITTER_AVAILABLE:
        if p.suffix.lower() == ".py":
            return _discover_python_sites_fallback(source_bytes, rel_path, covered_lines)
        return []

    parser = _get_parser_for_ext(p.suffix)
    if not parser:
        if p.suffix.lower() == ".py":
            return _discover_python_sites_fallback(source_bytes, rel_path, covered_lines)
        return []

    tree = parser.parse(source_bytes)
    root = tree.root_node

    sites: List[MutationSite] = []

    function_types = {
        "function_declaration",
        "function_definition",
        "arrow_function",
        "method_definition",
        "function_expression",
    }

    def _extract_fn_name(node: Any) -> str:
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

    def _walk(node: Any, current_fn: str):
        fn_name = current_fn
        if node.type in function_types:
            fn_name = _extract_fn_name(node)

        # 1. Binary expressions and boolean operators
        if node.type in ("binary_expression", "binary_operator", "comparison_operator", "boolean_operator"):
            # Inspect operator token
            op_node = node.child_by_field_name("operator")
            if not op_node:
                # Find operator child between operands
                for c in node.children:
                    token = source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip()
                    if token in MUTATION_MAP:
                        op_node = c
                        break

            if op_node:
                token = source_bytes[op_node.start_byte:op_node.end_byte].decode("utf-8", errors="ignore").strip()
                if token in MUTATION_MAP:
                    line = op_node.start_point[0] + 1
                    if covered_lines is None or line in covered_lines:
                        mutant, cat = MUTATION_MAP[token]
                        sites.append(MutationSite(
                            file_path=rel_path,
                            function_name=fn_name,
                            line=line,
                            start_byte=op_node.start_byte,
                            end_byte=op_node.end_byte,
                            original=token,
                            mutant=mutant,
                            category=cat
                        ))

        # 2. Boolean literals
        elif node.type in ("true", "false") or (node.type == "identifier" and source_bytes[node.start_byte:node.end_byte] in (b"True", b"False")):
            token = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
            if token in MUTATION_MAP:
                line = node.start_point[0] + 1
                if covered_lines is None or line in covered_lines:
                    mutant, cat = MUTATION_MAP[token]
                    sites.append(MutationSite(
                        file_path=rel_path,
                        function_name=fn_name,
                        line=line,
                        start_byte=node.start_byte,
                        end_byte=node.end_byte,
                        original=token,
                        mutant=mutant,
                        category=cat
                    ))

        for child in node.children:
            _walk(child, fn_name)

    _walk(root, "top_level")
    return sites
