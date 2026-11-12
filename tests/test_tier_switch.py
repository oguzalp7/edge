"""
Hermetic test suite for Edge Brigade Tier Switcher and Skills (TICK-FEAT-TIER-SWITCH-SKILLS).
Validates:
- TierState dataclass serialization / deserialization roundtrip
- Model matrices (PRO_STATION_MODELS, ULTRA_STATION_MODELS)
- State discovery with branch fallback (main -> pro, ultra -> ultra)
- Clean working tree validation and branch switching (main <-> ultra)
- Rejection of dirty tracked files outside .edge/
- Tolerance of .edge/ internal changes and untracked files
- Invalid tier rejection
- Markdown card formatting
- CLI integration (tools/brigade/tier.py and tools/brigade/cli.py tier)
- Skill definitions (skills/edge-pro/SKILL.md, skills/edge-ultra/SKILL.md)
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Soft import to allow clean RED test discovery before Coder implements the module
try:
    import tools.brigade.tier as tier
    from tools.brigade.tier import (
        PRO_BRANCH,
        PRO_STATION_MODELS,
        PRO_TRANSPORT,
        STATION_DESCRIPTIONS,
        ULTRA_BRANCH,
        ULTRA_STATION_MODELS,
        ULTRA_TRANSPORT,
        VALID_TIERS,
        TierState,
        format_tier_card,
        get_tier_state_path,
        get_tier_status,
        switch_tier,
    )
except ImportError:
    tier = None

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def hermetic_env(tmp_path, monkeypatch):
    """
    Ensures zero mutation of the operator's live ~/.gemini/antigravity/edge_tier.json
    by forcing EDGE_TIER_STATE_PATH to point inside tmp_path.
    """
    sandbox_state = tmp_path / "sandbox_edge_tier.json"
    monkeypatch.setenv("EDGE_TIER_STATE_PATH", str(sandbox_state))
    return sandbox_state


def create_mock_git_repo(path: Path, branch: str = "main") -> Path:
    """Initializes a hermetic git repository with an initial commit on the given branch."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "brigade-test@example.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Brigade Test"],
        cwd=str(path),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "checkout", "-b", branch], cwd=str(path), check=True, capture_output=True, text=True)
    readme = path / "README.md"
    readme.write_text("# Mock Repository\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(path), check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=str(path), check=True, capture_output=True, text=True)
    return path


def get_current_branch(repo_path: Path) -> str:
    """Helper to inspect current branch via git rev-parse."""
    res = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()


# =========================================================================
# 1. Constants & Model Matrices Contract
# =========================================================================


def test_station_model_matrices_and_constants():
    """Validates model allocation matrices for all 8 canonical station roles."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    canonical_roles = {
        "spec_writer",
        "researcher",
        "spec_critic",
        "seam_architect",
        "coder",
        "surgeon",
        "examiner",
        "qa_engineer",
    }

    assert set(PRO_STATION_MODELS.keys()) == canonical_roles
    assert set(ULTRA_STATION_MODELS.keys()) == canonical_roles
    assert set(STATION_DESCRIPTIONS.keys()) == canonical_roles

    # Pro models verification
    assert PRO_STATION_MODELS["spec_critic"] == "gemini-3.8-flash-high"
    for role, model in PRO_STATION_MODELS.items():
        if role != "spec_critic":
            assert model == "flash", f"Expected 'flash' for pro role {role}, got {model}"

    # Ultra models verification
    assert ULTRA_STATION_MODELS["spec_writer"] == "gemini-4-hydrogen-high"
    assert ULTRA_STATION_MODELS["researcher"] == "gemini-4-hydrogen-high"
    assert ULTRA_STATION_MODELS["spec_critic"] == "claude-opus-5-5-high"
    assert ULTRA_STATION_MODELS["seam_architect"] == "gemini-4-hydrogen-xhigh"
    assert ULTRA_STATION_MODELS["coder"] == "gemini-4-hydrogen-high"
    assert ULTRA_STATION_MODELS["surgeon"] == "gemini-4-hydrogen-high"
    assert ULTRA_STATION_MODELS["examiner"] == "gemini-4-hydrogen-high"
    assert ULTRA_STATION_MODELS["qa_engineer"] == "gemini-4-hydrogen-medium"

    # Invariant constants
    assert PRO_BRANCH == "main"
    assert ULTRA_BRANCH == "ultra"
    assert PRO_TRANSPORT == "invoke_subagent"
    assert ULTRA_TRANSPORT == "swarm"
    assert VALID_TIERS == ("pro", "ultra")


# =========================================================================
# 2. TierState Dataclass Serialization Roundtrip
# =========================================================================


def test_tier_state_serialization_roundtrip():
    """Validates serialization to/from dictionary."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    state = TierState(
        tier="ultra",
        branch="ultra",
        transport="swarm",
        station_models=dict(ULTRA_STATION_MODELS),
        updated_at="2026-11-12T23:45:00+00:00",
    )

    d = state.to_dict()
    assert d["tier"] == "ultra"
    assert d["branch"] == "ultra"
    assert d["transport"] == "swarm"
    assert d["station_models"]["spec_critic"] == "claude-opus-5-5-high"
    assert d["updated_at"] == "2026-11-12T23:45:00+00:00"

    restored = TierState.from_dict(d)
    assert restored.tier == state.tier
    assert restored.branch == state.branch
    assert restored.transport == state.transport
    assert restored.station_models == state.station_models
    assert restored.updated_at == state.updated_at


def test_tier_state_from_dict_defaults():
    """Validates from_dict backward compatibility with missing or sparse fields."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    sparse = {"tier": "pro"}
    state = TierState.from_dict(sparse)
    assert state.tier == "pro"
    assert state.branch == "main"
    assert state.transport == "invoke_subagent"
    assert state.station_models == PRO_STATION_MODELS
    assert state.updated_at != ""


# =========================================================================
# 3. State Path Resolver & Hermetic Environment Invariant
# =========================================================================


def test_get_tier_state_path_respects_env_override(tmp_path, monkeypatch):
    """Validates get_tier_state_path respects EDGE_TIER_STATE_PATH."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    custom_path = tmp_path / "custom" / "tier.json"
    monkeypatch.setenv("EDGE_TIER_STATE_PATH", str(custom_path))
    assert get_tier_state_path() == custom_path

    monkeypatch.delenv("EDGE_TIER_STATE_PATH", raising=False)
    expected_default = Path.home() / ".gemini" / "antigravity" / "edge_tier.json"
    assert get_tier_state_path() == expected_default


# =========================================================================
# 4. State Status Discovery & Fallback
# =========================================================================


def test_get_tier_status_fallback_to_main_branch(tmp_path):
    """Validates that a fresh repository on 'main' branch without state file resolves to Pro tier."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_main", branch="main")
    state_file = tmp_path / "non_existent_tier.json"

    state = get_tier_status(repo, state_path=state_file)
    assert state.tier == "pro"
    assert state.branch == "main"
    assert state.transport == "invoke_subagent"
    assert state.station_models == PRO_STATION_MODELS


def test_get_tier_status_fallback_to_ultra_branch(tmp_path):
    """Validates that a repository on 'ultra' branch without state file resolves to Ultra tier."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_ultra", branch="ultra")
    state_file = tmp_path / "non_existent_tier.json"

    state = get_tier_status(repo, state_path=state_file)
    assert state.tier == "ultra"
    assert state.branch == "ultra"
    assert state.transport == "swarm"
    assert state.station_models == ULTRA_STATION_MODELS


def test_get_tier_status_reads_persisted_file(tmp_path):
    """Validates reading from an existing persisted state file."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_test", branch="main")
    state_file = tmp_path / "persisted_tier.json"

    expected = TierState(
        tier="ultra",
        branch="ultra",
        transport="swarm",
        station_models=dict(ULTRA_STATION_MODELS),
        updated_at="2026-11-12T12:00:00+00:00",
    )
    state_file.write_text(json.dumps(expected.to_dict(), indent=2), encoding="utf-8")

    loaded = get_tier_status(repo, state_path=state_file)
    assert loaded.tier == "ultra"
    assert loaded.branch == "ultra"
    assert loaded.station_models["spec_critic"] == "claude-opus-5-5-high"


# =========================================================================
# 5. Core Tier Switching Engine
# =========================================================================


def test_switch_tier_to_ultra_creates_branch_and_updates_state(tmp_path):
    """Validates switching from Pro to Ultra: creates branch, checks it out, and writes state atomically."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_switch", branch="main")
    state_file = tmp_path / "edge_tier.json"

    ok, card, state = switch_tier(repo, "ultra", state_path=state_file)

    assert ok is True
    assert "Edge Execution Tier: ULTRA" in card
    assert state.tier == "ultra"
    assert state.branch == "ultra"
    assert state.transport == "swarm"
    assert state.station_models == ULTRA_STATION_MODELS

    # Verify git working tree branch
    assert get_current_branch(repo) == "ultra"

    # Verify persisted state file on disk
    assert state_file.is_file()
    disk_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert disk_data["tier"] == "ultra"
    assert disk_data["transport"] == "swarm"


def test_switch_tier_to_pro_switches_to_main_and_updates_state(tmp_path):
    """Validates switching from Ultra back to Pro: checks out main and writes Pro state."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_switch_back", branch="main")
    state_file = tmp_path / "edge_tier.json"

    # First switch to ultra
    ok1, _, _ = switch_tier(repo, "ultra", state_path=state_file)
    assert ok1 is True
    assert get_current_branch(repo) == "ultra"

    # Now switch back to pro
    ok2, card, state = switch_tier(repo, "pro", state_path=state_file)
    assert ok2 is True
    assert "Edge Execution Tier: PRO" in card
    assert state.tier == "pro"
    assert state.branch == "main"
    assert state.transport == "invoke_subagent"
    assert state.station_models == PRO_STATION_MODELS

    # Verify git working tree branch
    assert get_current_branch(repo) == "main"

    # Verify persisted state file on disk
    disk_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert disk_data["tier"] == "pro"
    assert disk_data["transport"] == "invoke_subagent"


def test_switch_tier_blocked_by_dirty_tracked_files(tmp_path):
    """
    Clean Working Tree Invariant:
    A tier switch must be blocked if uncommitted tracked files outside .edge/ are present.
    """
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_dirty", branch="main")
    state_file = tmp_path / "edge_tier.json"

    # Mutate tracked file README.md
    readme = repo / "README.md"
    readme.write_text("# Mock Repository - Modified!\n", encoding="utf-8")

    ok, err_msg, state = switch_tier(repo, "ultra", state_path=state_file)

    assert ok is False
    assert "README.md" in err_msg or "uncommitted tracked changes" in err_msg.lower()
    # Branch must remain unchanged
    assert get_current_branch(repo) == "main"
    # State file must not be modified to ultra
    assert not state_file.is_file()


def test_switch_tier_allows_dirty_edge_and_untracked_files(tmp_path):
    """
    Dirty Tolerance Invariant:
    Modifications inside .edge/ and untracked files (??) must NEVER block a tier switch.
    """
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_edge_dirty", branch="main")
    state_file = tmp_path / "edge_tier.json"

    # Create tracked file in .edge/ and modify it
    edge_dir = repo / ".edge"
    edge_dir.mkdir(parents=True, exist_ok=True)
    brigade_json = edge_dir / "brigade.json"
    brigade_json.write_text('{"state": "DIRTY_TEST"}\n', encoding="utf-8")
    subprocess.run(["git", "add", ".edge/brigade.json"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Add .edge state"], cwd=str(repo), check=True, capture_output=True)

    # Now dirty .edge/brigade.json
    brigade_json.write_text('{"state": "MUTATED_UNCOMMITTED"}\n', encoding="utf-8")

    # Add an untracked scratch file
    scratch = repo / "scratch_notes.txt"
    scratch.write_text("temporary scratch notes\n", encoding="utf-8")

    ok, card, state = switch_tier(repo, "ultra", state_path=state_file)

    assert ok is True
    assert state.tier == "ultra"
    assert get_current_branch(repo) == "ultra"


def test_switch_tier_rejects_invalid_tier_mode(tmp_path):
    """Validates rejection of unsupported tier names."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_invalid", branch="main")
    state_file = tmp_path / "edge_tier.json"

    for invalid in ["turbo", "super", "", "123", "extreme"]:
        ok, err_msg, state = switch_tier(repo, invalid, state_path=state_file)
        assert ok is False
        assert "invalid tier" in err_msg.lower()


def test_atomic_write_leaves_no_temporary_cruft(tmp_path):
    """
    Atomic Persistence Invariant:
    Writing state files must leave zero residual .tmp.<pid> files.
    """
    assert tier is not None, "tools.brigade.tier module must be implemented"

    repo = create_mock_git_repo(tmp_path / "repo_atomic", branch="main")
    state_dir = tmp_path / "state_dir"
    state_file = state_dir / "edge_tier.json"

    ok, _, _ = switch_tier(repo, "ultra", state_path=state_file)
    assert ok is True
    assert state_file.is_file()

    leftover_tmp_files = list(state_dir.glob("*.tmp.*"))
    assert leftover_tmp_files == [], f"Found residual atomic temporary files: {leftover_tmp_files}"


# =========================================================================
# 6. Markdown Visualizer Presentation
# =========================================================================


def test_format_tier_card_renders_all_eight_stations():
    """Validates markdown status card generation with table layout."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    ultra_state = TierState(
        tier="ultra",
        branch="ultra",
        transport="swarm",
        station_models=dict(ULTRA_STATION_MODELS),
        updated_at="2026-11-12T23:59:59+00:00",
    )
    card = format_tier_card(ultra_state)

    assert "### 🚀 Edge Execution Tier: ULTRA" in card
    assert "- **Tier:** `ultra`" in card
    assert "- **Active Branch:** `ultra`" in card
    assert "swarm (Shared message board)" in card
    assert "| Station Role | Model | Description |" in card

    # All 8 canonical stations must appear
    for role in [
        "spec_writer",
        "researcher",
        "spec_critic",
        "seam_architect",
        "coder",
        "surgeon",
        "examiner",
        "qa_engineer",
    ]:
        assert f"| `{role}` |" in card

    assert "`claude-opus-5-5-high`" in card
    assert "`gemini-4-hydrogen-xhigh`" in card

    # Pro card test
    pro_state = TierState(
        tier="pro",
        branch="main",
        transport="invoke_subagent",
        station_models=dict(PRO_STATION_MODELS),
        updated_at="2026-11-12T23:59:59+00:00",
    )
    pro_card = format_tier_card(pro_state)
    assert "### ⚡ Edge Execution Tier: PRO" in pro_card
    assert "invoke_subagent (Isolated subagents)" in pro_card
    assert "`gemini-3.8-flash-high`" in pro_card


# =========================================================================
# 7. CLI Subcommand Integrations
# =========================================================================


def test_standalone_tier_cli(tmp_path):
    """Validates standalone CLI: python3 tools/brigade/tier.py status|switch."""
    tier_script = REPO_ROOT / "tools" / "brigade" / "tier.py"
    assert tier_script.is_file(), "tools/brigade/tier.py must exist"

    repo = create_mock_git_repo(tmp_path / "repo_tier_cli", branch="main")
    env = {**os.environ, "EDGE_TIER_STATE_PATH": str(tmp_path / "cli_tier.json")}

    # 1. status
    proc = subprocess.run(
        [sys.executable, str(tier_script), "status", str(repo)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "Edge Execution Tier" in proc.stdout

    # 2. switch ultra
    proc = subprocess.run(
        [sys.executable, str(tier_script), "switch", "ultra", str(repo)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "Edge Execution Tier: ULTRA" in proc.stdout

    # 3. switch invalid
    proc = subprocess.run(
        [sys.executable, str(tier_script), "switch", "turbo", str(repo)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode != 0
    assert "Invalid tier" in proc.stdout or "Invalid tier" in proc.stderr


def test_brigade_cli_tier_subcommand(tmp_path):
    """Validates brigade CLI integration: brigade tier <repo> --action status|switch."""
    cli_script = REPO_ROOT / "tools" / "brigade" / "cli.py"
    assert cli_script.is_file(), "tools/brigade/cli.py must exist"

    repo = create_mock_git_repo(tmp_path / "repo_brigade_cli", branch="main")
    env = {**os.environ, "EDGE_TIER_STATE_PATH": str(tmp_path / "brigade_cli_tier.json")}

    # 1. status
    proc = subprocess.run(
        [sys.executable, str(cli_script), "tier", str(repo), "--action", "status"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    assert "Edge Execution Tier" in proc.stdout

    # 2. switch ultra with --json
    proc = subprocess.run(
        [sys.executable, str(cli_script), "tier", str(repo), "--action", "switch", "--target", "ultra", "--json"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data["success"] is True
    assert data["state"]["tier"] == "ultra"
    assert data["state"]["transport"] == "swarm"

    # 3. switch missing --target
    proc = subprocess.run(
        [sys.executable, str(cli_script), "tier", str(repo), "--action", "switch"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode != 0


# =========================================================================
# 8. Skill Manifest Verification
# =========================================================================


def test_skills_edge_pro_and_ultra_definitions():
    """Validates presence and frontmatter contracts for /edge-pro and /edge-ultra skills."""
    skills_dir = REPO_ROOT / "skills"

    pro_skill = skills_dir / "edge-pro" / "SKILL.md"
    ultra_skill = skills_dir / "edge-ultra" / "SKILL.md"

    assert pro_skill.is_file(), f"Expected skill manifest at {pro_skill}"
    assert ultra_skill.is_file(), f"Expected skill manifest at {ultra_skill}"

    pro_content = pro_skill.read_text(encoding="utf-8")
    assert "name: edge-pro" in pro_content
    assert "description:" in pro_content
    assert "switch pro" in pro_content

    ultra_content = ultra_skill.read_text(encoding="utf-8")
    assert "name: edge-ultra" in ultra_content
    assert "description:" in ultra_content
    assert "switch ultra" in ultra_content
