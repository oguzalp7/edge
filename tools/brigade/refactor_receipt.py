"""
Machine-Generated 4-Seal RefactorReceipt & Deterministic Verifier for Edge Brigade.

Pins receipts strictly under target_repo/.edge/receipts/refactor/<slug>.{json,md}
and binds them to (commit_sha, changed_files_hash) so stale gitignored receipts
cannot leak across branches or commits.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from tools.common import normalize_target_path

try:
    from .tasks_bridge import atomic_write_text, resolve_target_repo_root
except ImportError:
    from tools.brigade.tasks_bridge import atomic_write_text, resolve_target_repo_root


LOWER_IS_BETTER_METRICS = frozenset({"db_leaks", "max_cc", "dryer_clones", "sloc"})
HIGHER_IS_BETTER_METRICS = frozenset({"type_score"})


def _norm_rel(path_str: str) -> str:
    norm = str(path_str or "").strip().replace("\\", "/")
    return norm[2:] if norm.startswith("./") else norm


def compute_changed_files_hash(changed_files: List[str]) -> str:
    """Computes deterministic SHA-256 over sorted normalized changed file paths."""
    cleaned = sorted({_norm_rel(f) for f in (changed_files or []) if _norm_rel(f)})
    payload = "\n".join(cleaned).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_neutrality(examiner_cid: Optional[str], surgeon_cid: Optional[str]) -> str:
    """Evaluates whether Examiner and Surgeon are distinct, non-empty station CIDs."""
    ex = str(examiner_cid or "").strip()
    su = str(surgeon_cid or "").strip()
    if not ex or not su:
        return "unverified"
    if ex == su:
        return "violated"
    return "verified"


@dataclass
class RefactorReceipt:
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
            "schema_version": self.schema_version,
            "slug": self.slug,
            "ticket_id": self.ticket_id,
            "track": self.track,
            "seal_1_intent": dict(self.seal_1_intent),
            "seal_2_metrics": dict(self.seal_2_metrics),
            "seal_3_gate": dict(self.seal_3_gate),
            "seal_4_examiner": dict(self.seal_4_examiner),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RefactorReceipt":
        return cls(
            schema_version=str(data.get("schema_version") or "1.0.0"),
            slug=str(data.get("slug") or ""),
            ticket_id=str(data.get("ticket_id") or ""),
            track=str(data.get("track") or "core"),
            seal_1_intent=dict(data.get("seal_1_intent") or {}),
            seal_2_metrics=dict(data.get("seal_2_metrics") or {}),
            seal_3_gate=dict(data.get("seal_3_gate") or {}),
            seal_4_examiner=dict(data.get("seal_4_examiner") or {}),
        )

    def to_markdown(self) -> str:
        s1 = self.seal_1_intent
        s2 = self.seal_2_metrics
        s3 = self.seal_3_gate
        s4 = self.seal_4_examiner
        before = s2.get("before") or {}
        after = s2.get("after") or {}
        targets = s2.get("metric_targets") or {}

        lines = [
            f"# RefactorReceipt: {self.slug}",
            "",
            f"- **Ticket ID:** `{self.ticket_id}`",
            f"- **Track:** `{self.track}`",
            f"- **Commit SHA:** `{s1.get('commit_sha', '')}`",
            f"- **Changed Files Hash:** `{s1.get('changed_files_hash', '')}`",
            f"- **Door Classification:** {s1.get('door_type', '')}",
            f"- **Behavior Preserved:** `{s1.get('behavior_preserved')}`",
            "",
            "## Seal 2 — Before / After Metric Delta",
            "| Metric | Before | Target | After | Delta |",
            "| :--- | ---: | ---: | ---: | ---: |",
        ]
        all_keys = list(dict.fromkeys([*before.keys(), *after.keys(), *targets.keys()]))
        for key in all_keys:
            b_val = before.get(key)
            t_val = targets.get(key)
            a_val = after.get(key)
            delta_str = "—"
            if isinstance(b_val, (int, float)) and isinstance(a_val, (int, float)):
                diff = a_val - b_val
                delta_str = f"{diff:+g}"
            lines.append(
                f"| `{key}` | {b_val if b_val is not None else 'null'} | "
                f"{t_val if t_val is not None else '—'} | "
                f"{a_val if a_val is not None else 'null'} | {delta_str} |"
            )

        lines.extend([
            "",
            "## Seal 3 — Deterministic Gate Proof",
            f"- **All Passed:** `{s3.get('all_passed')}` (`{s3.get('base_branch', '')}`)",
        ])
        for st in s3.get("stages") or []:
            icon = "PASS" if st.get("passed") else "FAIL"
            lines.append(f"- Stage {st.get('stage_num')}: [{icon}] {st.get('name')} — {st.get('message')}")

        lines.extend([
            "",
            "## Seal 4 — Examiner 3-Axis Seal",
            f"- **Verdict:** `{s4.get('verdict', 'PENDING')}`",
            f"- **Neutrality:** `{s4.get('neutrality', 'unverified')}` (Examiner: `{s4.get('examiner_cid')}`, Surgeon: `{s4.get('surgeon_cid')}`)",
            f"- **Summary:** {s4.get('summary', '')}",
            "",
        ])
        return "\n".join(lines)

    def write(self, target_repo: Path) -> Tuple[Path, Path]:
        root = resolve_target_repo_root(target_repo)
        receipts_dir = root / ".edge" / "receipts" / "refactor"
        json_path = receipts_dir / f"{self.slug}.json"
        md_path = receipts_dir / f"{self.slug}.md"
        atomic_write_text(json_path, json.dumps(self.to_dict(), indent=2, ensure_ascii=False))
        atomic_write_text(md_path, self.to_markdown())
        return json_path, md_path


def _run_git(cwd: Path, args: List[str]) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return 1, "", str(exc)


def _get_git_head_sha(work_dir: Path) -> str:
    code, out, _ = _run_git(work_dir, ["rev-parse", "HEAD"])
    return out.strip() if code == 0 and out.strip() else ""


def _get_diff_changed_files(work_dir: Path, base_branch: str) -> List[str]:
    for args in (
        ["diff", "--name-only", f"{base_branch}..HEAD"],
        ["diff", "--name-only", base_branch],
        ["diff", "--name-only", "HEAD~1"],
    ):
        code, out, _ = _run_git(work_dir, args)
        if code == 0:
            files = [_norm_rel(line) for line in out.splitlines() if _norm_rel(line)]
            return [f for f in dict.fromkeys(files) if not f.startswith(".edge/")]
    return []


def _load_ticket_frontmatter(target_repo: Path, slug: str, ticket_path_hint: Optional[str] = None) -> Tuple[Dict[str, Any], str]:
    rel = ticket_path_hint or f".edge/tickets/refactor/{slug}.md"
    cand = target_repo / rel
    if not cand.is_file():
        cand = target_repo / ".edge" / "tickets" / "refactor" / f"{slug}.md"
        rel = f".edge/tickets/refactor/{slug}.md"
    if not cand.is_file():
        return {}, rel
    try:
        text = cand.read_text(encoding="utf-8", errors="ignore")
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) >= 3:
                parsed = yaml.safe_load(parts[1])
                if isinstance(parsed, dict):
                    return parsed, rel
    except Exception:
        pass
    return {}, rel


def _build_seal_4_from_examiner(
    examiner_receipt: Any,
    surgeon_cid: Optional[str],
    default_evidence: List[str],
) -> Dict[str, Any]:
    if examiner_receipt is None:
        return {
            "verdict": "PENDING",
            "examiner_cid": None,
            "surgeon_cid": surgeon_cid,
            "neutrality": "unverified",
            "sealed_at": "",
            "summary": "Awaiting Examiner 3-axis review.",
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


def build_and_write_refactor_receipt(
    target_repo: Path,
    work_dir: Path,
    slug: str,
    base_branch: str,
    ticket: Any = None,
    examiner_receipt: Any = None,
    surgeon_cid: Optional[str] = None,
) -> Tuple[RefactorReceipt, Path, Path]:
    """
    Runs EdgeVerificationGate.run_all_structured in work_dir, classifies door risk,
    synthesizes all 4 seals, and atomically writes <target_repo>/.edge/receipts/refactor/<slug>.{json,md}.
    """
    from tools.gate import EdgeVerificationGate
    from tools.brigade.ship_prep import classify_merge_danger

    root_repo = resolve_target_repo_root(target_repo)
    eff_work_dir = normalize_target_path(work_dir)
    track = getattr(ticket, "track", "core") if ticket else "core"
    ticket_id = getattr(ticket, "ticket_id", f"TICK-{track.upper()[:4]}-{slug.upper()}") if ticket else f"TICK-{track.upper()[:4]}-{slug.upper()}"

    fm, ticket_rel_path = _load_ticket_frontmatter(
        root_repo, slug, getattr(ticket, "refactor_ticket_path", None) if ticket else None
    )

    gate_payload = EdgeVerificationGate(eff_work_dir).run_all_structured(
        base_ref=base_branch,
        is_refactor=True,
        skip_verification=True,
        track=track,
    )
    commit_sha = gate_payload.get("commit_sha") or _get_git_head_sha(eff_work_dir)
    changed_files = _get_diff_changed_files(eff_work_dir, base_branch)
    if not changed_files and ticket and getattr(ticket, "target_file", ""):
        changed_files = [_norm_rel(ticket.target_file)]

    _, diff_stat, _ = _run_git(eff_work_dir, ["diff", "--stat", f"{base_branch}..HEAD"])
    _, diff_text, _ = _run_git(eff_work_dir, ["diff", f"{base_branch}..HEAD"])
    door_type, blast_radius = classify_merge_danger(
        changed_files,
        diff_stat=diff_stat,
        diff_text=diff_text,
        is_refactor=True,
    )

    target_rules = list(fm.get("target_rules") or ([ticket.rule_id] if ticket and ticket.rule_id else []))
    target_files = list(
        fm.get("target_files")
        or (getattr(ticket, "expected_files", None) or ([ticket.target_file] if ticket and ticket.target_file else []))
    )
    metric_targets = dict(
        (getattr(ticket, "metric_targets", None) or {}) if ticket else {}
    )
    if not metric_targets and isinstance(fm.get("metric_targets"), dict):
        metric_targets = dict(fm["metric_targets"])

    tasks_axi_id = getattr(ticket, "tasks_axi_id", None) if ticket else None
    if not tasks_axi_id:
        tasks_axi_id = fm.get("tasks_axi_id")

    before_metrics = dict(getattr(ticket, "before_metrics", None) or {}) if ticket else {}
    after_metrics = dict(gate_payload.get("metrics") or {})

    eff_surgeon_cid = surgeon_cid or (getattr(ticket, "surgeon_cid", None) if ticket else None)
    seal_1 = {
        "ticket_id": ticket_id,
        "slug": slug,
        "track": track,
        "target_rules": target_rules,
        "target_files": target_files,
        "changed_files": list(changed_files),
        "changed_files_hash": compute_changed_files_hash(changed_files),
        "commit_sha": commit_sha,
        "behavior_preserved": True,
        "door_type": door_type,
        "one_way_reasons": list(blast_radius.get("one_way_reasons") or []),
        "ticket_path": ticket_rel_path,
        "tasks_axi_id": tasks_axi_id,
    }
    seal_2 = {
        "before": before_metrics,
        "after": after_metrics,
        "metric_targets": metric_targets,
    }
    seal_3 = {
        "all_passed": bool(gate_payload.get("all_passed")),
        "stages": list(gate_payload.get("stages") or []),
        "commit_sha": commit_sha,
        "base_branch": base_branch,
        "track": track,
    }
    seal_4 = _build_seal_4_from_examiner(examiner_receipt, eff_surgeon_cid, changed_files)

    receipt = RefactorReceipt(
        slug=slug,
        ticket_id=ticket_id,
        track=track,
        seal_1_intent=seal_1,
        seal_2_metrics=seal_2,
        seal_3_gate=seal_3,
        seal_4_examiner=seal_4,
    )
    json_path, md_path = receipt.write(root_repo)
    return receipt, json_path, md_path


def refresh_receipt_examiner_seal(
    target_repo: Path,
    slug: str,
    examiner_receipt: Any,
    surgeon_cid: Optional[str] = None,
) -> Optional[Tuple[RefactorReceipt, Path, Path]]:
    """Refreshes Seal 4 of an existing RefactorReceipt with the sealed ExaminerReceipt."""
    root_repo = resolve_target_repo_root(target_repo)
    json_path = root_repo / ".edge" / "receipts" / "refactor" / f"{slug}.json"
    if not json_path.is_file():
        return None
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        receipt = RefactorReceipt.from_dict(raw)
    except Exception:
        return None

    eff_surgeon = surgeon_cid or receipt.seal_4_examiner.get("surgeon_cid")
    default_ev = list(receipt.seal_1_intent.get("changed_files") or [])
    receipt.seal_4_examiner = _build_seal_4_from_examiner(examiner_receipt, eff_surgeon, default_ev)
    j_path, m_path = receipt.write(root_repo)
    return receipt, j_path, m_path


class RefactorReceiptVerifier:
    """Deterministic validator for 4-seal RefactorReceipts."""

    @staticmethod
    def verify_intent_and_door(
        data: Dict[str, Any],
        repo_path: Optional[Path] = None,
        base_ref: Optional[str] = None,
        work_dir: Optional[Path] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        seal_1 = data.get("seal_1_intent")
        if not isinstance(seal_1, dict):
            return False, "Missing or invalid seal_1_intent.", {"error": "MISSING_SEAL_1"}

        if seal_1.get("behavior_preserved") is not True:
            return False, "Seal 1 failed: behavior_preserved must be True.", {"error": "BEHAVIOR_NOT_PRESERVED"}

        changed_files = seal_1.get("changed_files")
        if not isinstance(changed_files, list):
            return False, "Seal 1 failed: changed_files must be a list.", {"error": "INVALID_CHANGED_FILES"}

        expected_hash = compute_changed_files_hash(changed_files)
        recorded_hash = str(seal_1.get("changed_files_hash") or "")
        if not recorded_hash or recorded_hash != expected_hash:
            return False, "Seal 1 failed: changed_files_hash mismatch (tampered or stale).", {
                "error": "CHANGED_FILES_HASH_MISMATCH",
                "expected_hash": expected_hash,
                "recorded_hash": recorded_hash,
            }

        git_root = work_dir or repo_path
        if git_root is not None:
            git_dir = normalize_target_path(git_root)
            head_sha = _get_git_head_sha(git_dir)
            recorded_sha = str(seal_1.get("commit_sha") or "")
            if head_sha and recorded_sha != head_sha:
                return False, f"Stale receipt: commit_sha '{recorded_sha}' != current HEAD '{head_sha}'.", {
                    "error": "STALE_RECEIPT_COMMIT",
                    "recorded_sha": recorded_sha,
                    "head_sha": head_sha,
                }
            if base_ref:
                cur_files = _get_diff_changed_files(git_dir, base_ref)
                cur_hash = compute_changed_files_hash(cur_files)
                if cur_files and cur_hash != recorded_hash:
                    return False, "Stale receipt: changed_files_hash does not match current branch diff.", {
                        "error": "STALE_RECEIPT_DIFF",
                        "current_hash": cur_hash,
                        "recorded_hash": recorded_hash,
                    }

        return True, "Seal 1 intent and door lock verified.", {"changed_files_hash": recorded_hash}

    @staticmethod
    def verify_metric_delta(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        seal_2 = data.get("seal_2_metrics")
        if not isinstance(seal_2, dict):
            return False, "Missing or invalid seal_2_metrics.", {"error": "MISSING_SEAL_2"}

        after = seal_2.get("after")
        if not isinstance(after, dict):
            return False, "Seal 2 failed: missing 'after' metrics.", {"error": "MISSING_AFTER_METRICS"}

        targets = seal_2.get("metric_targets")
        if targets is None:
            targets = {}
        if not isinstance(targets, dict):
            return False, "Seal 2 failed: metric_targets must be a dict.", {"error": "INVALID_METRIC_TARGETS"}

        for key, target_val in targets.items():
            after_val = after.get(key)
            if after_val is None:
                return False, f"Seal 2 failed: required target metric '{key}' is null/missing.", {
                    "error": "NULL_TARGET_METRIC",
                    "metric": key,
                }
            if not isinstance(after_val, (int, float)) or not isinstance(target_val, (int, float)):
                return False, f"Seal 2 failed: non-numeric value for metric '{key}'.", {
                    "error": "INVALID_METRIC_VALUE",
                    "metric": key,
                }
            if key in HIGHER_IS_BETTER_METRICS:
                if after_val < target_val:
                    return False, f"Seal 2 failed: '{key}'={after_val} is below target {target_val}.", {
                        "error": "METRIC_TARGET_FAILED",
                        "metric": key,
                        "after": after_val,
                        "target": target_val,
                    }
            elif after_val > target_val:
                return False, f"Seal 2 failed: '{key}'={after_val} exceeds target {target_val}.", {
                    "error": "METRIC_TARGET_FAILED",
                    "metric": key,
                    "after": after_val,
                    "target": target_val,
                }

        return True, "Seal 2 metric delta verified.", {"after": after, "metric_targets": targets}

    @staticmethod
    def verify_gate_proof(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        seal_3 = data.get("seal_3_gate")
        if not isinstance(seal_3, dict):
            return False, "Missing or invalid seal_3_gate.", {"error": "MISSING_SEAL_3"}

        if seal_3.get("all_passed") is not True:
            return False, "Seal 3 failed: deterministic gate did not pass (all_passed != True).", {
                "error": "GATE_FAILED",
            }
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
            return False, f"Seal 4 failed: Examiner verdict is '{verdict or 'MISSING'}' (PASS required).", {
                "error": "EXAMINER_NOT_PASS",
                "verdict": verdict,
            }

        examiner_cid = seal_4.get("examiner_cid")
        surgeon_cid = seal_4.get("surgeon_cid")
        computed = compute_neutrality(examiner_cid, surgeon_cid)
        recorded = str(seal_4.get("neutrality") or computed)

        if computed == "violated" or recorded == "violated":
            return False, "Seal 4 failed: neutrality violated (examiner_cid == surgeon_cid).", {
                "error": "NEUTRALITY_VIOLATED",
                "examiner_cid": examiner_cid,
                "surgeon_cid": surgeon_cid,
            }

        if strict and (computed != "verified" or recorded != "verified"):
            return False, f"Seal 4 failed: neutrality is '{computed}' (distinct examiner_cid & surgeon_cid required).", {
                "error": "NEUTRALITY_UNVERIFIED",
                "neutrality": computed,
            }

        return True, "Seal 4 examiner seal verified.", {"neutrality": computed}

    @staticmethod
    def verify_receipt(
        data: Dict[str, Any],
        repo_path: Optional[Path] = None,
        base_ref: Optional[str] = None,
        work_dir: Optional[Path] = None,
        strict: bool = True,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        if not isinstance(data, dict):
            return False, "Invalid receipt payload: expected dict.", {"error": "INVALID_RECEIPT"}

        checks = (
            RefactorReceiptVerifier.verify_intent_and_door(
                data, repo_path=repo_path, base_ref=base_ref, work_dir=work_dir
            ),
            RefactorReceiptVerifier.verify_metric_delta(data),
            RefactorReceiptVerifier.verify_gate_proof(data),
            RefactorReceiptVerifier.verify_examiner_seal(data, strict=strict),
        )
        for ok, msg, details in checks:
            if not ok:
                return False, msg, details

        return True, "All 4 RefactorReceipt seals verified.", {
            "slug": data.get("slug"),
            "ticket_id": data.get("ticket_id"),
        }

    @staticmethod
    def verify_receipt_file(
        receipt_path: Path,
        repo_path: Optional[Path] = None,
        base_ref: Optional[str] = None,
        work_dir: Optional[Path] = None,
        strict: bool = True,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        p = Path(receipt_path)
        if not p.is_file():
            return False, f"RefactorReceipt file not found: {p}", {"error": "MISSING_RECEIPT_FILE"}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"Malformed RefactorReceipt JSON at {p}: {exc}", {"error": "MALFORMED_RECEIPT"}
        return RefactorReceiptVerifier.verify_receipt(
            data, repo_path=repo_path, base_ref=base_ref, work_dir=work_dir, strict=strict
        )
