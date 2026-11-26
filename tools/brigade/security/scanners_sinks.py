"""Submodule: scanners_sinks."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.brigade.security.constants import _CMD_EXEC_RE, _DANGEROUS_HTML_RE, _EVAL_SINK_RE, _HARDCODED_SECRET_RE, _HTML_SANITIZER_RE, _MATH_RANDOM_RE, _PY_CMD_EXEC_RE, _PY_EVAL_SINK_RE, _SEC_CTX_RE, _SQL_RAW_INTERP_RE
from tools.brigade.security.models import SecurityFinding
from tools.brigade.security.exclusions import _compute_excluded_lines, _make_finding
from tools.brigade.security.refutation import _enclosing_fn_ranges
from tools.brigade.security.scanners_abac import _scan_abac_class, _scan_data_isolation_class

def _scan_js_injection_line(
    rel: str,
    idx: int,
    line: str,
    fn_name: str,
    has_sanitizer: bool,
) -> List[SecurityFinding]:
    findings: List[SecurityFinding] = []
    if _SQL_RAW_INTERP_RE.search(line):
        findings.append(_make_finding("INJECTION_AND_SINKS", "confirmed", "CRITICAL", rel, idx, fn_name, "sql.raw(${...})", line, "sql_sink"))
    if _DANGEROUS_HTML_RE.search(line):
        if has_sanitizer:
            findings.append(_make_finding(
                "INJECTION_AND_SINKS", "rejected", None, rel, idx, fn_name, "dangerouslySetInnerHTML", line, "xss_sink",
                rejection_reason="Refuted: sanitizer (DOMPurify/sanitize) verified in file",
            ))
        else:
            findings.append(_make_finding("INJECTION_AND_SINKS", "confirmed", "HIGH", rel, idx, fn_name, "dangerouslySetInnerHTML", line, "xss_sink"))
    return findings


def _scan_injection_line(
    rel: str,
    idx: int,
    line: str,
    fn_name: str,
    has_sanitizer: bool,
    is_python: bool,
) -> List[SecurityFinding]:
    findings = [] if is_python else _scan_js_injection_line(rel, idx, line, fn_name, has_sanitizer)
    cmd_re = _PY_CMD_EXEC_RE if is_python else _CMD_EXEC_RE
    eval_re = _PY_EVAL_SINK_RE if is_python else _EVAL_SINK_RE
    is_cmd = bool(cmd_re.search(line))
    if is_cmd or eval_re.search(line):
        sev = "CRITICAL" if is_cmd else "HIGH"
        sink_lbl = "shell_exec" if is_cmd else "eval_sink"
        findings.append(_make_finding("INJECTION_AND_SINKS", "confirmed", sev, rel, idx, fn_name, sink_lbl, line, "exec_sink"))
    return findings


def _scan_injection_class(
    rel: str,
    content: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
    is_python: bool = False,
) -> List[SecurityFinding]:
    excl = excluded_lines or set()
    findings: List[SecurityFinding] = []
    has_sanitizer = bool(_HTML_SANITIZER_RE.search(content))
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        _, fn_name = fn_map[idx]
        findings.extend(_scan_injection_line(rel, idx, line, fn_name, has_sanitizer, is_python))
    return findings


def _scan_crypto_class(
    rel: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
    is_python: bool = False,
) -> List[SecurityFinding]:
    excl = excluded_lines or set()
    findings: List[SecurityFinding] = []
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        _, fn_name = fn_map[idx]
        if _HARDCODED_SECRET_RE.search(line):
            findings.append(_make_finding("CRYPTO_AND_SECRETS", "confirmed", "CRITICAL", rel, idx, fn_name, "hardcoded_secret", line, "secret_literal"))
        if not is_python and _MATH_RANDOM_RE.search(line):
            win = " ".join(lines[max(0, idx - 3) : min(len(lines), idx + 3)]) + f" {fn_name}"
            if _SEC_CTX_RE.search(win):
                findings.append(_make_finding("CRYPTO_AND_SECRETS", "confirmed", "HIGH", rel, idx, fn_name, "Math.random()", line, "crypto_prng"))
    return findings


def _scan_single_file(rel: str, path: Path, allow_server_actions: bool = True) -> List[SecurityFinding]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    is_python = Path(rel).suffix.lower() == ".py"
    excluded_lines = _compute_excluded_lines(content, lines, is_python)
    fn_map = _enclosing_fn_ranges(lines, is_python=is_python)
    found: List[SecurityFinding] = []
    found.extend(_scan_abac_class(rel, content, lines, fn_map, excluded_lines, allow_server_actions=allow_server_actions))
    found.extend(_scan_data_isolation_class(rel, lines, fn_map, excluded_lines))
    found.extend(_scan_injection_class(rel, content, lines, fn_map, excluded_lines, is_python))
    found.extend(_scan_crypto_class(rel, lines, fn_map, excluded_lines, is_python))
    return found
