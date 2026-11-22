"""
Per-Spec Ship Engine & Specs-to-PR Bridge for Edge Brigade.
Deterministically discovers changed specs between <base>..HEAD, runs scoped
ProofVerifier validation, constructs per-spec SpecShipPlan payloads (lean
2-section PR bodies with ## Summary and ## Evidence), and optionally creates
isolated ship/<spec-slug> branches via --split-branches.
@intent Synthesize two-tier ship branches, PR summaries, and door-brake validations
@concepts two-tier-delivery, refactor-receipt-binding, one-way-door-brake
@invariants [INV-DELIVERY-DEV-FIRST], [INV-DELIVERY-LEAN-PR]
"""

from dataclasses import dataclass, asdict, field
from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import json
import os
import re
import shlex
import subprocess
import tempfile

try:
    from .models import BrigadeState, Ticket
    from .fsm import ProofVerifier
    from .smoke_routes import SmokeScanReport, triage_smoke_failures
    from .security_audit import run_security_audit, triage_security_findings
    from .refactor_receipt import RefactorReceiptVerifier, compute_changed_files_hash
    from .tasks_bridge import resolve_target_repo_root
except ImportError:
    from tools.brigade.models import BrigadeState, Ticket
    from tools.brigade.fsm import ProofVerifier
    from tools.brigade.smoke_routes import SmokeScanReport, triage_smoke_failures
    from tools.brigade.security_audit import run_security_audit, triage_security_findings
    from tools.brigade.refactor_receipt import RefactorReceiptVerifier, compute_changed_files_hash
    from tools.brigade.tasks_bridge import resolve_target_repo_root

from tools.common import normalize_target_path, run_command


INDEX_TOKEN_RE = re.compile(r"(@route|@module|@spec|Page:|Action:|Schema:)\s+([^\s|]+)")
BOLD_TERM_RE = re.compile(r"\*\*([^*]+)\*\*")
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")
_TICKET_RE = re.compile(r"\b(TICK-[A-Z0-9][A-Z0-9-]*)\b")
_URL_USERINFO_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://)([^\s/@'\"]+@)")
_REPO_PREFIXES: Tuple[str, ...] = (
    "src/", "tools/", "skills/", "agents/", "rules/",
    "tests/", "scripts/", "specs/", "public/", "drizzle/", "prisma/",
)
_INLINE_PATH_RE = re.compile(
    r"((?:src|tools|skills|agents|rules|tests|scripts|specs|public|drizzle|prisma)/[^\s|`'\",;<>]+)"
)


_EVIDENCE_ARTIFACT_PREFIXES: Tuple[str, ...] = (
    ".edge/qa/screenshots/",
    ".edge/qa/proofs/",
    ".edge/qa/visual/",
)
_SLICE_BRANCH_PREFIXES: Tuple[str, ...] = (
    "feat/",
    "fix/",
    "refactor/",
    "hotfix/",
    "chore/",
    "ship/",
)
DEFAULT_STAGE_BRANCHES: Dict[str, str] = {
    "integration": "development",
    "staging": "staging",
    "production": "production",
}
_CALLSTACK_HEADING_RE = re.compile(
    r"^(#{1,4})\s+.*(?:call[-\s]?stack|responsive\s+layout\s+flow|architecture|flow|component\s+tree|file\s+tree)",
    re.IGNORECASE,
)
_HEADING_LEVEL_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_CRIT_ID_RE = re.compile(r"\b((?:AC|IC)-\d+)\b")
_FENCE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_-]*)\s*\n(.*?)```", re.DOTALL)
_TREEHOUSE_SLOT_RE = re.compile(r"^.*/\.treehouse/pool/slot-\d+/[^/]+/")
_KNOWN_ROOT_RE = re.compile(
    r"^.*/(?=(?:\.edge|src|tools|skills|agents|rules|tests|scripts|specs|public|drizzle|prisma)/)"
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
    callstack_blocks: List[str] = field(default_factory=list)
    acceptance_criteria: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class RealizationAudit:
    actual_code_files: List[str] = field(default_factory=list)
    realized_files: List[str] = field(default_factory=list)
    untouched_expected_files: List[str] = field(default_factory=list)
    unplanned_extra_files: List[str] = field(default_factory=list)
    file_tree_diff: str = ""
    criteria_rows: List[Dict[str, str]] = field(default_factory=list)


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
    realization_audit: Optional[RealizationAudit] = None
    kind: str = "spec"
    refactor_receipt: Optional[Dict[str, Any]] = None

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
    smoke_report: Optional[Dict[str, Any]] = None
    security_report: Optional[Dict[str, Any]] = None


def _clean_slug(raw: str) -> str:
    return (raw or "").strip().lower().replace("_", "-")


def _is_evidence_artifact_path(norm_path: str) -> bool:
    rel = _normalize_display_path(norm_path).lstrip("/")
    low = rel.lower()
    return any(
        low.startswith(pref) or f"/{pref}" in low
        for pref in _EVIDENCE_ARTIFACT_PREFIXES
    )


def _strip_repo_prefix(s: str, repo: Optional[Path]) -> str:
    if repo is None:
        return s
    for cand in (str(repo).replace("\\", "/").rstrip("/"),):
        if cand and s.startswith(cand + "/"):
            return s[len(cand) + 1:]
    try:
        from tools.common.paths import to_wsl_path
        wsl_repo = to_wsl_path(repo).rstrip("/")
        if wsl_repo and s.startswith(wsl_repo + "/"):
            return s[len(wsl_repo) + 1:]
    except Exception:
        pass
    return s


def _normalize_display_path(raw_path: str, repo: Optional[Path] = None) -> str:
    s = str(raw_path or "").strip().replace("\\", "/")
    if not s:
        return ""
    s = re.sub(r"^//wsl(?:\.localhost|\$)/[^/]+", "", s)
    s = re.sub(r"^[A-Za-z]:/", lambda m: f"/mnt/{m.group(0)[0].lower()}/", s)
    s = _strip_repo_prefix(s, repo)
    s = _TREEHOUSE_SLOT_RE.sub("", s)
    s = _KNOWN_ROOT_RE.sub("", s)
    s = re.sub(r"^/home/[^/]+/[^/]+/", "", s)
    return s.lstrip("./") if s.startswith("./") else s


def _format_screenshot_title(raw_path_or_url: str) -> str:
    clean = str(raw_path_or_url or "").split("?")[0].strip()
    stem = Path(clean).stem if clean else ""
    stem = re.sub(r"^\d+[-_]+", "", stem)
    words = [w.capitalize() for w in re.split(r"[-_\s]+", stem) if w]
    return " ".join(words) or "Screenshot"


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


_AUTH_SEGMENT_RE = re.compile(
    r"(?:^|/)(auth|middleware|permissions|rbac|session|security)(?:/|\.|$)",
    re.IGNORECASE,
)


def _is_one_way_door_path(norm_path: str) -> bool:
    low = norm_path.lower()
    if low.startswith("drizzle/") or "/drizzle/" in low:
        return True
    if low.startswith("src/db/schema") or "/db/schema/" in low or low.endswith("/db/schema"):
        return True
    return low.endswith(".sql")


def _is_refactor_auth_path(norm_path: str) -> bool:
    return bool(_AUTH_SEGMENT_RE.search(_norm_rel_path(norm_path)))


def _strip_line_comments_for_diff(lines: List[str]) -> str:
    cleaned: List[str] = []
    in_block = False
    for raw in lines:
        s = raw.strip()
        if not s:
            continue
        if in_block:
            if "*/" in s:
                in_block = False
                after = s.split("*/", 1)[1].strip()
                if after and not after.startswith("//"):
                    cleaned.append(after)
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            else:
                after = s.split("*/", 1)[1].strip()
                if after and not after.startswith("//"):
                    cleaned.append(after)
            continue
        if s.startswith(("//", "*")):
            continue
        cleaned.append(raw)
    return "\n".join(cleaned)


def _extract_balanced_parens(text: str, open_idx: int) -> str:
    depth = 0
    chars: List[str] = []
    for ch in text[open_idx:]:
        if ch == "(":
            depth += 1
            if depth > 1:
                chars.append(ch)
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
            chars.append(ch)
        elif depth >= 1:
            chars.append(ch)
    return re.sub(r"\s+", " ", "".join(chars)).strip().rstrip(",").strip()


def _extract_export_summary(text: str) -> Dict[str, Any]:
    named_exports: set = set()
    func_sigs: Dict[str, set] = {}
    star_exports: set = set()
    module_export_keys: set = set()

    for m in re.finditer(
        r"\bexport\s+(?:declare\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(",
        text,
    ):
        fn_name = m.group(1)
        sig = _extract_balanced_parens(text, m.end() - 1)
        named_exports.add(fn_name)
        func_sigs.setdefault(fn_name, set()).add(sig)

    for m in re.finditer(
        r"\bexport\s+(?:declare\s+)?(?:const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)",
        text,
    ):
        named_exports.add(m.group(1))

    for m in re.finditer(r"\bexport\s+(?:type\s+)?\{([^}]+)\}", text, re.DOTALL):
        for part in m.group(1).split(","):
            tok = part.strip()
            if not tok:
                continue
            if tok.startswith("type "):
                tok = tok[5:].strip()
            if " as " in tok:
                tok = tok.split(" as ", 1)[1].strip()
            if tok:
                named_exports.add(tok)

    for m in re.finditer(
        r"\bexport\s+\*(?:\s+as\s+([A-Za-z_$][\w$]*))?\s+from\s+['\"]([^'\"]+)['\"]",
        text,
    ):
        star_exports.add((m.group(1) or "", m.group(2)))

    has_default = bool(re.search(r"\bexport\s+default\b", text))

    has_module_exports = bool(re.search(r"\bmodule\.exports\s*=", text))
    for m in re.finditer(r"\bmodule\.exports\s*=\s*\{([^}]+)\}", text, re.DOTALL):
        for part in m.group(1).split(","):
            key = part.split(":", 1)[0].strip()
            if key:
                module_export_keys.add(key)

    return {
        "named_exports": named_exports,
        "func_sigs": func_sigs,
        "star_exports": star_exports,
        "has_default": has_default,
        "has_module_exports": has_module_exports,
        "module_export_keys": module_export_keys,
    }


def _split_diff_by_file(diff_text: str) -> List[Tuple[str, List[str], List[str]]]:
    chunks: List[Tuple[str, List[str], List[str]]] = []
    cur_file = "<diff>"
    rem: List[str] = []
    add: List[str] = []

    for line in (diff_text or "").splitlines():
        if line.startswith("diff --git "):
            if rem or add:
                chunks.append((cur_file, rem, add))
            parts = line.split()
            cur_file = parts[-1][2:] if parts and parts[-1].startswith("b/") else "<diff>"
            rem, add = [], []
        elif line.startswith("-") and not line.startswith("---"):
            rem.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            add.append(line[1:])
    if rem or add:
        chunks.append((cur_file, rem, add))
    return chunks


def _detect_exported_api_breaks(diff_text: str) -> List[str]:
    if not diff_text or not diff_text.strip():
        return []

    reasons: List[str] = []
    for fpath, rem_lines, add_lines in _split_diff_by_file(diff_text):
        low = fpath.lower()
        if any(marker in low for marker in (".test.", ".spec.", ".md", ".json")):
            continue
        rem_text = _strip_line_comments_for_diff(rem_lines)
        add_text = _strip_line_comments_for_diff(add_lines)
        if not rem_text.strip():
            continue

        rem = _extract_export_summary(rem_text)
        add = _extract_export_summary(add_text)

        for sym in sorted(rem["named_exports"] - add["named_exports"]):
            reasons.append(f"Exported symbol removed ({fpath}): {sym}")
        for fn_name, rem_sigs in sorted(rem["func_sigs"].items()):
            if fn_name in add["func_sigs"] and not rem_sigs.issubset(add["func_sigs"][fn_name]):
                reasons.append(f"Exported function signature changed ({fpath}): {fn_name}")
        for alias, mod in sorted(rem["star_exports"] - add["star_exports"]):
            label = f"* as {alias} from {mod}" if alias else f"* from {mod}"
            reasons.append(f"Wildcard re-export removed ({fpath}): {label}")
        if rem["has_default"] and not add["has_default"]:
            reasons.append(f"Default export removed ({fpath})")
        if rem["module_export_keys"] and add["module_export_keys"]:
            for key in sorted(rem["module_export_keys"] - add["module_export_keys"]):
                reasons.append(f"CommonJS module.exports key removed ({fpath}): {key}")
        elif rem["has_module_exports"] and not add["has_module_exports"]:
            reasons.append(f"CommonJS module.exports removed ({fpath})")

    return reasons


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


def classify_merge_danger(
    changed_files: List[str],
    diff_stat: str = "",
    diff_text: str = "",
    is_refactor: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """Classifies merge door risk (Two-Way vs One-Way) and populates blast_radius telemetry."""
    norm_files = [_norm_rel_path(f) for f in changed_files if str(f).strip()]
    db_triggers = [f for f in norm_files if _is_one_way_door_path(f)]
    one_way_triggers = list(db_triggers)
    one_way_reasons: List[str] = [f"Database migration/schema touched: {f}" for f in db_triggers]

    ins, dels = _parse_stat_counts(diff_stat)
    if is_refactor:
        for f in norm_files:
            if _is_refactor_auth_path(f):
                if f not in one_way_triggers:
                    one_way_triggers.append(f)
                one_way_reasons.append(f"Security/auth path touched: {f}")

        api_breaks = _detect_exported_api_breaks(diff_text)
        one_way_reasons.extend(api_breaks)

        if len(norm_files) > 15:
            one_way_reasons.append(f"Large refactor blast radius: {len(norm_files)} files changed (> 15)")
        if (ins + dels) > 500:
            one_way_reasons.append(f"Large refactor diff size: {ins + dels} lines changed (> 500)")

    if one_way_reasons:
        summary_reason = "; ".join(one_way_reasons[:2])
        door_type = (
            f"One-way door ({summary_reason})"
            if is_refactor or not db_triggers
            else "One-way door (Database Migration / Schema Change)"
        )
    else:
        door_type = "Two-way door (Reversible Code / Configuration Change)"

    layers = sorted({_classify_layer(f) for f in norm_files})
    blast_radius = {
        "changed_file_count": len(norm_files),
        "changed_files": norm_files,
        "layers": layers,
        "domains": _extract_domains(norm_files),
        "one_way_triggers": one_way_triggers,
        "one_way_reasons": one_way_reasons,
        "insertions": ins,
        "deletions": dels,
        "diff_stat": diff_stat.strip(),
    }
    return door_type, blast_radius


def _read_stage_branches_config(repo_path: Optional[Path]) -> Dict[str, str]:
    if repo_path is None:
        return {}
    cfg_file = Path(repo_path) / ".edge" / "brigade.json"
    if not cfg_file.is_file():
        return {}
    try:
        data = json.loads(cfg_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw_stages = data.get("stage_branches") if isinstance(data, dict) else None
    if not isinstance(raw_stages, dict):
        return {}
    return {
        str(k).strip(): str(v).strip()
        for k, v in raw_stages.items()
        if str(k).strip() and str(v or "").strip()
    }


def resolve_stage_branches(
    repo_path: Optional[Path] = None,
    overrides: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Resolves integration/staging/production branch names from defaults, .edge/brigade.json, and overrides."""
    resolved = dict(DEFAULT_STAGE_BRANCHES)
    resolved.update(_read_stage_branches_config(repo_path))
    for k, v in (overrides or {}).items():
        clean_k = str(k).strip()
        clean_v = str(v or "").strip()
        if clean_k and clean_v:
            resolved[clean_k] = clean_v
    return resolved


def _get_head_branch(repo: Path) -> str:
    code, out, _ = run_command(["git", "branch", "--show-current"], cwd=repo)
    return (out.strip() or "HEAD") if code == 0 else "HEAD"


def _candidate_base_refs(
    raw: str,
    eff_head: str,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[str, str]:
    clean_base = raw[7:] if raw.startswith("origin/") else raw
    if raw.startswith("origin/"):
        return raw, clean_base
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    protected_bases = {eff_stages.get("staging", "staging"), eff_stages.get("production", "production"), "staging"}
    if eff_head == clean_base or clean_base in protected_bases:
        return f"origin/{clean_base}", clean_base
    return clean_base, f"origin/{clean_base}"


def _resolve_base_ref(
    repo: Path,
    base_branch: str,
    head_branch: Optional[str] = None,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    raw = (base_branch or "").strip()
    if not raw:
        return None
    eff_head = head_branch if head_branch is not None else _get_head_branch(repo)
    for cand in _candidate_base_refs(raw, eff_head, stage_branches):
        code, _, _ = run_command(["git", "rev-parse", "--verify", cand], cwd=repo)
        if code == 0:
            return cand
    return None


def validate_branch_topology(
    base_branch: str,
    head_branch: str,
    split_branches: bool = False,
    allow_override: bool = False,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, str]:
    """Enforces development-first PR topology unless allow_override=True bypasses it."""
    if allow_override:
        return True, ""
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    integration_branch = eff_stages.get("integration", "development")
    staging_branch = eff_stages.get("staging", "staging")
    production_branch = eff_stages.get("production", "production")

    raw_base = (base_branch or "").strip()
    clean_base = raw_base[7:] if raw_base.startswith("origin/") else raw_base
    if clean_base not in (staging_branch, production_branch) or clean_base == integration_branch:
        return True, ""
    if split_branches:
        return (
            False,
            f"Branch topology violation: per-spec split branches (ship/<slug>) must target "
            f"'{integration_branch}' first (--base {integration_branch}), never '{clean_base}' directly.",
        )
    clean_head = (head_branch or "").strip()
    if clean_head.startswith(_SLICE_BRANCH_PREFIXES):
        return (
            False,
            f"Branch topology violation: slice branch '{clean_head}' cannot target '{clean_base}' directly. "
            f"Open per-spec PR to '{integration_branch}' first, then promote '{integration_branch}' -> '{clean_base}'.",
        )
    return True, ""


def _collect_bold_terms_from_file(fpath: Path, terms: List[str]) -> None:
    if not fpath.is_file():
        return
    for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
        for match in BOLD_TERM_RE.finditer(line):
            term = match.group(1).strip()
            if term and term not in terms:
                terms.append(term)


def _filter_matching_terms(terms: List[str], search_tokens: List[str]) -> List[str]:
    matched: List[str] = []
    for t in terms:
        low_t = t.lower()
        if any(tok in low_t for tok in search_tokens):
            matched.append(t)
    return (matched or terms)[:12]


def _extract_closed_glossary_entries(lines: List[str]) -> Optional[List[Tuple[str, str]]]:
    """
    If ## Closed Concept Glossary heading exists, returns [(concept_id, full_row_text)].
    Returns None when the heading is absent so callers can fall back to legacy **bold** parsing.
    """
    start_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip().lower() == "## closed concept glossary"),
        None,
    )
    if start_idx is None:
        return None

    entries: List[Tuple[str, str]] = []
    for raw in lines[start_idx + 1 :]:
        s = raw.strip()
        if s.startswith("## "):
            break
        if not s or _TABLE_SEP_RE.match(s):
            continue
        if s.startswith(("- ", "* ")):
            m = re.match(r"^[-*]\s+`?([a-z0-9][a-z0-9_-]*)`?\s*:", s)
            if m:
                entries.append((m.group(1), s))
        elif s.startswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            cid = cells[0].strip("`").strip() if cells else ""
            if cid and cid.lower() != "concept":
                entries.append((cid, s))
    return entries


def _read_context_terms(repo: Path, search_tokens: List[str]) -> List[str]:
    context_file = repo / "CONTEXT.md"
    if context_file.is_file():
        lines = context_file.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
        glossary_entries = _extract_closed_glossary_entries(lines)
        if glossary_entries is not None:
            if not search_tokens:
                return [cid for cid, _ in glossary_entries][:12]
            lowered_tokens = [tok.lower() for tok in search_tokens]
            return [
                cid
                for cid, row in glossary_entries
                if any(tok in row.lower() for tok in lowered_tokens)
            ][:12]

    terms: List[str] = []
    for fname in ("CONTEXT.md", "GLOSSARY.md"):
        _collect_bold_terms_from_file(repo / fname, terms)
    if not search_tokens:
        return terms[:12]
    return _filter_matching_terms(terms, search_tokens)


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


def _is_broad_path(pat: str, repo: Optional[Path] = None) -> bool:
    norm = _norm_rel_path(pat)
    if norm.endswith(("/", "/*", "/**")) or "/**" in norm:
        return True
    name = Path(norm).name
    if name in ("*", "**"):
        return True
    if "*" not in norm and "." not in name:
        return not (repo is not None and (repo / norm).is_file())
    return False


def _base_commit_timestamp(repo: Path, eff_base: str) -> int:
    code, out, _ = run_command(["git", "show", "-s", "--format=%ct", eff_base], cwd=repo)
    if code == 0 and out.strip().isdigit():
        return int(out.strip())
    return 0


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


def _extract_spec_slug_from_proof_json(raw_text: str) -> Optional[str]:
    try:
        data = json.loads(raw_text)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw_spec = str(data.get("spec") or "").strip()
    return _clean_slug(Path(raw_spec).stem) if raw_spec else None


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


def _collect_proof_ticket_map(repo: Path, eff_base: str, base_ts: int = 0) -> Dict[str, str]:
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
            if base_ts and int(pf.stat().st_mtime) < base_ts:
                continue
            parsed = _extract_ticket_from_proof_json(pf.read_text(encoding="utf-8", errors="ignore"))
            if parsed:
                mapping[parsed[0]] = parsed[1]
    return mapping


def _collect_diff_proof_slugs(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    base_ts: int,
) -> set:
    slugs = set(_collect_proof_ticket_map(repo, eff_base, base_ts=base_ts).keys())
    for cf in changed_files:
        norm = _norm_rel_path(cf)
        if norm.startswith(".edge/qa/proofs/") and norm.endswith(".json") and not norm.endswith("-visual.json"):
            pf = repo / norm
            if pf.is_file():
                slug = _extract_spec_slug_from_proof_json(pf.read_text(encoding="utf-8", errors="ignore"))
                if slug:
                    slugs.add(slug)
    return slugs


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
    bound_tids: set,
    repo: Path,
) -> Optional[str]:
    expected = [p for p in _extract_spec_expected_files(spec_file) if not _is_broad_path(p, repo)]
    if not expected:
        return None
    for tid, c_files in commit_tickets:
        if tid in bound_tids:
            continue
        if _match_expected_files(expected, c_files):
            return tid
    return None


def _resolve_explicit_spec_ticket(
    repo: Path,
    spec_rel: str,
    proof_tickets: Dict[str, str],
    history_receipts: Dict[str, Dict[str, Any]],
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
    return None


def _resolve_spec_ticket_ids(
    repo: Path,
    eff_base: str,
    spec_paths: List[str],
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Reverse-resolves TICK-* IDs (explicit anchors first, then unbound commit file overlap)."""
    if not spec_paths:
        return {}
    base_ts = _base_commit_timestamp(repo, eff_base)
    proof_tickets = _collect_proof_ticket_map(repo, eff_base, base_ts=base_ts)
    hist = history_receipts or {}
    resolved: Dict[str, str] = {}
    unresolved: List[str] = []
    for spec_rel in spec_paths:
        tid = _resolve_explicit_spec_ticket(repo, spec_rel, proof_tickets, hist)
        if tid:
            resolved[spec_rel] = tid
        else:
            unresolved.append(spec_rel)
    if unresolved:
        commit_tickets = _commit_ticket_file_index(repo, eff_base)
        bound_tids = set(resolved.values())
        for spec_rel in unresolved:
            tid = _match_commit_ticket_for_spec(repo / spec_rel, commit_tickets, bound_tids, repo)
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


def _ticket_anchored_for_spec(
    repo: Path,
    rel: str,
    spec_slug: str,
    log_body: str,
    tid: Optional[str],
    history_receipts: Dict[str, Dict[str, Any]],
) -> bool:
    if not tid or tid not in log_body:
        return False
    rec = history_receipts.get(tid)
    if rec and _receipt_matches_spec(rec, rel, spec_slug):
        return True
    spec_file = repo / rel
    return bool(spec_file.is_file() and tid in spec_file.read_text(encoding="utf-8", errors="ignore"))


def _spec_has_diff_anchor(
    repo: Path,
    rel: str,
    log_body: str,
    ticket_map: Dict[str, str],
    history_receipts: Dict[str, Dict[str, Any]],
    diff_proof_slugs: set,
) -> bool:
    spec_slug = _clean_slug(Path(rel).stem)
    if spec_slug and spec_slug in log_body.lower():
        return True
    if rel in log_body or spec_slug in diff_proof_slugs:
        return True
    return _ticket_anchored_for_spec(repo, rel, spec_slug, log_body, ticket_map.get(rel), history_receipts)


def _specific_matched_files(repo: Path, rel: str, changed_files: List[str]) -> List[str]:
    expected = _extract_spec_expected_files(repo / rel)
    specific: List[str] = []
    for pat in expected:
        if not _is_broad_path(pat, repo):
            specific.append(pat)
    return _match_expected_files(specific, changed_files) if specific else []


def _unanchored_spec_eligible(
    repo: Path,
    rel: str,
    changed_files: List[str],
    covered_files: set,
    base_ts: int,
    has_anchors: bool,
    diff_proof_slugs: set,
) -> bool:
    hits = _specific_matched_files(repo, rel, changed_files)
    if not hits:
        return False
    if not has_anchors:
        return True
    spec_file = repo / rel
    if rel.startswith(".edge/archive/specs/") and base_ts and int(spec_file.stat().st_mtime) < base_ts:
        return False
    spec_slug = _clean_slug(spec_file.stem)
    old_proof = repo / ".edge" / "qa" / "proofs" / f"{spec_slug}.json"
    if old_proof.is_file() and spec_slug not in diff_proof_slugs:
        return False
    return any(h not in covered_files for h in hits)


def _scan_disk_specs_for_diff(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    ticket_map: Dict[str, str],
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
    has_git_specs: bool = False,
) -> List[str]:
    """Scans gitignored .edge specs on disk (anchored specs first, bounded unanchored fallback)."""
    _, log_body, _ = run_command(["git", "log", "--format=%B", f"{eff_base}..HEAD"], cwd=repo)
    hist = history_receipts or {}
    base_ts = _base_commit_timestamp(repo, eff_base)
    diff_proof_slugs = _collect_diff_proof_slugs(repo, eff_base, changed_files, base_ts)
    all_candidates = _list_disk_spec_candidates(repo)

    anchored: List[str] = []
    unanchored: List[str] = []
    for rel in all_candidates:
        if _spec_has_diff_anchor(repo, rel, log_body, ticket_map, hist, diff_proof_slugs):
            anchored.append(rel)
        else:
            unanchored.append(rel)

    covered_files: set = set()
    for rel in anchored:
        covered_files.update(_specific_matched_files(repo, rel, changed_files))

    has_anchors = bool(anchored or has_git_specs)
    matched = list(anchored)
    for rel in unanchored:
        if _unanchored_spec_eligible(repo, rel, changed_files, covered_files, base_ts, has_anchors, diff_proof_slugs):
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
    git_specs = [line.strip() for line in spec_diff_out.splitlines() if line.strip() and _is_valid_spec_candidate(line)]
    candidates: List[str] = [*git_specs, *changed_files]
    candidates.extend(ch.symbol for ch in index_changes if ch.kind == "@spec")

    eff_hist = history_receipts if history_receipts is not None else _load_brigade_history_snapshot(repo)[3]
    disk_specs = _list_disk_spec_candidates(repo)
    eff_tickets = ticket_map if ticket_map is not None else _resolve_spec_ticket_ids(repo, eff_base, disk_specs, eff_hist)
    candidates.extend(
        _scan_disk_specs_for_diff(repo, eff_base, changed_files, eff_tickets, eff_hist, has_git_specs=bool(git_specs))
    )
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


def _is_flow_or_tree_line(line: str) -> bool:
    return any(g in line for g in ("├──", "└──", "│", "->", "→"))


def _flush_flow_buf(buf: List[str], blocks: List[str]) -> None:
    text = "\n".join(buf).strip()
    if text and text not in blocks:
        blocks.append(text)
    buf.clear()


def _collect_section_callstacks(section_lines: List[str]) -> List[str]:
    blocks: List[str] = []
    flow_buf: List[str] = []
    in_fence = False
    fence_lang = ""
    fence_buf: List[str] = []
    for raw in section_lines:
        s = raw.strip()
        if s.startswith("```"):
            _flush_flow_buf(flow_buf, blocks)
            if not in_fence:
                in_fence, fence_lang, fence_buf = True, s[3:].strip().lower(), []
            else:
                if fence_lang != "mermaid":
                    blk = "\n".join(fence_buf).strip()
                    if blk and blk not in blocks:
                        blocks.append(blk)
                in_fence = False
            continue
        if in_fence:
            fence_buf.append(raw.rstrip())
        elif _is_flow_or_tree_line(s):
            flow_buf.append(raw.rstrip())
        else:
            _flush_flow_buf(flow_buf, blocks)
    _flush_flow_buf(flow_buf, blocks)
    return blocks


def _collect_heading_callstack_blocks(lines: List[str]) -> List[str]:
    blocks: List[str] = []
    sec_lines: List[str] = []
    sec_level: Optional[int] = None
    for raw in lines:
        s = raw.strip()
        hm = _HEADING_LEVEL_RE.match(s)
        if _CALLSTACK_HEADING_RE.match(s):
            blocks.extend(_collect_section_callstacks(sec_lines))
            sec_lines, sec_level = [], len(hm.group(1)) if hm else 2
            continue
        if sec_level is not None and ((hm and len(hm.group(1)) <= sec_level) or s == "---"):
            blocks.extend(_collect_section_callstacks(sec_lines))
            sec_lines, sec_level = [], None
            continue
        if sec_level is not None:
            sec_lines.append(raw)
    if sec_level is not None:
        blocks.extend(_collect_section_callstacks(sec_lines))
    return blocks


def _is_fallback_callstack_block(lang: str, body: str) -> bool:
    if lang == "mermaid" or not body:
        return False
    if "├──" in body or "└──" in body:
        return True
    arrow_lines = sum(1 for ln in body.splitlines() if "->" in ln or "→" in ln)
    return arrow_lines >= 2


def _extract_callstack_blocks(text: str, lines: List[str], has_mermaid: bool = False) -> List[str]:
    blocks = _collect_heading_callstack_blocks(lines)
    if not blocks and not has_mermaid:
        for m in _FENCE_BLOCK_RE.finditer(text):
            lang, body = m.group(1).strip().lower(), m.group(2).strip()
            if _is_fallback_callstack_block(lang, body) and body not in blocks:
                blocks.append(body)
    unique: List[str] = []
    for b in blocks:
        if b not in unique:
            unique.append(b)
    return unique[:3]


def _parse_crit_table_row(s: str) -> Optional[Dict[str, str]]:
    if not s.startswith("|") or _TABLE_SEP_RE.match(s):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if not cells:
        return None
    m = _CRIT_ID_RE.search(cells[0])
    if not m:
        return None
    cid = m.group(1)
    if len(cells) >= 3:
        title = cells[1].strip("`*") or cid
        exp = cells[2].strip("`*") or title
    elif len(cells) == 2:
        title, exp = cid, cells[1].strip("`*")
    else:
        title, exp = cid, cells[0]
    return {"id": cid, "title": title, "expectation": exp}


def _parse_crit_line_item(s: str) -> Optional[Tuple[Dict[str, str], bool]]:
    if s.startswith("|") or not _CRIT_ID_RE.search(s):
        return None
    m = _CRIT_ID_RE.search(s)
    assert m is not None
    cid = m.group(1)
    is_heading = bool(_HEADING_LEVEL_RE.match(s))
    cleaned = re.sub(r"^#{1,6}\s+|^[-*]\s+", "", s).replace("**", "").replace("`", "").strip()
    after_id = cleaned.split(cid, 1)[1].lstrip(" :.-)").strip()
    if ":" in after_id:
        title_p, exp_p = after_id.split(":", 1)
        return {"id": cid, "title": title_p.strip("() ") or cid, "expectation": exp_p.strip() or title_p.strip()}, is_heading and not exp_p.strip()
    return {"id": cid, "title": after_id.strip("() ") or cid, "expectation": after_id.strip() or cid}, is_heading


def _collect_heading_bullets(lines: List[str], start_idx: int) -> str:
    bullets: List[str] = []
    for raw in lines[start_idx + 1:]:
        st = raw.strip()
        if not st:
            continue
        if st.startswith("#") or st == "---":
            break
        if st.startswith(("- ", "* ")):
            bullets.append(st[2:].replace("**", "").strip())
            if len(bullets) >= 2:
                break
    return "; ".join(bullets)


def _extract_acceptance_criteria(lines: List[str]) -> List[Dict[str, str]]:
    criteria: List[Dict[str, str]] = []
    seen_ids: set = set()
    for idx, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        entry = _parse_crit_table_row(s)
        needs_bullets = False
        if entry is None:
            parsed = _parse_crit_line_item(s)
            if parsed:
                entry, needs_bullets = parsed
        if not entry or entry["id"] in seen_ids:
            continue
        if needs_bullets:
            sub = _collect_heading_bullets(lines, idx)
            if sub:
                entry["expectation"] = sub
        seen_ids.add(entry["id"])
        criteria.append(entry)
    return criteria


def parse_spec_document(spec_path: Path, rel_path: str = "") -> SpecDigest:
    """Parses a Markdown specification into title, summary, Mermaid, call-stack blocks, and criteria."""
    eff_rel = rel_path or str(spec_path).replace("\\", "/")
    if not spec_path.is_file():
        return SpecDigest(path=eff_rel, title=spec_path.stem, summary="")
    text = spec_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    title, summary = _extract_spec_title_and_summary(lines, spec_path.stem)
    mermaids = [m.group(1).strip() for m in _MERMAID_BLOCK_RE.finditer(text) if m.group(1).strip()]
    matrix = _extract_spec_matrix_rows(lines)
    callstacks = _extract_callstack_blocks(text, lines, has_mermaid=bool(mermaids))
    criteria = _extract_acceptance_criteria(lines)
    return SpecDigest(
        path=eff_rel,
        title=title,
        summary=summary,
        mermaid_blocks=mermaids,
        matrix_rows=matrix,
        callstack_blocks=callstacks,
        acceptance_criteria=criteria,
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


def _append_glob_matches(pat: str, norm_changed: List[str], expanded: List[str]) -> None:
    for cf in norm_changed:
        if fnmatch(cf, pat) and cf not in expanded:
            expanded.append(cf)


def _expand_expected_globs(patterns: List[str], changed_files: List[str]) -> List[str]:
    """Expands globbed spec patterns (e.g. 0017_*.sql) against changed files."""
    expanded: List[str] = []
    norm_changed = [_norm_rel_path(cf) for cf in changed_files]
    for pat in patterns:
        if any(ch in pat for ch in "*?["):
            _append_glob_matches(pat, norm_changed, expanded)
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
        common_root = resolve_target_repo_root(repo)
        alt_file = common_root / ".edge" / "brigade.json"
        if alt_file.is_file():
            state_file = alt_file
        else:
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


def _scan_dir_matching_proofs(
    proofs_dir: Path,
    slug_set: set,
    ticket_set: set,
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Path]:
    if not proofs_dir.is_dir():
        return []
    found: List[Path] = []
    for pf in sorted(proofs_dir.glob("*.json")):
        if pf.name.endswith("-visual.json"):
            continue
        meta = _parse_proof_raw_meta(pf.read_text(encoding="utf-8", errors="ignore"), pf.name, ticket_by_slug)
        if meta["spec_slug"] in slug_set or (meta["ticket_id"] and meta["ticket_id"] in ticket_set):
            found.append(pf)
    return found


def _collect_matching_disk_proofs(
    roots: List[Path],
    spec_slugs: List[str],
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Path]:
    slug_set = set(spec_slugs)
    ticket_set = {v for v in ticket_by_slug.values() if v}
    found: List[Path] = []
    for root in roots:
        found.extend(_scan_dir_matching_proofs(root / ".edge" / "qa" / "proofs", slug_set, ticket_set, ticket_by_slug))
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
    out: List[str] = []
    for u in val:
        if isinstance(u, str) and u.strip():
            out.append(str(u))
    return out


def _lookup_slug_by_ticket(tid: Optional[str], ticket_by_slug: Dict[str, Optional[str]]) -> str:
    if not tid:
        return ""
    for s, t in ticket_by_slug.items():
        if t == tid:
            return s
    return ""


def _parse_proof_raw_meta(
    raw_text: str,
    rel_path: str,
    ticket_by_slug: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    raw = _load_json_dict(raw_text)
    tid = str(raw.get("ticket_id") or "").strip() or None
    raw_spec = str(raw.get("spec") or "").strip()
    spec_slug = _clean_slug(Path(raw_spec).stem) if raw_spec else _lookup_slug_by_ticket(tid, ticket_by_slug)
    return {
        "spec_slug": spec_slug or _clean_slug(Path(rel_path).stem),
        "ticket_id": tid,
        "screenshot_urls": _extract_str_list(raw.get("screenshot_urls")),
        "directives_checklist": raw.get("directives_checklist"),
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
            "directives_checklist": meta.get("directives_checklist"),
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


def _proof_dedup_key(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    hashes = tuple(sorted((entry.get("screenshot_hashes") or {}).values()))
    return (entry.get("path"), entry.get("spec_slug"), entry.get("ticket_id"), hashes)


def _append_unique_proof(
    ok: bool,
    entry: Dict[str, Any],
    verified: List[Dict[str, Any]],
    failed: List[Dict[str, Any]],
    seen_keys: set,
) -> None:
    key = _proof_dedup_key(entry)
    if key in seen_keys:
        return
    seen_keys.add(key)
    (verified if ok else failed).append(entry)


def _verify_historical_proofs_for_slugs(
    repo: Path,
    eff_base: str,
    roots: List[Path],
    ticket: Optional[Ticket],
    target_slugs: List[str],
    t_map: Dict[str, Optional[str]],
    verified: List[Dict[str, Any]],
    failed: List[Dict[str, Any]],
    seen_keys: set,
) -> None:
    covered_slugs = {e.get("spec_slug") for e in verified}
    for slug in target_slugs:
        if not slug or slug in covered_slugs:
            continue
        for rel_path, raw_text in _discover_historical_proof_blobs(repo, eff_base, slug, t_map.get(slug), t_map):
            ok, entry = _verify_proof_raw_text(raw_text, rel_path, roots, ticket, t_map)
            _append_unique_proof(ok, entry, verified, failed, seen_keys)
            covered_slugs.add(slug)


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
    raw_v, raw_f = _verify_disk_proofs(repo, roots, ticket, proof_files, selected_slug, t_map)
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for e in raw_v:
        _append_unique_proof(True, e, verified, failed, seen_keys)
    for e in raw_f:
        _append_unique_proof(False, e, verified, failed, seen_keys)
    if not eff_base:
        return verified, failed

    target_slugs = [selected_slug] if selected_slug else list(spec_slugs)
    _verify_historical_proofs_for_slugs(
        repo, eff_base, roots, ticket, target_slugs, t_map, verified, failed, seen_keys
    )
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


def _is_meta_spec_or_index(path_str: str, spec_path: str) -> bool:
    norm = _norm_rel_path(path_str)
    if norm == _norm_rel_path(spec_path) or norm == "specs/INDEX.md":
        return True
    return norm.startswith((".edge/specs/", ".edge/archive/specs/"))


def _matches_any_expected(path_str: str, expected_files: List[str]) -> bool:
    norm = _norm_rel_path(path_str)
    return any(fnmatch(norm, pat) or norm == pat for pat in expected_files)


def _classify_audit_files(
    plan: SpecShipPlan,
    actual_code_files: List[str],
) -> Tuple[List[str], List[str], List[str]]:
    realized: List[str] = []
    untouched: List[str] = []
    for raw_exp in plan.expected_files:
        pat = _norm_rel_path(raw_exp)
        hits = [f for f in actual_code_files if fnmatch(f, pat) or f == pat]
        if hits:
            for h in hits:
                if h not in realized:
                    realized.append(h)
        elif not any(ch in pat for ch in "*?[") and not _is_broad_path(pat):
            if pat not in untouched:
                untouched.append(pat)

    unplanned = [
        f for f in actual_code_files
        if not _is_meta_spec_or_index(f, plan.spec_path) and not _matches_any_expected(f, plan.expected_files)
    ]
    return realized, untouched, unplanned


def _build_file_tree_diff(
    realized: List[str],
    unplanned: List[str],
    untouched: List[str],
) -> str:
    diff_lines = [f"+ {f} (expected)" for f in realized]
    diff_lines.extend(f"~ {f} (unplanned)" for f in unplanned)
    diff_lines.extend(f"! {f} (expected but untouched)" for f in untouched)
    if not diff_lines:
        return ""
    if len(diff_lines) > 30:
        extra = len(diff_lines) - 30
        diff_lines = [*diff_lines[:30], f"... (+{extra} more)"]
    return "```diff\n" + "\n".join(diff_lines) + "\n```"


def _collect_proof_evidence_text(verified_proofs: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    checklist_items: List[str] = []
    action_items: List[str] = []
    for p in verified_proofs:
        dc = p.get("directives_checklist")
        if isinstance(dc, dict):
            checklist_items.extend(f"{k}: {v}" for k, v in dc.items())
        elif isinstance(dc, list):
            checklist_items.extend(str(item) for item in dc)
        action_items.extend(str(a) for a in p.get("user_actions_executed", []) or [])
        action_items.extend(str(u) for u in p.get("visited_urls", []) or [])
        db_cc = p.get("db_crosscheck")
        if isinstance(db_cc, dict):
            action_items.extend(str(k) for k in db_cc.keys())
    return checklist_items, action_items


def _tokens_overlap(crit_id: str, exp_text: str, haystack: str) -> bool:
    if crit_id.lower() in haystack:
        return True
    words = [w for w in re.findall(r"[a-z0-9]{4,}", exp_text.lower())]
    if not words:
        return False
    hits = sum(1 for w in words if w in haystack)
    return hits >= min(2, len(words))


def _evaluate_single_criterion(
    crit: Dict[str, str],
    checklist_items: List[str],
    action_items: List[str],
    code_haystack: str,
    has_pass_seal: bool,
    has_realized: bool,
) -> Dict[str, str]:
    cid = crit["id"]
    exp = crit.get("expectation") or crit.get("title") or cid
    chk_hay = "\n".join(checklist_items).lower()
    act_hay = "\n".join(action_items).lower()
    if _tokens_overlap(cid, exp, chk_hay):
        return {"id": cid, "expectation": exp, "status": "✅ Verified", "evidence": "QA directives_checklist"}
    if _tokens_overlap(cid, exp, act_hay):
        return {"id": cid, "expectation": exp, "status": "✅ Verified", "evidence": "QA action / route / DB cross-check"}
    if has_pass_seal and has_realized:
        return {"id": cid, "expectation": exp, "status": "✅ Verified", "evidence": "Examiner PASS seal & realized files"}
    if _tokens_overlap(cid, exp, code_haystack) or has_pass_seal:
        return {"id": cid, "expectation": exp, "status": "☑️ Implemented", "evidence": "Diff / code realization"}
    return {"id": cid, "expectation": exp, "status": "⚠️ Unverified", "evidence": "No matching proof or code trace"}


def _build_criteria_rows(
    digest: Optional[SpecDigest],
    plan: SpecShipPlan,
    examiner_receipt: Optional[Dict[str, Any]],
    actual_code_files: List[str],
    realized_files: List[str],
) -> List[Dict[str, str]]:
    if not digest or not digest.acceptance_criteria:
        return []
    checklist_items, action_items = _collect_proof_evidence_text(plan.verified_proofs)
    has_pass = bool(examiner_receipt and str(examiner_receipt.get("verdict") or "").upper() == "PASS")
    code_parts = [*actual_code_files, *(f"{c.kind} {c.symbol}" for c in plan.index_changes)]
    if examiner_receipt:
        code_parts.append(str(examiner_receipt.get("summary") or ""))
    code_haystack = "\n".join(code_parts).lower()
    return [
        _evaluate_single_criterion(c, checklist_items, action_items, code_haystack, has_pass, bool(realized_files))
        for c in digest.acceptance_criteria
    ]


def _extract_actual_code_files(matched_files: List[str]) -> List[str]:
    actual: List[str] = []
    for raw_path in matched_files:
        if _is_evidence_artifact_path(raw_path):
            continue
        norm = _normalize_display_path(raw_path).lstrip("/")
        if norm and norm not in actual:
            actual.append(norm)
    return actual


def compute_realization_audit(
    plan: SpecShipPlan,
    digest: Optional[SpecDigest],
    examiner_receipt: Optional[Dict[str, Any]],
) -> RealizationAudit:
    """Computes code-only file counts, expected vs. actual file diff, and AC/IC criteria matrix."""
    actual_code_files = _extract_actual_code_files(plan.matched_files)
    realized, untouched, unplanned = _classify_audit_files(plan, actual_code_files)
    file_tree_diff = _build_file_tree_diff(realized, unplanned, untouched)
    criteria_rows = _build_criteria_rows(digest, plan, examiner_receipt, actual_code_files, realized)
    return RealizationAudit(
        actual_code_files=actual_code_files,
        realized_files=realized,
        untouched_expected_files=untouched,
        unplanned_extra_files=unplanned,
        file_tree_diff=file_tree_diff,
        criteria_rows=criteria_rows,
    )


def _format_realization_subsection(audit: Optional[RealizationAudit]) -> List[str]:
    if not audit:
        return []
    lines = [
        "",
        "### Spec Expectations vs. Realization",
        (
            f"- **Files:** `{len(audit.realized_files)}` realized · "
            f"`{len(audit.untouched_expected_files)}` untouched expected · "
            f"`{len(audit.unplanned_extra_files)}` unplanned scope delta"
        ),
    ]
    if audit.file_tree_diff:
        lines.append(audit.file_tree_diff)
    if audit.criteria_rows:
        lines.extend([
            "| ID | Spec Expectation | Status | Realized Evidence / Notes |",
            "| :--- | :--- | :--- | :--- |",
        ])
        for row in audit.criteria_rows:
            exp_clean = str(row["expectation"]).replace("|", "\\|")
            ev_clean = str(row["evidence"]).replace("|", "\\|")
            lines.append(f"| `{row['id']}` | {exp_clean} | {row['status']} | {ev_clean} |")
    return lines


def _format_architecture_subsection(spec_digests: List[SpecDigest]) -> List[str]:
    mermaids: List[str] = []
    callstacks: List[str] = []
    for digest in spec_digests:
        mermaids.extend(digest.mermaid_blocks[:2])
        callstacks.extend(digest.callstack_blocks[:3])
    if not mermaids and not callstacks:
        return []
    lines = ["", "### Architecture & Call-Stack Flow"]
    for m_block in mermaids[:2]:
        lines.extend(["```mermaid", m_block, "```"])
    for c_block in callstacks[:3]:
        lines.extend(["```text", c_block, "```"])
    return lines


def _format_included_specs_subsection(included_plans: List[SpecShipPlan]) -> List[str]:
    if not included_plans:
        return []
    lines = ["", "### Included Specs & Realization"]
    for plan in included_plans:
        title = plan.spec_digest.title if plan.spec_digest and plan.spec_digest.title else plan.spec_slug
        audit = plan.realization_audit
        if audit is not None:
            stats = (
                f"{len(audit.actual_code_files)} code file(s), "
                f"{len(audit.realized_files)} realized / "
                f"{len(audit.untouched_expected_files)} untouched / "
                f"{len(audit.unplanned_extra_files)} unplanned"
            )
        else:
            stats = f"{len(plan.matched_files)} matched file(s)"
        proof_badge = f"✅ {len(plan.verified_proofs)} proof(s)" if plan.verified_proofs else "—"
        lines.append(f"- **{title}** (`{plan.spec_slug}`, branch `{plan.pr_branch}`): {stats} · QA: {proof_badge}")
    return lines


def _format_refactor_summary_block(
    refactor_receipts: List[Dict[str, Any]],
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if not refactor_receipts:
        return []
    lines: List[str] = []
    eff_door = door_type or str(refactor_receipts[0].get("seal_1_intent", {}).get("door_type") or "Two-way door (Reversible Code / Configuration Change)")
    reasons: List[str] = list((blast_radius or {}).get("one_way_reasons") or [])
    for rec in refactor_receipts:
        for r in rec.get("seal_1_intent", {}).get("one_way_reasons") or []:
            if r not in reasons:
                reasons.append(r)

    lines.append(f"- **Door Classification:** {eff_door}")
    if reasons:
        lines.append(f"- **One-Way Reasons:** {'; '.join(reasons)}")

    for rec in refactor_receipts:
        s1 = rec.get("seal_1_intent") or {}
        s2 = rec.get("seal_2_metrics") or {}
        slug = rec.get("slug") or s1.get("slug") or "refactor"
        rules = ", ".join(f"`{r}`" for r in (s1.get("target_rules") or [])) or "—"
        lines.extend([
            "",
            f"### Before/After Metric Delta (`{slug}`)",
            f"- **Intent & Rules:** {rules} (`behavior_preserved: {s1.get('behavior_preserved')}`)",
            "| Metric | Before | Target | After | Delta |",
            "| :--- | ---: | ---: | ---: | ---: |",
        ])
        before = s2.get("before") or {}
        after = s2.get("after") or {}
        targets = s2.get("metric_targets") or {}
        keys = list(dict.fromkeys([*before.keys(), *after.keys(), *targets.keys()]))
        for k in keys:
            b_v = before.get(k)
            t_v = targets.get(k)
            a_v = after.get(k)
            delta_s = f"{a_v - b_v:+g}" if isinstance(b_v, (int, float)) and isinstance(a_v, (int, float)) else "—"
            lines.append(
                f"| `{k}` | {b_v if b_v is not None else 'null'} | "
                f"{t_v if t_v is not None else '—'} | "
                f"{a_v if a_v is not None else 'null'} | {delta_s} |"
            )
    return lines


def _format_refactor_evidence_block(refactor_receipts: List[Dict[str, Any]]) -> List[str]:
    if not refactor_receipts:
        return []
    lines: List[str] = ["", "### RefactorReceipt & Deterministic Gate"]
    for rec in refactor_receipts:
        slug = rec.get("slug") or rec.get("seal_1_intent", {}).get("slug") or "refactor"
        s3 = rec.get("seal_3_gate") or {}
        stages = s3.get("stages") or []
        passed_cnt = sum(1 for st in stages if st.get("passed"))
        lines.append(
            f"- **RefactorReceipt:** `.edge/receipts/refactor/{slug}.json` "
            f"(Gate: `{passed_cnt}/{len(stages)}` stages passed, `all_passed={s3.get('all_passed')}`)"
        )
        s4 = rec.get("seal_4_examiner") or {}
        if s4:
            lines.extend(_format_examiner_seal_block(s4))
    return lines


def _format_summary_section(
    head_branch: str,
    base_branch: str,
    code_count: int,
    index_changes: List[IndexChange],
    context_terms: List[str],
    spec_digests: List[SpecDigest],
    audit: Optional[RealizationAudit] = None,
    included_plans: Optional[List[SpecShipPlan]] = None,
    refactor_receipts: Optional[List[Dict[str, Any]]] = None,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> List[str]:
    lines = [
        "## Summary",
        f"- **Branch:** `{head_branch}` -> `{base_branch}` ({code_count} code file(s) changed)",
    ]
    if index_changes:
        idx_summary = ", ".join(f"`{c.kind} {c.symbol}`" for c in index_changes[:8])
        lines.append(f"- **Navigation Index (`specs/INDEX.md`):** {idx_summary}")
    if context_terms:
        lines.append(f"- **Domain Vocabulary (`CONTEXT.md`):** {', '.join(context_terms)}")
    for digest in spec_digests:
        lines.append(f"- **Spec (`{digest.path}`):** {digest.title}" + (f" — {digest.summary}" if digest.summary else ""))
    if refactor_receipts:
        lines.extend(_format_refactor_summary_block(refactor_receipts, door_type=door_type, blast_radius=blast_radius))
    lines.extend(_format_realization_subsection(audit))
    if audit is None and included_plans:
        lines.extend(_format_included_specs_subsection(included_plans))
    lines.extend(_format_architecture_subsection(spec_digests))
    return lines


def _format_examiner_seal_block(examiner_receipt: Optional[Dict[str, Any]]) -> List[str]:
    if not examiner_receipt:
        return []
    verdict = str(examiner_receipt.get("verdict") or "").upper()
    icon = "✅" if verdict == "PASS" else "❌"
    summary = str(examiner_receipt.get("summary") or "").strip()
    lines = [
        "",
        "### Examiner 3-Axis Seal",
        f"- **Verdict:** {icon} `{verdict}` — {summary}",
    ]
    raw_ev = examiner_receipt.get("evidence_reviewed") or []
    norm_ev = list(dict.fromkeys(_normalize_display_path(str(p)) for p in raw_ev if str(p).strip()))
    if norm_ev:
        lines.extend([f"<details><summary>📂 Reviewed Artifacts ({len(norm_ev)} files)</summary>", ""])
        lines.extend(f"- `{p}`" for p in norm_ev)
        lines.extend(["", "</details>"])
    return lines


def _format_proof_line(p: Dict[str, Any]) -> List[str]:
    shots = len(p.get("screenshot_hashes", {}))
    out = [
        f"- **QA Proof `{p['slug']}`:** ✅ Verified (`persistence_verified: true`, `console_clean: true`, `{shots}` SHA-256 verified screenshot(s))"
    ]
    visited = p.get("visited_urls") or []
    if visited:
        routes = " · ".join(f"`{u}`" for u in visited)
        out.append(f"- **Visited Routes:** {routes}")
    actions = p.get("user_actions_executed") or []
    if actions:
        out.extend([f"<details><summary>⚡ Executed E2E Actions ({len(actions)} steps)</summary>", ""])
        out.extend(f"{idx}. {act}" for idx, act in enumerate(actions, 1))
        out.extend(["", "</details>"])
    db_cc = p.get("db_crosscheck")
    if db_cc:
        pretty_json = json.dumps(db_cc, indent=2, ensure_ascii=False)
        out.extend(["<details><summary>🗄️ Database & State Cross-Check</summary>", "", "```json", pretty_json, "```", "", "</details>"])
    urls = p.get("screenshot_urls") or []
    if urls:
        out.extend(["", "#### Visual Evidence Gallery"])
        for url in urls:
            title = _format_screenshot_title(str(url))
            fname = Path(str(url).split("?")[0]).name or "screenshot.png"
            out.extend([f"- **{title}**", f"  ![{fname}]({url})"])
    return out


def _smoke_metric(smoke_report: Dict[str, Any], key: str, cast: Any, default: Any) -> Any:
    val = smoke_report.get(key)
    return cast(default if val is None else val)


def _format_smoke_audit_block(smoke_report: Optional[Dict[str, Any]]) -> List[str]:
    if not smoke_report:
        return []
    passed = _smoke_metric(smoke_report, "passed_routes", int, 0)
    total = _smoke_metric(smoke_report, "total_routes", int, 0)
    c_errs = _smoke_metric(smoke_report, "total_console_errors", int, 0)
    p_errs = _smoke_metric(smoke_report, "total_page_errors", int, 0)
    slow = _smoke_metric(smoke_report, "slow_routes", int, 0)
    stuck = _smoke_metric(smoke_report, "stuck_routes", int, 0)
    max_settle = _smoke_metric(smoke_report, "max_settle_ms", int, 0)
    max_heap = _smoke_metric(smoke_report, "max_heap_mb", float, 0.0)
    icon = "✅" if smoke_report.get("all_navigable") else "❌"
    return [
        "",
        "### Route Navigability & Console Smoke Audit",
        f"- {icon} {passed}/{total} routes navigable · {c_errs} console errors · {p_errs} page errors",
        f"- Telemetry: slow={slow} · stuck={stuck} · max_settle={max_settle}ms · max_heap={max_heap}MB",
    ]


def _format_security_audit_block(security_report: Optional[Dict[str, Any]]) -> List[str]:
    if not security_report:
        return []
    confirmed = _smoke_metric(security_report, "confirmed_count", int, 0)
    rejected = _smoke_metric(security_report, "rejected_count", int, 0)
    covered = _smoke_metric(security_report, "ledger_covered", int, 0)
    total = _smoke_metric(security_report, "ledger_total", int, 0)
    icon = "✅" if security_report.get("passed") else "❌"
    return [
        "",
        "### Security & ABAC Audit",
        f"- {icon} {confirmed} confirmed vulnerabilities · {rejected} refuted · Shared Ledger: {covered}/{total} units covered",
    ]


def _format_evidence_section(
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    refactor_receipts: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    lines = ["", "## Evidence"]
    if specs_linked:
        lines.append(f"- **Specs:** {', '.join(f'`{s}`' for s in specs_linked)}")
    lines.append(f"- **Gate Status:** {gate_status}")
    if refactor_receipts:
        lines.extend(_format_refactor_evidence_block(refactor_receipts))
        if examiner_receipt:
            lines.extend(_format_examiner_seal_block(examiner_receipt))
    else:
        lines.extend(_format_examiner_seal_block(examiner_receipt))
    if verified_proofs or failed_proofs:
        lines.extend(["", "### Live QA Proof & Visual Evidence"])
        for p in verified_proofs:
            lines.extend(_format_proof_line(p))
        for fp in failed_proofs:
            lines.append(f"- **QA Proof `{fp['slug']}` (FAILED - {fp['error']}):** {fp['message']}")
    lines.extend(_format_smoke_audit_block(smoke_report))
    lines.extend(_format_security_audit_block(security_report))
    return lines


def _format_markdown_sections(
    head_branch: str,
    base_branch: str,
    code_count: int,
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    spec_digests: Optional[List[SpecDigest]] = None,
    audit: Optional[RealizationAudit] = None,
    included_plans: Optional[List[SpecShipPlan]] = None,
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    refactor_receipts: Optional[List[Dict[str, Any]]] = None,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> str:
    """Renders lean 2-section PR body (## Summary + ## Evidence only; no ## Merge Danger)."""
    lines = _format_summary_section(
        head_branch,
        base_branch,
        code_count,
        index_changes,
        context_terms,
        spec_digests or [],
        audit=audit,
        included_plans=included_plans,
        refactor_receipts=refactor_receipts,
        door_type=door_type,
        blast_radius=blast_radius,
    )
    lines.extend(
        _format_evidence_section(
            specs_linked,
            verified_proofs,
            failed_proofs,
            examiner_receipt,
            gate_status,
            smoke_report=smoke_report,
            security_report=security_report,
            refactor_receipts=refactor_receipts,
        )
    )
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


def _clean_pr_title(spec_slug: str, raw_title: str, kind: str = "spec") -> str:
    cleaned = re.sub(r"^[^\w\s]+\s*", "", raw_title or "").strip()
    cleaned = re.sub(r"^(Edge Brigade Specification|Specification|Spec)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    summary = cleaned or f"deliver {spec_slug}"
    prefix = f"refactor({spec_slug}): " if kind == "refactor" else f"feat({spec_slug}): "
    full = f"{prefix}{summary}"
    if len(full) <= 96:
        return full
    budget = 93 - len(prefix)
    if budget <= 0:
        return full[:93].rstrip() + "..."
    candidate = summary[:budget]
    if len(summary) > budget and not summary[budget].isspace() and " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    trimmed = candidate.rstrip(" &-:,/;(\t")
    if not trimmed:
        trimmed = summary[:budget].rstrip()
    return f"{prefix}{trimmed}..."


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
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> None:
    if plan.realization_audit is None:
        plan.realization_audit = compute_realization_audit(plan, plan.spec_digest, plan_receipt)
    code_count = len(plan.realization_audit.actual_code_files)
    digests = [plan.spec_digest] if plan.spec_digest else []
    ref_list = [plan.refactor_receipt] if plan.refactor_receipt else []
    pr_body = _format_markdown_sections(
        plan.pr_branch, base_branch, code_count, plan.index_changes,
        context_terms, [plan.spec_path], plan.verified_proofs, plan.failed_proofs,
        plan_receipt, gate_status, digests, audit=plan.realization_audit,
        refactor_receipts=ref_list, door_type=door_type, blast_radius=blast_radius,
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
    plan.realization_audit = compute_realization_audit(plan, digest, examiner_receipt)
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
    code, out, _ = run_command(["git", "log", "--reverse", "--format=%H%x00%B%x1e", f"{eff_base}..HEAD"], cwd=repo)
    if code != 0 or not out.strip():
        return []
    commits: List[Tuple[str, str, List[str]]] = []
    for record in out.split("\x1e"):
        if "\x00" not in record:
            continue
        sha, msg = record.split("\x00", 1)
        sha = sha.strip()
        if not sha:
            continue
        _, f_out, _ = run_command(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
            cwd=repo,
        )
        c_files = [_norm_rel_path(f) for f in f_out.splitlines() if f.strip()]
        commits.append((sha, msg.strip(), c_files))
    return commits


def _ticket_commit_owners(
    message: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> List[str]:
    owners: List[str] = []
    for p in plans:
        tid = p.ticket_id or ticket_map.get(p.spec_path)
        if tid and re.search(rf"(?<![A-Za-z0-9-]){re.escape(tid)}(?![A-Za-z0-9-])", message):
            owners.append(p.pr_branch)
    return owners


def _explicit_commit_owners(
    subject: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> List[str]:
    tid_owners = _ticket_commit_owners(subject, plans, ticket_map)
    if tid_owners:
        return tid_owners
    low_subj = subject.lower()
    owners: List[str] = []
    for p in plans:
        slug_hit = bool(re.search(rf"(?<![a-z0-9-]){re.escape(p.spec_slug)}(?![a-z0-9-])", low_subj))
        if slug_hit:
            owners.append(p.pr_branch)
    return owners


def _overlap_commit_owners(c_files: List[str], plans: List[SpecShipPlan]) -> List[str]:
    owners: List[str] = []
    for p in plans:
        specific = [pat for pat in p.expected_files if not _is_broad_path(pat)]
        if specific and _match_expected_files(specific, c_files):
            owners.append(p.pr_branch)
    return owners


def _match_commit_owners(
    subject: str,
    c_files: List[str],
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
    last_owner: Optional[str],
) -> List[str]:
    tid_owners = _ticket_commit_owners(subject, plans, ticket_map)
    if tid_owners:
        return tid_owners
    overlap = _overlap_commit_owners(c_files, plans)
    if overlap:
        return overlap
    explicit = _explicit_commit_owners(subject, plans, ticket_map)
    if explicit:
        return explicit
    if last_owner:
        return [last_owner]
    return [plans[0].pr_branch] if len(plans) == 1 else []


def _resolve_spec_commits(
    repo: Path,
    eff_base: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> Tuple[Dict[str, List[str]], Dict[str, bool], Dict[str, List[str]]]:
    """Attributes eff_base..HEAD commits per plan (ticket/file overlap/slug/contiguous)."""
    exclusive: Dict[str, List[str]] = {p.pr_branch: [] for p in plans}
    has_shared: Dict[str, bool] = {p.pr_branch: False for p in plans}
    exc_files: Dict[str, List[str]] = {p.pr_branch: [] for p in plans}
    last_owner: Optional[str] = None
    for sha, subj, c_files in _list_range_commits(repo, eff_base):
        owners = _match_commit_owners(subj, c_files, plans, ticket_map, last_owner)
        if len(owners) == 1:
            owner_key = owners[0]
            exclusive[owner_key].append(sha)
            exc_files[owner_key].extend(f for f in c_files if f not in exc_files[owner_key])
            last_owner = owner_key
        else:
            for owner_key in owners:
                has_shared[owner_key] = True
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
        key = plan.pr_branch
        if not has_shared.get(key):
            plan.commit_shas = list(exclusive.get(key, []))
        for cf in exc_files.get(key, []):
            if not cf.startswith(".edge/") and cf not in plan.matched_files:
                plan.matched_files.append(cf)
        plan.index_changes = _filter_plan_index_changes(
            index_changes, plan.spec_slug, plan.spec_path, plan.matched_files
        )


def _read_existing_ship_branch_files(
    repo: Path,
    eff_base: str,
    pr_branch: str,
) -> Optional[List[str]]:
    rc, _, _ = run_command(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{pr_branch}"],
        cwd=repo,
    )
    if rc != 0:
        return None
    d_rc, d_out, _ = run_command(
        ["git", "diff", "--name-only", f"{eff_base}..{pr_branch}"],
        cwd=repo,
    )
    if d_rc != 0 or not d_out.strip():
        return None
    return [_norm_rel_path(line) for line in d_out.splitlines() if line.strip()]


def _merge_branch_code_files(matched_files: List[str], branch_files: List[str]) -> List[str]:
    meta = [
        _norm_rel_path(p) for p in matched_files
        if _norm_rel_path(p).startswith(".edge/") and not _is_evidence_artifact_path(p)
    ]
    code = [
        bf for bf in branch_files
        if not bf.startswith(".edge/") and not _is_evidence_artifact_path(bf)
    ]
    return list(dict.fromkeys([*meta, *code]))


def _scope_plans_to_existing_ship_branches(
    repo: Path,
    eff_base: str,
    plans: List[SpecShipPlan],
    index_changes: List[IndexChange],
) -> None:
    for plan in plans:
        branch_files = _read_existing_ship_branch_files(repo, eff_base, plan.pr_branch)
        if not branch_files:
            continue
        plan.matched_files = _merge_branch_code_files(plan.matched_files, branch_files)
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


def _prepare_split_branch_context(
    repo: Path,
) -> Tuple[bool, str, str, set, str]:
    st_code, st_out, _ = run_command(["git", "status", "--porcelain"], cwd=repo)
    if st_code != 0 or st_out.strip():
        return False, "", "", set(), "Working tree must be clean before running --split-branches."

    _, orig_branch, _ = run_command(["git", "branch", "--show-current"], cwd=repo)
    _, head_sha, _ = run_command(["git", "rev-parse", "HEAD"], cwd=repo)
    head_sha = head_sha.strip()
    orig_ref = orig_branch.strip() or head_sha

    ls_code, ls_out, ls_err = run_command(["git", "ls-tree", "-r", "--name-only", head_sha], cwd=repo)
    if ls_code != 0:
        return False, "", "", set(), f"Failed to inspect HEAD tree: {ls_err}"
    head_tree: set = set()
    for line in ls_out.splitlines():
        if line.strip():
            head_tree.add(_norm_rel_path(line))
    return True, head_sha, orig_ref, head_tree, ""


def create_split_branches(
    repo: Path,
    eff_base: str,
    spec_plans: List[SpecShipPlan],
    ticket_map: Optional[Dict[str, str]] = None,
) -> Tuple[bool, List[str], str]:
    """Creates isolated ship/<spec-slug> branches off eff_base, always restoring original HEAD."""
    if not spec_plans:
        return True, [], ""

    ctx_ok, head_sha, orig_ref, head_tree, ctx_err = _prepare_split_branch_context(repo)
    if not ctx_ok:
        return False, [], ctx_err
    exclusive, has_shared, _ = _resolve_spec_commits(repo, eff_base, spec_plans, ticket_map or {})

    created: List[str] = []
    try:
        for plan in spec_plans:
            ok, err = _materialize_single_branch(
                repo, eff_base, head_sha, head_tree, plan,
                exclusive_commits=exclusive.get(plan.pr_branch, []),
                has_shared_commits=has_shared.get(plan.pr_branch, False),
            )
            if not ok:
                return False, created, err
            created.append(plan.pr_branch)
    finally:
        run_command(["git", "checkout", orig_ref], cwd=repo)

    return True, created, ""


def _redact_url_credentials(text: str) -> str:
    """Masks userinfo credentials inside URL strings with '<redacted>@'."""
    return _URL_USERINFO_RE.sub(r"\1<redacted>@", text or "")


def _extract_github_path_pair(path: str) -> Optional[Tuple[str, str]]:
    cleaned = path.strip().strip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    parts = [p for p in cleaned.split("/") if p]
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


def parse_github_owner_repo(remote_url: str) -> Optional[Tuple[str, str]]:
    """Extracts (owner, repo) from SSH, SCP, or HTTPS GitHub remote URLs (including userinfo)."""
    raw = (remote_url or "").strip()
    if not raw:
        return None
    scp_match = re.match(r"^[^\s/@:]+@github\.com:(.+)$", raw)
    if scp_match:
        return _extract_github_path_pair(scp_match.group(1))
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https", "ssh") or (parsed.hostname or "").lower() != "github.com":
        return None
    return _extract_github_path_pair(parsed.path)


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
            return False, f"Failed to hash screenshot '{resolved}': {_redact_url_credentials(h_err)}"
        u_code, _, u_err = _run_git_with_env(
            repo,
            ["update-index", "--add", "--cacheinfo", f"100644,{blob_sha.strip()},{stage_path}"],
            env,
        )
        if u_code != 0:
            return False, f"Failed to stage evidence '{stage_path}': {_redact_url_credentials(u_err)}"
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
        return False, "", f"Failed to write evidence tree: {_redact_url_credentials(w_err)}"
    args = ["commit-tree", tree_sha.strip()]
    if parent_sha:
        args.extend(["-p", parent_sha])
    args.extend(["-m", f"chore(qa-evidence): publish {', '.join(slugs)}"])
    c_code, c_sha, c_err = run_command(["git", *args], cwd=repo)
    if c_code != 0:
        return False, "", f"Failed to commit evidence tree: {_redact_url_credentials(c_err)}"
    commit_sha = c_sha.strip()
    run_command(["git", "update-ref", f"refs/heads/{evidence_branch}", commit_sha], cwd=repo)
    p_code, _, p_err = run_command(["git", "push", "origin", f"refs/heads/{evidence_branch}"], cwd=repo)
    if p_code != 0:
        return False, commit_sha, f"Failed to push '{evidence_branch}' to origin: {_redact_url_credentials(p_err)}"
    return True, commit_sha, ""


def _resolve_github_target(repo: Path) -> Tuple[bool, str, str, str]:
    r_code, remote_url, r_err = run_command(["git", "remote", "get-url", "origin"], cwd=repo)
    if r_code != 0 or not remote_url.strip():
        return False, "", "", f"Cannot publish evidence: missing git remote 'origin' ({_redact_url_credentials(r_err)})."
    parsed = parse_github_owner_repo(remote_url.strip())
    if not parsed:
        masked = _redact_url_credentials(remote_url.strip())
        return False, "", "", f"Cannot publish evidence: origin remote '{masked}' is not GitHub."
    return True, parsed[0], parsed[1], ""


def _bind_evidence_urls(
    shots: List[Tuple[Dict[str, Any], Path, str]],
    owner: str,
    repo_name: str,
    commit_sha: str,
) -> None:
    for proof, _, stage_path in shots:
        raw_url = f"https://github.com/{owner}/{repo_name}/blob/{commit_sha}/{stage_path}?raw=true"
        urls = proof.setdefault("screenshot_urls", [])
        if raw_url not in urls:
            urls.append(raw_url)


def publish_screenshots_to_evidence_branch(
    repo: Path,
    evidence_branch: str,
    spec_plans: List[SpecShipPlan],
    search_roots: List[Path],
) -> Tuple[bool, str]:
    """Publishes QA screenshots onto an orphan branch without switching HEAD and binds permanent GitHub URLs."""
    gh_ok, owner, repo_name, gh_err = _resolve_github_target(repo)
    if not gh_ok:
        return False, gh_err

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

    _bind_evidence_urls(shots, owner, repo_name, commit_sha)
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
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    spec_digests: List[SpecDigest],
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    door_type: str = "",
    blast_radius: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    if sel_slug and len(selected_plans) == 1:
        return selected_plans[0].pr_body, selected_plans[0].show_me_body
    code_count = len([f for f in changed_files if not _is_evidence_artifact_path(f)])
    refactor_receipts = [p.refactor_receipt for p in selected_plans if p.kind == "refactor" and p.refactor_receipt]
    pr_body = _format_markdown_sections(
        head_branch,
        base_branch,
        code_count,
        index_changes,
        context_terms,
        specs_linked,
        verified_proofs,
        failed_proofs,
        examiner_receipt,
        gate_status,
        spec_digests,
        included_plans=selected_plans,
        smoke_report=smoke_report,
        security_report=security_report,
        refactor_receipts=refactor_receipts,
        door_type=door_type,
        blast_radius=blast_radius,
    )
    ship_cmd = f"gh pr create --base {shlex.quote(base_branch)} --head {shlex.quote(head_branch)}"
    return pr_body, f"{pr_body}\n\n## Ship Command\n```bash\n{ship_cmd}\n```"


def _check_tier2_smoke_report(
    repo: Path,
    base_branch: str,
    require_smoke: bool,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    staging_branch = eff_stages.get("staging", "staging")
    raw_base = (base_branch or "").strip()
    clean_base = raw_base[7:] if raw_base.startswith("origin/") else raw_base
    if clean_base != staging_branch:
        return True, None, ""
    smoke_file = repo / ".edge" / "qa" / "smoke-routes.json"
    if not smoke_file.is_file():
        if require_smoke:
            return (
                False,
                None,
                "Tier 2 staging release blocked: Route smoke scan report missing at "
                ".edge/qa/smoke-routes.json. Run 'brigade smoke-routes .' first.",
            )
        return True, None, ""
    try:
        raw = json.loads(smoke_file.read_text(encoding="utf-8"))
        report = SmokeScanReport.from_dict(raw)
    except Exception:
        return False, None, "Tier 2 staging release blocked: Malformed smoke scan report at .edge/qa/smoke-routes.json."
    if not report.all_navigable:
        triage_smoke_failures(repo, report)
        return (
            False,
            report.to_dict(),
            f"Tier 2 staging release blocked: Route smoke scan failed "
            f"({report.failed_routes}/{report.total_routes} route(s) non-navigable).",
        )
    return True, report.to_dict(), ""


def _check_tier2_security_audit(
    repo: Path,
    base_branch: str,
    eff_base: str,
    changed_files: List[str],
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    eff_stages = stage_branches or DEFAULT_STAGE_BRANCHES
    staging_branch = eff_stages.get("staging", "staging")
    raw_base = (base_branch or "").strip()
    clean_base = raw_base[7:] if raw_base.startswith("origin/") else raw_base
    if clean_base != staging_branch:
        return True, None, ""
    sec_report = run_security_audit(
        repo, diff_only=True, base_ref=eff_base, changed_files=changed_files
    )
    if not sec_report.passed:
        triage_security_findings(repo, sec_report)
        return (
            False,
            sec_report.to_dict(),
            f"Tier 2 staging release blocked: Security audit found "
            f"{sec_report.confirmed_count} confirmed vulnerability/ies.",
        )
    return True, sec_report.to_dict(), ""


def _run_tier2_gates(
    repo: Path,
    base_branch: str,
    eff_base: str,
    changed_files: List[str],
    require_smoke: bool,
    eff_stages: Dict[str, str],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], str]:
    smoke_ok, smoke_report, smoke_err = _check_tier2_smoke_report(
        repo, base_branch, require_smoke, stage_branches=eff_stages
    )
    sec_ok, sec_report, sec_err = _check_tier2_security_audit(
        repo, base_branch, eff_base, changed_files, stage_branches=eff_stages
    )
    gate_err = smoke_err if not smoke_ok else (sec_err if not sec_ok else "")
    return smoke_report, sec_report, gate_err


def _validate_ship_result(
    result: ShipPrepResult,
    strict_proofs: bool,
    split_branches: bool,
    repo: Path,
    eff_base: str,
    ticket_map: Optional[Dict[str, str]] = None,
    gate_err: str = "",
) -> Tuple[bool, ShipPrepResult, str]:
    if gate_err:
        return False, result, gate_err
    if result.failed_proofs:
        return False, result, f"ProofVerifier rejected {len(result.failed_proofs)} QA proof receipt(s)."
    for plan in result.spec_plans:
        if plan.kind == "refactor" and plan.refactor_receipt is not None:
            v_ok, v_msg, _ = RefactorReceiptVerifier.verify_receipt(plan.refactor_receipt, strict=True)
            if not v_ok:
                return False, result, f"RefactorReceipt blocked ({plan.spec_slug}): {v_msg}"
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


def _discover_specs_and_tickets(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    receipts_by_ticket: Dict[str, Dict[str, Any]],
) -> Tuple[List[str], Dict[str, str], Dict[str, Optional[str]]]:
    disk_specs = _list_disk_spec_candidates(repo)
    ticket_map = _resolve_spec_ticket_ids(repo, eff_base, disk_specs, receipts_by_ticket)
    specs_linked = discover_changed_specs(
        repo, eff_base, changed_files, index_changes, ticket_map=ticket_map, history_receipts=receipts_by_ticket
    )
    extra_specs = [s for s in specs_linked if s not in ticket_map]
    if extra_specs:
        ticket_map.update(_resolve_spec_ticket_ids(repo, eff_base, extra_specs, receipts_by_ticket))
    ticket_by_slug: Dict[str, Optional[str]] = {}
    for spec_rel in specs_linked:
        ticket_by_slug[_clean_slug(Path(spec_rel).stem)] = ticket_map.get(spec_rel)
    return specs_linked, ticket_map, ticket_by_slug


def _maybe_publish_plan_evidence(
    repo: Path,
    publish_evidence: bool,
    failed_proofs: List[Dict[str, Any]],
    evidence_branch: str,
    selected_plans: List[SpecShipPlan],
    ticket: Optional[Ticket],
) -> Tuple[bool, str]:
    if not publish_evidence or failed_proofs:
        return True, ""
    return publish_screenshots_to_evidence_branch(
        repo, evidence_branch, selected_plans, _proof_search_roots(repo, ticket)
    )


def _discover_refactor_receipts(
    repo: Path,
    changed_files: List[str],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Discovers valid (non-stale) refactor receipts pinned under target_repo/.edge/receipts/refactor/."""
    roots = [resolve_target_repo_root(repo)]
    if repo not in roots:
        roots.append(repo)

    _, head_out, _ = run_command(["git", "rev-parse", "HEAD"], cwd=repo)
    head_sha = head_out.strip()
    cur_diff_hash = compute_changed_files_hash(changed_files) if changed_files else ""

    discovered: List[Tuple[str, Dict[str, Any]]] = []
    seen_slugs: set = set()
    for root in roots:
        rec_dir = root / ".edge" / "receipts" / "refactor"
        if not rec_dir.is_dir():
            continue
        for json_file in sorted(rec_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            s1 = data.get("seal_1_intent")
            if not isinstance(s1, dict):
                continue
            rec_sha = str(s1.get("commit_sha") or "").strip()
            rec_hash = str(s1.get("changed_files_hash") or "").strip()
            if not ((head_sha and rec_sha == head_sha) or (cur_diff_hash and rec_hash == cur_diff_hash)):
                continue
            slug = _clean_slug(str(data.get("slug") or s1.get("slug") or json_file.stem))
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            discovered.append((f".edge/receipts/refactor/{json_file.name}", data))
    return discovered


def _build_refactor_plans(
    refactor_receipts: List[Tuple[str, Dict[str, Any]]],
    base_branch: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    gate_status: str,
    used_branches: set,
    door_type: str,
    blast_radius: Dict[str, Any],
) -> List[SpecShipPlan]:
    plans: List[SpecShipPlan] = []
    for rel_path, rec in refactor_receipts:
        s1 = rec.get("seal_1_intent") or {}
        slug = _clean_slug(str(rec.get("slug") or s1.get("slug") or Path(rel_path).stem))
        tid = str(rec.get("ticket_id") or s1.get("ticket_id") or "") or None
        rec_files = [_norm_rel_path(f) for f in (s1.get("changed_files") or []) if str(f).strip()]
        target_files = [_norm_rel_path(f) for f in (s1.get("target_files") or []) if str(f).strip()]
        expected = list(dict.fromkeys([*rec_files, *target_files]))
        matched = _match_expected_files(expected, changed_files) or list(rec_files)

        cand_branch = f"ship/{slug}"
        if cand_branch in used_branches:
            cand_branch = f"ship/refactor-{slug}"
        used_branches.add(cand_branch)

        rules = [str(r) for r in (s1.get("target_rules") or []) if str(r).strip()]
        raw_title = f"refactor {', '.join(rules)}" if rules else f"clean {slug}"
        pr_title = _clean_pr_title(slug, raw_title, kind="refactor")

        plan = SpecShipPlan(
            spec_slug=slug,
            spec_path=rel_path,
            pr_branch=cand_branch,
            pr_title=pr_title,
            expected_files=expected,
            matched_files=matched,
            index_changes=_filter_plan_index_changes(index_changes, slug, rel_path, matched),
            ticket_id=tid,
            kind="refactor",
            refactor_receipt=rec,
        )
        eff_door = str(s1.get("door_type") or door_type)
        eff_blast = dict(blast_radius)
        if s1.get("one_way_reasons"):
            eff_blast["one_way_reasons"] = list(dict.fromkeys([
                *(eff_blast.get("one_way_reasons") or []),
                *(s1.get("one_way_reasons") or []),
            ]))
        _render_plan_bodies(
            plan,
            base_branch,
            context_terms,
            rec.get("seal_4_examiner") or None,
            gate_status,
            door_type=eff_door,
            blast_radius=eff_blast,
        )
        plans.append(plan)
    return plans


def _assemble_ship_result(
    base_branch: str,
    head_branch: str,
    door_type: str,
    blast_radius: Dict[str, Any],
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    changed_files: List[str],
    selected_plans: List[SpecShipPlan],
    sel_slug: Optional[str],
    gate_status: str,
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
) -> ShipPrepResult:
    spec_digests = [p.spec_digest for p in selected_plans if p.spec_digest]
    pr_body, show_me_body = _render_top_level_bodies(
        sel_slug, selected_plans, head_branch, base_branch, changed_files,
        index_changes, context_terms, specs_linked, verified_proofs, failed_proofs,
        examiner_receipt, gate_status, spec_digests, smoke_report=smoke_report, security_report=security_report,
        door_type=door_type, blast_radius=blast_radius,
    )
    return ShipPrepResult(
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
        smoke_report=smoke_report,
        security_report=security_report,
    )


def _compute_search_tokens(blast_radius: Dict[str, Any], index_changes: List[IndexChange]) -> List[str]:
    tokens = list(blast_radius.get("domains", []))
    for ch in index_changes:
        tokens.append(ch.symbol.lower())
    return list(dict.fromkeys(tokens))


def prepare_ship_payload(
    repo_path: Path,
    base_branch: str = "development",
    strict_proofs: bool = False,
    spec_slug: Optional[str] = None,
    split_branches: bool = False,
    publish_evidence: bool = False,
    evidence_branch: str = "edge-qa-evidence",
    require_smoke: bool = False,
    allow_topology_override: bool = False,
    stage_branches: Optional[Dict[str, str]] = None,
) -> Tuple[bool, ShipPrepResult, str]:
    """Collects per-spec and refactor ship plans, scoped ProofVerifier results, optional evidence publishing, and PR bodies."""
    repo = normalize_target_path(repo_path)
    head_branch = _get_head_branch(repo)
    eff_stages = resolve_stage_branches(repo, stage_branches)
    topo_ok, topo_err = validate_branch_topology(
        base_branch,
        head_branch,
        split_branches=split_branches,
        allow_override=allow_topology_override,
        stage_branches=eff_stages,
    )
    if not topo_ok:
        return False, _empty_result(base_branch, head_branch), topo_err

    eff_base = _resolve_base_ref(repo, base_branch, head_branch=head_branch, stage_branches=eff_stages)
    if not eff_base:
        return False, _empty_result(base_branch, head_branch), f"Git base branch '{base_branch}' not found in {repo}."

    diff_ok, head_branch, changed_files, diff_stat, idx_diff, diff_err = _collect_git_diff_bundle(repo, eff_base)
    if not diff_ok:
        return False, _empty_result(base_branch, head_branch), diff_err

    _, diff_text, _ = run_command(["git", "diff", f"{eff_base}..HEAD"], cwd=repo)
    index_changes = parse_index_diff(idx_diff)
    ticket, examiner_receipt, gate_status, receipts_by_ticket = _load_brigade_history_snapshot(repo)
    refactor_receipts = _discover_refactor_receipts(repo, changed_files)
    is_refactor_slice = (
        head_branch.startswith("refactor/")
        or bool(refactor_receipts)
        or (ticket is not None and getattr(ticket, "track", "") in ("core", "ui"))
    )
    door_type, blast_radius = classify_merge_danger(
        changed_files, diff_stat, diff_text=diff_text, is_refactor=is_refactor_slice
    )
    for _, rec in refactor_receipts:
        s1 = rec.get("seal_1_intent") or {}
        for reason in s1.get("one_way_reasons") or []:
            if reason not in blast_radius["one_way_reasons"]:
                blast_radius["one_way_reasons"].append(reason)
        rec_door = str(s1.get("door_type") or "")
        if rec_door.startswith("One-way") and not door_type.startswith("One-way"):
            door_type = rec_door

    context_terms = _read_context_terms(repo, _compute_search_tokens(blast_radius, index_changes))
    specs_linked, ticket_map, ticket_by_slug = _discover_specs_and_tickets(
        repo, eff_base, changed_files, index_changes, receipts_by_ticket
    )

    selected_slug = _clean_slug(spec_slug) if spec_slug else None
    verified_proofs, failed_proofs = _verify_scoped_proofs(
        repo, ticket, list(ticket_by_slug.keys()), changed_files,
        selected_slug=selected_slug, eff_base=eff_base, ticket_by_slug=ticket_by_slug,
    )
    spec_plans, plan_receipts = _build_all_spec_plans(
        repo, specs_linked, base_branch, changed_files, index_changes,
        context_terms, verified_proofs, failed_proofs, examiner_receipt, receipts_by_ticket, gate_status, ticket_map,
    )
    used_branches = {p.pr_branch for p in spec_plans}
    refactor_plans = _build_refactor_plans(
        refactor_receipts, base_branch, changed_files, index_changes,
        context_terms, gate_status, used_branches, door_type, blast_radius,
    )
    all_plans = [*spec_plans, *refactor_plans]
    exclusive, has_shared, exc_files = _resolve_spec_commits(repo, eff_base, all_plans, ticket_map)
    _apply_slice_commits_to_plans(all_plans, exclusive, has_shared, exc_files, index_changes)
    if not split_branches:
        _scope_plans_to_existing_ship_branches(repo, eff_base, all_plans, index_changes)

    sel_ok, selected_plans, sel_slug, sel_err = _select_spec_plans(all_plans, spec_slug, eff_base)
    if not sel_ok:
        res_err = _empty_result(base_branch, head_branch)
        res_err.spec_plans = all_plans
        res_err.selected_spec = sel_slug
        return False, res_err, sel_err

    pub_ok, pub_err = _maybe_publish_plan_evidence(
        repo, publish_evidence, failed_proofs, evidence_branch, selected_plans, ticket
    )
    if not pub_ok:
        res_pub_err = _empty_result(base_branch, head_branch)
        res_pub_err.spec_plans = selected_plans
        res_pub_err.verified_proofs = verified_proofs
        return False, res_pub_err, pub_err

    for plan in selected_plans:
        if plan.kind == "refactor":
            rec_ex = (plan.refactor_receipt or {}).get("seal_4_examiner") or None
            _render_plan_bodies(
                plan, base_branch, context_terms, rec_ex, gate_status,
                door_type=door_type, blast_radius=blast_radius,
            )
        else:
            p_rec = plan_receipts.get(plan.spec_slug)
            plan.realization_audit = compute_realization_audit(plan, plan.spec_digest, p_rec)
            _render_plan_bodies(plan, base_branch, context_terms, p_rec, gate_status)

    smoke_report, sec_report, gate_err = _run_tier2_gates(
        repo, base_branch, eff_base, changed_files, require_smoke, eff_stages
    )
    result = _assemble_ship_result(
        base_branch, head_branch, door_type, blast_radius, index_changes, context_terms,
        specs_linked, verified_proofs, failed_proofs, examiner_receipt, changed_files,
        selected_plans, sel_slug, gate_status, smoke_report=smoke_report, security_report=sec_report,
    )
    return _validate_ship_result(
        result,
        strict_proofs,
        split_branches,
        repo,
        eff_base,
        ticket_map=ticket_map,
        gate_err=gate_err,
    )


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
            "smoke_report": result.smoke_report,
            "security_report": result.security_report,
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return result.pr_body
