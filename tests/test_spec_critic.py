"""
Unit tests for tools.brigade.spec_critic (Cross-Provider Goldfish Spec Critic).
Hermetic tests verifying prompt generation, primary model execution,
automatic quota/rate-limit fallback, atomic report writes, and error handling.
"""

from pathlib import Path
import os
import sys
from unittest.mock import patch

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.brigade.spec_critic import (
    PRIMARY_CRITIC_MODEL,
    FALLBACK_CRITIC_MODEL,
    SpecCritiqueResult,
    build_spec_critic_prompt,
    _should_fallback,
    run_spec_critique,
)


def test_primary_model_succeeds(tmp_path: Path):
    """
    Test 1: Primary claude-opus-5-5-high succeeds.
    Verifies agy arguments, fallback_triggered is False, atomic report creation,
    and zero leftover .tmp files.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    specs_dir = repo_dir / "docs" / "specs"
    specs_dir.mkdir(parents=True)
    spec_file = specs_dir / "slice-auth.md"
    spec_file.write_text("# Slice Auth Specification\nContent here...", encoding="utf-8")

    critique_text = (
        "## 1. Paraphrase Check\n"
        "Proposed auth slice handles sessions. Interacts with repository contracts.\n"
        "Assumes token validity.\n\n"
        "## 2. Flexibility & Code Reuse (Anti-Debt)\n"
        "Reuse session utility from core.\n\n"
        "## 3. Zero-Decision & Edge-Case Audit\n"
        "No ambiguity found."
    )

    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        mock_run.return_value = (0, critique_text, "")

        result = run_spec_critique(repo_dir, spec_file)

        assert result.success is True
        assert result.model_used == PRIMARY_CRITIC_MODEL
        assert result.fallback_triggered is False
        assert result.error is None
        assert mock_run.call_count == 1

        # Check command args: agy --model <model> -p <prompt>
        cmd = mock_run.call_args[0][0]
        assert len(cmd) == 5
        assert cmd[0] == "agy"
        assert cmd[1:4] == ["--model", "claude-opus-5-5-high", "-p"]
        prompt_arg = cmd[-1]
        assert "slice-auth.md" in prompt_arg
        assert "# Slice Auth Specification" in prompt_arg

        # Verify atomic report existence and metadata
        report_file = repo_dir / ".edge" / "specs" / "slice-auth-critique.md"
        assert report_file.is_file()
        assert str(report_file) == result.report_path

        report_content = report_file.read_text(encoding="utf-8")
        assert "- **Model:** claude-opus-5-5-high" in report_content
        assert "- **Fallback Triggered:** False" in report_content
        assert "- **Source Spec:**" in report_content
        assert "- **Generated At:**" in report_content
        assert "## 1. Paraphrase Check" in report_content

        # Verify no .tmp files exist
        tmp_files = list((repo_dir / ".edge" / "specs").glob("*.tmp*"))
        assert len(tmp_files) == 0


def test_primary_quota_error_triggers_fallback_success(tmp_path: Path):
    """
    Test 2: Primary fails with quota error (returncode=1, stderr 'Error 429: quota exhausted').
    Automatically falls back to gemini-3.8-flash-high, succeeds, and marks fallback_triggered=True.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = repo_dir / "slice-booking.md"
    spec_file.write_text("# Slice Booking Specification", encoding="utf-8")

    fallback_text = (
        "## 1. Paraphrase Check\n"
        "Booking management slice with slot allocation.\n\n"
        "## 2. Flexibility & Code Reuse (Anti-Debt)\n"
        "Reuse slot reservation service.\n\n"
        "## 3. Zero-Decision & Edge-Case Audit\n"
        "Handle booking timeout explicitly."
    )

    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        mock_run.side_effect = [
            (1, "", "Error 429: quota exhausted"),
            (0, fallback_text, ""),
        ]

        result = run_spec_critique(repo_dir, "slice-booking.md")

        assert result.success is True
        assert result.model_used == FALLBACK_CRITIC_MODEL
        assert result.fallback_triggered is True
        assert result.error is None
        assert mock_run.call_count == 2

        # Check call 1 was primary, call 2 was fallback
        call_1_cmd = mock_run.call_args_list[0][0][0]
        assert len(call_1_cmd) == 5
        assert call_1_cmd[1:4] == ["--model", "claude-opus-5-5-high", "-p"]
        assert "slice-booking.md" in call_1_cmd[-1]

        call_2_cmd = mock_run.call_args_list[1][0][0]
        assert len(call_2_cmd) == 5
        assert call_2_cmd[1:4] == ["--model", "gemini-3.8-flash-high", "-p"]
        assert "slice-booking.md" in call_2_cmd[-1]

        # Check persisted report
        report_file = repo_dir / ".edge" / "specs" / "slice-booking-critique.md"
        assert report_file.is_file()
        content = report_file.read_text(encoding="utf-8")
        assert "- **Model:** gemini-3.8-flash-high" in content
        assert "- **Fallback Triggered:** True" in content
        assert "Handle booking timeout explicitly." in content


def test_primary_empty_stdout_triggers_fallback(tmp_path: Path):
    """
    Test 3: Primary returns returncode=0 with empty stdout ''.
    Triggers fallback to gemini-3.8-flash-high and succeeds.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = repo_dir / "slice-empty.md"
    spec_file.write_text("# Slice Empty Specification", encoding="utf-8")

    fallback_text = "## 1. Paraphrase Check\nFallback succeeded."

    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        mock_run.side_effect = [
            (0, "   ", ""),
            (0, fallback_text, ""),
        ]

        result = run_spec_critique(repo_dir, "slice-empty.md")

        assert result.success is True
        assert result.model_used == FALLBACK_CRITIC_MODEL
        assert result.fallback_triggered is True
        assert mock_run.call_count == 2


def test_both_primary_and_fallback_fail(tmp_path: Path):
    """
    Test 4: Both primary and fallback fail.
    Returns success=False with clean error message and no partial report written.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = repo_dir / "slice-fail.md"
    spec_file.write_text("# Slice Fail Specification", encoding="utf-8")

    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        mock_run.side_effect = [
            (1, "", "Error 429: rate limit exceeded"),
            (1, "", "Fatal: model unavailable"),
        ]

        result = run_spec_critique(repo_dir, spec_file)

        assert result.success is False
        assert result.fallback_triggered is True
        assert result.model_used == FALLBACK_CRITIC_MODEL
        assert result.report_path == ""
        assert "model unavailable" in result.error

        specs_dir = repo_dir / ".edge" / "specs"
        if specs_dir.exists():
            reports = list(specs_dir.glob("*.md"))
            assert len(reports) == 0
            tmp_files = list(specs_dir.glob("*.tmp*"))
            assert len(tmp_files) == 0


def test_missing_spec_file_fails_immediately(tmp_path: Path):
    """
    Test 5: Missing spec file.
    Returns success=False immediately with 0 subprocess calls.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        result = run_spec_critique(repo_dir, "non-existent-spec.md")

        assert result.success is False
        assert result.model_used == ""
        assert result.fallback_triggered is False
        assert "Spec file not found" in result.error
        mock_run.assert_not_called()


def test_spec_critique_result_serialization():
    """
    Verifies to_dict and from_dict roundtrip.
    """
    res = SpecCritiqueResult(
        success=True,
        model_used="claude-opus-5-5-high",
        fallback_triggered=False,
        report_path="/path/to/report.md",
        summary="Paraphrase summary",
        error=None,
    )
    d = res.to_dict()
    assert d["success"] is True
    assert d["model_used"] == "claude-opus-5-5-high"

    reconstructed = SpecCritiqueResult.from_dict(d)
    assert reconstructed == res


def test_should_fallback_matrix():
    """
    Verifies the _should_fallback heuristic across varied status codes, stdout, and stderr.
    """
    # Success cases
    assert _should_fallback(0, "Valid critique text", "") is False

    # Failure code
    assert _should_fallback(1, "Some text", "Error") is True

    # Empty stdout
    assert _should_fallback(0, "", "") is True
    assert _should_fallback(0, "   \n\t ", "") is True

    # Quota / rate limit keywords in stderr
    assert _should_fallback(0, "Some text", "429 Too Many Requests") is True
    assert _should_fallback(0, "Some text", "Resource exhausted by quota") is True
    assert _should_fallback(0, "Some text", "Rate limit reached") is True

    # Quota error in stdout
    assert _should_fallback(0, "Error: 429 quota exhausted", "") is True
    assert _should_fallback(0, "Fatal error: model unavailable", "") is True

    # Planning mode CLI trap in stdout
    assert _should_fallback(0, "Planning mode is on, but your request was only '-'", "") is True
    assert (
        _should_fallback(
            0,
            "Planning mode is on, but your message ends at '-' and doesn't say what you want planned.",
            "",
        )
        is True
    )


def test_planning_mode_trap_stdout_triggers_fallback_and_prevents_corrupt_report(tmp_path: Path):
    """
    Verifies that when primary returns exit code 0 with the 'Planning mode is on, ...' trap message:
    1. run_spec_critique triggers fallback to FALLBACK_CRITIC_MODEL.
    2. If fallback ALSO returns the 'Planning mode is on, ...' trap message, run_spec_critique
       returns result.success is False and does NOT write a corrupt critique file to disk.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = repo_dir / "slice-trap.md"
    spec_file.write_text("# Slice Trap Specification", encoding="utf-8")

    trap_msg = "Planning mode is on, but your request was only '-'"

    # Case 1: Primary hits trap, fallback succeeds with valid critique
    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        mock_run.side_effect = [
            (0, trap_msg, ""),
            (0, "## 1. Paraphrase Check\nFallback succeeded after planning mode trap.", ""),
        ]
        res_ok = run_spec_critique(repo_dir, spec_file)
        assert res_ok.success is True
        assert res_ok.fallback_triggered is True
        assert res_ok.model_used == FALLBACK_CRITIC_MODEL
        assert mock_run.call_count == 2

    # Clean up report before Case 2
    report_file = repo_dir / ".edge" / "specs" / "slice-trap-critique.md"
    if report_file.exists():
        report_file.unlink()

    # Case 2: Both primary and fallback return the planning mode trap message
    with patch("tools.brigade.spec_critic.run_command") as mock_run:
        mock_run.side_effect = [
            (0, trap_msg, ""),
            (0, trap_msg, ""),
        ]
        result = run_spec_critique(repo_dir, spec_file)
        assert result.success is False
        assert result.fallback_triggered is True
        assert result.report_path == ""
        assert not report_file.exists(), "Corrupt planning-mode trap stdout must NOT be persisted to disk"
        assert mock_run.call_count == 2


def test_build_spec_critic_prompt():
    """
    Verifies that the generated prompt contains persona rubric, path, and spec text.
    """
    prompt = build_spec_critic_prompt(
        Path("docs/specs/test.md"),
        "Specification content for test slice.",
        "Goldfish persona rubric.",
    )
    assert "Goldfish persona rubric." in prompt
    assert "docs/specs/test.md" in prompt
    assert "Specification content for test slice." in prompt
    assert "## 1. Paraphrase Check" not in prompt or "Goldfish" in prompt
