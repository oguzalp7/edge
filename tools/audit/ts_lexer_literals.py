"""
Comment, regex literal, and quoted string scanners for TS/TSX sanitizer.
"""

from __future__ import annotations

from tools.audit.ts_lexer_state import LexerState


def _can_start_regex(prev_token_kind: str) -> bool:
    return prev_token_kind in ("start", "op", "punct", "kw_expr")


def _scan_line_comment(st: LexerState) -> None:
    start_line, start = st.line_no, st.i
    st.i += 2
    while st.i < st.n and st.source[st.i] != "\n":
        st.i += 1
    st.comments.append((start_line, st.source[start : st.i]))


def _scan_block_comment(st: LexerState) -> None:
    st.i += 2
    seg_start, seg_line = st.i, st.line_no
    while st.i < st.n:
        if st.source[st.i] == "*" and st.i + 1 < st.n and st.source[st.i + 1] == "/":
            st.comments.append((seg_line, st.source[seg_start : st.i]))
            st.i += 2
            return
        if st.source[st.i] == "\n":
            st.comments.append((seg_line, st.source[seg_start : st.i]))
            st.emit_newline(st.i)
            st.i += 1
            seg_start, seg_line = st.i, st.line_no
            continue
        st.i += 1


def _scan_regex_literal(st: LexerState) -> None:
    st.emit_char(st.i, "/")
    st.i += 1
    in_class = False
    while st.i < st.n:
        rc = st.source[st.i]
        if rc == "\n":
            st.emit_newline(st.i)
            st.i += 1
            break
        if rc == "\\" and st.i + 1 < st.n:
            if st.source[st.i + 1] == "\n":
                st.emit_newline(st.i + 1)
            st.i += 2
            continue
        if rc == "[":
            in_class = True
        elif rc == "]" and in_class:
            in_class = False
        elif rc == "/" and not in_class:
            st.emit_char(st.i, "/")
            st.i += 1
            while st.i < st.n and st.source[st.i].isalpha():
                st.emit_char(st.i, st.source[st.i])
                st.i += 1
            break
        st.i += 1
    st.prev_kind = "lit"


def _scan_quoted_string(st: LexerState, quote: str) -> None:
    st.emit_char(st.i, quote)
    st.i += 1
    while st.i < st.n:
        sc = st.source[st.i]
        if sc == "\n":
            st.emit_newline(st.i)
            st.i += 1
            break
        if sc == "\\" and st.i + 1 < st.n:
            if st.source[st.i + 1] == "\n":
                st.emit_newline(st.i + 1)
            st.i += 2
            continue
        if sc == quote:
            st.emit_char(st.i, quote)
            st.i += 1
            break
        st.i += 1
    st.prev_kind = "lit"
