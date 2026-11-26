"""
Tree-sitter AST node rule handlers for ts_discipline.
"""

from __future__ import annotations

from typing import Any, List, Set, Tuple

from tools.audit.ts_ast_type_rules import check_interface_or_object_type, check_positional_params, node_text
from tools.audit.ts_models import _NEVER_BINDING_RE, TsDisciplineFinding, make_finding


def unwrap_parens(node: Any) -> Any:
    cur = node
    while cur is not None and cur.type == "parenthesized_expression":
        named = [c for c in cur.children if c.is_named]
        cur = named[0] if named else None
    return cur


def check_as_expression(
    node: Any, ln: int, source_bytes: bytes, lines: List[str], double_cast_spans: Set[Tuple[int, int]], findings: List[TsDisciplineFinding]
) -> None:
    span = (node.start_byte, node.end_byte)
    if span in double_cast_spans:
        return
    named = [c for c in node.children if c.is_named]
    if len(named) < 2:
        return
    lhs_node = unwrap_parens(named[0])
    type_text = node_text(named[-1], source_bytes).strip()
    if lhs_node is not None and lhs_node.type == "as_expression":
        inner_named = [c for c in lhs_node.children if c.is_named]
        inner_type = node_text(inner_named[-1], source_bytes).strip() if inner_named else ""
        if inner_type == "unknown":
            double_cast_spans.add(span)
            double_cast_spans.add((lhs_node.start_byte, lhs_node.end_byte))
            findings.append(make_finding(
                "RULE-TS-DOUBLE-CAST", "CRITICAL", -20, ln, "as unknown as",
                "Double cast `as unknown as` forces arbitrary type conversion.",
                "Validate the value with a Zod schema or verifying type guard instead of double-casting.", lines,
            ))
    if span not in double_cast_spans and type_text not in ("const", "any"):
        fix = (
            f"Use `satisfies {type_text}` instead of `as {type_text}` to preserve narrow literal inference."
            if (lhs_node is not None and lhs_node.type in ("object", "array"))
            else "Prefer discriminant `switch`, `in`, `typeof`/`instanceof`, or a verifying type guard over `as`."
        )
        findings.append(make_finding(
            "RULE-TS-UNSAFE-AS", "WARNING", -10, ln, f"as {type_text}",
            f"Unsafe type assertion `as {type_text}` overrides compiler verification.", fix, lines,
        ))


def check_console_log_call(node: Any, ln: int, source_bytes: bytes, lines: List[str], findings: List[TsDisciplineFinding]) -> None:
    fn_node = node.child_by_field_name("function")
    if fn_node is None or fn_node.type != "member_expression":
        return
    obj, prop = fn_node.child_by_field_name("object"), fn_node.child_by_field_name("property")
    if obj is not None and prop is not None and node_text(obj, source_bytes).strip() == "console" and node_text(prop, source_bytes).strip() == "log":
        findings.append(make_finding(
            "RULE-TS-CONSOLE-LOG", "WARNING", -8, ln, "console.log",
            "`console.log(...)` left in shipped production TypeScript file.",
            "Remove debug `console.log` or emit structured telemetry.", lines,
        ))


def check_generic_type(node: Any, ln: int, source_bytes: bytes, lines: List[str], is_core_lib: bool, findings: List[TsDisciplineFinding]) -> bool:
    name_node = node.child_by_field_name("name")
    name_text = node_text(name_node, source_bytes).strip() if name_node is not None else ""
    if name_text == "z.infer":
        return True
    if is_core_lib and name_text == "Record" and (ta_node := node.child_by_field_name("type_arguments")) is not None:
        args = [node_text(c, source_bytes).strip() for c in ta_node.children if c.is_named]
        if args == ["string", "unknown"]:
            findings.append(make_finding(
                "RULE-TS-RECORD-UNKNOWN", "WARNING", -8, ln, "Record<string, unknown>",
                "Untyped `Record<string, unknown>` leaked into core/lib domain boundary.",
                "Validate at perimeter (actions/routes) and pass typed domain contracts into src/core and src/lib.", lines,
            ))
    return False


def check_switch_statement(node: Any, ln: int, source_bytes: bytes, lines: List[str], findings: List[TsDisciplineFinding]) -> bool:
    body_node = node.child_by_field_name("body")
    default_node = next((c for c in body_node.children if c.type == "switch_default"), None) if body_node is not None else None
    if default_node is not None and _NEVER_BINDING_RE.search(node_text(default_node, source_bytes)):
        return True
    findings.append(make_finding(
        "RULE-TS-SWITCH-EXHAUSTIVE", "WARNING", -8, ln, "switch",
        "`switch` statement lacks an exhaustive `default:` branch with a `: never` binding.",
        "Add `default: { const _exhaustive: never = value; throw new Error(...); }`.", lines,
    ))
    return False
