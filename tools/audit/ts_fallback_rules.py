"""
Specialized fallback rule scanners (non-null, switch, optional bag, positional args).
"""

from __future__ import annotations

import re
from typing import List, Tuple

from tools.audit.ts_fallback_helpers import (
    _check_bag_segments,
    _extract_switch_default_block,
    _find_matching_delimiter,
    _split_top_level_properties,
)
from tools.audit.ts_fallback_sig_rules import _collect_signature_candidates, scan_positional_args
from tools.audit.ts_models import (
    _NEVER_BINDING_RE,
    _NON_NULL_PRECEDING_KEYWORDS,
    TsDisciplineFinding,
    _offset_to_line,
    make_finding,
)


def _is_non_null_bang(masked: str, idx: int) -> bool:
    n = len(masked)
    if idx == 0 or not (masked[idx - 1].isalnum() or masked[idx - 1] in ("_", "$", ")", "]")):
        return False
    if masked[idx - 1].isalnum() or masked[idx - 1] in ("_", "$"):
        k = idx - 1
        while k >= 0 and (masked[k].isalnum() or masked[k] in ("_", "$")):
            k -= 1
        if masked[k + 1 : idx] in _NON_NULL_PRECEDING_KEYWORDS:
            return False
    next_ch = masked[idx + 1] if idx + 1 < n else ""
    return not (next_ch == "=" or next_ch.isalnum() or next_ch in ("_", "$", "("))


def scan_non_null_assertions(
    masked: str, line_starts: List[int], lines: List[str]
) -> List[TsDisciplineFinding]:
    return [
        make_finding(
            "RULE-TS-NON-NULL", "WARNING", -10, _offset_to_line(line_starts, idx), "!",
            "Non-null assertion (`!`) suppresses null/undefined checks at runtime.",
            "Narrow explicitly (`if (!value) ...` or `.at(0)`) instead of postfix `!`.", lines,
        )
        for idx, ch in enumerate(masked)
        if ch == "!" and _is_non_null_bang(masked, idx)
    ]


def scan_switch_exhaustiveness(
    masked: str, line_starts: List[int], lines: List[str]
) -> Tuple[List[TsDisciplineFinding], bool]:
    findings: List[TsDisciplineFinding] = []
    has_never_bonus = False
    n = len(masked)
    for m in re.finditer(r"\bswitch\s*\(", masked):
        close_paren = _find_matching_delimiter(masked, m.end() - 1, "(", ")")
        if close_paren < 0:
            continue
        brace_idx = close_paren + 1
        while brace_idx < n and masked[brace_idx].isspace():
            brace_idx += 1
        if brace_idx >= n or masked[brace_idx] != "{":
            continue
        close_brace = _find_matching_delimiter(masked, brace_idx, "{", "}")
        if close_brace < 0:
            continue
        default_block = _extract_switch_default_block(masked[brace_idx : close_brace + 1])
        if default_block is not None and _NEVER_BINDING_RE.search(default_block):
            has_never_bonus = True
        else:
            findings.append(make_finding(
                "RULE-TS-SWITCH-EXHAUSTIVE", "WARNING", -8, _offset_to_line(line_starts, m.start()), "switch",
                "`switch` statement lacks an exhaustive `default:` branch with a `: never` binding.",
                "Add `default: { const _exhaustive: never = value; throw new Error(...); }`.", lines,
            ))
    return findings, has_never_bonus


def scan_optional_bags(masked: str, line_starts: List[int], lines: List[str]) -> List[TsDisciplineFinding]:
    findings: List[TsDisciplineFinding] = []
    bag_patterns = (
        re.compile(r"\binterface\s+([A-Za-z_$][\w$]*)(?:\s*<[^>]*>)?(?:\s+extends\s+[^{]+)?\s*\{"),
        re.compile(r"\btype\s+([A-Za-z_$][\w$]*)(?:\s*<[^>]*>)?\s*=\s*\{"),
    )
    for pat in bag_patterns:
        for m in pat.finditer(masked):
            close_b = _find_matching_delimiter(masked, m.end() - 1, "{", "}")
            if close_b < 0 or not _check_bag_segments(_split_top_level_properties(masked[m.end() : close_b])):
                continue
            sym = m.group(1)
            findings.append(make_finding(
                "RULE-TS-OPTIONAL-BAG", "ADVISORY", -6, _offset_to_line(line_starts, m.start()), sym,
                f"Type `{sym}` models state with a status boolean and optional fields instead of a discriminated union.",
                "Refactor into a discriminated union with an explicit literal `status` or `kind` field.", lines,
            ))
    return findings
