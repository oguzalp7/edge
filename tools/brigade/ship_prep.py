"""
Specs-to-PR Ship Bridge for Edge Brigade.
Deterministically synthesizes specs/INDEX.md diffs, CONTEXT.md domain terms,
archived specs, ProofVerifier-validated QA receipts, ExaminerReceipt, and
One-way vs. Two-way Door / Blast Radius classification for `no-mistakes`.
"""

from dataclasses import dataclass, asdict
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


@dataclass
class IndexChange:
    kind: str       # "@route" | "Page" | "@module" | "Action" | "Schema" | "@spec" | "other"
    symbol: str
    raw_line: str


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


def _norm_rel_path(raw: str) -> str:
    norm = raw.replace("\\", "/").strip()
    return norm[2:] if norm.startswith("./") else norm


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
    """Classifies branch diff into One-way vs. Two-way Door and computes blast radius."""
    norm_files = [_norm_rel_path(f) for f in changed_files if str(f).strip()]
    one_way_triggers = [f for f in norm_files if _is_one_way_door_path(f)]
    if one_way_triggers:
        door_type = "One-way door (Database Migration / Schema Change)"
    else:
        door_type = "Two-way door (Reversible Code / Configuration Change)"

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


def _scan_spec_dir(repo: Path, sub: str, tokens: List[str], seen: List[str]) -> List[str]:
    sdir = repo / sub
    if not sdir.is_dir():
        return []
    found: List[str] = []
    for p in sorted(sdir.glob("*.md")):
        rel = f"{sub}/{p.name}"
        if rel in seen:
            continue
        if not tokens or any(tok in p.stem.lower() for tok in tokens):
            found.append(rel)
    return found


def _collect_linked_specs(repo: Path, index_changes: List[IndexChange], branch: str, domains: List[str]) -> List[str]:
    linked: List[str] = []
    for ch in index_changes:
        if ch.kind == "@spec" and ch.symbol not in linked:
            linked.append(ch.symbol)

    slug = branch.split("/")[-1].lower().replace("_", "-") if branch else ""
    tokens = [t for t in [slug, *domains] if t]
    for sub in (".edge/archive/specs", ".edge/specs"):
        linked.extend(_scan_spec_dir(repo, sub, tokens, linked))
    return linked


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


def _discover_proof_files(repo: Path, ticket: Optional[Ticket]) -> Tuple[List[Path], List[Path]]:
    roots = [repo]
    if ticket and ticket.worktree_path:
        wt = normalize_target_path(ticket.worktree_path)
        if wt.is_dir() and wt not in roots:
            roots.insert(0, wt)

    seen_names: set = set()
    proof_files: List[Path] = []
    for root in roots:
        pdir = root / ".edge" / "qa" / "proofs"
        if not pdir.is_dir():
            continue
        for pf in sorted(pdir.glob("*.json")):
            if pf.name.endswith("-visual.json") or pf.name in seen_names:
                continue
            seen_names.add(pf.name)
            proof_files.append(pf)
    return proof_files, roots


def _verify_all_proofs(
    repo: Path,
    ticket: Optional[Ticket],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    proof_files, roots = _discover_proof_files(repo, ticket)
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for pf in proof_files:
        ok, msg, det = ProofVerifier.verify_receipt(pf, roots, ticket=ticket)
        rel = str(pf.relative_to(repo)).replace("\\", "/") if repo in pf.parents else str(pf)
        if ok:
            verified.append({
                "slug": det.get("slug", pf.stem),
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
                "slug": pf.stem,
                "path": rel,
                "error": det.get("error", "PROOF_VERIFICATION_FAILED"),
                "message": msg,
                "details": det,
            })
    return verified, failed


def _build_intent_str(
    head_branch: str,
    index_changes: List[IndexChange],
    verified_proofs: List[Dict[str, Any]],
    changed_files: List[str],
    door_type: str,
) -> str:
    targets = [f"{c.kind} {c.symbol}" for c in index_changes if c.kind in ("@route", "@module", "@spec")][:4]
    if not targets:
        targets = changed_files[:3] or [head_branch or "HEAD"]
    proof_slugs = [p["slug"] for p in verified_proofs]
    proof_part = f" | Verified QA proofs: {', '.join(proof_slugs)}" if proof_slugs else ""
    door_short = "One-way door" if door_type.startswith("One-way") else "Two-way door"
    raw_intent = f"Deliver {head_branch or 'slice'} ({', '.join(targets)}){proof_part} [{door_short}]"
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
    blast_radius: Dict[str, Any],
    index_changes: List[IndexChange],
    context_terms: List[str],
) -> List[str]:
    lines = [
        "## Summary",
        f"- **Branch:** `{head_branch}` -> `{base_branch}` ({blast_radius.get('changed_file_count', 0)} file(s) changed)",
    ]
    if index_changes:
        idx_summary = ", ".join(f"`{c.kind} {c.symbol}`" for c in index_changes[:8])
        lines.append(f"- **Navigation Index (`specs/INDEX.md`):** {idx_summary}")
    if context_terms:
        lines.append(f"- **Domain Vocabulary (`CONTEXT.md`):** {', '.join(context_terms)}")
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


def _format_danger_section(door_type: str, blast_radius: Dict[str, Any]) -> List[str]:
    lines = [
        "",
        "## Merge Danger",
        f"- **Door:** {door_type}",
        (
            f"- **Blast Radius:** {blast_radius.get('changed_file_count', 0)} files | "
            f"layers={blast_radius.get('layers', [])} | "
            f"+{blast_radius.get('insertions', 0)}/-{blast_radius.get('deletions', 0)} lines"
        ),
    ]
    if blast_radius.get("one_way_triggers"):
        triggers = ", ".join(blast_radius["one_way_triggers"])
        lines.append(f"- **One-Way Triggers:** {triggers} (verify backward-compatible migration & rollback)")
    else:
        lines.append("- **Rollback:** Standard `git revert` (two-way door).")
    return lines


def _format_markdown_sections(
    head_branch: str,
    base_branch: str,
    door_type: str,
    blast_radius: Dict[str, Any],
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
) -> str:
    lines = _format_summary_section(head_branch, base_branch, blast_radius, index_changes, context_terms)
    lines.extend(_format_evidence_section(specs_linked, verified_proofs, failed_proofs, examiner_receipt, gate_status))
    lines.extend(_format_danger_section(door_type, blast_radius))
    return "\n".join(lines)


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


def prepare_ship_payload(
    repo_path: Path,
    base_branch: str = "staging",
    strict_proofs: bool = False,
) -> Tuple[bool, ShipPrepResult, str]:
    """Collects Specs, Proofs, ExaminerReceipt, and Merge Danger into a deterministic ship payload."""
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
    specs_linked = _collect_linked_specs(repo, index_changes, head_branch, blast_radius.get("domains", []))

    ticket, examiner_receipt, gate_status = _load_brigade_snapshot(repo)
    verified_proofs, failed_proofs = _verify_all_proofs(repo, ticket)

    intent = _build_intent_str(head_branch, index_changes, verified_proofs, changed_files, door_type)
    scenario_contract = _build_scenario_contract(head_branch, index_changes, verified_proofs, examiner_receipt, changed_files)
    pr_body = _format_markdown_sections(
        head_branch, base_branch, door_type, blast_radius, index_changes,
        context_terms, specs_linked, verified_proofs, failed_proofs, examiner_receipt, gate_status,
    )
    cmd_line = f"no-mistakes axi run --base-branch {shlex.quote(base_branch)} --intent {shlex.quote(intent)} -y"
    show_me_body = f"{pr_body}\n\n## Ship Command\n```bash\n{cmd_line}\n```"

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
    )

    if failed_proofs:
        return False, result, f"ProofVerifier rejected {len(failed_proofs)} QA proof receipt(s)."
    if strict_proofs and not verified_proofs and not examiner_receipt:
        return False, result, "Strict proofs mode failed: no verified QA proofs or ExaminerReceipt found."
    return True, result, ""


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
            "verified_proofs": result.verified_proofs,
            "failed_proofs": result.failed_proofs,
            "examiner_receipt": result.examiner_receipt,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return result.pr_body
