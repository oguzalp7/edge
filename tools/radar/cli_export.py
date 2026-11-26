"""
Ticket export subcommand implementation for Edge Radar CLI.
"""

import re
from pathlib import Path
from typing import Any, Dict, Set

from tools.common import normalize_target_path
from tools.radar.ledger import LedgerEngine
from tools.radar.models import FindingSeverity, FindingStatus


def _derive_item_slug(item: Any) -> str:
    stem = Path(item.file_path).stem.lower()
    rule_short = re.sub(r"^rule-", "", item.rule_id.lower())
    fp_short = (item.fingerprint or "")[:6].lower()
    raw = f"{item.track}-{stem}-{rule_short}-{fp_short}" if fp_short else f"{item.track}-{stem}-{rule_short}"
    return re.sub(r"[^a-z0-9-]+", "-", raw).strip("-")


def _derive_metric_targets(item: Any) -> Dict[str, int]:
    details = item.details if isinstance(item.details, dict) else {}
    rule_upper = (item.rule_id or "").upper()
    if "db_leaks" in details or "DB-LEAK" in rule_upper or "SQL" in rule_upper:
        return {"db_leaks": 0}
    if "max_cc" in details or "CC" in rule_upper or "COMPLEXITY" in rule_upper:
        return {"max_cc": 10}
    if "DUPLICATE" in rule_upper or "DRYER" in rule_upper:
        return {"dryer_clones": 0}
    if rule_upper.startswith("RULE-TS-"):
        return {"type_score": 90}
    return {"max_cc": 10}


def _extract_frontmatter_keys(md_file: Path, existing: Set[str]) -> None:
    try:
        text = md_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    if not text.startswith("---"):
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        return
    fm: Dict[str, Any] = {}
    try:
        import yaml

        parsed = yaml.safe_load(parts[1])
        if isinstance(parsed, dict):
            fm = parsed
    except ImportError:
        for line in parts[1].splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip("'\"")
    except Exception:
        return
    if not isinstance(fm, dict):
        return
    for k in ("slug", "fingerprint"):
        if fm.get(k):
            existing.add(str(fm[k]))


def _load_existing_ticket_fingerprints(tickets_dir: Path) -> Set[str]:
    existing: Set[str] = set()
    if not tickets_dir.is_dir():
        return existing
    for md_file in tickets_dir.glob("*.md"):
        existing.add(md_file.stem)
        _extract_frontmatter_keys(md_file, existing)
    return existing


def cmd_export_tasks(args: Any) -> None:
    from tools.brigade.tasks_bridge import create_refactor_ticket, resolve_target_repo_root

    target_repo = resolve_target_repo_root(normalize_target_path(args.target))
    ledger = LedgerEngine(target_repo)
    tracks = ["core", "ui"] if args.track == "all" else [args.track]
    severity_rank = {
        FindingSeverity.CRITICAL.value: 0,
        FindingSeverity.WARNING.value: 1,
        FindingSeverity.ADVISORY.value: 2,
    }
    open_items = [
        item for trk in tracks for item in ledger.load_channel(trk)
        if item.status == FindingStatus.OPEN.value
    ]
    open_items.sort(key=lambda i: (severity_rank.get(i.severity, 99), i.file_path, i.line_number))

    existing_keys = _load_existing_ticket_fingerprints(target_repo / ".edge" / "tickets" / "refactor")
    exported_count, skipped_count, seen_fps = 0, 0, set()
    top_n = max(0, int(getattr(args, "top", 10)))

    for item in open_items:
        if exported_count >= top_n:
            break
        slug = _derive_item_slug(item)
        if item.fingerprint in seen_fps or item.fingerprint in existing_keys or slug in existing_keys:
            skipped_count += 1
            continue
        seen_fps.add(item.fingerprint)
        existing_keys.add(slug)
        ok, ticket_path, tasks_id = create_refactor_ticket(
            repo_path=target_repo,
            slug=slug,
            track=item.track,
            target_rules=[item.rule_id],
            target_files=[item.file_path],
            metric_targets=_derive_metric_targets(item),
            door_type="two-way",
            sync_tasks=getattr(args, "sync_tasks", None),
            hold_captain=False,
            parent_issue=getattr(args, "parent_issue", None),
            offline=bool(getattr(args, "offline", False)),
        )
        if ok:
            exported_count += 1
            tid_info = f" (#{tasks_id})" if tasks_id else ""
            print(f"✅ Exported {ticket_path}{tid_info}")

    print(f"Export complete: {exported_count} ticket(s) created, {skipped_count} duplicate(s) skipped.")
