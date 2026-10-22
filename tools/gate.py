#!/usr/bin/env python3
"""
Edge Verification Gate: Deterministic Architectural Quality Assurance
Enforces Matt Pocock's Deep Module & Seam Principles, Poteto's Kitchen Rules,
and Kun Chen's Deterministic Review Gates.

Stage: MigrationGate Invariant Gate (Never touch schemas/migrations in refactors)
Stage: Net SLOC Budget Gate (Refactoring must not inflate code, with scaffolding budget)
Stage: Target SLOC Contraction Gate (Target action/controller must strictly shrink)
Stage: Zero-Wrapper Left Behind Gate (No pass-through shallow modules)
Stage: Domain Purity Gate (No hardcoded canonical arrays / magic headers in UI)
Stage: Hermetic Verification Gate (TypeScript + Unit Tests)
"""

import sys
import os
import re
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path, run_command
from tools.rules import RAW_TH_PATTERN, CANONICAL_ARRAY_PATTERN, SHALLOW_WRAPPER_PATTERN
setup_utf8_console()


class GateResult:
    def __init__(self, stage_num: int, name: str, passed: bool, message: str, details: Optional[List[str]] = None):
        self.stage_num = stage_num
        self.name = name
        self.passed = passed
        self.message = message
        self.details = details or []

    def __str__(self) -> str:
        icon = "✅ PASS" if self.passed else "❌ FAIL"
        header = f"[{icon}] Stage {self.stage_num}: {self.name}"
        lines = [header, f"  {self.message}"]
        for d in self.details:
            lines.append(f"    - {d}")
        return "\n".join(lines)


class EdgeVerificationGate:
    def __init__(self, target_repo_path: Path):
        self.target_repo = target_repo_path

    def _run_cmd(self, cmd: List[str], cwd: Optional[Path] = None) -> Tuple[int, str, str]:
        """Run a command in target repo or specified directory using tools.common.runner."""
        work_dir = cwd or self.target_repo
        return run_command(cmd, cwd=work_dir)

    # =========================================================================
    # STAGE: MigrationGate Invariant Gate
    # =========================================================================
    def check_migration_gate(self, base_ref: str = "HEAD~1") -> GateResult:
        """
        Enforces MigrationGate Invariant:
        Refactoring tasks must NEVER alter database schemas (src/db/schema/*)
        or migrations (drizzle/*).
        """
        code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", base_ref])
        if code != 0:
            code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", "HEAD"])
            if code != 0:
                code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only"])
                if code != 0:
                    return GateResult(
                        1,
                        "MigrationGate Invariant Gate",
                        False,
                        f"Git diff failed: {stderr.strip()}",
                    )

        violations = []
        for line in stdout.strip().splitlines():
            file_path = line.strip().replace("\\", "/")
            if not file_path:
                continue
            if file_path.startswith("src/db/schema") or file_path.startswith("drizzle/"):
                violations.append(file_path)

        if violations:
            details = [f"Forbidden modified file: {v}" for v in violations]
            return GateResult(
                1,
                "MigrationGate Invariant Gate",
                False,
                "MigrationGate VIOLATION: Database schemas or migrations were modified during a refactor task!",
                details,
            )

        return GateResult(
            1,
            "MigrationGate Invariant Gate",
            True,
            "Database schema and migrations preserved (0 schema/migration files touched).",
        )

    # =========================================================================
    # STAGE: Net SLOC Budget Gate
    # =========================================================================
    def check_net_sloc_budget(
        self,
        base_ref: str = "HEAD~1",
        is_refactor: bool = True,
        scaffolding_allowance: int = 0,
    ) -> GateResult:
        """
        Calculates Net SLOC (Insertions - Deletions) in non-test, non-doc files.
        If is_refactor is True, net_sloc must be <= scaffolding_allowance (default 0).
        """
        code, stdout, stderr = self._run_cmd(["git", "diff", "--numstat", base_ref, "HEAD"])
        if code != 0:
            # Fallback to checking working tree against HEAD
            code, stdout, stderr = self._run_cmd(["git", "diff", "--numstat", "HEAD"])
            if code != 0:
                code, stdout, stderr = self._run_cmd(["git", "diff", "--numstat"])
                if code != 0:
                    return GateResult(1, "Net SLOC Budget Gate", False, f"Git diff failed: {stderr.strip()}")

        insertions = 0
        deletions = 0
        inspected_files = []

        for line in stdout.strip().splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                continue
            add_str, del_str, file_path = parts[0], parts[1], parts[2]
            if add_str == "-" or del_str == "-":
                continue  # Binary file

            # Filter out tests and markdown documentation from code budget
            if (
                ".test." in file_path
                or ".spec." in file_path
                or file_path.startswith("tests/")
                or file_path.endswith(".md")
                or file_path.endswith(".json")
            ):
                continue

            add = int(add_str)
            del_ = int(del_str)
            insertions += add
            deletions += del_
            inspected_files.append(f"{file_path}: +{add}/-{del_}")

        net_sloc = insertions - deletions

        if is_refactor and net_sloc > 0:
            if scaffolding_allowance > 0 and net_sloc <= scaffolding_allowance:
                details = [
                    f"Scaffolding allowance used: +{net_sloc} lines (limit: {scaffolding_allowance})",
                    f"Gross additions: +{insertions}, deletions: -{deletions} across {len(inspected_files)} production files.",
                    "Notice: One-time scaffolding allowance granted for new domain repository setup.",
                ]
                return GateResult(
                    1,
                    "Net SLOC Budget Gate",
                    True,
                    f"Scaffolding allowance used: +{net_sloc} lines (limit: {scaffolding_allowance})",
                    details,
                )

            details = [
                f"Net Code Inflation: +{net_sloc} lines (Added: {insertions}, Deleted: {deletions})",
                f"Rule: Pruning and refactoring tasks MUST NOT inflate production code (allowance: {scaffolding_allowance}).",
                "Top file changes:",
            ] + inspected_files[:8]
            return GateResult(
                1,
                "Net SLOC Budget Gate",
                False,
                f"Code inflation detected: Net +{net_sloc} production lines added." + (
                    f" (Exceeds scaffolding allowance of {scaffolding_allowance} lines)" if scaffolding_allowance > 0 else ""
                ),
                details,
            )

        details = [
            f"Net SLOC delta: {net_sloc} (Added: {insertions}, Deleted: {deletions}) across {len(inspected_files)} production files.",
        ]
        return GateResult(1, "Net SLOC Budget Gate", True, f"Net SLOC delta: {net_sloc} (budget satisfied).", details)

    # =========================================================================
    # STAGE: Target SLOC Contraction Gate
    # =========================================================================
    def check_target_sloc(self, target_file: str, base_ref: str = "HEAD~1") -> GateResult:
        """
        Enforces Target SLOC Contraction:
        The target action/controller file being refactored must strictly shrink:
        insertions - deletions < 0 (i.e. deletions > insertions).
        """
        # Normalize target file path for matching
        norm_target = target_file.replace("\\", "/").strip()
        if norm_target.startswith("./"):
            norm_target = norm_target[2:]

        # Handle absolute path if within target_repo
        try:
            target_path_obj = Path(target_file)
            if target_path_obj.is_absolute():
                norm_target = str(target_path_obj.relative_to(self.target_repo)).replace("\\", "/")
        except Exception:
            pass

        code, stdout, stderr = self._run_cmd(["git", "diff", "--numstat", base_ref])
        if code != 0:
            code, stdout, stderr = self._run_cmd(["git", "diff", "--numstat", "HEAD"])
            if code != 0:
                code, stdout, stderr = self._run_cmd(["git", "diff", "--numstat"])
                if code != 0:
                    return GateResult(
                        1,
                        "Target SLOC Contraction Gate",
                        False,
                        f"Git diff failed: {stderr.strip()}",
                    )

        found = False
        target_ins = 0
        target_del = 0
        matched_path = ""

        for line in stdout.strip().splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                continue
            add_str, del_str, file_path = parts[0], parts[1], parts[2]
            p = file_path.replace("\\", "/").strip()

            if p == norm_target or p.endswith("/" + norm_target) or norm_target.endswith("/" + p):
                found = True
                matched_path = p
                if add_str != "-" and del_str != "-":
                    target_ins = int(add_str)
                    target_del = int(del_str)
                break

        if not found:
            return GateResult(
                1,
                "Target SLOC Contraction Gate",
                False,
                f"Target file '{target_file}' was not modified in git diff. Target file must be refactored and contracted.",
                [f"Target file: {target_file}", "Diff check found 0 changes for this file."],
            )

        delta = target_ins - target_del
        details = [
            f"Target file: {matched_path}",
            f"Insertions: +{target_ins}, Deletions: -{target_del}",
            f"Target Net Delta: {delta} lines (Requirement: insertions - deletions < 0)",
        ]

        if delta < 0:
            return GateResult(
                1,
                "Target SLOC Contraction Gate",
                True,
                f"Target file '{matched_path}' contracted by {abs(delta)} lines (+{target_ins}/-{target_del}).",
                details,
            )
        else:
            return GateResult(
                1,
                "Target SLOC Contraction Gate",
                False,
                f"Target file contraction failed: '{matched_path}' delta is +{delta} lines (+{target_ins}/-{target_del}). Must be strictly negative (insertions - deletions < 0).",
                details,
            )

    def _get_modified_files(self, base_ref: Optional[str] = None) -> Optional[List[Path]]:
        """Get list of files modified between base_ref and current worktree/HEAD."""
        if not base_ref:
            return None
        code, stdout, _ = self._run_cmd(["git", "diff", "--name-only", base_ref])
        if code != 0:
            code, stdout, _ = self._run_cmd(["git", "diff", "--name-only", base_ref, "HEAD"])
            if code != 0:
                return None

        files = []
        for line in stdout.splitlines():
            line = line.strip().replace("\\", "/")
            if line:
                p = self.target_repo / line
                if p.exists():
                    files.append(p)
        return files

    # =========================================================================
    # STAGE: Zero-Wrapper Left Behind Gate
    # =========================================================================
    def check_zero_wrappers(self, base_ref: Optional[str] = None) -> GateResult:
        """
        Detects shallow pass-through components that wrap another component without
        substantive logic (e.g. ModalDialog wrapping Modal).
        """
        components_dir = self.target_repo / "src" / "components"
        if not components_dir.exists():
            return GateResult(1, "Zero-Wrapper Gate", True, "No components directory found.")

        shallow_wrappers = []
        modified = self._get_modified_files(base_ref)

        if modified is not None:
            candidate_files = [
                f for f in modified
                if f.suffix in (".tsx", ".jsx") and str(f).replace("\\", "/").startswith(str(components_dir).replace("\\", "/"))
            ]
        else:
            candidate_files = list(components_dir.rglob("*.tsx"))

        for tsx_file in candidate_files:
            # Skip tests
            if ".test." in tsx_file.name or ".spec." in tsx_file.name:
                continue

            try:
                content = tsx_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("//")]
            # Check for pass-through wrapper patterns:
            # 1. Imports another component
            # 2. Total non-comment lines < 45
            # 3. Main return statement is a single JSX element wrapping children with same/mapped props
            
            # Pattern check: return <SomeModal ...>{children}</SomeModal>
            pass_through_matches = SHALLOW_WRAPPER_PATTERN.findall(content)
            
            # Detect explicit wrapper adapter notes or pass-through delegation
            is_delegating = bool(pass_through_matches)
            if is_delegating and len(lines) < 55:
                target_comp = pass_through_matches[0][0]
                # If component name differs from target (e.g. ModalDialog wrapping Modal)
                comp_name_match = re.search(r"export\s+function\s+([A-Za-z0-9]+)", content)
                comp_name = comp_name_match.group(1) if comp_name_match else tsx_file.stem
                if comp_name != target_comp:
                    rel_path = tsx_file.relative_to(self.target_repo)
                    shallow_wrappers.append(
                        f"{rel_path}: '{comp_name}' is a shallow pass-through wrapping '{target_comp}'. Delete wrapper and migrate callers directly."
                    )

        if shallow_wrappers:
            return GateResult(
                1,
                "Zero-Wrapper Gate",
                False,
                f"Found {len(shallow_wrappers)} shallow pass-through wrapper(s).",
                shallow_wrappers,
            )

        return GateResult(1, "Zero-Wrapper Gate", True, "Zero shallow pass-through wrappers found.")

    # =========================================================================
    # STAGE: Presentation vs Domain Schema Purity Gate
    # =========================================================================
    def check_domain_purity(self, base_ref: Optional[str] = None) -> GateResult:
        """
        Verifies that domain schemas, canonical enums/arrays, and static table headers
        are not hardcoded inside frontend UI components.
        """
        violations = []

        modified = self._get_modified_files(base_ref)

        if modified is not None:
            candidate_files = [
                f for f in modified
                if f.suffix in (".tsx", ".jsx", ".ts", ".js")
                and any(str(f).replace("\\", "/").startswith(str(self.target_repo / d).replace("\\", "/")) for d in ["src/components", "src/app", "src/lib"])
            ]
        else:
            components_dir = self.target_repo / "src" / "components"
            target_dirs = [components_dir, self.target_repo / "src" / "app", self.target_repo / "src" / "lib"]
            candidate_files = []
            for tdir in target_dirs:
                if tdir.exists():
                    for ext in ("*.tsx", "*.jsx", "*.ts", "*.js"):
                        candidate_files.extend(list(tdir.rglob(ext)))

        for file_path in candidate_files:
            if ".test." in file_path.name or ".spec." in file_path.name:
                continue

            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            try:
                rel = file_path.relative_to(self.target_repo)
            except ValueError:
                rel = file_path

            # Check for canonical array declarations inside frontend component tree
            for idx, line in enumerate(content.splitlines(), start=1):
                if CANONICAL_ARRAY_PATTERN.search(line):
                    violations.append(
                        f"{rel}:{idx} - Hardcoded canonical definition found: '{line.strip()}'. Move to DB/Domain Schema."
                    )

            # Check for raw string <th> tags in JSX (bypassing schema-driven table headers)
            for idx, line in enumerate(content.splitlines(), start=1):
                m = RAW_TH_PATTERN.search(line)
                if m:
                    header_text = m.group(1).strip()
                    if header_text and not header_text.startswith("{"):
                        violations.append(
                            f"{rel}:{idx} - Hardcoded raw <th> header '{header_text}'. Table columns must be schema/dictionary-driven."
                        )

        if violations:
            return GateResult(
                1,
                "Domain Purity Gate",
                False,
                f"Found {len(violations)} domain purity / magic string violation(s).",
                violations[:10],
            )

        return GateResult(1, "Domain Purity Gate", True, "UI components are free of hardcoded domain constants and raw <th> headers.")

    # =========================================================================
    # STAGE: Hermetic Verification Gate
    # =========================================================================
    def check_verification(self) -> GateResult:
        """Runs npx tsc --noEmit and npm run test:unit to ensure zero compilation or behavioral regressions."""
        # 1. Typecheck
        code, stdout, stderr = self._run_cmd(["npx", "tsc", "--noEmit"])
        if code != 0:
            details = [l for l in (stdout + stderr).splitlines() if "error TS" in l][:8]
            return GateResult(1, "Hermetic Verification Gate", False, "TypeScript typecheck failed.", details)

        # 2. Unit tests
        code, stdout, stderr = self._run_cmd(["npm", "run", "test:unit"])
        if code != 0:
            details = [l for l in (stdout + stderr).splitlines() if "FAIL" in l or "Error" in l][:8]
            return GateResult(1, "Hermetic Verification Gate", False, "Unit tests failed.", details)

        return GateResult(1, "Hermetic Verification Gate", True, "TypeScript clean and all unit tests passed.")

    # =========================================================================
    # Runner
    # =========================================================================
    def run_all(
        self,
        base_ref: str = "HEAD~1",
        is_refactor: bool = True,
        skip_verification: bool = False,
        target_file: Optional[str] = None,
        scaffolding_allowance: int = 0,
        track: str = "all",
    ) -> bool:
        print("=" * 70)
        print(f"🛡️  EDGE VERIFICATION GATE — ARCHITECTURAL AUDIT [{track.upper()} TRACK]")
        print("=" * 70)

        results = [
            self.check_migration_gate(base_ref=base_ref),
            self.check_net_sloc_budget(
                base_ref=base_ref,
                is_refactor=is_refactor,
                scaffolding_allowance=scaffolding_allowance,
            ),
        ]

        if target_file:
            results.append(self.check_target_sloc(target_file=target_file, base_ref=base_ref))

        # UI track specific gates
        if track in ("ui", "all"):
            results.extend([
                self.check_zero_wrappers(base_ref=base_ref),
                self.check_domain_purity(base_ref=base_ref),
            ])

        if not skip_verification:
            results.append(self.check_verification())
        else:
            print("  (Skipping Hermetic verification per --skip-verify)")

        all_passed = True
        for idx, r in enumerate(results, start=1):
            r.stage_num = idx
            print(str(r))
            print("-" * 70)
            if not r.passed:
                all_passed = False

        print("\n" + ("=" * 70))
        if all_passed:
            print("🎉 ALL GATES PASSED! Codebase is deep, clean, and un-bloated.")
        else:
            print("🚫 GATE CHECK FAILED. Address the violations above before merging.")
        print("=" * 70)
        return all_passed


def main():
    parser = argparse.ArgumentParser(description="Edge Architectural Quality & Anti-Bloat Gate")
    parser.add_argument("target", nargs="?", default=".", help="Target repository directory (e.g. /home/oguz/my-project or .)")
    parser.add_argument("--base", default="HEAD~1", help="Base commit/branch to compare diff against (default: HEAD~1)")
    parser.add_argument("--no-refactor", action="store_true", help="Set if this is a feature addition (allows positive net SLOC)")
    parser.add_argument("--skip-verify", action="store_true", help="Skip running tsc and unit tests (fast static audit only)")
    parser.add_argument("--target-file", default=None, help="Target action/controller file to enforce strict contraction (insertions - deletions < 0)")
    parser.add_argument("--allow-scaffolding", type=int, default=0, help="Scaffolding budget tolerance for new domain repositories (lines)")
    parser.add_argument("--track", choices=["core", "ui", "all", "feature"], default="all", help="Refactoring track: core, ui, all, or feature (default: all)")

    args = parser.parse_args()
    target_path = normalize_target_path(args.target)

    gate = EdgeVerificationGate(target_path)
    passed = gate.run_all(
        base_ref=args.base,
        is_refactor=not args.no_refactor,
        skip_verification=args.skip_verify,
        target_file=args.target_file,
        scaffolding_allowance=args.allow_scaffolding,
        track=args.track,
    )

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
