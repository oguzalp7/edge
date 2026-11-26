"""
Single-pass TypeScript/TSX source sanitizer masking comments, strings, regexes, and JSX text.
"""

from __future__ import annotations

from typing import List, Tuple

from tools.audit.ts_lexer_jsx import (
    LexerState,
    consume_jsx_children_step,
    consume_jsx_tag,
    consume_template_step,
    is_generic_arrow_ahead,
)
from tools.audit.ts_lexer_literals import (
    _can_start_regex,
    _scan_block_comment,
    _scan_line_comment,
    _scan_quoted_string,
    _scan_regex_literal,
)
from tools.audit.ts_models import _NON_NULL_PRECEDING_KEYWORDS

_EXPRESSION_KEYWORDS = _NON_NULL_PRECEDING_KEYWORDS | frozenset(("export", "import", "as", "satisfies"))
_PUNCT_KINDS = {")": "close", "]": "close", "(": "punct", "[": "punct", ",": "punct", ";": "punct", ":": "punct"}


def _scan_slash(st: LexerState) -> None:
    nxt = st.source[st.i + 1] if st.i + 1 < st.n else ""
    if nxt == "/":
        _scan_line_comment(st)
    elif nxt == "*":
        _scan_block_comment(st)
    elif _can_start_regex(st.prev_kind):
        _scan_regex_literal(st)
    else:
        st.emit_char(st.i, "/")
        st.prev_kind = "op"
        st.i += 1


def _scan_brace(st: LexerState, state: str, ch: str) -> None:
    st.emit_char(st.i, ch)
    if state in ("tpl_expr", "jsx_expr"):
        st.stack[-1][1] += 1 if ch == "{" else -1
        if ch == "}" and st.stack[-1][1] == 0:
            st.stack.pop()
            st.prev_kind = "close" if st.stack[-1][0] == "jsx_children" else "punct"
            st.i += 1
            return
    st.prev_kind = "punct"
    st.i += 1


def _scan_ident_or_num(st: LexerState, ch: str) -> None:
    if ch.isalpha() or ch in ("_", "$"):
        start = st.i
        while st.i < st.n and (st.source[st.i].isalnum() or st.source[st.i] in ("_", "$")):
            st.emit_char(st.i, st.source[st.i])
            st.i += 1
        st.prev_kind = "kw_expr" if st.source[start : st.i] in _EXPRESSION_KEYWORDS else "ident"
        return
    while st.i < st.n and (st.source[st.i].isalnum() or st.source[st.i] in (".", "_")):
        st.emit_char(st.i, st.source[st.i])
        st.i += 1
    st.prev_kind = "number"


def _scan_code_token(st: LexerState, state: str, is_tsx: bool) -> None:
    ch = st.source[st.i]
    if ch == "\n":
        st.emit_newline(st.i)
        st.i += 1
        return
    if ch in (" ", "\t", "\r", "\v", "\f"):
        st.emit_char(st.i, ch)
        st.i += 1
        return
    if ch == "/":
        _scan_slash(st)
        return
    if ch in ("'", '"'):
        _scan_quoted_string(st, ch)
        return
    if ch == "`":
        st.emit_char(st.i, "`")
        st.stack.append(["template"])
        st.prev_kind = "punct"
        st.i += 1
        return
    can_jsx = state == "jsx_children" or (
        _can_start_regex(st.prev_kind) and st.i + 1 < st.n and (st.source[st.i + 1].isalpha() or st.source[st.i + 1] in ("_", "$", ">"))
    )
    if is_tsx and ch == "<" and can_jsx and not is_generic_arrow_ahead(st.source, st.i):
        consume_jsx_tag(st)
        return
    if ch in ("{", "}"):
        _scan_brace(st, state, ch)
    elif ch.isalnum() or ch in ("_", "$"):
        _scan_ident_or_num(st, ch)
    else:
        st.emit_char(st.i, ch)
        st.prev_kind = _PUNCT_KINDS.get(ch, "op")
        st.i += 1


def _sanitize_ts_source(source: str, is_tsx: bool) -> Tuple[str, List[Tuple[int, str]]]:
    """Single-pass TypeScript/TSX lexer masking comments, strings, regexes, and JSX text."""
    st = LexerState(source=source, out=[" "] * len(source), comments=[])
    while st.i < st.n:
        state = st.stack[-1][0]
        if state == "jsx_children" and consume_jsx_children_step(st):
            continue
        if state == "template":
            consume_template_step(st)
            continue
        _scan_code_token(st, state, is_tsx)
    return "".join(st.out), st.comments
