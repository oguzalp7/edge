"""Git diff/SHA helpers, ticket frontmatter loader, and Seal 4 synthesis for RefactorReceipt."""

from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.receipt_models import compute_neutrality, norm_rel


_SCALAR_LITERALS: Dict[str, Any] = {
    "": None,
    "null": None,
    "~": None,
    "none": None,
    "true": True,
    "false": False,
}


def _parse_collection_scalar(val: str) -> Any:
    try:
        return json.loads(val)
    except Exception:
        if val.startswith("["):
            return [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        return {}


def _parse_numeric_or_str(val: str) -> Any:
    for caster in (int, float):
        try:
            return caster(val)
        except ValueError:
            continue
    return val


def _parse_scalar_fallback(raw: str) -> Any:
    val = raw.strip()
    low = val.lower()
    if low in _SCALAR_LITERALS:
        return _SCALAR_LITERALS[low]
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        return val[1:-1]
    if (val.startswith("[") and val.endswith("]")) or (val.startswith("{") and val.endswith("}")):
        return _parse_collection_scalar(val)
    return _parse_numeric_or_str(val)


def _apply_indented_entry(out: Dict[str, Any], cur_key: str, stripped: str) -> None:
    if stripped.startswith("- "):
        out.setdefault(cur_key, [])
        if isinstance(out[cur_key], list):
            out[cur_key].append(_parse_scalar_fallback(stripped[2:]))
        return
    if ":" in stripped:
        k, v = stripped.split(":", 1)
        if not isinstance(out.get(cur_key), dict):
            out[cur_key] = {}
        out[cur_key][k.strip()] = _parse_scalar_fallback(v)


def _parse_frontmatter_fallback(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    cur_key: Optional[str] = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if len(raw_line) > len(raw_line.lstrip(" ")) and cur_key is not None:
            _apply_indented_entry(out, cur_key, stripped)
        elif ":" in stripped:
            k, v = stripped.split(":", 1)
            cur_key = k.strip()
            out[cur_key] = _parse_scalar_fallback(v) if v.strip() else None
    return out


def _safe_load_frontmatter(raw_yaml: str) -> Optional[Dict[str, Any]]:
    try:
        import yaml

        parsed = yaml.safe_load(raw_yaml)
        return parsed if isinstance(parsed, dict) else None
    except ImportError:
        return _parse_frontmatter_fallback(raw_yaml)


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
            parsed = _safe_load_frontmatter(parts[1]) if len(parts) >= 3 else None
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
