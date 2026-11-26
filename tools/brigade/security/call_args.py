"""Submodule: call_args."""

from typing import Any, Dict, List, Optional, Set, Tuple
import re

from tools.brigade.security.constants import _ABAC_GUARD_RE, _POLICY_AUTH_FIELD_RE, _READ_ONLY_REPO_METHOD_RE, _RUN_ACTION_CALL_RE, _TOKEN_GUARD_RE
from tools.brigade.security.js_masker import _mask_js_comments_and_strings

def _skip_balanced_generics(text: str, start: int) -> int:
    """Advances index past balanced `<...>` TypeScript generic arguments."""
    depth = 0
    brace_depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "{(":
            brace_depth += 1
        elif ch in "})" and brace_depth > 0:
            brace_depth -= 1
        elif brace_depth == 0 and ch == "<":
            depth += 1
        elif brace_depth == 0 and ch == ">" and (i == 0 or text[i - 1] != "="):
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return start


def _read_first_call_arg(text: str, start: int) -> str:
    """Extracts the first argument expression from a call respecting nested brackets."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            if depth == 0:
                return text[start:i].strip()
            depth -= 1
        elif ch == "," and depth == 0:
            return text[start:i].strip()
        i += 1
    return text[start:].strip()


def _extract_action_policy_args(upstream: str) -> List[Tuple[str, str]]:
    """Extracts `(fn_name, masked_first_arg)` pairs for runAction/executeAction calls."""
    masked = _mask_js_comments_and_strings(upstream)
    results: List[Tuple[str, str]] = []
    n = len(masked)
    for m in _RUN_ACTION_CALL_RE.finditer(masked):
        pos = m.end()
        while pos < n and masked[pos].isspace():
            pos += 1
        if pos < n and masked[pos] == "<":
            pos = _skip_balanced_generics(masked, pos)
            while pos < n and masked[pos].isspace():
                pos += 1
        if pos >= n or masked[pos] != "(":
            continue
        arg_start = pos + 1
        while arg_start < n and masked[arg_start].isspace():
            arg_start += 1
        results.append((m.group(1), _read_first_call_arg(masked, arg_start)))
    return results


