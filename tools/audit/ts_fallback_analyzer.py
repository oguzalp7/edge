"""
Full-precision sanitized lexer/regex fallback analyzer for TypeScript/TSX files.
"""

from __future__ import annotations

from typing import List, Tuple

from tools.audit.ts_fallback_helpers import _is_object_or_array_literal_lhs, _mask_import_export_aliases, _mask_span
from tools.audit.ts_fallback_rules import (
    scan_non_null_assertions,
    scan_optional_bags,
    scan_positional_args,
    scan_switch_exhaustiveness,
)
from tools.audit.ts_lexer import _sanitize_ts_source
from tools.audit.ts_models import (
    _BRAND_RE,
    _DOUBLE_CAST_RE,
    _RECORD_UNKNOWN_RE,
    _SATISFIES_RE,
    _SUPPRESSION_RE,
    _UNSAFE_AS_RE,
    _Z_INFER_RE,
    TsDisciplineFinding,
    _build_line_starts,
    _is_core_or_lib_path,
    _is_test_path,
    _offset_to_line,
    make_finding,
)
from tools.rules import TS_CONSOLE_LOG_PATTERN, TS_EXPLICIT_ANY_PATTERN


def _scan_core_and_cast_rules(
    masked: str, comments: List[Tuple[int, str]], line_starts: List[int], lines: List[str]
) -> List[TsDisciplineFinding]:
    findings: List[TsDisciplineFinding] = []
    for m in TS_EXPLICIT_ANY_PATTERN.finditer(masked):
        findings.append(make_finding(
            "RULE-TS-EXPLICIT-ANY", "CRITICAL", -20, _offset_to_line(line_starts, m.start()), "any",
            "Explicit `any` bypasses TypeScript structural soundness.",
            "Replace `any` with `unknown` and narrow with Zod or explicit type guards.", lines,
        ))
    for c_line, c_text in comments:
        if (m := _SUPPRESSION_RE.search(c_text)):
            findings.append(make_finding(
                "RULE-TS-SUPPRESSION", "CRITICAL", -20, c_line, m.group(0),
                f"Compiler suppression `{m.group(0)}` hides type errors.",
                "Remove suppression directive and fix the underlying type contract.", lines,
            ))
    masked_no_double = list(masked)
    for m in _DOUBLE_CAST_RE.finditer(masked):
        _mask_span(masked_no_double, m.start(), m.end())
        findings.append(make_finding(
            "RULE-TS-DOUBLE-CAST", "CRITICAL", -20, _offset_to_line(line_starts, m.start()), "as unknown as",
            "Double cast `as unknown as` forces arbitrary type conversion.",
            "Validate the value with a Zod schema or verifying type guard instead of double-casting.", lines,
        ))
    masked_for_as = _mask_import_export_aliases("".join(masked_no_double))
    for m in _UNSAFE_AS_RE.finditer(masked_for_as):
        target_type = m.group(1).strip()
        if target_type in ("const", "any"):
            continue
        fix = (
            f"Use `satisfies {target_type}` instead of `as {target_type}` to preserve narrow literal inference."
            if _is_object_or_array_literal_lhs(masked_for_as, m.start())
            else "Prefer discriminant `switch`, `in`, `typeof`/`instanceof`, or a verifying type guard over `as`."
        )
        findings.append(make_finding(
            "RULE-TS-UNSAFE-AS", "WARNING", -10, _offset_to_line(line_starts, m.start()), f"as {target_type}",
            f"Unsafe type assertion `as {target_type}` overrides compiler verification.", fix, lines,
        ))
    return findings


def _scan_runtime_and_structural_rules(
    masked: str, line_starts: List[int], lines: List[str], is_test: bool, is_core_lib: bool
) -> Tuple[List[TsDisciplineFinding], bool]:
    findings = scan_non_null_assertions(masked, line_starts, lines)
    if not is_test:
        for m in TS_CONSOLE_LOG_PATTERN.finditer(masked):
            findings.append(make_finding(
                "RULE-TS-CONSOLE-LOG", "WARNING", -8, _offset_to_line(line_starts, m.start()), "console.log",
                "`console.log(...)` left in shipped production TypeScript file.",
                "Remove debug `console.log` or emit structured telemetry.", lines,
            ))
    if is_core_lib:
        for m in _RECORD_UNKNOWN_RE.finditer(masked):
            findings.append(make_finding(
                "RULE-TS-RECORD-UNKNOWN", "WARNING", -8, _offset_to_line(line_starts, m.start()), "Record<string, unknown>",
                "Untyped `Record<string, unknown>` leaked into core/lib domain boundary.",
                "Validate at perimeter (actions/routes) and pass typed domain contracts into src/core and src/lib.", lines,
            ))
    sw_findings, has_never_switch_bonus = scan_switch_exhaustiveness(masked, line_starts, lines)
    findings.extend(sw_findings)
    findings.extend(scan_optional_bags(masked, line_starts, lines))
    findings.extend(scan_positional_args(masked, line_starts, lines))
    has_bonus = has_never_switch_bonus or bool(_SATISFIES_RE.search(masked) or _BRAND_RE.search(masked) or _Z_INFER_RE.search(masked))
    return findings, has_bonus


def _analyze_with_fallback(source: str, rel_path: str) -> Tuple[List[TsDisciplineFinding], bool]:
    is_tsx = rel_path.lower().endswith(".tsx")
    lines, line_starts = source.splitlines(), _build_line_starts(source)
    masked, comments = _sanitize_ts_source(source, is_tsx=is_tsx)
    findings = _scan_core_and_cast_rules(masked, comments, line_starts, lines)
    extra, has_bonus = _scan_runtime_and_structural_rules(
        masked, line_starts, lines, _is_test_path(rel_path), _is_core_or_lib_path(rel_path)
    )
    findings.extend(extra)
    return findings, has_bonus
