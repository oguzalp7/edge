"""
Delimiter balancing and top-level argument/property splitting for TS fallback analyzer.
"""

from __future__ import annotations

from typing import List

_OPEN_DELIMS = {"(": 0, "{": 1, "[": 2, "<": 3}
_CLOSE_DELIMS = {")": 0, "}": 1, "]": 2}


def _find_matching_delimiter(text: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == open_ch:
            depth += 1
        elif text[i] == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _find_matching_open_delimiter(text: str, close_idx: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(close_idx, -1, -1):
        if text[i] == close_ch:
            depth += 1
        elif text[i] == open_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _advance_depths(text: str, i: int, depths: List[int]) -> None:
    ch = text[i]
    if ch in _OPEN_DELIMS:
        depths[_OPEN_DELIMS[ch]] += 1
    elif ch in _CLOSE_DELIMS and depths[_CLOSE_DELIMS[ch]] > 0:
        depths[_CLOSE_DELIMS[ch]] -= 1
    elif ch == ">" and depths[3] > 0 and not (i > 0 and text[i - 1] == "="):
        depths[3] -= 1


def _split_top_level_delimited(text: str, seps: tuple[str, ...]) -> List[str]:
    parts: List[str] = []
    depths = [0, 0, 0, 0]
    start = 0
    for i, ch in enumerate(text):
        _advance_depths(text, i, depths)
        if ch in seps and not any(depths):
            if (seg := text[start:i].strip()):
                parts.append(seg)
            start = i + 1
    if (tail := text[start:].strip()):
        parts.append(tail)
    return parts


def _split_top_level_commas(text: str) -> List[str]:
    return _split_top_level_delimited(text, (",",))


def _split_top_level_properties(body_inner: str) -> List[str]:
    return _split_top_level_delimited(body_inner, (";", ",", "\n"))


def _strip_default_value(param_str: str) -> str:
    depths = [0, 0, 0, 0]
    n = len(param_str)
    for i, ch in enumerate(param_str):
        _advance_depths(param_str, i, depths)
        if ch == "=" and not any(depths):
            if i + 1 < n and param_str[i + 1] == ">":
                continue
            return param_str[:i].strip()
    return param_str.strip()
