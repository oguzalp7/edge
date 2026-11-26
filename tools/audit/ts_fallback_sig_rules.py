"""
Positional parameter / signature fallback rule scanner for TS/TSX files.
"""

from __future__ import annotations

import re
from typing import List, Set, Tuple

from tools.audit.ts_fallback_delims import (
    _find_matching_delimiter,
    _split_top_level_commas,
    _strip_default_value,
)
from tools.audit.ts_models import (
    _ARROW_VAR_SIG_RE,
    _CONTROL_KEYWORDS,
    _FUNC_DECL_SIG_RE,
    _ID_PARAM_RE,
    _METHOD_SIG_RE,
    TsDisciplineFinding,
    _offset_to_line,
    make_finding,
)


def _collect_signature_candidates(masked: str) -> List[Tuple[int, str, int]]:
    seen: Set[int] = set()
    candidates: List[Tuple[int, str, int]] = []
    for regex, default_name in ((_FUNC_DECL_SIG_RE, "anonymous"), (_ARROW_VAR_SIG_RE, "anonymous")):
        for m in regex.finditer(masked):
            if (p_idx := m.end() - 1) not in seen:
                seen.add(p_idx)
                candidates.append((m.start(), m.group(1) or default_name, p_idx))

    for m in _METHOD_SIG_RE.finditer(masked):
        name, p_idx = m.group(1), m.end() - 1
        if name in _CONTROL_KEYWORDS or p_idx in seen:
            continue
        close_p = _find_matching_delimiter(masked, p_idx, "(", ")")
        if close_p < 0 or not re.match(r"^(?::\s*[^=>{;]+)?(?:\{|=>)", masked[close_p + 1 :].lstrip()):
            continue
        seen.add(p_idx)
        candidates.append((m.start(), name, p_idx))
    return candidates


def scan_positional_args(masked: str, line_starts: List[int], lines: List[str]) -> List[TsDisciplineFinding]:
    findings: List[TsDisciplineFinding] = []
    for sig_start, sym, open_p in _collect_signature_candidates(masked):
        close_p = _find_matching_delimiter(masked, open_p, "(", ")")
        params_raw = masked[open_p + 1 : close_p].strip() if close_p >= 0 else ""
        if not params_raw:
            continue
        positional_count, id_param_count = 0, 0
        for p in _split_top_level_commas(params_raw):
            p_clean = _strip_default_value(p)
            if re.match(r"^this(?:\s*:|\s*$)", p_clean):
                continue
            positional_count += 1
            if _ID_PARAM_RE.match(p_clean):
                id_param_count += 1
        if positional_count >= 4 or id_param_count >= 2:
            findings.append(make_finding(
                "RULE-TS-POSITIONAL-ARGS", "ADVISORY", -5, _offset_to_line(line_starts, sig_start), sym,
                f"Function `{sym}` takes {positional_count} positional / {id_param_count} `*Id` parameter(s).",
                "Group parameters into a single named options object ({ ... }); skip only on documented hot paths.", lines,
            ))
    return findings
