"""Tier 2 Route Smoke Scanner, Multi-Framework Discovery & Auto-Triage Engine."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

try:
    from .fsm import BrigadeFSM
    from .models import CycleState, Ticket, TransitionLog
except ImportError:
    from tools.brigade.fsm import BrigadeFSM
    from tools.brigade.models import CycleState, Ticket, TransitionLog


_AUTH_ENTRY_SEGMENTS = {"login", "signin", "signup", "register"}
_PROTECTED_SEGMENTS = {"portal", "admin", "dashboard", "settings", "account", "studio"}
_AUTH_REDIRECT_MARKERS = ("/login", "/signin", "redirect=")
_SKIP_DIRS = {".git", "node_modules", ".next", ".edge", ".svelte-kit", "dist", "build"}
_NEXT_EXTS = (".tsx", ".ts", ".jsx", ".js")
_ASTRO_EXTS = (".astro", ".html")
_INDEX_ROUTE_RE = re.compile(r"@route\s+([^\s|]+)")
_PARAM_BRACKET_RE = re.compile(r"\[\.\.\.([^\]]+)\]|\[([^\]]+)\]")
_PARAM_COLON_RE = re.compile(r":([a-zA-Z0-9_]+)")


@dataclass
class DiscoveredRoute:
    route_pattern: str
    concrete_url_path: str
    source_file: str
    framework: str
    is_dynamic: bool
    requires_auth: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveredRoute":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class RouteSmokeResult:
    route_pattern: str
    url: str
    source_file: str
    http_status: int
    final_url: str
    auth_redirected: bool
    console_errors: List[str] = field(default_factory=list)
    page_errors: List[str] = field(default_factory=list)
    failed_requests: List[str] = field(default_factory=list)
    navigable: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteSmokeResult":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class SmokeScanReport:
    base_url: str
    scanned_at: str
    total_routes: int
    passed_routes: int
    failed_routes: int
    all_navigable: bool
    total_console_errors: int = 0
    total_page_errors: int = 0
    results: List[RouteSmokeResult] = field(default_factory=list)
    triage_tickets_created: List[str] = field(default_factory=list)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["results"] = [r.to_dict() for r in self.results]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SmokeScanReport":
        raw = dict(data)
        raw_results = raw.get("results") or []
        raw["results"] = [
            RouteSmokeResult.from_dict(r) if isinstance(r, dict) else r
            for r in raw_results
        ]
        valid = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


def _write_json_atomic(target: Path, payload: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f"{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, target)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _normalize_route_path(raw: str) -> str:
    clean = "/" + (raw or "").strip().strip("/")
    return re.sub(r"/+", "/", clean)


def _is_auth_entry_route(route_pattern: str) -> bool:
    segs = {s.lower() for s in route_pattern.strip("/").split("/") if s}
    return bool(segs & _AUTH_ENTRY_SEGMENTS)


def _requires_auth_route(route_pattern: str) -> bool:
    if _is_auth_entry_route(route_pattern):
        return False
    segs = {s.lower() for s in route_pattern.strip("/").split("/") if s}
    return bool(segs & _PROTECTED_SEGMENTS)


def _is_dynamic_route(route_pattern: str) -> bool:
    if "[" in route_pattern and "]" in route_pattern:
        return True
    return bool(_PARAM_COLON_RE.search(route_pattern))


def _has_skipped_segment(parts: tuple[str, ...]) -> bool:
    for seg in parts:
        if seg == "api" or seg.startswith("@") or seg.startswith("_"):
            return True
    return False


def _strip_route_groups(parts: tuple[str, ...]) -> List[str]:
    return [seg for seg in parts if not (seg.startswith("(") and seg.endswith(")"))]


def _make_discovered_route(
    route_pattern: str,
    source_file: str,
    framework: str,
    params: Dict[str, str],
    visited_paths: List[str],
) -> DiscoveredRoute:
    norm_pat = _normalize_route_path(route_pattern)
    concrete = _resolve_concrete_url(norm_pat, params, visited_paths)
    return DiscoveredRoute(
        route_pattern=norm_pat,
        concrete_url_path=concrete,
        source_file=source_file,
        framework=framework,
        is_dynamic=_is_dynamic_route(norm_pat),
        requires_auth=_requires_auth_route(norm_pat),
    )


def _discover_nextjs_app(repo_path: Path) -> List[tuple[str, str, str]]:
    found: List[tuple[str, str, str]] = []
    for root_rel in ("src/app", "app"):
        base = repo_path / root_rel
        if not base.is_dir():
            continue
        for fpath in sorted(base.rglob("page.*")):
            if fpath.suffix not in _NEXT_EXTS or not fpath.is_file():
                continue
            parts = fpath.relative_to(base).parts[:-1]
            if _has_skipped_segment(parts):
                continue
            segs = _strip_route_groups(parts)
            pat = "/" + "/".join(segs) if segs else "/"
            found.append((pat, fpath.relative_to(repo_path).as_posix(), "nextjs-app"))
    return found


def _discover_page_files(
    repo_path: Path,
    roots: tuple[str, ...],
    exts: tuple[str, ...],
    framework: str,
) -> List[tuple[str, str, str]]:
    found: List[tuple[str, str, str]] = []
    for root_rel in roots:
        base = repo_path / root_rel
        if not base.is_dir():
            continue
        for fpath in sorted(base.rglob("*")):
            if not fpath.is_file() or fpath.suffix not in exts:
                continue
            rel_parts = fpath.relative_to(base).parts
            if _has_skipped_segment(rel_parts):
                continue
            stem = fpath.stem
            dirs = list(rel_parts[:-1])
            segs = dirs if stem == "index" else [*dirs, stem]
            pat = "/" + "/".join(segs) if segs else "/"
            found.append((pat, fpath.relative_to(repo_path).as_posix(), framework))
    return found


def _discover_sveltekit(repo_path: Path) -> List[tuple[str, str, str]]:
    base = repo_path / "src" / "routes"
    if not base.is_dir():
        return []
    found: List[tuple[str, str, str]] = []
    for fpath in sorted(base.rglob("+page.svelte")):
        if not fpath.is_file():
            continue
        parts = fpath.relative_to(base).parts[:-1]
        if _has_skipped_segment(parts):
            continue
        segs = _strip_route_groups(parts)
        pat = "/" + "/".join(segs) if segs else "/"
        found.append((pat, fpath.relative_to(repo_path).as_posix(), "sveltekit"))
    return found


def _file_to_custom_route(rel_parts: tuple[str, ...], stem: str) -> str:
    trimmed = list(rel_parts)
    for prefix in (("src", "app"), ("src", "routes"), ("src", "pages"), ("app",), ("pages",)):
        if tuple(trimmed[: len(prefix)]) == prefix:
            trimmed = trimmed[len(prefix) :]
            break
    dirs = _strip_route_groups(tuple(trimmed[:-1]))
    segs = dirs if stem in ("page", "+page", "index") else [*dirs, stem]
    return "/" + "/".join(segs) if segs else "/"


def _discover_custom(repo_path: Path, pattern: Optional[str]) -> List[tuple[str, str, str]]:
    if not pattern:
        return []
    found: List[tuple[str, str, str]] = []
    for fpath in sorted(repo_path.glob(pattern)):
        if not fpath.is_file():
            continue
        rel = fpath.relative_to(repo_path)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        pat = _file_to_custom_route(rel.parts, fpath.stem)
        found.append((pat, rel.as_posix(), "custom"))
    return found


def _discover_index_routes(repo_path: Path) -> List[tuple[str, str, str]]:
    index_file = repo_path / "specs" / "INDEX.md"
    if not index_file.is_file():
        return []
    found: List[tuple[str, str, str]] = []
    text = index_file.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        match = _INDEX_ROUTE_RE.search(line)
        if match:
            found.append((match.group(1).strip(), "specs/INDEX.md", "index"))
    return found


def _collect_visited_paths(repo_path: Path) -> List[str]:
    proofs_dir = repo_path / ".edge" / "qa" / "proofs"
    if not proofs_dir.is_dir():
        return []
    paths: List[str] = []
    for pf in sorted(proofs_dir.glob("*.json")):
        if pf.name.endswith("-visual.json"):
            continue
        _append_proof_visited_paths(pf, paths)
    return paths


def _append_proof_visited_paths(proof_file: Path, dest: List[str]) -> None:
    try:
        data = json.loads(proof_file.read_text(encoding="utf-8"))
    except Exception:
        return
    for raw_url in data.get("visited_urls") or []:
        parsed = urlparse(str(raw_url).strip())
        path = _normalize_route_path(parsed.path or "/")
        if path and path not in dest:
            dest.append(path)


def _route_pattern_to_regex(route_pattern: str) -> re.Pattern[str]:
    segs = [s for s in route_pattern.strip("/").split("/") if s]
    if not segs:
        return re.compile(r"^/$")
    parts: List[str] = []
    for seg in segs:
        if seg.startswith("[...") and seg.endswith("]"):
            parts.append(".+")
        elif (seg.startswith("[") and seg.endswith("]")) or seg.startswith(":"):
            parts.append("[^/]+")
        else:
            parts.append(re.escape(seg))
    return re.compile("^/" + "/".join(parts) + "$")


def _apply_explicit_params(route_pattern: str, params: Dict[str, str]) -> str:
    def _sub_bracket(m: re.Match[str]) -> str:
        key = m.group(1) or m.group(2)
        return str(params[key]) if key in params else m.group(0)

    out = _PARAM_BRACKET_RE.sub(_sub_bracket, route_pattern)
    return _PARAM_COLON_RE.sub(lambda m: str(params.get(m.group(1), m.group(0))), out)


def _resolve_concrete_url(
    route_pattern: str,
    params: Dict[str, str],
    visited_paths: List[str],
) -> str:
    resolved = _apply_explicit_params(route_pattern, params)
    if not _is_dynamic_route(resolved):
        return resolved
    matcher = _route_pattern_to_regex(route_pattern)
    for vp in visited_paths:
        if not _is_dynamic_route(vp) and matcher.match(vp):
            return vp
    return resolved


def discover_project_routes(
    repo_path: Path,
    pattern: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
) -> List[DiscoveredRoute]:
    """Discovers routes across Next.js, SvelteKit, Astro, custom globs, and specs/INDEX.md."""
    repo = Path(repo_path)
    param_map = dict(params or {})
    visited_paths = _collect_visited_paths(repo)
    raw_entries: List[tuple[str, str, str]] = []
    raw_entries.extend(_discover_nextjs_app(repo))
    raw_entries.extend(_discover_page_files(repo, ("src/pages", "pages"), _NEXT_EXTS, "nextjs-pages"))
    raw_entries.extend(_discover_sveltekit(repo))
    raw_entries.extend(_discover_page_files(repo, ("src/pages",), _ASTRO_EXTS, "astro"))
    raw_entries.extend(_discover_custom(repo, pattern))
    raw_entries.extend(_discover_index_routes(repo))

    by_pattern: Dict[str, DiscoveredRoute] = {}
    for raw_pat, src, fw in raw_entries:
        norm_pat = _normalize_route_path(raw_pat)
        if norm_pat not in by_pattern:
            by_pattern[norm_pat] = _make_discovered_route(norm_pat, src, fw, param_map, visited_paths)
    return list(by_pattern.values())


def _is_auth_redirected(route_pattern: str, final_url: str) -> bool:
    if _is_auth_entry_route(route_pattern):
        return False
    low = (final_url or "").lower()
    return any(marker in low for marker in _AUTH_REDIRECT_MARKERS)


def _http_fallback_probe(full_url: str, auth_cookie: Optional[str]) -> Dict[str, Any]:
    headers = {"Cookie": auth_cookie} if auth_cookie else {}
    req = urllib.request.Request(full_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return {
                "http_status": int(resp.getcode() or 200),
                "final_url": resp.geturl(),
                "console_errors": [],
                "page_errors": [],
                "failed_requests": [],
            }
    except urllib.error.HTTPError as exc:
        return {
            "http_status": int(exc.code),
            "final_url": exc.geturl(),
            "console_errors": [],
            "page_errors": [f"HTTP {exc.code}: {exc.reason}"],
            "failed_requests": [f"{full_url} -> {exc.code}"],
        }
    except Exception as exc:
        return {
            "http_status": 0,
            "final_url": full_url,
            "console_errors": [],
            "page_errors": [str(exc)],
            "failed_requests": [f"{full_url} -> {exc}"],
        }


def _playwright_node_probe(full_url: str, auth_cookie: Optional[str]) -> Optional[Dict[str, Any]]:
    if not shutil.which("node"):
        return None
    script = (
        "const { chromium } = require('playwright');"
        "(async () => {"
        "  const url = process.argv[1]; const cookie = process.argv[2] || '';"
        "  const browser = await chromium.launch({ headless: true });"
        "  const ctx = await browser.newContext(cookie ? { extraHTTPHeaders: { Cookie: cookie } } : {});"
        "  const page = await ctx.newPage();"
        "  const consoleErrors = []; const pageErrors = []; const failedRequests = [];"
        "  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });"
        "  page.on('pageerror', e => pageErrors.push(String(e)));"
        "  page.on('response', r => { if (r.status() >= 500) failedRequests.push(r.url() + ' -> ' + r.status()); });"
        "  const resp = await page.goto(url, { waitUntil: 'networkidle', timeout: 15000 });"
        "  console.log(JSON.stringify({ http_status: resp ? resp.status() : 0, final_url: page.url(), console_errors: consoleErrors, page_errors: pageErrors, failed_requests: failedRequests }));"
        "  await browser.close();"
        "})().catch(e => { console.error(String(e)); process.exit(2); });"
    )
    try:
        proc = subprocess.run(
            ["node", "-e", script, full_url, auth_cookie or ""],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return None
    return None


def _default_browser_driver(
    route: DiscoveredRoute,
    full_url: str,
    auth_cookie: Optional[str],
) -> Dict[str, Any]:
    pw_res = _playwright_node_probe(full_url, auth_cookie)
    if pw_res is not None:
        return pw_res
    return _http_fallback_probe(full_url, auth_cookie)


def _evaluate_probe_result(
    route: DiscoveredRoute,
    full_url: str,
    raw: Dict[str, Any],
) -> RouteSmokeResult:
    http_status = int(raw.get("http_status", 0) or 0)
    final_url = str(raw.get("final_url") or full_url)
    console_errors = [str(e) for e in (raw.get("console_errors") or [])]
    page_errors = [str(e) for e in (raw.get("page_errors") or [])]
    failed_requests = [str(e) for e in (raw.get("failed_requests") or [])]
    auth_redirected = bool(raw.get("auth_redirected")) or _is_auth_redirected(route.route_pattern, final_url)
    navigable = (
        (200 <= http_status < 400)
        and len(console_errors) == 0
        and len(page_errors) == 0
        and not auth_redirected
    )
    return RouteSmokeResult(
        route_pattern=route.route_pattern,
        url=full_url,
        source_file=route.source_file,
        http_status=http_status,
        final_url=final_url,
        auth_redirected=auth_redirected,
        console_errors=console_errors,
        page_errors=page_errors,
        failed_requests=failed_requests,
        navigable=navigable,
    )


def run_route_smoke_scan(
    repo_path: Path,
    base_url: str = "http://localhost:3000",
    pattern: Optional[str] = None,
    params: Optional[Dict[str, str]] = None,
    auth_cookie: Optional[str] = None,
    out_path: Optional[Path] = None,
    driver_fn: Optional[Callable[[DiscoveredRoute, str, Optional[str]], Dict[str, Any]]] = None,
) -> SmokeScanReport:
    """Scans discovered routes via headless browser or driver_fn and writes .edge/qa/smoke-routes.json."""
    repo = Path(repo_path)
    routes = discover_project_routes(repo, pattern=pattern, params=params)
    probe = driver_fn or _default_browser_driver
    base_clean = base_url.rstrip("/")

    results: List[RouteSmokeResult] = []
    for route in routes:
        full_url = f"{base_clean}{route.concrete_url_path}"
        raw = probe(route, full_url, auth_cookie)
        results.append(_evaluate_probe_result(route, full_url, raw))

    passed = sum(1 for r in results if r.navigable)
    failed = len(results) - passed
    report = SmokeScanReport(
        base_url=base_clean,
        scanned_at=datetime.now(timezone.utc).isoformat(),
        total_routes=len(results),
        passed_routes=passed,
        failed_routes=failed,
        all_navigable=(failed == 0),
        total_console_errors=sum(len(r.console_errors) for r in results),
        total_page_errors=sum(len(r.page_errors) for r in results),
        results=results,
    )
    target = Path(out_path) if out_path else (repo / ".edge" / "qa" / "smoke-routes.json")
    _write_json_atomic(target, report.to_dict())
    return report


def _route_to_slug(route_pattern: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", (route_pattern or "").strip("/")).strip("-")
    return cleaned.upper() if cleaned else "ROOT"


def _build_smoke_fix_hint(res: RouteSmokeResult) -> str:
    if res.auth_redirected:
        return "Verify session/auth cookie handling or public visibility for this route (redirected to login wall)."
    if res.http_status >= 500 or res.http_status == 404 or res.http_status == 0:
        return f"Fix route handler or page resolution returning HTTP {res.http_status} on '{res.route_pattern}'."
    if res.page_errors:
        return f"Fix uncaught runtime / React hydration pageerror on '{res.route_pattern}'."
    return f"Eliminate browser console.error emitted during navigation to '{res.route_pattern}'."


def _build_smoke_ticket(res: RouteSmokeResult) -> Ticket:
    slug = _route_to_slug(res.route_pattern)
    ticket_id = f"TICK-SMOKE-{slug}"
    fingerprint = hashlib.sha256(f"ui:smoke:{res.route_pattern}".encode("utf-8")).hexdigest()[:16]
    desc = (
        f"Route '{res.route_pattern}' ({res.url}) failed smoke navigability: "
        f"http_status={res.http_status}, auth_redirected={res.auth_redirected}, "
        f"console_errors={len(res.console_errors)}, page_errors={len(res.page_errors)}."
    )
    target_file = res.source_file or "specs/INDEX.md"
    return Ticket(
        ticket_id=ticket_id,
        track="ui",
        domain="smoke",
        rule_id="ROUTE_SMOKE_NAVIGABILITY",
        severity="CRITICAL",
        target_file=target_file,
        line_number=1,
        fingerprint=fingerprint,
        description=desc,
        suggested_fix=_build_smoke_fix_hint(res),
        branch_name=f"fix/smoke-{slug.lower()}",
        expected_files=[target_file],
        require_qa=True,
    )


def _ticket_to_ledger_item(ticket: Ticket, res: RouteSmokeResult) -> Dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "track": ticket.track,
        "domain": ticket.domain,
        "rule_id": ticket.rule_id,
        "severity": ticket.severity,
        "file_path": ticket.target_file,
        "line_number": ticket.line_number,
        "fingerprint": ticket.fingerprint,
        "title": f"Smoke failure on {res.route_pattern}",
        "description": ticket.description,
        "suggested_fix": ticket.suggested_fix,
        "route_pattern": res.route_pattern,
        "url": res.url,
        "status": "OPEN",
        "created_at": ticket.created_at,
    }


def _load_ui_ledger_data(ledger_path: Path) -> Dict[str, Any]:
    if not ledger_path.is_file():
        return {"version": "1.0.0", "track": "ui", "items": []}
    try:
        loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {"version": "1.0.0", "track": "ui", "items": []}


def _upsert_ui_ledger(repo: Path, pairs: List[tuple[Ticket, RouteSmokeResult]]) -> None:
    ledger_path = repo / ".edge" / "ledger" / "ui.json"
    data = _load_ui_ledger_data(ledger_path)
    items: List[Dict[str, Any]] = list(data.get("items") or [])
    for ticket, res in pairs:
        entry = _ticket_to_ledger_item(ticket, res)
        idx = next(
            (i for i, it in enumerate(items) if it.get("ticket_id") == ticket.ticket_id or it.get("fingerprint") == ticket.fingerprint),
            None,
        )
        if idx is not None:
            items[idx] = entry
        else:
            items.append(entry)
    data["items"] = items
    _write_json_atomic(ledger_path, data)


def _activate_triage_if_idle(repo: Path, tickets: List[Ticket]) -> None:
    if not tickets:
        return
    fsm = BrigadeFSM(repo)
    if fsm.state.current_state != CycleState.IDLE:
        return
    first = tickets[0]
    fsm.state.active_ticket = first
    fsm.state.active_branch = first.branch_name
    fsm.state.current_state = CycleState.TRIAGE
    fsm.state.history.append(
        TransitionLog(
            from_state=CycleState.IDLE.value,
            to_state=CycleState.TRIAGE.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=True,
            message=f"Auto-triaged smoke failure {first.ticket_id} ({first.target_file}).",
            details={"ticket_id": first.ticket_id, "source": "smoke_routes"},
        )
    )
    fsm.save()


def triage_smoke_failures(repo_path: Path, report: SmokeScanReport) -> List[str]:
    """Creates idempotent CRITICAL UI ledger tickets and activates CycleState.TRIAGE if IDLE."""
    repo = Path(repo_path)
    failing = [r for r in report.results if not r.navigable]
    if not failing:
        return []
    pairs = [(_build_smoke_ticket(res), res) for res in failing]
    tickets = [t for t, _ in pairs]
    _upsert_ui_ledger(repo, pairs)
    _activate_triage_if_idle(repo, tickets)

    created_ids = [t.ticket_id for t in tickets]
    report.triage_tickets_created = created_ids
    _write_json_atomic(repo / ".edge" / "qa" / "smoke-routes.json", report.to_dict())
    return created_ids
