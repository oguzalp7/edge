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
import os
import re
import shlex
import subprocess
import tempfile

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
_TICKET_RE = re.compile(r"\b(TICK-[A-Z0-9][A-Z0-9-]*)\b")
_PHASE_TAG_RE = re.compile(r"\((?:polish|gate|qa|red)\)", re.IGNORECASE)
_REPO_PREFIXES: Tuple[str, ...] = (
    "src/", "tools/", "skills/", "agents/", "rules/",
    "tests/", "scripts/", "specs/", "public/", "drizzle/", "prisma/",
)
_INLINE_PATH_RE = re.compile(
    r"((?:src|tools|skills|agents|rules|tests|scripts|specs|public|drizzle|prisma)/[^\s|`'\",;<>]+)"
)


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
    ticket_id: Optional[str] = None
    commit_shas: List[str] = field(default_factory=list)

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


def _read_commit_proof_tickets(repo: Path, sha: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    _, paths_out, _ = run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha, "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    for rel in paths_out.splitlines():
        norm = _norm_rel_path(rel)
        if not norm.endswith(".json") or norm.endswith("-visual.json"):
            continue
        code, blob, _ = run_command(["git", "show", f"{sha}:{norm}"], cwd=repo)
        if code == 0 and blob:
            parsed = _extract_ticket_from_proof_json(blob)
            if parsed:
                found[parsed[0]] = parsed[1]
    return found


def _collect_proof_ticket_map(repo: Path, eff_base: str) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    code, log_out, _ = run_command(
        ["git", "log", "--reverse", "--format=%H", f"{eff_base}..HEAD", "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    if code == 0:
        for sha in log_out.splitlines():
            if sha.strip():
                mapping.update(_read_commit_proof_tickets(repo, sha.strip()))
    proofs_dir = repo / ".edge" / "qa" / "proofs"
    if proofs_dir.is_dir():
        for pf in sorted(proofs_dir.glob("*.json")):
            if pf.name.endswith("-visual.json"):
                continue
            parsed = _extract_ticket_from_proof_json(pf.read_text(encoding="utf-8", errors="ignore"))
            if parsed:
                mapping[parsed[0]] = parsed[1]
    return mapping


def _receipt_matches_spec(rec: Dict[str, Any], spec_rel: str, spec_slug: str) -> bool:
    target_name = Path(spec_rel).name.lower()
    for ev in rec.get("evidence_reviewed", []) or []:
        norm_ev = _norm_rel_path(str(ev))
        if norm_ev == spec_rel or norm_ev.lower().endswith(f"/{target_name}"):
            return True
        if _clean_slug(Path(norm_ev).stem) == spec_slug:
            return True
    return False


def _commit_ticket_file_index(repo: Path, eff_base: str) -> List[Tuple[str, List[str]]]:
    code, out, _ = run_command(["git", "log", "--format=%H%x00%s", f"{eff_base}..HEAD"], cwd=repo)
    if code != 0 or not out.strip():
        return []
    entries: List[Tuple[str, List[str]]] = []
    for line in out.splitlines():
        if "\x00" not in line:
            continue
        sha, subj = line.split("\x00", 1)
        m = _TICKET_RE.search(subj)
        if not m:
            continue
        _, files_out, _ = run_command(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
            cwd=repo,
        )
        entries.append((m.group(1), [_norm_rel_path(f) for f in files_out.splitlines() if f.strip()]))
    return entries


def _match_commit_ticket_for_spec(
    spec_file: Path,
    commit_tickets: List[Tuple[str, List[str]]],
) -> Optional[str]:
    expected = _extract_spec_expected_files(spec_file)
    if not expected:
        return None
    for tid, c_files in commit_tickets:
        if _match_expected_files(expected, c_files):
            return tid
    return None


def _resolve_single_spec_ticket(
    repo: Path,
    spec_rel: str,
    proof_tickets: Dict[str, str],
    history_receipts: Dict[str, Dict[str, Any]],
    commit_tickets: List[Tuple[str, List[str]]],
) -> Optional[str]:
    spec_file = repo / spec_rel
    spec_slug = _clean_slug(spec_file.stem)
    if spec_slug in proof_tickets:
        return proof_tickets[spec_slug]
    for tid, rec in history_receipts.items():
        if _receipt_matches_spec(rec, spec_rel, spec_slug):
            return tid
    if spec_file.is_file():
        m = _TICKET_RE.search(spec_file.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1)
    return _match_commit_ticket_for_spec(spec_file, commit_tickets)


def _resolve_spec_ticket_ids(
    repo: Path,
    eff_base: str,
    spec_paths: List[str],
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Reverse-resolves TICK-* IDs for specs via proof JSON, brigade history, .md text, and git commits."""
    if not spec_paths:
        return {}
    proof_tickets = _collect_proof_ticket_map(repo, eff_base)
    commit_tickets = _commit_ticket_file_index(repo, eff_base)
    hist = history_receipts or {}
    resolved: Dict[str, str] = {}
    for spec_rel in spec_paths:
        tid = _resolve_single_spec_ticket(repo, spec_rel, proof_tickets, hist, commit_tickets)
        if tid:
            resolved[spec_rel] = tid
    return resolved


def _list_disk_spec_candidates(repo: Path) -> List[str]:
    candidates: List[str] = []
    for base_rel in (".edge/specs", ".edge/archive/specs"):
        folder = repo / base_rel
        if not folder.is_dir():
            continue
        for md_file in sorted(folder.glob("*.md")):
            rel = f"{base_rel}/{md_file.name}"
            if _is_valid_spec_candidate(rel):
                candidates.append(rel)
    return candidates


def _ticket_in_history_for_diff(
    tid: Optional[str],
    history_receipts: Dict[str, Dict[str, Any]],
    changed_files: List[str],
) -> bool:
    if not tid or tid not in history_receipts:
        return False
    ev = [str(x) for x in (history_receipts[tid].get("evidence_reviewed") or [])]
    return bool(_match_expected_files(ev, changed_files))


def _spec_matches_diff(
    repo: Path,
    rel: str,
    log_body: str,
    changed_files: List[str],
    ticket_map: Dict[str, str],
    history_receipts: Dict[str, Dict[str, Any]],
) -> bool:
    spec_slug = _clean_slug(Path(rel).stem)
    tid = ticket_map.get(rel)
    if tid and tid in log_body:
        return True
    if spec_slug and spec_slug in log_body.lower():
        return True
    if _ticket_in_history_for_diff(tid, history_receipts, changed_files):
        return True
    expected = _extract_spec_expected_files(repo / rel)
    return bool(expected and _match_expected_files(expected, changed_files))


def _scan_disk_specs_for_diff(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    ticket_map: Dict[str, str],
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Scans gitignored .edge specs on disk and returns those matching eff_base..HEAD."""
    _, log_body, _ = run_command(["git", "log", "--format=%B", f"{eff_base}..HEAD"], cwd=repo)
    hist = history_receipts or {}
    matched: List[str] = []
    for rel in _list_disk_spec_candidates(repo):
        if _spec_matches_diff(repo, rel, log_body, changed_files, ticket_map, hist):
            matched.append(rel)
    return matched


def _deduplicate_spec_candidates(repo: Path, candidates: List[str]) -> List[str]:
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


def discover_changed_specs(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    ticket_map: Optional[Dict[str, str]] = None,
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Discovers changed specs between eff_base..HEAD (git diff + gitignored .edge specs), deduplicated by slug."""
    _, spec_diff_out, _ = run_command(
        ["git", "diff", "--name-only", f"{eff_base}..HEAD", "--", ".edge/specs/", ".edge/archive/specs/"],
        cwd=repo,
    )
    candidates: List[str] = [line.strip() for line in spec_diff_out.splitlines() if line.strip()]
    candidates.extend(changed_files)
    candidates.extend(ch.symbol for ch in index_changes if ch.kind == "@spec")

    eff_hist = history_receipts if history_receipts is not None else _load_brigade_history_snapshot(repo)[3]
    disk_specs = _list_disk_spec_candidates(repo)
    eff_tickets = ticket_map if ticket_map is not None else _resolve_spec_ticket_ids(repo, eff_base, disk_specs, eff_hist)
    candidates.extend(_scan_disk_specs_for_diff(repo, eff_base, changed_files, eff_tickets, eff_hist))
    return _deduplicate_spec_candidates(repo, candidates)


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


def _clean_path_candidate(raw: str) -> Optional[str]:
    cand = _norm_rel_path(raw.strip("`',\";: "))
    if cand.endswith(")") and cand.count(")") > cand.count("("):
        cand = cand[:-1]
    if not cand or " " in cand or "..." in cand:
        return None
    return cand if cand.startswith(_REPO_PREFIXES) else None


def _extract_table_paths(lines: List[str]) -> List[str]:
    """Scans all Markdown table rows and inline code spans for repo-prefixed file paths."""
    found: List[str] = []
    for raw in lines:
        s = raw.strip()
        if not s.startswith("|") or _TABLE_SEP_RE.match(s):
            continue
        spans = re.findall(r"`([^`]+)`", s)
        for tok in [*spans, *_INLINE_PATH_RE.findall(s)]:
            cand = _clean_path_candidate(tok)
            if cand and cand not in found:
                found.append(cand)
    return found


def _expand_expected_globs(patterns: List[str], changed_files: List[str]) -> List[str]:
    """Expands globbed spec patterns (e.g. 0017_*.sql) against changed files."""
    expanded: List[str] = []
    norm_changed = [_norm_rel_path(cf) for cf in changed_files]
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            hits = [cf for cf in norm_changed if fnmatch(cf, pat)]
            expanded.extend(h for h in hits if h not in expanded)
        elif pat not in expanded:
            expanded.append(pat)
    return expanded


def _extract_spec_expected_files(spec_file: Path) -> List[str]:
    if not spec_file.is_file():
        return []
    text = spec_file.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    found = [
        *_extract_frontmatter_expected(text),
        *_extract_section_expected(lines),
        *_extract_table_paths(lines),
    ]
    return list(dict.fromkeys(found))


def _resolve_entry_ticket_id(entry: Any, rec_raw: Dict[str, Any]) -> Optional[str]:
    tid = rec_raw.get("ticket_id") or entry.details.get("ticket_id")
    if tid:
        return str(tid).strip()
    m = _TICKET_RE.search(entry.message or "")
    return m.group(1) if m else None


def _extract_examiner_receipts_by_ticket(state: BrigadeState) -> Dict[str, Dict[str, Any]]:
    """Recovers per-ticket ExaminerReceipt dicts from history entries and active examiner_receipt."""
    receipts: Dict[str, Dict[str, Any]] = {}
    for entry in state.history:
        details = entry.details if isinstance(entry.details, dict) else {}
        rec_raw = details.get("examiner_receipt")
        if not isinstance(rec_raw, dict):
            continue
        tid = _resolve_entry_ticket_id(entry, rec_raw)
        if tid:
            receipts[tid] = dict(rec_raw)
    if state.examiner_receipt:
        rec_dict = state.examiner_receipt.to_dict()
        fallback_tid = state.active_ticket.ticket_id if state.active_ticket else None
        tid = rec_dict.get("ticket_id") or fallback_tid
        if tid:
            receipts[str(tid)] = rec_dict
    return receipts


def _extract_gate_status(state: BrigadeState) -> str:
    for entry in reversed(state.history):
        if entry.from_state == "GATE" or entry.to_state == "GATE":
            status_word = "PASSED" if entry.success else "FAILED"
            return f"{status_word} ({entry.message})"
    return "No GATE transition logged"


def _load_brigade_history_snapshot(
    repo: Path,
) -> Tuple[Optional[Ticket], Optional[Dict[str, Any]], str, Dict[str, Dict[str, Any]]]:
    state_file = repo / ".edge" / "brigade.json"
    if not state_file.is_file():
        return None, None, "Not recorded", {}
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        state = BrigadeState.from_dict(raw)
    except Exception:
        return None, None, "Unreadable .edge/brigade.json", {}

    receipts_by_ticket = _extract_examiner_receipts_by_ticket(state)
    receipt_dict = state.examiner_receipt.to_dict() if state.examiner_receipt else None
    if not receipt_dict and receipts_by_ticket:
        receipt_dict = list(receipts_by_ticket.values())[-1]
    return state.active_ticket, receipt_dict, _extract_gate_status(state), receipts_by_ticket


def _load_brigade_snapshot(repo: Path) -> Tuple[Optional[Ticket], Optional[Dict[str, Any]], str]:
    ticket, receipt_dict, gate_status, _ = _load_brigade_history_snapshot(repo)
    return ticket, receipt_dict, gate_status


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
        if pf.name not in seen_names:
            seen_names.add(pf.name)
            unique.append(pf)
    return unique


def _collect_matching_disk_proofs(
    roots: List[Path],
    spec_slugs: List[str],
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Path]:
    slug_set = set(spec_slugs)
    ticket_set = {v for v in ticket_by_slug.values() if v}
    found: List[Path] = []
    for root in roots:
        proofs_dir = root / ".edge" / "qa" / "proofs"
        if not proofs_dir.is_dir():
            continue
        for pf in sorted(proofs_dir.glob("*.json")):
            if pf.name.endswith("-visual.json"):
                continue
            meta = _parse_proof_raw_meta(pf.read_text(encoding="utf-8", errors="ignore"), pf.name, ticket_by_slug)
            if meta["spec_slug"] in slug_set or (meta["ticket_id"] and meta["ticket_id"] in ticket_set):
                found.append(pf)
    return found


def _discover_scoped_proof_files(
    repo: Path,
    roots: List[Path],
    spec_slugs: List[str],
    changed_files: List[str],
    selected_slug: Optional[str],
    ticket_by_slug: Optional[Dict[str, Optional[str]]] = None,
) -> List[Path]:
    """Collects ONLY proof files belonging to changed specs or changed in <base>..HEAD."""
    candidates: List[Path] = []
    for root in roots:
        for slug in spec_slugs:
            cand = root / ".edge" / "qa" / "proofs" / f"{slug}.json"
            if cand.is_file():
                candidates.append(cand)
    candidates.extend(_collect_diff_proof_paths(repo, changed_files))
    candidates.extend(_collect_matching_disk_proofs(roots, spec_slugs, ticket_by_slug or {}))
    return _filter_unique_proofs(candidates, selected_slug)


def _load_json_dict(raw_text: str) -> Dict[str, Any]:
    try:
        raw = json.loads(raw_text)
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _extract_str_list(val: Any) -> List[str]:
    if not isinstance(val, list):
        return []
    return [str(u) for u in val if isinstance(u, str) and u.strip()]


def _parse_proof_raw_meta(
    raw_text: str,
    rel_path: str,
    ticket_by_slug: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    raw = _load_json_dict(raw_text)
    tid = str(raw.get("ticket_id") or "").strip() or None
    raw_spec = str(raw.get("spec") or "").strip()
    spec_slug = _clean_slug(Path(raw_spec).stem) if raw_spec else ""
    if not spec_slug and tid:
        spec_slug = next((s for s, t in ticket_by_slug.items() if t == tid), "")
    return {
        "spec_slug": spec_slug or _clean_slug(Path(rel_path).stem),
        "ticket_id": tid,
        "screenshot_urls": _extract_str_list(raw.get("screenshot_urls")),
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


def _match_commit_proof_blobs(
    repo: Path,
    sha: str,
    spec_slug: str,
    ticket_id: Optional[str],
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Tuple[str, str]]:
    _, paths_out, _ = run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha, "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    hits: List[Tuple[str, str]] = []
    for rel in paths_out.splitlines():
        norm = _norm_rel_path(rel)
        if not norm.endswith(".json") or norm.endswith("-visual.json"):
            continue
        b_code, raw_text, _ = run_command(["git", "show", f"{sha}:{norm}"], cwd=repo)
        if b_code != 0 or not raw_text.strip():
            continue
        meta = _parse_proof_raw_meta(raw_text, norm, ticket_by_slug)
        if meta["spec_slug"] == spec_slug or (ticket_id and meta["ticket_id"] == ticket_id):
            hits.append((norm, raw_text))
    return hits


def _discover_historical_proof_blobs(
    repo: Path,
    eff_base: str,
    spec_slug: str,
    ticket_id: Optional[str],
    ticket_by_slug: Optional[Dict[str, Optional[str]]] = None,
) -> List[Tuple[str, str]]:
    """Recovers historical proof JSON blobs in eff_base..HEAD matching spec_slug or ticket_id."""
    code, log_out, _ = run_command(
        ["git", "log", "--format=%H", f"{eff_base}..HEAD", "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    if code != 0 or not log_out.strip():
        return []
    t_map = ticket_by_slug or {}
    for sha in log_out.splitlines():
        if not sha.strip():
            continue
        hits = _match_commit_proof_blobs(repo, sha.strip(), spec_slug, ticket_id, t_map)
        if hits:
            return hits
    return []


def _proof_matches_selected(
    entry: Dict[str, Any],
    selected_slug: Optional[str],
    t_map: Dict[str, Optional[str]],
) -> bool:
    if not selected_slug:
        return True
    if entry.get("spec_slug") == selected_slug or entry.get("slug") == selected_slug:
        return True
    sel_tid = t_map.get(selected_slug)
    return bool(sel_tid and entry.get("ticket_id") == sel_tid)


def _verify_disk_proofs(
    repo: Path,
    roots: List[Path],
    ticket: Optional[Ticket],
    proof_files: List[Path],
    selected_slug: Optional[str],
    t_map: Dict[str, Optional[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for pf in proof_files:
        rel = str(pf.relative_to(repo)).replace("\\", "/") if repo in pf.parents else str(pf)
        raw_text = pf.read_text(encoding="utf-8", errors="ignore")
        ok, entry = _verify_proof_raw_text(raw_text, rel, roots, ticket, t_map)
        if not _proof_matches_selected(entry, selected_slug, t_map):
            continue
        (verified if ok else failed).append(entry)
    return verified, failed


def _verify_scoped_proofs(
    repo: Path,
    ticket: Optional[Ticket],
    spec_slugs: List[str],
    changed_files: List[str],
    selected_slug: Optional[str] = None,
    eff_base: Optional[str] = None,
    ticket_by_slug: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    roots = _proof_search_roots(repo, ticket)
    t_map = ticket_by_slug or {}
    proof_files = _discover_scoped_proof_files(repo, roots, spec_slugs, changed_files, selected_slug, ticket_by_slug=t_map)
    verified, failed = _verify_disk_proofs(repo, roots, ticket, proof_files, selected_slug, t_map)
    if not eff_base:
        return verified, failed

    covered_slugs = {e.get("spec_slug") for e in verified}
    target_slugs = [selected_slug] if selected_slug else list(spec_slugs)
    for slug in target_slugs:
        if not slug or slug in covered_slugs:
            continue
        for rel_path, raw_text in _discover_historical_proof_blobs(repo, eff_base, slug, t_map.get(slug), t_map):
            ok, entry = _verify_proof_raw_text(raw_text, rel_path, roots, ticket, t_map)
            (verified if ok else failed).append(entry)
            covered_slugs.add(slug)
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
        for url in p.get("screenshot_urls", []) or []:
            fname = Path(str(url).split("?")[0]).name or "screenshot.png"
            lines.append(f"  - ![{fname}]({url})")
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


def _proof_belongs_to_plan(
    proof: Dict[str, Any],
    spec_slug: str,
    ticket_id: Optional[str],
) -> bool:
    if proof.get("spec_slug") == spec_slug:
        return True
    if ticket_id and proof.get("ticket_id") == ticket_id:
        return True
    return not proof.get("spec_slug") and proof.get("slug") == spec_slug


def _resolve_active_receipt(
    plan_ticket_id: Optional[str],
    spec_slug: str,
    spec_rel: str,
    examiner_receipt: Optional[Dict[str, Any]],
    total_plans: int,
) -> Optional[Dict[str, Any]]:
    if not examiner_receipt:
        return None
    rec_tid = examiner_receipt.get("ticket_id")
    if rec_tid:
        return examiner_receipt if rec_tid == plan_ticket_id else None
    if total_plans == 1 or _receipt_matches_spec(examiner_receipt, spec_rel, spec_slug):
        return examiner_receipt
    return None


def _resolve_plan_receipt(
    plan_ticket_id: Optional[str],
    spec_slug: str,
    spec_rel: str,
    examiner_receipt: Optional[Dict[str, Any]],
    receipts_by_ticket: Dict[str, Dict[str, Any]],
    total_plans: int,
) -> Optional[Dict[str, Any]]:
    if plan_ticket_id and plan_ticket_id in receipts_by_ticket:
        return receipts_by_ticket[plan_ticket_id]
    active = _resolve_active_receipt(plan_ticket_id, spec_slug, spec_rel, examiner_receipt, total_plans)
    if active:
        return active
    if total_plans == 1 and receipts_by_ticket:
        return list(receipts_by_ticket.values())[-1]
    return None


def _append_proof_matched_files(matched: List[str], proofs: List[Dict[str, Any]]) -> None:
    for vp in proofs:
        if vp.get("path") and vp["path"] not in matched:
            matched.append(vp["path"])
        for sp in vp.get("screenshot_paths", []):
            norm_sp = _norm_rel_path(str(sp))
            if norm_sp not in matched:
                matched.append(norm_sp)


def _render_plan_bodies(
    plan: SpecShipPlan,
    base_branch: str,
    context_terms: List[str],
    plan_receipt: Optional[Dict[str, Any]],
    gate_status: str,
) -> None:
    digests = [plan.spec_digest] if plan.spec_digest else []
    pr_body = _format_markdown_sections(
        plan.pr_branch, base_branch, len(plan.matched_files), plan.index_changes,
        context_terms, [plan.spec_path], plan.verified_proofs, plan.failed_proofs,
        plan_receipt, gate_status, digests,
    )
    ship_cmd = (
        f"git push -u origin {shlex.quote(plan.pr_branch)}\n"
        f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(plan.pr_branch)} --title {shlex.quote(plan.pr_title)}"
    )
    plan.pr_body = pr_body
    plan.show_me_body = f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"


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
    ticket_id: Optional[str] = None,
) -> SpecShipPlan:
    spec_file = repo / spec_rel
    spec_slug = _clean_slug(spec_file.stem)
    digest = parse_spec_document(spec_file, rel_path=spec_rel)
    expected = _extract_spec_expected_files(spec_file)
    matched = _match_expected_files(_expand_expected_globs(expected, changed_files), changed_files)
    if spec_rel not in matched:
        matched.append(spec_rel)

    plan_v_proofs = [p for p in verified_proofs if _proof_belongs_to_plan(p, spec_slug, ticket_id)]
    plan_f_proofs = [p for p in failed_proofs if _proof_belongs_to_plan(p, spec_slug, ticket_id)]
    _append_proof_matched_files(matched, plan_v_proofs)

    plan = SpecShipPlan(
        spec_slug=spec_slug,
        spec_path=spec_rel,
        pr_branch=f"ship/{spec_slug}",
        pr_title=_clean_pr_title(spec_slug, digest.title),
        expected_files=expected,
        matched_files=matched,
        index_changes=_filter_plan_index_changes(index_changes, spec_slug, spec_rel, matched),
        verified_proofs=plan_v_proofs,
        failed_proofs=plan_f_proofs,
        spec_digest=digest,
        ticket_id=ticket_id,
    )
    _render_plan_bodies(plan, base_branch, context_terms, examiner_receipt, gate_status)
    return plan


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


def _list_range_commits(repo: Path, eff_base: str) -> List[Tuple[str, str, List[str]]]:
    code, out, _ = run_command(["git", "log", "--reverse", "--format=%H%x00%s", f"{eff_base}..HEAD"], cwd=repo)
    if code != 0 or not out.strip():
        return []
    commits: List[Tuple[str, str, List[str]]] = []
    for line in out.splitlines():
        if "\x00" not in line:
            continue
        sha, subj = line.split("\x00", 1)
        _, f_out, _ = run_command(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
            cwd=repo,
        )
        c_files = [_norm_rel_path(f) for f in f_out.splitlines() if f.strip()]
        commits.append((sha.strip(), subj.strip(), c_files))
    return commits


def _explicit_commit_owners(
    subject: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> List[str]:
    low_subj = subject.lower()
    owners: List[str] = []
    for p in plans:
        tid = p.ticket_id or ticket_map.get(p.spec_path)
        slug_hit = bool(re.search(rf"(?<![a-z0-9-]){re.escape(p.spec_slug)}(?![a-z0-9-])", low_subj))
        if (tid and tid in subject) or slug_hit:
            owners.append(p.spec_slug)
    return owners


def _overlap_commit_owners(c_files: List[str], plans: List[SpecShipPlan]) -> List[str]:
    owners: List[str] = []
    for p in plans:
        if p.expected_files and _match_expected_files(p.expected_files, c_files):
            owners.append(p.spec_slug)
    return owners


def _match_commit_owners(
    subject: str,
    c_files: List[str],
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
    last_owner: Optional[str],
) -> List[str]:
    explicit = _explicit_commit_owners(subject, plans, ticket_map)
    if explicit:
        return explicit
    overlap = _overlap_commit_owners(c_files, plans)
    if overlap:
        return overlap
    if last_owner:
        return [last_owner]
    return [plans[0].spec_slug] if len(plans) == 1 else []


def _resolve_spec_commits(
    repo: Path,
    eff_base: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> Tuple[Dict[str, List[str]], Dict[str, bool], Dict[str, List[str]]]:
    """Attributes eff_base..HEAD commits per spec (ticket/slug, phase tags, file overlap, contiguous slice)."""
    exclusive: Dict[str, List[str]] = {p.spec_slug: [] for p in plans}
    has_shared: Dict[str, bool] = {p.spec_slug: False for p in plans}
    exc_files: Dict[str, List[str]] = {p.spec_slug: [] for p in plans}
    last_owner: Optional[str] = None
    for sha, subj, c_files in _list_range_commits(repo, eff_base):
        owners = _match_commit_owners(subj, c_files, plans, ticket_map, last_owner)
        if len(owners) == 1:
            slug = owners[0]
            exclusive[slug].append(sha)
            exc_files[slug].extend(f for f in c_files if f not in exc_files[slug])
            last_owner = slug
        else:
            for slug in owners:
                has_shared[slug] = True
            last_owner = None
    return exclusive, has_shared, exc_files


def _apply_slice_commits_to_plans(
    plans: List[SpecShipPlan],
    exclusive: Dict[str, List[str]],
    has_shared: Dict[str, bool],
    exc_files: Dict[str, List[str]],
    index_changes: List[IndexChange],
) -> None:
    for plan in plans:
        if not has_shared.get(plan.spec_slug):
            plan.commit_shas = list(exclusive.get(plan.spec_slug, []))
        for cf in exc_files.get(plan.spec_slug, []):
            if not cf.startswith(".edge/") and cf not in plan.matched_files:
                plan.matched_files.append(cf)
        plan.index_changes = _filter_plan_index_changes(
            index_changes, plan.spec_slug, plan.spec_path, plan.matched_files
        )


def _resolve_du_edge_conflicts(repo: Path, sha: str) -> bool:
    """Resolves modify/delete (DU) conflicts solely on .edge/ artifacts overwritten across slices."""
    _, st_out, _ = run_command(["git", "status", "--porcelain"], cwd=repo)
    du_edge: List[str] = []
    conflict_codes = {"UU", "AA", "DD", "DU", "UD", "AU", "UA"}
    for line in st_out.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], _norm_rel_path(line[3:].strip().strip('"'))
        if code == "DU" and path.startswith(".edge/"):
            du_edge.append(path)
        elif code in conflict_codes:
            return False
    if not du_edge:
        return False
    cmds = (
        ["git", "checkout", sha, "--", *du_edge],
        ["git", "add", "--", *du_edge],
        ["git", "commit", "--no-edit"],
    )
    return all(run_command(c, cwd=repo)[0] == 0 for c in cmds)


def _cherry_pick_slice_commits(
    repo: Path,
    pr_branch: str,
    eff_base: str,
    commit_shas: List[str],
) -> Tuple[bool, str]:
    c_code, _, c_err = run_command(["git", "checkout", "-B", pr_branch, eff_base], cwd=repo)
    if c_code != 0:
        return False, f"Failed to create branch '{pr_branch}': {c_err}"
    for sha in commit_shas:
        cp_code, cp_out, cp_err = run_command(
            ["git", "cherry-pick", "-X", "theirs", sha],
            cwd=repo,
        )
        if cp_code == 0:
            continue
        combined = f"{cp_out}\n{cp_err}".lower()
        if "nothing to commit" in combined or "previous cherry-pick is now empty" in combined:
            run_command(["git", "cherry-pick", "--skip"], cwd=repo)
            continue
        if _resolve_du_edge_conflicts(repo, sha):
            continue
        run_command(["git", "cherry-pick", "--abort"], cwd=repo)
        return False, f"Failed to cherry-pick {sha[:8]} onto '{pr_branch}': {cp_err or cp_out}"
    return True, ""


def _materialize_checkout_files(
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


def _materialize_single_branch(
    repo: Path,
    eff_base: str,
    head_sha: str,
    head_tree: set,
    plan: SpecShipPlan,
    exclusive_commits: Optional[List[str]] = None,
    has_shared_commits: bool = False,
) -> Tuple[bool, str]:
    slice_shas = exclusive_commits if exclusive_commits is not None else plan.commit_shas
    if slice_shas and not has_shared_commits:
        return _cherry_pick_slice_commits(repo, plan.pr_branch, eff_base, slice_shas)
    return _materialize_checkout_files(repo, eff_base, head_sha, head_tree, plan)


def create_split_branches(
    repo: Path,
    eff_base: str,
    spec_plans: List[SpecShipPlan],
    ticket_map: Optional[Dict[str, str]] = None,
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
    exclusive, has_shared, _ = _resolve_spec_commits(repo, eff_base, spec_plans, ticket_map or {})

    created: List[str] = []
    try:
        for plan in spec_plans:
            ok, err = _materialize_single_branch(
                repo, eff_base, head_sha, head_tree, plan,
                exclusive_commits=exclusive.get(plan.spec_slug, []),
                has_shared_commits=has_shared.get(plan.spec_slug, False),
            )
            if not ok:
                return False, created, err
            created.append(plan.pr_branch)
    finally:
        run_command(["git", "checkout", orig_ref], cwd=repo)

    return True, created, ""


def parse_github_owner_repo(remote_url: str) -> Optional[Tuple[str, str]]:
    """Extracts (owner, repo) from SSH or HTTPS GitHub remote URLs."""
    raw = (remote_url or "").strip()
    m = re.match(
        r"^(?:https?://github\.com/|ssh://git@github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?/?$",
        raw,
    )
    if not m:
        return None
    return m.group(1), m.group(2)


def _run_git_with_env(repo: Path, args: List[str], env: Dict[str, str]) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return 1, "", str(exc)


def _seed_evidence_parent_tree(
    repo: Path,
    evidence_branch: str,
    env: Dict[str, str],
) -> Optional[str]:
    """Resolves local/remote evidence branch head and seeds temp GIT_INDEX_FILE via git read-tree."""
    l_code, l_sha, _ = run_command(["git", "rev-parse", "--verify", f"refs/heads/{evidence_branch}"], cwd=repo)
    parent_sha = l_sha.strip() if l_code == 0 and l_sha.strip() else None
    if not parent_sha:
        run_command(
            ["git", "fetch", "origin", f"refs/heads/{evidence_branch}:refs/remotes/origin/{evidence_branch}"],
            cwd=repo,
        )
        r_code, r_sha, _ = run_command(
            ["git", "rev-parse", "--verify", f"refs/remotes/origin/{evidence_branch}"],
            cwd=repo,
        )
        parent_sha = r_sha.strip() if r_code == 0 and r_sha.strip() else None
    if parent_sha:
        _run_git_with_env(repo, ["read-tree", parent_sha], env)
    return parent_sha


def _resolve_single_shot(raw_sp: str, search_roots: List[Path], repo: Path) -> Optional[Path]:
    resolved = ProofVerifier.resolve_screenshot_file(raw_sp, search_roots)
    if resolved and resolved.is_file():
        return resolved
    cand = repo / _norm_rel_path(raw_sp)
    return cand if cand.is_file() else None


def _collect_evidence_shots(
    repo: Path,
    spec_plans: List[SpecShipPlan],
    search_roots: List[Path],
) -> List[Tuple[Dict[str, Any], Path, str]]:
    shots: List[Tuple[Dict[str, Any], Path, str]] = []
    for plan in spec_plans:
        for proof in plan.verified_proofs:
            for raw_sp in proof.get("screenshot_paths", []) or []:
                resolved = _resolve_single_shot(str(raw_sp), search_roots, repo)
                if resolved:
                    stage_path = f"evidence/{plan.spec_slug}/{resolved.name}"
                    shots.append((proof, resolved, stage_path))
    return shots


def _stage_evidence_blobs(
    repo: Path,
    shots: List[Tuple[Dict[str, Any], Path, str]],
    env: Dict[str, str],
) -> Tuple[bool, str]:
    for _, resolved, stage_path in shots:
        h_code, blob_sha, h_err = run_command(["git", "hash-object", "-w", "--", str(resolved)], cwd=repo)
        if h_code != 0:
            return False, f"Failed to hash screenshot '{resolved}': {h_err}"
        u_code, _, u_err = _run_git_with_env(
            repo,
            ["update-index", "--add", "--cacheinfo", f"100644,{blob_sha.strip()},{stage_path}"],
            env,
        )
        if u_code != 0:
            return False, f"Failed to stage evidence '{stage_path}': {u_err}"
    return True, ""


def _commit_and_push_evidence(
    repo: Path,
    evidence_branch: str,
    parent_sha: Optional[str],
    env: Dict[str, str],
    slugs: List[str],
) -> Tuple[bool, str, str]:
    w_code, tree_sha, w_err = _run_git_with_env(repo, ["write-tree"], env)
    if w_code != 0:
        return False, "", f"Failed to write evidence tree: {w_err}"
    args = ["commit-tree", tree_sha.strip()]
    if parent_sha:
        args.extend(["-p", parent_sha])
    args.extend(["-m", f"chore(qa-evidence): publish {', '.join(slugs)}"])
    c_code, c_sha, c_err = run_command(["git", *args], cwd=repo)
    if c_code != 0:
        return False, "", f"Failed to commit evidence tree: {c_err}"
    commit_sha = c_sha.strip()
    run_command(["git", "update-ref", f"refs/heads/{evidence_branch}", commit_sha], cwd=repo)
    p_code, _, p_err = run_command(["git", "push", "origin", f"refs/heads/{evidence_branch}"], cwd=repo)
    if p_code != 0:
        return False, commit_sha, f"Failed to push '{evidence_branch}' to origin: {p_err}"
    return True, commit_sha, ""


def publish_screenshots_to_evidence_branch(
    repo: Path,
    evidence_branch: str,
    spec_plans: List[SpecShipPlan],
    search_roots: List[Path],
) -> Tuple[bool, str]:
    """Publishes QA screenshots onto an orphan branch without switching HEAD and binds permanent GitHub URLs."""
    r_code, remote_url, r_err = run_command(["git", "remote", "get-url", "origin"], cwd=repo)
    if r_code != 0 or not remote_url.strip():
        return False, f"Cannot publish evidence: missing git remote 'origin' ({r_err})."
    parsed = parse_github_owner_repo(remote_url.strip())
    if not parsed:
        return False, f"Cannot publish evidence: origin remote '{remote_url.strip()}' is not GitHub."
    owner, repo_name = parsed

    shots = _collect_evidence_shots(repo, spec_plans, search_roots)
    if not shots:
        return True, ""

    with tempfile.TemporaryDirectory() as tmp_dir:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp_dir) / "git_index")}
        parent_sha = _seed_evidence_parent_tree(repo, evidence_branch, env)
        st_ok, st_err = _stage_evidence_blobs(repo, shots, env)
        if not st_ok:
            return False, st_err
        slugs = [p.spec_slug for p in spec_plans]
        cm_ok, commit_sha, cm_err = _commit_and_push_evidence(repo, evidence_branch, parent_sha, env, slugs)
        if not cm_ok:
            return False, cm_err

    for proof, _, stage_path in shots:
        raw_url = f"https://github.com/{owner}/{repo_name}/blob/{commit_sha}/{stage_path}?raw=true"
        urls = proof.setdefault("screenshot_urls", [])
        if raw_url not in urls:
            urls.append(raw_url)
    return True, ""


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


def _render_top_level_bodies(
    sel_slug: Optional[str],
    selected_plans: List[SpecShipPlan],
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
    spec_digests: List[SpecDigest],
) -> Tuple[str, str]:
    if sel_slug and len(selected_plans) == 1:
        return selected_plans[0].pr_body, selected_plans[0].show_me_body
    pr_body = _format_markdown_sections(
        head_branch, base_branch, changed_count, index_changes,
        context_terms, specs_linked, verified_proofs, failed_proofs, examiner_receipt, gate_status, spec_digests,
    )
    ship_cmd = f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(head_branch)}"
    return pr_body, f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"


def _validate_ship_result(
    result: ShipPrepResult,
    strict_proofs: bool,
    split_branches: bool,
    repo: Path,
    eff_base: str,
    ticket_map: Optional[Dict[str, str]] = None,
) -> Tuple[bool, ShipPrepResult, str]:
    if result.failed_proofs:
        return False, result, f"ProofVerifier rejected {len(result.failed_proofs)} QA proof receipt(s)."
    if strict_proofs and not result.verified_proofs and not result.examiner_receipt:
        return False, result, "Strict proofs mode failed: no verified QA proofs or ExaminerReceipt found."
    if split_branches:
        sp_ok, created, sp_err = create_split_branches(repo, eff_base, result.spec_plans, ticket_map=ticket_map)
        result.split_branches_created = created
        if not sp_ok:
            return False, result, sp_err
    return True, result, ""


def _build_all_spec_plans(
    repo: Path,
    specs_linked: List[str],
    base_branch: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    receipts_by_ticket: Dict[str, Dict[str, Any]],
    gate_status: str,
    ticket_map: Dict[str, str],
) -> Tuple[List[SpecShipPlan], Dict[str, Optional[Dict[str, Any]]]]:
    plans: List[SpecShipPlan] = []
    plan_receipts: Dict[str, Optional[Dict[str, Any]]] = {}
    total = len(specs_linked)
    for spec_rel in specs_linked:
        tid = ticket_map.get(spec_rel)
        slug = _clean_slug(Path(spec_rel).stem)
        p_rec = _resolve_plan_receipt(tid, slug, spec_rel, examiner_receipt, receipts_by_ticket, total)
        plan_receipts[slug] = p_rec
        plans.append(
            _build_single_spec_plan(
                repo, spec_rel, base_branch, changed_files, index_changes,
                context_terms, verified_proofs, failed_proofs, p_rec, gate_status, ticket_id=tid,
            )
        )
    return plans, plan_receipts


def prepare_ship_payload(
    repo_path: Path,
    base_branch: str = "staging",
    strict_proofs: bool = False,
    spec_slug: Optional[str] = None,
    split_branches: bool = False,
    publish_evidence: bool = False,
    evidence_branch: str = "edge-qa-evidence",
) -> Tuple[bool, ShipPrepResult, str]:
    """Collects per-spec ship plans, scoped ProofVerifier results, optional evidence publishing, and PR bodies."""
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

    ticket, examiner_receipt, gate_status, receipts_by_ticket = _load_brigade_history_snapshot(repo)
    disk_specs = _list_disk_spec_candidates(repo)
    ticket_map = _resolve_spec_ticket_ids(repo, eff_base, disk_specs, receipts_by_ticket)
    specs_linked = discover_changed_specs(
        repo, eff_base, changed_files, index_changes, ticket_map=ticket_map, history_receipts=receipts_by_ticket
    )
    extra_specs = [s for s in specs_linked if s not in ticket_map]
    if extra_specs:
        ticket_map.update(_resolve_spec_ticket_ids(repo, eff_base, extra_specs, receipts_by_ticket))

    spec_slugs = [_clean_slug(Path(s).stem) for s in specs_linked]
    ticket_by_slug: Dict[str, Optional[str]] = {_clean_slug(Path(s).stem): ticket_map.get(s) for s in specs_linked}
    selected_slug = _clean_slug(spec_slug) if spec_slug else None

    verified_proofs, failed_proofs = _verify_scoped_proofs(
        repo, ticket, spec_slugs, changed_files, selected_slug=selected_slug, eff_base=eff_base, ticket_by_slug=ticket_by_slug
    )
    all_plans, plan_receipts = _build_all_spec_plans(
        repo, specs_linked, base_branch, changed_files, index_changes,
        context_terms, verified_proofs, failed_proofs, examiner_receipt, receipts_by_ticket, gate_status, ticket_map,
    )
    exclusive, has_shared, exc_files = _resolve_spec_commits(repo, eff_base, all_plans, ticket_map)
    _apply_slice_commits_to_plans(all_plans, exclusive, has_shared, exc_files, index_changes)

    sel_ok, selected_plans, sel_slug, sel_err = _select_spec_plans(all_plans, spec_slug, eff_base)
    if not sel_ok:
        res_err = _empty_result(base_branch, head_branch)
        res_err.spec_plans = all_plans
        res_err.selected_spec = sel_slug
        return False, res_err, sel_err

    if publish_evidence and not failed_proofs:
        pub_ok, pub_err = publish_screenshots_to_evidence_branch(
            repo, evidence_branch, selected_plans, _proof_search_roots(repo, ticket)
        )
        if not pub_ok:
            res_pub_err = _empty_result(base_branch, head_branch)
            res_pub_err.spec_plans = selected_plans
            res_pub_err.verified_proofs = verified_proofs
            return False, res_pub_err, pub_err

    for plan in selected_plans:
        _render_plan_bodies(plan, base_branch, context_terms, plan_receipts.get(plan.spec_slug), gate_status)

    spec_digests = [p.spec_digest for p in selected_plans if p.spec_digest]
    pr_body, show_me_body = _render_top_level_bodies(
        sel_slug, selected_plans, head_branch, base_branch, len(changed_files),
        index_changes, context_terms, specs_linked, verified_proofs, failed_proofs, examiner_receipt, gate_status, spec_digests,
    )

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
        intent=_build_intent_str(head_branch, index_changes, verified_proofs, changed_files, spec_digests=spec_digests),
        scenario_contract=_build_scenario_contract(head_branch, index_changes, verified_proofs, examiner_receipt, changed_files),
        pr_body=pr_body,
        show_me_body=show_me_body,
        spec_digests=spec_digests,
        spec_plans=selected_plans,
        selected_spec=sel_slug,
    )
    return _validate_ship_result(result, strict_proofs, split_branches, repo, eff_base, ticket_map=ticket_map)


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
