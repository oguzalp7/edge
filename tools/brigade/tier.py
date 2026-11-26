#!/usr/bin/env python3
"""Edge Brigade Tier Switcher & Model Matrix Controller Facade (stdlib-only)."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import List, Optional, Tuple, Union

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from tools.brigade.tier_git import checkout_git_branch as _checkout_git_branch, get_current_git_branch, resolve_switch_branch
from tools.brigade.tier_models import (
    EFFORT_CAPABLE_FAMILIES,
    PRO_BRANCH,
    PRO_STATION_MODELS,
    PRO_TRANSPORT,
    STATION_DESCRIPTIONS,
    ULTRA_BRANCH,
    ULTRA_STATION_MODELS,
    ULTRA_TRANSPORT,
    VALID_EFFORT_LEVELS,
    VALID_TIERS,
    TierMode,
    TierState,
    atomic_write_json,
    create_tier_state,
    default_transport,
    get_tier_state_path,
)
from tools.brigade.tier_ssot import (
    apply_effort_to_model,
    get_station_models_ssot_path,
    load_ssot_station_config,
    resolve_ssot_tier_models,
    set_station_model,
)


def get_tier_status(repo_path: Union[Path, str], state_path: Optional[Path] = None) -> TierState:
    """Inspect persisted tier state file or fallback to current git branch."""
    path = state_path or get_tier_state_path()
    if path.is_file():
        try:
            return TierState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            pass
    branch = get_current_git_branch(Path(repo_path))
    return create_tier_state("ultra" if branch == ULTRA_BRANCH else "pro", branch)


def switch_tier(
    repo_path: Union[Path, str], target_tier: str, state_path: Optional[Path] = None, checkout: bool = False,
) -> Tuple[bool, str, TierState]:
    """Switch Edge Brigade execution tier (preserving current branch unless checkout=True)."""
    repo = Path(repo_path)
    state_file = state_path or get_tier_state_path()
    current_state = get_tier_status(repo, state_file)
    tier_clean = target_tier.strip().lower()
    if tier_clean not in VALID_TIERS:
        return False, f"❌ Invalid tier '{target_tier}'. Supported tiers: {', '.join(VALID_TIERS)}", current_state
    ok, target_branch, checkout_err = resolve_switch_branch(repo, tier_clean, checkout)
    if not ok:
        return False, f"❌ {checkout_err}", current_state
    new_state = TierState(
        tier=tier_clean, branch=target_branch, transport=default_transport(tier_clean),
        station_models=resolve_ssot_tier_models(tier_clean), updated_at=datetime.now(timezone.utc).isoformat(),
    )
    atomic_write_json(state_file, new_state.to_dict())
    return True, format_tier_card(new_state), new_state


def format_tier_card(state: TierState) -> str:
    """Render user-facing Markdown card summarizing active tier and station model matrix."""
    icon = "🚀" if state.tier == "ultra" else "⚡"
    transport_label = "swarm (Shared message board)" if state.transport == "swarm" else "invoke_subagent (Isolated subagents)"
    lines = [
        f"### {icon} Edge Execution Tier: {state.tier.upper()}", "",
        f"- **Tier:** `{state.tier}`", f"- **Active Branch:** `{state.branch}`",
        f"- **Agent Transport:** `{transport_label}`", f"- **Updated:** `{state.updated_at}`", "",
        "#### 📋 Station Model Matrix", "", "| Station Role | Model | Description |", "| :--- | :--- | :--- |",
    ]
    for role, model in sorted(state.station_models.items()):
        lines.append(f"| `{role}` | `{model}` | {STATION_DESCRIPTIONS.get(role, 'Brigade Station Worker')} |")
    return "\n".join(lines)


def _cli_set_model(argv: List[str]) -> int:
    if len(argv) < 4:
        print("Usage: tier.py set-model <role> <model> [--effort <low|medium|high|xhigh>] [--tier <pro|ultra>]")
        return 1
    effort, tier = None, "ultra"
    for idx, arg in enumerate(argv[4:]):
        if arg == "--effort" and idx + 1 < len(argv[4:]):
            effort = argv[4:][idx + 1]
        elif arg == "--tier" and idx + 1 < len(argv[4:]):
            tier = argv[4:][idx + 1]
    ok, msg = set_station_model(argv[2], argv[3], effort=effort, tier=tier)
    print(msg)
    return 0 if ok else 1


def _cli_switch(argv: List[str]) -> int:
    if len(argv) < 3:
        print("Error: switch requires target tier ('pro' or 'ultra')")
        return 1
    checkout = "--checkout" in argv[3:]
    positional = [a for a in argv[3:] if a != "--checkout"]
    success, msg, _ = switch_tier(positional[0] if positional else ".", argv[2], checkout=checkout)
    print(msg)
    return 0 if success else 1


def main() -> int:
    """CLI entrypoint for status, switch, and set-model actions."""
    if len(sys.argv) < 2:
        print("Usage: tier.py status [repo] | tier.py switch <pro|ultra> [repo] [--checkout] | tier.py set-model <role> <model>")
        return 1
    action = sys.argv[1].lower()
    if action == "status":
        print(format_tier_card(get_tier_status(sys.argv[2] if len(sys.argv) > 2 else ".")))
        return 0
    if action == "switch":
        return _cli_switch(sys.argv)
    if action == "set-model":
        return _cli_set_model(sys.argv)
    print(f"Unknown action '{action}'. Use 'status', 'switch', or 'set-model'.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
