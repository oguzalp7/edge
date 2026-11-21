"""Incremental Security Audit, Automated Refutation, Shared Coverage Ledger & Core Triage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from .fsm import BrigadeFSM
    from .models import CycleState, Ticket, TransitionLog
except ImportError:
    from tools.brigade.fsm import BrigadeFSM
    from tools.brigade.models import CycleState, Ticket, TransitionLog


_AUDIT_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py"}
_JS_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
_USE_SERVER_DIRECTIVE_RE = re.compile(r'^\s*["\']use server["\']\s*;?\s*$', re.MULTILINE)
_IGNORED_DIRS = {".git", "node_modules", ".next", "dist", "build", ".edge", "__pycache__", "tests", "__tests__"}
_VALID_VERDICTS = {"confirmed", "needs_validation", "rejected"}
_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
_VALID_LEDGER_STATUSES = {"covered", "planned", "out_of_scope"}

_PRIV_BYPASS_RE = re.compile(r"\b(system-caller|bypassAuth|skipAuth)\b")
_ABAC_SINK_RE = re.compile(r"\b(db\.(?:insert|update|delete)|[A-Za-z0-9_]*Repository\.[A-Za-z0-9_]+|\.upsert\s*\()")
_ABAC_GUARD_RE = re.compile(
    r"\b(?:requireAuth|getCurrentSessionAction|assert[A-Za-z0-9_]*Access|evaluate[A-Za-z0-9_]*Access|getSession|checkPermission|getServerSession|auth)\s*\("
)
_TOKEN_GUARD_RE = re.compile(
    r"\b(?:hashInvitationToken|verify[A-Za-z0-9_]*Token|validate[A-Za-z0-9_]*Token|timingSafeEqual)\s*\("
)
_POLICY_AUTH_FIELD_RE = re.compile(r"\b(?:minAuthLevel|authLevel|requireAuth)\b")
_RUN_ACTION_CALL_RE = re.compile(r"\brunAction(?:\s*<[^>]*>)?\s*\(\s*([^,)]+)")
_READ_ONLY_REPO_METHOD_RE = re.compile(
    r"^[A-Za-z0-9_]*Repository\.(?:find|list|get|search|lookup|count|exists|validate)[A-Za-z0-9_]*$"
)
_DATA_MUTATION_RE = re.compile(r"\bdb\.(update|delete)\s*\(")
_SQL_RAW_INTERP_RE = re.compile(r"sql\.raw\s*\([^)]*\$\{")
_DANGEROUS_HTML_RE = re.compile(r"\bdangerouslySetInnerHTML\b")
_HTML_SANITIZER_RE = re.compile(r"\b(?:DOMPurify|sanitize[A-Za-z0-9_]*)\b")
_CMD_EXEC_RE = re.compile(r"(?:\bchild_process\.exec\s*\(|\bexecSync\s*\(|\bos\.system\s*\(|\bsubprocess\.run\s*\([^)]*shell\s*=\s*True)")
_PY_CMD_EXEC_RE = re.compile(r"(?:\bos\.system\s*\(|\bsubprocess\.run\s*\([^)]*shell\s*=\s*True)")
_EVAL_SINK_RE = re.compile(r"(?:\beval\s*\(|\bnew\s+Function\s*\()")
_PY_EVAL_SINK_RE = re.compile(r"\beval\s*\(")
_MATH_RANDOM_RE = re.compile(r"\bMath\.random\s*\(")
_SEC_CTX_RE = re.compile(r"\b(?:token|secret|otp|password|key|salt|nonce|session|auth)\b", re.IGNORECASE)
_HARDCODED_SECRET_RE = re.compile(r"(?:sk_live_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16})")
_FN_START_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*\*?\s*([A-Za-z0-9_$]+)|(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^>]*>\s*)?\()"
)
_PY_FN_START_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\(")
_POLICY_OBJ_START_RE = re.compile(r"^(?:export\s+)?const\s+([A-Za-z0-9_$]+)\s*=\s*\{")
_POLICY_KEY_START_RE = re.compile(r"^\s*([A-Za-z0-9_$]+)\s*:\s*\{")
_EXPORT_SPEC_RE = re.compile(r"\bexport\s+(?:type\s+)?\{([^}]*)\}")


@dataclass
class CoverageUnit:
    coverage_id: str
    file_path: str
    file_sha256: str
    surface: str
    boundary: str
    attack_class: str
    status: str  # "covered" | "planned" | "out_of_scope"
    last_audited_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageUnit":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class CoverageLedger:
    version: str = "1.0.0"
    updated_at: str = ""
    units: List[CoverageUnit] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "units": [u.to_dict() for u in self.units],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageLedger":
        raw_units = data.get("units") or []
        units = [CoverageUnit.from_dict(u) if isinstance(u, dict) else u for u in raw_units]
        return cls(
            version=str(data.get("version") or "1.0.0"),
            updated_at=str(data.get("updated_at") or ""),
            units=units,
        )


@dataclass
class SecurityTrace:
    entrypoint: str
    propagation: List[str] = field(default_factory=list)
    sink: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityFinding:
    finding_id: str
    fingerprint: str
    verdict: str  # "confirmed" | "needs_validation" | "rejected"
    severity: Optional[str]
    attack_class: str
    boundary: str
    trace: Dict[str, Any]
    evidence: str
    rejection_reason: Optional[str] = None
    blocker: Optional[str] = None
    fix_target: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityFinding":
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


@dataclass
class SecurityAuditReport:
    scope_label: str
    audited_at: str
    profile: str
    confirmed_count: int
    needs_validation_count: int
    rejected_count: int
    ledger_covered: int
    ledger_total: int
    passed: bool
    findings: List[SecurityFinding] = field(default_factory=list)
    triage_tickets_created: List[str] = field(default_factory=list)
    schema_version: str = "1.0.0"

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["findings"] = [f.to_dict() for f in self.findings]
        return payload

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecurityAuditReport":
        raw = dict(data)
        raw_findings = raw.get("findings") or []
        raw["findings"] = [
            SecurityFinding.from_dict(f) if isinstance(f, dict) else f for f in raw_findings
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


def _validate_single_finding(f: SecurityFinding) -> List[str]:
    errs: List[str] = []
    if f.verdict not in _VALID_VERDICTS:
        errs.append(f"{f.finding_id}: invalid verdict '{f.verdict}'")
    if f.verdict == "confirmed":
        if f.severity not in _VALID_SEVERITIES:
            errs.append(f"{f.finding_id}: confirmed finding missing valid severity")
        if not f.trace.get("entrypoint") or not f.trace.get("sink"):
            errs.append(f"{f.finding_id}: confirmed finding requires trace.entrypoint and trace.sink")
        return errs
    if f.severity is not None:
        errs.append(f"{f.finding_id}: unconfirmed finding ({f.verdict}) must have severity=None")
    if f.verdict == "rejected" and not (f.rejection_reason or "").strip():
        errs.append(f"{f.finding_id}: rejected finding requires rejection_reason")
    return errs


def validate_security_artifacts(
    ledger: CoverageLedger,
    findings: List[SecurityFinding],
) -> Tuple[bool, List[str]]:
    """Enforces Cloudflare 3-verdict invariants (non-confirmed => severity=None) and ledger schema."""
    errors: List[str] = []
    for unit in ledger.units:
        if unit.status not in _VALID_LEDGER_STATUSES:
            errors.append(f"{unit.coverage_id}: invalid status '{unit.status}'")
        if unit.status == "covered" and not (unit.file_sha256 or "").strip():
            errors.append(f"{unit.coverage_id}: covered unit missing file_sha256")
    for finding in findings:
        errors.extend(_validate_single_finding(finding))
    return (len(errors) == 0), errors


def _is_auditable_source(path: Path, rel_posix: str) -> bool:
    if not path.is_file() or path.suffix not in _AUDIT_EXTS:
        return False
    if set(path.parts) & _IGNORED_DIRS:
        return False
    name = path.name
    return not (name.startswith("test_") or "_test." in name or ".test." in name or ".spec." in name)


def _discover_repo_sources(repo: Path) -> Dict[str, Path]:
    sources: Dict[str, Path] = {}
    for p in sorted(repo.rglob("*")):
        try:
            rel = p.relative_to(repo).as_posix()
        except ValueError:
            continue
        if _is_auditable_source(p, rel):
            sources[rel] = p
    return sources


def _expand_scopes(scopes: Optional[List[str]]) -> List[str]:
    tokens: List[str] = []
    for item in scopes or []:
        for part in str(item).split(","):
            clean = part.strip().replace("\\", "/").lstrip("./").rstrip("/")
            if clean:
                tokens.append(clean)
    return tokens


def _matches_scope(rel: str, scope_tokens: List[str]) -> bool:
    for tok in scope_tokens:
        if rel == tok or rel.startswith(tok + "/") or fnmatch(rel, tok):
            return True
    return False


def _git_diff_rel_files(repo: Path, base_ref: Optional[str]) -> Set[str]:
    args = ["diff", "--name-only", f"{base_ref}..HEAD"] if base_ref else ["diff", "--name-only", "HEAD"]
    try:
        proc = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, timeout=15)
        out = proc.stdout if proc.returncode == 0 else ""
    except Exception:
        out = ""
    return {ln.strip().replace("\\", "/").lstrip("./") for ln in out.splitlines() if ln.strip()}


def _classify_surface_and_boundary(rel: str, content: str) -> Tuple[str, str]:
    is_js_ts = Path(rel).suffix.lower() in _JS_TS_EXTS
    if rel.startswith("src/actions/") or (is_js_ts and bool(_USE_SERVER_DIRECTIVE_RE.search(content))):
        return "server_action", "auth_abac"
    if "/api/" in f"/{rel}":
        return "api_route", "auth_abac"
    if rel.startswith("src/core/") or rel.startswith("core/"):
        return "core_module", "domain_isolation"
    if rel.endswith((".tsx", ".jsx")):
        return "component", "xss_sink"
    return "module", "boundary"


def _ast_call_name(func_node: ast.AST) -> str:
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute) and isinstance(func_node.value, ast.Name):
        return f"{func_node.value.id}.{func_node.attr}"
    return ""


def _is_docstring_stmt(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str)


def _collect_python_ast_exclusions(content: str) -> Optional[Set[int]]:
    """Collects line ranges of re.compile / _make_finding calls and docstrings via Python AST."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return None
    excluded: Set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _ast_call_name(node.func) in ("re.compile", "_make_finding"):
            excluded.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        elif isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            if _is_docstring_stmt(node.body[0]):
                doc = node.body[0]
                excluded.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    return excluded


def _compute_js_excluded_lines(lines: List[str]) -> Set[int]:
    """Excludes blank lines and // or /* ... */ comment lines in JS/TS files."""
    excluded: Set[int] = set()
    in_block = False
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            excluded.add(idx)
            continue
        if in_block:
            excluded.add(idx)
            if "*/" in stripped:
                in_block = False
            continue
        if stripped.startswith("//"):
            excluded.add(idx)
        elif stripped.startswith("/*"):
            if "*/" not in stripped[2:]:
                excluded.add(idx)
                in_block = True
            elif stripped.endswith("*/"):
                excluded.add(idx)
    return excluded


def _compute_excluded_lines(content: str, lines: List[str], is_python: bool) -> Set[int]:
    """Computes 1-based line numbers to exclude (comments, blanks, Python regex/finding metadata, docstrings)."""
    if not is_python:
        return _compute_js_excluded_lines(lines)

    ast_excl = _collect_python_ast_exclusions(content)
    excluded: Set[int] = set(ast_excl) if ast_excl is not None else set()
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            excluded.add(idx)
        elif ast_excl is None and ("re.compile(" in line or "_make_finding(" in line):
            excluded.add(idx)
    return excluded


def _make_finding(
    attack_class: str,
    verdict: str,
    severity: Optional[str],
    rel: str,
    line_num: int,
    entrypoint: str,
    sink: str,
    evidence: str,
    boundary: str,
    rejection_reason: Optional[str] = None,
) -> SecurityFinding:
    fp_raw = f"{attack_class}:{rel}:{line_num}:{sink}"
    fp = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:12]
    fid = f"SEC-{fp[:8].upper()}"
    eff_sev = severity if verdict == "confirmed" else None
    trace = SecurityTrace(entrypoint=f"{rel}:{line_num}:{entrypoint}", propagation=[entrypoint], sink=sink).to_dict()
    return SecurityFinding(
        finding_id=fid,
        fingerprint=fp,
        verdict=verdict,
        severity=eff_sev,
        attack_class=attack_class,
        boundary=boundary,
        trace=trace,
        evidence=evidence.strip(),
        rejection_reason=rejection_reason,
        fix_target=rel,
    )


def _mask_js_comments_and_strings(content: str) -> str:
    """Masks JS/TS comments and string bodies with spaces while preserving newlines and ${...} braces."""
    n = len(content)
    out = [" "] * n
    stack: List[List[Any]] = [["code"]]
    i = 0
    while i < n:
        state = stack[-1][0]
        ch = content[i]
        if ch == "\n":
            out[i] = "\n"
            i += 1
            continue
        if state == "template":
            if ch == "\\" and i + 1 < n:
                if content[i + 1] == "\n":
                    out[i + 1] = "\n"
                i += 2
                continue
            if ch == "`":
                stack.pop()
                i += 1
                continue
            if ch == "$" and i + 1 < n and content[i + 1] == "{":
                out[i] = "$"
                out[i + 1] = "{"
                stack.append(["tpl_expr", 1])
                i += 2
                continue
            i += 1
            continue
        if ch == "/" and i + 1 < n and content[i + 1] == "/":
            i += 2
            while i < n and content[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and content[i + 1] == "*":
            i += 2
            while i < n:
                if content[i] == "*" and i + 1 < n and content[i + 1] == "/":
                    i += 2
                    break
                if content[i] == "\n":
                    out[i] = "\n"
                i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                sc = content[i]
                if sc == "\n":
                    out[i] = "\n"
                    i += 1
                    break
                if sc == "\\" and i + 1 < n:
                    if content[i + 1] == "\n":
                        out[i + 1] = "\n"
                    i += 2
                    continue
                if sc == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "`":
            stack.append(["template"])
            i += 1
            continue
        if ch == "{" and state == "tpl_expr":
            stack[-1][1] += 1
        elif ch == "}" and state == "tpl_expr":
            stack[-1][1] -= 1
            if stack[-1][1] == 0:
                stack.pop()
        out[i] = ch
        i += 1
    return "".join(out)


@dataclass
class _FnDef:
    name: str
    start_line: int
    end_line: int
    is_exported: bool


def _extract_reexported_names(masked_content: str) -> Set[str]:
    names: Set[str] = set()
    for m in _EXPORT_SPEC_RE.finditer(masked_content):
        for item in m.group(1).split(","):
            tok = item.strip().split(" as ")[0].strip()
            if tok:
                names.add(tok)
    return names


def _extract_top_level_fn_defs(
    lines: List[str],
    masked_lines: List[str],
    is_python: bool = False,
) -> List[_FnDef]:
    if is_python:
        defs: List[_FnDef] = []
        for idx, line in enumerate(lines, start=1):
            if line[:1].isspace():
                continue
            m = _PY_FN_START_RE.match(line)
            if m:
                if defs:
                    defs[-1].end_line = idx - 1
                defs.append(_FnDef(name=m.group(1), start_line=idx, end_line=len(lines), is_exported=True))
        return defs

    reexported = _extract_reexported_names("\n".join(masked_lines))
    defs = []
    brace_depth = 0
    for idx, mline in enumerate(masked_lines, start=1):
        stripped = mline.strip()
        if brace_depth == 0 and stripped:
            m = _FN_START_RE.match(stripped)
            if m:
                if defs:
                    defs[-1].end_line = idx - 1
                name = m.group(1) or m.group(2) or "handler"
                is_exp = stripped.startswith("export ") or name in reexported
                defs.append(_FnDef(name=name, start_line=idx, end_line=len(lines), is_exported=is_exp))
        brace_depth = max(0, brace_depth + mline.count("{") - mline.count("}"))
    return defs


def _enclosing_fn_ranges(lines: List[str], is_python: bool = False) -> Dict[int, Tuple[int, str]]:
    masked_lines = lines if is_python else _mask_js_comments_and_strings("\n".join(lines)).splitlines()
    if len(masked_lines) < len(lines):
        masked_lines.extend([""] * (len(lines) - len(masked_lines)))
    defs = _extract_top_level_fn_defs(lines, masked_lines, is_python=is_python)
    mapping: Dict[int, Tuple[int, str]] = {}
    def_idx = 0
    for line_no in range(1, len(lines) + 1):
        while def_idx < len(defs) and line_no > defs[def_idx].end_line:
            def_idx += 1
        if def_idx < len(defs) and defs[def_idx].start_line <= line_no <= defs[def_idx].end_line:
            mapping[line_no] = (defs[def_idx].start_line, defs[def_idx].name)
        else:
            mapping[line_no] = (1, "module")
    return mapping


def _extract_auth_policies(masked_lines: List[str]) -> Set[str]:
    """Extracts `<OBJ>.<key>` entries from top-level policy objects declaring minAuthLevel/authLevel/requireAuth."""
    auth_policies: Set[str] = set()
    brace_depth = 0
    active_obj: Optional[str] = None
    active_key: Optional[str] = None
    key_depth: Optional[int] = None
    key_buf: List[str] = []

    for mline in masked_lines:
        stripped = mline.strip()
        if active_obj is None and brace_depth == 0:
            m_obj = _POLICY_OBJ_START_RE.match(stripped)
            if m_obj:
                active_obj = m_obj.group(1)

        if active_obj is not None:
            if active_key is None and brace_depth == 1:
                m_key = _POLICY_KEY_START_RE.match(mline)
                if m_key:
                    active_key = m_key.group(1)
                    key_depth = 1
                    key_buf = [mline]
            elif active_key is not None:
                key_buf.append(mline)

        prev_depth = brace_depth
        brace_depth = max(0, brace_depth + mline.count("{") - mline.count("}"))

        if active_obj is not None and active_key is not None and key_depth is not None:
            if brace_depth <= key_depth and prev_depth >= key_depth:
                if _POLICY_AUTH_FIELD_RE.search("\n".join(key_buf)):
                    auth_policies.add(f"{active_obj}.{active_key}")
                active_key = None
                key_depth = None
                key_buf = []

        if active_obj is not None and brace_depth == 0:
            active_obj = None
            active_key = None
            key_depth = None
            key_buf = []

    return auth_policies


def _upstream_refutation_reason(
    upstream: str,
    sink_name: str,
    sink_window: str,
    auth_policies: Set[str],
    guard_helpers: Set[str],
    allow_read_only_run_action: bool = True,
) -> Optional[str]:
    if _ABAC_GUARD_RE.search(upstream):
        return "Refuted: auth/ABAC guard verified upstream before sink"
    if _TOKEN_GUARD_RE.search(upstream):
        return "Refuted: cryptographic token guard verified upstream before sink"
    for helper in guard_helpers:
        if re.search(rf"\b{re.escape(helper)}\s*\(", upstream):
            return f"Refuted: intra-file guard helper '{helper}' verified upstream before sink"
    for m_ra in _RUN_ACTION_CALL_RE.finditer(upstream):
        policy_arg = m_ra.group(1).strip()
        if policy_arg in auth_policies or _POLICY_AUTH_FIELD_RE.search(policy_arg):
            return f"Refuted: runAction policy '{policy_arg}' enforces auth level"
        if allow_read_only_run_action and _READ_ONLY_REPO_METHOD_RE.match(sink_name):
            return "Refuted: non-mutating repository read wrapped in runAction"
    if allow_read_only_run_action and _READ_ONLY_REPO_METHOD_RE.match(sink_name) and "publicOnly" in sink_window:
        return "Refuted: publicOnly read-only repository query"
    return None


def _compute_guard_and_caller_helpers(
    lines: List[str],
    fn_defs: List[_FnDef],
    auth_policies: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """Computes intra-file guard helpers and private helpers called exclusively under auth guards."""
    fn_bodies: Dict[str, str] = {
        fn.name: "\n".join(lines[fn.start_line - 1 : fn.end_line])
        for fn in fn_defs
    }
    fn_by_name: Dict[str, _FnDef] = {fn.name: fn for fn in fn_defs}

    # 1. Fixed-point guard helpers (non-exported helpers executing auth/token guards)
    guard_helpers: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in fn_defs:
            if fn.is_exported or fn.name in guard_helpers:
                continue
            body = fn_bodies[fn.name]
            if _ABAC_GUARD_RE.search(body) or _TOKEN_GUARD_RE.search(body) or any(
                re.search(rf"\b{re.escape(gh)}\s*\(", body) for gh in guard_helpers
            ):
                guard_helpers.add(fn.name)
                changed = True

    # 2. Fixed-point caller-guarded private helpers
    caller_guarded: Set[str] = set()
    changed = True
    while changed:
        changed = False
        for fn in fn_defs:
            if fn.is_exported or fn.name in caller_guarded:
                continue
            call_pat = re.compile(rf"\b{re.escape(fn.name)}\s*\(")
            call_sites: List[Tuple[_FnDef, int]] = []
            for other in fn_defs:
                if other.name == fn.name:
                    continue
                for line_no in range(other.start_line, other.end_line + 1):
                    if call_pat.search(lines[line_no - 1]):
                        call_sites.append((other, line_no))
            if not call_sites:
                continue
            all_guarded = True
            for caller_fn, call_line in call_sites:
                if caller_fn.name in caller_guarded:
                    continue
                upstream = "\n".join(lines[caller_fn.start_line - 1 : call_line])
                reason = _upstream_refutation_reason(
                    upstream,
                    sink_name="",
                    sink_window="",
                    auth_policies=auth_policies,
                    guard_helpers=guard_helpers,
                    allow_read_only_run_action=False,
                )
                if reason is None:
                    all_guarded = False
                    break
            if all_guarded:
                caller_guarded.add(fn.name)
                changed = True

    return guard_helpers, caller_guarded


def _scan_abac_class(
    rel: str,
    content: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
) -> List[SecurityFinding]:
    surface, boundary = _classify_surface_and_boundary(rel, content)
    if surface not in ("server_action", "api_route"):
        return []
    excl = excluded_lines or set()
    masked_lines = _mask_js_comments_and_strings(content).splitlines()
    if len(masked_lines) < len(lines):
        masked_lines.extend([""] * (len(lines) - len(masked_lines)))
    fn_defs = _extract_top_level_fn_defs(lines, masked_lines, is_python=False)
    auth_policies = _extract_auth_policies(masked_lines)
    guard_helpers, caller_guarded = _compute_guard_and_caller_helpers(lines, fn_defs, auth_policies)

    findings: List[SecurityFinding] = []
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        fn_start, fn_name = fn_map[idx]
        if _PRIV_BYPASS_RE.search(line):
            findings.append(_make_finding(
                "ACCESS_CONTROL_ABAC", "confirmed", "CRITICAL", rel, idx, fn_name, "privilege_bypass", line, boundary
            ))
            continue
        m_sink = _ABAC_SINK_RE.search(line)
        if not m_sink:
            continue
        sink_name = m_sink.group(1)
        upstream = "\n".join(lines[fn_start - 1 : idx])
        sink_window = " ".join(lines[idx - 1 : min(len(lines), idx + 4)])
        reason = _upstream_refutation_reason(
            upstream,
            sink_name=sink_name,
            sink_window=sink_window,
            auth_policies=auth_policies,
            guard_helpers=guard_helpers,
            allow_read_only_run_action=True,
        )
        if reason is None and fn_name in caller_guarded:
            reason = f"Refuted: private helper '{fn_name}' called exclusively from auth-guarded action(s)"

        if reason is not None:
            findings.append(_make_finding(
                "ACCESS_CONTROL_ABAC", "rejected", None, rel, idx, fn_name, sink_name, line, boundary,
                rejection_reason=reason,
            ))
        else:
            sev = "CRITICAL" if ("delete" in line or "admin" in rel.lower()) else "HIGH"
            findings.append(_make_finding(
                "ACCESS_CONTROL_ABAC", "confirmed", sev, rel, idx, fn_name, sink_name, line, boundary
            ))
    return findings


def _scan_data_isolation_class(
    rel: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
) -> List[SecurityFinding]:
    excl = excluded_lines or set()
    findings: List[SecurityFinding] = []
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        m_mut = _DATA_MUTATION_RE.search(line)
        if not m_mut:
            continue
        stmt_window = " ".join(lines[idx - 1 : min(len(lines), idx + 5)])
        if ".where(" not in stmt_window:
            _, fn_name = fn_map[idx]
            findings.append(_make_finding(
                "DATA_ISOLATION", "confirmed", "HIGH", rel, idx, fn_name, f"db.{m_mut.group(1)}(without .where)", line, "tenant_row"
            ))
    return findings


def _scan_js_injection_line(
    rel: str,
    idx: int,
    line: str,
    fn_name: str,
    has_sanitizer: bool,
) -> List[SecurityFinding]:
    findings: List[SecurityFinding] = []
    if _SQL_RAW_INTERP_RE.search(line):
        findings.append(_make_finding("INJECTION_AND_SINKS", "confirmed", "CRITICAL", rel, idx, fn_name, "sql.raw(${...})", line, "sql_sink"))
    if _DANGEROUS_HTML_RE.search(line):
        if has_sanitizer:
            findings.append(_make_finding(
                "INJECTION_AND_SINKS", "rejected", None, rel, idx, fn_name, "dangerouslySetInnerHTML", line, "xss_sink",
                rejection_reason="Refuted: sanitizer (DOMPurify/sanitize) verified in file",
            ))
        else:
            findings.append(_make_finding("INJECTION_AND_SINKS", "confirmed", "HIGH", rel, idx, fn_name, "dangerouslySetInnerHTML", line, "xss_sink"))
    return findings


def _scan_injection_line(
    rel: str,
    idx: int,
    line: str,
    fn_name: str,
    has_sanitizer: bool,
    is_python: bool,
) -> List[SecurityFinding]:
    findings = [] if is_python else _scan_js_injection_line(rel, idx, line, fn_name, has_sanitizer)
    cmd_re = _PY_CMD_EXEC_RE if is_python else _CMD_EXEC_RE
    eval_re = _PY_EVAL_SINK_RE if is_python else _EVAL_SINK_RE
    is_cmd = bool(cmd_re.search(line))
    if is_cmd or eval_re.search(line):
        sev = "CRITICAL" if is_cmd else "HIGH"
        sink_lbl = "shell_exec" if is_cmd else "eval_sink"
        findings.append(_make_finding("INJECTION_AND_SINKS", "confirmed", sev, rel, idx, fn_name, sink_lbl, line, "exec_sink"))
    return findings


def _scan_injection_class(
    rel: str,
    content: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
    is_python: bool = False,
) -> List[SecurityFinding]:
    excl = excluded_lines or set()
    findings: List[SecurityFinding] = []
    has_sanitizer = bool(_HTML_SANITIZER_RE.search(content))
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        _, fn_name = fn_map[idx]
        findings.extend(_scan_injection_line(rel, idx, line, fn_name, has_sanitizer, is_python))
    return findings


def _scan_crypto_class(
    rel: str,
    lines: List[str],
    fn_map: Dict[int, Tuple[int, str]],
    excluded_lines: Optional[Set[int]] = None,
    is_python: bool = False,
) -> List[SecurityFinding]:
    excl = excluded_lines or set()
    findings: List[SecurityFinding] = []
    for idx, line in enumerate(lines, start=1):
        if idx in excl:
            continue
        _, fn_name = fn_map[idx]
        if _HARDCODED_SECRET_RE.search(line):
            findings.append(_make_finding("CRYPTO_AND_SECRETS", "confirmed", "CRITICAL", rel, idx, fn_name, "hardcoded_secret", line, "secret_literal"))
        if not is_python and _MATH_RANDOM_RE.search(line):
            win = " ".join(lines[max(0, idx - 3) : min(len(lines), idx + 3)]) + f" {fn_name}"
            if _SEC_CTX_RE.search(win):
                findings.append(_make_finding("CRYPTO_AND_SECRETS", "confirmed", "HIGH", rel, idx, fn_name, "Math.random()", line, "crypto_prng"))
    return findings


def _scan_single_file(rel: str, path: Path) -> List[SecurityFinding]:
    content = path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    is_python = Path(rel).suffix.lower() == ".py"
    excluded_lines = _compute_excluded_lines(content, lines, is_python)
    fn_map = _enclosing_fn_ranges(lines, is_python=is_python)
    found: List[SecurityFinding] = []
    found.extend(_scan_abac_class(rel, content, lines, fn_map, excluded_lines))
    found.extend(_scan_data_isolation_class(rel, lines, fn_map, excluded_lines))
    found.extend(_scan_injection_class(rel, content, lines, fn_map, excluded_lines, is_python))
    found.extend(_scan_crypto_class(rel, lines, fn_map, excluded_lines, is_python))
    return found


def _load_prior_ledger(sec_dir: Path) -> Dict[str, CoverageUnit]:
    ledger_path = sec_dir / "coverage-ledger.json"
    if not ledger_path.is_file():
        return {}
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        return {u.file_path: u for u in CoverageLedger.from_dict(raw).units}
    except Exception:
        return {}


def _load_prior_findings(sec_dir: Path) -> List[SecurityFinding]:
    findings_path = sec_dir / "findings.json"
    if not findings_path.is_file():
        return []
    try:
        raw = json.loads(findings_path.read_text(encoding="utf-8"))
        items = raw.get("findings") if isinstance(raw, dict) else raw
        return [SecurityFinding.from_dict(f) for f in (items or []) if isinstance(f, dict)]
    except Exception:
        return []


def _resolve_diff_set(
    repo: Path,
    diff_only: bool,
    base_ref: Optional[str],
    changed_files: Optional[List[str]],
) -> Optional[Set[str]]:
    if changed_files is not None:
        return {f.strip().replace("\\", "/").lstrip("./") for f in changed_files if f.strip()}
    if diff_only:
        return _git_diff_rel_files(repo, base_ref)
    return None


def _is_target_selected(
    rel: str,
    sha: str,
    prior: Optional[CoverageUnit],
    scan_all: bool,
    scope_tokens: List[str],
    diff_set: Optional[Set[str]],
) -> bool:
    if prior and prior.status == "covered" and prior.file_sha256 != sha:
        return True
    if scan_all:
        return True
    if scope_tokens and _matches_scope(rel, scope_tokens):
        return True
    return diff_set is not None and rel in diff_set


def _select_active_targets(
    sources: Dict[str, Path],
    shas: Dict[str, str],
    prior_units: Dict[str, CoverageUnit],
    scopes: Optional[List[str]],
    diff_only: bool,
    base_ref: Optional[str],
    recursive: bool,
    changed_files: Optional[List[str]],
    repo: Path,
) -> Set[str]:
    scope_tokens = _expand_scopes(scopes)
    diff_set = _resolve_diff_set(repo, diff_only, base_ref, changed_files)
    scan_all = recursive or (not scope_tokens and diff_set is None)
    return {
        rel for rel in sources
        if _is_target_selected(rel, shas[rel], prior_units.get(rel), scan_all, scope_tokens, diff_set)
    }


def _finding_rel_path(finding: SecurityFinding) -> str:
    if finding.fix_target:
        return finding.fix_target
    ep = str(finding.trace.get("entrypoint") or "")
    return ep.split(":", 1)[0]


def _build_scope_label(scopes: Optional[List[str]], diff_only: bool, changed_files: Optional[List[str]]) -> str:
    if scopes:
        return ",".join(_expand_scopes(scopes))
    if diff_only or changed_files is not None:
        return "diff"
    return "recursive"


def _build_coverage_unit(
    rel: str,
    sha: str,
    status: str,
    last_audited_at: str,
    content: str,
) -> CoverageUnit:
    surface, boundary = _classify_surface_and_boundary(rel, content)
    cid = f"COV-{hashlib.sha256(rel.encode('utf-8')).hexdigest()[:8].upper()}"
    return CoverageUnit(
        coverage_id=cid,
        file_path=rel,
        file_sha256=sha,
        surface=surface,
        boundary=boundary,
        attack_class="ALL_4_CLASSES",
        status=status,
        last_audited_at=last_audited_at,
    )


def _merge_ledger_and_findings(
    sources: Dict[str, Path],
    shas: Dict[str, str],
    active: Set[str],
    prior_units: Dict[str, CoverageUnit],
    prior_findings: List[SecurityFinding],
    now_iso: str,
) -> Tuple[List[CoverageUnit], List[SecurityFinding]]:
    units: List[CoverageUnit] = []
    preserved_files: Set[str] = set()
    scanned_findings: List[SecurityFinding] = []

    for rel, path in sources.items():
        content = path.read_text(encoding="utf-8", errors="ignore")
        if rel in active:
            scanned_findings.extend(_scan_single_file(rel, path))
            units.append(_build_coverage_unit(rel, shas[rel], "covered", now_iso, content))
        else:
            prev = prior_units.get(rel)
            if prev and prev.status == "covered" and prev.file_sha256 == shas[rel]:
                preserved_files.add(rel)
                units.append(prev)
            else:
                prev_ts = prev.last_audited_at if prev else ""
                units.append(_build_coverage_unit(rel, shas[rel], "out_of_scope", prev_ts, content))

    merged_findings = [f for f in prior_findings if _finding_rel_path(f) in preserved_files]
    merged_findings.extend(scanned_findings)
    return units, merged_findings


def _ensure_security_dir_excluded(repo: Path) -> None:
    """Marks .edge/security/ excluded locally when inside a git repo without .edge gitignore."""
    exclude_file = repo / ".git" / "info" / "exclude"
    if not (repo / ".git").is_dir():
        return
    try:
        chk = subprocess.run(
            ["git", "check-ignore", "-q", ".edge/security/coverage-ledger.json"],
            cwd=str(repo),
            capture_output=True,
            timeout=5,
        )
        if chk.returncode == 0:
            return
    except Exception:
        return
    exclude_file.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude_file.read_text(encoding="utf-8", errors="ignore") if exclude_file.is_file() else ""
    if ".edge/security/" not in existing.splitlines():
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        exclude_file.write_text(f"{existing}{prefix}.edge/security/\n", encoding="utf-8")


def run_security_audit(
    repo_path: Path,
    scopes: Optional[List[str]] = None,
    diff_only: bool = False,
    base_ref: Optional[str] = None,
    recursive: bool = False,
    changed_files: Optional[List[str]] = None,
    profile: str = "standard",
    out_dir: Optional[Path] = None,
) -> SecurityAuditReport:
    """Runs incremental 4-class security audit with automated refutation and shared ledger updates."""
    repo = Path(repo_path).resolve()
    sec_dir = Path(out_dir) if out_dir else (repo / ".edge" / "security")
    now_iso = datetime.now(timezone.utc).isoformat()

    if out_dir is None:
        _ensure_security_dir_excluded(repo)

    sources = _discover_repo_sources(repo)
    shas = {rel: hashlib.sha256(p.read_bytes()).hexdigest() for rel, p in sources.items()}
    prior_units = _load_prior_ledger(sec_dir)
    prior_findings = _load_prior_findings(sec_dir)

    active = _select_active_targets(sources, shas, prior_units, scopes, diff_only, base_ref, recursive, changed_files, repo)
    units, merged_findings = _merge_ledger_and_findings(sources, shas, active, prior_units, prior_findings, now_iso)

    ledger = CoverageLedger(version="1.0.0", updated_at=now_iso, units=units)
    _write_json_atomic(sec_dir / "coverage-ledger.json", ledger.to_dict())
    _write_json_atomic(sec_dir / "findings.json", {"version": "1.0.0", "updated_at": now_iso, "findings": [f.to_dict() for f in merged_findings]})

    confirmed = sum(1 for f in merged_findings if f.verdict == "confirmed")
    needs_val = sum(1 for f in merged_findings if f.verdict == "needs_validation")
    rejected = sum(1 for f in merged_findings if f.verdict == "rejected")
    covered_cnt = sum(1 for u in units if u.status == "covered")

    return SecurityAuditReport(
        scope_label=_build_scope_label(scopes, diff_only, changed_files),
        audited_at=now_iso,
        profile=profile,
        confirmed_count=confirmed,
        needs_validation_count=needs_val,
        rejected_count=rejected,
        ledger_covered=covered_cnt,
        ledger_total=len(units),
        passed=(confirmed == 0),
        findings=merged_findings,
    )


def _slug_from_finding(f: SecurityFinding) -> str:
    base = Path(f.fix_target or "security").stem
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", f"{base}-{f.finding_id[-4:]}").strip("-")
    return cleaned.upper() or "FINDING"


def _build_security_ticket(f: SecurityFinding) -> Ticket:
    slug = _slug_from_finding(f)
    ticket_id = f"TICK-SEC-{slug}"
    ep = str(f.trace.get("entrypoint") or f.fix_target)
    parts = ep.split(":")
    line_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    target_file = f.fix_target or parts[0]
    return Ticket(
        ticket_id=ticket_id,
        track="core",
        domain="security",
        rule_id="SECURITY_AUDIT_CONFIRMED",
        severity="CRITICAL",
        target_file=target_file,
        line_number=line_num,
        fingerprint=f.fingerprint,
        description=f"[{f.attack_class}] {ep} -> {f.trace.get('sink')}: {f.evidence[:140]}",
        suggested_fix=f"Remediate {f.attack_class} sink '{f.trace.get('sink')}' in {target_file}.",
        branch_name=f"fix/sec-{slug.lower()}",
        expected_files=[target_file],
    )


def _upsert_core_ledger(repo: Path, tickets: List[Ticket]) -> None:
    ledger_path = repo / ".edge" / "ledger" / "core.json"
    data: Dict[str, Any] = {"version": "1.0.0", "track": "core", "items": []}
    if ledger_path.is_file():
        try:
            loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass
    items: List[Dict[str, Any]] = list(data.get("items") or [])
    for t in tickets:
        entry = {
            "ticket_id": t.ticket_id,
            "track": "core",
            "domain": "security",
            "rule_id": t.rule_id,
            "severity": t.severity,
            "file_path": t.target_file,
            "line_number": t.line_number,
            "fingerprint": t.fingerprint,
            "title": t.description[:90],
            "description": t.description,
            "suggested_fix": t.suggested_fix,
            "status": "OPEN",
            "created_at": t.created_at,
        }
        idx = next((i for i, it in enumerate(items) if it.get("ticket_id") == t.ticket_id or it.get("fingerprint") == t.fingerprint), None)
        if idx is not None:
            items[idx] = entry
        else:
            items.append(entry)
    data["items"] = items
    _write_json_atomic(ledger_path, data)


def triage_security_findings(repo_path: Path, report: SecurityAuditReport) -> List[str]:
    """Upserts CRITICAL TICK-SEC-* tickets into .edge/ledger/core.json and transitions IDLE FSM to TRIAGE."""
    repo = Path(repo_path).resolve()
    confirmed = [f for f in report.findings if f.verdict == "confirmed"]
    if not confirmed:
        return []
    tickets = [_build_security_ticket(f) for f in confirmed]
    _upsert_core_ledger(repo, tickets)

    fsm = BrigadeFSM(repo)
    if fsm.state.current_state == CycleState.IDLE:
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
                message=f"Auto-triaged confirmed security finding {first.ticket_id}.",
                details={"ticket_id": first.ticket_id, "source": "security_audit"},
            )
        )
        fsm.save()

    ids = [t.ticket_id for t in tickets]
    report.triage_tickets_created = ids
    return ids


def _format_security_toon(report: SecurityAuditReport) -> str:
    header = (
        f"security_audit[{report.confirmed_count}]"
        f"{{scope:{report.scope_label},confirmed:{report.confirmed_count},"
        f"needs_validation:{report.needs_validation_count},rejected:{report.rejected_count},"
        f"ledger_covered:{report.ledger_covered}/{report.ledger_total},"
        f"passed:{str(report.passed).lower()}}}:"
    )
    lines = [header, "  id | verdict | severity | attack_class | entrypoint | sink | summary"]
    for f in report.findings:
        sev = f.severity or "none"
        summary = (f.rejection_reason or f.evidence or "").replace("\n", " ")[:60]
        lines.append(
            f"  {f.finding_id} | {f.verdict} | {sev} | {f.attack_class} | "
            f"{f.trace.get('entrypoint', '')} | {f.trace.get('sink', '')} | {summary}"
        )
    return "\n".join(lines)


def _format_security_markdown(report: SecurityAuditReport) -> str:
    icon = "✅" if report.passed else "❌"
    lines = [
        f"### Security & ABAC Audit ({icon} {report.confirmed_count} confirmed · {report.rejected_count} refuted)",
        f"- **Shared Ledger:** {report.ledger_covered}/{report.ledger_total} units covered · **Scope:** `{report.scope_label}`",
        "",
        "| id | verdict | severity | attack_class | entrypoint | sink |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for f in report.findings:
        lines.append(
            f"| `{f.finding_id}` | `{f.verdict}` | `{f.severity or 'none'}` | `{f.attack_class}` | `{f.trace.get('entrypoint', '')}` | `{f.trace.get('sink', '')}` |"
        )
    return "\n".join(lines)


def format_security_report(report: SecurityAuditReport, fmt: str = "toon") -> str:
    """Formats SecurityAuditReport as 'toon' (default), 'json', or 'markdown'."""
    mode = (fmt or "toon").strip().lower()
    if mode == "json":
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    if mode == "markdown":
        return _format_security_markdown(report)
    return _format_security_toon(report)
