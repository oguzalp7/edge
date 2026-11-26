"""
Masking, LHS inspection, and switch/object-bag helpers for TS fallback analyzer.
"""

from __future__ import annotations

import re
from typing import List, Optional

from tools.audit.ts_fallback_delims import (
    _advance_depths,
    _find_matching_delimiter,
    _find_matching_open_delimiter,
    _split_top_level_commas,
    _split_top_level_delimited,
    _split_top_level_properties,
    _strip_default_value,
)
from tools.audit.ts_models import _PROP_SIG_RE, _STATUS_BOOLEAN_NAMES

_DEFAULT_CASE_RE = re.compile(r"(?<![A-Za-z0-9_$])default\s*:")
_NEXT_CASE_RE = re.compile(r"(?<![A-Za-z0-9_$])case\s")
_IMPORT_ALIAS_RE = re.compile(
    r"\bimport\s+(?:type\s+)?(?:\*\s+as\s+[A-Za-z_$][\w$]*|\{[^}]*\}|[A-Za-z_$][\w$]*(?:\s*,\s*\{[^}]*\})?)\s*(?:from\b)?"
)
_EXPORT_ALIAS_RE = re.compile(r"\bexport\s+(?:\*\s+as\s+[A-Za-z_$][\w$]*|(?:type\s+)?\{[^}]*\})")


def _skip_ws_backwards(text: str, idx: int) -> int:
    while idx >= 0 and text[idx].isspace():
        idx -= 1
    return idx


def _is_object_or_array_literal_lhs(masked: str, as_start: int) -> bool:
    idx = _skip_ws_backwards(masked, as_start - 1)
    while idx >= 0 and masked[idx] == ")":
        open_p = _find_matching_open_delimiter(masked, idx, "(", ")")
        if open_p < 0:
            return False
        idx = _skip_ws_backwards(masked, open_p - 1)
    if idx < 0 or masked[idx] not in ("}", "]"):
        return False
    open_d = _find_matching_open_delimiter(masked, idx, "{" if masked[idx] == "}" else "[", masked[idx])
    if open_d < 0:
        return False
    before = _skip_ws_backwards(masked, open_d - 1)
    return before < 0 or masked[before] in ("=", "(", "[", ",", ":", "?", ">") or masked[max(0, before - 5) : before + 1].endswith("return")


def _mask_span(chars: List[str], start: int, end: int) -> None:
    for idx in range(max(0, start), min(len(chars), end)):
        if chars[idx] != "\n":
            chars[idx] = " "


def _mask_import_export_aliases(masked: str) -> str:
    chars = list(masked)
    for pat in (_IMPORT_ALIAS_RE, _EXPORT_ALIAS_RE):
        for m in pat.finditer(masked):
            _mask_span(chars, m.start(), m.end())
    return "".join(chars)


def _extract_switch_default_block(body_text: str) -> Optional[str]:
    depth, default_start = 0, None
    for i, ch in enumerate(body_text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            if default_start is not None and depth == 1:
                return body_text[default_start:i]
            depth -= 1
        elif depth == 1 and default_start is None and (dm := _DEFAULT_CASE_RE.match(body_text, i)):
            default_start = dm.end()
        elif depth == 1 and default_start is not None and i >= default_start and _NEXT_CASE_RE.match(body_text, i):
            return body_text[default_start:i]
    return body_text[default_start:] if default_start is not None else None


def _check_bag_segments(segments: List[str]) -> bool:
    has_status_bool, optional_count = False, 0
    for seg in segments:
        if not (m := _PROP_SIG_RE.match(seg)):
            continue
        if m.group(2) == "?":
            optional_count += 1
        if m.group(1) in _STATUS_BOOLEAN_NAMES and re.search(r"\bboolean\b", m.group(3)):
            has_status_bool = True
    return has_status_bool and optional_count >= 2
