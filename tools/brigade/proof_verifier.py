"""ProofVerifier and QA proof receipt validation helpers."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.fsm_ops.proof_media import ProofVerifierMediaMixin
from tools.brigade.models import Ticket
from tools.brigade.station_qa_params import _resolve_qa_slug


class SubstepList(str):
    """String-compatible list wrapper for substep lists allowing ' '.join() and sequence unpacking."""
    def __new__(cls, items):
        val = ", ".join(items)
        s = super().__new__(cls, val)
        s._items = list(items)
        return s

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._items[idx]
        return super().__getitem__(idx)


def _find_proof_file(candidates: List[Path]) -> Optional[Path]:
    for p in candidates:
        if p.is_file():
            return p
    return None


def _is_non_empty_list(val: Any) -> bool:
    return isinstance(val, list) and len(val) > 0


class ProofVerifier(ProofVerifierMediaMixin):
    """Deterministic validator for physical QA behavioral proof receipts (.edge/qa/proofs/*.json)."""

    REQUIRED_FLAGS = ("persistence_verified", "console_clean")
    AUTH_REQUIRED_FIELDS = ("visited_urls", "user_actions_executed")

    @staticmethod
    def _verify_core_flags(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        if not ProofVerifier._is_non_empty_str_list(data.get("user_actions_executed")):
            return False, "QA proof receipt invariant failed: 'user_actions_executed' must be a non-empty list.", {"error": "INVALID_ACTIONS"}
        if data.get("persistence_verified") is not True:
            return False, "QA proof receipt invariant failed: 'persistence_verified' must be True (DOM reload + DB cross-check required).", {"error": "PERSISTENCE_NOT_VERIFIED"}
        if data.get("console_clean") is not True:
            return False, "QA proof receipt invariant failed: 'console_clean' must be True (zero console.error, 0 unhandled exceptions).", {"error": "CONSOLE_NOT_CLEAN"}
        return True, "", {}

    @staticmethod
    def _verify_telemetry(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        if data.get("host_facts_verified") is not True:
            return False, "QA proof verification failed: 'host_facts_verified' must be True.", {"error": "HOST_FACTS_NOT_VERIFIED"}
        db_cc = data.get("db_crosscheck")
        if not isinstance(db_cc, dict) or len(db_cc) == 0:
            return False, "QA proof verification failed: 'db_crosscheck' must be a non-empty dict.", {"error": "MISSING_DB_CROSSCHECK"}
        return True, "", {"db_crosscheck": db_cc}

    @staticmethod
    def _load_receipt_json(proof_path: Path) -> Tuple[bool, Optional[Dict[str, Any]], str, Dict[str, Any]]:
        if not proof_path.is_file():
            return False, None, f"QA verification blocked: missing proof receipt at '{proof_path}'.", {"error": "MISSING_PROOF_RECEIPT"}
        try:
            data = json.loads(proof_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, None, f"QA verification blocked: malformed JSON in proof receipt at '{proof_path}': {exc}", {"error": "MALFORMED_PROOF_RECEIPT"}
        if not isinstance(data, dict):
            return False, None, f"QA verification blocked: proof receipt JSON must be an object at '{proof_path}'.", {"error": "MALFORMED_PROOF_RECEIPT"}
        return True, data, "", {}

    @staticmethod
    def verify_receipt(
        proof_path: Path,
        search_roots: List[Path],
        ticket: Optional[Ticket] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        loaded_ok, data, l_msg, l_det = ProofVerifier._load_receipt_json(proof_path)
        if not loaded_ok or data is None:
            return False, l_msg, l_det

        url_ok, url_msg, url_det = ProofVerifier.verify_urls(data, ticket)
        if not url_ok:
            return False, url_msg, url_det

        flag_ok, flag_msg, flag_det = ProofVerifier._verify_core_flags(data)
        if not flag_ok:
            return False, flag_msg, flag_det

        shot_ok, shot_msg, shot_det = ProofVerifier.verify_screenshots(data.get("screenshot_paths"), search_roots)
        if not shot_ok:
            return False, shot_msg, shot_det

        tel_ok, tel_msg, tel_det = ProofVerifier._verify_telemetry(data)
        if not tel_ok:
            return False, tel_msg, tel_det

        slug = str(data.get("slug") or proof_path.stem)
        return True, f"QA proof receipt verified for '{slug}'.", {
            "slug": slug,
            "visited_urls": data["visited_urls"],
            "user_actions_executed": data["user_actions_executed"],
            "screenshot_paths": data["screenshot_paths"],
            "screenshot_count": len(data["screenshot_paths"]),
            "screenshot_hashes": shot_det["screenshot_hashes"],
            "db_crosscheck": tel_det["db_crosscheck"],
            "persistence_verified": True,
            "console_clean": True,
            "host_facts_verified": True,
        }


def _validate_qa_proof_receipt(
    repo_path: Path,
    work_dir: Path,
    ticket: Ticket,
    scenario_slug: str = "qa_scenario",
) -> Tuple[bool, str, Dict[str, Any]]:
    slug = _resolve_qa_slug(scenario_slug, ticket)

    candidates = [
        work_dir / ".edge" / "qa" / "proofs" / f"{slug}.json",
        repo_path / ".edge" / "qa" / "proofs" / f"{slug}.json",
    ]
    proof_file = _find_proof_file(candidates)

    if not proof_file:
        return (
            False,
            f"QA verification blocked: missing proof receipt at '.edge/qa/proofs/{slug}.json'. "
            "QA_ENGINEER must delegate browser verification to the browser subagent and synthesize the receipt.",
            {"error": "MISSING_PROOF_RECEIPT", "expected_slug": slug},
        )

    search_roots = list(dict.fromkeys([work_dir, repo_path]))
    ok, msg, details = ProofVerifier.verify_receipt(proof_file, search_roots, ticket=ticket)
    if not ok:
        details.setdefault("expected_slug", slug)
        return False, msg, details

    details.setdefault("slug", slug)
    return True, msg, details
