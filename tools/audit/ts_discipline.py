#!/usr/bin/env python3
"""
TypeScript Type-System Discipline Engine (tools/audit/ts_discipline.py).
Deterministic 0-100 scorer & analyzer enforcing type-system discipline across
.ts and .tsx files using Tree-sitter AST when available and a full-precision
sanitized lexer/regex fallback otherwise.
"""

from __future__ import annotations

import json
import os
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.common.toon import encode
from tools.rules import TS_CONSOLE_LOG_PATTERN, TS_EXPLICIT_ANY_PATTERN

try:
    import tree_sitter  # noqa: F401
    import tree_sitter_language_pack as tslp

    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

DEFAULT_EXCLUDE_DIRS: Set[str] = {
    "node_modules",
    ".next",
    "dist",
    "build",
    "coverage",
    ".git",
    ".edge",
    ".archive",
    ".scratch",
    "scratch",
    "__pycache__",
}

_STATUS_BOOLEAN_NAMES: Set[str] = {
    "loading",
    "isLoading",
    "error",
    "hasError",
    "success",
    "isSuccess",
    "pending",
    "isPending",
}

_NON_NULL_PRECEDING_KEYWORDS: Set[str] = {
    "return",
    "throw",
    "typeof",
    "void",
    "delete",
    "await",
    "yield",
    "case",
    "in",
    "of",
    "else",
}

_CONTROL_KEYWORDS: Set[str] = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "throw",
    "new",
    "typeof",
    "delete",
    "void",
    "await",
    "yield",
    "case",
    "else",
}

_SUPPRESSION_RE = re.compile(r"@ts-(?:ignore|expect-error|nocheck)\b")
_DOUBLE_CAST_RE = re.compile(r"\bas\s+unknown\s+as\b")
_UNSAFE_AS_RE = re.compile(r"\bas\s+([A-Za-z_$][\w$.<>]*|\{[^}]*\}|\([^)]*\)|\[[^\]]*\])")
_RECORD_UNKNOWN_RE = re.compile(r"\bRecord\s*<\s*string\s*,\s*unknown\s*>")
_NEVER_BINDING_RE = re.compile(r":\s*never\b")
_SATISFIES_RE = re.compile(r"\bsatisfies\b")
_BRAND_RE = re.compile(r"\breadonly\s+__brand\b")
_Z_INFER_RE = re.compile(r"\bz\.infer\s*<")
_PROP_SIG_RE = re.compile(r"^(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*(\??)\s*:\s*(.+)$")
_ID_PARAM_RE = re.compile(
    r"^(?:public\s+|private\s+|protected\s+|readonly\s+)?([A-Za-z_$][\w$]*Id)\s*(\??)\s*:\s*string\b"
)
_FUNC_DECL_SIG_RE = re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)?\s*(?:<[^>]*>)?\s*\(")
_ARROW_VAR_SIG_RE = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^>]*>)?\s*\("
)
_METHOD_SIG_RE = re.compile(
    r"(?:^|[;{]\s*)(?:export\s+|public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+|async\s+|\*\s*)*"
    r"([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\("
)


def _get_parser_for_ext(ext: str) -> Optional[Any]:
    """Return a Tree-sitter parser for .ts or .tsx when available."""
    if not TREE_SITTER_AVAILABLE:
        return None
    norm = ext.lower()
    if norm == ".ts":
        return tslp.get_parser("typescript")
    if norm == ".tsx":
        return tslp.get_parser("tsx")
    return None


@dataclass
class TsDisciplineFinding:
    rule_id: str
    severity: str
    penalty: int
    line_number: int
    symbol: Optional[str]
    message: str
    suggested_fix: str
    snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "penalty": self.penalty,
            "line_number": self.line_number,
            "symbol": self.symbol,
            "message": self.message,
            "suggested_fix": self.suggested_fix,
            "snippet": self.snippet,
        }


@dataclass
class TsDisciplineFileReport:
    path: str
    sloc: int
    score: int
    band: str
    badge: str
    findings: List[TsDisciplineFinding] = field(default_factory=list)
    bonuses: List[TsDisciplineFinding] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "sloc": self.sloc,
            "score": self.score,
            "band": self.band,
            "badge": self.badge,
            "findings": [f.to_dict() for f in self.findings],
            "bonuses": [b.to_dict() for b in self.bonuses],
        }


@dataclass
class TsDisciplineSummary:
    target_path: str
    files_analyzed: int
    total_sloc: int
    overall_score: float
    overall_band: str
    strict_count: int
    loose_count: int
    porous_count: int
    rule_counts: Dict[str, int]
    file_reports: List[TsDisciplineFileReport]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_path": self.target_path,
            "files_analyzed": self.files_analyzed,
            "total_sloc": self.total_sloc,
            "overall_score": self.overall_score,
            "overall_band": self.overall_band,
            "strict_count": self.strict_count,
            "loose_count": self.loose_count,
            "porous_count": self.porous_count,
            "rule_counts": dict(self.rule_counts),
            "file_reports": [r.to_dict() for r in self.file_reports],
        }


def _score_to_band_and_badge(score: float) -> Tuple[str, str]:
    if score >= 85:
        return "STRICT", "🟢 STRICT"
    if score >= 60:
        return "LOOSE", "🟡 LOOSE"
    return "POROUS", "🔴 POROUS"


def _normalize_rel_path(rel_path: str) -> str:
    norm = rel_path.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _is_test_path(rel_path: str) -> bool:
    norm = _normalize_rel_path(rel_path)
    name = Path(norm).name
    return (
        ".test." in name
        or ".spec." in name
        or "_test." in name
        or norm.startswith("tests/")
        or "/tests/" in norm
        or norm.startswith("__tests__/")
        or "/__tests__/" in norm
    )


def _is_core_or_lib_path(rel_path: str) -> bool:
    norm = _normalize_rel_path(rel_path)
    return (
        norm.startswith("src/core/")
        or norm.startswith("src/lib/")
        or "/src/core/" in norm
        or "/src/lib/" in norm
    )


def _build_line_starts(source: str) -> List[int]:
    starts = [0]
    for idx, ch in enumerate(source):
        if ch == "\n":
            starts.append(idx + 1)
    return starts


def _offset_to_line(line_starts: List[int], offset: int) -> int:
    return bisect_right(line_starts, offset)


def _line_snippet(lines: List[str], line_no: int) -> str:
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()
    return ""


def _compute_sloc(source: str) -> int:
    count = 0
    for line in source.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            count += 1
    return count


def _can_start_regex(prev_token_kind: str) -> bool:
    return prev_token_kind in ("start", "op", "punct", "kw_expr")


def _sanitize_ts_source(source: str, is_tsx: bool) -> Tuple[str, List[Tuple[int, str]]]:
    """
    Single-pass TypeScript/TSX lexer that masks comments, string/template bodies,
    regex bodies, and TSX JSX text with spaces while preserving line numbers and
    collecting comment lines for directive checking.
    """
    n = len(source)
    out: List[str] = [" "] * n
    comments: List[Tuple[int, str]] = []

    line_no = 1
    i = 0
    # Stack frames: ("code",), ("template",), ("tpl_expr", brace_depth), ("jsx_children",), ("jsx_expr", brace_depth)
    stack: List[List[Any]] = [["code"]]
    prev_kind = "start"

    def _emit_char(pos: int, ch: str) -> None:
        out[pos] = ch

    def _emit_newline(pos: int) -> None:
        nonlocal line_no
        out[pos] = "\n"
        line_no += 1

    while i < n:
        state = stack[-1][0]
        ch = source[i]

        if state == "jsx_children":
            if ch == "\n":
                _emit_newline(i)
                i += 1
                continue
            if ch == "{":
                _emit_char(i, "{")
                stack.append(["jsx_expr", 1])
                prev_kind = "punct"
                i += 1
                continue
            if ch == "<":
                # Closing tag </...> or </>
                if i + 1 < n and source[i + 1] == "/":
                    _emit_char(i, "<")
                    _emit_char(i + 1, "/")
                    i += 2
                    while i < n and source[i] != ">":
                        if source[i] == "\n":
                            _emit_newline(i)
                        else:
                            _emit_char(i, source[i])
                        i += 1
                    if i < n and source[i] == ">":
                        _emit_char(i, ">")
                        i += 1
                    if len(stack) > 1:
                        stack.pop()
                    prev_kind = "close"
                    continue
                # Nested JSX opening tag <Tag ...> or <>
                if i + 1 < n and (source[i + 1].isalpha() or source[i + 1] in ("_", "$", ">")):
                    prev_kind = "op"
                    # Fall through to code-mode JSX tag handler below
                    pass
                else:
                    i += 1
                    continue
            else:
                # JSX text character: remains masked as space
                i += 1
                continue

        if state == "template":
            if ch == "\n":
                _emit_newline(i)
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                if source[i + 1] == "\n":
                    _emit_newline(i + 1)
                i += 2
                continue
            if ch == "`":
                _emit_char(i, "`")
                stack.pop()
                prev_kind = "lit"
                i += 1
                continue
            if ch == "$" and i + 1 < n and source[i + 1] == "{":
                _emit_char(i, "$")
                _emit_char(i + 1, "{")
                stack.append(["tpl_expr", 1])
                prev_kind = "punct"
                i += 2
                continue
            i += 1
            continue

        # Code-like states: "code", "tpl_expr", "jsx_expr", or JSX tag header from jsx_children
        if ch == "\n":
            _emit_newline(i)
            i += 1
            continue

        # Whitespace
        if ch in (" ", "\t", "\r", "\v", "\f"):
            _emit_char(i, ch)
            i += 1
            continue

        # Line comment //
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            start_line = line_no
            start = i
            i += 2
            while i < n and source[i] != "\n":
                i += 1
            comments.append((start_line, source[start:i]))
            continue

        # Block comment /* ... */
        if ch == "/" and i + 1 < n and source[i + 1] == "*":
            i += 2
            seg_start = i
            seg_line = line_no
            while i < n:
                if source[i] == "*" and i + 1 < n and source[i + 1] == "/":
                    comments.append((seg_line, source[seg_start:i]))
                    i += 2
                    break
                if source[i] == "\n":
                    comments.append((seg_line, source[seg_start:i]))
                    _emit_newline(i)
                    i += 1
                    seg_start = i
                    seg_line = line_no
                    continue
                i += 1
            continue

        # Regex literal
        if ch == "/" and _can_start_regex(prev_kind):
            _emit_char(i, "/")
            i += 1
            in_class = False
            while i < n:
                rc = source[i]
                if rc == "\n":
                    _emit_newline(i)
                    i += 1
                    break
                if rc == "\\" and i + 1 < n:
                    if source[i + 1] == "\n":
                        _emit_newline(i + 1)
                    i += 2
                    continue
                if rc == "[":
                    in_class = True
                    i += 1
                    continue
                if rc == "]" and in_class:
                    in_class = False
                    i += 1
                    continue
                if rc == "/" and not in_class:
                    _emit_char(i, "/")
                    i += 1
                    while i < n and source[i].isalpha():
                        _emit_char(i, source[i])
                        i += 1
                    break
                i += 1
            prev_kind = "lit"
            continue

        # Single / Double quoted string
        if ch in ("'", '"'):
            quote = ch
            _emit_char(i, quote)
            i += 1
            while i < n:
                sc = source[i]
                if sc == "\n":
                    _emit_newline(i)
                    i += 1
                    break
                if sc == "\\" and i + 1 < n:
                    if source[i + 1] == "\n":
                        _emit_newline(i + 1)
                    i += 2
                    continue
                if sc == quote:
                    _emit_char(i, quote)
                    i += 1
                    break
                i += 1
            prev_kind = "lit"
            continue

        # Template literal start
        if ch == "`":
            _emit_char(i, "`")
            stack.append(["template"])
            prev_kind = "punct"
            i += 1
            continue

        # JSX opening tag detection in TSX
        if (
            is_tsx
            and ch == "<"
            and (
                state == "jsx_children"
                or (
                    prev_kind in ("start", "op", "punct", "kw_expr")
                    and i + 1 < n
                    and (source[i + 1].isalpha() or source[i + 1] in ("_", "$", ">"))
                )
            )
        ):
            # Look ahead to distinguish TSX generic arrow (<T,> / <T extends ...>) from JSX tag
            tag_start = i
            j = i + 1
            is_fragment = j < n and source[j] == ">"
            is_generic_arrow = False
            if not is_fragment:
                while j < n and (source[j].isalnum() or source[j] in ("_", "$", ".")):
                    j += 1
                while j < n and source[j] in (" ", "\t", "\r", "\n"):
                    j += 1
                if j < n and source[j] == ",":
                    is_generic_arrow = True
                elif source[j : j + 7] == "extends" and (
                    j + 7 >= n or not (source[j + 7].isalnum() or source[j + 7] in ("_", "$"))
                ):
                    is_generic_arrow = True

            if not is_generic_arrow:
                # Consume JSX tag header until '>' at attribute brace depth 0
                _emit_char(i, "<")
                i += 1
                attr_brace = 0
                in_sq = False
                in_dq = False
                self_closing = False
                while i < n:
                    tc = source[i]
                    if tc == "\n":
                        _emit_newline(i)
                        i += 1
                        continue
                    if in_sq:
                        if tc == "\\" and i + 1 < n:
                            i += 2
                            continue
                        if tc == "'":
                            _emit_char(i, "'")
                            in_sq = False
                        i += 1
                        continue
                    if in_dq:
                        if tc == "\\" and i + 1 < n:
                            i += 2
                            continue
                        if tc == '"':
                            _emit_char(i, '"')
                            in_dq = False
                        i += 1
                        continue
                    if tc == "'" and attr_brace == 0:
                        _emit_char(i, "'")
                        in_sq = True
                        i += 1
                        continue
                    if tc == '"' and attr_brace == 0:
                        _emit_char(i, '"')
                        in_dq = True
                        i += 1
                        continue
                    if tc == "{":
                        _emit_char(i, "{")
                        attr_brace += 1
                        i += 1
                        continue
                    if tc == "}":
                        _emit_char(i, "}")
                        if attr_brace > 0:
                            attr_brace -= 1
                        i += 1
                        continue
                    if tc == ">" and attr_brace == 0:
                        k = i - 1
                        while k > tag_start and source[k] in (" ", "\t", "\n", "\r"):
                            k -= 1
                        self_closing = k > tag_start and source[k] == "/"
                        _emit_char(i, ">")
                        i += 1
                        break
                    # Inside attribute brace expression, handle nested strings/comments cleanly
                    if attr_brace > 0 and tc in ("'", '"'):
                        q = tc
                        _emit_char(i, q)
                        i += 1
                        while i < n:
                            ac = source[i]
                            if ac == "\n":
                                _emit_newline(i)
                                i += 1
                                break
                            if ac == "\\" and i + 1 < n:
                                i += 2
                                continue
                            if ac == q:
                                _emit_char(i, q)
                                i += 1
                                break
                            i += 1
                        continue
                    _emit_char(i, tc)
                    i += 1

                if not self_closing:
                    stack.append(["jsx_children"])
                    prev_kind = "op"
                else:
                    prev_kind = "close"
                continue

        # Braces inside tpl_expr or jsx_expr
        if ch == "{":
            _emit_char(i, "{")
            if state in ("tpl_expr", "jsx_expr"):
                stack[-1][1] += 1
            prev_kind = "punct"
            i += 1
            continue

        if ch == "}":
            _emit_char(i, "}")
            if state in ("tpl_expr", "jsx_expr"):
                stack[-1][1] -= 1
                if stack[-1][1] == 0:
                    stack.pop()
                    prev_kind = "close" if stack[-1][0] == "jsx_children" else "punct"
                    i += 1
                    continue
            prev_kind = "punct"
            i += 1
            continue

        # Identifiers & keywords
        if ch.isalpha() or ch in ("_", "$"):
            start = i
            while i < n and (source[i].isalnum() or source[i] in ("_", "$")):
                _emit_char(i, source[i])
                i += 1
            word = source[start:i]
            if word in _NON_NULL_PRECEDING_KEYWORDS or word in ("export", "import", "as", "satisfies"):
                prev_kind = "kw_expr"
            else:
                prev_kind = "ident"
            continue

        # Numbers
        if ch.isdigit():
            while i < n and (source[i].isalnum() or source[i] in (".", "_")):
                _emit_char(i, source[i])
                i += 1
            prev_kind = "number"
            continue

        # Punctuation / Operators
        _emit_char(i, ch)
        if ch in (")", "]"):
            prev_kind = "close"
        elif ch in ("(", "[", ",", ";", ":"):
            prev_kind = "punct"
        else:
            prev_kind = "op"
        i += 1

    return "".join(out), comments


def _find_matching_delimiter(text: str, open_idx: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    n = len(text)
    for i in range(open_idx, n):
        ch = text[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _find_matching_open_delimiter(text: str, close_idx: int, open_ch: str, close_ch: str) -> int:
    depth = 0
    for i in range(close_idx, -1, -1):
        ch = text[i]
        if ch == close_ch:
            depth += 1
        elif ch == open_ch:
            depth -= 1
            if depth == 0:
                return i
    return -1


def _split_top_level_commas(text: str) -> List[str]:
    parts: List[str] = []
    paren = 0
    brace = 0
    bracket = 0
    angle = 0
    start = 0
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "(":
            paren += 1
        elif ch == ")" and paren > 0:
            paren -= 1
        elif ch == "{":
            brace += 1
        elif ch == "}" and brace > 0:
            brace -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]" and bracket > 0:
            bracket -= 1
        elif ch == "<":
            angle += 1
        elif ch == ">":
            if i > 0 and text[i - 1] == "=":
                pass
            elif angle > 0:
                angle -= 1
        elif ch == "," and paren == 0 and brace == 0 and bracket == 0 and angle == 0:
            parts.append(text[start:i])
            start = i + 1
        i += 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _strip_default_value(param_str: str) -> str:
    paren = 0
    brace = 0
    bracket = 0
    angle = 0
    n = len(param_str)
    for i, ch in enumerate(param_str):
        if ch == "(":
            paren += 1
        elif ch == ")" and paren > 0:
            paren -= 1
        elif ch == "{":
            brace += 1
        elif ch == "}" and brace > 0:
            brace -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]" and bracket > 0:
            bracket -= 1
        elif ch == "<":
            angle += 1
        elif ch == ">" and angle > 0 and not (i > 0 and param_str[i - 1] == "="):
            angle -= 1
        elif ch == "=" and paren == 0 and brace == 0 and bracket == 0 and angle == 0:
            if i + 1 < n and param_str[i + 1] == ">":
                continue
            return param_str[:i].strip()
    return param_str.strip()


def _is_object_or_array_literal_lhs(masked: str, as_start: int) -> bool:
    idx = as_start - 1
    while idx >= 0 and masked[idx].isspace():
        idx -= 1
    if idx < 0:
        return False
    while idx >= 0 and masked[idx] == ")":
        open_p = _find_matching_open_delimiter(masked, idx, "(", ")")
        if open_p < 0:
            return False
        idx = open_p - 1
        while idx >= 0 and masked[idx].isspace():
            idx -= 1
    if idx < 0:
        return False
    if masked[idx] == "}":
        open_b = _find_matching_open_delimiter(masked, idx, "{", "}")
        if open_b < 0:
            return False
        before = open_b - 1
        while before >= 0 and masked[before].isspace():
            before -= 1
        if before < 0 or masked[before] in ("=", "(", "[", ",", ":", "?", ">"):
            return True
        if masked[max(0, before - 5) : before + 1].endswith("return"):
            return True
        return False
    if masked[idx] == "]":
        open_k = _find_matching_open_delimiter(masked, idx, "[", "]")
        if open_k < 0:
            return False
        before = open_k - 1
        while before >= 0 and masked[before].isspace():
            before -= 1
        if before < 0 or masked[before] in ("=", "(", "[", ",", ":", "?", ">"):
            return True
        if masked[max(0, before - 5) : before + 1].endswith("return"):
            return True
        return False
    return False


def _mask_span(chars: List[str], start: int, end: int) -> None:
    for idx in range(max(0, start), min(len(chars), end)):
        if chars[idx] != "\n":
            chars[idx] = " "


def _mask_import_export_aliases(masked: str) -> str:
    chars = list(masked)
    # Mask import ... from / import * as ...;
    for m in re.finditer(
        r"\bimport\s+(?:type\s+)?(?:\*\s+as\s+[A-Za-z_$][\w$]*|\{[^}]*\}|[A-Za-z_$][\w$]*(?:\s*,\s*\{[^}]*\})?)\s*(?:from\b)?",
        masked,
    ):
        _mask_span(chars, m.start(), m.end())
    # Mask export * as ... and export [type] { ... }
    for m in re.finditer(
        r"\bexport\s+(?:\*\s+as\s+[A-Za-z_$][\w$]*|(?:type\s+)?\{[^}]*\})",
        masked,
    ):
        _mask_span(chars, m.start(), m.end())
    return "".join(chars)


def _extract_switch_default_block(body_text: str) -> Optional[str]:
    """Return the text of the top-level default: branch inside a switch { ... } body, or None."""
    n = len(body_text)
    depth = 0
    default_start: Optional[int] = None
    i = 0
    while i < n:
        ch = body_text[i]
        if ch == "{":
            depth += 1
            i += 1
            continue
        if ch == "}":
            if default_start is not None and depth == 1:
                return body_text[default_start:i]
            depth -= 1
            i += 1
            continue
        if depth == 1:
            if default_start is None and body_text.startswith("default", i):
                prev_ok = i == 0 or not (body_text[i - 1].isalnum() or body_text[i - 1] in ("_", "$"))
                j = i + 7
                while j < n and body_text[j].isspace():
                    j += 1
                if prev_ok and j < n and body_text[j] == ":":
                    default_start = j + 1
                    i = j + 1
                    continue
            elif default_start is not None and body_text.startswith("case", i):
                prev_ok = i == 0 or not (body_text[i - 1].isalnum() or body_text[i - 1] in ("_", "$"))
                nxt_ok = i + 4 < n and body_text[i + 4].isspace()
                if prev_ok and nxt_ok:
                    return body_text[default_start:i]
        i += 1
    if default_start is not None:
        return body_text[default_start:]
    return None


def _split_top_level_properties(body_inner: str) -> List[str]:
    segments: List[str] = []
    paren = 0
    brace = 0
    bracket = 0
    angle = 0
    start = 0
    for i, ch in enumerate(body_inner):
        if ch == "(":
            paren += 1
        elif ch == ")" and paren > 0:
            paren -= 1
        elif ch == "{":
            brace += 1
        elif ch == "}" and brace > 0:
            brace -= 1
        elif ch == "[":
            bracket += 1
        elif ch == "]" and bracket > 0:
            bracket -= 1
        elif ch == "<":
            angle += 1
        elif ch == ">" and angle > 0 and not (i > 0 and body_inner[i - 1] == "="):
            angle -= 1
        elif ch in (";", ",", "\n") and paren == 0 and brace == 0 and bracket == 0 and angle == 0:
            seg = body_inner[start:i].strip()
            if seg:
                segments.append(seg)
            start = i + 1
    tail = body_inner[start:].strip()
    if tail:
        segments.append(tail)
    return segments


def _check_bag_segments(segments: List[str]) -> bool:
    has_status_bool = False
    optional_count = 0
    for seg in segments:
        m = _PROP_SIG_RE.match(seg)
        if not m:
            continue
        prop_name, opt_mark, type_part = m.group(1), m.group(2), m.group(3)
        if opt_mark == "?":
            optional_count += 1
        if prop_name in _STATUS_BOOLEAN_NAMES and re.search(r"\bboolean\b", type_part):
            has_status_bool = True
    return has_status_bool and optional_count >= 2


def _analyze_with_fallback(source: str, rel_path: str) -> Tuple[List[TsDisciplineFinding], bool]:
    is_tsx = rel_path.lower().endswith(".tsx")
    is_test = _is_test_path(rel_path)
    is_core_lib = _is_core_or_lib_path(rel_path)

    lines = source.splitlines()
    line_starts = _build_line_starts(source)
    masked, comments = _sanitize_ts_source(source, is_tsx=is_tsx)

    findings: List[TsDisciplineFinding] = []
    has_never_switch_bonus = False

    # 1. RULE-TS-EXPLICIT-ANY (-20p, CRITICAL)
    for m in TS_EXPLICIT_ANY_PATTERN.finditer(masked):
        ln = _offset_to_line(line_starts, m.start())
        findings.append(
            TsDisciplineFinding(
                rule_id="RULE-TS-EXPLICIT-ANY",
                severity="CRITICAL",
                penalty=-20,
                line_number=ln,
                symbol="any",
                message="Explicit `any` bypasses TypeScript structural soundness.",
                suggested_fix="Replace `any` with `unknown` and narrow with Zod or explicit type guards.",
                snippet=_line_snippet(lines, ln),
            )
        )

    # 2. RULE-TS-SUPPRESSION (-20p, CRITICAL)
    for c_line, c_text in comments:
        m = _SUPPRESSION_RE.search(c_text)
        if m:
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-SUPPRESSION",
                    severity="CRITICAL",
                    penalty=-20,
                    line_number=c_line,
                    symbol=m.group(0),
                    message=f"Compiler suppression `{m.group(0)}` hides type errors.",
                    suggested_fix="Remove suppression directive and fix the underlying type contract.",
                    snippet=_line_snippet(lines, c_line),
                )
            )

    # 3. RULE-TS-DOUBLE-CAST (-20p, CRITICAL)
    masked_no_double = list(masked)
    for m in _DOUBLE_CAST_RE.finditer(masked):
        ln = _offset_to_line(line_starts, m.start())
        _mask_span(masked_no_double, m.start(), m.end())
        findings.append(
            TsDisciplineFinding(
                rule_id="RULE-TS-DOUBLE-CAST",
                severity="CRITICAL",
                penalty=-20,
                line_number=ln,
                symbol="as unknown as",
                message="Double cast `as unknown as` forces arbitrary type conversion.",
                suggested_fix="Validate the value with a Zod schema or verifying type guard instead of double-casting.",
                snippet=_line_snippet(lines, ln),
            )
        )

    # 4. RULE-TS-UNSAFE-AS (-10p, WARNING)
    masked_for_as = _mask_import_export_aliases("".join(masked_no_double))
    for m in _UNSAFE_AS_RE.finditer(masked_for_as):
        target_type = m.group(1).strip()
        if target_type in ("const", "any"):
            continue
        ln = _offset_to_line(line_starts, m.start())
        if _is_object_or_array_literal_lhs(masked_for_as, m.start()):
            fix = f"Use `satisfies {target_type}` instead of `as {target_type}` to preserve narrow literal inference."
        else:
            fix = "Prefer discriminant `switch`, `in`, `typeof`/`instanceof`, or a verifying type guard over `as`."
        findings.append(
            TsDisciplineFinding(
                rule_id="RULE-TS-UNSAFE-AS",
                severity="WARNING",
                penalty=-10,
                line_number=ln,
                symbol=f"as {target_type}",
                message=f"Unsafe type assertion `as {target_type}` overrides compiler verification.",
                suggested_fix=fix,
                snippet=_line_snippet(lines, ln),
            )
        )

    # 5. RULE-TS-NON-NULL (-10p, WARNING)
    n = len(masked)
    for idx, ch in enumerate(masked):
        if ch != "!":
            continue
        if idx == 0:
            continue
        prev_ch = masked[idx - 1]
        if not (prev_ch.isalnum() or prev_ch in ("_", "$", ")", "]")):
            continue
        # Check preceding keyword
        if prev_ch.isalnum() or prev_ch in ("_", "$"):
            k = idx - 1
            while k >= 0 and (masked[k].isalnum() or masked[k] in ("_", "$")):
                k -= 1
            prev_word = masked[k + 1 : idx]
            if prev_word in _NON_NULL_PRECEDING_KEYWORDS:
                continue
        next_ch = masked[idx + 1] if idx + 1 < n else ""
        if next_ch == "=":
            continue
        if next_ch.isalnum() or next_ch in ("_", "$", "("):
            continue
        ln = _offset_to_line(line_starts, idx)
        findings.append(
            TsDisciplineFinding(
                rule_id="RULE-TS-NON-NULL",
                severity="WARNING",
                penalty=-10,
                line_number=ln,
                symbol="!",
                message="Non-null assertion (`!`) suppresses null/undefined checks at runtime.",
                suggested_fix="Narrow explicitly (`if (!value) ...` or `.at(0)`) instead of postfix `!`.",
                snippet=_line_snippet(lines, ln),
            )
        )

    # 6. RULE-TS-CONSOLE-LOG (-8p, WARNING)
    if not is_test:
        for m in TS_CONSOLE_LOG_PATTERN.finditer(masked):
            ln = _offset_to_line(line_starts, m.start())
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-CONSOLE-LOG",
                    severity="WARNING",
                    penalty=-8,
                    line_number=ln,
                    symbol="console.log",
                    message="`console.log(...)` left in shipped production TypeScript file.",
                    suggested_fix="Remove debug `console.log` or emit structured telemetry.",
                    snippet=_line_snippet(lines, ln),
                )
            )

    # 7. RULE-TS-RECORD-UNKNOWN (-8p, WARNING in src/core/ and src/lib/)
    if is_core_lib:
        for m in _RECORD_UNKNOWN_RE.finditer(masked):
            ln = _offset_to_line(line_starts, m.start())
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-RECORD-UNKNOWN",
                    severity="WARNING",
                    penalty=-8,
                    line_number=ln,
                    symbol="Record<string, unknown>",
                    message="Untyped `Record<string, unknown>` leaked into core/lib domain boundary.",
                    suggested_fix="Validate at perimeter (actions/routes) and pass typed domain contracts into src/core and src/lib.",
                    snippet=_line_snippet(lines, ln),
                )
            )

    # 8. RULE-TS-SWITCH-EXHAUSTIVE (-8p, WARNING)
    for m in re.finditer(r"\bswitch\s*\(", masked):
        open_paren = m.end() - 1
        close_paren = _find_matching_delimiter(masked, open_paren, "(", ")")
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
        body_text = masked[brace_idx : close_brace + 1]
        default_block = _extract_switch_default_block(body_text)
        if default_block is not None and _NEVER_BINDING_RE.search(default_block):
            has_never_switch_bonus = True
        else:
            ln = _offset_to_line(line_starts, m.start())
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-SWITCH-EXHAUSTIVE",
                    severity="WARNING",
                    penalty=-8,
                    line_number=ln,
                    symbol="switch",
                    message="`switch` statement lacks an exhaustive `default:` branch with a `: never` binding.",
                    suggested_fix="Add `default: { const _exhaustive: never = value; throw new Error(...); }`.",
                    snippet=_line_snippet(lines, ln),
                )
            )

    # 9. RULE-TS-OPTIONAL-BAG (-6p, ADVISORY)
    bag_patterns = (
        re.compile(r"\binterface\s+([A-Za-z_$][\w$]*)(?:\s*<[^>]*>)?(?:\s+extends\s+[^{]+)?\s*\{"),
        re.compile(r"\btype\s+([A-Za-z_$][\w$]*)(?:\s*<[^>]*>)?\s*=\s*\{"),
    )
    for pat in bag_patterns:
        for m in pat.finditer(masked):
            open_b = m.end() - 1
            close_b = _find_matching_delimiter(masked, open_b, "{", "}")
            if close_b < 0:
                continue
            inner = masked[open_b + 1 : close_b]
            segments = _split_top_level_properties(inner)
            if _check_bag_segments(segments):
                ln = _offset_to_line(line_starts, m.start())
                sym = m.group(1)
                findings.append(
                    TsDisciplineFinding(
                        rule_id="RULE-TS-OPTIONAL-BAG",
                        severity="ADVISORY",
                        penalty=-6,
                        line_number=ln,
                        symbol=sym,
                        message=f"Type `{sym}` models state with a status boolean and optional fields instead of a discriminated union.",
                        suggested_fix="Refactor into a discriminated union with an explicit literal `status` or `kind` field.",
                        snippet=_line_snippet(lines, ln),
                    )
                )

    # 10. RULE-TS-POSITIONAL-ARGS (-5p, ADVISORY)
    seen_param_parens: Set[int] = set()
    sig_candidates: List[Tuple[int, str, int]] = []

    for m in _FUNC_DECL_SIG_RE.finditer(masked):
        p_idx = m.end() - 1
        if p_idx not in seen_param_parens:
            seen_param_parens.add(p_idx)
            sig_candidates.append((m.start(), m.group(1) or "anonymous", p_idx))

    for m in _ARROW_VAR_SIG_RE.finditer(masked):
        p_idx = m.end() - 1
        if p_idx not in seen_param_parens:
            seen_param_parens.add(p_idx)
            sig_candidates.append((m.start(), m.group(1), p_idx))

    for m in _METHOD_SIG_RE.finditer(masked):
        name = m.group(1)
        if name in _CONTROL_KEYWORDS:
            continue
        p_idx = m.end() - 1
        if p_idx in seen_param_parens:
            continue
        close_p = _find_matching_delimiter(masked, p_idx, "(", ")")
        if close_p < 0:
            continue
        after = masked[close_p + 1 :].lstrip()
        # Must be followed by return type + '{' or '=>' or direct '{'
        if not re.match(r"^(?::\s*[^=>{;]+)?(?:\{|=>)", after):
            continue
        seen_param_parens.add(p_idx)
        sig_candidates.append((m.start(), name, p_idx))

    for sig_start, sym, open_p in sig_candidates:
        close_p = _find_matching_delimiter(masked, open_p, "(", ")")
        if close_p < 0:
            continue
        params_raw = masked[open_p + 1 : close_p].strip()
        if not params_raw:
            continue
        params = _split_top_level_commas(params_raw)
        positional_count = 0
        id_param_count = 0
        for p in params:
            p_clean = _strip_default_value(p)
            if re.match(r"^this(?:\s*:|\s*$)", p_clean):
                continue
            positional_count += 1
            if _ID_PARAM_RE.match(p_clean):
                id_param_count += 1
        if positional_count >= 4 or id_param_count >= 2:
            ln = _offset_to_line(line_starts, sig_start)
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-POSITIONAL-ARGS",
                    severity="ADVISORY",
                    penalty=-5,
                    line_number=ln,
                    symbol=sym,
                    message=f"Function `{sym}` takes {positional_count} positional / {id_param_count} `*Id` parameter(s).",
                    suggested_fix="Group parameters into a single named options object ({ ... }); skip only on documented hot paths.",
                    snippet=_line_snippet(lines, ln),
                )
            )

    has_bonus = (
        has_never_switch_bonus
        or bool(_SATISFIES_RE.search(masked))
        or bool(_BRAND_RE.search(masked))
        or bool(_Z_INFER_RE.search(masked))
    )
    return findings, has_bonus


def _node_text(node: Any, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _unwrap_parens(node: Any) -> Any:
    cur = node
    while cur is not None and cur.type == "parenthesized_expression":
        named = [c for c in cur.children if c.is_named]
        cur = named[0] if named else None
    return cur


def _analyze_with_ast(source: str, rel_path: str, parser: Any) -> Tuple[List[TsDisciplineFinding], bool]:
    source_bytes = source.encode("utf-8")
    lines = source.splitlines()
    tree = parser.parse(source_bytes)
    root = tree.root_node

    is_test = _is_test_path(rel_path)
    is_core_lib = _is_core_or_lib_path(rel_path)

    findings: List[TsDisciplineFinding] = []
    double_cast_spans: Set[Tuple[int, int]] = set()
    has_bonus = False

    def _walk(node: Any) -> None:
        nonlocal has_bonus
        ntype = node.type
        ln = node.start_point[0] + 1

        # 1. RULE-TS-EXPLICIT-ANY
        if ntype == "predefined_type" and _node_text(node, source_bytes).strip() == "any":
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-EXPLICIT-ANY",
                    severity="CRITICAL",
                    penalty=-20,
                    line_number=ln,
                    symbol="any",
                    message="Explicit `any` bypasses TypeScript structural soundness.",
                    suggested_fix="Replace `any` with `unknown` and narrow with Zod or explicit type guards.",
                    snippet=_line_snippet(lines, ln),
                )
            )

        # 2. RULE-TS-SUPPRESSION
        elif ntype == "comment":
            comment_text = _node_text(node, source_bytes)
            for offset_line, cline in enumerate(comment_text.splitlines()):
                m = _SUPPRESSION_RE.search(cline)
                if m:
                    actual_ln = ln + offset_line
                    findings.append(
                        TsDisciplineFinding(
                            rule_id="RULE-TS-SUPPRESSION",
                            severity="CRITICAL",
                            penalty=-20,
                            line_number=actual_ln,
                            symbol=m.group(0),
                            message=f"Compiler suppression `{m.group(0)}` hides type errors.",
                            suggested_fix="Remove suppression directive and fix the underlying type contract.",
                            snippet=_line_snippet(lines, actual_ln),
                        )
                    )

        # 3 & 4. RULE-TS-DOUBLE-CAST & RULE-TS-UNSAFE-AS
        elif ntype == "as_expression":
            span = (node.start_byte, node.end_byte)
            if span not in double_cast_spans:
                named = [c for c in node.children if c.is_named]
                if len(named) >= 2:
                    lhs_node = _unwrap_parens(named[0])
                    type_node = named[-1]
                    type_text = _node_text(type_node, source_bytes).strip()

                    # Check double cast: (x as unknown) as T
                    if lhs_node is not None and lhs_node.type == "as_expression":
                        inner_named = [c for c in lhs_node.children if c.is_named]
                        inner_type = _node_text(inner_named[-1], source_bytes).strip() if inner_named else ""
                        if inner_type == "unknown":
                            double_cast_spans.add(span)
                            double_cast_spans.add((lhs_node.start_byte, lhs_node.end_byte))
                            findings.append(
                                TsDisciplineFinding(
                                    rule_id="RULE-TS-DOUBLE-CAST",
                                    severity="CRITICAL",
                                    penalty=-20,
                                    line_number=ln,
                                    symbol="as unknown as",
                                    message="Double cast `as unknown as` forces arbitrary type conversion.",
                                    suggested_fix="Validate the value with a Zod schema or verifying type guard instead of double-casting.",
                                    snippet=_line_snippet(lines, ln),
                                )
                            )
                            # Do not return early from walk; walk children in case nested
                    if span not in double_cast_spans and type_text not in ("const", "any"):
                        if lhs_node is not None and lhs_node.type in ("object", "array"):
                            fix = f"Use `satisfies {type_text}` instead of `as {type_text}` to preserve narrow literal inference."
                        else:
                            fix = "Prefer discriminant `switch`, `in`, `typeof`/`instanceof`, or a verifying type guard over `as`."
                        findings.append(
                            TsDisciplineFinding(
                                rule_id="RULE-TS-UNSAFE-AS",
                                severity="WARNING",
                                penalty=-10,
                                line_number=ln,
                                symbol=f"as {type_text}",
                                message=f"Unsafe type assertion `as {type_text}` overrides compiler verification.",
                                suggested_fix=fix,
                                snippet=_line_snippet(lines, ln),
                            )
                        )

        # 5. RULE-TS-NON-NULL
        elif ntype == "non_null_expression":
            findings.append(
                TsDisciplineFinding(
                    rule_id="RULE-TS-NON-NULL",
                    severity="WARNING",
                    penalty=-10,
                    line_number=ln,
                    symbol="!",
                    message="Non-null assertion (`!`) suppresses null/undefined checks at runtime.",
                    suggested_fix="Narrow explicitly (`if (!value) ...` or `.at(0)`) instead of postfix `!`.",
                    snippet=_line_snippet(lines, ln),
                )
            )

        # 6. RULE-TS-CONSOLE-LOG
        elif ntype == "call_expression" and not is_test:
            fn_node = node.child_by_field_name("function")
            if fn_node is not None and fn_node.type == "member_expression":
                obj = fn_node.child_by_field_name("object")
                prop = fn_node.child_by_field_name("property")
                if (
                    obj is not None
                    and prop is not None
                    and _node_text(obj, source_bytes).strip() == "console"
                    and _node_text(prop, source_bytes).strip() == "log"
                ):
                    findings.append(
                        TsDisciplineFinding(
                            rule_id="RULE-TS-CONSOLE-LOG",
                            severity="WARNING",
                            penalty=-8,
                            line_number=ln,
                            symbol="console.log",
                            message="`console.log(...)` left in shipped production TypeScript file.",
                            suggested_fix="Remove debug `console.log` or emit structured telemetry.",
                            snippet=_line_snippet(lines, ln),
                        )
                    )

        # 7. RULE-TS-RECORD-UNKNOWN + BONUS z.infer<...>
        elif ntype == "generic_type":
            name_node = node.child_by_field_name("name")
            name_text = _node_text(name_node, source_bytes).strip() if name_node is not None else ""
            if name_text == "z.infer":
                has_bonus = True
            elif is_core_lib and name_text == "Record":
                ta_node = node.child_by_field_name("type_arguments")
                if ta_node is not None:
                    args = [_node_text(c, source_bytes).strip() for c in ta_node.children if c.is_named]
                    if args == ["string", "unknown"]:
                        findings.append(
                            TsDisciplineFinding(
                                rule_id="RULE-TS-RECORD-UNKNOWN",
                                severity="WARNING",
                                penalty=-8,
                                line_number=ln,
                                symbol="Record<string, unknown>",
                                message="Untyped `Record<string, unknown>` leaked into core/lib domain boundary.",
                                suggested_fix="Validate at perimeter (actions/routes) and pass typed domain contracts into src/core and src/lib.",
                                snippet=_line_snippet(lines, ln),
                            )
                        )

        # 8. RULE-TS-SWITCH-EXHAUSTIVE
        elif ntype == "switch_statement":
            body_node = node.child_by_field_name("body")
            default_node = None
            if body_node is not None:
                for c in body_node.children:
                    if c.type == "switch_default":
                        default_node = c
                        break
            has_never = False
            if default_node is not None:
                default_text = _node_text(default_node, source_bytes)
                if _NEVER_BINDING_RE.search(default_text):
                    has_never = True
            if has_never:
                has_bonus = True
            else:
                findings.append(
                    TsDisciplineFinding(
                        rule_id="RULE-TS-SWITCH-EXHAUSTIVE",
                        severity="WARNING",
                        penalty=-8,
                        line_number=ln,
                        symbol="switch",
                        message="`switch` statement lacks an exhaustive `default:` branch with a `: never` binding.",
                        suggested_fix="Add `default: { const _exhaustive: never = value; throw new Error(...); }`.",
                        snippet=_line_snippet(lines, ln),
                    )
                )

        # 9. RULE-TS-OPTIONAL-BAG + BONUS readonly __brand
        elif ntype in ("interface_body", "object_type"):
            has_status_bool = False
            optional_count = 0
            for c in node.children:
                if c.type != "property_signature":
                    continue
                pname_node = c.child_by_field_name("name")
                pname = _node_text(pname_node, source_bytes).strip() if pname_node is not None else ""
                ptype_node = c.child_by_field_name("type")
                ptype = _node_text(ptype_node, source_bytes).strip() if ptype_node is not None else ""
                c_text = _node_text(c, source_bytes)
                if pname == "__brand" and "readonly" in c_text:
                    has_bonus = True
                if any(tok.type == "?" for tok in c.children):
                    optional_count += 1
                if pname in _STATUS_BOOLEAN_NAMES and re.search(r"\bboolean\b", ptype):
                    has_status_bool = True
            if has_status_bool and optional_count >= 2:
                sym = None
                if node.parent is not None:
                    p_name = node.parent.child_by_field_name("name")
                    if p_name is not None:
                        sym = _node_text(p_name, source_bytes).strip()
                findings.append(
                    TsDisciplineFinding(
                        rule_id="RULE-TS-OPTIONAL-BAG",
                        severity="ADVISORY",
                        penalty=-6,
                        line_number=ln,
                        symbol=sym,
                        message=f"Type `{sym or 'object'}` models state with a status boolean and optional fields instead of a discriminated union.",
                        suggested_fix="Refactor into a discriminated union with an explicit literal `status` or `kind` field.",
                        snippet=_line_snippet(lines, ln),
                    )
                )

        # 10. RULE-TS-POSITIONAL-ARGS
        elif ntype in ("function_declaration", "function_expression", "arrow_function", "method_definition"):
            params_node = node.child_by_field_name("parameters")
            if params_node is not None:
                positional_count = 0
                id_param_count = 0
                for c in params_node.children:
                    if c.type not in ("required_parameter", "optional_parameter", "rest_parameter"):
                        continue
                    pat_node = c.child_by_field_name("pattern") or c.child_by_field_name("name")
                    pat_text = _node_text(pat_node, source_bytes).strip() if pat_node is not None else ""
                    if pat_text == "this":
                        continue
                    positional_count += 1
                    if pat_node is not None and pat_node.type == "identifier" and pat_text.endswith("Id"):
                        type_node = c.child_by_field_name("type")
                        type_text = _node_text(type_node, source_bytes).lstrip(":").strip() if type_node is not None else ""
                        if re.match(r"^string\b", type_text):
                            id_param_count += 1
                if positional_count >= 4 or id_param_count >= 2:
                    sym_node = node.child_by_field_name("name")
                    if sym_node is not None:
                        sym = _node_text(sym_node, source_bytes).strip()
                    elif node.parent is not None and node.parent.type == "variable_declarator":
                        vname = node.parent.child_by_field_name("name")
                        sym = _node_text(vname, source_bytes).strip() if vname is not None else "anonymous"
                    else:
                        sym = "anonymous"
                    findings.append(
                        TsDisciplineFinding(
                            rule_id="RULE-TS-POSITIONAL-ARGS",
                            severity="ADVISORY",
                            penalty=-5,
                            line_number=ln,
                            symbol=sym,
                            message=f"Function `{sym}` takes {positional_count} positional / {id_param_count} `*Id` parameter(s).",
                            suggested_fix="Group parameters into a single named options object ({ ... }); skip only on documented hot paths.",
                            snippet=_line_snippet(lines, ln),
                        )
                    )

        # BONUS-TS-DISCIPLINE: satisfies_expression
        elif ntype == "satisfies_expression":
            has_bonus = True

        for child in node.children:
            _walk(child)

    _walk(root)
    return findings, has_bonus


class TsDisciplineAuditor:
    """Deterministic TypeScript/TSX Type-System Discipline Auditor."""

    def __init__(
        self,
        root_dir: Path,
        exclude_dirs: Optional[Set[str]] = None,
        include_tests: bool = False,
    ):
        self.root_dir = Path(root_dir).resolve()
        self.exclude_dirs = set(exclude_dirs) if exclude_dirs is not None else set(DEFAULT_EXCLUDE_DIRS)
        self.include_tests = include_tests

    def _is_eligible_file(self, file_path: Path, rel_path: str) -> bool:
        name = file_path.name.lower()
        if not (name.endswith(".ts") or name.endswith(".tsx")):
            return False
        if name.endswith(".d.ts"):
            return False
        parts = set(_normalize_rel_path(rel_path).split("/")[:-1])
        if parts & self.exclude_dirs:
            return False
        if not self.include_tests and _is_test_path(rel_path):
            return False
        return True

    def get_ts_files(self, target: Path, scoped_files: Optional[List[str]] = None) -> List[Path]:
        target_path = Path(target).resolve()
        results: List[Path] = []
        seen: Set[Path] = set()

        if scoped_files is not None:
            for entry in scoped_files:
                p = Path(entry)
                if not p.is_absolute():
                    cand = (self.root_dir / p).resolve()
                    if not cand.exists():
                        cand = (target_path / p).resolve()
                else:
                    cand = p.resolve()
                if not cand.is_file() or cand in seen:
                    continue
                try:
                    rel = cand.relative_to(self.root_dir).as_posix()
                except ValueError:
                    rel = cand.as_posix()
                if self._is_eligible_file(cand, rel):
                    seen.add(cand)
                    results.append(cand)
            return sorted(results)

        if target_path.is_file():
            try:
                rel = target_path.relative_to(self.root_dir).as_posix()
            except ValueError:
                rel = target_path.as_posix()
            if self._is_eligible_file(target_path, rel):
                return [target_path]
            return []

        if not target_path.exists():
            return []

        for dirpath, dirnames, filenames in os.walk(target_path):
            dirnames[:] = sorted(d for d in dirnames if d not in self.exclude_dirs)
            for fname in sorted(filenames):
                fpath = Path(dirpath) / fname
                try:
                    rel = fpath.resolve().relative_to(self.root_dir).as_posix()
                except ValueError:
                    rel = fpath.as_posix()
                if self._is_eligible_file(fpath, rel):
                    results.append(fpath)
        return sorted(results)

    def analyze_source(self, source: str, rel_path: str = "input.ts") -> TsDisciplineFileReport:
        norm_rel = _normalize_rel_path(rel_path)
        sloc = _compute_sloc(source)

        ext = ".tsx" if norm_rel.lower().endswith(".tsx") else ".ts"
        parser = _get_parser_for_ext(ext) if TREE_SITTER_AVAILABLE else None

        if parser is not None:
            findings, has_bonus = _analyze_with_ast(source, norm_rel, parser)
        else:
            findings, has_bonus = _analyze_with_fallback(source, norm_rel)

        findings.sort(key=lambda f: (f.line_number, f.rule_id))

        bonuses: List[TsDisciplineFinding] = []
        if has_bonus:
            bonuses.append(
                TsDisciplineFinding(
                    rule_id="BONUS-TS-DISCIPLINE",
                    severity="BONUS",
                    penalty=5,
                    line_number=1,
                    symbol=None,
                    message="Positive type-system discipline signal detected (`satisfies`, branded type, `z.infer`, or exhaustive `never`).",
                    suggested_fix="",
                    snippet="",
                )
            )

        raw = 100 + sum(f.penalty for f in findings) + (5 if has_bonus else 0)
        score = max(0, min(100, raw))
        band, badge = _score_to_band_and_badge(score)

        return TsDisciplineFileReport(
            path=norm_rel,
            sloc=sloc,
            score=score,
            band=band,
            badge=badge,
            findings=findings,
            bonuses=bonuses,
        )

    def analyze_file(self, file_path: Path) -> TsDisciplineFileReport:
        resolved = Path(file_path).resolve()
        try:
            rel = resolved.relative_to(self.root_dir).as_posix()
        except ValueError:
            rel = resolved.as_posix()
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return self.analyze_source(content, rel_path=rel)

    def scan(self, target: Path, scoped_files: Optional[List[str]] = None) -> TsDisciplineSummary:
        files = self.get_ts_files(target, scoped_files=scoped_files)
        reports = [self.analyze_file(f) for f in files]
        reports.sort(key=lambda r: (r.score, r.path))

        total_sloc = sum(r.sloc for r in reports)
        if not reports:
            overall_score = 100.0
        elif total_sloc > 0:
            overall_score = round(sum(r.score * r.sloc for r in reports) / total_sloc, 1)
        else:
            overall_score = round(sum(r.score for r in reports) / len(reports), 1)

        overall_band, _ = _score_to_band_and_badge(overall_score)
        strict_count = sum(1 for r in reports if r.band == "STRICT")
        loose_count = sum(1 for r in reports if r.band == "LOOSE")
        porous_count = sum(1 for r in reports if r.band == "POROUS")

        rule_counts: Dict[str, int] = {}
        for r in reports:
            for f in r.findings:
                rule_counts[f.rule_id] = rule_counts.get(f.rule_id, 0) + 1

        return TsDisciplineSummary(
            target_path=str(target),
            files_analyzed=len(reports),
            total_sloc=total_sloc,
            overall_score=overall_score,
            overall_band=overall_band,
            strict_count=strict_count,
            loose_count=loose_count,
            porous_count=porous_count,
            rule_counts=rule_counts,
            file_reports=reports,
        )


def format_human(summary: TsDisciplineSummary, top: int = 15) -> str:
    lines: List[str] = []
    _, badge = _score_to_band_and_badge(summary.overall_score)
    lines.append("=" * 95)
    lines.append("🔷 TYPESCRIPT TYPE-SYSTEM DISCIPLINE AUDIT (edge-audit --track types)")
    lines.append("=" * 95)
    lines.append(f"Target Path      : {summary.target_path}")
    lines.append(f"Overall Score    : {badge} {summary.overall_score}/100 ({summary.overall_band})")
    lines.append(f"Files Analyzed   : {summary.files_analyzed} (Total SLOC: {summary.total_sloc:,})")
    lines.append(
        f"Band Distribution: 🟢 STRICT {summary.strict_count} | "
        f"🟡 LOOSE {summary.loose_count} | 🔴 POROUS {summary.porous_count}"
    )

    if summary.rule_counts:
        lines.append("\nRule Violation Counts:")
        for rule_id, cnt in sorted(summary.rule_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  - {rule_id:<28} : {cnt}")

    hotspots = [r for r in summary.file_reports if r.findings][:top]
    if hotspots:
        lines.append(f"\n🚨 TOP {len(hotspots)} TYPE-DISCIPLINE HOTSPOTS:")
        lines.append("-" * 95)
        for idx, r in enumerate(hotspots, 1):
            lines.append(f"[#{idx:02d}] {r.badge} [{r.score:03d}/100] ({r.sloc} SLOC) -> {r.path}")
            for f in r.findings[:8]:
                lines.append(f"       ❌ L{f.line_number} {f.rule_id} ({f.penalty}p): {f.message}")
    else:
        lines.append("\n✨ All analyzed TypeScript files passed with zero type-discipline penalties.")

    lines.append("=" * 95)
    return "\n".join(lines)


def format_markdown(summary: TsDisciplineSummary, top: int = 15) -> str:
    lines: List[str] = []
    lines.append("# 🔷 TypeScript Type-System Discipline Report (`--track types`)")
    lines.append("")
    lines.append(
        f"> **Target:** `{summary.target_path}` | **Overall Score:** `{summary.overall_score}/100` (`{summary.overall_band}`) | "
        f"**Files:** `{summary.files_analyzed}` (`{summary.total_sloc:,}` SLOC)"
    )
    lines.append("")
    lines.append("| Band | Count |")
    lines.append("| :--- | :--- |")
    lines.append(f"| 🟢 STRICT (85-100) | `{summary.strict_count}` |")
    lines.append(f"| 🟡 LOOSE (60-84) | `{summary.loose_count}` |")
    lines.append(f"| 🔴 POROUS (0-59) | `{summary.porous_count}` |")
    lines.append("")

    if summary.rule_counts:
        lines.append("## 📊 Rule Breakdown")
        lines.append("")
        lines.append("| Rule ID | Count |")
        lines.append("| :--- | :--- |")
        for rule_id, cnt in sorted(summary.rule_counts.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{rule_id}` | `{cnt}` |")
        lines.append("")

    hotspots = [r for r in summary.file_reports if r.findings][:top]
    if hotspots:
        lines.append(f"## 🚨 Top {len(hotspots)} Hotspots")
        lines.append("")
        lines.append("| Score | Band | SLOC | Path | Rules |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for r in hotspots:
            rules = ", ".join(dict.fromkeys(f.rule_id for f in r.findings))
            lines.append(f"| `{r.score}/100` | {r.badge} | `{r.sloc}` | `{r.path}` | {rules} |")
        lines.append("")

    return "\n".join(lines)


def format_json(summary: TsDisciplineSummary, top: int = 15) -> str:
    payload = {
        "ts_discipline_summary": {
            "target_path": summary.target_path,
            "overall_score": summary.overall_score,
            "overall_band": summary.overall_band,
            "files_analyzed": summary.files_analyzed,
            "total_sloc": summary.total_sloc,
            "strict_count": summary.strict_count,
            "loose_count": summary.loose_count,
            "porous_count": summary.porous_count,
            "rule_counts": dict(summary.rule_counts),
            "results": [r.to_dict() for r in summary.file_reports[:top]],
        }
    }
    return json.dumps(payload, indent=2)


def format_toon(summary: TsDisciplineSummary, top: int = 15) -> str:
    hotspots = [r for r in summary.file_reports if r.findings][:top]
    data = {
        "ts_discipline_result": {
            "target": summary.target_path,
            "overall_score": summary.overall_score,
            "overall_band": summary.overall_band,
            "files_analyzed": summary.files_analyzed,
            "total_sloc": summary.total_sloc,
            "strict_count": summary.strict_count,
            "loose_count": summary.loose_count,
            "porous_count": summary.porous_count,
            "rule_counts": dict(summary.rule_counts),
            "hotspots": [
                {
                    "path": r.path,
                    "score": r.score,
                    "band": r.band,
                    "sloc": r.sloc,
                    "rules": "|".join(dict.fromkeys(f.rule_id for f in r.findings)),
                }
                for r in hotspots
            ],
        }
    }
    return encode(data)
