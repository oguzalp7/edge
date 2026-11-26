"""
AST normalization helpers and public structural data models for DRYER.
"""

from typing import Any, List, Optional, Tuple

from tools.audit.dryer_units import (
    AstUnit,
    CloneCluster,
    ClonePair,
    _count_ast_nodes,
    _extract_shingles,
    _find_unit_symbol,
    extract_units,
    jaccard_similarity,
)

IGNORED_NODE_TYPES = {
    "comment", "line_comment", "block_comment", "type_annotation",
    "type_arguments", "type_parameters", "return_type", "accessibility_modifier", "type",
}
LITERAL_NODE_TYPES = {
    "string", "string_fragment", "template_string", "number", "integer",
    "float", "true", "false", "null", "undefined", "none",
}
_PRESERVED_OPS = frozenset(("+", "-", "*", "/", "%", "&&", "||", "===", "!==", "==", "!=", "<", ">", "<=", ">=", "??", "=", "+=", "-="))


def _is_callee(node: Any) -> bool:
    parent = node.parent
    if not parent:
        return False
    if parent.type in ("call_expression", "call"):
        fn_child = parent.child_by_field_name("function")
        return bool(fn_child and fn_child.id == node.id)
    if parent.type in ("member_expression", "attribute"):
        prop = parent.child_by_field_name("property") or parent.child_by_field_name("attribute")
        gp = parent.parent
        return bool(prop and prop.id == node.id and gp and gp.type in ("call_expression", "call"))
    return False


def _is_jsx_tag(node: Any) -> bool:
    parent = node.parent
    if not parent or parent.type not in ("jsx_opening_element", "jsx_self_closing_element", "jsx_closing_element"):
        return False
    name_child = parent.child_by_field_name("name")
    if name_child and (name_child.id == node.id or (node.parent and node.parent.id == name_child.id)):
        return True
    return node.type in ("jsx_identifier", "identifier")


def normalize_ast(node: Any, source_bytes: bytes) -> Optional[Tuple[Any, ...]]:
    """Normalizes a tree-sitter node into an immutable structural tuple."""
    if node is None or node.type in IGNORED_NODE_TYPES:
        return None
    if _is_jsx_tag(node):
        return ("JSX_TAG", source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore"))
    if _is_callee(node) and node.type in ("identifier", "property_identifier"):
        return ("CALLEE", source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore"))
    if node.type in LITERAL_NODE_TYPES:
        return ("$LIT",)
    if node.type in ("identifier", "property_identifier", "shorthand_property_identifier"):
        return ("$ID",)
    if not node.children:
        tok = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
        return ("OP", tok) if tok in _PRESERVED_OPS else (node.type,)
    children = [nc for child in node.children if (nc := normalize_ast(child, source_bytes)) is not None]
    return (node.type, *children)


def extract_units_from_tree(
    root: Any, file_path: str, source_bytes: bytes, min_lines: int, min_nodes: int
) -> List[AstUnit]:
    return extract_units(root, file_path, source_bytes, min_lines, min_nodes, normalize_ast)
