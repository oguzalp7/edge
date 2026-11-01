"""
Cross-Provider Zero-Context Goldfish Spec Critic Engine.
Executes an isolated, single-shot advisory critique of slice specifications
using high-reasoning primary frontier models (claude-opus-5-5-high)
with automatic fallback to flash models (gemini-3.8-flash-high).
"""

from dataclasses import dataclass, asdict, fields
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Optional, Dict, Any, Union

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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecCritiqueResult":
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def build_spec_critic_prompt(spec_path: Path, spec_content: str, persona_content: str) -> str:
    """
    Builds a hermetic zero-context prompt containing the persona rubric,
    the relative/target spec path, and the full spec content.
    """
    return (
        f"{persona_content.strip()}\n\n"
        f"---\n\n"
        f"Target Specification Path: {spec_path}\n\n"
        f"Specification Content:\n"
        f"```markdown\n"
        f"{spec_content}\n"
        f"```\n\n"
        f"Instructions:\n"
        f"Provide your advisory critique adhering strictly to the 3 mandatory sections in under 400 words."
    )


def _should_fallback(returncode: int, stdout: str, stderr: str) -> bool:
    """
    Determines if fallback model invocation should be triggered based on process execution results.
    Returns True when returncode != 0, when stdout is empty/whitespace,
    or when stderr/stdout indicates quota/rate-limit/model unavailability.
    """
    if returncode != 0:
        return True

    clean_stdout = stdout.strip() if stdout else ""
    if not clean_stdout:
        return True

    stderr_lower = stderr.lower() if stderr else ""
    stdout_lower = clean_stdout.lower()

    indicators = [
        "429",
        "quota",
        "rate limit",
        "resource_exhausted",
        "exhausted",
        "unavailable",
    ]

    # Stderr check: any quota/rate-limit/unavailability indicator in stderr
    if any(k in stderr_lower for k in indicators):
        return True

    # Stdout check: error message indicating quota/rate-limit/unavailability
    if any(k in stdout_lower for k in indicators):
        if any(err_word in stdout_lower for err_word in ["error", "fail", "exception"]):
            return True

    return False


def run_spec_critique(
    repo_path: Union[Path, str],
    spec_path: Union[Path, str],
    primary_model: str = PRIMARY_CRITIC_MODEL,
    fallback_model: str = FALLBACK_CRITIC_MODEL,
    timeout: int = 180,
) -> SpecCritiqueResult:
    """
    Executes an advisory single-shot critique of the target specification.
    Invokes primary model with transparent fallback to secondary model on quota/failure.
    Atomically writes the resulting critique report to .edge/specs/<spec_stem>-critique.md.
    Advisory invariant: Does not mutate .edge/brigade.json or lock FSM transitions.
    """
    norm_repo = normalize_target_path(repo_path)

    raw_spec_str = str(spec_path).replace("\\", "/")
    if (
        raw_spec_str.startswith("/")
        or (len(raw_spec_str) >= 2 and raw_spec_str[1] == ":")
        or raw_spec_str.startswith("//")
    ):
        resolved_spec = normalize_target_path(spec_path)
    else:
        resolved_spec = normalize_target_path(norm_repo / spec_path)

    if not resolved_spec.is_file():
        return SpecCritiqueResult(
            success=False,
            model_used="",
            fallback_triggered=False,
            report_path="",
            summary="",
            error=f"Spec file not found: {spec_path}",
        )

    try:
        spec_content = resolved_spec.read_text(encoding="utf-8")
    except Exception as e:
        return SpecCritiqueResult(
            success=False,
            model_used="",
            fallback_triggered=False,
            report_path="",
            summary="",
            error=f"Failed to read spec file {resolved_spec}: {str(e)}",
        )

    # Load persona rubric from agents/spec-critic.md if available
    plugin_root = Path(__file__).resolve().parent.parent.parent
    persona_path = plugin_root / "agents" / "spec-critic.md"
    persona_content = DEFAULT_PERSONA_RUBRIC
    if persona_path.is_file():
        try:
            persona_content = persona_path.read_text(encoding="utf-8")
        except Exception:
            persona_content = DEFAULT_PERSONA_RUBRIC

    try:
        rel_spec_path = resolved_spec.relative_to(norm_repo)
    except ValueError:
        rel_spec_path = resolved_spec

    prompt = build_spec_critic_prompt(rel_spec_path, spec_content, persona_content)

    model_used = primary_model
    fallback_triggered = False

    cmd = ["agy", "-p", "--mode", "plan", "--model", primary_model, prompt]
    code, out, err = run_command(cmd, cwd=norm_repo, timeout=timeout)

    if _should_fallback(code, out, err) and fallback_model and fallback_model != primary_model:
        fallback_cmd = ["agy", "-p", "--mode", "plan", "--model", fallback_model, prompt]
        code, out, err = run_command(fallback_cmd, cwd=norm_repo, timeout=timeout)
        fallback_triggered = True
        model_used = fallback_model

    specs_dir = norm_repo / ".edge" / "specs"
    report_file = specs_dir / f"{resolved_spec.stem}-critique.md"
    tmp_file = specs_dir / f"{resolved_spec.stem}-critique.md.tmp.{os.getpid()}"

    if tmp_file.exists():
        try:
            tmp_file.unlink()
        except OSError:
            pass

    if code == 0 and out.strip():
        specs_dir.mkdir(parents=True, exist_ok=True)
        gen_time = datetime.now(timezone.utc).isoformat()
        report_content = (
            f"# Spec Critique: {resolved_spec.name}\n\n"
            f"- **Model:** {model_used}\n"
            f"- **Fallback Triggered:** {fallback_triggered}\n"
            f"- **Source Spec:** {rel_spec_path}\n"
            f"- **Generated At:** {gen_time}\n\n"
            f"---\n\n"
            f"{out.strip()}\n"
        )
        try:
            tmp_file.write_text(report_content, encoding="utf-8")
            os.replace(tmp_file, report_file)
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except OSError:
                    pass

        summary_line = out.strip().split("\n\n")[0] if "\n\n" in out.strip() else out.strip()[:200]
        return SpecCritiqueResult(
            success=True,
            model_used=model_used,
            fallback_triggered=fallback_triggered,
            report_path=str(report_file),
            summary=summary_line,
            error=None,
        )

    if tmp_file.exists():
        try:
            tmp_file.unlink()
        except OSError:
            pass

    error_msg = err.strip() if err.strip() else "Process exited with non-zero code or empty output"
    return SpecCritiqueResult(
        success=False,
        model_used=model_used,
        fallback_triggered=fallback_triggered,
        report_path="",
        summary="",
        error=error_msg,
    )
