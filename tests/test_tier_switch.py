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
    """Validates branchless default (checkout=False) and opt-in legacy checkout (checkout=True) for Ultra."""
    assert tier is not None, "tools.brigade.tier module must be implemented"
    import inspect

    sig = inspect.signature(switch_tier)
    assert "checkout" in sig.parameters, "switch_tier must accept checkout: bool = False"
    assert sig.parameters["checkout"].default is False

    # 1. Default branchless mode (checkout=False): preserves active branch 'main'
    repo = create_mock_git_repo(tmp_path / "repo_switch", branch="main")
    state_file = tmp_path / "edge_tier.json"

    ok, card, state = switch_tier(repo, "ultra", state_path=state_file)

    assert ok is True
    assert "Edge Execution Tier: ULTRA" in card
    assert state.tier == "ultra"
    assert state.branch == "main"
    assert state.transport == "swarm"
    assert state.station_models == ULTRA_STATION_MODELS
    assert get_current_branch(repo) == "main"

    assert state_file.is_file()
    disk_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert disk_data["tier"] == "ultra"
    assert disk_data["transport"] == "swarm"

    # 2. Opt-in legacy checkout=True: creates and checks out 'ultra' branch
    repo_legacy = create_mock_git_repo(tmp_path / "repo_switch_legacy", branch="main")
    state_file_legacy = tmp_path / "edge_tier_legacy.json"
    ok_leg, _, state_leg = switch_tier(repo_legacy, "ultra", state_path=state_file_legacy, checkout=True)
    assert ok_leg is True
    assert state_leg.tier == "ultra"
    assert state_leg.branch == "ultra"
    assert get_current_branch(repo_legacy) == "ultra"


def test_switch_tier_to_pro_switches_to_main_and_updates_state(tmp_path):
    """Validates branchless Pro switch and opt-in checkout=True back to main."""
    assert tier is not None, "tools.brigade.tier module must be implemented"
    import inspect

    sig = inspect.signature(switch_tier)
    assert "checkout" in sig.parameters, "switch_tier must accept checkout: bool = False"

    # 1. Default branchless mode preserves current feature branch
    repo = create_mock_git_repo(tmp_path / "repo_switch_back", branch="feat/my-work")
    state_file = tmp_path / "edge_tier.json"

    ok1, _, _ = switch_tier(repo, "ultra", state_path=state_file)
    assert ok1 is True
    assert get_current_branch(repo) == "feat/my-work"

    ok2, card, state = switch_tier(repo, "pro", state_path=state_file)
    assert ok2 is True
    assert "Edge Execution Tier: PRO" in card
    assert state.tier == "pro"
    assert state.branch == "feat/my-work"
    assert state.transport == "invoke_subagent"
    assert state.station_models == PRO_STATION_MODELS
    assert get_current_branch(repo) == "feat/my-work"

    disk_data = json.loads(state_file.read_text(encoding="utf-8"))
    assert disk_data["tier"] == "pro"
    assert disk_data["transport"] == "invoke_subagent"

    # 2. Opt-in checkout=True switches ultra -> main
    repo_leg = create_mock_git_repo(tmp_path / "repo_switch_back_legacy", branch="main")
    state_leg = tmp_path / "edge_tier_back_legacy.json"
    ok_u, _, _ = switch_tier(repo_leg, "ultra", state_path=state_leg, checkout=True)
    assert ok_u is True
    assert get_current_branch(repo_leg) == "ultra"

    ok_p, _, state_p = switch_tier(repo_leg, "pro", state_path=state_leg, checkout=True)
    assert ok_p is True
    assert state_p.tier == "pro"
    assert state_p.branch == "main"
    assert get_current_branch(repo_leg) == "main"


def test_switch_tier_blocked_by_dirty_tracked_files(tmp_path):
    """
    Branchless mode (checkout=False) succeeds even with dirty tracked files and NEVER calls git checkout;
    explicit checkout=True still enforces Clean Working Tree Invariant.
    """
    assert tier is not None, "tools.brigade.tier module must be implemented"
    import inspect
    from unittest.mock import patch

    sig = inspect.signature(switch_tier)
    assert "checkout" in sig.parameters, "switch_tier must accept checkout: bool = False"

    repo = create_mock_git_repo(tmp_path / "repo_dirty", branch="main")
    state_file = tmp_path / "edge_tier.json"

    readme = repo / "README.md"
    readme.write_text("# Mock Repository - Modified!\n", encoding="utf-8")

    # 1. Default branchless mode: succeeds on dirty working tree without calling git checkout
    with patch.object(tier, "_checkout_git_branch", side_effect=AssertionError("git checkout must not be called")) as _:
        ok_bl, _, state_bl = switch_tier(repo, "ultra", state_path=state_file)
    assert ok_bl is True
    assert state_bl.tier == "ultra"
    assert get_current_branch(repo) == "main"

    # 2. Explicit checkout=True: blocked by dirty tracked file
    state_file_leg = tmp_path / "edge_tier_dirty_leg.json"
    ok, err_msg, _ = switch_tier(repo, "ultra", state_path=state_file_leg, checkout=True)
    assert ok is False
    assert "README.md" in err_msg or "uncommitted tracked changes" in err_msg.lower()
    assert get_current_branch(repo) == "main"
    assert not state_file_leg.is_file()


def test_switch_tier_allows_dirty_edge_and_untracked_files(tmp_path):
    """
    Dirty Tolerance Invariant:
    Modifications inside .edge/ and untracked files (??) succeed in both branchless and checkout=True modes.
    """
    assert tier is not None, "tools.brigade.tier module must be implemented"
    import inspect

    sig = inspect.signature(switch_tier)
    assert "checkout" in sig.parameters, "switch_tier must accept checkout: bool = False"

    repo = create_mock_git_repo(tmp_path / "repo_edge_dirty", branch="main")
    state_file = tmp_path / "edge_tier.json"

    edge_dir = repo / ".edge"
    edge_dir.mkdir(parents=True, exist_ok=True)
    brigade_json = edge_dir / "brigade.json"
    brigade_json.write_text('{"state": "DIRTY_TEST"}\n', encoding="utf-8")
    subprocess.run(["git", "add", ".edge/brigade.json"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Add .edge state"], cwd=str(repo), check=True, capture_output=True)

    brigade_json.write_text('{"state": "MUTATED_UNCOMMITTED"}\n', encoding="utf-8")
    scratch = repo / "scratch_notes.txt"
    scratch.write_text("temporary scratch notes\n", encoding="utf-8")

    ok_bl, _, state_bl = switch_tier(repo, "ultra", state_path=state_file)
    assert ok_bl is True
    assert state_bl.tier == "ultra"
    assert get_current_branch(repo) == "main"

    ok, _, state = switch_tier(repo, "ultra", state_path=state_file, checkout=True)
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
    assert "station_models.json" in ultra_content
    assert "--checkout" in ultra_content
    assert "set-model" in ultra_content

    assert "station_models.json" in pro_content
    assert "--checkout" in pro_content


# =========================================================================
# 9. SPEC-EDGE-BRIGADE-011 (AC-1): SSOT station_models.json & set_station_model
# =========================================================================


def test_station_models_ssot_load_and_apply_effort(tmp_path):
    """Validates station_models.json SSOT schema, load_ssot_station_config, and apply_effort_to_model."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    ssot_file = REPO_ROOT / "tools" / "brigade" / "station_models.json"
    assert ssot_file.is_file(), "tools/brigade/station_models.json SSOT must exist"

    ssot_data = json.loads(ssot_file.read_text(encoding="utf-8"))
    assert ssot_data.get("default_tier") == "pro"
    assert ssot_data["tiers"]["ultra"]["branch"] == "main"
    assert ssot_data["tiers"]["ultra"]["transport"] == "swarm"
    assert ssot_data["tiers"]["ultra"]["stations"]["examiner"]["fork"] == "spec_writer"
    assert ssot_data["tiers"]["pro"]["branch"] == "main"
    assert ssot_data["tiers"]["pro"]["transport"] == "invoke_subagent"

    load_fn = getattr(tier, "load_ssot_station_config", None)
    apply_fn = getattr(tier, "apply_effort_to_model", None)
    assert load_fn is not None, "tools.brigade.tier must define load_ssot_station_config"
    assert apply_fn is not None, "tools.brigade.tier must define apply_effort_to_model"

    ultra_cfg = load_fn("ultra", ssot_path=ssot_file)
    assert ultra_cfg["seam_architect"]["model"] == "gemini-4-hydrogen-xhigh"
    assert ultra_cfg["examiner"]["fork"] == "spec_writer"

    pro_cfg = load_fn("pro", ssot_path=ssot_file)
    assert pro_cfg["coder"]["model"] == "flash"
    assert pro_cfg["spec_critic"]["model"] == "gemini-3.8-flash-high"

    assert apply_fn("gemini-4-hydrogen", "xhigh") == "gemini-4-hydrogen-xhigh"
    assert apply_fn("gemini-4-hydrogen-high", "xhigh") == "gemini-4-hydrogen-xhigh"
    assert apply_fn("flash", "high") == "flash"
    assert apply_fn("gemini-4-hydrogen-high", None) == "gemini-4-hydrogen-high"


def test_set_station_model_updates_ssot_and_syncs_matching_tier_only(tmp_path):
    """Validates set_station_model updates station_models.json and syncs edge_tier.json only when tier matches."""
    assert tier is not None, "tools.brigade.tier module must be implemented"

    set_fn = getattr(tier, "set_station_model", None)
    assert set_fn is not None, "tools.brigade.tier must define set_station_model"

    ssot_src = REPO_ROOT / "tools" / "brigade" / "station_models.json"
    assert ssot_src.is_file(), "tools/brigade/station_models.json SSOT must exist"

    ssot_copy = tmp_path / "station_models.json"
    ssot_copy.write_text(ssot_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Active tier is 'pro' -> configuring 'ultra' must NOT overwrite active pro state
    state_file = tmp_path / "edge_tier.json"
    state_file.write_text(
        json.dumps(TierState("pro", "main", "invoke_subagent", dict(PRO_STATION_MODELS), "2026-11-20T00:00:00Z").to_dict()),
        encoding="utf-8",
    )

    ok_u, _ = set_fn("coder", "gemini-4-hydrogen", effort="xhigh", tier="ultra", ssot_path=ssot_copy, state_path=state_file)
    assert ok_u is True
    updated_ssot = json.loads(ssot_copy.read_text(encoding="utf-8"))
    assert updated_ssot["tiers"]["ultra"]["stations"]["coder"]["model"] == "gemini-4-hydrogen-xhigh"
    assert json.loads(state_file.read_text(encoding="utf-8"))["station_models"]["coder"] == "flash"

    # Active tier is 'ultra' -> configuring 'ultra' syncs edge_tier.json atomically
    state_file.write_text(
        json.dumps(TierState("ultra", "main", "swarm", dict(ULTRA_STATION_MODELS), "2026-11-20T00:00:00Z").to_dict()),
        encoding="utf-8",
    )
    ok_sync, _ = set_fn("coder", "gemini-4-hydrogen", effort="medium", tier="ultra", ssot_path=ssot_copy, state_path=state_file)
    assert ok_sync is True
    assert json.loads(state_file.read_text(encoding="utf-8"))["station_models"]["coder"] == "gemini-4-hydrogen-medium"
