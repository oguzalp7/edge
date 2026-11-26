"""Atomic cross-project factory inbox persistence and noise pruning."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.distill.inbox_filter import PRUNE_REASONS, classify_prune_reason, compute_signal_fingerprint, match_project_scope
from tools.distill.state_io import _default_factory_inbox_path, _is_ephemeral_test_path, _save_json_atomic


class FactoryInbox:
    """Silent inbox queueing harness signals during PROJECT_MODE runs."""

    def __init__(self, inbox_file_override: Optional[Path] = None):
        if inbox_file_override:
            self.inbox_file = Path(inbox_file_override).resolve()
        else:
            facade = sys.modules.get("tools.distill.state")
            path_fn = getattr(facade, "_default_factory_inbox_path", _default_factory_inbox_path) if facade else _default_factory_inbox_path
            self.inbox_file = path_fn()

    def load_signals(self) -> List[Dict[str, Any]]:
        if not self.inbox_file.exists():
            return []
        try:
            return json.loads(self.inbox_file.read_text(encoding="utf-8")).get("signals", [])
        except Exception:
            return []

    def _build_signal_record(self, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
        kind = str(raw.get("kind", "HARNESS_FRICTION"))
        role_or_tool = str(raw.get("role_or_tool", ""))
        summary = str(raw.get("summary", ""))
        fp = compute_signal_fingerprint(kind, role_or_tool, summary)
        record = {
            "signal_id": raw.get("signal_id") or f"SIG-INBOX-{fp[:8].upper()}",
            "fingerprint": fp,
            "kind": kind,
            "source_project": str(raw.get("source_project", "")),
            "role_or_tool": role_or_tool,
            "summary": summary,
            "created_at": raw.get("created_at") or datetime.now(timezone.utc).isoformat(),
            "resolved": bool(raw.get("resolved", False)),
        }
        return record, fp

    def append_signals(self, raw_signals: List[Dict[str, Any]]) -> int:
        existing = self.load_signals()
        existing_fps = {s.get("fingerprint") for s in existing if s.get("fingerprint")}
        facade = sys.modules.get("tools.distill.state")
        path_fn = getattr(facade, "_default_factory_inbox_path", _default_factory_inbox_path) if facade else _default_factory_inbox_path
        is_prod = hasattr(path_fn, "assert_called") or ("EDGE_DISTILL_FACTORY_INBOX_FILE" not in os.environ)
        is_default_prod = is_prod and (self.inbox_file.resolve() == path_fn().resolve())
        added = 0
        for raw in raw_signals:
            if is_default_prod and _is_ephemeral_test_path(str(raw.get("source_project", ""))):
                continue
            record, fp = self._build_signal_record(raw)
            if fp not in existing_fps:
                existing.append(record)
                existing_fps.add(fp)
                added += 1
        _save_json_atomic(self.inbox_file, {"signals": existing})
        return added

    def load_pending(self) -> List[Dict[str, Any]]:
        return [s for s in self.load_signals() if not s.get("resolved", False)]

    def clear(self) -> None:
        _save_json_atomic(self.inbox_file, {"signals": []})

    def resolve_all(self) -> None:
        signals = self.load_signals()
        for s in signals:
            s["resolved"] = True
        _save_json_atomic(self.inbox_file, {"signals": signals})

    def prune(
        self, drop_exit_zero: bool = True, drop_benign_tools: bool = True, drop_ephemeral: bool = True,
        deduplicate: bool = True, project: Optional[str] = None, resolved_only: bool = False,
        max_age_days: Optional[int] = None, dry_run: bool = False,
    ) -> Dict[str, Any]:
        records, counts = self.load_signals(), {reason: 0 for reason in PRUNE_REASONS}
        opts = {"drop_exit_zero": drop_exit_zero, "drop_benign_tools": drop_benign_tools, "drop_ephemeral": drop_ephemeral, "deduplicate": deduplicate, "resolved_only": resolved_only, "max_age_days": max_age_days}
        now, kept, seen_fps = datetime.now(timezone.utc), [], set()
        for rec in records:
            fp = compute_signal_fingerprint(str(rec.get("kind", "HARNESS_FRICTION")), str(rec.get("role_or_tool", "")), str(rec.get("summary", "")))
            if project is not None and not match_project_scope(str(rec.get("source_project", "")), project):
                kept.append(rec)
                seen_fps.add(fp)
                continue
            reason = classify_prune_reason(rec, fp, seen_fps, opts, now)
            if reason:
                counts[reason] += 1
            else:
                kept.append(rec)
                seen_fps.add(fp)
        removed = len(records) - len(kept)
        if not dry_run and removed > 0:
            _save_json_atomic(self.inbox_file, {"signals": kept})
        return {"before": len(records), "after": len(kept), "removed": removed, "removed_by_reason": counts, "dry_run": dry_run}
