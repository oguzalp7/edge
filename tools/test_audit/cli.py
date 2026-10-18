#!/usr/bin/env python3
"""
edge-tests-audit-typescript: Deterministic Test Purity & External I/O Leakage Auditor
Analyzes TypeScript/JavaScript unit tests for live DB connections, DDL/DML leakage,
uncontained seeds, missing teardowns, and hardcoded data collisions.
"""

import sys
import os
import re
import argparse
import json
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path
from tools.common.toon import encode

setup_utf8_console()


class TestFileAuditor:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()

    def get_test_files(self, target_dir: Path) -> list[Path]:
        results = []
        if not target_dir.exists():
            return results
        if target_dir.is_file():
            if target_dir.suffix in [".ts", ".tsx", ".js", ".jsx"]:
                return [target_dir]
            return []

        for root, _, files in os.walk(target_dir):
            for file in files:
                if (file.endswith(".test.ts") or file.endswith(".test.tsx") or
                    file.endswith(".spec.ts") or file.endswith(".spec.tsx")):
                    results.append(Path(root) / file)
        return sorted(results)

    def analyze_file(self, file_path: Path) -> dict:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return {
                "path": str(file_path),
                "score": 0,
                "badge": "🔴 ERROR",
                "category": "ERROR",
                "violations": [{"rule": "READ_ERROR", "penalty": -100, "desc": f"File could not be read: {e}"}],
                "bonuses": []
            }

        try:
            rel_path = file_path.resolve().relative_to(self.root_dir).as_posix()
        except ValueError:
            rel_path = file_path.as_posix()

        score = 100
        violations = []
        bonuses = []

        # 1. Direct DB Client Imports (-35p)
        db_import_patterns = [
            r'import\s+.*\{[^}]*\bdb\b[^}]*\}\s+from\s+["\']@/db["\']',
            r'import\s+.*\bdb\b.*\s+from\s+["\']@/db["\']',
            r'import\s+.*from\s+["\']@/db/index["\']',
            r'import\s+.*from\s+["\']@/db["\']',
        ]
        has_db_import = any(re.search(pat, content) for pat in db_import_patterns)
        if has_db_import:
            score -= 35
            violations.append({
                "rule": "DB_CLIENT_IMPORT",
                "penalty": -35,
                "desc": "Direct database client (@/db) imported"
            })

        # 2. Direct DB Manipulation / DML (-25p)
        dml_matches = re.findall(r'\bdb\.(insert|update|delete|transaction|execute)\s*\(', content)
        if dml_matches:
            score -= 25
            unique_ops = sorted(list(set(dml_matches)))
            violations.append({
                "rule": "DB_DML_EXECUTION",
                "penalty": -25,
                "desc": f"Physical database manipulation ({len(dml_matches)} calls: {', '.join(f'db.{op}()' for op in unique_ops)})"
            })

        # 3. Schema / DDL / Seeding (-20p)
        seed_matches = re.findall(r'\b(seed[A-Z]\w*|ensure[A-Z]\w*Tables)\s*\(', content)
        if seed_matches:
            score -= 20
            unique_seeds = sorted(list(set(seed_matches)))
            violations.append({
                "rule": "DDL_OR_SEED_EXECUTION",
                "penalty": -20,
                "desc": f"DDL or Seed execution ({', '.join(f'{s}()' for s in unique_seeds)})"
            })

        # 4. Teardown & Cleanup Health (-25p or -10p)
        has_db_activity = has_db_import or bool(dml_matches)
        has_teardown = bool(re.search(r'\b(afterAll|afterEach)\s*\(', content))
        has_cleanup_func = bool(re.search(r'\bcleanup\w*\s*\(', content, re.IGNORECASE) or re.search(r'\bdelete\w*\s*\(', content))

        if has_db_activity:
            if not has_teardown and not has_cleanup_func:
                score -= 25
                violations.append({
                    "rule": "NO_TEARDOWN",
                    "penalty": -25,
                    "desc": "Database manipulation present without afterAll/cleanup (DB poisoning risk)"
                })
            elif has_teardown and not has_cleanup_func:
                score -= 10
                violations.append({
                    "rule": "WEAK_TEARDOWN",
                    "penalty": -10,
                    "desc": "afterAll present but lacks concrete cleanup/deletion"
                })

        # 5. Direct Server Action Import (-15p)
        action_matches = re.findall(r'from\s+["\']@/actions/[^"\']+["\']', content)
        if action_matches:
            score -= 15
            violations.append({
                "rule": "SERVER_ACTION_IMPORT",
                "penalty": -15,
                "desc": f"Direct dependency on Server Action layer ({len(action_matches)} imports)"
            })

        # 6. Hardcoded Data Collisions (-5p)
        has_static_collision = bool(re.search(r'["\'](?:\+?[1-9]\d{9,14}|5[0-9]{9}|test@example\.com)["\']', content))
        if has_static_collision and has_db_activity:
            score -= 5
            violations.append({
                "rule": "HARDCODED_DATA_COLLISION",
                "penalty": -5,
                "desc": "Static phone/credential used in DB write (Unique constraint collision risk)"
            })

        # 7. Bonuses (+10p / +15p)
        has_mocking = bool(re.search(r'\bvi\.(fn|mock|spyOn)\s*\(', content))
        if has_mocking:
            score += 10
            bonuses.append({
                "bonus": 10,
                "desc": "Isolated in-memory mock used (vi.mock / vi.fn)"
            })

        has_pure_core = bool(re.search(
            r'from\s+["\']@/(?:core|domain|lib/[^"\']+/(?:domain|core|engine|rules|calculator)|lib/pricing/rate-resolver|lib/pricing/campaign-rules|lib/customers/qualification)(?:/[^"\']*)?["\']',
            content
        ))
        if has_pure_core and not has_db_import:
            score += 15
            bonuses.append({
                "bonus": 15,
                "desc": "Pure Domain / Core engine test (Hermetic)"
            })

        score = max(0, min(100, score))

        if score < 50:
            category = "RED_TOXIC"
            badge = "🔴 TOXIC (LEAKY)"
        elif score < 85:
            category = "YELLOW_MASKED"
            badge = "🟡 MASKED INTEGRATION"
        else:
            category = "GREEN_PURE"
            badge = "🟢 PURE UNIT"

        return {
            "path": rel_path,
            "score": score,
            "badge": badge,
            "category": category,
            "violations": violations,
            "bonuses": bonuses
        }


def format_human(results: list[dict], top: int = 15) -> str:
    lines = []
    lines.append("=" * 95)
    lines.append("📊 TYPESCRIPT UNIT TEST HEALTH RADAR (edge-tests-audit-typescript)")
    lines.append("=" * 95)

    toxic = [r for r in results if r["score"] < 50]
    masked = [r for r in results if 50 <= r["score"] < 85]
    pure = [r for r in results if r["score"] >= 85]

    if toxic:
        lines.append(f"\n🚨 TOP {min(top, len(toxic))} TOXIC UNIT TESTS (URGENT ISOLATION REQUIRED):")
        lines.append("-" * 95)
        for idx, r in enumerate(toxic[:top]):
            lines.append(f"[#{idx + 1:02d}] {r['badge']} [Score: {r['score']:02d}/100] -> {r['path']}")
            for v in r["violations"]:
                lines.append(f"       ❌ {v['penalty']}p : {v['desc']}")
            for b in r["bonuses"]:
                lines.append(f"       ✅ +{b['bonus']}p : {b['desc']}")
    else:
        lines.append("\n✨ Excellent! No toxic / database-leaking unit tests were found.")

    lines.append("\n" + "=" * 95)
    lines.append("📈 DISTRIBUTION & SUMMARY STATISTICS:")
    total = len(results)
    avg_score = round(sum(r["score"] for r in results) / total) if total else 0
    pure_pct = round((len(pure) / total) * 100) if total else 0
    masked_pct = round((len(masked) / total) * 100) if total else 0
    toxic_pct = round((len(toxic) / total) * 100) if total else 0

    lines.append(f"   Total Test Files    : {total}")
    lines.append(f"   Average Health      : {avg_score} / 100")
    lines.append(f"   🟢 Pure Unit        : {len(pure)} ({pure_pct}%)")
    lines.append(f"   🟡 Masked Integrat. : {len(masked)} ({masked_pct}%)")
    lines.append(f"   🔴 Toxic / Leaky DB : {len(toxic)} ({toxic_pct}%)")
    lines.append("=" * 95)
    return "\n".join(lines)


def format_markdown(results: list[dict], top: int = 15) -> str:
    lines = []
    lines.append("# 📊 TypeScript Unit Test Health Radar (`edge-tests-audit-typescript`)")
    lines.append("")
    total = len(results)
    toxic = [r for r in results if r["score"] < 50]
    masked = [r for r in results if 50 <= r["score"] < 85]
    pure = [r for r in results if r["score"] >= 85]
    avg_score = round(sum(r["score"] for r in results) / total) if total else 0

    lines.append(f"> **Total Test Files:** `{total}` | **Average Health:** `{avg_score} / 100`")
    lines.append("")
    lines.append("## 📈 Summary Distribution")
    lines.append("")
    lines.append("| Category | Count | Percentage |")
    lines.append("| :--- | :--- | :--- |")
    pure_pct = round((len(pure) / total) * 100) if total else 0
    masked_pct = round((len(masked) / total) * 100) if total else 0
    toxic_pct = round((len(toxic) / total) * 100) if total else 0
    lines.append(f"| 🟢 Pure Unit | `{len(pure)}` | `{pure_pct}%` |")
    lines.append(f"| 🟡 Masked Integration | `{len(masked)}` | `{masked_pct}%` |")
    lines.append(f"| 🔴 Toxic / Leaky DB | `{len(toxic)}` | `{toxic_pct}%` |")
    lines.append("")

    if toxic:
        lines.append(f"## 🚨 Top {min(top, len(toxic))} Toxic Unit Tests (Urgent Isolation Required)")
        lines.append("")
        lines.append("| Score | Badge | Path | Violations |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for r in toxic[:top]:
            viols = ", ".join(f"{v['rule']} ({v['penalty']}p)" for v in r["violations"])
            lines.append(f"| `{r['score']}/100` | {r['badge']} | `{r['path']}` | {viols} |")
        lines.append("")
    else:
        lines.append("✅ *Excellent! No toxic / database-leaking unit tests were found.*")
        lines.append("")
    return "\n".join(lines)


def format_toon(results: list[dict], top: int = 15) -> str:
    total = len(results)
    toxic = [r for r in results if r["score"] < 50]
    masked = [r for r in results if 50 <= r["score"] < 85]
    pure = [r for r in results if r["score"] >= 85]
    avg_score = round(sum(r["score"] for r in results) / total) if total else 0

    data = {
        "test_purity_result": {
            "total_files": total,
            "average_score": avg_score,
            "pure_count": len(pure),
            "masked_count": len(masked),
            "toxic_count": len(toxic),
            "toxic_hotspots": [
                {
                    "path": r["path"],
                    "score": r["score"],
                    "violations": "|".join(v["rule"] for v in r["violations"]),
                }
                for r in toxic[:top]
            ],
        }
    }
    return encode(data)


def format_json(results: list[dict], top: int = 15) -> str:
    total = len(results)
    toxic = [r for r in results if r["score"] < 50]
    masked = [r for r in results if 50 <= r["score"] < 85]
    pure = [r for r in results if r["score"] >= 85]
    avg_score = round(sum(r["score"] for r in results) / total) if total else 0

    data = {
        "test_audit_summary": {
            "total_files": total,
            "average_score": avg_score,
            "pure_count": len(pure),
            "masked_count": len(masked),
            "toxic_count": len(toxic),
            "results": [
                {
                    "path": r["path"],
                    "score": r["score"],
                    "category": r["category"],
                    "violations": r["violations"],
                    "bonuses": r["bonuses"],
                }
                for r in results[:top]
            ]
        }
    }
    return json.dumps(data, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="edge-tests-audit-typescript: Deterministic Unit Test Purity & Isolation Auditor"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="tests/unit",
        help="Target directory or file to audit (default: tests/unit)"
    )
    parser.add_argument(
        "--format",
        choices=["human", "table", "markdown", "toon", "json"],
        default="human",
        help="Output format: 'human'/'table' (console), 'markdown', 'toon', or 'json'"
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Maximum number of toxic tests to display (default: 15)"
    )
    parser.add_argument(
        "-o", "--output", "--out",
        dest="output",
        type=str,
        default=None,
        help="Optional file path to write report to"
    )
    parser.add_argument(
        "--fail-under",
        type=int,
        default=None,
        help="Exit with non-zero code if average score is below threshold"
    )
    parser.add_argument(
        "--strict-pure",
        action="store_true",
        help="Exit with code 1 if any toxic (< 50) test exists"
    )

    args = parser.parse_args()

    project_root = Path.cwd()
    target_path = normalize_target_path(args.target)
    if not target_path.is_absolute():
        target_path = (project_root / target_path).resolve()

    auditor = TestFileAuditor(project_root)
    files = auditor.get_test_files(target_path)

    if not files:
        print(f"Warning: No test files found in target path: {target_path}", file=sys.stderr)
        sys.exit(0)

    results = [auditor.analyze_file(f) for f in files]
    results.sort(key=lambda x: x["score"])

    if args.format == "toon":
        output = format_toon(results, top=args.top)
    elif args.format == "markdown":
        output = format_markdown(results, top=args.top)
    elif args.format == "json":
        output = format_json(results, top=args.top)
    else:
        output = format_human(results, top=args.top)

    print(output)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"\nReport saved to: {out_path}")

    # Gate verification exit codes
    avg_score = sum(r["score"] for r in results) / len(results) if results else 0
    if args.fail_under is not None and avg_score < args.fail_under:
        sys.exit(1)
    if args.strict_pure and any(r["score"] < 50 for r in results):
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
