"""
Dead-Code Elimination & Mechanical Debt Pre-Sweep Engine.
"""

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple, Union

from tools.audit.dead_code_knip import DeadCodeReport, format_dead_code_report, parse_knip_json
from tools.ui_audit.graph_builder import GraphBuilder


def _is_stem_referenced(root: Path, orphan: object) -> bool:
    stem = Path(orphan.rel_path).stem
    for p in root.rglob("*"):
        if not (p.is_file() and p.suffix in (".ts", ".tsx", ".js", ".jsx") and p != orphan.file_path):
            continue
        try:
            if stem in p.read_text(encoding="utf-8", errors="ignore"):
                return True
        except Exception:
            pass
    return False


def _run_knip_cli(root: Path, timeout_sec: int) -> Optional[DeadCodeReport]:
    if not ((root / "package.json").exists() and shutil.which("npx")):
        return None
    for cmd in (["npx", "--no-install", "knip", "--reporter", "json"], ["npx", "--yes", "knip", "--reporter", "json"]):
        try:
            res = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True, timeout=timeout_sec)
            out = res.stdout.strip()
            if "{" in out and '"issues"' in out:
                return parse_knip_json(out)
        except Exception:
            pass
    return None


def run_dead_code_scan(repo_root: Union[Path, str], timeout_sec: int = 60) -> DeadCodeReport:
    """Executes knip with JSON reporter, falling back to GraphBuilder orphan scan."""
    root = Path(repo_root)
    if (knip_rep := _run_knip_cli(root, timeout_sec)) is not None:
        return knip_rep
    try:
        graph = GraphBuilder(root)
        graph.build_graph()
        unused = [o.rel_path for o in graph.find_orphans() if not _is_stem_referenced(root, o)]
        return DeadCodeReport(unused_files=unused, unused_exports=[], unused_types=[], engine="fallback")
    except Exception:
        return DeadCodeReport(unused_files=[], unused_exports=[], unused_types=[], engine="fallback")


def run_mechanical_presweep(repo_root: Union[Path, str], target_files: Optional[List[str]] = None) -> Tuple[int, str]:
    """Executes 'npx eslint --fix' to mechanically eliminate dead imports."""
    cmd = ["npx", "eslint", "--fix", *(target_files or ["."])]
    try:
        res = subprocess.run(cmd, cwd=str(Path(repo_root)), capture_output=True, text=True)
        return res.returncode, res.stdout or res.stderr
    except Exception as e:
        return 1, str(e)
