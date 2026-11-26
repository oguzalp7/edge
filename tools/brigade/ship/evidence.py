"""Ship-prep submodule: evidence."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import os
import tempfile

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.models import SpecShipPlan
from tools.brigade.ship.evidence_git import _collect_evidence_shots, _redact_url_credentials, _resolve_github_target, _run_git_with_env

def _seed_evidence_parent_tree(
    repo: Path,
    evidence_branch: str,
    env: Dict[str, str],
) -> Optional[str]:
    """Resolves local/remote evidence branch head and seeds temp GIT_INDEX_FILE via git read-tree."""
    l_code, l_sha, _ = call_run_command(["git", "rev-parse", "--verify", f"refs/heads/{evidence_branch}"], cwd=repo)
    parent_sha = l_sha.strip() if l_code == 0 and l_sha.strip() else None
    if not parent_sha:
        call_run_command(
            ["git", "fetch", "origin", f"refs/heads/{evidence_branch}:refs/remotes/origin/{evidence_branch}"],
            cwd=repo,
        )
        r_code, r_sha, _ = call_run_command(
            ["git", "rev-parse", "--verify", f"refs/remotes/origin/{evidence_branch}"],
            cwd=repo,
        )
        parent_sha = r_sha.strip() if r_code == 0 and r_sha.strip() else None
    if parent_sha:
        _run_git_with_env(repo, ["read-tree", parent_sha], env)
    return parent_sha


def _stage_evidence_blobs(
    repo: Path,
    shots: List[Tuple[Dict[str, Any], Path, str]],
    env: Dict[str, str],
) -> Tuple[bool, str]:
    for _, resolved, stage_path in shots:
        h_code, blob_sha, h_err = call_run_command(["git", "hash-object", "-w", "--", str(resolved)], cwd=repo)
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
    c_code, c_sha, c_err = call_run_command(["git", *args], cwd=repo)
    if c_code != 0:
        return False, "", f"Failed to commit evidence tree: {_redact_url_credentials(c_err)}"
    commit_sha = c_sha.strip()
    call_run_command(["git", "update-ref", f"refs/heads/{evidence_branch}", commit_sha], cwd=repo)
    p_code, _, p_err = call_run_command(["git", "push", "origin", f"refs/heads/{evidence_branch}"], cwd=repo)
    if p_code != 0:
        return False, commit_sha, f"Failed to push '{evidence_branch}' to origin: {_redact_url_credentials(p_err)}"
    return True, commit_sha, ""


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
