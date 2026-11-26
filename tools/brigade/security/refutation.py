"""Submodule: refutation."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.brigade.security.constants import _EXPORT_SPEC_RE, _FN_START_RE, _PY_FN_START_RE
from tools.brigade.security.js_masker import _mask_js_comments_and_strings

@dataclass
class _FnDef:
    name: str
    start_line: int
    end_line: int
    is_exported: bool


def _extract_reexported_names(masked_content: str) -> Set[str]:
    names: Set[str] = set()
    for m in _EXPORT_SPEC_RE.finditer(masked_content):
        for item in m.group(1).split(","):
            tok = item.strip().split(" as ")[0].strip()
            if tok:
                names.add(tok)
    return names


def _extract_python_fn_defs(lines: List[str]) -> List[_FnDef]:
    defs: List[_FnDef] = []
    for idx, line in enumerate(lines, start=1):
        if line[:1].isspace() or not (m := _PY_FN_START_RE.match(line)):
            continue
        if defs:
            defs[-1].end_line = idx - 1
        defs.append(_FnDef(name=m.group(1), start_line=idx, end_line=len(lines), is_exported=True))
    return defs


def _extract_top_level_fn_defs(
    lines: List[str],
    masked_lines: List[str],
    is_python: bool = False,
) -> List[_FnDef]:
    if is_python:
        return _extract_python_fn_defs(lines)
    reexported = _extract_reexported_names("\n".join(masked_lines))
    defs: List[_FnDef] = []
    brace_depth = 0
    for idx, mline in enumerate(masked_lines, start=1):
        stripped = mline.strip()
        if brace_depth == 0 and stripped and (m := _FN_START_RE.match(stripped)):
            if defs:
                defs[-1].end_line = idx - 1
            name = m.group(1) or m.group(2) or "handler"
            defs.append(_FnDef(name=name, start_line=idx, end_line=len(lines), is_exported=stripped.startswith("export ") or name in reexported))
        brace_depth = max(0, brace_depth + mline.count("{") - mline.count("}"))
    return defs


def _enclosing_fn_ranges(lines: List[str], is_python: bool = False) -> Dict[int, Tuple[int, str]]:
    masked_lines = lines if is_python else _mask_js_comments_and_strings("\n".join(lines)).splitlines()
    if len(masked_lines) < len(lines):
        masked_lines.extend([""] * (len(lines) - len(masked_lines)))
    defs = _extract_top_level_fn_defs(lines, masked_lines, is_python=is_python)
    mapping: Dict[int, Tuple[int, str]] = {}
    def_idx = 0
    for line_no in range(1, len(lines) + 1):
        while def_idx < len(defs) and line_no > defs[def_idx].end_line:
            def_idx += 1
        if def_idx < len(defs) and defs[def_idx].start_line <= line_no <= defs[def_idx].end_line:
            mapping[line_no] = (defs[def_idx].start_line, defs[def_idx].name)
        else:
            mapping[line_no] = (1, "module")
    return mapping


