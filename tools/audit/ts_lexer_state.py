"""
Lexer state and template/generic lookahead helpers for TS/TSX sanitizer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Tuple


@dataclass
class LexerState:
    source: str
    out: List[str]
    comments: List[Tuple[int, str]]
    line_no: int = 1
    i: int = 0
    stack: List[List[Any]] = field(default_factory=lambda: [["code"]])
    prev_kind: str = "start"

    @property
    def n(self) -> int:
        return len(self.source)

    def emit_char(self, pos: int, ch: str) -> None:
        self.out[pos] = ch

    def emit_newline(self, pos: int) -> None:
        self.out[pos] = "\n"
        self.line_no += 1


def is_generic_arrow_ahead(source: str, tag_start: int) -> bool:
    n = len(source)
    j = tag_start + 1
    if j < n and source[j] == ">":
        return False
    while j < n and (source[j].isalnum() or source[j] in ("_", "$", ".")):
        j += 1
    while j < n and source[j] in (" ", "\t", "\r", "\n"):
        j += 1
    if j < n and source[j] == ",":
        return True
    return source[j : j + 7] == "extends" and (j + 7 >= n or not (source[j + 7].isalnum() or source[j + 7] in ("_", "$")))


def consume_template_step(st: LexerState) -> None:
    ch = st.source[st.i]
    if ch == "\n":
        st.emit_newline(st.i)
        st.i += 1
    elif ch == "\\" and st.i + 1 < st.n:
        if st.source[st.i + 1] == "\n":
            st.emit_newline(st.i + 1)
        st.i += 2
    elif ch == "`":
        st.emit_char(st.i, "`")
        st.stack.pop()
        st.prev_kind = "lit"
        st.i += 1
    elif ch == "$" and st.i + 1 < st.n and st.source[st.i + 1] == "{":
        st.emit_char(st.i, "$")
        st.emit_char(st.i + 1, "{")
        st.stack.append(["tpl_expr", 1])
        st.prev_kind = "punct"
        st.i += 2
    else:
        st.i += 1
