import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from collections import defaultdict

from .models import LedgerItem, ChannelSummary, Track, FindingStatus, FindingSeverity


class LedgerEngine:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.ledger_dir = repo_path / ".edge" / "ledger"
        self.ledger_dir.mkdir(parents=True, exist_ok=True)

    def _channel_file(self, track: str) -> Path:
        return self.ledger_dir / f"{track}.json"

    def load_channel(self, track: str) -> List[LedgerItem]:
        file_path = self._channel_file(track)
        if not file_path.exists():
            return []
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return [LedgerItem.from_dict(item) for item in data.get("items", [])]
        except Exception:
            return []

    def sync_channel(
        self,
        track: str,
        detected_items: List[LedgerItem],
        scanned_files: Optional[List[str]] = None
    ) -> ChannelSummary:
        """
        Idempotently merges newly detected items into the track ledger.
        - Existing open items found again -> updates last_seen_at
        - New items -> added with status=OPEN, first_seen_at=now
        - Items belonging to scanned_files that are NO LONGER detected -> status=RESOLVED
        """
        existing_items = {item.fingerprint: item for item in self.load_channel(track)}
        now_iso = datetime.now(timezone.utc).isoformat()

        # Update or add current detected items
        detected_fps = set()
        for item in detected_items:
            fp = item.fingerprint
            detected_fps.add(fp)
            if fp in existing_items:
                existing = existing_items[fp]
                existing.last_seen_at = now_iso
                existing.details = item.details
                existing.line_number = item.line_number
                # If previously resolved/ignored but reappeared, re-open
                if existing.status == FindingStatus.RESOLVED:
                    existing.status = FindingStatus.OPEN
                    existing.resolved_at = None
            else:
                item.first_seen_at = now_iso
                item.last_seen_at = now_iso
                existing_items[fp] = item

        # Auto-resolve items whose files were scanned but no longer trigger the rule
        if scanned_files:
            scanned_set = set(scanned_files)
            for fp, item in existing_items.items():
                if item.file_path in scanned_set and fp not in detected_fps and item.status == FindingStatus.OPEN:
                    item.status = FindingStatus.RESOLVED
                    item.resolved_at = now_iso

        all_items = list(existing_items.values())

        # Sort: OPEN first (by severity: CRITICAL > WARNING > ADVISORY), then RESOLVED
        sev_rank = {FindingSeverity.CRITICAL: 0, FindingSeverity.WARNING: 1, FindingSeverity.ADVISORY: 2}
        all_items.sort(key=lambda x: (0 if x.status == FindingStatus.OPEN else 1, sev_rank.get(x.severity, 3), x.file_path))

        # Calculate metrics
        open_items = [i for i in all_items if i.status == FindingStatus.OPEN]
        crit_count = sum(1 for i in open_items if i.severity == FindingSeverity.CRITICAL)
        warn_count = sum(1 for i in open_items if i.severity == FindingSeverity.WARNING)
        adv_count = sum(1 for i in open_items if i.severity == FindingSeverity.ADVISORY)
        res_count = sum(1 for i in all_items if i.status == FindingStatus.RESOLVED)

        # Health score: 100 - (crit*6 + warn*2.5 + adv*0.5)
        penalty = (crit_count * 6.0) + (warn_count * 2.5) + (adv_count * 0.5)
        health_score = max(10.0, min(100.0, 100.0 - penalty))

        # Macro pattern detection: group by rule_id
        macro_patterns = self._detect_macro_patterns(open_items)

        summary = ChannelSummary(
            track=track,
            health_score=health_score,
            total_open=len(open_items),
            critical_count=crit_count,
            warning_count=warn_count,
            advisory_count=adv_count,
            resolved_count=res_count,
            macro_patterns=macro_patterns,
            items=all_items,
        )

        # Write channel file
        self._channel_file(track).write_text(json.dumps(summary.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    def _detect_macro_patterns(self, open_items: List[LedgerItem]) -> List[str]:
        """Detects systemic recurring smells across 3+ files."""
        rule_groups = defaultdict(list)
        for item in open_items:
            rule_groups[item.rule_id].append(item.file_path)

        patterns = []
        for rule_id, files in rule_groups.items():
            distinct_files = set(files)
            if len(distinct_files) >= 3:
                patterns.append(
                    f"Macro Pattern [{rule_id}]: {len(distinct_files)} files share this debt. (Candidate for new gate/lint rule or shared primitive)."
                )
        return patterns

    def update_meta_index(self, summaries: Dict[str, ChannelSummary]) -> Dict[str, Any]:
        """Generates unified meta.json dashboard across all channels."""
        now_iso = datetime.now(timezone.utc).isoformat()
        total_open = sum(s.total_open for s in summaries.values())
        avg_health = sum(s.health_score for s in summaries.values()) / max(1, len(summaries))

        meta = {
            "updated_at": now_iso,
            "overall_health_score": round(avg_health, 1),
            "total_open_findings": total_open,
            "channels": {
                k: {
                    "health_score": round(v.health_score, 1),
                    "open": v.total_open,
                    "critical": v.critical_count,
                    "warning": v.warning_count,
                    "macro_patterns_count": len(v.macro_patterns),
                }
                for k, v in summaries.items()
            },
            "systemic_macro_patterns": [p for s in summaries.values() for p in s.macro_patterns],
        }

        (self.ledger_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        return meta
