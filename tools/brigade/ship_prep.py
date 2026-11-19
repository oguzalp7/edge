"""
Per-Spec Ship Engine & Specs-to-PR Bridge for Edge Brigade.
Deterministically discovers changed specs between <base>..HEAD, runs scoped
ProofVerifier validation, constructs per-spec SpecShipPlan payloads (lean
2-section PR bodies with ## Summary and ## Evidence), and optionally creates
isolated ship/<spec-slug> branches via --split-branches.
"""

from dataclasses import dataclass, asdict, field
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json
import re
import shlex

try:
    from .models import BrigadeState, Ticket
    from .fsm import ProofVerifier
except ImportError:
    from tools.brigade.models import BrigadeState, Ticket
    from tools.brigade.fsm import ProofVerifier

from tools.common import normalize_target_path, run_command


INDEX_TOKEN_RE = re.compile(r"(@route|@module|@spec|Page:|Action:|Schema:)\s+([^\s|]+)")
BOLD_TERM_RE = re.compile(r"\*\*([^*]+)\*\*")
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")


@dataclass
class IndexChange:
    kind: str       # "@route" | "Page" | "@module" | "Action" | "Schema" | "@spec" | "other"
    symbol: str
    raw_line: str


@dataclass
class SpecDigest:
    path: str
    title: str
    summary: str
    mermaid_blocks: List[str] = field(default_factory=list)
    matrix_rows: List[str] = field(default_factory=list)


@dataclass
class SpecShipPlan:
    spec_slug: str
    spec_path: str
    pr_branch: str
    pr_title: str
    expected_files: List[str] = field(default_factory=list)
    matched_files: List[str] = field(default_factory=list)
    index_changes: List[IndexChange] = field(default_factory=list)
    verified_proofs: List[Dict[str, Any]] = field(default_factory=list)
    failed_proofs: List[Dict[str, Any]] = field(default_factory=list)
    spec_digest: Optional[SpecDigest] = None
    pr_body: str = ""
    show_me_body: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ShipPrepResult:
    base_branch: str
    head_branch: str
    door_type: str
    blast_radius: Dict[str, Any]
    index_changes: List[IndexChange]
    context_terms: List[str]
    specs_linked: List[str]
    verified_proofs: List[Dict[str, Any]]
    failed_proofs: List[Dict[str, Any]]
    examiner_receipt: Optional[Dict[str, Any]]
    intent: str
    scenario_contract: List[str]
    pr_body: str
    show_me_body: str
    spec_digests: List[SpecDigest] = field(default_factory=list)
    spec_plans: List[SpecShipPlan] = field(default_factory=list)
    split_branches_created: List[str] = field(default_factory=list)
    selected_spec: Optional[str] = None


def _clean_slug(raw: str) -> str:
    return (raw or "").strip().lower().replace("_", "-")


def _norm_rel_path(raw: str) -> str:
    norm = raw.replace("\\", "/").strip()
    return norm[2:] if norm.startswith("./") else norm


def _extract_tokens_from_line(line: str) -> List[IndexChange]:
    changes: List[IndexChange] = []
    for match in INDEX_TOKEN_RE.finditer(line):
        kind = match.group(1).rstrip(":")
        symbol = match.group(2).strip()
        if symbol:
            changes.append(IndexChange(kind=kind, symbol=symbol, raw_line=line.strip()))
    return changes


def parse_index_diff(diff_text: str) -> List[IndexChange]:
    """Parses git diff (or raw INDEX.md lines) for @route, Page, @module, Action, Schema, @spec."""
    if not diff_text or not diff_text.strip():
        return []
    is_diff = any(marker in diff_text for marker in ("diff --git", "@@ ", "+++ "))
    changes: List[IndexChange] = []
    for raw in diff_text.splitlines():
        if is_diff:
            if not raw.startswith("+") or raw.startswith("+++"):
                continue
            line = raw[1:]
        else:
            line = raw
        changes.extend(_extract_tokens_from_line(line))
    return changes


def _is_one_way_door_path(norm_path: str) -> bool:
    low = norm_path.lower()
    if low.startswith("drizzle/") or "/drizzle/" in low:
        return True
    if low.startswith("src/db/schema") or "/db/schema/" in low or low.endswith("/db/schema"):
        return True
    return low.endswith(".sql")


_LAYER_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("tests", ("tests/", ".test.", ".spec.")),
    ("api", ("/actions/", "/api/", "src/actions/", "src/app/api/")),
    ("ui", ("/components/", ".tsx", ".jsx", ".css")),
    ("tooling", ("tools/", "skills/", "agents/", "rules/")),
    ("db", ("/db/", "db/")),
)


def _classify_layer(norm_path: str) -> str:
    low = norm_path.lower()
    if _is_one_way_door_path(norm_path):
        return "db"
    for layer, markers in _LAYER_RULES:
        if any(m in low for m in markers):
            return layer
    return "core"


def _extract_domains(norm_files: List[str]) -> List[str]:
    domains: List[str] = []
    for f in norm_files:
        parts = [p for p in f.split("/") if p and p not in ("src", "lib", "app", "tests", "unit")]
        if len(parts) >= 2:
            dom = parts[1] if parts[0] in ("actions", "components", "db", "tools") else parts[0]
            if dom not in domains and "." not in dom:
                domains.append(dom)
    return domains


def _parse_stat_counts(diff_stat: str) -> Tuple[int, int]:
    ins_m = re.search(r"(\d+)\s+insertion", diff_stat or "")
    del_m = re.search(r"(\d+)\s+deletion", diff_stat or "")
    return (int(ins_m.group(1)) if ins_m else 0), (int(del_m.group(1)) if del_m else 0)


def classify_merge_danger(changed_files: List[str], diff_stat: str = "") -> Tuple[str, Dict[str, Any]]:
    """Retained helper for JSON telemetry & backward compatibility (not rendered in PR bodies)."""
    norm_files = [_norm_rel_path(f) for f in changed_files if str(f).strip()]
    one_way_triggers = [f for f in norm_files if _is_one_way_door_path(f)]
    door_type = (
        "One-way door (Database Migration / Schema Change)"
        if one_way_triggers
        else "Two-way door (Reversible Code / Configuration Change)"
    )
    layers = sorted({_classify_layer(f) for f in norm_files})
    ins, dels = _parse_stat_counts(diff_stat)
    blast_radius = {
        "changed_file_count": len(norm_files),
        "changed_files": norm_files,
        "layers": layers,
        "domains": _extract_domains(norm_files),
        "one_way_triggers": one_way_triggers,
        "insertions": ins,
        "deletions": dels,
        "diff_stat": diff_stat.strip(),
    }
    return door_type, blast_radius


def _resolve_base_ref(repo: Path, base_branch: str) -> Optional[str]:
    for cand in (base_branch, f"origin/{base_branch}"):
        code, _, _ = run_command(["git", "rev-parse", "--verify", cand], cwd=repo)
        if code == 0:
            return cand
    return None


def _read_context_terms(repo: Path, search_tokens: List[str]) -> List[str]:
    terms: List[str] = []
    for fname in ("CONTEXT.md", "GLOSSARY.md"):
        fpath = repo / fname
        if not fpath.is_file():
            continue
        for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
            for match in BOLD_TERM_RE.finditer(line):
                term = match.group(1).strip()
                if term and term not in terms:
                    terms.append(term)
    if not search_tokens:
        return terms[:12]
    matched = [t for t in terms if any(tok in t.lower() for tok in search_tokens)]
    return (matched or terms)[:12]


def _is_critique_spec(path_str: str) -> bool:
    low = path_str.strip().lower()
    return "critique" in Path(low).name


def _is_valid_spec_candidate(path_str: str) -> bool:
    norm = _norm_rel_path(path_str)
    low = norm.lower()
    if not low.endswith(".md") or _is_critique_spec(low) or low.endswith("index.md"):
        return False
    return norm.startswith((".edge/specs/", ".edge/archive/specs/", "specs/"))


def _resolve_spec_on_disk(repo: Path, raw_path: str) -> Optional[str]:
    norm = _norm_rel_path(raw_path)
    name = Path(norm).name
    arch = repo / ".edge" / "archive" / "specs" / name
    if arch.is_file():
        return f".edge/archive/specs/{name}"
    active = repo / ".edge" / "specs" / name
    if active.is_file():
        return f".edge/specs/{name}"
    direct = repo / norm
    if direct.is_file():
        return norm
    return None


def discover_changed_specs(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
) -> List[str]:
    """Discovers changed specs between eff_base..HEAD, resolving moved archive paths and deduplicating by slug."""
    _, spec_diff_out, _ = run_command(
        ["git", "diff", "--name-only", f"{eff_base}..HEAD", "--", ".edge/specs/", ".edge/archive/specs/"],
        cwd=repo,
    )
    candidates: List[str] = [line.strip() for line in spec_diff_out.splitlines() if line.strip()]
    candidates.extend(changed_files)
    candidates.extend(ch.symbol for ch in index_changes if ch.kind == "@spec")

    by_slug: Dict[str, str] = {}
    for raw in candidates:
        if not _is_valid_spec_candidate(raw):
            continue
        resolved = _resolve_spec_on_disk(repo, raw)
        if not resolved:
            continue
        slug = _clean_slug(Path(resolved).stem)
        if slug not in by_slug or resolved.startswith(".edge/archive/specs/"):
            by_slug[slug] = resolved
    return list(by_slug.values())


def _extract_spec_title_and_summary(lines: List[str], fallback_title: str) -> Tuple[str, str]:
    title = fallback_title
    summary_lines: List[str] = []
    in_fence = False
    for raw in lines:
        s = raw.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        if s.startswith("# ") and title == fallback_title:
            title = s[2:].strip()
            continue
        if not s.startswith(("#", "|", "---", ">")) and len(summary_lines) < 2:
            summary_lines.append(s)
    return title, " ".join(summary_lines)


def _extract_spec_matrix_rows(lines: List[str], limit: int = 7) -> List[str]:
    rows: List[str] = []
    for raw in lines:
        s = raw.strip()
        if s.startswith("|") and not _TABLE_SEP_RE.match(s):
            rows.append(s)
            if len(rows) >= limit:
                break
    return rows


def parse_spec_document(spec_path: Path, rel_path: str = "") -> SpecDigest:
    """Parses a Markdown specification into title, summary, Mermaid blocks, and matrix rows."""
    eff_rel = rel_path or str(spec_path).replace("\\", "/")
    if not spec_path.is_file():
        return SpecDigest(path=eff_rel, title=spec_path.stem, summary="")
    text = spec_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    title, summary = _extract_spec_title_and_summary(lines, spec_path.stem)
    mermaids = [m.group(1).strip() for m in _MERMAID_BLOCK_RE.finditer(text) if m.group(1).strip()]
    matrix = _extract_spec_matrix_rows(lines)
    return SpecDigest(
        path=eff_rel,
        title=title,
        summary=summary,
        mermaid_blocks=mermaids,
        matrix_rows=matrix,
    )


def _parse_inline_yaml_list(val: str) -> List[str]:
    return [_norm_rel_path(x.strip().strip("'\"`")) for x in val[1:-1].split(",") if x.strip()]


def _read_yaml_block_items(lines: Any) -> List[str]:
    items: List[str] = []
    for sub in lines:
        st = sub.strip()
        if st.startswith("- "):
            val = _norm_rel_path(st[2:].strip().strip("'\"`"))
            if val:
                items.append(val)
        elif st and not st.startswith("#"):
            break
    return items


def _extract_frontmatter_expected(text: str) -> List[str]:
    if not text.startswith("---"):
        return []
    parts = text.split("---", 2)
    if len(parts) < 3:
        return []
    lines = iter(parts[1].splitlines())
    for raw in lines:
        s = raw.strip()
        if not s.startswith("expected_files:"):
            continue
        val = s[len("expected_files:"):].strip()
        if val.startswith("[") and val.endswith("]"):
            return [i for i in _parse_inline_yaml_list(val) if i]
        return _read_yaml_block_items(lines)
    return []


def _parse_bullet_path(line: str) -> Optional[str]:
    if not line.startswith(("- ", "* ")):
        return None
    parts = line[2:].split()
    if not parts:
        return None
    norm = _norm_rel_path(parts[0].strip("`',\""))
    return norm if norm and ("/" in norm or "." in norm) else None


def _extract_section_expected(lines: List[str]) -> List[str]:
    items: List[str] = []
    in_sec = False
    for raw in lines:
        s = raw.strip()
        if re.match(r"^#{2,3}\s+(?:\d+\.\s*)?expected\s+files", s, re.IGNORECASE):
            in_sec = True
            continue
        if in_sec and (s.startswith("#") or s == "---"):
            break
        if in_sec:
            parsed = _parse_bullet_path(s)
            if parsed:
                items.append(parsed)
    return items


def _extract_spec_expected_files(spec_file: Path) -> List[str]:
    if not spec_file.is_file():
        return []
    text = spec_file.read_text(encoding="utf-8", errors="ignore")
    found = _extract_frontmatter_expected(text)
    if not found:
        found = _extract_section_expected(text.splitlines())
    return list(dict.fromkeys(found))


def _load_brigade_snapshot(repo: Path) -> Tuple[Optional[Ticket], Optional[Dict[str, Any]], str]:
    state_file = repo / ".edge" / "brigade.json"
    if not state_file.is_file():
        return None, None, "Not recorded"
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        state = BrigadeState.from_dict(raw)
    except Exception:
        return None, None, "Unreadable .edge/brigade.json"

    receipt_dict = state.examiner_receipt.to_dict() if state.examiner_receipt else None
    gate_status = "No GATE transition logged"
    for entry in reversed(state.history):
        if entry.from_state == "GATE" or entry.to_state == "GATE":
            status_word = "PASSED" if entry.success else "FAILED"
            gate_status = f"{status_word} ({entry.message})"
            break
    return state.active_ticket, receipt_dict, gate_status


def _proof_search_roots(repo: Path, ticket: Optional[Ticket]) -> List[Path]:
    roots = [repo]
    if ticket and ticket.worktree_path:
        wt = normalize_target_path(ticket.worktree_path)
        if wt.is_dir() and wt not in roots:
            roots.insert(0, wt)
    return roots


def _collect_diff_proof_paths(repo: Path, changed_files: List[str]) -> List[Path]:
    found: List[Path] = []
    for cf in changed_files:
        norm = _norm_rel_path(cf)
        is_proof = norm.startswith(".edge/qa/proofs/") and norm.endswith(".json")
        if is_proof and not norm.endswith("-visual.json"):
            cand = repo / norm
            if cand.is_file():
                found.append(cand)
    return found


def _filter_unique_proofs(candidates: List[Path], selected_slug: Optional[str]) -> List[Path]:
    unique: List[Path] = []
    seen_names: set = set()
    for pf in candidates:
        stem_slug = _clean_slug(pf.stem)
        if selected_slug and stem_slug != selected_slug:
            continue
        if pf.name not in seen_names:
            seen_names.add(pf.name)
            unique.append(pf)
    return unique


def _discover_scoped_proof_files(
    repo: Path,
    roots: List[Path],
    spec_slugs: List[str],
    changed_files: List[str],
    selected_slug: Optional[str],
) -> List[Path]:
    """Collects ONLY proof files belonging to changed specs or changed in <base>..HEAD."""
    candidates: List[Path] = []
    for root in roots:
        for slug in spec_slugs:
            cand = root / ".edge" / "qa" / "proofs" / f"{slug}.json"
            if cand.is_file():
                candidates.append(cand)
    candidates.extend(_collect_diff_proof_paths(repo, changed_files))
    return _filter_unique_proofs(candidates, selected_slug)


def _verify_scoped_proofs(
    repo: Path,
    ticket: Optional[Ticket],
    spec_slugs: List[str],
    changed_files: List[str],
    selected_slug: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    roots = _proof_search_roots(repo, ticket)
    proof_files = _discover_scoped_proof_files(repo, roots, spec_slugs, changed_files, selected_slug)
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for pf in proof_files:
        ok, msg, det = ProofVerifier.verify_receipt(pf, roots, ticket=ticket)
        rel = str(pf.relative_to(repo)).replace("\\", "/") if repo in pf.parents else str(pf)
        if ok:
            verified.append({
                "slug": _clean_slug(str(det.get("slug") or pf.stem)),
                "path": rel,
                "visited_urls": det.get("visited_urls", []),
                "user_actions_executed": det.get("user_actions_executed", []),
                "screenshot_paths": det.get("screenshot_paths", []),
                "screenshot_hashes": det.get("screenshot_hashes", {}),
                "db_crosscheck": det.get("db_crosscheck", {}),
                "persistence_verified": True,
                "console_clean": True,
            })
        else:
            failed.append({
                "slug": _clean_slug(pf.stem),
                "path": rel,
                "error": det.get("error", "PROOF_VERIFICATION_FAILED"),
                "message": msg,
                "details": det,
            })
    return verified, failed


def _resolve_intent_targets(
    head_branch: str,
    index_changes: List[IndexChange],
    changed_files: List[str],
) -> List[str]:
    targets = [
        f"{c.kind} {c.symbol}"
        for c in index_changes
        if c.kind in ("@route", "@module", "@spec") and not _is_critique_spec(c.symbol)
    ][:4]
    if targets:
        return targets
    clean_files = [f for f in changed_files if not _is_critique_spec(f)][:3]
    return clean_files or [head_branch or "HEAD"]


def _build_intent_str(
    head_branch: str,
    index_changes: List[IndexChange],
    verified_proofs: List[Dict[str, Any]],
    changed_files: List[str],
    spec_digests: Optional[List[SpecDigest]] = None,
) -> str:
    targets = _resolve_intent_targets(head_branch, index_changes, changed_files)
    spec_items = [f"{Path(d.path).stem}: {d.title}" for d in (spec_digests or [])[:6]]
    spec_part = f" | Specs: {'; '.join(spec_items)}" if spec_items else ""
    proof_slugs = [p["slug"] for p in verified_proofs]
    proof_part = f" | Verified QA proofs: {', '.join(proof_slugs)}" if proof_slugs else ""
    raw_intent = f"Deliver {head_branch or 'slice'} ({', '.join(targets)}){spec_part}{proof_part}"
    return " ".join(raw_intent.split())


def _build_scenario_contract(
    head_branch: str,
    index_changes: List[IndexChange],
    verified_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    changed_files: List[str],
) -> List[str]:
    contract: List[str] = [f"{c.kind}: {c.symbol}" for c in index_changes]
    for p in verified_proofs:
        acts = ", ".join(p.get("user_actions_executed", []))
        urls = ", ".join(p.get("visited_urls", []))
        contract.append(f"QA Proof [{p['slug']}]: actions=[{acts}] urls=[{urls}] db={json.dumps(p.get('db_crosscheck', {}))}")
    if examiner_receipt:
        contract.append(f"Examiner [{examiner_receipt.get('verdict')}]: {examiner_receipt.get('summary')}")
    if contract:
        return contract
    return [f"Changed: {f}" for f in changed_files[:8]] or [f"Branch: {head_branch}"]


def _format_summary_section(
    head_branch: str,
    base_branch: str,
    changed_count: int,
    index_changes: List[IndexChange],
    context_terms: List[str],
    spec_digests: List[SpecDigest],
) -> List[str]:
    lines = [
        "## Summary",
        f"- **Branch:** `{head_branch}` -> `{base_branch}` ({changed_count} file(s) changed)",
    ]
    if index_changes:
        idx_summary = ", ".join(f"`{c.kind} {c.symbol}`" for c in index_changes[:8])
        lines.append(f"- **Navigation Index (`specs/INDEX.md`):** {idx_summary}")
    if context_terms:
        lines.append(f"- **Domain Vocabulary (`CONTEXT.md`):** {', '.join(context_terms)}")
    for digest in spec_digests:
        lines.append(f"- **Spec (`{digest.path}`):** {digest.title}" + (f" — {digest.summary}" if digest.summary else ""))
        for m_block in digest.mermaid_blocks[:2]:
            lines.extend(["```mermaid", m_block, "```"])
    return lines


def _format_evidence_section(
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
) -> List[str]:
    lines = ["", "## Evidence"]
    if specs_linked:
        lines.append(f"- **Specs:** {', '.join(f'`{s}`' for s in specs_linked)}")
    lines.append(f"- **Gate Status:** {gate_status}")
    if examiner_receipt:
        ev = ", ".join(examiner_receipt.get("evidence_reviewed", [])) or "diff"
        lines.append(f"- **Examiner Seal:** `{examiner_receipt.get('verdict')}` — {examiner_receipt.get('summary')} (reviewed: {ev})")
    for p in verified_proofs:
        shots = len(p.get("screenshot_hashes", {}))
        lines.append(
            f"- **QA Proof `{p['slug']}` (Verified):** urls={p['visited_urls']}, "
            f"actions={p['user_actions_executed']}, screenshots={shots} (SHA-256 verified), "
            f"db_crosscheck={json.dumps(p['db_crosscheck'])}"
        )
    for fp in failed_proofs:
        lines.append(f"- **QA Proof `{fp['slug']}` (FAILED - {fp['error']}):** {fp['message']}")
    return lines


def _format_markdown_sections(
    head_branch: str,
    base_branch: str,
    changed_count: int,
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    spec_digests: Optional[List[SpecDigest]] = None,
) -> str:
    """Renders lean 2-section PR body (## Summary + ## Evidence only; no ## Merge Danger)."""
    lines = _format_summary_section(
        head_branch, base_branch, changed_count, index_changes, context_terms, spec_digests or []
    )
    lines.extend(_format_evidence_section(specs_linked, verified_proofs, failed_proofs, examiner_receipt, gate_status))
    return "\n".join(lines)


def _match_expected_files(expected_files: List[str], changed_files: List[str]) -> List[str]:
    matched: List[str] = []
    for cf in changed_files:
        norm_cf = _norm_rel_path(cf)
        if any(fnmatch(norm_cf, pat) or norm_cf == pat for pat in expected_files):
            matched.append(norm_cf)
    return matched


def _filter_plan_index_changes(
    index_changes: List[IndexChange],
    spec_slug: str,
    spec_path: str,
    matched_files: List[str],
) -> List[IndexChange]:
    tokens = {spec_slug, spec_path.lower()}
    tokens.update(Path(mf).stem.lower() for mf in matched_files)
    return [ch for ch in index_changes if any(tok in ch.raw_line.lower() for tok in tokens)]


def _clean_pr_title(spec_slug: str, raw_title: str) -> str:
    cleaned = re.sub(r"^[^\w\s]+\s*", "", raw_title or "").strip()
    cleaned = re.sub(r"^(Edge Brigade Specification|Specification|Spec)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    summary = cleaned or f"deliver {spec_slug}"
    return f"feat({spec_slug}): {summary}"[:96]


def _build_single_spec_plan(
    repo: Path,
    spec_rel: str,
    base_branch: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
) -> SpecShipPlan:
    spec_file = repo / spec_rel
    spec_slug = _clean_slug(spec_file.stem)
    digest = parse_spec_document(spec_file, rel_path=spec_rel)
    expected = _extract_spec_expected_files(spec_file)
    matched = _match_expected_files(expected, changed_files)
    if spec_rel not in matched:
        matched.append(spec_rel)

    plan_v_proofs = [p for p in verified_proofs if p.get("slug") == spec_slug]
    plan_f_proofs = [p for p in failed_proofs if p.get("slug") == spec_slug]
    for vp in plan_v_proofs:
        if vp.get("path") and vp["path"] not in matched:
            matched.append(vp["path"])
        for sp in vp.get("screenshot_paths", []):
            norm_sp = _norm_rel_path(str(sp))
            if norm_sp not in matched:
                matched.append(norm_sp)

    plan_idx = _filter_plan_index_changes(index_changes, spec_slug, spec_rel, matched)
    pr_branch = f"ship/{spec_slug}"
    pr_title = _clean_pr_title(spec_slug, digest.title)
    pr_body = _format_markdown_sections(
        pr_branch, base_branch, len(matched), plan_idx, context_terms,
        [spec_rel], plan_v_proofs, plan_f_proofs, examiner_receipt, gate_status, [digest],
    )
    ship_cmd = (
        f"git push -u origin {shlex.quote(pr_branch)}\n"
        f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(pr_branch)} --title {shlex.quote(pr_title)}"
    )
    show_me_body = f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"
    return SpecShipPlan(
        spec_slug=spec_slug,
        spec_path=spec_rel,
        pr_branch=pr_branch,
        pr_title=pr_title,
        expected_files=expected,
        matched_files=matched,
        index_changes=plan_idx,
        verified_proofs=plan_v_proofs,
        failed_proofs=plan_f_proofs,
        spec_digest=digest,
        pr_body=pr_body,
        show_me_body=show_me_body,
    )


def _collect_plan_tree_files(plan: SpecShipPlan, head_tree: set) -> List[str]:
    candidates: List[str] = [*plan.matched_files, plan.spec_path]
    proof_rel = f".edge/qa/proofs/{plan.spec_slug}.json"
    candidates.append(proof_rel)
    for vp in plan.verified_proofs:
        if vp.get("path"):
            candidates.append(_norm_rel_path(vp["path"]))
        candidates.extend(_norm_rel_path(str(s)) for s in vp.get("screenshot_paths", []))
    ordered: List[str] = []
    for c in candidates:
        norm = _norm_rel_path(c)
        if norm in head_tree and norm not in ordered:
            ordered.append(norm)
    return ordered


def _materialize_single_branch(
    repo: Path,
    eff_base: str,
    head_sha: str,
    head_tree: set,
    plan: SpecShipPlan,
) -> Tuple[bool, str]:
    c_code, _, c_err = run_command(["git", "checkout", "-B", plan.pr_branch, eff_base], cwd=repo)
    if c_code != 0:
        return False, f"Failed to create branch '{plan.pr_branch}': {c_err}"

    files = _collect_plan_tree_files(plan, head_tree)
    if not files:
        return True, ""

    co_code, _, co_err = run_command(["git", "checkout", head_sha, "--", *files], cwd=repo)
    if co_code != 0:
        return False, f"Failed to checkout slice files onto '{plan.pr_branch}': {co_err}"

    add_code, _, add_err = run_command(["git", "add", "--", *files], cwd=repo)
    if add_code != 0:
        return False, f"Failed to stage slice files on '{plan.pr_branch}': {add_err}"

    diff_code, _, _ = run_command(["git", "diff", "--cached", "--quiet"], cwd=repo)
    if diff_code != 0:
        cm_code, _, cm_err = run_command(["git", "commit", "-m", plan.pr_title], cwd=repo)
        if cm_code != 0:
            return False, f"Failed to commit '{plan.pr_branch}': {cm_err}"
    return True, ""


def create_split_branches(
    repo: Path,
    eff_base: str,
    spec_plans: List[SpecShipPlan],
) -> Tuple[bool, List[str], str]:
    """Creates isolated ship/<spec-slug> branches off eff_base, always restoring original HEAD."""
    if not spec_plans:
        return True, [], ""

    st_code, st_out, _ = run_command(["git", "status", "--porcelain"], cwd=repo)
    if st_code != 0 or st_out.strip():
        return False, [], "Working tree must be clean before running --split-branches."

    _, orig_branch, _ = run_command(["git", "branch", "--show-current"], cwd=repo)
    _, head_sha, _ = run_command(["git", "rev-parse", "HEAD"], cwd=repo)
    head_sha = head_sha.strip()
    orig_ref = orig_branch.strip() or head_sha

    ls_code, ls_out, ls_err = run_command(["git", "ls-tree", "-r", "--name-only", head_sha], cwd=repo)
    if ls_code != 0:
        return False, [], f"Failed to inspect HEAD tree: {ls_err}"
    head_tree = {_norm_rel_path(line) for line in ls_out.splitlines() if line.strip()}

    created: List[str] = []
    try:
        for plan in spec_plans:
            ok, err = _materialize_single_branch(repo, eff_base, head_sha, head_tree, plan)
            if not ok:
                return False, created, err
            created.append(plan.pr_branch)
    finally:
        run_command(["git", "checkout", orig_ref], cwd=repo)

    return True, created, ""


def _collect_git_diff_bundle(repo: Path, eff_base: str) -> Tuple[bool, str, List[str], str, str, str]:
    _, head_out, _ = run_command(["git", "branch", "--show-current"], cwd=repo)
    head_branch = head_out.strip() or "HEAD"

    d_code, diff_names_out, diff_err = run_command(["git", "diff", "--name-only", f"{eff_base}..HEAD"], cwd=repo)
    if d_code != 0:
        return False, head_branch, [], "", "", f"Git diff failed: {diff_err}"

    changed_files = [line.strip() for line in diff_names_out.splitlines() if line.strip()]
    _, diff_stat, _ = run_command(["git", "diff", "--stat", f"{eff_base}..HEAD"], cwd=repo)
    _, idx_diff, _ = run_command(["git", "diff", f"{eff_base}..HEAD", "--", "specs/INDEX.md"], cwd=repo)
    if not idx_diff.strip() and (repo / "specs" / "INDEX.md").is_file() and "specs/INDEX.md" in changed_files:
        idx_diff = (repo / "specs" / "INDEX.md").read_text(encoding="utf-8", errors="ignore")
    return True, head_branch, changed_files, diff_stat, idx_diff, ""


def _empty_result(base_branch: str, head_branch: str = "") -> ShipPrepResult:
    return ShipPrepResult(
        base_branch=base_branch,
        head_branch=head_branch,
        door_type="Two-way door (Reversible Code / Configuration Change)",
        blast_radius={"changed_file_count": 0, "changed_files": [], "layers": [], "domains": []},
        index_changes=[],
        context_terms=[],
        specs_linked=[],
        verified_proofs=[],
        failed_proofs=[],
        examiner_receipt=None,
        intent="",
        scenario_contract=[],
        pr_body="",
        show_me_body="",
    )


def _select_spec_plans(
    plans: List[SpecShipPlan],
    spec_slug: Optional[str],
    eff_base: str,
) -> Tuple[bool, List[SpecShipPlan], Optional[str], str]:
    if not spec_slug:
        return True, plans, None, ""
    target = _clean_slug(spec_slug)
    matched = [p for p in plans if p.spec_slug == target]
    if not matched:
        return False, plans, target, f"Spec '{spec_slug}' not found among changed specs in {eff_base}..HEAD."
    return True, matched, target, ""


def _validate_ship_result(
    result: ShipPrepResult,
    strict_proofs: bool,
    split_branches: bool,
    repo: Path,
    eff_base: str,
) -> Tuple[bool, ShipPrepResult, str]:
    if result.failed_proofs:
        return False, result, f"ProofVerifier rejected {len(result.failed_proofs)} QA proof receipt(s)."
    if strict_proofs and not result.verified_proofs and not result.examiner_receipt:
        return False, result, "Strict proofs mode failed: no verified QA proofs or ExaminerReceipt found."
    if split_branches:
        sp_ok, created, sp_err = create_split_branches(repo, eff_base, result.spec_plans)
        result.split_branches_created = created
        if not sp_ok:
            return False, result, sp_err
    return True, result, ""


def prepare_ship_payload(
    repo_path: Path,
    base_branch: str = "staging",
    strict_proofs: bool = False,
    spec_slug: Optional[str] = None,
    split_branches: bool = False,
) -> Tuple[bool, ShipPrepResult, str]:
    """Collects per-spec ship plans, scoped ProofVerifier results, and lean PR bodies."""
    repo = normalize_target_path(repo_path)
    eff_base = _resolve_base_ref(repo, base_branch)
    if not eff_base:
        return False, _empty_result(base_branch), f"Git base branch '{base_branch}' not found in {repo}."

    diff_ok, head_branch, changed_files, diff_stat, idx_diff, diff_err = _collect_git_diff_bundle(repo, eff_base)
    if not diff_ok:
        return False, _empty_result(base_branch, head_branch), diff_err

    index_changes = parse_index_diff(idx_diff)
    door_type, blast_radius = classify_merge_danger(changed_files, diff_stat)
    search_tokens = list(dict.fromkeys([*blast_radius.get("domains", []), *(c.symbol.lower() for c in index_changes)]))
    context_terms = _read_context_terms(repo, search_tokens)

    specs_linked = discover_changed_specs(repo, eff_base, changed_files, index_changes)
    spec_slugs = [_clean_slug(Path(s).stem) for s in specs_linked]
    selected_slug = _clean_slug(spec_slug) if spec_slug else None

    ticket, examiner_receipt, gate_status = _load_brigade_snapshot(repo)
    verified_proofs, failed_proofs = _verify_scoped_proofs(
        repo, ticket, spec_slugs, changed_files, selected_slug=selected_slug
    )

    all_plans = [
        _build_single_spec_plan(
            repo, spec_rel, base_branch, changed_files, index_changes,
            context_terms, verified_proofs, failed_proofs, examiner_receipt, gate_status,
        )
        for spec_rel in specs_linked
    ]
    sel_ok, selected_plans, sel_slug, sel_err = _select_spec_plans(all_plans, spec_slug, eff_base)
    if not sel_ok:
        res_err = _empty_result(base_branch, head_branch)
        res_err.spec_plans = all_plans
        res_err.selected_spec = sel_slug
        return False, res_err, sel_err

    spec_digests = [p.spec_digest for p in selected_plans if p.spec_digest]
    intent = _build_intent_str(head_branch, index_changes, verified_proofs, changed_files, spec_digests=spec_digests)
    scenario_contract = _build_scenario_contract(head_branch, index_changes, verified_proofs, examiner_receipt, changed_files)

    if sel_slug and len(selected_plans) == 1:
        pr_body = selected_plans[0].pr_body
        show_me_body = selected_plans[0].show_me_body
    else:
        pr_body = _format_markdown_sections(
            head_branch, base_branch, len(changed_files), index_changes,
            context_terms, specs_linked, verified_proofs, failed_proofs, examiner_receipt, gate_status, spec_digests,
        )
        ship_cmd = f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(head_branch)}"
        show_me_body = f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"

    result = ShipPrepResult(
        base_branch=base_branch,
        head_branch=head_branch,
        door_type=door_type,
        blast_radius=blast_radius,
        index_changes=index_changes,
        context_terms=context_terms,
        specs_linked=specs_linked,
        verified_proofs=verified_proofs,
        failed_proofs=failed_proofs,
        examiner_receipt=examiner_receipt,
        intent=intent,
        scenario_contract=scenario_contract,
        pr_body=pr_body,
        show_me_body=show_me_body,
        spec_digests=spec_digests,
        spec_plans=selected_plans,
        selected_spec=sel_slug,
    )
    return _validate_ship_result(result, strict_proofs, split_branches, repo, eff_base)


def format_ship_output(result: ShipPrepResult, fmt: str = "pr") -> str:
    """Formats ShipPrepResult as 'pr', 'show-me', or 'json'."""
    if fmt == "show-me":
        return result.show_me_body
    if fmt == "json":
        payload = {
            "base_branch": result.base_branch,
            "head_branch": result.head_branch,
            "intent": result.intent,
            "scenario_contract": result.scenario_contract,
            "pr_body": result.pr_body,
            "show_me_body": result.show_me_body,
            "door_type": result.door_type,
            "blast_radius": result.blast_radius,
            "index_changes": [asdict(c) for c in result.index_changes],
            "context_terms": result.context_terms,
            "specs": result.specs_linked,
            "spec_digests": [asdict(d) for d in result.spec_digests],
            "spec_plans": [p.to_dict() for p in result.spec_plans],
            "split_branches_created": result.split_branches_created,
            "selected_spec": result.selected_spec,
            "verified_proofs": result.verified_proofs,
            "failed_proofs": result.failed_proofs,
            "examiner_receipt": result.examiner_receipt,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return result.pr_body
