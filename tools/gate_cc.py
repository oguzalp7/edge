"""Cyclomatic complexity and SLOC helpers for Edge Verification Gate."""

import ast
import re
import sys
from typing import Any, List, Optional, Tuple

from tools.audit import crapper as _crapper

_JS_BRANCH_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bif\b"), re.compile(r"\bfor\b"), re.compile(r"\bwhile\b"),
    re.compile(r"\bcase\b"), re.compile(r"\bcatch\b"), re.compile(r"&&"),
    re.compile(r"\|\|"), re.compile(r"(?<!\?)\?(?![?.:])"),
]
_JS_FUNC_DECL_RE = re.compile(r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>]*>)?\s*\(")
_JS_VAR_FUNC_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?"
    r"(?:function\b|(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=>)"
)
_JS_METHOD_RE = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+|async\s+)*"
    r"([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>]*>)?\s*\([^;]*\)\s*(?::\s*[^{;=]+)?\{"
)
_JS_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return"}
_JS_COMMENT_OR_STRING_RE = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`"
)
_TS_FUNC_TYPES = {"function_declaration", "function_definition", "arrow_function", "method_definition", "function_expression"}


def _mask_non_newlines(match: re.Match[str]) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in match.group(0))


def strip_js_comments_and_strings(text: str) -> str:
    """Replace JS/TS comments and string literal contents with spaces while keeping newlines."""
    return _JS_COMMENT_OR_STRING_RE.sub(_mask_non_newlines, text)


def count_js_branches(sanitized_block: str) -> int:
    """Count branch keywords/operators in a sanitized JS/TS block."""
    return 1 + sum(len(pat.findall(sanitized_block)) for pat in _JS_BRANCH_PATTERNS)


def ast_py_node_complexity(root_node: ast.AST) -> int:
    """Compute cyclomatic complexity of a Python AST subtree."""
    comp = 1
    for node in ast.walk(root_node):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            comp += 1
        elif isinstance(node, ast.BoolOp):
            comp += max(1, len(node.values) - 1)
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):
            comp += len(node.cases)
    return comp


def compute_py_fallback_max_cc(source_text: str) -> Optional[Tuple[int, str]]:
    """Compute max per-function CC for Python source via stdlib ast."""
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None
    funcs: List[Tuple[int, str]] = []

    def _visit(stmts: List[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((ast_py_node_complexity(stmt), stmt.name))
            elif isinstance(stmt, ast.ClassDef):
                _visit(stmt.body)

    _visit(tree.body)
    return max(funcs, key=lambda item: item[0]) if funcs else (ast_py_node_complexity(tree), "<module>")


def _scan_js_block_end(lines: List[str], start_idx: int) -> int:
    brace_count, started = 0, False
    for scan_idx in range(start_idx, len(lines)):
        scan_line = lines[scan_idx]
        opens, closes = scan_line.count("{"), scan_line.count("}")
        if opens > 0:
            started = True
        brace_count += opens - closes
        if (started and brace_count <= 0) or (not started and ";" in scan_line):
            return scan_idx
    return start_idx


def _match_js_func_name(line: str) -> Optional[str]:
    m = _JS_FUNC_DECL_RE.search(line) or _JS_VAR_FUNC_RE.search(line)
    if m:
        return m.group(1)
    m_meth = _JS_METHOD_RE.search(line)
    if m_meth and m_meth.group(1) not in _JS_CONTROL_KEYWORDS:
        return m_meth.group(1)
    return None


def compute_js_fallback_max_cc(source_text: str) -> Tuple[int, str]:
    """Compute max per-function CC for JS/TS source without tree-sitter."""
    sanitized = strip_js_comments_and_strings(source_text)
    lines = sanitized.splitlines()
    funcs: List[Tuple[int, str]] = []
    idx = 0
    while idx < len(lines):
        name = _match_js_func_name(lines[idx])
        if not name:
            idx += 1
            continue
        end_idx = _scan_js_block_end(lines, idx)
        funcs.append((count_js_branches("\n".join(lines[idx : end_idx + 1])), name))
        idx = end_idx + 1
    return max(funcs, key=lambda item: item[0]) if funcs else (count_js_branches(sanitized), "<module>")


def compute_source_max_cc(source_text: str, suffix: str) -> Tuple[int, str]:
    """Compute max per-function cyclomatic complexity for Python or JS/TS source."""
    if not source_text or not source_text.strip():
        return (0, "<empty>")
    ext = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
    gate_mod = sys.modules.get("tools.gate")
    gate_ts = bool(getattr(gate_mod, "TREE_SITTER_AVAILABLE", True)) if gate_mod else True
    if gate_ts and bool(getattr(_crapper, "TREE_SITTER_AVAILABLE", False)):
        parser, _ = _crapper._get_parser_for_ext(ext)
        if parser is not None:
            return _ts_max_cc(parser, source_text.encode("utf-8"))
    if ext == ".py":
        py_res = compute_py_fallback_max_cc(source_text)
        if py_res is not None:
            return py_res
    return compute_js_fallback_max_cc(source_text)


def _ts_max_cc(parser: Any, source_bytes: bytes) -> Tuple[int, str]:
    root = parser.parse(source_bytes).root_node
    found: List[Tuple[int, str]] = []

    def _visit(node: Any) -> None:
        if node.type in _TS_FUNC_TYPES:
            found.append((_crapper._calc_node_complexity(node, source_bytes), _crapper._find_function_symbol(node, source_bytes)))
            return
        for child in node.children:
            _visit(child)

    _visit(root)
    return max(found, key=lambda item: item[0]) if found else (_crapper._calc_node_complexity(root, source_bytes), "<module>")


def count_source_sloc(content: str, suffix: str) -> int:
    """Count non-comment source lines of code."""
    if suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        from tools.audit.ts_discipline import _compute_sloc
        return _compute_sloc(content)
    return sum(1 for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("#"))
