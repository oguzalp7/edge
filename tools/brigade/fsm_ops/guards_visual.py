"""BrigadeFSM mixin: guards_visual."""

from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
import json
import importlib.util
import shutil

from tools.brigade.models import BrigadeState, Checkpoint, ContextHeatZone, CycleState, ReviewFinding, StationRole, Ticket, TransitionLog
from tools.brigade.proof_verifier import ProofVerifier
from tools.brigade.stations import StationRegistry
from tools.common.paths import is_wsl_path, to_wsl_path
from tools.common import normalize_target_path, run_command


class FsmGuardsVisualMixin:
    """Mixin providing guards_visual operations for BrigadeFSM."""

    @staticmethod
    def _resolve_visual_from_receipt(receipt_path: Path, roots: List[Path]) -> Optional[Tuple[Path, Path, Optional[Path]]]:
        if not receipt_path.is_file():
            return None
        try:
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        b_raw = str(data.get("baseline_path") or "").strip()
        r_raw = str(data.get("refactored_path") or "").strip()
        if not b_raw or not r_raw:
            return None
        b_file = ProofVerifier.resolve_screenshot_file(b_raw, roots)
        r_file = ProofVerifier.resolve_screenshot_file(r_raw, roots)
        if not (b_file and r_file):
            return None
        d_raw = str(data.get("diff_out_path") or "").strip()
        d_path = normalize_target_path(d_raw) if d_raw else None
        return b_file, r_file, d_path

    def _find_visual_parity_pair(self, slug: str, work_dir: Path) -> Optional[Tuple[Path, Path, Path]]:
        roots = list(dict.fromkeys([work_dir, self.target_repo]))
        default_diff = work_dir / ".edge" / "qa" / "visual" / f"{slug}-diff.png"
        for root in roots:
            vis_dir = root / ".edge" / "qa" / "visual"
            b_path, r_path = vis_dir / f"{slug}-baseline.png", vis_dir / f"{slug}-refactored.png"
            if not (b_path.is_file() and r_path.is_file()):
                continue
            return b_path, r_path, default_diff
        cands = [
            cand
            for root in roots
            for cand in (root / ".edge" / "qa" / "visual" / f"{slug}-diff.json", root / ".edge" / "qa" / "proofs" / f"{slug}-visual.json")
        ]
        for cand in cands:
            if (resolved := self._resolve_visual_from_receipt(cand, roots)):
                return resolved[0], resolved[1], resolved[2] or default_diff
        return None

    def _run_diff_image_subprocess(self, baseline: Path, refactored: Path, diff_out: Path) -> Tuple[bool, str, Dict[str, Any]]:
        plugin_root = Path(__file__).resolve().parents[3]
        uv_bin = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
        b_arg = to_wsl_path(baseline) if is_wsl_path(baseline) else str(baseline)
        r_arg = to_wsl_path(refactored) if is_wsl_path(refactored) else str(refactored)
        d_arg = to_wsl_path(diff_out) if is_wsl_path(diff_out) else str(diff_out)
        cmd = [
            uv_bin, "run", "--with", "pillow", "python3",
            "-m", "tools.ui_audit.diff_image",
            b_arg, r_arg, "--tolerance", "15", "--max-mismatch", "0.15", "--diff-out", d_arg,
        ]
        code, out, err = self._run_cmd(cmd, cwd=plugin_root)
        if code != 0:
            detail_msg = (out or err or "Pixel mismatch exceeded 0.15% threshold.").strip()
            return False, f"UI visual parity FAILED (mismatch > 0.15%): {detail_msg}", {
                "error": "VISUAL_PARITY_FAILED",
                "baseline": str(baseline),
                "refactored": str(refactored),
                "diff_out": str(diff_out),
                "output": out,
            }
        return True, "UI visual parity passed (<= 0.15%).", {
            "baseline": str(baseline),
            "refactored": str(refactored),
            "diff_out": str(diff_out),
            "output": out,
        }

    def _check_ui_visual_parity(self, ticket: Ticket, work_dir: Path) -> Tuple[bool, str, Dict[str, Any]]:
        slug = StationRegistry._resolve_qa_slug("qa_scenario", ticket)
        pair = self._find_visual_parity_pair(slug, work_dir)
        if not pair:
            return (
                False,
                f"UI visual parity blocked: missing baseline/refactored screenshots for '{slug}'. "
                f"Expected '.edge/qa/visual/{slug}-baseline.png' and '.edge/qa/visual/{slug}-refactored.png'.",
                {"error": "MISSING_VISUAL_PARITY_IMAGES", "slug": slug},
            )
        baseline, refactored, diff_out = pair
        if importlib.util.find_spec("PIL") is None:
            return self._run_diff_image_subprocess(baseline, refactored, diff_out)
        from tools.ui_audit.diff_image import compare_images
        passed = compare_images(baseline, refactored, tolerance=15, max_mismatch_pct=0.15, diff_out_path=diff_out)
        payload = {"baseline": str(baseline), "refactored": str(refactored), "diff_out": str(diff_out)}
        if not passed:
            return False, f"UI visual parity FAILED (mismatch > 0.15%) for '{slug}'.", {"error": "VISUAL_PARITY_FAILED", **payload}
        return True, f"UI visual parity passed (<= 0.15%) for '{slug}'.", payload
