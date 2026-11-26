"""
Metric computation helpers (SLOC, indent, CC, exports, function bounds) for TypeScriptAdapter.
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple

from tools.audit.models import FunctionMetrics

_CC_PATTERNS = (
    r"\bif\b", r"\belse\s+if\b", r"\bswitch\b", r"\bcase\b", r"\bwhile\b",
    r"\bfor\b", r"\bcatch\b", r"&&", r"\|\|", r"\?\?", r"\?[^:.\s]+\s*:",
)
_EXPORT_PATTERNS = (
    r"\bexport\s+default\b", r"\bexport\s+(?:async\s+)?function\b",
    r"\bexport\s+(?:const|let|var)\b", r"\bexport\s+class\b",
    r"\bexport\s+(?:type|interface)\b", r"\bexport\s+enum\b", r"\bexport\s*\{[^}]+\}",
)
_FUNC_SIG_RE = re.compile(
    r"^(?:\s*export\s+)?(?:async\s+)?(?:function\s+(\w+)|(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?function)"
)


def count_ts_lines(lines: List[str]) -> Tuple[int, int, int, int]:
    total = len(lines)
    blank, comment, in_multiline = 0, 0, False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank += 1
            continue
        if in_multiline:
            comment += 1
            in_multiline = "*/" not in stripped
            continue
        if stripped.startswith("/*"):
            comment += 1
            in_multiline = ("*/" not in stripped) or (stripped.count("/*") > stripped.count("*/"))
            continue
        if stripped.startswith("//"):
            comment += 1
    return total, (total - blank - comment), comment, blank


def calc_ts_max_indent(lines: List[str]) -> int:
    space_indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip() and (len(l) - len(l.lstrip(" "))) > 0]
    indent_unit = 2
    if space_indents and min(space_indents) >= 4 and (sum(1 for i in space_indents if i % 4 == 0) / len(space_indents)) >= 0.5:
        indent_unit = 4
    max_indent = 0
    for line in lines:
        if not line.strip():
            continue
        tabs = len(line) - len(line.lstrip("\t"))
        spaces = len(line) - len(line.lstrip(" "))
        level = tabs if tabs > 0 else spaces // indent_unit
        max_indent = max(max_indent, level)
    return min(max_indent, 20)


def calc_ts_complexity(content: str) -> int:
    return 1 + sum(len(re.findall(pat, content)) for pat in _CC_PATTERNS)


def count_ts_exports(content: str) -> int:
    return sum(len(re.findall(pat, content)) for pat in _EXPORT_PATTERNS)


def _scan_brace_end(lines: List[str], start_idx: int) -> int:
    brace_count, started = 0, False
    for scan_idx in range(start_idx, min(start_idx + 500, len(lines))):
        scan_line = lines[scan_idx]
        brace_count += scan_line.count("{") - scan_line.count("}")
        started = started or ("{" in scan_line)
        if started and brace_count <= 0:
            return scan_idx + 1
    return start_idx + 1


def find_ts_functions(
    lines: List[str], path: Optional[Path] = None, rel_path: Optional[str] = None
) -> List[FunctionMetrics]:
    try:
        from tools.audit.crapper import TREE_SITTER_AVAILABLE, analyze_file_crap
        crap_metrics = analyze_file_crap(path, rel_path or str(path)) if (TREE_SITTER_AVAILABLE and path and path.exists()) else []
        if crap_metrics:
            return [
                FunctionMetrics(name=m.name, start_line=m.start_line, end_line=m.end_line, sloc=m.sloc, complexity=m.complexity, is_exported=m.is_exported)
                for m in crap_metrics
            ]
    except Exception:
        pass

    funcs: List[FunctionMetrics] = []
    for idx in range(min(len(lines), 3000)):
        line = lines[idx]
        match = _FUNC_SIG_RE.search(line)
        if not match:
            continue
        name = match.group(1) or match.group(2) or match.group(3) or "anonymous"
        start_line = idx + 1
        end_line = _scan_brace_end(lines, idx)
        func_body = "\n".join(lines[start_line - 1 : end_line])
        funcs.append(FunctionMetrics(
            name=name,
            start_line=start_line,
            end_line=end_line,
            sloc=max(1, end_line - start_line + 1),
            complexity=calc_ts_complexity(func_body),
            is_exported=("export" in line),
        ))
    return funcs
