"""
CRAPPER: Change Risk Anti-Patterns Complexity and LCOV Branch Risk Engine.
Calculates Cyclomatic Complexity (CC) and CRAP score using tree-sitter ASTs
and LCOV branch/line test coverage reports.
"""

import sys
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Any, Union

try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


@dataclass
class FunctionCrapMetric:
    file_path: str
    name: str
    start_line: int
    end_line: int
    complexity: int
    coverage_pct: Optional[float] = None
    crap_score: Optional[float] = None
    sloc: int = 0
    is_exported: bool = False


def compute_crap(cc: int, coverage_pct: float) -> float:
    """
    Computes the CRAP (Change Risk Anti-Patterns) score:
    CRAP(m) = CC(m)^2 * (1 - cov(m)/100)^3 + CC(m)
    """
    cov_clamped = max(0.0, min(100.0, float(coverage_pct)))
    risk_factor = (1.0 - (cov_clamped / 100.0)) ** 3
    crap = (cc ** 2) * risk_factor + cc
    return round(float(crap), 2)


def parse_lcov(lcov_content: str) -> Dict[str, Dict[str, Any]]:
    """
    Parses LCOV content into structured per-file line and branch hits.
    Returns: { file_path: { 'lines': {line: count}, 'branches': [(line, taken)] } }
    """
    records: Dict[str, Dict[str, Any]] = {}
    current_file: Optional[str] = None
    lines: Dict[int, int] = {}
    branches: List[Tuple[int, int]] = []

    for raw_line in lcov_content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("SF:"):
            current_file = line[3:].strip().replace("\\", "/")
            if current_file.startswith("./"):
                current_file = current_file[2:]
            lines = {}
            branches = []
        elif line.startswith("DA:"):
            parts = line[3:].split(",")
            if len(parts) >= 2:
                try:
                    l_no = int(parts[0])
                    hits = int(parts[1])
                    lines[l_no] = hits
                except ValueError:
                    pass
        elif line.startswith("BRDA:"):
            parts = line[5:].split(",")
            if len(parts) >= 4:
                try:
                    l_no = int(parts[0])
                    taken_raw = parts[3].strip()
                    taken = 0 if taken_raw == "-" else int(taken_raw)
                    branches.append((l_no, taken))
                except ValueError:
                    pass
        elif line == "end_of_record":
            if current_file:
                records[current_file] = {
                    "lines": lines,
                    "branches": branches,
                }
            current_file = None
            lines = {}
            branches = []

    if current_file:
        records[current_file] = {
            "lines": lines,
            "branches": branches,
        }
    return records


def function_coverage_from_lcov(file_cov: Optional[Dict[str, Any]], start_line: int, end_line: int) -> float:
    """
    Computes coverage percentage for lines [start_line, end_line].
    Prioritizes branch coverage when branches exist; falls back to line coverage.
    """
    if not file_cov:
        return 0.0

    branches = file_cov.get("branches", [])
    branches_in_range = [b for b in branches if start_line <= b[0] <= end_line]
    if branches_in_range:
        taken = sum(1 for b in branches_in_range if b[1] > 0)
        return round(float(taken) / float(len(branches_in_range)) * 100.0, 2)

    lines = file_cov.get("lines", {})
    lines_in_range = [count for line, count in lines.items() if start_line <= line <= end_line]
    if lines_in_range:
        hit = sum(1 for count in lines_in_range if count > 0)
        return round(float(hit) / float(len(lines_in_range)) * 100.0, 2)

    return 0.0


def discover_existing_lcov(repo_root: Union[Path, str]) -> Optional[Path]:
    """Scans repository root for existing LCOV coverage files."""
    root = Path(repo_root)
    candidates = [
        root / "coverage" / "lcov.info",
        root / ".coverage" / "lcov.info",
        root / "target" / "coverage" / "lcov.info",
        root / "lcov.info",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def _get_parser_for_ext(ext: str):
    if not TREE_SITTER_AVAILABLE:
        return None, None
    ext = ext.lower()
    if ext in (".ts",):
        return tslp.get_parser("typescript"), "typescript"
    elif ext in (".tsx", ".jsx"):
        return tslp.get_parser("tsx"), "tsx"
    elif ext in (".js", ".mjs", ".cjs"):
        return tslp.get_parser("javascript"), "javascript"
    elif ext in (".py",):
        return tslp.get_parser("python"), "python"
    return None, None


def _calc_node_complexity(node: Any, source_bytes: bytes) -> int:
    """Computes cyclomatic complexity of an AST subtree."""
    branching_types = {
        "if_statement",
        "while_statement",
        "for_statement",
        "for_in_statement",
        "catch_clause",
        "except_clause",
        "switch_case",
        "case_clause",
        "ternary_expression",
        "conditional_expression",
    }
    comp = 1

    def _walk(n: Any):
        nonlocal comp
        if n.type in branching_types:
            comp += 1
        elif n.type in ("binary_expression", "logical_expression"):
            op = n.child_by_field_name("operator")
            if op:
                op_text = source_bytes[op.start_byte:op.end_byte].decode("utf-8", errors="ignore").strip()
                if op_text in ("&&", "||"):
                    comp += 1
            else:
                for c in n.children:
                    token = source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore").strip()
                    if token in ("&&", "||"):
                        comp += 1
                        break
        elif n.type == "boolean_operator":
            comp += 1

        for child in n.children:
            _walk(child)

    _walk(node)
    return comp


def _find_function_symbol(node: Any, source_bytes: bytes) -> str:
    name_node = node.child_by_field_name("name")
    if name_node:
        return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
    p = node.parent
    if p and p.type == "variable_declarator":
        var_name = p.child_by_field_name("name")
        if var_name:
            return source_bytes[var_name.start_byte:var_name.end_byte].decode("utf-8", errors="ignore")
    for c in node.children:
        if c.type in ("identifier", "property_identifier"):
            return source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore")
    return f"anonymous_L{node.start_point[0] + 1}"


def analyze_file_crap(
    file_path: Union[Path, str],
    rel_path: str,
    lcov_data: Optional[Dict[str, Any]] = None
) -> List[FunctionCrapMetric]:
    """
    Extracts functions from a source file via tree-sitter AST,
    calculates cyclomatic complexity, and computes CRAP score if coverage is provided.
    """
    if not TREE_SITTER_AVAILABLE:
        return []

    p = Path(file_path)
    if not p.exists():
        return []

    parser, lang = _get_parser_for_ext(p.suffix)
    if not parser:
        return []

    try:
        source_bytes = p.read_bytes()
    except Exception:
        return []

    tree = parser.parse(source_bytes)
    root = tree.root_node

    function_types = {
        "function_declaration",
        "function_definition",
        "arrow_function",
        "method_definition",
        "function_expression",
    }

    metrics: List[FunctionCrapMetric] = []

    def _visit(node: Any):
        if node.type in function_types:
            start_l = node.start_point[0] + 1
            end_l = node.end_point[0] + 1
            sloc = max(1, end_l - start_l + 1)
            name = _find_function_symbol(node, source_bytes)
            complexity = _calc_node_complexity(node, source_bytes)

            is_exported = False
            cur_p = node.parent
            while cur_p and cur_p.type not in ("program", "module"):
                if cur_p.type in ("export_statement", "export_declaration"):
                    is_exported = True
                    break
                cur_p = cur_p.parent

            cov_pct = None
            crap = None
            if lcov_data is not None:
                cov_pct = function_coverage_from_lcov(lcov_data, start_l, end_l)
                crap = compute_crap(complexity, cov_pct)

            metrics.append(FunctionCrapMetric(
                file_path=rel_path,
                name=name,
                start_line=start_l,
                end_line=end_l,
                complexity=complexity,
                coverage_pct=cov_pct,
                crap_score=crap,
                sloc=sloc,
                is_exported=is_exported,
            ))
            return  # Do not descend into nested functions

        for child in node.children:
            _visit(child)

    _visit(root)
    return metrics
