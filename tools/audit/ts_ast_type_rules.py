"""
Tree-sitter AST interface/object-bag and positional parameter rule handlers.
"""

from __future__ import annotations

import re
from typing import Any, List

from tools.audit.ts_models import _STATUS_BOOLEAN_NAMES, TsDisciplineFinding, make_finding


def node_text(node: Any, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def check_interface_or_object_type(node: Any, ln: int, source_bytes: bytes, lines: List[str], findings: List[TsDisciplineFinding]) -> bool:
    has_status_bool, optional_count, has_brand = False, 0, False
    for c in node.children:
        if c.type != "property_signature":
            continue
        pname_n, ptype_n = c.child_by_field_name("name"), c.child_by_field_name("type")
        pname = node_text(pname_n, source_bytes).strip() if pname_n is not None else ""
        ptype = node_text(ptype_n, source_bytes).strip() if ptype_n is not None else ""
        if pname == "__brand" and "readonly" in node_text(c, source_bytes):
            has_brand = True
        if any(tok.type == "?" for tok in c.children):
            optional_count += 1
        if pname in _STATUS_BOOLEAN_NAMES and re.search(r"\bboolean\b", ptype):
            has_status_bool = True
    if has_status_bool and optional_count >= 2:
        p_name = node.parent.child_by_field_name("name") if node.parent is not None else None
        sym = node_text(p_name, source_bytes).strip() if p_name is not None else None
        findings.append(make_finding(
            "RULE-TS-OPTIONAL-BAG", "ADVISORY", -6, ln, sym,
            f"Type `{sym or 'object'}` models state with a status boolean and optional fields instead of a discriminated union.",
            "Refactor into a discriminated union with an explicit literal `status` or `kind` field.", lines,
        ))
    return has_brand


def _resolve_fn_symbol(node: Any, source_bytes: bytes) -> str:
    sym_node = node.child_by_field_name("name")
    if sym_node is not None:
        return node_text(sym_node, source_bytes).strip()
    if node.parent is not None and node.parent.type == "variable_declarator" and (vn := node.parent.child_by_field_name("name")) is not None:
        return node_text(vn, source_bytes).strip()
    return "anonymous"


def check_positional_params(node: Any, ln: int, source_bytes: bytes, lines: List[str], findings: List[TsDisciplineFinding]) -> None:
    params_node = node.child_by_field_name("parameters")
    if params_node is None:
        return
    positional_count, id_param_count = 0, 0
    for c in params_node.children:
        if c.type not in ("required_parameter", "optional_parameter", "rest_parameter"):
            continue
        pat_node = c.child_by_field_name("pattern") or c.child_by_field_name("name")
        pat_text = node_text(pat_node, source_bytes).strip() if pat_node is not None else ""
        if pat_text == "this":
            continue
        positional_count += 1
        if pat_node is not None and pat_node.type == "identifier" and pat_text.endswith("Id"):
            type_text = node_text(tn, source_bytes).lstrip(":").strip() if (tn := c.child_by_field_name("type")) is not None else ""
            if re.match(r"^string\b", type_text):
                id_param_count += 1
    if positional_count < 4 and id_param_count < 2:
        return
    sym = _resolve_fn_symbol(node, source_bytes)
    findings.append(make_finding(
        "RULE-TS-POSITIONAL-ARGS", "ADVISORY", -5, ln, sym,
        f"Function `{sym}` takes {positional_count} positional / {id_param_count} `*Id` parameter(s).",
        "Group parameters into a single named options object ({ ... }); skip only on documented hot paths.", lines,
    ))
