"""
Cross-Provider Zero-Context Goldfish Spec Critic Engine.
Executes an isolated, single-shot advisory critique of slice specifications
using high-reasoning primary frontier models (claude-opus-5-5-high)
with automatic fallback to flash models (gemini-3.8-flash-high).
"""

from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import Any, Dict, Optional, Tuple, Union

from tools.common import normalize_target_path, run_command

PRIMARY_CRITIC_MODEL: str = "claude-opus-5-5-high"
FALLBACK_CRITIC_MODEL: str = "gemini-3.8-flash-high"

DEFAULT_PERSONA_RUBRIC: str = """# 🐟 Persona: Spec Critic (Goldfish Critic)

> **Role:** Cross-Provider Zero-Context Specification Critic & Anti-Debt Auditor  
> **Station:** `spec_critic` in Edge Brigade (Advisory Mode)  
> **Constraint:** Zero Sycophancy, Independent Eyes, Strict < 400 Words Plain English Output

## 📋 Mandatory Review Rubric

### ## 1. Paraphrase Check
Provide a strict 3-sentence synthesis:
1. What the specification explicitly proposes to build or modify.
2. How the proposed change interacts with existing system boundaries and contracts.
3. The most critical unstated or hidden assumptions baked into the proposal.

### ## 2. Flexibility & Code Reuse (Anti-Debt)
Audit for architectural leverage and debt prevention:
- Identify existing codebase utilities, modules, or abstractions that should be reused instead of reinvented.
- Highlight overlapping responsibilities, duplicate patterns, or potential conflicts with current code.
- Recommend simpler, more flexible structural alternatives to eliminate future refactoring debt and avoid orphan anchors ("yetim çapa").

### ## 3. Zero-Decision & Edge-Case Audit
Expose gaps that would force downstream implementation agents to guess:
- Pinpoint missing type signatures, data models, validation boundaries, or lifecycle guarantees.
- Enumerate unhandled failure modes, boundary errors, timeouts, or empty/null states.
- Audit for missing pagination (`{ items, total, page, pageSize }` & URL `searchParams`), missing mutation idempotency / concurrency guards, missing resource-level ABAC ownership filters, missing UI 4-state (`Loading`/`Empty`/`No-Results`/`Error`) & `!res.success` optimistic rollback, and unscheduled mock (`DEFAULT_*`/`MOCK_*`) or orphan component cleanup.
- Flag ambiguous requirements or vague acceptance criteria that require explicit decisions.
"""


@dataclass
class SpecCritiqueResult:
    success: bool
    model_used: str
    fallback_triggered: bool
    report_path: str
    summary: str
    error: Optional[str] = None
    dispatch_mode: str = "cli"
    dispatch_directive: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecCritiqueResult":
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def build_spec_critic_prompt(spec_path: Path, spec_content: str, persona_content: str) -> str:
    """Build a hermetic zero-context prompt containing rubric, spec path, and spec content."""
    spec_display = spec_path.as_posix() if hasattr(spec_path, "as_posix") else str(spec_path).replace("\\", "/")
    return (
        f"{persona_content.strip()}\n\n"
        f"---\n\n"
        f"Target Specification Path: {spec_display}\n\n"
        f"Specification Content:\n"
        f"```markdown\n"
        f"{spec_content}\n"
        f"```\n\n"
        f"Instructions:\n"
        f"Provide your advisory critique adhering strictly to the 3 mandatory sections in under 400 words."
    )


_QUOTA_INDICATORS = ("429", "quota", "rate limit", "resource_exhausted", "exhausted", "unavailable")
_PLANNING_TRAPS = ("your request was only", "planning mode is on", "your message ends at", "doesn't say what you want planned")
_MISSING_BIN_MARKERS = (
    "filenotfounderror",
    "no such file or directory",
    "not recognized as an internal or external command",
    "command not found",
    "cannot find the file specified",
)


def _has_planning_or_quota_error(stdout_lower: str, stderr_lower: str) -> bool:
    if any(k in stderr_lower for k in _QUOTA_INDICATORS):
        return True
    if any(t in stdout_lower for t in _PLANNING_TRAPS):
        return True
    if any(k in stdout_lower for k in _QUOTA_INDICATORS):
        return any(err_word in stdout_lower for err_word in ("error", "fail", "exception"))
    return False


def _should_fallback(returncode: int, stdout: str, stderr: str) -> bool:
    """Return True when CLI execution failed, output is empty, or quota/planning trap occurred."""
    if returncode != 0 or not (stdout or "").strip():
        return True
    return _has_planning_or_quota_error(stdout.strip().lower(), (stderr or "").lower())


def _is_missing_binary_error(code: int, err: str) -> bool:
    if shutil.which("agy") is not None:
        return False
    err_low = (err or "").lower()
    return code == 127 or any(marker in err_low for marker in _MISSING_BIN_MARKERS)


def _resolve_spec_path(norm_repo: Path, spec_path: Union[Path, str]) -> Path:
    raw_spec_str = str(spec_path).replace("\\", "/")
    is_abs = raw_spec_str.startswith("/") or (len(raw_spec_str) >= 2 and raw_spec_str[1] == ":") or raw_spec_str.startswith("//")
    return normalize_target_path(spec_path) if is_abs else normalize_target_path(norm_repo / spec_path)


def _load_target_spec_and_prompt(
    norm_repo: Path, spec_path: Optional[Union[Path, str]], issue_number: Optional[int], offline: bool
) -> Tuple[Optional[Path], Any, Optional[str], Optional[SpecCritiqueResult]]:
    from tools.tracker.backends import resolve_backend
    from tools.tracker.cache import cache_issue_spec

    tracker_backend = None
    if issue_number is not None:
        tracker_backend = resolve_backend(norm_repo, offline=offline)
        issue = tracker_backend.get_issue(int(issue_number), include_comments=False)
        resolved_spec = cache_issue_spec(norm_repo, issue)
    elif spec_path is not None:
        resolved_spec = _resolve_spec_path(norm_repo, spec_path)
    else:
        return None, None, None, SpecCritiqueResult(False, "", False, "", "", "Either spec_path or issue_number must be provided.")
    if not resolved_spec.is_file():
        return None, None, None, SpecCritiqueResult(False, "", False, "", "", f"Spec file not found: {spec_path}")
    try:
        spec_content = resolved_spec.read_text(encoding="utf-8")
    except Exception as exc:
        return None, None, None, SpecCritiqueResult(False, "", False, "", "", f"Failed to read spec file {resolved_spec}: {exc}")
    try:
        from tools.brigade.stations import StationRegistry
        persona = StationRegistry.load_station_rubric("spec-critic", repo_path=norm_repo)
    except Exception:
        persona = DEFAULT_PERSONA_RUBRIC
    try:
        rel_spec = resolved_spec.relative_to(norm_repo)
    except ValueError:
        rel_spec = resolved_spec
    return resolved_spec, tracker_backend, build_spec_critic_prompt(rel_spec, spec_content, persona), None


def _build_native_critic_result(
    norm_repo: Path, resolved_spec: Path, prompt: str, issue_number: Optional[int], fallback_triggered: bool = False
) -> SpecCritiqueResult:
    from tools.brigade.station_dispatch import build_spec_critic_dispatch

    dispatch_mode, directive, prompt_file = build_spec_critic_dispatch(
        repo_path=norm_repo, spec_path=resolved_spec, prompt=prompt, issue_number=issue_number
    )
    resolved_model = str(directive.get("model") or directive.get("Model") or "flash")
    summary = f"Native {dispatch_mode} SPEC_CRITIC dispatch ready ({prompt_file.name})."
    return SpecCritiqueResult(
        success=True,
        model_used=resolved_model,
        fallback_triggered=fallback_triggered,
        report_path=str(prompt_file),
        summary=summary,
        error=None,
        dispatch_mode=dispatch_mode,
        dispatch_directive=directive,
    )


def _write_cli_critique_report(
    norm_repo: Path, resolved_spec: Path, tracker_backend: Any, issue_number: Optional[int],
    post_comment: bool, model_used: str, fallback_triggered: bool, out: str,
) -> SpecCritiqueResult:
    from tools.common.fs import atomic_write_text, resolve_target_repo_root

    if issue_number is not None:
        report_file = resolve_target_repo_root(norm_repo) / ".edge" / "cache" / "issues" / f"{int(issue_number)}-critique.md"
    else:
        report_file = norm_repo / ".edge" / "specs" / f"{resolved_spec.stem}-critique.md"
    try:
        rel_spec_path = resolved_spec.relative_to(norm_repo)
    except ValueError:
        rel_spec_path = resolved_spec
    gen_time = datetime.now(timezone.utc).isoformat()
    report_content = (
        f"# Spec Critique: {resolved_spec.name}\n\n"
        f"- **Model:** {model_used}\n- **Fallback Triggered:** {fallback_triggered}\n"
        f"- **Source Spec:** {rel_spec_path}\n- **Generated At:** {gen_time}\n\n---\n\n{out.strip()}\n"
    )
    atomic_write_text(report_file, report_content)
    if tracker_backend is not None and issue_number is not None and post_comment:
        tracker_backend.add_comment(int(issue_number), report_content)
    summary_line = out.strip().split("\n\n")[0] if "\n\n" in out.strip() else out.strip()[:200]
    return SpecCritiqueResult(True, model_used, fallback_triggered, str(report_file), summary_line, None)


def run_spec_critique(
    repo_path: Union[Path, str],
    spec_path: Optional[Union[Path, str]] = None,
    primary_model: str = PRIMARY_CRITIC_MODEL,
    fallback_model: str = FALLBACK_CRITIC_MODEL,
    timeout: int = 180,
    issue_number: Optional[int] = None,
    offline: bool = False,
    post_comment: bool = True,
    native: bool = False,
) -> SpecCritiqueResult:
    """Execute advisory critique via agy CLI or native Swarm/subagent dispatch."""
    norm_repo = normalize_target_path(repo_path)
    resolved_spec, tracker_backend, prompt, err_res = _load_target_spec_and_prompt(norm_repo, spec_path, issue_number, offline)
    if err_res is not None or resolved_spec is None or prompt is None:
        return err_res  # type: ignore[return-value]
    if native:
        return _build_native_critic_result(norm_repo, resolved_spec, prompt, issue_number)
    model_used, fallback_triggered = primary_model, False
    code, out, err = run_command(["agy", "--model", primary_model, "-p", prompt], cwd=norm_repo, timeout=timeout)
    if _is_missing_binary_error(code, err):
        return _build_native_critic_result(norm_repo, resolved_spec, prompt, issue_number, fallback_triggered=True)
    if _should_fallback(code, out, err) and fallback_model and fallback_model != primary_model:
        code, out, err = run_command(["agy", "--model", fallback_model, "-p", prompt], cwd=norm_repo, timeout=timeout)
        fallback_triggered, model_used = True, fallback_model
    if code == 0 and out.strip() and not _should_fallback(code, out, err):
        return _write_cli_critique_report(
            norm_repo, resolved_spec, tracker_backend, issue_number, post_comment, model_used, fallback_triggered, out
        )
    return SpecCritiqueResult(False, model_used, fallback_triggered, "", "", err.strip() or "Process exited with non-zero code or empty output")
