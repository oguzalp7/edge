"""
Scan, status, and report subcommand implementations for Edge Radar CLI.
"""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.common import normalize_target_path, toon_encode
from tools.radar.churn import ChurnAnalyzer
from tools.radar.ledger import LedgerEngine
from tools.radar.models import FindingStatus
from tools.radar.scanner import RadarScanner


def _resolve_scan_scope(args: Any, churn_analyzer: ChurnAnalyzer) -> Tuple[bool, Optional[List[str]]]:
    if args.mode == "churn":
        hotspots = churn_analyzer.get_churn_hotspots(since=args.since, max_files=args.max_churn)
        scoped = [h[0] for h in hotspots]
        if not scoped:
            print(f"🎯 Churn Scope: No active commit hotspots found in the past {args.since}. Codebase is quiescent.")
            return False, None
        print(f"🎯 Churn Scope: Scanning {len(scoped)} active hot files from the past {args.since}...")
        return True, scoped
    if args.mode == "pr":
        scoped = churn_analyzer.get_pr_changed_files(base_ref=args.base)
        if not scoped:
            print(f"🎯 PR Scope: No modified files found against base '{args.base}'.")
            return False, None
        print(f"🎯 PR Scope: Scanning {len(scoped)} files changed against '{args.base}'...")
        return True, scoped
    print("🌐 Full Scope: Scanning all production source files in repo...")
    return True, None


def _print_scan_dashboard(target_repo: Path, meta: Dict[str, Any], summaries: Dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("📡 EDGE HEALTH RADAR — OBSERVATION & DEBT LEDGER")
    print("=" * 70)
    print(f"Overall Health Score: {meta['overall_health_score']}/100 | Open Findings: {meta['total_open_findings']}")
    print("-" * 70)
    for track_name, summary in summaries.items():
        icon = "⚙️ " if track_name == "core" else "🎨"
        print(f"{icon} Track [{track_name.upper()}]: Health {summary.health_score}/100")
        print(f"   Open: {summary.total_open} (Critical: {summary.critical_count}, Warning: {summary.warning_count}, Advisory: {summary.advisory_count}) | Auto-Resolved: {summary.resolved_count}")
        for mp in summary.macro_patterns:
            print(f"      - {mp}")
        print()
    print(f"📁 Ledger updated at: {target_repo / '.edge' / 'ledger'}")
    print("=" * 70)


def cmd_scan(args: Any) -> None:
    target_repo = normalize_target_path(args.target)
    if not target_repo.exists():
        print(f"Error: Repository path does not exist: {target_repo}", file=sys.stderr)
        sys.exit(1)
    churn_analyzer = ChurnAnalyzer(target_repo)
    proceed, scoped_files = _resolve_scan_scope(args, churn_analyzer)
    if not proceed:
        return
    ledger = LedgerEngine(target_repo)
    scanner = RadarScanner(target_repo)
    summaries = {}
    if args.track in ("all", "core"):
        summaries["core"] = ledger.sync_channel("core", scanner.scan_core(file_paths=scoped_files), scanned_files=scoped_files)
    if args.track in ("all", "ui"):
        summaries["ui"] = ledger.sync_channel("ui", scanner.scan_ui(file_paths=scoped_files), scanned_files=scoped_files)
    meta = ledger.update_meta_index(summaries)
    _print_scan_dashboard(target_repo, meta, summaries)


def cmd_status(args: Any) -> None:
    target_repo = normalize_target_path(args.target)
    meta_file = target_repo / ".edge" / "ledger" / "meta.json"
    if not meta_file.exists():
        print("No radar ledger found. Run `scan` first.")
        sys.exit(0)
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    fmt = getattr(args, "format", "human")
    if fmt == "toon":
        print(toon_encode({"radar_status": meta}))
        return
    if fmt == "json":
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


def _finding_to_dict(item: Any) -> Dict[str, Any]:
    return {
        "severity": item.severity,
        "title": item.title,
        "file": f"{item.file_path}:{item.line_number}",
        "fingerprint": item.fingerprint,
        "suggested_fix": item.suggested_fix,
    }


def _append_md_section(out_lines: List[str], heading: str, empty_msg: str, items: List[Any], top: int) -> None:
    out_lines.append(heading)
    if not items:
        out_lines.append(empty_msg)
        return
    for idx, item in enumerate(items[:top], start=1):
        out_lines.extend([
            f"### {idx}. [{item.severity}] {item.title}",
            f"- **File:** `{item.file_path}:{item.line_number}`",
            f"- **Fingerprint:** `{item.fingerprint}`",
            f"- **Suggested Action:** {item.suggested_fix}",
            f"- **Details:** `{item.details}`\n",
        ])


def cmd_report(args: Any) -> None:
    target_repo = normalize_target_path(args.target)
    ledger = LedgerEngine(target_repo)
    ui_items = [i for i in ledger.load_channel("ui") if i.status == FindingStatus.OPEN.value]
    core_items = [i for i in ledger.load_channel("core") if i.status == FindingStatus.OPEN.value]
    fmt = getattr(args, "format", "markdown")
    if fmt == "toon":
        report_content = toon_encode({
            "radar_report": {
                "target": str(target_repo),
                "total_actionable": len(ui_items) + len(core_items),
                "core_findings": [_finding_to_dict(i) for i in core_items[:args.top]],
                "ui_findings": [_finding_to_dict(i) for i in ui_items[:args.top]],
            }
        })
    else:
        out_lines = [
            "# 📡 Edge Radar: Debt Ledger & Refactoring Proposals\n",
            f"> **Generated at:** {Path(target_repo).resolve().name}  ",
            f"> **Total Actionable Items:** {len(ui_items) + len(core_items)}\n",
            "---\n",
        ]
        _append_md_section(out_lines, "## ⚙️ Backend / Core Track Findings\n", "_No open backend debt in current scope._\n", core_items, args.top)
        _append_md_section(out_lines, "\n---\n## 🎨 Frontend / UI Track Findings\n", "_No open UI debt in current scope._\n", ui_items, args.top)
        report_content = "\n".join(out_lines)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(report_content, encoding="utf-8")
        print(f"Report successfully saved to: {out_path}")
    else:
        print(report_content)
