"""
RED Unit & Integration Tests for TypeScript Type-System Discipline Engine (`tools/audit/ts_discipline.py`),
CLI `--track types` / `--track all` integration (`tools/audit/cli.py`),
Radar `scan_core` integration (`tools/radar/scanner.py`),
Shared rule patterns (`tools/rules.py`),
and Gate diff-added-lines hardening (`tools/gate.py`).

Spec SSOT: z:\\home\\oguz\\MS-Randevu-monolith\\.edge\\specs\\ts-discipline-engine.md
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pytest


def _load_ts_discipline():
    """Import the target engine lazily so pytest collects all RED tests cleanly."""
    import tools.audit.ts_discipline as mod

    return mod


def _is_tree_sitter_available() -> bool:
    try:
        import tree_sitter  # noqa: F401
        import tree_sitter_language_pack  # noqa: F401

        return True
    except ImportError:
        return False


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.email", "seam@edge.local")
    _git(repo, "config", "user.name", "Seam Architect")


def _write_and_commit(repo: Path, files: Dict[str, str], msg: str) -> None:
    for rel_path, content in files.items():
        full = repo / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--no-gpg-sign", "-m", msg)


def _analyze(tmp_path: Path, source: str, rel_path: str = "src/core/sample.ts"):
    mod = _load_ts_discipline()
    auditor = mod.TsDisciplineAuditor(tmp_path)
    return auditor.analyze_source(source, rel_path=rel_path)


def _rule_ids(report) -> List[str]:
    return [f.rule_id for f in report.findings]


# =============================================================================
# 1. Public API & All 10 Penalty Rules + 1 Bonus Rule (Positives & Exclusions)
# =============================================================================


class TestTsDisciplineContractsAndRules:
    def test_public_dataclasses_and_to_dict(self, tmp_path: Path) -> None:
        mod = _load_ts_discipline()
        finding = mod.TsDisciplineFinding(
            rule_id="RULE-TS-EXPLICIT-ANY",
            severity="CRITICAL",
            penalty=-20,
            line_number=3,
            symbol="parseInput",
            message="Explicit any detected",
            suggested_fix="Use unknown and narrow with Zod",
            snippet="function parseInput(x: any) {}",
        )
        f_dict = finding.to_dict()
        assert f_dict["rule_id"] == "RULE-TS-EXPLICIT-ANY"
        assert f_dict["penalty"] == -20
        assert f_dict["line_number"] == 3

        report = mod.TsDisciplineFileReport(
            path="src/core/sample.ts",
            sloc=10,
            score=80,
            band="LOOSE",
            badge="🟡 LOOSE",
            findings=[finding],
            bonuses=[],
        )
        r_dict = report.to_dict()
        assert r_dict["score"] == 80
        assert r_dict["band"] == "LOOSE"

        summary = mod.TsDisciplineSummary(
            target_path=str(tmp_path),
            files_analyzed=1,
            total_sloc=10,
            overall_score=80.0,
            overall_band="LOOSE",
            strict_count=0,
            loose_count=1,
            porous_count=0,
            rule_counts={"RULE-TS-EXPLICIT-ANY": 1},
            file_reports=[report],
        )
        s_dict = summary.to_dict()
        assert s_dict["overall_score"] == 80.0
        assert s_dict["files_analyzed"] == 1

    def test_rule_explicit_any_detection_and_exclusions(self, tmp_path: Path) -> None:
        # Positive detections: : any, <any>, as any, any[], Array<any>
        snippets = [
            "export function parse(x: any): string { return String(x); }\n",
            "export const data = decode<any>(raw);\n",
            "export const cast = payload as any;\n",
            "export const items: any[] = [];\n",
            "export const rows: Array<any> = [];\n",
        ]
        for idx, code in enumerate(snippets):
            report = _analyze(tmp_path, code, rel_path=f"src/core/any_{idx}.ts")
            hits = [f for f in report.findings if f.rule_id == "RULE-TS-EXPLICIT-ANY"]
            assert len(hits) >= 1, f"Expected RULE-TS-EXPLICIT-ANY for snippet {idx}: {code}"
            assert hits[0].penalty == -20
            assert hits[0].severity == "CRITICAL"
            assert "RULE-TS-UNSAFE-AS" not in _rule_ids(report), (
                "as any must be owned solely by RULE-TS-EXPLICIT-ANY"
            )

        # False-positive exclusions: comments, strings, templates, identifiers (Company, many, anyId)
        clean_source = (
            "// x: any and payload as any and any[]\n"
            "/* Array<any> and parse<any>(x) */\n"
            'const msg = "avoid : any, <any>, as any, and any[]";\n'
            "const tpl = `never write x: any or Array<any>`;\n"
            "export interface Company {\n"
            "    anyId: string;\n"
            "    companyName: string;\n"
            "    manyFlags: boolean;\n"
            "    anythingSpecial: number;\n"
            "}\n"
            "export function hasMany(company: Company): string {\n"
            "    return company.anyId;\n"
            "}\n"
        )
        clean_report = _analyze(tmp_path, clean_source, rel_path="src/core/company.ts")
        assert clean_report.findings == []
        assert clean_report.score == 100

    def test_rule_suppression_detection_and_exclusions(self, tmp_path: Path) -> None:
        for directive in (
            "// @ts-ignore\nconst a = 1;\n",
            "// @ts-expect-error temporary\nconst b = 2;\n",
            "// @ts-nocheck\nexport const c = 3;\n",
            "/* @ts-ignore */\nconst d = 4;\n",
        ):
            report = _analyze(tmp_path, directive, rel_path="src/core/supp.ts")
            hits = [f for f in report.findings if f.rule_id == "RULE-TS-SUPPRESSION"]
            assert len(hits) == 1, f"Expected RULE-TS-SUPPRESSION for: {directive}"
            assert hits[0].penalty == -20
            assert hits[0].severity == "CRITICAL"

        clean_source = (
            'const docs = "Never use @ts-ignore, @ts-expect-error, or @ts-nocheck";\n'
            "const tpl = `forbidden: @ts-nocheck and @ts-ignore`;\n"
        )
        clean_report = _analyze(tmp_path, clean_source, rel_path="src/core/supp_clean.ts")
        assert [f for f in clean_report.findings if f.rule_id == "RULE-TS-SUPPRESSION"] == []

    def test_rule_double_cast_and_no_unsafe_as_double_penalty(self, tmp_path: Path) -> None:
        bad_source = (
            "export interface User { id: string }\n"
            "export function decode(raw: unknown): User {\n"
            "    return raw as unknown as User;\n"
            "}\n"
        )
        report = _analyze(tmp_path, bad_source, rel_path="src/core/double_cast.ts")
        assert _rule_ids(report) == ["RULE-TS-DOUBLE-CAST"]
        assert report.findings[0].penalty == -20
        assert report.findings[0].severity == "CRITICAL"
        assert report.score == 80

        clean_source = (
            '// const bad = raw as unknown as User;\n'
            'const hint = "avoid raw as unknown as User";\n'
            "const tpl = `x as unknown as Foo`;\n"
        )
        clean_report = _analyze(tmp_path, clean_source, rel_path="src/core/double_cast_clean.ts")
        assert clean_report.findings == []

    def test_rule_unsafe_as_satisfies_suggestion_and_exclusions(self, tmp_path: Path) -> None:
        # 1. Plain cast
        plain_cast = "export function castUser(data: unknown) { return data as User; }\n"
        r1 = _analyze(tmp_path, plain_cast, rel_path="src/core/cast1.ts")
        assert _rule_ids(r1) == ["RULE-TS-UNSAFE-AS"]
        assert r1.findings[0].penalty == -10
        assert r1.findings[0].severity == "WARNING"

        # 2. Object literal cast -> must recommend satisfies
        obj_cast = "export const cfg = { retries: 3 } as Config;\n"
        r2 = _analyze(tmp_path, obj_cast, rel_path="src/core/cast2.ts")
        assert _rule_ids(r2) == ["RULE-TS-UNSAFE-AS"]
        assert "satisfies" in r2.findings[0].suggested_fix.lower()

        # 3. Array literal cast -> must recommend satisfies
        arr_cast = "export const nums = [1, 2, 3] as ReadonlyArray<number>;\n"
        r3 = _analyze(tmp_path, arr_cast, rel_path="src/core/cast3.ts")
        assert _rule_ids(r3) == ["RULE-TS-UNSAFE-AS"]
        assert "satisfies" in r3.findings[0].suggested_fix.lower()

        # 4. Exclusions: as const, import/export aliases, comments, strings
        clean_source = (
            'import * as ns from "./ns";\n'
            'import { helper as internalHelper } from "./helper";\n'
            'export { internalHelper as publicHelper };\n'
            'export * as utils from "./utils";\n'
            'export const ROLES = ["admin", "staff"] as const;\n'
            'export const CONFIG = { strict: true } as const;\n'
            "// data as User\n"
            'const note = "never cast data as User";\n'
            "export const used = { ns, publicCount: ROLES.length, CONFIG, note };\n"
        )
        clean_report = _analyze(tmp_path, clean_source, rel_path="src/core/cast_clean.ts")
        assert [f for f in clean_report.findings if f.rule_id == "RULE-TS-UNSAFE-AS"] == []

    def test_rule_non_null_detection_and_strict_exclusions(self, tmp_path: Path) -> None:
        # Positive detections: foo!.bar, arr[0]!, getUser()!
        bad_cases = [
            "export function getName(foo?: { bar: string }) { return foo!.bar; }\n",
            "export function first(arr: string[]) { return arr[0]!; }\n",
            "export function current() { return getUser()!; }\n",
        ]
        for idx, code in enumerate(bad_cases):
            report = _analyze(tmp_path, code, rel_path=f"src/core/nonnull_{idx}.ts")
            hits = [f for f in report.findings if f.rule_id == "RULE-TS-NON-NULL"]
            assert len(hits) == 1, f"Expected RULE-TS-NON-NULL for case {idx}: {code}"
            assert hits[0].penalty == -10
            assert hits[0].severity == "WARNING"

        # Strict false-positive exclusions: logical NOT, !=, !==, comments, strings, JSX text
        clean_ts = (
            "export function validate(check: { valid: boolean }, items: string[], a: number, b: number) {\n"
            "    if (!check.valid) return false;\n"
            "    const isEmpty = !items.length;\n"
            "    const negated = !(a > b);\n"
            "    if (a != b && a !== b) return !isEmpty && negated;\n"
            "    // foo!.bar and arr[0]!\n"
            '    const greeting = "hello! foo!.bar";\n'
            "    const tpl = `done! ${items.length}`;\n"
            "    return Boolean(greeting && tpl);\n"
            "}\n"
        )
        r_ts = _analyze(tmp_path, clean_ts, rel_path="src/core/logical_not.ts")
        assert [f for f in r_ts.findings if f.rule_id == "RULE-TS-NON-NULL"] == []

        clean_tsx = (
            "export function Banner({ ok }: { ok: boolean }) {\n"
            "    if (!ok) return <span>Failed!</span>;\n"
            "    return (\n"
            "        <div>\n"
            "            <h1>Welcome!</h1>\n"
            "            <p>Booking confirmed!</p>\n"
            "        </div>\n"
            "    );\n"
            "}\n"
        )
        r_tsx = _analyze(tmp_path, clean_tsx, rel_path="src/components/Banner.tsx")
        assert [f for f in r_tsx.findings if f.rule_id == "RULE-TS-NON-NULL"] == []

    def test_rule_console_log_detection_and_exclusions(self, tmp_path: Path) -> None:
        bad_ts = 'export function act(x: string) {\n    console.log("debug", x);\n    return x;\n}\n'
        r_bad = _analyze(tmp_path, bad_ts, rel_path="src/core/logger.ts")
        hits = [f for f in r_bad.findings if f.rule_id == "RULE-TS-CONSOLE-LOG"]
        assert len(hits) == 1
        assert hits[0].penalty == -8
        assert hits[0].severity == "WARNING"

        bad_tsx = 'export function View() {\n    console.log("render");\n    return <div />;\n}\n'
        r_tsx = _analyze(tmp_path, bad_tsx, rel_path="src/components/View.tsx")
        assert [f.rule_id for f in r_tsx.findings] == ["RULE-TS-CONSOLE-LOG"]

        # Exclusions: comments, strings, console.error/warn, test files
        clean_prod = (
            '// console.log("commented out");\n'
            '/* console.log("block comment"); */\n'
            'const msg = "do not call console.log(x)";\n'
            'export function report(err: Error) {\n'
            '    console.error("fatal", err);\n'
            '    console.warn("warn", msg);\n'
            "}\n"
        )
        r_clean = _analyze(tmp_path, clean_prod, rel_path="src/core/clean_log.ts")
        assert [f for f in r_clean.findings if f.rule_id == "RULE-TS-CONSOLE-LOG"] == []

        r_test_path = _analyze(tmp_path, bad_ts, rel_path="tests/unit/logger.test.ts")
        assert [f for f in r_test_path.findings if f.rule_id == "RULE-TS-CONSOLE-LOG"] == []

        r_colocated_test = _analyze(tmp_path, bad_ts, rel_path="src/core/logger.test.ts")
        assert [f for f in r_colocated_test.findings if f.rule_id == "RULE-TS-CONSOLE-LOG"] == []

    def test_rule_record_unknown_core_lib_vs_perimeter(self, tmp_path: Path) -> None:
        source_with_record = (
            "export function normalizePayload(raw: Record<string, unknown>): string {\n"
            "    return String(raw.id ?? '');\n"
            "}\n"
        )
        # Flagged in src/core/ and src/lib/ (including nested paths)
        for flagged_path in (
            "src/core/booking/parser.ts",
            "src/lib/customers/mapper.ts",
            "packages/web/src/core/adapter.ts",
        ):
            r_flag = _analyze(tmp_path, source_with_record, rel_path=flagged_path)
            hits = [f for f in r_flag.findings if f.rule_id == "RULE-TS-RECORD-UNKNOWN"]
            assert len(hits) == 1, f"Expected RULE-TS-RECORD-UNKNOWN for {flagged_path}"
            assert hits[0].penalty == -8
            assert hits[0].severity == "WARNING"

        # Permitted at perimeter (src/actions/, src/app/, boundary parsers)
        for allowed_path in (
            "src/actions/booking.ts",
            "src/app/api/webhook/route.ts",
            "src/boundaries/stripe-webhook.ts",
        ):
            r_ok = _analyze(tmp_path, source_with_record, rel_path=allowed_path)
            assert [f for f in r_ok.findings if f.rule_id == "RULE-TS-RECORD-UNKNOWN"] == [], (
                f"Record<string, unknown> should be allowed at perimeter {allowed_path}"
            )

        # Comments / strings in src/core/ must not trigger
        commented = (
            "// Record<string, unknown>\n"
            'const note = "Avoid Record<string, unknown> in core";\n'
        )
        r_comment = _analyze(tmp_path, commented, rel_path="src/core/doc.ts")
        assert [f for f in r_comment.findings if f.rule_id == "RULE-TS-RECORD-UNKNOWN"] == []

    def test_rule_switch_exhaustive_and_never_pass(self, tmp_path: Path) -> None:
        missing_default = (
            'type State = "idle" | "ready";\n'
            "export function label(state: State): string {\n"
            "    switch (state) {\n"
            '        case "idle": return "Idle";\n'
            '        case "ready": return "Ready";\n'
            "    }\n"
            "}\n"
        )
        r1 = _analyze(tmp_path, missing_default, rel_path="src/core/sw1.ts")
        hits1 = [f for f in r1.findings if f.rule_id == "RULE-TS-SWITCH-EXHAUSTIVE"]
        assert len(hits1) == 1
        assert hits1[0].penalty == -8
        assert hits1[0].severity == "WARNING"

        default_without_never = (
            'type State = "idle" | "ready";\n'
            "export function label(state: State): string {\n"
            "    switch (state) {\n"
            '        case "idle": return "Idle";\n'
            '        default: return "Unknown";\n'
            "    }\n"
            "}\n"
        )
        r2 = _analyze(tmp_path, default_without_never, rel_path="src/core/sw2.ts")
        hits2 = [f for f in r2.findings if f.rule_id == "RULE-TS-SWITCH-EXHAUSTIVE"]
        assert len(hits2) == 1

        exhaustive_pass = (
            'type State = { status: "idle" } | { status: "ready" };\n'
            "export function label(state: State): string {\n"
            "    switch (state.status) {\n"
            '        case "idle": return "Idle";\n'
            '        case "ready": return "Ready";\n'
            "        default: {\n"
            "            const _exhaustive: never = state;\n"
            "            throw new Error(`Unhandled: ${String(_exhaustive)}`);\n"
            "        }\n"
            "    }\n"
            "}\n"
        )
        r_pass = _analyze(tmp_path, exhaustive_pass, rel_path="src/core/sw_ok.ts")
        assert [f for f in r_pass.findings if f.rule_id == "RULE-TS-SWITCH-EXHAUSTIVE"] == []
        assert any(b.rule_id == "BONUS-TS-DISCIPLINE" for b in r_pass.bonuses)

        comment_only = (
            "// switch (x) { case 1: break; }\n"
            'const snippet = "switch (x) { case 1: return 1; }";\n'
        )
        r_comment = _analyze(tmp_path, comment_only, rel_path="src/core/sw_comment.ts")
        assert [f for f in r_comment.findings if f.rule_id == "RULE-TS-SWITCH-EXHAUSTIVE"] == []

    def test_rule_optional_bag_and_discriminated_union_exclusion(self, tmp_path: Path) -> None:
        bag_interface = (
            "export interface FetchBag<T> {\n"
            "    loading?: boolean;\n"
            "    error?: string;\n"
            "    data?: T;\n"
            "}\n"
        )
        r1 = _analyze(tmp_path, bag_interface, rel_path="src/core/bag1.ts")
        hits1 = [f for f in r1.findings if f.rule_id == "RULE-TS-OPTIONAL-BAG"]
        assert len(hits1) == 1
        assert hits1[0].penalty == -6
        assert hits1[0].severity == "ADVISORY"

        bag_type = (
            "export type SubmitBag = {\n"
            "    isPending: boolean;\n"
            "    hasError?: boolean;\n"
            "    message?: string;\n"
            "};\n"
        )
        r2 = _analyze(tmp_path, bag_type, rel_path="src/core/bag2.ts")
        assert [f for f in r2.findings if f.rule_id == "RULE-TS-OPTIONAL-BAG"] != []

        for status_bool in (
            "loading",
            "isLoading",
            "error",
            "hasError",
            "success",
            "isSuccess",
            "pending",
            "isPending",
        ):
            src = (
                f"export interface Bag_{status_bool} {{\n"
                f"    {status_bool}: boolean;\n"
                "    data?: string;\n"
                "    reason?: string;\n"
                "}\n"
            )
            rep = _analyze(tmp_path, src, rel_path=f"src/core/bag_{status_bool}.ts")
            assert any(f.rule_id == "RULE-TS-OPTIONAL-BAG" for f in rep.findings), (
                f"Expected RULE-TS-OPTIONAL-BAG for status boolean '{status_bool}'"
            )

        # Valid discriminated unions and non-bag shapes must NOT trigger
        clean_unions = (
            "export type AsyncState<T> =\n"
            '    | { status: "idle" }\n'
            '    | { status: "loading" }\n'
            '    | { status: "error"; message: string }\n'
            '    | { status: "ready"; data: T };\n\n'
            "export type Event =\n"
            '    | { kind: "created"; id: string }\n'
            '    | { kind: "cancelled"; reason?: string };\n\n'
            "export interface SingleOptionalWithFlag {\n"
            "    loading: boolean;\n"
            "    label?: string;\n"
            "    id: string;\n"
            "}\n\n"
            "export interface ErrorStringOnly {\n"
            "    error?: string;\n"
            "    data?: string;\n"
            "    code?: number;\n"
            "}\n\n"
            "export interface PlainOptionalOptions {\n"
            "    title?: string;\n"
            "    subtitle?: string;\n"
            "    limit?: number;\n"
            "}\n"
        )
        r_clean = _analyze(tmp_path, clean_unions, rel_path="src/core/unions.ts")
        assert [f for f in r_clean.findings if f.rule_id == "RULE-TS-OPTIONAL-BAG"] == []

    def test_rule_positional_args_and_object_arg_exclusions(self, tmp_path: Path) -> None:
        # 1. >= 4 positional parameters
        four_params = (
            "export function scheduleBooking(\n"
            "    branchId: string,\n"
            "    start: Date,\n"
            "    durationMs: number,\n"
            "    notes: string,\n"
            "): void {}\n"
        )
        r1 = _analyze(tmp_path, four_params, rel_path="src/core/pos1.ts")
        hits1 = [f for f in r1.findings if f.rule_id == "RULE-TS-POSITIONAL-ARGS"]
        assert len(hits1) == 1
        assert hits1[0].penalty == -5
        assert hits1[0].severity == "ADVISORY"
        assert "object" in hits1[0].suggested_fix.lower()

        # 2. >= 2 plain *Id: string parameters (even with < 4 total params)
        two_ids = (
            "export function transferSlot(branchId: string, customerId: string): void {}\n"
        )
        r2 = _analyze(tmp_path, two_ids, rel_path="src/core/pos2.ts")
        assert [f.rule_id for f in r2.findings] == ["RULE-TS-POSITIONAL-ARGS"]

        # 3. Optional *Id?: string parameters
        two_opt_ids = (
            "export const linkStaff = (branchId: string, staffId?: string): void => {};\n"
        )
        r3 = _analyze(tmp_path, two_opt_ids, rel_path="src/core/pos3.ts")
        assert [f.rule_id for f in r3.findings] == ["RULE-TS-POSITIONAL-ARGS"]

        # 4. Exclusions: destructured object params, single *Id param, `this` parameter
        clean_sigs = (
            "export interface TransferParams {\n"
            "    branchId: string;\n"
            "    customerId: string;\n"
            "    staffId: string;\n"
            "    notes?: string;\n"
            "}\n"
            "export function transferObject({ branchId, customerId, staffId, notes }: TransferParams) {\n"
            "    return { branchId, customerId, staffId, notes };\n"
            "}\n"
            "export function getBranch(branchId: string, includeArchived: boolean, at: Date) {\n"
            "    return { branchId, includeArchived, at };\n"
            "}\n"
            "export function boundMethod(this: unknown, a: string, b: number, c: boolean) {\n"
            "    return { a, b, c };\n"
            "}\n"
        )
        r_clean = _analyze(tmp_path, clean_sigs, rel_path="src/core/pos_clean.ts")
        assert [f for f in r_clean.findings if f.rule_id == "RULE-TS-POSITIONAL-ARGS"] == []

    def test_bonus_ts_discipline_signals_cap_and_once_per_file(self, tmp_path: Path) -> None:
        # 1. Each signal triggers BONUS-TS-DISCIPLINE (+5p)
        signal_cases = [
            "export const cfg = { port: 3000 } satisfies { port: number };\n",
            'export type BranchId = string & { readonly __brand: "BranchId" };\n',
            "export type BookingInput = z.infer<typeof BookingSchema>;\n",
            (
                'type S = "a" | "b";\n'
                "export function f(s: S): number {\n"
                '    switch (s) { case "a": return 1; case "b": return 2; default: { const _e: never = s; throw new Error(_e); } }\n'
                "}\n"
            ),
        ]
        for idx, code in enumerate(signal_cases):
            report = _analyze(tmp_path, code, rel_path=f"src/core/bonus_{idx}.ts")
            assert len(report.bonuses) == 1, f"Expected 1 BONUS-TS-DISCIPLINE for signal {idx}"
            assert report.bonuses[0].rule_id == "BONUS-TS-DISCIPLINE"
            assert report.bonuses[0].penalty == 5
            assert report.bonuses[0].severity == "BONUS"
            assert report.score == 100  # capped at 100

        # 2. +5p actually lifts a penalized score (100 - 10 + 5 = 95)
        lifted_source = (
            'export type StaffId = string & { readonly __brand: "StaffId" };\n'
            "export const unsafe = raw as number;\n"
        )
        r_lifted = _analyze(tmp_path, lifted_source, rel_path="src/core/lifted.ts")
        assert r_lifted.score == 95
        assert len(r_lifted.bonuses) == 1

        # 3. Multiple positive signals in one file -> bonus awarded ONLY ONCE (+5p)
        multi_signal = (
            'export type BranchId = string & { readonly __brand: "BranchId" };\n'
            "export type Input = z.infer<typeof Schema>;\n"
            "export const cfg = { a: 1 } satisfies { a: number };\n"
            "export const unsafe = raw as number;\n"
        )
        r_multi = _analyze(tmp_path, multi_signal, rel_path="src/core/multi_bonus.ts")
        assert len(r_multi.bonuses) == 1
        assert r_multi.score == 95

        # 4. Signals inside comments or strings must NOT award bonus
        fake_signals = (
            "// satisfies Config, readonly __brand, z.infer<typeof S>, : never\n"
            'const doc = "satisfies readonly __brand z.infer<typeof X>";\n'
        )
        r_fake = _analyze(tmp_path, fake_signals, rel_path="src/core/fake_bonus.ts")
        assert r_fake.bonuses == []


# =============================================================================
# 2. Scoring, Bands, SLOC-Weighting & File Exclusions
# =============================================================================


class TestTsDisciplineScoringAndScanning:
    def test_score_clamping_and_band_thresholds(self, tmp_path: Path) -> None:
        # 6 explicit-any violations (-120p) -> clamped to 0, POROUS
        six_anys = "\n".join(f"export const v{i}: any = {i};" for i in range(6)) + "\n"
        r_zero = _analyze(tmp_path, six_anys, rel_path="src/core/zero.ts")
        assert r_zero.score == 0
        assert r_zero.band == "POROUS"
        assert r_zero.badge == "🔴 POROUS"

        # 85 boundary -> STRICT (-20p + 5p bonus = 85)
        boundary_85 = (
            "export const x: any = 1;\n"
            "export const cfg = { a: 1 } satisfies { a: number };\n"
        )
        r_85 = _analyze(tmp_path, boundary_85, rel_path="src/core/b85.ts")
        assert r_85.score == 85
        assert r_85.band == "STRICT"
        assert r_85.badge == "🟢 STRICT"

        # 80 -> LOOSE (-20p, no bonus)
        r_80 = _analyze(tmp_path, "export const x: any = 1;\n", rel_path="src/core/b80.ts")
        assert r_80.score == 80
        assert r_80.band == "LOOSE"
        assert r_80.badge == "🟡 LOOSE"

        # 60 boundary -> LOOSE (-40p, no bonus)
        r_60 = _analyze(
            tmp_path,
            "export const a: any = 1;\nexport const b: any = 2;\n",
            rel_path="src/core/b60.ts",
        )
        assert r_60.score == 60
        assert r_60.band == "LOOSE"

        # 50 -> POROUS (-50p, no bonus)
        r_50 = _analyze(
            tmp_path,
            "export const a: any = 1;\nexport const b: any = 2;\nexport const c = x as Foo;\n",
            rel_path="src/core/b50.ts",
        )
        assert r_50.score == 50
        assert r_50.band == "POROUS"
        assert r_50.badge == "🔴 POROUS"

    def test_sloc_weighted_repo_overall_score_and_sorting(self, tmp_path: Path) -> None:
        mod = _load_ts_discipline()
        core_dir = tmp_path / "src" / "core"
        core_dir.mkdir(parents=True)

        # Large porous file (~80 SLOC, 3 CRITICAL violations -> score 40)
        bad_lines = [
            "export const a: any = 1;",
            "export const b: any = 2;",
            "export const c: any = 3;",
        ] + [f"export const pad_{i} = {i};" for i in range(77)]
        (core_dir / "z_bad.ts").write_text("\n".join(bad_lines) + "\n", encoding="utf-8")

        # Two tiny clean barrel files (2 SLOC each, score 100)
        (core_dir / "a_tiny.ts").write_text("export const x = 1;\nexport const y = 2;\n", encoding="utf-8")
        (core_dir / "b_tiny.ts").write_text("export const z = 3;\nexport const w = 4;\n", encoding="utf-8")

        summary = mod.TsDisciplineAuditor(tmp_path).scan(tmp_path)
        assert summary.files_analyzed == 3
        assert summary.strict_count == 2
        assert summary.loose_count == 0
        assert summary.porous_count == 1
        assert summary.rule_counts["RULE-TS-EXPLICIT-ANY"] == 3

        # Sorted ascending by (score, path)
        assert summary.file_reports[0].path == "src/core/z_bad.ts"
        assert [r.path for r in summary.file_reports[1:]] == [
            "src/core/a_tiny.ts",
            "src/core/b_tiny.ts",
        ]

        expected_weighted = round(
            sum(r.score * r.sloc for r in summary.file_reports) / summary.total_sloc,
            1,
        )
        assert summary.overall_score == expected_weighted
        assert summary.overall_score < 60.0
        assert summary.overall_band == "POROUS"

    def test_empty_repo_summary_defaults(self, tmp_path: Path) -> None:
        mod = _load_ts_discipline()
        summary = mod.TsDisciplineAuditor(tmp_path).scan(tmp_path)
        assert summary.files_analyzed == 0
        assert summary.total_sloc == 0
        assert summary.overall_score == 100.0
        assert summary.overall_band == "STRICT"
        assert summary.file_reports == []

    def test_file_discovery_exclusions_and_include_tests_toggle(self, tmp_path: Path) -> None:
        mod = _load_ts_discipline()
        files = {
            "src/app.ts": "export const a = 1;\n",
            "src/view.tsx": "export function View() { return <div />; }\n",
            "src/types.d.ts": "declare const x: any;\n",
            "node_modules/pkg/index.ts": "export const bad: any = 1;\n",
            ".next/server/app.ts": "export const bad: any = 1;\n",
            "dist/index.ts": "export const bad: any = 1;\n",
            "build/out.ts": "export const bad: any = 1;\n",
            "coverage/cov.ts": "export const bad: any = 1;\n",
            "src/app.test.ts": "export const t1: any = 1;\n",
            "src/view.spec.tsx": "export const t2: any = 1;\n",
            "src/legacy_test.ts": "export const t3: any = 1;\n",
            "tests/unit/a.test.ts": "export const t4: any = 1;\n",
            "src/__tests__/b.ts": "export const t5: any = 1;\n",
        }
        for rel, content in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        prod_auditor = mod.TsDisciplineAuditor(tmp_path, include_tests=False)
        prod_rels = sorted(p.relative_to(tmp_path).as_posix() for p in prod_auditor.get_ts_files(tmp_path))
        assert prod_rels == ["src/app.ts", "src/view.tsx"]

        all_auditor = mod.TsDisciplineAuditor(tmp_path, include_tests=True)
        all_rels = sorted(p.relative_to(tmp_path).as_posix() for p in all_auditor.get_ts_files(tmp_path))
        assert "src/types.d.ts" not in all_rels
        assert "node_modules/pkg/index.ts" not in all_rels
        assert "dist/index.ts" not in all_rels
        assert "src/app.test.ts" in all_rels
        assert "tests/unit/a.test.ts" in all_rels

    def test_scoped_files_parameter(self, tmp_path: Path) -> None:
        mod = _load_ts_discipline()
        (tmp_path / "src").mkdir(parents=True)
        (tmp_path / "src" / "a.ts").write_text("export const a: any = 1;\n", encoding="utf-8")
        (tmp_path / "src" / "b.ts").write_text("export const b: any = 2;\n", encoding="utf-8")

        summary = mod.TsDisciplineAuditor(tmp_path).scan(tmp_path, scoped_files=["src/a.ts"])
        assert summary.files_analyzed == 1
        assert [r.path for r in summary.file_reports] == ["src/a.ts"]


# =============================================================================
# 3. Formatters (`human`, `markdown`, `json`, `toon`)
# =============================================================================


class TestTsDisciplineFormatters:
    def _build_sample_summary(self, tmp_path: Path):
        mod = _load_ts_discipline()
        src = tmp_path / "src" / "core"
        src.mkdir(parents=True)
        (src / "hotspot.ts").write_text(
            'export function f(x: any) {\n    console.log(x);\n    return x;\n}\n',
            encoding="utf-8",
        )
        (src / "clean.ts").write_text(
            "export const cfg = { ok: true } satisfies { ok: boolean };\n",
            encoding="utf-8",
        )
        (src / "mid.ts").write_text("export const u = raw as User;\n", encoding="utf-8")
        return mod, mod.TsDisciplineAuditor(tmp_path).scan(tmp_path)

    def test_format_json_structure_and_top_limit(self, tmp_path: Path) -> None:
        mod, summary = self._build_sample_summary(tmp_path)
        parsed = json.loads(mod.format_json(summary, top=2))
        assert "ts_discipline_summary" in parsed
        payload = parsed["ts_discipline_summary"]
        for key in (
            "target_path",
            "overall_score",
            "overall_band",
            "files_analyzed",
            "total_sloc",
            "strict_count",
            "loose_count",
            "porous_count",
            "rule_counts",
            "results",
        ):
            assert key in payload, f"Missing JSON summary key: {key}"
        assert payload["files_analyzed"] == 3
        assert len(payload["results"]) == 2
        assert payload["results"][0]["path"] == "src/core/hotspot.ts"

    def test_format_toon_structure_and_pipe_delimited_rules(self, tmp_path: Path) -> None:
        mod, summary = self._build_sample_summary(tmp_path)
        toon_out = mod.format_toon(summary, top=5)
        assert "ts_discipline_result:" in toon_out
        assert "src/core/hotspot.ts" in toon_out
        assert "|" in toon_out
        assert "RULE-TS-EXPLICIT-ANY" in toon_out
        assert "RULE-TS-CONSOLE-LOG" in toon_out

    def test_format_human_and_markdown_outputs(self, tmp_path: Path) -> None:
        mod, summary = self._build_sample_summary(tmp_path)

        human_out = mod.format_human(summary, top=5)
        assert str(summary.overall_score) in human_out
        assert summary.overall_band in human_out
        assert "src/core/hotspot.ts" in human_out
        assert "RULE-TS-EXPLICIT-ANY" in human_out

        md_out = mod.format_markdown(summary, top=5)
        assert md_out.lstrip().startswith("#")
        assert str(summary.overall_score) in md_out
        assert summary.overall_band in md_out
        assert "src/core/hotspot.ts" in md_out


# =============================================================================
# 4. CLI Integration (`tools/audit/cli.py`)
# =============================================================================


class TestTsDisciplineCliIntegration:
    def _create_mini_repo(self, root: Path) -> None:
        (root / "src" / "core").mkdir(parents=True)
        (root / "src" / "components").mkdir(parents=True)
        (root / "tests").mkdir(parents=True)
        (root / "src" / "core" / "service.ts").write_text(
            "export function run(input: any) { return input; }\n",
            encoding="utf-8",
        )
        (root / "src" / "components" / "Button.tsx").write_text(
            "export function Button() { return <button>Click</button>; }\n",
            encoding="utf-8",
        )
        (root / "tests" / "service.test.ts").write_text(
            "import { run } from '../src/core/service';\n"
            "test('run', () => expect(run(1)).toBe(1));\n",
            encoding="utf-8",
        )

    def test_cli_run_types_track_all_four_formats(self, tmp_path: Path) -> None:
        self._create_mini_repo(tmp_path)
        import tools.audit.cli as cli_mod

        assert hasattr(cli_mod, "run_types_track"), "tools.audit.cli must define run_types_track"

        parsed_json = json.loads(cli_mod.run_types_track(tmp_path, "json", top=5))
        assert "ts_discipline_summary" in parsed_json

        toon_out = cli_mod.run_types_track(tmp_path, "toon", top=5)
        assert "ts_discipline_result:" in toon_out

        md_out = cli_mod.run_types_track(tmp_path, "markdown", top=5)
        assert "src/core/service.ts" in md_out

        human_out = cli_mod.run_types_track(tmp_path, "human", top=5)
        assert "src/core/service.ts" in human_out

    def test_cli_run_all_tracks_includes_types_across_all_formats(self, tmp_path: Path) -> None:
        self._create_mini_repo(tmp_path)
        from tools.audit.cli import run_all_tracks

        # JSON: unified_audit keeps target_path, core, ui, tests and adds types
        parsed_all = json.loads(run_all_tracks(tmp_path, "json", top=5))
        unified = parsed_all["unified_audit"]
        for key in ("target_path", "core", "ui", "tests", "types"):
            assert key in unified, f"Missing unified_audit key: {key}"
        assert "ts_discipline_summary" in unified["types"]

        # TOON: edge_unified_audit includes types section
        toon_all = run_all_tracks(tmp_path, "toon", top=5)
        assert "edge_unified_audit:" in toon_all
        assert "types:" in toon_all

        # Markdown: summary header includes Types Health and type discipline report
        md_all = run_all_tracks(tmp_path, "markdown", top=5)
        assert "Types Health:" in md_all

        # Human: includes [TRACK 4/4] TYPESCRIPT TYPE-SYSTEM DISCIPLINE
        human_all = run_all_tracks(tmp_path, "human", top=5)
        assert "[TRACK 4/4] TYPESCRIPT TYPE-SYSTEM DISCIPLINE" in human_all

    def test_cli_main_accepts_track_types(self, tmp_path: Path, monkeypatch, capsys) -> None:
        self._create_mini_repo(tmp_path)
        import tools.audit.cli as cli_mod

        monkeypatch.setattr(
            sys,
            "argv",
            ["edge-audit", str(tmp_path), "--track", "types", "--format", "json"],
        )
        cli_mod.main()
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "ts_discipline_summary" in parsed


# =============================================================================
# 5. Radar Integration (`tools/radar/scanner.py`)
# =============================================================================


class TestTsDisciplineRadarIntegration:
    def test_radar_scan_core_emits_penalty_ledger_items_and_omits_bonuses(self, tmp_path: Path) -> None:
        from tools.radar.scanner import RadarScanner

        core_dir = tmp_path / "src" / "core"
        core_dir.mkdir(parents=True)
        (core_dir / "mixed.ts").write_text(
            'export type Id = string & { readonly __brand: "Id" };\n'
            "export function run(x: any, user?: { name: string }) {\n"
            "    return user!.name;\n"
            "}\n",
            encoding="utf-8",
        )

        items = RadarScanner(tmp_path).scan_core()
        ts_items = [i for i in items if i.rule_id.startswith("RULE-TS-")]
        rule_set = {i.rule_id for i in ts_items}

        assert "RULE-TS-EXPLICIT-ANY" in rule_set
        assert "RULE-TS-NON-NULL" in rule_set
        assert all(not i.rule_id.startswith("BONUS-") for i in items)
        assert all(i.severity != "BONUS" for i in items)

        any_item = next(i for i in ts_items if i.rule_id == "RULE-TS-EXPLICIT-ANY")
        assert any_item.track == "core"
        assert any_item.status == "OPEN"
        assert any_item.severity == "CRITICAL"
        assert any_item.details["penalty"] == -20
        assert "snippet" in any_item.details
        assert "file_score" in any_item.details
        assert len(any_item.fingerprint) == 12

    def test_radar_scan_core_scoping_ignores_dts_and_triggers_macro_patterns(self, tmp_path: Path) -> None:
        from tools.radar.ledger import LedgerEngine
        from tools.radar.scanner import RadarScanner

        for rel in (
            "src/core/a.ts",
            "src/core/b.ts",
            "src/lib/c.ts",
        ):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                "export function getId(u?: { id: string }): string {\n    return u!.id;\n}\n",
                encoding="utf-8",
            )

        (tmp_path / "src" / "core" / "d.ts").write_text(
            "export function cast(x: unknown) { return x as any; }\n",
            encoding="utf-8",
        )
        (tmp_path / "src" / "core" / "ambient.d.ts").write_text(
            "declare const legacy: any;\n",
            encoding="utf-8",
        )

        scanner = RadarScanner(tmp_path)

        # 1. file_paths scoping limits emitted RULE-TS-* findings to the scoped file
        scoped_items = scanner.scan_core(file_paths=["src/core/a.ts"])
        scoped_ts = [i for i in scoped_items if i.rule_id.startswith("RULE-TS-")]
        assert len(scoped_ts) >= 1
        assert {i.file_path for i in scoped_ts} == {"src/core/a.ts"}

        # 2. Unscoped scan ignores .d.ts and feeds 3+ distinct files into macro pattern detection
        all_items = scanner.scan_core()
        assert all(not i.file_path.endswith(".d.ts") for i in all_items)

        summary = LedgerEngine(tmp_path).sync_channel("core", all_items)
        assert any("RULE-TS-NON-NULL" in mp for mp in summary.macro_patterns), (
            f"Expected RULE-TS-NON-NULL macro pattern across 3 files, got: {summary.macro_patterns}"
        )


# =============================================================================
# 6. Rules SSOT & Gate Diff-Added-Lines Hardening (`tools/rules.py`, `tools/gate.py`)
# =============================================================================


class TestRulesAndGateDiffHardening:
    def test_rules_exports_new_ts_discipline_patterns(self) -> None:
        import tools.rules as rules_mod

        for attr in ("TYPE_ESCAPE_PATTERN", "TS_EXPLICIT_ANY_PATTERN", "TS_CONSOLE_LOG_PATTERN"):
            assert hasattr(rules_mod, attr), f"tools.rules must export {attr}"

        assert rules_mod.TYPE_ESCAPE_PATTERN.search("// @ts-nocheck") is not None
        assert rules_mod.TYPE_ESCAPE_PATTERN.search("// @ts-ignore") is not None
        assert rules_mod.TYPE_ESCAPE_PATTERN.search("// @ts-expect-error") is not None
        assert rules_mod.TYPE_ESCAPE_PATTERN.search("x as any") is not None
        assert rules_mod.TYPE_ESCAPE_PATTERN.search("x as unknown as Foo") is not None

    def test_find_type_escape_violations_backward_compatible_with_ts_nocheck(self) -> None:
        from tools.gate import _find_type_escape_violations

        src = (
            "// normal comment mentioning as any\n"
            "// @ts-nocheck\n"
            "// @ts-ignore\n"
            "// @ts-expect-error\n"
            "const a = raw as any;\n"
            "const b = raw as unknown as string;\n"
        )
        hits = _find_type_escape_violations("src/core/sample.ts", src)
        assert len(hits) == 5
        assert any("src/core/sample.ts:2" in h for h in hits)

    def test_gate_check_type_escapes_catches_newly_added_escapes_in_git_repo(self, tmp_path: Path) -> None:
        from tools.gate import EdgeVerificationGate

        cases = [
            ("src/core/service.ts", "export function bad(x: any) { return x; }\n"),
            ("src/lib/helper.ts", "// @ts-nocheck\nexport const h = 1;\n"),
            ("src/core/mapper.ts", "export function name(u?: { n: string }) { return u!.n; }\n"),
            ("src/actions/booking.ts", 'export function logAct() { console.log("dbg"); }\n'),
            ("src/components/Panel.tsx", "export function Panel({ u }: { u?: { id: string } }) { return <div>{u!.id}</div>; }\n"),
        ]
        for idx, (rel_path, bad_content) in enumerate(cases):
            repo = tmp_path / f"repo_{idx}"
            repo.mkdir()
            _init_git_repo(repo)
            _write_and_commit(repo, {"README.md": "# Init\n"}, "chore: init")
            _write_and_commit(repo, {rel_path: bad_content}, f"feat: introduce {rel_path}")

            res = EdgeVerificationGate(repo).check_type_escapes("HEAD~1")
            assert not res.passed, f"Expected check_type_escapes to fail on added {rel_path}"
            assert rel_path in "\n".join(res.details)

    def test_gate_check_type_escapes_ignores_untouched_legacy_lines_and_safe_constructs(
        self, tmp_path: Path
    ) -> None:
        from tools.gate import EdgeVerificationGate

        _init_git_repo(tmp_path)
        legacy_file = (
            "export function legacy(x: any, u?: { id: string }) {\n"
            '    console.log("legacy");\n'
            "    return u!.id;\n"
            "}\n"
            "export const KEEP_LINE_5 = true;\n"
            "export const KEEP_LINE_6 = true;\n"
        )
        _write_and_commit(tmp_path, {"src/core/legacy.ts": legacy_file}, "chore: legacy baseline")

        # Edit ONLY bottom of legacy.ts with clean code, plus safe constructs & non-src/test files
        updated_legacy = legacy_file + "export const SAFE_ADDITION = 42;\n"
        safe_action = (
            'export const ROLES = ["admin", "staff"] as const;\n'
            "export function validate(check: { valid: boolean }): boolean {\n"
            "    if (!check.valid) {\n"
            '        console.error("invalid");\n'
            "        return false;\n"
            "    }\n"
            "    return true;\n"
            "}\n"
        )
        safe_tsx = (
            "export function Banner({ ok }: { ok: boolean }) {\n"
            "    if (!ok) return <span>Error!</span>;\n"
            "    return <p>Saved!</p>;\n"
            "}\n"
        )
        _write_and_commit(
            tmp_path,
            {
                "src/core/legacy.ts": updated_legacy,
                "src/actions/safe.ts": safe_action,
                "src/components/Banner.tsx": safe_tsx,
                "scripts/seed.ts": 'console.log("CLI seed output allowed outside src/");\n',
                "tests/unit/safe.test.ts": 'const x: any = 1;\nconsole.log(x!.y);\n',
                "src/types/global.d.ts": "declare const globalThing: any;\n",
            },
            "feat: clean additions leaving legacy lines untouched",
        )

        res = EdgeVerificationGate(tmp_path).check_type_escapes("HEAD~1")
        assert res.passed, f"Expected pass on untouched legacy + safe constructs, got: {res}"

    def test_gate_check_type_escapes_catches_untracked_new_file_and_deduplicates(self, tmp_path: Path) -> None:
        from tools.gate import EdgeVerificationGate

        _init_git_repo(tmp_path)
        _write_and_commit(tmp_path, {"README.md": "# Init\n"}, "chore: init")

        untracked = tmp_path / "src" / "core" / "untracked.ts"
        untracked.parent.mkdir(parents=True, exist_ok=True)
        untracked.write_text("export const x = (raw as any);\n", encoding="utf-8")

        res = EdgeVerificationGate(tmp_path).check_type_escapes("HEAD")
        assert not res.passed
        assert len(res.details) == 1, f"Expected deduplicated single violation, got: {res.details}"
        assert "src/core/untracked.ts:1" in res.details[0]


# =============================================================================
# 7. Regex Fallback & Tree-Sitter Parity
# =============================================================================


class TestTreeSitterAndRegexFallbackParity:
    _CORPUS = {
        "src/core/mixed_violations.ts": (
            "// @ts-nocheck\n"
            "export interface FetchBag { loading?: boolean; error?: string; data?: string }\n"
            "export function parse(x: any, a: string, b: string, c: number, d: boolean) {\n"
            '    console.log("dbg");\n'
            "    const u = x as unknown as { id: string };\n"
            "    const cfg = { port: 80 } as { port: number };\n"
            "    const bag: Record<string, unknown> = {};\n"
            "    switch (cfg.port) {\n"
            "        case 80: return u!.id;\n"
            "    }\n"
            "    return bag;\n"
            "}\n"
        ),
        "src/core/clean_with_bonus.ts": (
            'export type BranchId = string & { readonly __brand: "BranchId" };\n'
            "export interface Company { many: number; anyId: BranchId }\n"
            'type State = { status: "idle" } | { status: "ready"; company: Company };\n'
            "export function describe(state: State, check: { valid: boolean }): string {\n"
            '    if (!check.valid) return "invalid";\n'
            "    switch (state.status) {\n"
            '        case "idle": return "idle";\n'
            '        case "ready": return state.company.anyId;\n'
            "        default: {\n"
            "            const _exhaustive: never = state;\n"
            "            throw new Error(String(_exhaustive));\n"
            "        }\n"
            "    }\n"
            "}\n"
        ),
    }

    def test_regex_fallback_parity_across_all_rules(self, tmp_path: Path, monkeypatch) -> None:
        mod = _load_ts_discipline()
        monkeypatch.setattr(mod, "TREE_SITTER_AVAILABLE", False)
        assert mod._get_parser_for_ext(".ts") is None
        assert mod._get_parser_for_ext(".tsx") is None

        auditor = mod.TsDisciplineAuditor(tmp_path)

        bad = auditor.analyze_source(
            self._CORPUS["src/core/mixed_violations.ts"],
            rel_path="src/core/mixed_violations.ts",
        )
        bad_rules = set(_rule_ids(bad))
        expected_rules = {
            "RULE-TS-SUPPRESSION",
            "RULE-TS-OPTIONAL-BAG",
            "RULE-TS-EXPLICIT-ANY",
            "RULE-TS-POSITIONAL-ARGS",
            "RULE-TS-CONSOLE-LOG",
            "RULE-TS-DOUBLE-CAST",
            "RULE-TS-UNSAFE-AS",
            "RULE-TS-RECORD-UNKNOWN",
            "RULE-TS-SWITCH-EXHAUSTIVE",
            "RULE-TS-NON-NULL",
        }
        assert expected_rules.issubset(bad_rules), f"Missing rules in fallback: {expected_rules - bad_rules}"

        clean = auditor.analyze_source(
            self._CORPUS["src/core/clean_with_bonus.ts"],
            rel_path="src/core/clean_with_bonus.ts",
        )
        assert clean.findings == []
        assert clean.score == 100
        assert len(clean.bonuses) == 1

    @pytest.mark.skipif(not _is_tree_sitter_available(), reason="tree-sitter not installed")
    def test_tree_sitter_ast_and_regex_fallback_agree(self, tmp_path: Path, monkeypatch) -> None:
        mod = _load_ts_discipline()
        assert mod.TREE_SITTER_AVAILABLE is True
        assert mod._get_parser_for_ext(".ts") is not None
        assert mod._get_parser_for_ext(".tsx") is not None

        ast_auditor = mod.TsDisciplineAuditor(tmp_path)
        ast_reports = {
            rel: ast_auditor.analyze_source(src, rel_path=rel)
            for rel, src in self._CORPUS.items()
        }

        monkeypatch.setattr(mod, "TREE_SITTER_AVAILABLE", False)
        fb_auditor = mod.TsDisciplineAuditor(tmp_path)
        fb_reports = {
            rel: fb_auditor.analyze_source(src, rel_path=rel)
            for rel, src in self._CORPUS.items()
        }

        for rel in self._CORPUS:
            assert set(_rule_ids(ast_reports[rel])) == set(_rule_ids(fb_reports[rel]))
            assert ast_reports[rel].score == fb_reports[rel].score
            assert len(ast_reports[rel].bonuses) == len(fb_reports[rel].bonuses)
