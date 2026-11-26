"""
Knip JSON parsing and dead-code report formatting helpers.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class DeadCodeReport:
    unused_files: List[str]
    unused_exports: List[Dict[str, Any]]
    unused_types: List[Dict[str, Any]]
    engine: str = "knip"


def _add_unique_file(fname: Optional[str], seen: set, out: List[str]) -> None:
    if fname and fname not in seen:
        seen.add(fname)
        out.append(fname)


def _extract_issue_items(items: List[Dict[str, Any]], file_path: str, target: List[Dict[str, Any]]) -> None:
    for entry in items:
        item = dict(entry)
        if "file" not in item and file_path:
            item["file"] = file_path
        target.append(item)


def parse_knip_json(raw_json: str) -> DeadCodeReport:
    """Parses Knip JSON output into structured DeadCodeReport."""
    empty = DeadCodeReport(unused_files=[], unused_exports=[], unused_types=[], engine="knip")
    if not raw_json:
        return empty
    idx = raw_json.find('{"')
    if idx < 0:
        idx = raw_json.find("{")
    if idx < 0:
        return empty
    try:
        data = json.loads(raw_json[idx:])
    except Exception:
        return empty

    seen: set = set()
    unused_files: List[str] = []
    for f_item in data.get("files", []):
        _add_unique_file(f_item.get("name") or f_item.get("file") if isinstance(f_item, dict) else (f_item if isinstance(f_item, str) else None), seen, unused_files)

    unused_exports: List[Dict[str, Any]] = []
    unused_types: List[Dict[str, Any]] = []
    for issue in data.get("issues", []):
        fp = issue.get("file", "")
        for f_item in issue.get("files", []):
            _add_unique_file((f_item.get("name") or fp) if isinstance(f_item, dict) else (f_item if isinstance(f_item, str) else None), seen, unused_files)
        _extract_issue_items(issue.get("exports", []), fp, unused_exports)
        _extract_issue_items(issue.get("types", []), fp, unused_types)

    return DeadCodeReport(unused_files=unused_files, unused_exports=unused_exports, unused_types=unused_types, engine="knip")


def format_dead_code_report(report: DeadCodeReport, fmt: str = "human") -> str:
    """Formats dead code report as human-readable, markdown, or JSON."""
    if fmt == "json":
        return json.dumps({"dead_code": {
            "engine": report.engine,
            "unused_files": report.unused_files,
            "unused_exports": report.unused_exports,
            "unused_types": report.unused_types,
        }}, indent=2)
    if fmt == "markdown":
        out = [
            f"# 🧹 Dead-Code Report ({report.engine.upper()} Engine)",
            f"> **Unused Files:** {len(report.unused_files)} | **Unused Exports:** {len(report.unused_exports)} | **Unused Types:** {len(report.unused_types)}\n",
        ]
        if report.unused_files:
            out.extend(["### Unused Files"] + [f"- `{f}`" for f in report.unused_files])
        if report.unused_exports:
            out.extend(["\n### Unused Exports"] + [f"- `{e.get('name')}` in `{e.get('file', '')}` (line {e.get('line', '?')})" for e in report.unused_exports])
        if report.unused_types:
            out.extend(["\n### Unused Types"] + [f"- `{t.get('name')}` in `{t.get('file', '')}` (line {t.get('line', '?')})" for t in report.unused_types])
        return "\n".join(out)
    out = [
        "=" * 80,
        f"🧹  DEAD-CODE REPORT ({report.engine.upper()} ENGINE)",
        f"   Unused Files: {len(report.unused_files)} | Exports: {len(report.unused_exports)} | Types: {len(report.unused_types)}",
        "=" * 80,
    ]
    out.extend(f"   [FILE] {f}" for f in report.unused_files)
    out.extend(f"   [EXPORT] {e.get('name')} in {e.get('file', '')}" for e in report.unused_exports)
    out.extend(f"   [TYPE] {t.get('name')} in {t.get('file', '')}" for t in report.unused_types)
    return "\n".join(out)
