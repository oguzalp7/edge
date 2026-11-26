"""Submodule: js_masker."""

from typing import Any, List


def _scan_template_step(content: str, i: int, n: int, out: List[str], stack: List[List[Any]]) -> int:
    ch = content[i]
    if ch == "\\" and i + 1 < n:
        if content[i + 1] == "\n":
            out[i + 1] = "\n"
        return i + 2
    if ch == "`":
        stack.pop()
        return i + 1
    if ch == "$" and i + 1 < n and content[i + 1] == "{":
        out[i], out[i + 1] = "$", "{"
        stack.append(["tpl_expr", 1])
        return i + 2
    return i + 1


def _skip_block_comment(content: str, i: int, n: int, out: List[str]) -> int:
    i += 2
    while i < n:
        if content[i] == "*" and i + 1 < n and content[i + 1] == "/":
            return i + 2
        if content[i] == "\n":
            out[i] = "\n"
        i += 1
    return i


def _skip_quoted_literal(content: str, i: int, n: int, out: List[str], quote: str) -> int:
    i += 1
    while i < n:
        sc = content[i]
        if sc == "\n":
            out[i] = "\n"
            return i + 1
        if sc == "\\" and i + 1 < n:
            if content[i + 1] == "\n":
                out[i + 1] = "\n"
            i += 2
            continue
        if sc == quote:
            return i + 1
        i += 1
    return i


def _update_tpl_braces(state: str, ch: str, stack: List[List[Any]]) -> None:
    if state != "tpl_expr":
        return
    if ch == "{":
        stack[-1][1] += 1
    elif ch == "}":
        stack[-1][1] -= 1
        if stack[-1][1] == 0:
            stack.pop()


def _mask_js_comments_and_strings(content: str) -> str:
    """Masks JS/TS comments and string bodies with spaces while preserving newlines and ${...} braces."""
    n, out, stack, i = len(content), [" "] * len(content), [["code"]], 0
    while i < n:
        state, ch = stack[-1][0], content[i]
        if ch == "\n":
            out[i] = "\n"
            i += 1
        elif state == "template":
            i = _scan_template_step(content, i, n, out, stack)
        elif ch == "/" and i + 1 < n and content[i + 1] == "/":
            i = content.find("\n", i + 2)
            i = n if i < 0 else i
        elif ch == "/" and i + 1 < n and content[i + 1] == "*":
            i = _skip_block_comment(content, i, n, out)
        elif ch in ("'", '"'):
            i = _skip_quoted_literal(content, i, n, out, ch)
        elif ch == "`":
            stack.append(["template"])
            i += 1
        else:
            _update_tpl_braces(state, ch, stack)
            out[i] = ch
            i += 1
    return "".join(out)
