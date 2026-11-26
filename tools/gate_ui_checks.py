"""UI checks and visual/a11y heuristics for Edge Verification Gate."""

from pathlib import Path
import re
from typing import Any, List, Optional

from tools.gate_git import get_modified_files, read_changed_prod_files
from tools.gate_static import GateResult, find_dual_theme_and_a11y_violations
from tools.rules import CANONICAL_ARRAY_PATTERN, RAW_TH_PATTERN, SHALLOW_WRAPPER_PATTERN


def check_zero_wrappers(target_repo: Path, run_cmd: Any, base_ref: Optional[str] = None) -> GateResult:
    """Detect shallow pass-through components wrapping another component."""
    components_dir = target_repo / "src" / "components"
    if not components_dir.exists():
        return GateResult(1, "Zero-Wrapper Gate", True, "No components directory found.")
    modified = get_modified_files(target_repo, run_cmd, base_ref)
    comp_prefix = str(components_dir).replace("\\", "/")
    candidates = (
        [f for f in modified if f.suffix in (".tsx", ".jsx") and str(f).replace("\\", "/").startswith(comp_prefix)]
        if modified is not None else list(components_dir.rglob("*.tsx"))
    )
    shallow_wrappers: List[str] = []
    for tsx_file in candidates:
        if ".test." in tsx_file.name or ".spec." in tsx_file.name:
            continue
        content = tsx_file.read_text(encoding="utf-8", errors="replace")
        lines = [ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("//")]
        matches = SHALLOW_WRAPPER_PATTERN.findall(content)
        if matches and len(lines) < 55:
            target_comp = matches[0][0]
            comp_m = re.search(r"export\s+function\s+([A-Za-z0-9]+)", content)
            comp_name = comp_m.group(1) if comp_m else tsx_file.stem
            if comp_name != target_comp:
                rel = tsx_file.relative_to(target_repo)
                shallow_wrappers.append(f"{rel}: '{comp_name}' is a shallow pass-through wrapping '{target_comp}'. Delete wrapper and migrate callers directly.")
    if shallow_wrappers:
        return GateResult(1, "Zero-Wrapper Gate", False, f"Found {len(shallow_wrappers)} shallow pass-through wrapper(s).", shallow_wrappers)
    return GateResult(1, "Zero-Wrapper Gate", True, "Zero shallow pass-through wrappers found.")


def _collect_domain_purity_files(target_repo: Path, run_cmd: Any, base_ref: Optional[str]) -> List[Path]:
    modified = get_modified_files(target_repo, run_cmd, base_ref)
    prefixes = [str(target_repo / d).replace("\\", "/") for d in ("src/components", "src/app", "src/lib")]
    if modified is not None:
        return [
            f for f in modified
            if f.suffix in (".tsx", ".jsx", ".ts", ".js") and any(str(f).replace("\\", "/").startswith(p) for p in prefixes)
        ]
    out: List[Path] = []
    for d in ("src/components", "src/app", "src/lib"):
        tdir = target_repo / d
        if tdir.exists():
            for ext in ("*.tsx", "*.jsx", "*.ts", "*.js"):
                out.extend(list(tdir.rglob(ext)))
    return out


def check_domain_purity(target_repo: Path, run_cmd: Any, base_ref: Optional[str] = None) -> GateResult:
    """Verify domain constants and static table headers are not hardcoded in UI files."""
    violations: List[str] = []
    for file_path in _collect_domain_purity_files(target_repo, run_cmd, base_ref):
        if ".test." in file_path.name or ".spec." in file_path.name:
            continue
        content = file_path.read_text(encoding="utf-8", errors="replace")
        try:
            rel = file_path.relative_to(target_repo)
        except ValueError:
            rel = file_path
        for idx, line in enumerate(content.splitlines(), start=1):
            if CANONICAL_ARRAY_PATTERN.search(line):
                violations.append(f"{rel}:{idx} - Hardcoded canonical definition found: '{line.strip()}'. Move to DB/Domain Schema.")
            m = RAW_TH_PATTERN.search(line)
            if m and m.group(1).strip() and not m.group(1).strip().startswith("{"):
                violations.append(f"{rel}:{idx} - Hardcoded raw <th> header '{m.group(1).strip()}'. Table columns must be schema/dictionary-driven.")
    if violations:
        return GateResult(1, "Domain Purity Gate", False, f"Found {len(violations)} domain purity / magic string violation(s).", violations[:10])
    return GateResult(1, "Domain Purity Gate", True, "UI components are free of hardcoded domain constants and raw <th> headers.")


def check_dual_theme_and_a11y(target_repo: Path, run_cmd: Any, base_ref: Optional[str] = "HEAD~1") -> GateResult:
    """Check changed .tsx files for unpaired bg-white and icon <X> buttons missing aria-label."""
    files, err = read_changed_prod_files(target_repo, run_cmd, base_ref, (".tsx",), require_src_prefix=False)
    if files is None:
        return GateResult(1, "Dual-Theme & A11y Heuristic Gate", False, f"Git diff failed: {err}")
    violations = [v for rel, content in files for v in find_dual_theme_and_a11y_violations(rel, content)]
    if violations:
        return GateResult(1, "Dual-Theme & A11y Heuristic Gate", False, f"Found {len(violations)} dual-theme or accessibility heuristic warning(s).", violations[:10])
    return GateResult(1, "Dual-Theme & A11y Heuristic Gate", True, "Dual-theme and icon-button aria-label checks passed.")
