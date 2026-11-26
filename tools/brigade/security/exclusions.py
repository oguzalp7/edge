"""Submodule: exclusions."""

from typing import Any, Dict, List, Optional, Set, Tuple
import ast
import hashlib

from tools.brigade.security.models import SecurityFinding, SecurityTrace

def _ast_call_name(func_node: ast.AST) -> str:
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute) and isinstance(func_node.value, ast.Name):
        return f"{func_node.value.id}.{func_node.attr}"
    return ""


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _collect_python_ast_exclusions(content: str) -> Optional[Set[int]]:
    """Collects line ranges of re.compile / _make_finding calls and docstrings via Python AST."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    excluded: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _ast_call_name(node.func) in ("re.compile", "_make_finding"):
            excluded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        elif isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            if _is_docstring_stmt(node.body[0]):
                doc = node.body[0]
                excluded.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return excluded


def _compute_js_excluded_lines(lines: List[str]) -> Set[int]:
    """Excludes blank lines and // or /* ... */ comment lines in JS/TS files."""
    excluded: Set[int] = set()
    in_block = False
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            excluded.add(idx)
            continue
        if in_block:
            excluded.add(idx)
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("//"):
            excluded.add(idx)
        elif stripped.startswith("/*"):
            if "*/" not in stripped[2:]:
                excluded.add(idx)
                in_block = True
            elif stripped.endswith("*/"):
                excluded.add(idx)
    return excluded


def _compute_excluded_lines(content: str, lines: List[str], is_python: bool) -> Set[int]:
    """Computes 1-based line numbers to exclude (comments, blanks, Python regex/finding metadata, docstrings)."""
    if not is_python:
        return _compute_js_excluded_lines(lines)

    ast_excl = _collect_python_ast_exclusions(content)
    excluded: Set[int] = set(ast_excl) if ast_excl is not None else set()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            excluded.add(idx)
        elif ast_excl is None and ("re.compile(" in line or "_make_finding(" in line):
            excluded.add(idx)
    return excluded


def _make_finding(
    attack_class: str,
    verdict: str,
    severity: Optional[str],
    rel: str,
    line_num: int,
    entrypoint: str,
    sink: str,
    evidence: str,
    boundary: str,
    rejection_reason: Optional[str] = None,
) -> SecurityFinding:
    fp_raw = f"{attack_class}:{rel}:{line_num}:{sink}"
    fp = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:12]
    fid = f"SEC-{fp[:8].upper()}"
    eff_sev = severity if verdict == "confirmed" else None
    trace = SecurityTrace(entrypoint=f"{rel}:{line_num}:{entrypoint}", propagation=[entrypoint], sink=sink).to_dict()
    return SecurityFinding(
        finding_id=fid,
        fingerprint=fp,
        verdict=verdict,
        severity=eff_sev,
        attack_class=attack_class,
        boundary=boundary,
        trace=trace,
        evidence=evidence.strip(),
        rejection_reason=rejection_reason,
        fix_target=rel,
    )
