#!/usr/bin/env python3
"""
TypeScript Type-System Discipline Engine (tools/audit/ts_discipline.py).
Deterministic 0-100 scorer & analyzer enforcing type-system discipline across
.ts and .tsx files using Tree-sitter AST when available and a full-precision
sanitized lexer/regex fallback otherwise.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

try:
    import tree_sitter  # noqa: F401
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from tools.audit.ts_ast_analyzer import _analyze_with_ast
from tools.audit.ts_fallback_analyzer import _analyze_with_fallback
from tools.audit.ts_lexer import _sanitize_ts_source  # noqa: F401
from tools.audit.ts_models import (
    DEFAULT_EXCLUDE_DIRS,
    TsDisciplineFileReport,
    TsDisciplineFinding,
    TsDisciplineSummary,
    _compute_sloc,
    _is_test_path,
    _normalize_rel_path,
    _score_to_band_and_badge,
)
from tools.audit.ts_reporters import format_human, format_json, format_markdown, format_toon


def _get_parser_for_ext(ext: str) -> Optional[Any]:
    if not TREE_SITTER_AVAILABLE:
        return None
    norm = ext.lower()
    if norm == ".ts":
        return tslp.get_parser("typescript")
    return tslp.get_parser("tsx") if norm == ".tsx" else None


def _safe_rel(root_dir: Path, path: Path) -> str:
    try:
        return path.relative_to(root_dir).as_posix()
    except ValueError:
        return path.as_posix()


class TsDisciplineAuditor:
    """Deterministic TypeScript/TSX Type-System Discipline Auditor."""

    def __init__(self, root_dir: Path, exclude_dirs: Optional[Set[str]] = None, include_tests: bool = False):
        self.root_dir = Path(root_dir).resolve()
        self.exclude_dirs = set(exclude_dirs) if exclude_dirs is not None else set(DEFAULT_EXCLUDE_DIRS)
        self.include_tests = include_tests

    def _is_eligible_file(self, file_path: Path, rel_path: str) -> bool:
        name = file_path.name.lower()
        if not name.endswith((".ts", ".tsx")) or name.endswith(".d.ts"):
            return False
        if set(_normalize_rel_path(rel_path).split("/")[:-1]) & self.exclude_dirs:
            return False
        return self.include_tests or not _is_test_path(rel_path)

    def _collect_scoped_files(self, target_path: Path, scoped_files: List[str]) -> List[Path]:
        results: List[Path] = []
        seen: Set[Path] = set()
        for entry in scoped_files:
            p = Path(entry)
            cand = p.resolve() if p.is_absolute() else (self.root_dir / p).resolve()
            if not p.is_absolute() and not cand.exists():
                cand = (target_path / p).resolve()
            if not cand.is_file() or cand in seen:
                continue
            if self._is_eligible_file(cand, _safe_rel(self.root_dir, cand)):
                seen.add(cand)
                results.append(cand)
        return sorted(results)

    def get_ts_files(self, target: Path, scoped_files: Optional[List[str]] = None) -> List[Path]:
        target_path = Path(target).resolve()
        if scoped_files is not None:
            return self._collect_scoped_files(target_path, scoped_files)
        if target_path.is_file():
            return [target_path] if self._is_eligible_file(target_path, _safe_rel(self.root_dir, target_path)) else []
        if not target_path.exists():
            return []
        results: List[Path] = []
        for dirpath, dirnames, filenames in os.walk(target_path):
            dirnames[:] = sorted(d for d in dirnames if d not in self.exclude_dirs)
            cands = (Path(dirpath) / fn for fn in sorted(filenames))
            results.extend(fp for fp in cands if self._is_eligible_file(fp, _safe_rel(self.root_dir, fp.resolve())))
        return sorted(results)

    def analyze_source(self, source: str, rel_path: str = "input.ts") -> TsDisciplineFileReport:
        norm_rel = _normalize_rel_path(rel_path)
        sloc = _compute_sloc(source)
        parser = _get_parser_for_ext(".tsx" if norm_rel.lower().endswith(".tsx") else ".ts") if TREE_SITTER_AVAILABLE else None
        findings, has_bonus = _analyze_with_ast(source, norm_rel, parser) if parser is not None else _analyze_with_fallback(source, norm_rel)
        findings.sort(key=lambda f: (f.line_number, f.rule_id))
        bonuses = (
            [TsDisciplineFinding(
                "BONUS-TS-DISCIPLINE", "BONUS", 5, 1, None,
                "Positive type-system discipline signal detected (`satisfies`, branded type, `z.infer`, or exhaustive `never`).",
                "", "",
            )]
            if has_bonus else []
        )
        score = max(0, min(100, 100 + sum(f.penalty for f in findings) + (5 if has_bonus else 0)))
        band, badge = _score_to_band_and_badge(score)
        return TsDisciplineFileReport(path=norm_rel, sloc=sloc, score=score, band=band, badge=badge, findings=findings, bonuses=bonuses)

    def analyze_file(self, file_path: Path) -> TsDisciplineFileReport:
        resolved = Path(file_path).resolve()
        return self.analyze_source(resolved.read_text(encoding="utf-8", errors="replace"), rel_path=_safe_rel(self.root_dir, resolved))

    def scan(self, target: Path, scoped_files: Optional[List[str]] = None) -> TsDisciplineSummary:
        reports = sorted((self.analyze_file(f) for f in self.get_ts_files(target, scoped_files=scoped_files)), key=lambda r: (r.score, r.path))
        total_sloc = sum(r.sloc for r in reports)
        if not reports:
            overall_score = 100.0
        elif total_sloc > 0:
            overall_score = round(sum(r.score * r.sloc for r in reports) / total_sloc, 1)
        else:
            overall_score = round(sum(r.score for r in reports) / len(reports), 1)

        overall_band, _ = _score_to_band_and_badge(overall_score)
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
            strict_count=sum(1 for r in reports if r.band == "STRICT"),
            loose_count=sum(1 for r in reports if r.band == "LOOSE"),
            porous_count=sum(1 for r in reports if r.band == "POROUS"),
            rule_counts=rule_counts,
            file_reports=reports,
        )
