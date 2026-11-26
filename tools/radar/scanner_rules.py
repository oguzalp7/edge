"""Per-file TS discipline, CRAP/function metrics, and DRYER AST clone checks."""

from pathlib import Path
from typing import Any, List, Optional

from tools.audit.ts_discipline import TsDisciplineAuditor
from .models import FindingSeverity, FindingStatus, LedgerItem, Track


def _compute_fn_crap(fn: Any, file_lcov: Any) -> Optional[float]:
    if file_lcov is None:
        return None
    try:
        from tools.audit.crapper import compute_crap, function_coverage_from_lcov
        return compute_crap(fn.complexity, function_coverage_from_lcov(file_lcov, fn.start_line, fn.end_line))
    except Exception:
        return None


def scan_function_metrics(fmetric: Any, rel: str, file_lcov: Any, findings: List[LedgerItem]) -> None:
    """Emit RULE-HIGH-CRAP and RULE-FAT-FUNCTION items for a file metric."""
    limit = 80 if "action" in rel else 60
    for fn in fmetric.functions:
        crap_score = _compute_fn_crap(fn, file_lcov)
        if crap_score is not None and crap_score >= 30.0:
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-HIGH-CRAP", rel, fn.name, str(round(crap_score, 1))),
                track=Track.CORE.value, rule_id="RULE-HIGH-CRAP",
                title=f"High Change Risk (CRAP {crap_score:.1f} >= 30.0): '{fn.name}' in {rel}",
                file_path=rel, line_number=fn.start_line, symbol=fn.name,
                severity=FindingSeverity.CRITICAL.value, status=FindingStatus.OPEN.value,
                details={"crap_score": crap_score, "complexity": fn.complexity, "sloc": fn.sloc},
                suggested_fix="Break function into smaller units or write missing branch tests.",
                first_seen_at="", last_seen_at="",
            ))
        if fn.sloc > limit and not (crap_score is not None and crap_score < 15.0):
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-FAT-FUNCTION", rel, fn.name),
                track=Track.CORE.value, rule_id="RULE-FAT-FUNCTION",
                title=f"Fat Function: '{fn.name}' has {fn.sloc} SLOC (limit: {limit}) in {rel}",
                file_path=rel, line_number=fn.start_line, symbol=fn.name,
                severity=FindingSeverity.WARNING.value, status=FindingStatus.OPEN.value,
                details={"sloc": fn.sloc, "complexity": fn.complexity},
                suggested_fix="Decompose into pure helper functions or delegate business calculation to src/core.",
                first_seen_at="", last_seen_at="",
            ))


def scan_ts_and_seam(fmetric: Any, rel: str, ts_auditor: TsDisciplineAuditor, check_ts: bool, findings: List[LedgerItem]) -> None:
    """Emit deep nesting, missing core test seam, and RULE-TS-* items."""
    if fmetric.max_indent_level > 5:
        findings.append(LedgerItem(
            fingerprint=LedgerItem.generate_fingerprint("RULE-DEEP-NESTING", rel, str(fmetric.max_indent_level)),
            track=Track.CORE.value, rule_id="RULE-DEEP-NESTING",
            title=f"Arrow Anti-Pattern: Deep indentation ({fmetric.max_indent_level} levels) in {rel}",
            file_path=rel, line_number=1, symbol=None, severity=FindingSeverity.WARNING.value, status=FindingStatus.OPEN.value,
            details={"max_indent": fmetric.max_indent_level, "sloc": fmetric.sloc},
            suggested_fix="Flatten nested callbacks/conditions using early returns, guard clauses, or reducer extraction.",
            first_seen_at="", last_seen_at="",
        ))
    is_exempt = rel.endswith(("types.ts", ".d.ts", "index.ts")) or "/examples/" in rel
    if rel.startswith("src/core/") and not is_exempt and not fmetric.has_test_seam and fmetric.sloc > 40:
        findings.append(LedgerItem(
            fingerprint=LedgerItem.generate_fingerprint("RULE-MISSING-TEST-SEAM", rel),
            track=Track.CORE.value, rule_id="RULE-MISSING-TEST-SEAM",
            title=f"Untested Core Domain Module: {rel} ({fmetric.sloc} SLOC)",
            file_path=rel, line_number=1, symbol=None, severity=FindingSeverity.CRITICAL.value, status=FindingStatus.OPEN.value,
            details={"sloc": fmetric.sloc}, suggested_fix="Add companion in-memory unit tests under tests/unit/ to guarantee hermetic domain verification.",
            first_seen_at="", last_seen_at="",
        ))
    norm_rel = rel.replace("\\", "/").lstrip("./")
    if not (check_ts and norm_rel.endswith((".ts", ".tsx")) and not norm_rel.endswith(".d.ts")):
        return
    ts_report = ts_auditor.analyze_file(fmetric.path)
    for tf in ts_report.findings:
        if tf.penalty < 0:
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint(tf.rule_id, norm_rel, tf.symbol or "", str(tf.line_number)),
                track=Track.CORE.value, rule_id=tf.rule_id, title=f"{tf.message} ({norm_rel}:{tf.line_number})",
                file_path=norm_rel, line_number=tf.line_number, symbol=tf.symbol, severity=tf.severity,
                status=FindingStatus.OPEN.value, details={"penalty": tf.penalty, "snippet": tf.snippet, "file_score": ts_report.score},
                suggested_fix=tf.suggested_fix, first_seen_at="", last_seen_at="",
            ))


def scan_dryer_clones(target_dir: Path, file_paths: Optional[List[str]], findings: List[LedgerItem]) -> None:
    """Emit RULE-AST-DUPLICATE findings from DryerScanner when Tree-sitter is available."""
    try:
        from tools.audit.dryer import TREE_SITTER_AVAILABLE, DryerScanner
        if not TREE_SITTER_AVAILABLE:
            return
        for pair in DryerScanner(threshold=0.82).scan_path(target_dir, scoped_files=file_paths):
            rel_left = pair.left.file_path[2:] if pair.left.file_path.startswith("./") else pair.left.file_path
            sev = FindingSeverity.CRITICAL.value if pair.score >= 0.92 else FindingSeverity.WARNING.value
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-AST-DUPLICATE", rel_left, pair.left.symbol, str(round(pair.score, 2))),
                track=Track.CORE.value, rule_id="RULE-AST-DUPLICATE",
                title=f"Structural AST Duplicate ({pair.score * 100:.1f}%): '{pair.left.symbol}' in {Path(rel_left).name} matches '{pair.right.symbol}' in {Path(pair.right.file_path).name}",
                file_path=rel_left, line_number=pair.left.start_line, symbol=pair.left.symbol,
                severity=sev, status=FindingStatus.OPEN.value,
                details={"score": pair.score, "right_file": pair.right.file_path, "right_symbol": pair.right.symbol},
                suggested_fix="Extract duplicate logic into shared domain helper under src/core/ or src/lib/.",
                first_seen_at="", last_seen_at="",
            ))
    except Exception:
        pass
