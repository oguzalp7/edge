"""
CRAP score formula and LCOV parsing/coverage lookup helpers.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass
class FunctionCrapMetric:
    file_path: str
    name: str
    start_line: int
    end_line: int
    complexity: int
    coverage_pct: Optional[float] = None
    crap_score: Optional[float] = None
    sloc: int = 0
    is_exported: bool = False


def compute_crap(cc: int, coverage_pct: float) -> float:
    """CRAP(m) = CC(m)^2 * (1 - cov(m)/100)^3 + CC(m)."""
    cov_clamped = max(0.0, min(100.0, float(coverage_pct)))
    risk_factor = (1.0 - (cov_clamped / 100.0)) ** 3
    return round(float((cc ** 2) * risk_factor + cc), 2)


def _parse_da_line(line: str, lines: Dict[int, int]) -> None:
    parts = line[3:].split(",")
    if len(parts) < 2:
        return
    try:
        lines[int(parts[0])] = int(parts[1])
    except ValueError:
        pass


def _parse_brda_line(line: str, branches: List[Tuple[int, int]]) -> None:
    parts = line[5:].split(",")
    if len(parts) < 4:
        return
    try:
        taken_raw = parts[3].strip()
        branches.append((int(parts[0]), 0 if taken_raw == "-" else int(taken_raw)))
    except ValueError:
        pass


def parse_lcov(lcov_content: str) -> Dict[str, Dict[str, Any]]:
    """Parses LCOV content into structured per-file line and branch hits."""
    records: Dict[str, Dict[str, Any]] = {}
    current_file: Optional[str] = None
    lines: Dict[int, int] = {}
    branches: List[Tuple[int, int]] = []

    for raw_line in lcov_content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("SF:"):
            sf = line[3:].strip().replace("\\", "/")
            current_file = sf[2:] if sf.startswith("./") else sf
            lines, branches = {}, []
        elif line.startswith("DA:"):
            _parse_da_line(line, lines)
        elif line.startswith("BRDA:"):
            _parse_brda_line(line, branches)
        elif line == "end_of_record":
            if current_file:
                records[current_file] = {"lines": lines, "branches": branches}
            current_file, lines, branches = None, {}, []

    if current_file:
        records[current_file] = {"lines": lines, "branches": branches}
    return records


def function_coverage_from_lcov(file_cov: Optional[Dict[str, Any]], start_line: int, end_line: int) -> float:
    """Computes coverage percentage for lines [start_line, end_line]."""
    if not file_cov:
        return 0.0
    branches_in_range = [b for b in file_cov.get("branches", []) if start_line <= b[0] <= end_line]
    if branches_in_range:
        taken = sum(1 for b in branches_in_range if b[1] > 0)
        return round(float(taken) / float(len(branches_in_range)) * 100.0, 2)
    lines_in_range = [cnt for ln, cnt in file_cov.get("lines", {}).items() if start_line <= ln <= end_line]
    if lines_in_range:
        hit = sum(1 for cnt in lines_in_range if cnt > 0)
        return round(float(hit) / float(len(lines_in_range)) * 100.0, 2)
    return 0.0


def discover_existing_lcov(repo_root: Union[Path, str]) -> Optional[Path]:
    """Scans repository root for existing LCOV coverage files."""
    root = Path(repo_root)
    for rel in ("coverage/lcov.info", ".coverage/lcov.info", "target/coverage/lcov.info", "lcov.info"):
        if (c := root / rel).exists() and c.is_file():
            return c
    return None
