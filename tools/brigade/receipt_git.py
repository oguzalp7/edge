"""Git diff/SHA helpers, ticket frontmatter loader, and Seal 4 synthesis for RefactorReceipt."""

from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

import yaml

from tools.brigade.receipt_models import compute_neutrality, norm_rel


def run_git(cwd: Path, args: List[str]) -> Tuple[int, str, str]:
    """Run git command in cwd with timeout."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return 1, "", str(exc)


def get_git_head_sha(work_dir: Path) -> str:
    """Return current HEAD commit SHA or empty string."""
    code, out, _ = run_git(work_dir, ["rev-parse", "HEAD"])
    return out.strip() if code == 0 and out.strip() else ""


def get_diff_changed_files(work_dir: Path, base_branch: str) -> List[str]:
    """Return non-.edge changed files against base_branch."""
    for args in (["diff", "--name-only", f"{base_branch}..HEAD"], ["diff", "--name-only", base_branch], ["diff", "--name-only", "HEAD~1"]):
        code, out, _ = run_git(work_dir, args)
        if code == 0:
            files = [norm_rel(line) for line in out.splitlines() if norm_rel(line)]
            return [f for f in dict.fromkeys(files) if not f.startswith(".edge/")]
    return []


def load_ticket_frontmatter(target_repo: Path, slug: str, ticket_path_hint: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    """Load YAML frontmatter from a refactor ticket markdown file."""
    rel = ticket_path_hint or f".edge/tickets/refactor/{slug}.md"
    cand = target_repo / rel
    if not cand.is_file():
        rel = f".edge/tickets/refactor/{slug}.md"
        cand = target_repo / rel
    if not cand.is_file():
        return {}, rel
    try:
        text = cand.read_text(encoding="utf-8", errors="ignore")
        if text.startswith("---"):
            parts = text.split("---", 2)
            parsed = yaml.safe_load(parts[1]) if len(parts) >= 3 else None
            if isinstance(parsed, dict):
                return parsed, rel
    except Exception:
        pass
    return {}, rel


def build_seal_4_from_examiner(examiner_receipt: Any, surgeon_cid: Optional[str], default_evidence: List[str]) -> Dict[str, Any]:
    """Build Seal 4 examiner payload from an ExaminerReceipt or dict."""
    if examiner_receipt is None:
        return {
            "verdict": "PENDING", "examiner_cid": None, "surgeon_cid": surgeon_cid,
            "neutrality": "unverified", "sealed_at": "", "summary": "Awaiting Examiner 3-axis review.",
            "evidence_reviewed": list(default_evidence),
        }
    ex_dict = examiner_receipt.to_dict() if hasattr(examiner_receipt, "to_dict") else dict(examiner_receipt)
    examiner_cid = ex_dict.get("examiner_cid")
    return {
        "verdict": str(ex_dict.get("verdict") or "").upper(),
        "examiner_cid": examiner_cid,
        "surgeon_cid": surgeon_cid,
        "neutrality": compute_neutrality(examiner_cid, surgeon_cid),
        "sealed_at": str(ex_dict.get("sealed_at") or datetime.now(timezone.utc).isoformat()),
        "summary": str(ex_dict.get("summary") or ""),
        "evidence_reviewed": list(ex_dict.get("evidence_reviewed") or default_evidence),
    }
