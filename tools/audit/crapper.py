"""
CRAPPER: Change Risk Anti-Patterns Complexity and LCOV Branch Risk Engine.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from tools.audit.crapper_lcov import (
    FunctionCrapMetric,
    compute_crap,
    discover_existing_lcov,
    function_coverage_from_lcov,
    parse_lcov,
)

_BRANCHING_TYPES = {
    "if_statement", "elif_clause", "while_statement", "for_statement",
    "for_in_statement", "catch_clause", "except_clause", "switch_case",
    "case_clause", "ternary_expression", "conditional_expression",
}
_FUNCTION_TYPES = {"function_declaration", "function_definition", "arrow_function", "method_definition", "function_expression"}


def _get_parser_for_ext(ext: str):
    if not TREE_SITTER_AVAILABLE:
        return None, None
    mapping = {".ts": "typescript", ".tsx": "tsx", ".jsx": "tsx", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".py": "python"}
    lang = mapping.get(ext.lower())
    return (tslp.get_parser(lang), lang) if lang else (None, None)


def _has_logical_op(node: Any, source_bytes: bytes) -> bool:
    op = node.child_by_field_name("operator")
    if op:
        return source_bytes[op.start_byte:op.end_byte].decode("utf-8", errors="ignore").strip() in ("&&", "||")
    return any(
        source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip() in ("&&", "||")
        for c in node.children
    )


def _calc_node_complexity(node: Any, source_bytes: bytes) -> int:
    """Computes cyclomatic complexity of an AST subtree."""
    comp = 1
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type in _BRANCHING_TYPES or n.type == "boolean_operator":
            comp += 1
        elif n.type in ("binary_expression", "logical_expression") and _has_logical_op(n, source_bytes):
            comp += 1
        stack.extend(n.children)
    return comp


def _find_function_symbol(node: Any, source_bytes: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
    p = node.parent
    if p and p.type == "variable_declarator" and (vn := p.child_by_field_name("name")):
        return source_bytes[vn.start_byte:vn.end_byte].decode("utf-8", errors="ignore")
    for c in node.children:
        if c.type in ("identifier", "property_identifier"):
            return source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore")
    return f"anonymous_L{node.start_point[0] + 1}"


def _is_exported_node(node: Any) -> bool:
    cur_p = node.parent
    while cur_p and cur_p.type not in ("program", "module"):
        if cur_p.type in ("export_statement", "export_declaration"):
            return True
        cur_p = cur_p.parent
    return False


def _build_crap_metric(node: Any, rel_path: str, source_bytes: bytes, lcov_data: Optional[Dict[str, Any]]) -> FunctionCrapMetric:
    start_l = node.start_point[0] + 1
    end_l = node.end_point[0] + 1
    complexity = _calc_node_complexity(node, source_bytes)
    cov_pct = function_coverage_from_lcov(lcov_data, start_l, end_l) if lcov_data is not None else None
    crap = compute_crap(complexity, cov_pct) if cov_pct is not None else None
    return FunctionCrapMetric(
        file_path=rel_path,
        name=_find_function_symbol(node, source_bytes),
        start_line=start_l,
        end_line=end_l,
        complexity=complexity,
        coverage_pct=cov_pct,
        crap_score=crap,
        sloc=max(1, end_l - start_l + 1),
        is_exported=_is_exported_node(node),
    )


def analyze_file_crap(
    file_path: Union[Path, str], rel_path: str, lcov_data: Optional[Dict[str, Any]] = None
) -> List[FunctionCrapMetric]:
    """Extracts functions via tree-sitter AST and computes CC and CRAP score."""
    if not TREE_SITTER_AVAILABLE or not (p := Path(file_path)).exists():
        return []
    parser, _ = _get_parser_for_ext(p.suffix)
    if not parser:
        return []
    try:
        source_bytes = p.read_bytes()
    except Exception:
        return []

    metrics: List[FunctionCrapMetric] = []
    stack = [parser.parse(source_bytes).root_node]
    while stack:
        node = stack.pop()
        if node.type in _FUNCTION_TYPES:
            metrics.append(_build_crap_metric(node, rel_path, source_bytes, lcov_data))
            continue
        stack.extend(reversed(node.children))
    return metrics
