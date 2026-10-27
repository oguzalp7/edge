"""
Dead-Code Elimination & Mechanical Debt Pre-Sweep Engine.
Integrates Knip for JS/TS projects with GraphBuilder fallback and automated eslint --fix pre-sweep.
"""

import sys
import os
import json
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional, Union

from tools.ui_audit.graph_builder import GraphBuilder


@dataclass
class DeadCodeReport:
    unused_files: List[str]
    unused_exports: List[Dict[str, Any]]
    unused_types: List[Dict[str, Any]]
    engine: str = "knip"  # "knip" | "fallback"


def parse_knip_json(raw_json: str) -> DeadCodeReport:
    """Parses Knip JSON output into structured DeadCodeReport."""
    if not raw_json:
        return DeadCodeReport(unused_files=[], unused_exports=[], unused_types=[], engine="knip")

    idx = raw_json.find("{")
    if idx == -1:
        return DeadCodeReport(unused_files=[], unused_exports=[], unused_types=[], engine="knip")

    try:
        data = json.loads(raw_json[idx:])
    except Exception:
        return DeadCodeReport(unused_files=[], unused_exports=[], unused_types=[], engine="knip")

    # Collect unused files deduplicated preserving insertion order
    unused_files_set = set()
    unused_files: List[str] = []

    def _add_file(fname: Optional[str]):
        if fname and fname not in unused_files_set:
            unused_files_set.add(fname)
            unused_files.append(fname)

    # Top-level files
    for f_item in data.get("files", []):
        if isinstance(f_item, dict):
            _add_file(f_item.get("name") or f_item.get("file"))
        elif isinstance(f_item, str):
            _add_file(f_item)

    unused_exports: List[Dict[str, Any]] = []
    unused_types: List[Dict[str, Any]] = []

    issues = data.get("issues", [])
    for issue in issues:
        file_path = issue.get("file", "")
        # Knip v5/v6 per-issue files
        for f_item in issue.get("files", []):
            if isinstance(f_item, dict):
                _add_file(f_item.get("name") or file_path)
            elif isinstance(f_item, str):
                _add_file(f_item)

        for exp in issue.get("exports", []):
            item = dict(exp)
            if "file" not in item and file_path:
                item["file"] = file_path
            unused_exports.append(item)
        for typ in issue.get("types", []):
            item = dict(typ)
            if "file" not in item and file_path:
                item["file"] = file_path
            unused_types.append(item)

    return DeadCodeReport(
        unused_files=unused_files,
        unused_exports=unused_exports,
        unused_types=unused_types,
        engine="knip"
    )


def run_dead_code_scan(repo_root: Union[Path, str], timeout_sec: int = 60) -> DeadCodeReport:
    """
    Executes knip with JSON reporter if package.json exists.
    Tries 'npx --no-install knip --reporter json' then 'npx --yes knip --reporter json'.
    If knip is missing or fails, falls back cleanly to GraphBuilder orphan scan.
    """
    root = Path(repo_root)
    pkg_json = root / "package.json"

    if pkg_json.exists() and shutil.which("npx"):
        for cmd in (
            ["npx", "--no-install", "knip", "--reporter", "json"],
            ["npx", "--yes", "knip", "--reporter", "json"],
        ):
            try:
                res = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout_sec)
                out = res.stdout.strip()
                if "{" in out and '"issues"' in out:
                    return parse_knip_json(out)
            except Exception:
                pass

    # Fallback to GraphBuilder orphan component / file detection
    try:
        graph = GraphBuilder(root)
        graph.build_graph()
        orphans = graph.find_orphans()

        unused_files = []
        for o in orphans:
            rel = o.rel_path
            stem = Path(rel).stem
            is_referenced = False
            for p in root.rglob("*"):
                if p.is_file() and p.suffix in (".ts", ".tsx", ".js", ".jsx") and p != o.file_path:
                    try:
                        txt = p.read_text(encoding="utf-8", errors="ignore")
                        if stem in txt:
                            is_referenced = True
                            break
                    except Exception:
                        pass
            if not is_referenced:
                unused_files.append(rel)

        return DeadCodeReport(
            unused_files=unused_files,
            unused_exports=[],
            unused_types=[],
            engine="fallback"
        )
    except Exception:
        return DeadCodeReport(unused_files=[], unused_exports=[], unused_types=[], engine="fallback")


def run_mechanical_presweep(
    repo_root: Union[Path, str],
    target_files: Optional[List[str]] = None
) -> Tuple[int, str]:
    """
    Executes 'npx eslint --fix' to mechanically eliminate dead imports and formatting issues
    without consuming LLM reasoning tokens.
    """
    root = Path(repo_root)
    cmd = ["npx", "eslint", "--fix"]
    if target_files:
        cmd.extend(target_files)
    else:
        cmd.append(".")

    try:
        res = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
        return res.returncode, res.stdout or res.stderr
    except Exception as e:
        return 1, str(e)


def format_dead_code_report(report: DeadCodeReport, fmt: str = "human") -> str:
    """Formats dead code report as human-readable, markdown, or JSON."""
    if fmt == "json":
        return json.dumps({
            "dead_code": {
                "engine": report.engine,
                "unused_files": report.unused_files,
                "unused_exports": report.unused_exports,
                "unused_types": report.unused_types,
            }
        }, indent=2)
    elif fmt == "markdown":
        out = [
            f"# 🧹 Dead-Code Report ({report.engine.upper()} Engine)",
            f"> **Unused Files:** {len(report.unused_files)} | **Unused Exports:** {len(report.unused_exports)} | **Unused Types:** {len(report.unused_types)}\n",
        ]
        if report.unused_files:
            out.append("### Unused Files")
            for f in report.unused_files:
                out.append(f"- `{f}`")
        if report.unused_exports:
            out.append("\n### Unused Exports")
            for e in report.unused_exports:
                out.append(f"- `{e.get('name')}` in `{e.get('file', '')}` (line {e.get('line', '?')})")
        if report.unused_types:
            out.append("\n### Unused Types")
            for t in report.unused_types:
                out.append(f"- `{t.get('name')}` in `{t.get('file', '')}` (line {t.get('line', '?')})")
        return "\n".join(out)
    else:
        out = [
            "=" * 80,
            f"🧹  DEAD-CODE REPORT ({report.engine.upper()} ENGINE)",
            f"   Unused Files: {len(report.unused_files)} | Exports: {len(report.unused_exports)} | Types: {len(report.unused_types)}",
            "=" * 80,
        ]
        for f in report.unused_files:
            out.append(f"   [FILE] {f}")
        for e in report.unused_exports:
            out.append(f"   [EXPORT] {e.get('name')} in {e.get('file', '')}")
        for t in report.unused_types:
            out.append(f"   [TYPE] {t.get('name')} in {t.get('file', '')}")
        return "\n".join(out)
