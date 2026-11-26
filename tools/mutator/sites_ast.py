"""
Tree-sitter AST mutation operator site discovery helpers.
"""

from typing import Any, List, Optional, Set, Tuple

from tools.mutator.sites_models import MUTATION_MAP, MutationSite

_FN_TYPES = {"function_declaration", "function_definition", "arrow_function", "method_definition", "function_expression"}
_BIN_TYPES = {"binary_expression", "binary_operator", "comparison_operator", "boolean_operator"}


def _extract_ts_fn_name(node: Any, source_bytes: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
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


def _target_op_node(node: Any, source_bytes: bytes) -> Any:
    if node.type in _BIN_TYPES:
        return _find_op_child(node, source_bytes)
    if node.type in ("true", "false") or (node.type == "identifier" and source_bytes[node.start_byte:node.end_byte] in (b"True", b"False")):
        return node
    return None


def _discover_treesitter_operators(
    parser: Any, source_bytes: bytes, rel_path: str, covered_lines: Optional[Set[int]] = None
) -> List[MutationSite]:
    root = parser.parse(source_bytes).root_node
    sites: List[MutationSite] = []
    stack: List[Tuple[Any, str]] = [(root, "top_level")]
    while stack:
        node, current_fn = stack.pop()
        fn_name = _extract_ts_fn_name(node, source_bytes) if node.type in _FN_TYPES else current_fn
        target_node = _target_op_node(node, source_bytes)
        if target_node is not None:
            token = source_bytes[target_node.start_byte:target_node.end_byte].decode("utf-8", errors="ignore").strip()
            line = target_node.start_point[0] + 1
            if token in MUTATION_MAP and (covered_lines is None or line in covered_lines):
                mutant, cat = MUTATION_MAP[token]
                sites.append(MutationSite(rel_path, fn_name, line, target_node.start_byte, target_node.end_byte, token, mutant, cat, "operators"))
        stack.extend((c, fn_name) for c in reversed(node.children))
    return sites
