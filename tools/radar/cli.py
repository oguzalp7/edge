#!/usr/bin/env python3
"""
Edge Radar CLI Driver: Scoped Pattern Observation & Idempotent Debt Ledger
"""

import sys
import os
import argparse
import io
from pathlib import Path
from typing import List, Optional

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path, toon_encode
setup_utf8_console()


from tools.radar.models import Track, FindingSeverity, FindingStatus
from tools.radar.churn import ChurnAnalyzer
from tools.radar.ledger import LedgerEngine
from tools.radar.scanner import RadarScanner


def cmd_scan(args):
    target_repo = normalize_target_path(args.target)
    if not target_repo.exists():
        print(f"Error: Repository path does not exist: {target_repo}", file=sys.stderr)
        sys.exit(1)

    churn_analyzer = ChurnAnalyzer(target_repo)
    ledger = LedgerEngine(target_repo)
    scanner = RadarScanner(target_repo)

    # Determine scope
    scoped_files: Optional[List[str]] = None
    if args.mode == "churn":
        hotspots = churn_analyzer.get_churn_hotspots(since=args.since, max_files=args.max_churn)
        scoped_files = [h[0] for h in hotspots]
        if not scoped_files:
            print(f"🎯 Churn Scope: No active commit hotspots found in the past {args.since}. Codebase is quiescent.")
            return
        print(f"🎯 Churn Scope: Scanning {len(scoped_files)} active hot files from the past {args.since}...")
    elif args.mode == "pr":
        scoped_files = churn_analyzer.get_pr_changed_files(base_ref=args.base)
        if not scoped_files:
            print(f"🎯 PR Scope: No modified files found against base '{args.base}'.")
            return
        print(f"🎯 PR Scope: Scanning {len(scoped_files)} files changed against '{args.base}'...")
    else:
        print("🌐 Full Scope: Scanning all production source files in repo...")

    summaries = {}

    # Scan Core Track
    if args.track in ["all", "core"]:
        core_findings = scanner.scan_core(file_paths=scoped_files)
        core_summary = ledger.sync_channel("core", core_findings, scanned_files=scoped_files)
        summaries["core"] = core_summary

    # Scan UI Track
    if args.track in ["all", "ui"]:
        ui_findings = scanner.scan_ui(file_paths=scoped_files)
        ui_summary = ledger.sync_channel("ui", ui_findings, scanned_files=scoped_files)
        summaries["ui"] = ui_summary

    meta = ledger.update_meta_index(summaries)

    # Output executive dashboard
    print("\n" + "=" * 70)
    print("📡 EDGE HEALTH RADAR — OBSERVATION & DEBT LEDGER")
    print("=" * 70)
    print(f"Overall Health Score: {meta['overall_health_score']}/100 | Open Findings: {meta['total_open_findings']}")
    print("-" * 70)

    for track_name, summary in summaries.items():
        icon = "⚙️ " if track_name == "core" else "🎨"
        print(f"{icon} Track [{track_name.upper()}]: Health {summary.health_score}/100")
        print(f"   Open: {summary.total_open} (Critical: {summary.critical_count}, Warning: {summary.warning_count}, Advisory: {summary.advisory_count}) | Auto-Resolved: {summary.resolved_count}")
        if summary.macro_patterns:
            print(f"   💡 Systemic Macro Patterns ({len(summary.macro_patterns)}):")
            for mp in summary.macro_patterns:
                print(f"      - {mp}")
        print()

    print(f"📁 Ledger updated at: {target_repo / '.edge' / 'ledger'}")
    print("=" * 70)


def cmd_status(args):
    target_repo = normalize_target_path(args.target)
    ledger = LedgerEngine(target_repo)
    meta_file = target_repo / ".edge" / "ledger" / "meta.json"

    if not meta_file.exists():
        print("No radar ledger found. Run `scan` first.")
        sys.exit(0)

    import json
    meta = json.loads(meta_file.read_text(encoding="utf-8"))

    fmt = getattr(args, "format", "human")
    if fmt == "toon":
        print(toon_encode({"radar_status": meta}))
        return
    elif fmt == "json":
        print(json.dumps(meta, indent=2))
        return

    print("\n" + "=" * 70)
    print("📊 EDGE HEALTH RADAR DASHBOARD")
    print("=" * 70)
    print(f"Last Updated: {meta['updated_at']}")
    print(f"Overall Health: {meta['overall_health_score']}/100 | Active Open Debt: {meta['total_open_findings']}")
    print("-" * 70)

    for ch_name, data in meta.get("channels", {}).items():
        icon = "⚙️ " if ch_name == "core" else "🎨"
        print(f"{icon} {ch_name.upper()} CHANNEL: Health {data['health_score']}/100 | Open: {data['open']} (Critical: {data['critical']}, Warning: {data['warning']})")

    if meta.get("systemic_macro_patterns"):
        print("\n🔍 RECURRING MACRO PATTERNS (Candidates for new Gate rules):")
        for p in meta["systemic_macro_patterns"]:
            print(f"  ⚡ {p}")

    print("=" * 70 + "\n")


def cmd_report(args):
    target_repo = normalize_target_path(args.target)
    ledger = LedgerEngine(target_repo)

    ui_items = [i for i in ledger.load_channel("ui") if i.status == FindingStatus.OPEN.value]
    core_items = [i for i in ledger.load_channel("core") if i.status == FindingStatus.OPEN.value]

    fmt = getattr(args, "format", "markdown")
    if fmt == "toon":
        data = {
            "radar_report": {
                "target": str(target_repo),
                "total_actionable": len(ui_items) + len(core_items),
                "core_findings": [
                    {
                        "severity": item.severity,
                        "title": item.title,
                        "file": f"{item.file_path}:{item.line_number}",
                        "fingerprint": item.fingerprint,
                        "suggested_fix": item.suggested_fix,
                    }
                    for item in core_items[:args.top]
                ],
                "ui_findings": [
                    {
                        "severity": item.severity,
                        "title": item.title,
                        "file": f"{item.file_path}:{item.line_number}",
                        "fingerprint": item.fingerprint,
                        "suggested_fix": item.suggested_fix,
                    }
                    for item in ui_items[:args.top]
                ],
            }
        }
        report_content = toon_encode(data)
        if args.out:
            out_path = Path(args.out)
            out_path.write_text(report_content, encoding="utf-8")
            print(f"Report successfully saved to: {out_path}")
        else:
            print(report_content)
        return

    out_lines = [
        "# 📡 Edge Radar: Debt Ledger & Refactoring Proposals\n",
        f"> **Generated at:** {Path(target_repo).resolve().name}  ",
        f"> **Total Actionable Items:** {len(ui_items) + len(core_items)}\n",
        "---\n",
        "## ⚙️ Backend / Core Track Findings\n",
    ]

    if not core_items:
        out_lines.append("_No open backend debt in current scope._\n")
    else:
        for idx, item in enumerate(core_items[:args.top], start=1):
            out_lines.extend([
                f"### {idx}. [{item.severity}] {item.title}",
                f"- **File:** `{item.file_path}:{item.line_number}`",
                f"- **Fingerprint:** `{item.fingerprint}`",
                f"- **Suggested Action:** {item.suggested_fix}",
                f"- **Details:** `{item.details}`\n",
            ])

    out_lines.append("\n---\n## 🎨 Frontend / UI Track Findings\n")
    if not ui_items:
        out_lines.append("_No open UI debt in current scope._\n")
    else:
        for idx, item in enumerate(ui_items[:args.top], start=1):
            out_lines.extend([
                f"### {idx}. [{item.severity}] {item.title}",
                f"- **File:** `{item.file_path}:{item.line_number}`",
                f"- **Fingerprint:** `{item.fingerprint}`",
                f"- **Suggested Action:** {item.suggested_fix}",
                f"- **Details:** `{item.details}`\n",
            ])

    report_content = "\n".join(out_lines)
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(report_content, encoding="utf-8")
        print(f"Report successfully saved to: {out_path}")
    else:
        print(report_content)


def _derive_item_slug(item) -> str:
    import re
    stem = Path(item.file_path).stem.lower()
    rule_short = re.sub(r"^rule-", "", item.rule_id.lower())
    fp_short = (item.fingerprint or "")[:6].lower()
    raw = f"{item.track}-{stem}-{rule_short}-{fp_short}" if fp_short else f"{item.track}-{stem}-{rule_short}"
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")


def _derive_metric_targets(item) -> dict:
    details = item.details if isinstance(item.details, dict) else {}
    rule_upper = (item.rule_id or "").upper()
    if "db_leaks" in details or "DB-LEAK" in rule_upper or "SQL" in rule_upper:
        return {"db_leaks": 0}
    if "max_cc" in details or "CC" in rule_upper or "COMPLEXITY" in rule_upper:
        return {"max_cc": 10}
    if "DUPLICATE" in rule_upper or "DRYER" in rule_upper:
        return {"dryer_clones": 0}
    if rule_upper.startswith("RULE-TS-"):
        return {"type_score": 90}
    return {"max_cc": 10}


def _load_existing_ticket_fingerprints(tickets_dir: Path) -> set:
    existing = set()
    if not tickets_dir.is_dir():
        return existing
    import yaml
    for md_file in tickets_dir.glob("*.md"):
        existing.add(md_file.stem)
        try:
            text = md_file.read_text(encoding="utf-8", errors="ignore")
            if text.startswith("---"):
                parts = text.split("---", 2)
                if len(parts) >= 3:
                    fm = yaml.safe_load(parts[1]) or {}
                    if isinstance(fm, dict):
                        if fm.get("slug"):
                            existing.add(str(fm["slug"]))
                        if fm.get("fingerprint"):
                            existing.add(str(fm["fingerprint"]))
        except Exception:
            continue
    return existing


def cmd_export_tasks(args):
    from tools.brigade.tasks_bridge import create_refactor_ticket, resolve_target_repo_root

    target_repo = resolve_target_repo_root(normalize_target_path(args.target))
    ledger = LedgerEngine(target_repo)
    tracks = ["core", "ui"] if args.track == "all" else [args.track]

    severity_rank = {
        FindingSeverity.CRITICAL.value: 0,
        FindingSeverity.WARNING.value: 1,
        FindingSeverity.ADVISORY.value: 2,
    }

    open_items = []
    for trk in tracks:
        for item in ledger.load_channel(trk):
            if item.status == FindingStatus.OPEN.value:
                open_items.append(item)

    open_items.sort(key=lambda i: (severity_rank.get(i.severity, 99), i.file_path, i.line_number))

    tickets_dir = target_repo / ".edge" / "tickets" / "refactor"
    existing_keys = _load_existing_ticket_fingerprints(tickets_dir)

    exported_count = 0
    skipped_count = 0
    seen_fps = set()
    top_n = max(0, int(getattr(args, "top", 10)))

    for item in open_items:
        if exported_count >= top_n:
            break
        slug = _derive_item_slug(item)
        if item.fingerprint in seen_fps or item.fingerprint in existing_keys or slug in existing_keys:
            skipped_count += 1
            continue
        seen_fps.add(item.fingerprint)
        existing_keys.add(slug)

        targets = _derive_metric_targets(item)
        ok, ticket_path, tasks_id = create_refactor_ticket(
            repo_path=target_repo,
            slug=slug,
            track=item.track,
            target_rules=[item.rule_id],
            target_files=[item.file_path],
            metric_targets=targets,
            door_type="two-way",
            sync_tasks=bool(getattr(args, "sync_tasks", False)),
            hold_captain=False,
        )
        if ok:
            exported_count += 1
            tid_info = f" (tasks-axi: {tasks_id})" if tasks_id else ""
            print(f"✅ Exported {ticket_path}{tid_info}")

    print(f"Export complete: {exported_count} ticket(s) created, {skipped_count} duplicate(s) skipped.")


def main():
    parser = argparse.ArgumentParser(description="Edge Radar: Scoped Pattern Observation & Idempotent Debt Ledger")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan command
    p_scan = subparsers.add_parser("scan", help="Scan repository and update debt ledger")
    p_scan.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_scan.add_argument("--mode", choices=["churn", "pr", "all"], default="churn", help="Scope mode: churn (hot files), pr (diff), all (full repo)")
    p_scan.add_argument("--since", default="14.days", help="Git churn time window (default: 14.days)")
    p_scan.add_argument("--max-churn", type=int, default=25, help="Max churn files to scan (default: 25)")
    p_scan.add_argument("--base", default="main", help="Base ref for PR mode (default: main)")
    p_scan.add_argument("--track", choices=["all", "ui", "core"], default="all", help="Channel track to scan")
    p_scan.set_defaults(func=cmd_scan)

    # status command
    p_status = subparsers.add_parser("status", help="Show current health board and open findings")
    p_status.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_status.add_argument("--format", choices=["human", "toon", "json"], default="human", help="Output format: human (default), toon (token-frugal), or json")
    p_status.set_defaults(func=cmd_status)

    # report command
    p_report = subparsers.add_parser("report", help="Generate refactoring proposal report")
    p_report.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_report.add_argument("--top", type=int, default=15, help="Max items per track")
    p_report.add_argument("--format", choices=["markdown", "toon"], default="markdown", help="Report format: markdown (default) or toon (token-frugal)")
    p_report.add_argument("--out", "-o", default=None, help="Output markdown or toon file path")
    p_report.set_defaults(func=cmd_report)

    # export-tasks command
    p_export = subparsers.add_parser("export-tasks", help="Convert open ledger items into refactor tickets")
    p_export.add_argument("target", nargs="?", default=".", help="Target repository directory")
    p_export.add_argument("--track", choices=["all", "core", "ui"], default="all", help="Track filter")
    p_export.add_argument("--top", type=int, default=10, help="Max open items to export")
    p_export.add_argument("--sync-tasks", action="store_true", help="Sync exported tickets to tasks-axi")
    p_export.set_defaults(func=cmd_export_tasks)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
