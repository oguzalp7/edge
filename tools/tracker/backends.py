"""
Tracker backend protocol, raw subprocess runner, remote detection, and resolution.
"""

import os
import re
import shlex
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, List, Optional, Protocol, Sequence, Tuple, Union

from tools.common.paths import WSL_DISTRO, is_wsl_path, normalize_target_path, to_wsl_path
from .models import TrackerAuthError, TrackerBackendKind, TrackerComment, TrackerError, TrackerIssue

AUTH_REMEDIATION = (
    "Run `gh auth login` / `gh-axi setup` to authenticate, "
    "or pass `--offline` / set `EDGE_TRACKER=local` for local mode."
)
AUTH_ERROR_PATTERN = re.compile(r"401|AUTH_REQUIRED|Bad credentials|not logged into|gh auth login", re.IGNORECASE)
NETWORK_ERROR_PATTERN = re.compile(r"could not resolve|connection refused|timed out", re.IGNORECASE)
RATE_LIMIT_PATTERN = re.compile(r"(?:HTTP\s*403|secondary rate limit|API rate limit)", re.IGNORECASE)
_SSH_SCP_PATTERN = re.compile(r"^[^/\s]+@[^:\s]+:")


class TrackerBackend(Protocol):
    """Unified interface contract implemented by all tracker backends."""

    kind: TrackerBackendKind

    def ensure_labels(self) -> List[str]: ...
    def create_issue(self, title: str, body: str = "", labels: Optional[Sequence[str]] = None, parent_number: Optional[int] = None) -> TrackerIssue: ...
    def get_issue(self, number: int, include_comments: bool = True) -> TrackerIssue: ...
    def list_issues(self, state: str = "open", labels: Optional[Sequence[str]] = None, parent_number: Optional[int] = None, limit: int = 100) -> List[TrackerIssue]: ...
    def edit_issue(self, number: int, title: Optional[str] = None, body: Optional[str] = None, add_labels: Optional[Sequence[str]] = None, remove_labels: Optional[Sequence[str]] = None) -> TrackerIssue: ...
    def add_comment(self, number: int, body: str) -> TrackerComment: ...
    def add_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]: ...
    def remove_subissue(self, parent_number: int, child_numbers: Sequence[int]) -> List[TrackerIssue]: ...
    def list_subissues(self, parent_number: int) -> List[TrackerIssue]: ...
    def close_issue(self, number: int, comment: Optional[str] = None, reason: str = "completed") -> TrackerIssue: ...


def needs_wsl_dispatch(cwd: Optional[Union[str, Path]]) -> bool:
    """Return True when running on Windows against a WSL repository path."""
    return cwd is not None and is_wsl_path(cwd) and os.name == "nt"


def binary_exists(name: str, cwd: Optional[Union[str, Path]] = None) -> bool:
    """Return True if ``name`` is available natively or inside WSL PATH."""
    if not needs_wsl_dispatch(cwd):
        return shutil.which(name) is not None
    try:
        proc = subprocess.run(["wsl", "-d", WSL_DISTRO, "which", name], capture_output=True, text=True, timeout=10)
        return proc.returncode == 0
    except Exception:
        return False


def _build_exec_args(cmd: Sequence[str], cwd: Union[str, Path]) -> Tuple[List[str], Optional[str]]:
    if needs_wsl_dispatch(cwd):
        wsl_cwd = to_wsl_path(cwd)
        return ["wsl", "-d", WSL_DISTRO, "bash", "-c", f"cd {shlex.quote(wsl_cwd)} && {shlex.join(list(cmd))}"], None
    norm = normalize_target_path(cwd)
    return list(cmd), str(norm) if norm.exists() else None


def run_tracker_cmd(
    cmd: Sequence[str],
    cwd: Union[str, Path],
    *,
    strip: bool = False,
    timeout: int = 120,
) -> Tuple[int, str, str]:
    """Execute a tracker CLI command without stripping trailing newlines unless requested."""
    exec_cmd, exec_cwd = _build_exec_args(cmd, cwd)
    try:
        proc = subprocess.run(exec_cmd, cwd=exec_cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return (proc.returncode, stdout.strip(), stderr.strip()) if strip else (proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s"
    except FileNotFoundError as exc:
        return 127, "", f"{cmd[0]}: not found ({exc})"
    except OSError as exc:
        return 1, "", str(exc)


def classify_tracker_error(returncode: int, stdout: str, stderr: str, tool: str = "tracker") -> TrackerError:
    """Map CLI exit codes and messages to TrackerAuthError (exit 2) or TrackerError (exit 1)."""
    combined = "\n".join(part for part in (stderr.strip(), stdout.strip()) if part)
    if RATE_LIMIT_PATTERN.search(combined):
        return TrackerError(f"{tool} rate-limited or forbidden (rc={returncode}): {combined}")
    if returncode in (124, 127) or AUTH_ERROR_PATTERN.search(combined) or NETWORK_ERROR_PATTERN.search(combined):
        detail = combined or f"exit code {returncode}"
        return TrackerAuthError(f"{tool} auth/network failure (rc={returncode}): {detail}. {AUTH_REMEDIATION}")
    return TrackerError(f"{tool} failed (rc={returncode}): {combined or 'unknown error'}")


def run_tracker_checked(cmd: Sequence[str], cwd: Union[str, Path], *, strip: bool = False, timeout: int = 120) -> str:
    """Run a tracker command and raise a classified TrackerError on non-zero exit."""
    rc, stdout, stderr = run_tracker_cmd(cmd, cwd, strip=strip, timeout=timeout)
    if rc != 0:
        tool = Path(cmd[0]).name if cmd else "tracker"
        raise classify_tracker_error(rc, stdout, stderr, tool=tool)
    return stdout


@contextmanager
def temp_body_file(text: str, cwd: Optional[Union[str, Path]] = None) -> Iterator[str]:
    """Write ``text`` as UTF-8 bytes via mkstemp, close, convert WSL path if needed, and unlink."""
    fd, raw_path = tempfile.mkstemp(prefix="edge-tracker-body-", suffix=".md")
    host_path = Path(raw_path)
    fd_closed = False
    try:
        with os.fdopen(fd, "wb") as handle:
            fd_closed = True
            handle.write(text.encode("utf-8"))
        yield to_wsl_path(host_path) if needs_wsl_dispatch(cwd) else str(host_path)
    finally:
        if not fd_closed:
            os.close(fd)
        host_path.unlink(missing_ok=True)


def _is_github_remote_url(url: str, gh_host: str) -> bool:
    lower = url.strip().lower()
    if "github.com" in lower:
        return True
    if not gh_host:
        return False
    return gh_host in lower or lower.startswith("ssh://") or bool(_SSH_SCP_PATTERN.match(lower))


def has_github_remote(repo_path: Union[str, Path]) -> bool:
    """Return True if ``git remote -v`` points to github.com or matches GH_HOST/GHE."""
    norm = normalize_target_path(repo_path)
    try:
        proc = subprocess.run(["git", "remote", "-v"], cwd=str(norm), capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    if proc.returncode != 0 or not proc.stdout.strip():
        return False
    gh_host = os.environ.get("GH_HOST", "").strip().lower()
    return any(len(parts) >= 2 and _is_github_remote_url(parts[1], gh_host) for parts in (line.split() for line in proc.stdout.splitlines()))


def _select_explicit_backend(repo_path: Union[str, Path], backend: str) -> TrackerBackend:
    from .gh_axi_backend import GhAxiBackend
    from .gh_cli_backend import GhCliBackend

    if backend == "gh-axi":
        if not binary_exists("gh-axi", repo_path):
            raise TrackerAuthError(f"`gh-axi` binary not found. {AUTH_REMEDIATION}")
        return GhAxiBackend(repo_path)
    if backend == "gh":
        if not binary_exists("gh", repo_path):
            raise TrackerAuthError(f"`gh` binary not found. {AUTH_REMEDIATION}")
        return GhCliBackend(repo_path)
    raise TrackerError(f"Unsupported tracker backend: {backend}")


def resolve_backend(repo_path: Union[str, Path], backend: str = "auto", offline: bool = False) -> TrackerBackend:
    """Resolve the tracker backend according to the fail-fast priority matrix."""
    from .gh_axi_backend import GhAxiBackend
    from .gh_cli_backend import GhCliBackend
    from .local_backend import LocalTrackerBackend

    env_mode = os.environ.get("EDGE_TRACKER", "").strip().lower()
    if offline or backend == "local" or env_mode == "local":
        return LocalTrackerBackend(repo_path)
    if backend != "auto":
        return _select_explicit_backend(repo_path, backend)
    if not has_github_remote(repo_path):
        return LocalTrackerBackend(repo_path)
    if binary_exists("gh-axi", repo_path):
        return GhAxiBackend(repo_path)
    if binary_exists("gh", repo_path):
        return GhCliBackend(repo_path)
    raise TrackerAuthError(f"GitHub remote found, but neither `gh-axi` nor `gh` is available. {AUTH_REMEDIATION}")
