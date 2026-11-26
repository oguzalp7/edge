"""Ship-prep submodule: evidence_git."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import re
import subprocess

from tools.brigade.fsm import ProofVerifier
from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.constants import _URL_USERINFO_RE
from tools.brigade.ship.models import SpecShipPlan
from tools.brigade.ship.paths import _norm_rel_path

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


def _resolve_github_target(repo: Path) -> Tuple[bool, str, str, str]:
    import sys
    r_code, remote_url, r_err = call_run_command(["git", "remote", "get-url", "origin"], cwd=repo)
    if r_code != 0 or not remote_url.strip():
        return False, "", "", f"Git remote 'origin' missing ({_redact_url_credentials(r_err)})."
    facade = sys.modules.get("tools.brigade.ship_prep")
    parse_fn = getattr(facade, "parse_github_owner_repo", parse_github_owner_repo) if facade is not None else parse_github_owner_repo
    parsed = parse_fn(remote_url.strip())
    if not parsed:
        return False, "", "", f"Remote 'origin' URL '{_redact_url_credentials(remote_url.strip())}' is not a GitHub repository."
    return True, parsed[0], parsed[1], ""


def _resolve_single_shot(raw_sp: str, search_roots: List[Path], repo: Path) -> Optional[Path]:
    resolved = ProofVerifier.resolve_screenshot_file(raw_sp, search_roots)
    if resolved and resolved.is_file():
        return resolved
    cand = repo / _norm_rel_path(raw_sp)
    return cand if cand.is_file() else None


def _collect_plan_shots(
    repo: Path, plan: SpecShipPlan, search_roots: List[Path]
) -> List[Tuple[Dict[str, Any], Path, str]]:
    shots: List[Tuple[Dict[str, Any], Path, str]] = []
    for proof in plan.verified_proofs:
        for raw_sp in proof.get("screenshot_paths", []) or []:
            if (resolved := _resolve_single_shot(str(raw_sp), search_roots, repo)):
                shots.append((proof, resolved, f"evidence/{plan.spec_slug}/{resolved.name}"))
    return shots


def _collect_evidence_shots(
    repo: Path, spec_plans: List[SpecShipPlan], search_roots: List[Path]
) -> List[Tuple[Dict[str, Any], Path, str]]:
    shots: List[Tuple[Dict[str, Any], Path, str]] = []
    for plan in spec_plans:
        shots.extend(_collect_plan_shots(repo, plan, search_roots))
    return shots
