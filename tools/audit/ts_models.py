"""
Data contracts, scoring helpers, path classifiers, and shared regexes for ts_discipline.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

DEFAULT_EXCLUDE_DIRS: Set[str] = {
    "node_modules", ".next", "dist", "build", "coverage",
    ".git", ".edge", ".archive", ".scratch", "scratch", "__pycache__",
}
_STATUS_BOOLEAN_NAMES: Set[str] = {"loading", "isLoading", "error", "hasError", "success", "isSuccess", "pending", "isPending"}
_NON_NULL_PRECEDING_KEYWORDS: Set[str] = {"return", "throw", "typeof", "void", "delete", "await", "yield", "case", "in", "of", "else"}
_CONTROL_KEYWORDS: Set[str] = {"if", "for", "while", "switch", "catch", "return", "throw", "new", "typeof", "delete", "void", "await", "yield", "case", "else"}

_SUPPRESSION_RE = re.compile(r"@ts-(?:ignore|expect-error|nocheck)\b")
_DOUBLE_CAST_RE = re.compile(r"\bas\s+unknown\s+as\b")
_UNSAFE_AS_RE = re.compile(r"\bas\s+([A-Za-z_$][\w$.<>]*|\{[^}]*\}|\([^)]*\)|\[[^\]]*\])")
_RECORD_UNKNOWN_RE = re.compile(r"\bRecord\s*<\s*string\s*,\s*unknown\s*>")
_NEVER_BINDING_RE = re.compile(r":\s*never\b")
_SATISFIES_RE = re.compile(r"\bsatisfies\b")
_BRAND_RE = re.compile(r"\breadonly\s+__brand\b")
_Z_INFER_RE = re.compile(r"\bz\.infer\s*<")
_PROP_SIG_RE = re.compile(r"^(?:readonly\s+)?([A-Za-z_$][\w$]*)\s*(\??)\s*:\s*(.+)$")
_ID_PARAM_RE = re.compile(r"^(?:public\s+|private\s+|protected\s+|readonly\s+)?([A-Za-z_$][\w$]*Id)\s*(\??)\s*:\s*string\b")
_FUNC_DECL_SIG_RE = re.compile(r"\bfunction\s*\*?\s*([A-Za-z_$][\w$]*)?\s*(?:<[^>]*>)?\s*\(")
_ARROW_VAR_SIG_RE = re.compile(r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^>]*>)?\s*\(")
_METHOD_SIG_RE = re.compile(r"(?:^|[;{]\s*)(?:export\s+|public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+|async\s+|\*\s*)*([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(")


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
            "rule_id": self.rule_id, "severity": self.severity, "penalty": self.penalty,
            "line_number": self.line_number, "symbol": self.symbol, "message": self.message,
            "suggested_fix": self.suggested_fix, "snippet": self.snippet,
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
            "path": self.path, "sloc": self.sloc, "score": self.score, "band": self.band,
            "badge": self.badge, "findings": [f.to_dict() for f in self.findings],
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
            "target_path": self.target_path, "files_analyzed": self.files_analyzed,
            "total_sloc": self.total_sloc, "overall_score": self.overall_score,
            "overall_band": self.overall_band, "strict_count": self.strict_count,
            "loose_count": self.loose_count, "porous_count": self.porous_count,
            "rule_counts": dict(self.rule_counts), "file_reports": [r.to_dict() for r in self.file_reports],
        }


def _score_to_band_and_badge(score: float) -> Tuple[str, str]:
    if score >= 85:
        return "STRICT", "🟢 STRICT"
    return ("LOOSE", "🟡 LOOSE") if score >= 60 else ("POROUS", "🔴 POROUS")


def _normalize_rel_path(rel_path: str) -> str:
    norm = rel_path.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _is_test_path(rel_path: str) -> bool:
    norm = _normalize_rel_path(rel_path)
    name = Path(norm).name
    return (
        ".test." in name or ".spec." in name or "_test." in name
        or norm.startswith(("tests/", "__tests__/")) or "/tests/" in norm or "/__tests__/" in norm
    )


def _is_core_or_lib_path(rel_path: str) -> bool:
    norm = _normalize_rel_path(rel_path)
    return norm.startswith(("src/core/", "src/lib/")) or "/src/core/" in norm or "/src/lib/" in norm


def _build_line_starts(source: str) -> List[int]:
    return [0] + [idx + 1 for idx, ch in enumerate(source) if ch == "\n"]


def _offset_to_line(line_starts: List[int], offset: int) -> int:
    return bisect_right(line_starts, offset)


def _line_snippet(lines: List[str], line_no: int) -> str:
    return lines[line_no - 1].strip() if 1 <= line_no <= len(lines) else ""


def _compute_sloc(source: str) -> int:
    return sum(1 for line in source.splitlines() if (s := line.strip()) and not s.startswith("//"))


def make_finding(
    rule_id: str, severity: str, penalty: int, line_no: int, symbol: Optional[str], message: str, fix: str, lines: List[str]
) -> TsDisciplineFinding:
    return TsDisciplineFinding(rule_id, severity, penalty, line_no, symbol, message, fix, _line_snippet(lines, line_no))
