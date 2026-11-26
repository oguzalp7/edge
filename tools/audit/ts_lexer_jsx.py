"""
JSX tag and children scanning helpers for the TypeScript/TSX single-pass lexer.
"""

from __future__ import annotations

from tools.audit.ts_lexer_state import LexerState, consume_template_step, is_generic_arrow_ahead


def _consume_quoted_in_attr(st: LexerState, quote: str) -> None:
    st.emit_char(st.i, quote)
    st.i += 1
    while st.i < st.n:
        ac = st.source[st.i]
        if ac == "\n":
            st.emit_newline(st.i)
            st.i += 1
            return
        if ac == "\\" and st.i + 1 < st.n:
            st.i += 2
            continue
        if ac == quote:
            st.emit_char(st.i, quote)
            st.i += 1
            return
        st.i += 1


def _is_self_closing_slash(source: str, tag_start: int, close_gt_idx: int) -> bool:
    k = close_gt_idx - 1
    while k > tag_start and source[k] in (" ", "\t", "\n", "\r"):
        k -= 1
    return k > tag_start and source[k] == "/"


def consume_jsx_tag(st: LexerState) -> None:
    tag_start = st.i
    st.emit_char(st.i, "<")
    st.i += 1
    attr_brace, self_closing = 0, False
    while st.i < st.n:
        tc = st.source[st.i]
        if tc == "\n":
            st.emit_newline(st.i)
        elif tc in ("'", '"'):
            _consume_quoted_in_attr(st, tc)
            continue
        elif tc in ("{", "}"):
            st.emit_char(st.i, tc)
            attr_brace = attr_brace + 1 if tc == "{" else max(0, attr_brace - 1)
        elif tc == ">" and attr_brace == 0:
            self_closing = _is_self_closing_slash(st.source, tag_start, st.i)
            st.emit_char(st.i, ">")
            st.i += 1
            break
        else:
            st.emit_char(st.i, tc)
        st.i += 1
    if not self_closing:
        st.stack.append(["jsx_children"])
        st.prev_kind = "op"
    else:
        st.prev_kind = "close"


def _consume_closing_jsx_tag(st: LexerState) -> bool:
    st.emit_char(st.i, "<")
    st.emit_char(st.i + 1, "/")
    st.i += 2
    while st.i < st.n and st.source[st.i] != ">":
        st.emit_newline(st.i) if st.source[st.i] == "\n" else st.emit_char(st.i, st.source[st.i])
        st.i += 1
    if st.i < st.n and st.source[st.i] == ">":
        st.emit_char(st.i, ">")
        st.i += 1
    if len(st.stack) > 1:
        st.stack.pop()
    st.prev_kind = "close"
    return True


def consume_jsx_children_step(st: LexerState) -> bool:
    """Handles one step inside jsx_children. Returns True if handled, False to fall through to JSX tag open."""
    ch = st.source[st.i]
    if ch == "\n":
        st.emit_newline(st.i)
        st.i += 1
        return True
    if ch == "{":
        st.emit_char(st.i, "{")
        st.stack.append(["jsx_expr", 1])
        st.prev_kind = "punct"
        st.i += 1
        return True
    if ch == "<" and st.i + 1 < st.n:
        nxt = st.source[st.i + 1]
        if nxt == "/":
            return _consume_closing_jsx_tag(st)
        if nxt.isalpha() or nxt in ("_", "$", ">"):
            st.prev_kind = "op"
            return False
    st.i += 1
    return True
