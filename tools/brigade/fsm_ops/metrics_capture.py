"""BrigadeFSM mixin: metrics_capture."""

from typing import Tuple, Dict, Any, Optional, List, Set


class FsmMetricsCaptureMixin:
    """Mixin providing metrics_capture operations for BrigadeFSM."""

    def _resolve_station_cid(self, role_name: str) -> Optional[str]:
        st = self.state.stations.get(role_name)
        cid = getattr(st, "conversation_id", None) if st else None
        return str(cid).strip() if cid and str(cid).strip() else None

    def _collect_metric_candidates(self, target_file: str, expected_files: Optional[List[str]]) -> List[str]:
        candidates: List[str] = []
        for raw in [target_file, *(expected_files or [])]:
            norm = str(raw or "").strip().replace("\\", "/")
            norm = norm[2:] if norm.startswith("./") else norm
            if norm and norm not in candidates:
                candidates.append(norm)
        return candidates

    def _capture_before_metrics(self, target_file: str = "", expected_files: Optional[List[str]] = None) -> Dict[str, Any]:
        from tools.gate import (
            EdgeVerificationGate, _PRODUCTION_CODE_SUFFIXES, _compute_source_max_cc,
            _count_sql_leaks, _is_action_controller_path, _is_eligible_prod_path,
        )
        db_leaks, max_cc, sloc, abs_files, ts_abs = 0, 0, 0, [], []
        for rel in self._collect_metric_candidates(target_file, expected_files):
            if not _is_eligible_prod_path(rel, _PRODUCTION_CODE_SUFFIXES, require_src_prefix=False):
                continue
            full_path = self.target_repo / rel
            if not full_path.is_file():
                continue
            abs_files.append(str(full_path.resolve()))
            suffix = full_path.suffix.lower()
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            db_leaks += _count_sql_leaks(content) if _is_action_controller_path(rel) else 0
            max_cc = max(max_cc, _compute_source_max_cc(content, suffix)[0])
            sloc += EdgeVerificationGate._count_source_sloc(content, suffix)
            if suffix in (".ts", ".tsx") and not rel.lower().endswith(".d.ts"):
                ts_abs.append(str(full_path.resolve()))
        type_score: Optional[float] = None
        if ts_abs:
            try:
                from tools.audit.ts_discipline import TsDisciplineAuditor
                type_score = TsDisciplineAuditor(self.target_repo).scan(self.target_repo, scoped_files=ts_abs).overall_score
            except Exception:
                type_score = None
        return {
            "db_leaks": db_leaks, "max_cc": max_cc,
            "dryer_clones": EdgeVerificationGate(self.target_repo)._compute_dryer_clones(abs_files),
            "type_score": type_score, "sloc": sloc,
        }
