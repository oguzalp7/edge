"""
Subtree shingling and function unit extraction helpers for DRYER.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Set, Tuple

_TARGET_NODE_TYPES = {"function_declaration", "function_definition", "arrow_function", "method_definition", "function_expression"}
_SHINGLE_IGNORED = {
    "comment", "line_comment", "block_comment", "type_annotation",
    "type_arguments", "type_parameters", "return_type", "accessibility_modifier", "type",
}


@dataclass
class AstUnit:
    file_path: str
    symbol: str
    kind: str
    start_line: int
    end_line: int
    node_count: int
    fingerprints: frozenset[str]


@dataclass
class ClonePair:
    score: float
    language: str
    left: AstUnit
    right: AstUnit


@dataclass
class CloneCluster:
    cluster_id: str
    members: List[AstUnit]
    distinct_files: List[str]
    max_score: float


def jaccard_similarity(fp_a: frozenset[str], fp_b: frozenset[str]) -> float:
    if not fp_a or not fp_b:
        return 0.0
    union = len(fp_a | fp_b)
    return round(float(len(fp_a & fp_b)) / float(union), 4) if union > 0 else 0.0


def _extract_shingles(norm_tree: Tuple[Any, ...], depth_limit: int = 3) -> Set[str]:
    shingles: Set[str] = set()
    stack: List[Tuple[Any, List[str]]] = [(norm_tree, [])]
    while stack:
        sub, path = stack.pop()
        if not isinstance(sub, tuple) or not sub:
            continue
        head = str(sub[0])
        current_path = path + [head]
        shingles.update("->".join(current_path[-k:]) for k in range(1, min(depth_limit + 1, len(current_path) + 1)))
        children = sub[1:]
        if children:
            child_types = [str(c[0]) if isinstance(c, tuple) and c else str(c) for c in children]
            shingles.add(f"{head}({','.join(child_types)})")
        stack.extend((c, current_path) for c in children if isinstance(c, tuple))
    return shingles


def _count_ast_nodes(node: Any) -> int:
    count, stack = 0, [node]
    while stack:
        n = stack.pop()
        count += 1
        stack.extend(c for c in n.children if c.type not in _SHINGLE_IGNORED)
    return count


def _find_unit_symbol(node: Any, source_bytes: bytes) -> str:
    if (nn := node.child_by_field_name("name")):
        return source_bytes[nn.start_byte:nn.end_byte].decode("utf-8", errors="ignore")
    p = node.parent
    if p and p.type == "variable_declarator" and (vn := p.child_by_field_name("name")):
        return source_bytes[vn.start_byte:vn.end_byte].decode("utf-8", errors="ignore")
    for c in node.children:
        if c.type in ("identifier", "property_identifier"):
            return source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore")
    return f"anonymous_L{node.start_point[0] + 1}"


def extract_units(
    root: Any,
    file_path: str,
    source_bytes: bytes,
    min_lines: int,
    min_nodes: int,
    normalizer: Callable[[Any, bytes], Optional[Tuple[Any, ...]]],
) -> List[AstUnit]:
    units: List[AstUnit] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type not in _TARGET_NODE_TYPES:
            stack.extend(reversed(node.children))
            continue
        start_l, end_l = node.start_point[0] + 1, node.end_point[0] + 1
        node_cnt = _count_ast_nodes(node)
        if (end_l - start_l + 1) < min_lines or node_cnt < min_nodes:
            stack.extend(reversed(node.children))
            continue
        if (norm := normalizer(node, source_bytes)):
            kind = "method" if node.type == "method_definition" else "function"
            units.append(AstUnit(file_path, _find_unit_symbol(node, source_bytes), kind, start_l, end_l, node_cnt, frozenset(_extract_shingles(norm))))
    return units
