"""Submodule: validate."""

from fnmatch import fnmatch
from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Set, Tuple

from tools.brigade.security.constants import _AUDIT_EXTS, _IGNORED_DIRS, _JS_TS_EXTS, _USE_SERVER_DIRECTIVE_RE


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


def _classify_surface_and_boundary(
    rel: str,
    content: str,
    allow_server_actions: bool = True,
) -> Tuple[str, str]:
    is_js_ts = Path(rel).suffix.lower() in _JS_TS_EXTS
    if allow_server_actions and (rel.startswith("src/actions/") or (is_js_ts and bool(_USE_SERVER_DIRECTIVE_RE.search(content)))):
        return "server_action", "auth_abac"
    if "/api/" in f"/{rel}":
        return "api_route", "auth_abac"
    if rel.startswith("src/core/") or rel.startswith("core/"):
        return "core_module", "domain_isolation"
    if rel.endswith((".tsx", ".jsx")):
        return "component", "xss_sink"
    return "module", "boundary"
