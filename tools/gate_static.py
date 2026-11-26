"""Static regex/path helpers and GateResult model for Edge Verification Gate."""

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.gate_cc import strip_js_comments_and_strings
from tools.rules import (
    BG_WHITE_NO_DARK_PATTERN,
    ICON_X_BUTTON_NO_ARIA_PATTERN,
    MOCK_FALLBACK_PATTERN,
    SQL_LEAK_PATTERN,
    TYPE_ESCAPE_PATTERN,
)

PRODUCTION_CODE_SUFFIXES: Tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".py")
ACTION_CODE_SUFFIXES: Tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
_NON_DIRECTIVE_COMMENT_RE = re.compile(r"//(?!\s*@ts-(?:ignore|expect-error|nocheck)\b)[^\n]*")
_BG_WHITE_TOKEN_RE = re.compile(r"(?<![-\w])bg-white\b")
_DIFF_HUNK_HEADER_RE = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_GATE_TS_RULES: Tuple[str, ...] = (
    "RULE-TS-EXPLICIT-ANY", "RULE-TS-SUPPRESSION", "RULE-TS-DOUBLE-CAST",
    "RULE-TS-NON-NULL", "RULE-TS-CONSOLE-LOG",
)


class GateResult:
    """Outcome record for a single verification gate stage."""

    def __init__(
        self, stage_num: int, name: str, passed: bool, message: str,
        details: Optional[List[str]] = None, metrics: Optional[Dict[str, Any]] = None,
    ):
        self.stage_num = stage_num
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or []
        self.metrics: Dict[str, Any] = dict(metrics) if metrics is not None else {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage_num": self.stage_num, "name": self.name, "passed": self.passed,
            "message": self.message, "details": list(self.details), "metrics": dict(self.metrics),
        }

    def __str__(self) -> str:
        icon = "✅ PASS" if self.passed else "❌ FAIL"
        lines = [f"[{icon}] Stage {self.stage_num}: {self.name}", f"  {self.message}"]
        lines.extend(f"    - {d}" for d in self.details)
        return "\n".join(lines)


def is_excluded_non_prod_path(rel_path: str) -> bool:
    """Return True if path is a test, doc, config, or .edge artifact."""
    norm = rel_path.strip().replace("\\", "/").lstrip("./")
    if not norm:
        return True
    name = Path(norm).name.lower()
    markers = (".test.", ".spec.", "/tests/", "/__tests__/", "/.edge/")
    prefixes = ("tests/", "__tests__/", ".edge/")
    return (
        any(m in norm for m in markers) or norm.startswith(prefixes)
        or name.startswith("test_") or name.endswith(("_test.py", ".md", ".json"))
    )


def is_action_controller_path(rel_path: str) -> bool:
    """Return True when rel_path points to a JS/TS action controller file."""
    norm = rel_path.strip().replace("\\", "/").lstrip("./")
    if is_excluded_non_prod_path(norm) or Path(norm).suffix.lower() not in ACTION_CODE_SUFFIXES:
        return False
    return "actions" in norm.split("/")[:-1]


def count_sql_leaks(source_text: str) -> int:
    """Count direct DB operations in sanitized JS/TS source."""
    return len(SQL_LEAK_PATTERN.findall(strip_js_comments_and_strings(source_text)))


def is_eligible_prod_path(rel_path: str, suffixes: Tuple[str, ...], require_src_prefix: bool) -> bool:
    """Return True when rel_path is a non-excluded production source file."""
    if is_excluded_non_prod_path(rel_path):
        return False
    if require_src_prefix and not rel_path.startswith("src/"):
        return False
    return Path(rel_path).suffix.lower() in suffixes


def find_mock_fallback_violations(rel_path: str, content: str) -> List[str]:
    """Detect DEFAULT_* and MOCK_* synthetic fallbacks in production source."""
    hits: List[str] = []
    for idx, line in enumerate(strip_js_comments_and_strings(content).splitlines(), start=1):
        m = MOCK_FALLBACK_PATTERN.search(line)
        if m:
            hits.append(f"{rel_path}:{idx} - Production mock/default fallback '{m.group(0)}' detected.")
    return hits


def find_type_escape_violations(rel_path: str, content: str) -> List[str]:
    """Detect explicit TS type escapes outside directive comments."""
    hits: List[str] = []
    for idx, line in enumerate(_NON_DIRECTIVE_COMMENT_RE.sub("", content).splitlines(), start=1):
        m = TYPE_ESCAPE_PATTERN.search(line)
        if m:
            hits.append(f"{rel_path}:{idx} - Type escape '{m.group(0)}' detected.")
    return hits


def find_dual_theme_and_a11y_violations(rel_path: str, content: str) -> List[str]:
    """Detect unpaired bg-white and icon-only <X> buttons missing aria-label."""
    hits: List[str] = []
    for m in BG_WHITE_NO_DARK_PATTERN.finditer(content):
        raw_cls = m.group(0)
        if _BG_WHITE_TOKEN_RE.search(raw_cls) and "dark:bg-" not in raw_cls:
            hits.append(f"{rel_path}: className contains 'bg-white' without paired 'dark:bg-*' token.")
    for m in ICON_X_BUTTON_NO_ARIA_PATTERN.finditer(content):
        if "aria-label" not in m.group("attrs"):
            hits.append(f"{rel_path}: icon-only <X> <button> missing 'aria-label'.")
    return hits


def get_added_line_numbers(run_cmd: Any, eff_base: str, rel_path: str, total_lines: int) -> Set[int]:
    """Return 1-based line numbers added or modified relative to eff_base."""
    show_code, _, _ = run_cmd(["git", "show", f"{eff_base}:{rel_path}"])
    if show_code != 0:
        return set(range(1, total_lines + 1))
    diff_code, diff_out, _ = run_cmd(["git", "diff", "-U0", eff_base, "--", rel_path])
    if diff_code != 0:
        return set()
    added: Set[int] = set()
    for match in _DIFF_HUNK_HEADER_RE.finditer(diff_out):
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count > 0:
            added.update(range(start, start + count))
    return added


def collect_ts_diff_violations(
    ts_auditor: Any, rel_path: str, content: str, added_lines: Set[int], seen_keys: Set[Tuple[str, int]]
) -> List[str]:
    """Collect newly added RULE-TS-* violations from TsDisciplineAuditor."""
    if not added_lines:
        return []
    hits: List[str] = []
    ts_report = ts_auditor.analyze_source(content, rel_path=rel_path)
    for finding in ts_report.findings:
        if finding.rule_id not in _GATE_TS_RULES:
            continue
        if finding.rule_id == "RULE-TS-CONSOLE-LOG" and not rel_path.startswith("src/"):
            continue
        key = (rel_path, finding.line_number)
        if finding.line_number not in added_lines or key in seen_keys:
            continue
        seen_keys.add(key)
        hits.append(f"{rel_path}:{finding.line_number} - {finding.rule_id}: {finding.message}")
    return hits
