"""Deterministic 4-Seal RefactorReceipt validator."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from tools.brigade.receipt_models import compute_neutrality
from tools.brigade.receipt_seals import verify_seal_1_intent, verify_seal_2_metrics


class RefactorReceiptVerifier:
    """Deterministic validator for 4-seal RefactorReceipts."""

    @staticmethod
    def verify_intent_and_door(
        data: Dict[str, Any], repo_path: Optional[Path] = None, base_ref: Optional[str] = None, work_dir: Optional[Path] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        return verify_seal_1_intent(data, repo_path=repo_path, base_ref=base_ref, work_dir=work_dir)

    @staticmethod
    def verify_metric_delta(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        return verify_seal_2_metrics(data)

    @staticmethod
    def verify_gate_proof(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        seal_3 = data.get("seal_3_gate")
        if not isinstance(seal_3, dict):
            return False, "Missing or invalid seal_3_gate.", {"error": "MISSING_SEAL_3"}
        if seal_3.get("all_passed") is not True:
            return False, "Seal 3 failed: deterministic gate did not pass (all_passed != True).", {"error": "GATE_FAILED"}
        stages = seal_3.get("stages")
        if not isinstance(stages, list) or not stages:
            return False, "Seal 3 failed: gate stages missing.", {"error": "MISSING_GATE_STAGES"}
        if any(not isinstance(s, dict) or s.get("passed") is not True for s in stages):
            return False, "Seal 3 failed: one or more gate stages failed.", {"error": "GATE_STAGE_FAILED"}
        return True, "Seal 3 gate proof verified.", {"stage_count": len(stages)}

    @staticmethod
    def verify_examiner_seal(data: Dict[str, Any], strict: bool = True) -> Tuple[bool, str, Dict[str, Any]]:
        seal_4 = data.get("seal_4_examiner")
        if not isinstance(seal_4, dict):
            return False, "Missing or invalid seal_4_examiner.", {"error": "MISSING_SEAL_4"}
        verdict = str(seal_4.get("verdict") or "").strip().upper()
        if verdict != "PASS":
            return False, f"Seal 4 failed: Examiner verdict is '{verdict or 'MISSING'}' (PASS required).", {"error": "EXAMINER_NOT_PASS", "verdict": verdict}
        examiner_cid, surgeon_cid = seal_4.get("examiner_cid"), seal_4.get("surgeon_cid")
        computed = compute_neutrality(examiner_cid, surgeon_cid)
        recorded = str(seal_4.get("neutrality") or computed)
        if computed == "violated" or recorded == "violated":
            return False, "Seal 4 failed: neutrality violated (examiner_cid == surgeon_cid).", {"error": "NEUTRALITY_VIOLATED", "examiner_cid": examiner_cid, "surgeon_cid": surgeon_cid}
        if strict and (computed != "verified" or recorded != "verified"):
            return False, f"Seal 4 failed: neutrality is '{computed}' (distinct examiner_cid & surgeon_cid required).", {"error": "NEUTRALITY_UNVERIFIED", "neutrality": computed}
        return True, "Seal 4 examiner seal verified.", {"neutrality": computed}

    @staticmethod
    def verify_receipt(
        data: Dict[str, Any], repo_path: Optional[Path] = None, base_ref: Optional[str] = None, work_dir: Optional[Path] = None, strict: bool = True,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        if not isinstance(data, dict):
            return False, "Invalid receipt payload: expected dict.", {"error": "INVALID_RECEIPT"}
        for ok, msg, details in (
            RefactorReceiptVerifier.verify_intent_and_door(data, repo_path=repo_path, base_ref=base_ref, work_dir=work_dir),
            RefactorReceiptVerifier.verify_metric_delta(data),
            RefactorReceiptVerifier.verify_gate_proof(data),
            RefactorReceiptVerifier.verify_examiner_seal(data, strict=strict),
        ):
            if not ok:
                return False, msg, details
        return True, "All 4 RefactorReceipt seals verified.", {"slug": data.get("slug"), "ticket_id": data.get("ticket_id")}

    @staticmethod
    def verify_receipt_file(
        receipt_path: Path, repo_path: Optional[Path] = None, base_ref: Optional[str] = None, work_dir: Optional[Path] = None, strict: bool = True,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        p = Path(receipt_path)
        if not p.is_file():
            return False, f"RefactorReceipt file not found: {p}", {"error": "MISSING_RECEIPT_FILE"}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"Malformed RefactorReceipt JSON at {p}: {exc}", {"error": "MALFORMED_RECEIPT"}
        return RefactorReceiptVerifier.verify_receipt(data, repo_path=repo_path, base_ref=base_ref, work_dir=work_dir, strict=strict)
