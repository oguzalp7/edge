"""4-Seal RefactorReceipt dataclass, hashing, neutrality, and Markdown rendering."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from .tasks_bridge import atomic_write_text, resolve_target_repo_root
except ImportError:
    from tools.brigade.tasks_bridge import atomic_write_text, resolve_target_repo_root

LOWER_IS_BETTER_METRICS = frozenset({"db_leaks", "max_cc", "dryer_clones", "sloc"})
HIGHER_IS_BETTER_METRICS = frozenset({"type_score"})


def norm_rel(path_str: str) -> str:
    """Normalize relative forward-slash path without leading ./."""
    norm = str(path_str or "").strip().replace("\\", "/")
    return norm[2:] if norm.startswith("./") else norm


def compute_changed_files_hash(changed_files: List[str]) -> str:
    """Compute deterministic SHA-256 over sorted normalized changed file paths."""
    cleaned = sorted({norm_rel(f) for f in (changed_files or []) if norm_rel(f)})
    return hashlib.sha256("\n".join(cleaned).encode("utf-8")).hexdigest()


def compute_neutrality(examiner_cid: Optional[str], surgeon_cid: Optional[str]) -> str:
    """Evaluate whether Examiner and Surgeon are distinct, non-empty station CIDs."""
    ex, su = str(examiner_cid or "").strip(), str(surgeon_cid or "").strip()
    if not ex or not su:
        return "unverified"
    return "violated" if ex == su else "verified"


def _render_metric_rows(s2: Dict[str, Any]) -> List[str]:
    before, after, targets = s2.get("before") or {}, s2.get("after") or {}, s2.get("metric_targets") or {}
    lines = ["## Seal 2 — Before / After Metric Delta", "| Metric | Before | Target | After | Delta |", "| :--- | ---: | ---: | ---: | ---: |"]
    for key in dict.fromkeys([*before.keys(), *after.keys(), *targets.keys()]):
        b_val, t_val, a_val = before.get(key), targets.get(key), after.get(key)
        delta_str = f"{(a_val - b_val):+g}" if isinstance(b_val, (int, float)) and isinstance(a_val, (int, float)) else "—"
        lines.append(
            f"| `{key}` | {b_val if b_val is not None else 'null'} | "
            f"{t_val if t_val is not None else '—'} | {a_val if a_val is not None else 'null'} | {delta_str} |"
        )
    return lines


@dataclass
class RefactorReceipt:
    """4-Seal RefactorReceipt binding intent, metrics, gate proof, and examiner review."""

    slug: str
    ticket_id: str
    track: str
    seal_1_intent: Dict[str, Any]
    seal_2_metrics: Dict[str, Any]
    seal_3_gate: Dict[str, Any]
    seal_4_examiner: Dict[str, Any]
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version, "slug": self.slug, "ticket_id": self.ticket_id,
            "track": self.track, "seal_1_intent": dict(self.seal_1_intent),
            "seal_2_metrics": dict(self.seal_2_metrics), "seal_3_gate": dict(self.seal_3_gate),
            "seal_4_examiner": dict(self.seal_4_examiner),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefactorReceipt":
        return cls(
            schema_version=str(data.get("schema_version") or "1.0.0"), slug=str(data.get("slug") or ""),
            ticket_id=str(data.get("ticket_id") or ""), track=str(data.get("track") or "core"),
            seal_1_intent=dict(data.get("seal_1_intent") or {}), seal_2_metrics=dict(data.get("seal_2_metrics") or {}),
            seal_3_gate=dict(data.get("seal_3_gate") or {}), seal_4_examiner=dict(data.get("seal_4_examiner") or {}),
        )

    def to_markdown(self) -> str:
        s1, s3, s4 = self.seal_1_intent, self.seal_3_gate, self.seal_4_examiner
        lines = [
            f"# RefactorReceipt: {self.slug}", "", f"- **Ticket ID:** `{self.ticket_id}`", f"- **Track:** `{self.track}`",
            f"- **Commit SHA:** `{s1.get('commit_sha', '')}`", f"- **Changed Files Hash:** `{s1.get('changed_files_hash', '')}`",
            f"- **Door Classification:** {s1.get('door_type', '')}", f"- **Behavior Preserved:** `{s1.get('behavior_preserved')}`", "",
            *_render_metric_rows(self.seal_2_metrics), "", "## Seal 3 — Deterministic Gate Proof",
            f"- **All Passed:** `{s3.get('all_passed')}` (`{s3.get('base_branch', '')}`)",
        ]
        for st in s3.get("stages") or []:
            lines.append(f"- Stage {st.get('stage_num')}: [{'PASS' if st.get('passed') else 'FAIL'}] {st.get('name')} — {st.get('message')}")
        lines.extend([
            "", "## Seal 4 — Examiner 3-Axis Seal", f"- **Verdict:** `{s4.get('verdict', 'PENDING')}`",
            f"- **Neutrality:** `{s4.get('neutrality', 'unverified')}` (Examiner: `{s4.get('examiner_cid')}`, Surgeon: `{s4.get('surgeon_cid')}`)",
            f"- **Summary:** {s4.get('summary', '')}", "",
        ])
        return "\n".join(lines)

    def write(self, target_repo: Path) -> Tuple[Path, Path]:
        receipts_dir = resolve_target_repo_root(target_repo) / ".edge" / "receipts" / "refactor"
        json_path, md_path = receipts_dir / f"{self.slug}.json", receipts_dir / f"{self.slug}.md"
        atomic_write_text(json_path, json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        atomic_write_text(md_path, self.to_markdown())
        return json_path, md_path
