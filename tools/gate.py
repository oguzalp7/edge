#!/usr/bin/env python3
"""Edge Verification Gate: Deterministic Architectural Quality Assurance Facade."""

import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.audit import crapper as _crapper
from tools.common import normalize_target_path, run_command, setup_utf8_console
from tools.gate_cc import compute_source_max_cc
from tools.gate_mixin import GateCheckMethodsMixin
from tools.gate_git import get_head_commit_sha
from tools.gate_metrics import compute_changed_metrics
from tools.gate_sdl import check_differential_mutation_gate
from tools.gate_static import GateResult

setup_utf8_console()

TREE_SITTER_AVAILABLE: bool = bool(getattr(_crapper, "TREE_SITTER_AVAILABLE", False))

__all__ = ["GateResult", "EdgeVerificationGate", "check_differential_mutation_gate", "TREE_SITTER_AVAILABLE", "main"]


class EdgeVerificationGate(GateCheckMethodsMixin):
    """Orchestrates deterministic static, complexity, and profile-gated checks."""

    GHOST_ROOT_DIRS: Tuple[str, ...] = ("rc", "pecs", "ests", "pp", "ib", "omponents")

    def __init__(self, target_repo_path: Path):
        self.target_repo = target_repo_path

    def _run_cmd(self, cmd: List[str], cwd: Optional[Path] = None, timeout: int = 300) -> Tuple[int, str, str]:
        return run_command(cmd, cwd=cwd or self.target_repo, timeout=timeout)

    def _run_profile_gated(self, profiles: Any, gate_key: str, stage_name: str, fn: Any) -> GateResult:
        from tools.common.profiles import is_stack_gate_enabled
        return fn() if is_stack_gate_enabled(profiles, gate_key) else GateResult(1, stage_name, True, "Skipped (inactive profile)")

    def _evaluate_stages(self, base_ref: str = "HEAD~1", is_refactor: bool = True, skip_verification: bool = False, track: str = "all") -> Tuple[bool, List[GateResult], bool]:
        from tools.common.profiles import resolve_active_profiles

        profiles = resolve_active_profiles(self.target_repo)
        ghost = self.check_ghost_root_directories()
        ghost.stage_num = 0
        if not ghost.passed:
            return False, [ghost], True
        results: List[GateResult] = [ghost, self.check_navigation_gate()]
        if is_refactor and track != "feature":
            results.append(self._run_profile_gated(profiles, "migration_gate", "MigrationGate Invariant Gate", lambda: self.check_migration_gate(base_ref=base_ref)))
        results.extend([
            self.check_complexity_non_regression(base_ref=base_ref),
            self.check_mock_fallbacks(base_ref=base_ref),
            self._run_profile_gated(profiles, "type_escapes", "Type Escape Gate", lambda: self.check_type_escapes(base_ref=base_ref)),
            self._run_profile_gated(profiles, "dual_theme_and_a11y", "Dual-Theme & A11y Heuristic Gate", lambda: self.check_dual_theme_and_a11y(base_ref=base_ref)),
        ])
        if track in ("core", "all"):
            results.append(self._run_profile_gated(profiles, "layer_leakage", "Layer Leakage Gate", lambda: self.check_layer_leakage(base_ref=base_ref)))
            results.append(self.check_differential_mutation_gate(base_ref=base_ref, skip_verify=skip_verification))
        if track in ("ui", "all"):
            results.append(self._run_profile_gated(profiles, "zero_wrappers", "Zero-Wrapper Gate", lambda: self.check_zero_wrappers(base_ref=base_ref)))
            results.append(self._run_profile_gated(profiles, "domain_purity", "Domain Purity Gate", lambda: self.check_domain_purity(base_ref=base_ref)))
        if not skip_verification:
            results.append(self._run_profile_gated(profiles, "verification", "Hermetic Verification Gate", self.check_verification))
        for idx, r in enumerate(results):
            r.stage_num = idx
        return all(r.passed for r in results), results, False

    def run_all_structured(self, base_ref: str = "HEAD~1", is_refactor: bool = True, skip_verification: bool = False, target_file: Optional[str] = None, scaffolding_allowance: int = 0, track: str = "all") -> Dict[str, Any]:
        with redirect_stdout(io.StringIO()):
            all_passed, results, ghost_failed = self._evaluate_stages(base_ref=base_ref, is_refactor=is_refactor, skip_verification=skip_verification, track=track)
            commit_sha = get_head_commit_sha(self._run_cmd)
            metrics = (
                {"db_leaks": None, "max_cc": None, "dryer_clones": None, "type_score": None, "sloc": None}
                if ghost_failed else compute_changed_metrics(self.target_repo, self._run_cmd, base_ref=base_ref)
            )
        return {"track": track, "base_ref": base_ref, "commit_sha": commit_sha, "all_passed": all_passed, "stages": [r.to_dict() for r in results], "metrics": metrics}

    def run_all(self, base_ref: str = "HEAD~1", is_refactor: bool = True, skip_verification: bool = False, target_file: Optional[str] = None, scaffolding_allowance: int = 0, track: str = "all") -> bool:
        print("=" * 70 + f"\n🛡️  EDGE VERIFICATION GATE — ARCHITECTURAL AUDIT [{track.upper()} TRACK]\n" + "=" * 70)
        all_passed, results, ghost_failed = self._evaluate_stages(base_ref=base_ref, is_refactor=is_refactor, skip_verification=skip_verification, track=track)
        if ghost_failed:
            print(f"{results[0]}\n" + ("-" * 70) + "\n\n" + ("=" * 70) + "\n🚫 GATE CHECK FAILED: Ghost root directories present. Halting audit immediately.\n" + "=" * 70)
            return False
        if skip_verification:
            print("  (Skipping Hermetic verification per --skip-verify)")
        for r in results:
            print(f"{r}\n" + ("-" * 70))
        msg = "🎉 ALL GATES PASSED! Codebase is deep, clean, and un-bloated." if all_passed else "🚫 GATE CHECK FAILED. Address the violations above before merging."
        print("\n" + ("=" * 70) + f"\n{msg}\n" + "=" * 70)
        return all_passed


def __getattr__(name: str) -> Any:
    import tools.gate_cc as _gc
    import tools.gate_metrics as _gm
    import tools.gate_static as _gs

    legacy_map = {
        "_compute_source_max_cc": compute_source_max_cc,
        "_count_source_sloc": _gc.count_source_sloc,
        "_compute_dryer_clones": _gm.compute_dryer_clones,
        "_find_type_escape_violations": _gs.find_type_escape_violations,
        "_PRODUCTION_CODE_SUFFIXES": _gs.PRODUCTION_CODE_SUFFIXES,
        "_count_sql_leaks": _gs.count_sql_leaks,
        "_is_action_controller_path": _gs.is_action_controller_path,
        "_is_eligible_prod_path": _gs.is_eligible_prod_path,
        "_is_excluded_non_prod_path": _gs.is_excluded_non_prod_path,
        "_find_mock_fallback_violations": _gs.find_mock_fallback_violations,
    }
    if name in legacy_map:
        return legacy_map[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge Architectural Quality & Complexity Gate")
    parser.add_argument("target", nargs="?", default=".")
    parser.add_argument("--base", default="HEAD~1")
    parser.add_argument("--no-refactor", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--target-file", default=None)
    parser.add_argument("--allow-scaffolding", type=int, default=0)
    parser.add_argument("--track", choices=["core", "ui", "all", "feature"], default="all")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()
    gate = EdgeVerificationGate(normalize_target_path(args.target))
    if args.format == "json":
        payload = gate.run_all_structured(base_ref=args.base, is_refactor=not args.no_refactor, skip_verification=args.skip_verify, track=args.track)
        print(json.dumps(payload, indent=2))
        sys.exit(0 if payload.get("all_passed") else 1)
    sys.exit(0 if gate.run_all(base_ref=args.base, is_refactor=not args.no_refactor, skip_verification=args.skip_verify, track=args.track) else 1)


if __name__ == "__main__":
    main()
