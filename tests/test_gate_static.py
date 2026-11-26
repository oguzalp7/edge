"""Companion unit tests for tools.gate_static."""

from types import SimpleNamespace

from tools.gate_static import (
    PRODUCTION_CODE_SUFFIXES,
    GateResult,
    collect_ts_diff_violations,
    count_sql_leaks,
    find_dual_theme_and_a11y_violations,
    find_mock_fallback_violations,
    find_type_escape_violations,
    get_added_line_numbers,
    is_action_controller_path,
    is_eligible_prod_path,
    is_excluded_non_prod_path,
)


def test_gate_result_to_dict_and_str() -> None:
    res = GateResult(2, "Static Check", False, "Failed check", ["detail 1"], {"count": 1})
    as_dict = res.to_dict()
    assert as_dict["stage_num"] == 2
    assert as_dict["passed"] is False
    assert as_dict["metrics"] == {"count": 1}
    assert "FAIL" in str(res)


def test_path_classification_and_sql_leaks() -> None:
    assert ".ts" in PRODUCTION_CODE_SUFFIXES
    assert is_excluded_non_prod_path("tests/unit/foo.test.ts") is True
    assert is_excluded_non_prod_path("src/core/service.ts") is False
    assert is_action_controller_path("src/actions/booking.ts") is True
    assert is_action_controller_path("src/repositories/booking.ts") is False
    assert is_eligible_prod_path("src/app.ts", (".ts",), require_src_prefix=True) is True
    assert is_eligible_prod_path("lib/app.ts", (".ts",), require_src_prefix=True) is False
    assert count_sql_leaks("const x = db.select().from(users); // db.insert()") == 1


def test_mock_fallback_type_escape_and_a11y_scanners() -> None:
    assert len(find_mock_fallback_violations("src/a.ts", "const DEFAULT_DATA = [];")) == 1
    assert find_type_escape_violations("src/a.ts", "const x = val as any;") == [
        "src/a.ts:1 - Type escape 'as any' detected."
    ]
    a11y_hits = find_dual_theme_and_a11y_violations(
        "src/Btn.tsx",
        '<button className="bg-white p-2"><X className="w-4 h-4" /></button>',
    )
    assert any("bg-white" in h for h in a11y_hits)
    assert any("aria-label" in h for h in a11y_hits)


def test_added_lines_and_ts_diff_violations() -> None:
    def fake_run(cmd):
        if cmd[:2] == ["git", "show"]:
            return 0, "old", ""
        return 0, "@@ -1,0 +2,2 @@\n+line2\n+line3\n", ""

    added = get_added_line_numbers(fake_run, "HEAD~1", "src/a.ts", 5)
    assert added == {2, 3}

    fake_auditor = SimpleNamespace(
        analyze_source=lambda content, rel_path: SimpleNamespace(
            findings=[
                SimpleNamespace(rule_id="RULE-TS-EXPLICIT-ANY", line_number=2, message="avoid any"),
                SimpleNamespace(rule_id="RULE-TS-EXPLICIT-ANY", line_number=5, message="old line"),
            ]
        )
    )
    hits = collect_ts_diff_violations(fake_auditor, "src/a.ts", "code", added, set())
    assert hits == ["src/a.ts:2 - RULE-TS-EXPLICIT-ANY: avoid any"]
