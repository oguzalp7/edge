"""
Tree-sitter AST analyzer for TypeScript/TSX files.
"""

from __future__ import annotations

from typing import Any, List, Set, Tuple

from tools.audit.ts_ast_rules import (
    check_as_expression,
    check_console_log_call,
    check_generic_type,
    check_interface_or_object_type,
    check_positional_params,
    check_switch_statement,
    node_text,
)
from tools.audit.ts_models import _SUPPRESSION_RE, TsDisciplineFinding, _is_core_or_lib_path, _is_test_path, make_finding

_FN_NODE_TYPES = frozenset(("function_declaration", "function_expression", "arrow_function", "method_definition"))


def _check_comment_node(node: Any, ln: int, source_bytes: bytes, lines: List[str], findings: List[TsDisciplineFinding]) -> None:
    for offset_line, cline in enumerate(node_text(node, source_bytes).splitlines()):
        if (m := _SUPPRESSION_RE.search(cline)):
            findings.append(make_finding(
                "RULE-TS-SUPPRESSION", "CRITICAL", -20, ln + offset_line, m.group(0),
                f"Compiler suppression `{m.group(0)}` hides type errors.",
                "Remove suppression directive and fix the underlying type contract.", lines,
            ))


def _analyze_with_ast(source: str, rel_path: str, parser: Any) -> Tuple[List[TsDisciplineFinding], bool]:
    source_bytes = source.encode("utf-8")
    lines = source.splitlines()
    root = parser.parse(source_bytes).root_node
    is_test, is_core_lib = _is_test_path(rel_path), _is_core_or_lib_path(rel_path)

    findings: List[TsDisciplineFinding] = []
    double_cast_spans: Set[Tuple[int, int]] = set()
    has_bonus = False
    stack = [root]

    while stack:
        node = stack.pop()
        ntype, ln = node.type, node.start_point[0] + 1
        if ntype == "predefined_type" and node_text(node, source_bytes).strip() == "any":
            findings.append(make_finding(
                "RULE-TS-EXPLICIT-ANY", "CRITICAL", -20, ln, "any",
                "Explicit `any` bypasses TypeScript structural soundness.",
                "Replace `any` with `unknown` and narrow with Zod or explicit type guards.", lines,
            ))
        elif ntype == "comment":
            _check_comment_node(node, ln, source_bytes, lines, findings)
        elif ntype == "as_expression":
            check_as_expression(node, ln, source_bytes, lines, double_cast_spans, findings)
        elif ntype == "non_null_expression":
            findings.append(make_finding(
                "RULE-TS-NON-NULL", "WARNING", -10, ln, "!",
                "Non-null assertion (`!`) suppresses null/undefined checks at runtime.",
                "Narrow explicitly (`if (!value) ...` or `.at(0)`) instead of postfix `!`.", lines,
            ))
        elif ntype == "call_expression" and not is_test:
            check_console_log_call(node, ln, source_bytes, lines, findings)
        elif ntype == "generic_type":
            has_bonus = check_generic_type(node, ln, source_bytes, lines, is_core_lib, findings) or has_bonus
        elif ntype == "switch_statement":
            has_bonus = check_switch_statement(node, ln, source_bytes, lines, findings) or has_bonus
        elif ntype in ("interface_body", "object_type"):
            has_bonus = check_interface_or_object_type(node, ln, source_bytes, lines, findings) or has_bonus
        elif ntype in _FN_NODE_TYPES:
            check_positional_params(node, ln, source_bytes, lines, findings)
        elif ntype == "satisfies_expression":
            has_bonus = True
        stack.extend(reversed(node.children))

    return findings, has_bonus
