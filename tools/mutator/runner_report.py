"""
Mutation outcome/summary dataclasses and report formatters (TOON, JSON, human).
"""

import json
from dataclasses import asdict, dataclass
from typing import List, Optional, Union

from tools.mutator.sites import MutationSite


@dataclass
class MutantOutcome:
    site: MutationSite
    status: str
    duration_sec: float = 0.0
    duration_ms: Optional[float] = None

    def __post_init__(self) -> None:
        if self.duration_ms is not None and self.duration_sec == 0.0:
            self.duration_sec = round(float(self.duration_ms) / 1000.0, 3)


@dataclass
class MutationSummary:
    total: int
    killed: int
    survived: int
    timed_out: int
    score_pct: float
    outcomes: List[MutantOutcome]
    file_path: str = ""
    mode: str = "all"
    passed: bool = True


@dataclass
class RecursiveMutationSummary:
    files_scanned: int
    total: int
    killed: int
    survived: int
    timed_out: int
    score_pct: float
    passed: bool
    file_summaries: List[MutationSummary]


def _clip_inline(text: str, limit: int = 60) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else (flat[: limit - 3] + "...")


def _collect_all_outcomes(summary: Union[MutationSummary, RecursiveMutationSummary]) -> List[MutantOutcome]:
    if isinstance(summary, RecursiveMutationSummary):
        return [o for fs in summary.file_summaries for o in fs.outcomes]
    return summary.outcomes


def _format_mutator_toon(summary: Union[MutationSummary, RecursiveMutationSummary], mode: str) -> str:
    is_rec = isinstance(summary, RecursiveMutationSummary)
    target_label = f"{summary.files_scanned}_files" if is_rec else (summary.file_path or "target")
    eff_mode = mode if is_rec else (summary.mode or mode)
    header = (
        f"mutator[{summary.total}]"
        f"{{target:{target_label},mode:{eff_mode},killed:{summary.killed},"
        f"survived:{summary.survived},timed_out:{summary.timed_out},"
        f"score_pct:{summary.score_pct},passed:{str(summary.passed).lower()}}}:"
    )
    cols = "  file:line | op | original | mutated | status" if is_rec else "  line | op | original | mutated | status"
    lines = [header, cols]
    for o in _collect_all_outcomes(summary):
        loc = f"{o.site.file_path}:{o.site.line}" if is_rec else str(o.site.line)
        lines.append(f"  {loc} | {o.site.category} | {_clip_inline(o.site.original)} | {_clip_inline(o.site.mutant)} | {o.status}")
    return "\n".join(lines)


def _format_mutator_human(summary: Union[MutationSummary, RecursiveMutationSummary]) -> str:
    target_label = f"{summary.files_scanned} file(s)" if isinstance(summary, RecursiveMutationSummary) else (summary.file_path or "target")
    lines = [
        "=" * 70,
        "🧬  EDGE MUTATOR REPORT",
        f"   Target: {target_label}",
        f"   Total Mutants: {summary.total} | Killed: {summary.killed} | Survived: {summary.survived} | Timed Out: {summary.timed_out}",
        f"   Mutation Score: {summary.score_pct:.1f}%",
        "=" * 70,
    ]
    for o in _collect_all_outcomes(summary):
        icon = "✔" if o.status == "KILLED" else "✖"
        lines.append(
            f"   {icon} [{o.status:9s}] {o.site.file_path}:{o.site.line}: "
            f"{_clip_inline(o.site.original, 40)} -> {_clip_inline(o.site.mutant, 40)}"
        )
    return "\n".join(lines)


def format_mutation_report(
    summary: Union[MutationSummary, RecursiveMutationSummary], fmt: str = "toon", mode: str = "all"
) -> str:
    """Formats MutationSummary or RecursiveMutationSummary as 'toon' (default), 'json', or 'human'."""
    style = (fmt or "toon").strip().lower()
    if style == "json":
        return json.dumps(asdict(summary), indent=2, ensure_ascii=False)
    return _format_mutator_human(summary) if style == "human" else _format_mutator_toon(summary, mode)
