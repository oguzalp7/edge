"""Delegation mixin for EdgeVerificationGate check methods."""

from typing import List, Optional, Tuple

from tools.gate_cc import count_source_sloc
from tools.gate_metrics import compute_dryer_clones
from tools.gate_checks import check_complexity_non_regression, check_layer_leakage, check_migration_gate, check_mock_fallbacks
from tools.gate_git import (
    check_ghost_root_directories as _ghost_dir_check,
    check_navigation_gate as _nav_gate_check,
    get_changed_rel_paths,
    has_navigation_check_script,
)
from tools.gate_sdl import check_differential_mutation_gate
from tools.gate_static import GateResult
from tools.gate_ts_checks import check_type_escapes, check_verification
from tools.gate_ui_checks import (
    check_domain_purity as _domain_purity,
    check_dual_theme_and_a11y as _dual_theme,
    check_zero_wrappers as _zero_wrappers,
)


class GateCheckMethodsMixin:
    """Delegation mixin keeping EdgeVerificationGate facade exports compact."""

    def _get_changed_rel_paths(self, base_ref: str = "HEAD~1") -> Tuple[Optional[List[str]], str, str]:
        return get_changed_rel_paths(self.target_repo, self._run_cmd, base_ref)

    def _has_navigation_check_script(self) -> bool:
        return has_navigation_check_script(self.target_repo)

    @staticmethod
    def _count_source_sloc(content: str, suffix: str) -> int:
        return count_source_sloc(content, suffix)

    def _compute_dryer_clones(self, abs_changed_files: List[str]) -> Optional[int]:
        return compute_dryer_clones(self.target_repo, abs_changed_files)

    def check_ghost_root_directories(self) -> GateResult:
        return _ghost_dir_check(self.target_repo, self.GHOST_ROOT_DIRS)

    def check_navigation_gate(self) -> GateResult:
        return _nav_gate_check(self.target_repo, self._run_cmd)

    def check_migration_gate(self, base_ref: str = "HEAD~1") -> GateResult:
        return check_migration_gate(self._run_cmd, base_ref=base_ref)

    def check_complexity_non_regression(self, base_ref: str = "HEAD~1", healthy_cc_ceiling: int = 10) -> GateResult:
        return check_complexity_non_regression(self.target_repo, self._run_cmd, base_ref=base_ref, healthy_cc_ceiling=healthy_cc_ceiling)

    def check_layer_leakage(self, base_ref: str = "HEAD~1") -> GateResult:
        return check_layer_leakage(self.target_repo, self._run_cmd, base_ref=base_ref)

    def check_zero_wrappers(self, base_ref: Optional[str] = None) -> GateResult:
        return _zero_wrappers(self.target_repo, self._run_cmd, base_ref=base_ref)

    def check_domain_purity(self, base_ref: Optional[str] = None) -> GateResult:
        return _domain_purity(self.target_repo, self._run_cmd, base_ref=base_ref)

    def check_mock_fallbacks(self, base_ref: Optional[str] = "HEAD~1") -> GateResult:
        return check_mock_fallbacks(self.target_repo, self._run_cmd, base_ref=base_ref)

    def check_type_escapes(self, base_ref: Optional[str] = "HEAD~1") -> GateResult:
        return check_type_escapes(self.target_repo, self._run_cmd, base_ref=base_ref)

    def check_dual_theme_and_a11y(self, base_ref: Optional[str] = "HEAD~1") -> GateResult:
        return _dual_theme(self.target_repo, self._run_cmd, base_ref=base_ref)

    def check_verification(self) -> GateResult:
        return check_verification(self._run_cmd)

    def check_differential_mutation_gate(self, base_ref: Optional[str] = "HEAD~1", skip_verify: bool = False, test_cmd: Optional[List[str]] = None) -> GateResult:
        rel_paths, _, _ = self._get_changed_rel_paths(base_ref or "HEAD~1")
        return check_differential_mutation_gate(self.target_repo, rel_paths or [], skip_verify=skip_verify, base_ref=base_ref, test_cmd=test_cmd)
