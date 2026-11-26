"""Ship-prep submodule: proof_meta."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json
import tempfile

from tools.brigade.fsm import ProofVerifier
from tools.brigade.models import BrigadeState, Ticket
from tools.common import normalize_target_path
from tools.brigade.ship.paths import _clean_slug

def _extract_ticket_from_proof_json(raw_text: str) -> Optional[Tuple[str, str]]:
    try:
        data = json.loads(raw_text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    tid = str(data.get("ticket_id") or "").strip()
    raw_spec = str(data.get("spec") or "").strip()
    if tid.startswith("TICK-") and raw_spec:
        return _clean_slug(Path(raw_spec).stem), tid
    return None


def _extract_spec_slug_from_proof_json(raw_text: str) -> Optional[str]:
    try:
        data = json.loads(raw_text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw_spec = str(data.get("spec") or "").strip()
    return _clean_slug(Path(raw_spec).stem) if raw_spec else None


def _proof_search_roots(repo: Path, ticket: Optional[Ticket]) -> List[Path]:
    roots = [repo]
    if ticket and ticket.worktree_path:
        wt = normalize_target_path(ticket.worktree_path)
        if wt.is_dir() and wt not in roots:
            roots.insert(0, wt)
    return roots


def _load_json_dict(raw_text: str) -> Dict[str, Any]:
    try:
        raw = json.loads(raw_text)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _extract_str_list(val: Any) -> List[str]:
    if not isinstance(val, list):
        return []
    out: List[str] = []
    for u in val:
        if isinstance(u, str) and u.strip():
            out.append(str(u))
    return out


def _lookup_slug_by_ticket(tid: Optional[str], ticket_by_slug: Dict[str, Optional[str]]) -> str:
    if not tid:
        return ""
    for s, t in ticket_by_slug.items():
        if t == tid:
            return s
    return ""


def _parse_proof_raw_meta(
    raw_text: str,
    rel_path: str,
    ticket_by_slug: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    raw = _load_json_dict(raw_text)
    tid = str(raw.get("ticket_id") or "").strip() or None
    raw_spec = str(raw.get("spec") or "").strip()
    spec_slug = _clean_slug(Path(raw_spec).stem) if raw_spec else _lookup_slug_by_ticket(tid, ticket_by_slug)
    return {
        "spec_slug": spec_slug or _clean_slug(Path(rel_path).stem),
        "ticket_id": tid,
        "screenshot_urls": _extract_str_list(raw.get("screenshot_urls")),
        "directives_checklist": raw.get("directives_checklist"),
    }


def _verify_proof_raw_text(
    raw_text: str,
    rel_path: str,
    roots: List[Path],
    ticket: Optional[Ticket],
    ticket_by_slug: Dict[str, Optional[str]],
) -> Tuple[bool, Dict[str, Any]]:
    meta = _parse_proof_raw_meta(raw_text, rel_path, ticket_by_slug)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_pf = Path(tmp_dir) / Path(rel_path).name
        tmp_pf.write_text(raw_text, encoding="utf-8")
        ok, msg, det = ProofVerifier.verify_receipt(tmp_pf, roots, ticket=ticket)
    if ok:
        return True, {
            "slug": _clean_slug(str(det.get("slug") or Path(rel_path).stem)),
            "spec_slug": meta["spec_slug"],
            "ticket_id": meta["ticket_id"],
            "path": rel_path,
            "visited_urls": det.get("visited_urls", []),
            "user_actions_executed": det.get("user_actions_executed", []),
            "screenshot_paths": det.get("screenshot_paths", []),
            "screenshot_urls": meta["screenshot_urls"],
            "screenshot_hashes": det.get("screenshot_hashes", {}),
            "db_crosscheck": det.get("db_crosscheck", {}),
            "directives_checklist": meta.get("directives_checklist"),
            "persistence_verified": True,
            "console_clean": True,
        }
    return False, {
        "slug": _clean_slug(Path(rel_path).stem),
        "spec_slug": meta["spec_slug"],
        "ticket_id": meta["ticket_id"],
        "path": rel_path,
        "error": det.get("error", "PROOF_VERIFICATION_FAILED"),
        "message": msg,
        "details": det,
    }
