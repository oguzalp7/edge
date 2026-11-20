#!/usr/bin/env python3
"""
Edge Verification Gate: Deterministic Architectural Quality Assurance
Enforces Matt Pocock's Deep Module & Seam Principles, Poteto's Kitchen Rules,
and Kun Chen's Deterministic Review Gates.

Stage: MigrationGate Invariant Gate (Never touch schemas/migrations in refactors)
Stage: Max CC Non-Regression Gate (No cyclomatic complexity regression; CC <= 10 ceiling on clean/new files)
Stage: Layer Leakage Gate (No new direct DB calls in action/controller layer)
Stage: Zero-Wrapper Left Behind Gate (No pass-through shallow modules)
Stage: Domain Purity Gate (No hardcoded canonical arrays / magic headers in UI)
Stage: Hermetic Verification Gate (TypeScript + Unit Tests)
"""

import ast
import json
import sys
import os
import re
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import setup_utf8_console, normalize_target_path, run_command
from tools.rules import (
    RAW_TH_PATTERN,
    CANONICAL_ARRAY_PATTERN,
    SHALLOW_WRAPPER_PATTERN,
    SQL_LEAK_PATTERN,
    MOCK_FALLBACK_PATTERN,
    TYPE_ESCAPE_PATTERN,
    BG_WHITE_NO_DARK_PATTERN,
    ICON_X_BUTTON_NO_ARIA_PATTERN,
)
from tools.audit import crapper as _crapper

setup_utf8_console()

TREE_SITTER_AVAILABLE: bool = bool(getattr(_crapper, "TREE_SITTER_AVAILABLE", False))

_PRODUCTION_CODE_SUFFIXES: Tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".py")
_ACTION_CODE_SUFFIXES: Tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

_JS_BRANCH_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"\bif\b"),
    re.compile(r"\bfor\b"),
    re.compile(r"\bwhile\b"),
    re.compile(r"\bcase\b"),
    re.compile(r"\bcatch\b"),
    re.compile(r"&&"),
    re.compile(r"\|\|"),
    re.compile(r"(?<!\?)\?(?![?.:])"),
]

_JS_FUNC_DECL_RE: re.Pattern[str] = re.compile(
    r"\bfunction\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>]*>)?\s*\("
)
_JS_VAR_FUNC_RE: re.Pattern[str] = re.compile(
    r"\b(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?"
    r"(?:function\b|(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=>)"
)
_JS_METHOD_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|readonly\s+|override\s+|async\s+)*"
    r"([A-Za-z_$][A-Za-z0-9_$]*)\s*(?:<[^>]*>)?\s*\([^;]*\)\s*(?::\s*[^{;=]+)?\{"
)
_JS_CONTROL_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return"}


_JS_COMMENT_OR_STRING_RE: re.Pattern[str] = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\"|`(?:\\.|[^`\\])*`"
)


def _mask_non_newlines(match: re.Match[str]) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in match.group(0))


def _strip_js_comments_and_strings(text: str) -> str:
    """
    Replaces JS/TS comments and string literal contents with spaces while preserving
    newlines so brace matching and branch keyword counting stay deterministic.
    """
    return _JS_COMMENT_OR_STRING_RE.sub(_mask_non_newlines, text)


def _count_js_branches(sanitized_block: str) -> int:
    score = 1
    for pat in _JS_BRANCH_PATTERNS:
        score += len(pat.findall(sanitized_block))
    return score


def _ast_py_node_complexity(root_node: ast.AST) -> int:
    comp = 1
    for node in ast.walk(root_node):
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)):
            comp += 1
        elif isinstance(node, ast.BoolOp):
            comp += max(1, len(node.values) - 1)
        elif hasattr(ast, "Match") and isinstance(node, ast.Match):
            comp += len(node.cases)
    return comp


def _compute_py_fallback_max_cc(source_text: str) -> Optional[Tuple[int, str]]:
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return None

    funcs: List[Tuple[int, str]] = []

    def _visit_stmts(stmts: List[ast.stmt]) -> None:
        for stmt in stmts:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.append((_ast_py_node_complexity(stmt), stmt.name))
            elif isinstance(stmt, ast.ClassDef):
                _visit_stmts(stmt.body)

    _visit_stmts(tree.body)
    if funcs:
        return max(funcs, key=lambda item: item[0])
    return (_ast_py_node_complexity(tree), "<module>")


def _compute_js_fallback_max_cc(source_text: str) -> Tuple[int, str]:
    sanitized = _strip_js_comments_and_strings(source_text)
    lines = sanitized.splitlines()
    funcs: List[Tuple[int, str]] = []

    idx = 0
    total_lines = len(lines)
    while idx < total_lines:
        line = lines[idx]
        m = _JS_FUNC_DECL_RE.search(line) or _JS_VAR_FUNC_RE.search(line)
        name: Optional[str] = None
        if m:
            name = m.group(1)
        else:
            m_meth = _JS_METHOD_RE.search(line)
            if m_meth and m_meth.group(1) not in _JS_CONTROL_KEYWORDS:
                name = m_meth.group(1)

        if name:
            brace_count = 0
            started = False
            end_idx = idx
            for scan_idx in range(idx, total_lines):
                scan_line = lines[scan_idx]
                opens = scan_line.count("{")
                closes = scan_line.count("}")
                if opens > 0:
                    started = True
                brace_count += opens - closes
                if started and brace_count <= 0:
                    end_idx = scan_idx
                    break
                if not started and ";" in scan_line:
                    end_idx = scan_idx
                    break

            body = "\n".join(lines[idx : end_idx + 1])
            funcs.append((_count_js_branches(body), name))
            idx = end_idx + 1
            continue

        idx += 1

    if funcs:
        return max(funcs, key=lambda item: item[0])
    return (_count_js_branches(sanitized), "<module>")


def _compute_source_max_cc(source_text: str, suffix: str) -> Tuple[int, str]:
    """
    Deterministically computes the maximum per-function cyclomatic complexity (CC)
    and corresponding symbol name for a source string.
    Uses tree-sitter AST via tools.audit.crapper when available, and falls back
    to Python AST / sanitized JS-TS block branch counting when tree-sitter is absent.
    """
    if not source_text or not source_text.strip():
        return (0, "<empty>")

    ext = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"

    ts_enabled = TREE_SITTER_AVAILABLE and bool(getattr(_crapper, "TREE_SITTER_AVAILABLE", False))
    if ts_enabled:
        parser, _ = _crapper._get_parser_for_ext(ext)
        if parser is not None:
            source_bytes = source_text.encode("utf-8")
            tree = parser.parse(source_bytes)
            root = tree.root_node
            function_types = {
                "function_declaration",
                "function_definition",
                "arrow_function",
                "method_definition",
                "function_expression",
            }
            found_funcs: List[Tuple[int, str]] = []

            def _visit(node: Any) -> None:
                if node.type in function_types:
                    sym = _crapper._find_function_symbol(node, source_bytes)
                    cc = _crapper._calc_node_complexity(node, source_bytes)
                    found_funcs.append((cc, sym))
                    return
                for child in node.children:
                    _visit(child)

            _visit(root)
            if found_funcs:
                return max(found_funcs, key=lambda item: item[0])
            return (_crapper._calc_node_complexity(root, source_bytes), "<module>")

    if ext == ".py":
        py_res = _compute_py_fallback_max_cc(source_text)
        if py_res is not None:
            return py_res

    return _compute_js_fallback_max_cc(source_text)


def _is_excluded_non_prod_path(rel_path: str) -> bool:
    norm = rel_path.strip().replace("\\", "/").lstrip("./")
    if not norm:
        return True
    name = Path(norm).name.lower()
    if (
        ".test." in norm
        or ".spec." in norm
        or norm.startswith("tests/")
        or "/tests/" in norm
        or norm.startswith("__tests__/")
        or "/__tests__/" in norm
        or name.startswith("test_")
        or name.endswith("_test.py")
        or norm.endswith(".md")
        or norm.endswith(".json")
        or norm.startswith(".edge/")
        or "/.edge/" in norm
    ):
        return True
    return False


def _is_action_controller_path(rel_path: str) -> bool:
    norm = rel_path.strip().replace("\\", "/").lstrip("./")
    if _is_excluded_non_prod_path(norm):
        return False
    suffix = Path(norm).suffix.lower()
    if suffix not in _ACTION_CODE_SUFFIXES:
        return False
    parts = norm.split("/")
    return "actions" in parts[:-1]


def _count_sql_leaks(source_text: str) -> int:
    sanitized = _strip_js_comments_and_strings(source_text)
    return len(SQL_LEAK_PATTERN.findall(sanitized))


_NON_DIRECTIVE_LINE_COMMENT_RE: re.Pattern[str] = re.compile(
    r"//(?!\s*@ts-(?:ignore|expect-error)\b)[^\n]*"
)
_BG_WHITE_TOKEN_RE: re.Pattern[str] = re.compile(r"(?<![-\w])bg-white\b")


def _is_eligible_prod_path(
    rel_path: str,
    suffixes: Tuple[str, ...],
    require_src_prefix: bool,
) -> bool:
    if _is_excluded_non_prod_path(rel_path):
        return False
    if require_src_prefix and not rel_path.startswith("src/"):
        return False
    return Path(rel_path).suffix.lower() in suffixes


def _find_mock_fallback_violations(rel_path: str, content: str) -> List[str]:
    sanitized = _strip_js_comments_and_strings(content)
    hits: List[str] = []
    for idx, line in enumerate(sanitized.splitlines(), start=1):
        match = MOCK_FALLBACK_PATTERN.search(line)
        if match:
            hits.append(f"{rel_path}:{idx} - Production mock/default fallback '{match.group(0)}' detected.")
    return hits


def _find_type_escape_violations(rel_path: str, content: str) -> List[str]:
    cleaned = _NON_DIRECTIVE_LINE_COMMENT_RE.sub("", content)
    hits: List[str] = []
    for idx, line in enumerate(cleaned.splitlines(), start=1):
        match = TYPE_ESCAPE_PATTERN.search(line)
        if match:
            hits.append(f"{rel_path}:{idx} - Type escape '{match.group(0)}' detected.")
    return hits


def _find_dual_theme_and_a11y_violations(rel_path: str, content: str) -> List[str]:
    hits: List[str] = []
    for m in BG_WHITE_NO_DARK_PATTERN.finditer(content):
        raw_cls = m.group(0)
        if _BG_WHITE_TOKEN_RE.search(raw_cls) and "dark:bg-" not in raw_cls:
            hits.append(f"{rel_path}: className contains 'bg-white' without paired 'dark:bg-*' token.")
    for m in ICON_X_BUTTON_NO_ARIA_PATTERN.finditer(content):
        if "aria-label" not in m.group("attrs"):
            hits.append(f"{rel_path}: icon-only <X> <button> missing 'aria-label'.")
    return hits


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
    GHOST_ROOT_DIRS: Tuple[str, ...] = ("rc", "pecs", "ests", "pp", "ib", "omponents")

    def __init__(self, target_repo_path: Path):
        self.target_repo = target_repo_path

    def check_ghost_root_directories(self) -> GateResult:
        """
        Stage-0 Invariant: Detects truncated ghost root directories (e.g., 'rc', 'pecs', 'ests')
        caused by string slicing defects or malformed scripts.
        """
        detected: List[str] = [
            name for name in self.GHOST_ROOT_DIRS
            if (self.target_repo / name).is_dir()
        ]
        if detected:
            details = [f"Found invalid ghost directory: {self.target_repo / d}" for d in detected]
            return GateResult(
                stage_num=0,
                name="Ghost Root Directory Sanitizer Gate",
                passed=False,
                message=(
                    f"Truncated ghost root directories detected: {', '.join(detected)}. "
                    f"These indicate path-slicing defects (e.g. 'rc' instead of 'src'). "
                    f"Clean up or remove these directories before proceeding."
                ),
                details=details,
            )

        return GateResult(
            stage_num=0,
            name="Ghost Root Directory Sanitizer Gate",
            passed=True,
            message="No truncated ghost root directories detected in repository root.",
        )
        self.target_repo = target_repo_path

    def _run_cmd(self, cmd: List[str], cwd: Optional[Path] = None, timeout: int = 120) -> Tuple[int, str, str]:
        """Run a command in target repo or specified directory using tools.common.runner."""
        work_dir = cwd or self.target_repo
        return run_command(cmd, cwd=work_dir, timeout=timeout)

    @staticmethod
    def _compute_source_max_cc(source_text: str, suffix: str) -> Tuple[int, str]:
        return _compute_source_max_cc(source_text, suffix)

    def _get_changed_rel_paths(self, base_ref: str = "HEAD~1") -> Tuple[Optional[List[str]], str, str]:
        """
        Returns (rel_paths, effective_base_ref, error_message) between base_ref and current state.
        Includes untracked files when operating inside a real git repository/worktree.
        """
        eff_base = base_ref
        code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", base_ref])
        if code != 0:
            eff_base = "HEAD"
            code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only", "HEAD"])
            if code != 0:
                code, stdout, stderr = self._run_cmd(["git", "diff", "--name-only"])
                if code != 0:
                    return None, eff_base, stderr.strip()

        seen: Dict[str, None] = {}
        for line in stdout.splitlines():
            norm = line.strip().replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            if norm:
                seen[norm] = None

        if (self.target_repo / ".git").exists():
            u_code, u_out, _ = self._run_cmd(["git", "ls-files", "--others", "--exclude-standard"])
            if u_code == 0 and u_out:
                for line in u_out.splitlines():
                    norm = line.strip().replace("\\", "/")
                    if norm.startswith("./"):
                        norm = norm[2:]
                    if norm:
                        seen[norm] = None

        return list(seen.keys()), eff_base, ""

    # =========================================================================
    # STAGE: Navigation Check Gate
    # =========================================================================
    def _has_navigation_check_script(self) -> bool:
        """Return True when target package.json defines a non-empty check:navigation script."""
        pkg_path = self.target_repo / "package.json"
        if not pkg_path.is_file():
            return False
        try:
            data = json.loads(pkg_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return False
        if not isinstance(data, dict):
            return False
        scripts = data.get("scripts")
        if not isinstance(scripts, dict):
            return False
        nav = scripts.get("check:navigation")
        return isinstance(nav, str) and bool(nav.strip())

    def check_navigation_gate(self) -> GateResult:
        """Run npm run check:navigation unconditionally when configured in package.json."""
        if not self._has_navigation_check_script():
            return GateResult(
                1,
                "Navigation Check Gate",
                True,
                "No check:navigation script configured; skipped.",
            )

        if not (self.target_repo / "node_modules").exists():
            return GateResult(
                1,
                "Navigation Check Gate",
                False,
                "Missing node_modules for check:navigation — symlink or run npm ci before running gate.",
            )

        code, stdout, stderr = self._run_cmd(["npm", "run", "check:navigation"], timeout=60)
        if code == 0:
            return GateResult(
                1,
                "Navigation Check Gate",
                True,
                "Navigation integrity check (check:navigation) passed.",
            )

        details = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()][:8]
        return GateResult(
            1,
            "Navigation Check Gate",
            False,
            f"Navigation integrity check (check:navigation) failed (exit code {code}).",
            details,
        )

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
    # STAGE: Max CC Non-Regression Gate
    # =========================================================================
    def check_complexity_non_regression(
        self,
        base_ref: str = "HEAD~1",
        healthy_cc_ceiling: int = 10,
    ) -> GateResult:
        """
        Enforces Cyclomatic Complexity Non-Regression across modified/added production files:
        - Existing files: after_max_cc <= max(before_max_cc, healthy_cc_ceiling)
        - Newly created files: after_max_cc <= healthy_cc_ceiling
        """
        rel_paths, eff_base, err = self._get_changed_rel_paths(base_ref)
        if rel_paths is None:
            return GateResult(
                1,
                "Max CC Non-Regression Gate",
                False,
                f"Git diff failed: {err}",
            )

        violations: List[str] = []
        inspected_details: List[str] = []

        for rel_path in rel_paths:
            if _is_excluded_non_prod_path(rel_path):
                continue

            suffix = Path(rel_path).suffix.lower()
            if suffix not in _PRODUCTION_CODE_SUFFIXES:
                continue

            full_path = self.target_repo / rel_path
            if not full_path.exists() or not full_path.is_file():
                continue

            try:
                after_text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            after_max_cc, after_sym = _compute_source_max_cc(after_text, suffix)
            show_code, before_text, _ = self._run_cmd(["git", "show", f"{eff_base}:{rel_path}"])

            if show_code == 0:
                before_max_cc, _ = _compute_source_max_cc(before_text, suffix)
                allowed_cc = max(before_max_cc, healthy_cc_ceiling)
                inspected_details.append(
                    f"{rel_path} ({after_sym}): max CC {before_max_cc} -> {after_max_cc} (ceiling: {allowed_cc})"
                )
                if after_max_cc > allowed_cc:
                    violations.append(
                        f"{rel_path} [symbol: {after_sym}]: max CC regressed {before_max_cc} -> {after_max_cc} (allowed ceiling: {allowed_cc})"
                    )
            else:
                inspected_details.append(
                    f"{rel_path} ({after_sym}, new): max CC {after_max_cc} (ceiling: {healthy_cc_ceiling})"
                )
                if after_max_cc > healthy_cc_ceiling:
                    violations.append(
                        f"{rel_path} [symbol: {after_sym}]: new file max CC 0 -> {after_max_cc} exceeds ceiling of {healthy_cc_ceiling}"
                    )

        if violations:
            return GateResult(
                1,
                "Max CC Non-Regression Gate",
                False,
                f"Cyclomatic complexity violation(s) detected in {len(violations)} production file(s).",
                violations,
            )

        return GateResult(
            1,
            "Max CC Non-Regression Gate",
            True,
            f"Max CC non-regression satisfied across {len(inspected_details)} production file(s) (healthy ceiling: {healthy_cc_ceiling}).",
            inspected_details[:8],
        )

    # =========================================================================
    # STAGE: Layer Leakage Gate
    # =========================================================================
    def check_layer_leakage(self, base_ref: str = "HEAD~1") -> GateResult:
        """
        Enforces Controller/Action Layer Leakage Non-Regression:
        - Newly created action files (src/actions/**, app/actions/**, */actions/*.ts*): 0 SQL_LEAK_PATTERN matches allowed.
        - Existing action files: after_leaks <= before_leaks (monotonically non-increasing DB leakage).
        """
        rel_paths, eff_base, err = self._get_changed_rel_paths(base_ref)
        if rel_paths is None:
            return GateResult(
                1,
                "Layer Leakage Gate",
                False,
                f"Git diff failed: {err}",
            )

        violations: List[str] = []
        inspected_details: List[str] = []

        for rel_path in rel_paths:
            if not _is_action_controller_path(rel_path):
                continue

            full_path = self.target_repo / rel_path
            if not full_path.exists() or not full_path.is_file():
                continue

            try:
                after_text = full_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            after_leaks = _count_sql_leaks(after_text)
            show_code, before_text, _ = self._run_cmd(["git", "show", f"{eff_base}:{rel_path}"])

            if show_code != 0:
                inspected_details.append(f"{rel_path} (new action): {after_leaks} direct DB call(s)")
                if after_leaks > 0:
                    violations.append(
                        f"{rel_path}: newly created action controller contains {after_leaks} direct DB leak(s) (0 allowed)."
                    )
            else:
                before_leaks = _count_sql_leaks(before_text)
                inspected_details.append(f"{rel_path}: direct DB leaks {before_leaks} -> {after_leaks}")
                if after_leaks > before_leaks:
                    violations.append(
                        f"{rel_path}: DB layer leakage increased {before_leaks} -> {after_leaks} direct DB call(s)."
                    )

        if violations:
            return GateResult(
                1,
                "Layer Leakage Gate",
                False,
                f"Action/controller DB layer leakage detected in {len(violations)} file(s).",
                violations,
            )

        return GateResult(
            1,
            "Layer Leakage Gate",
            True,
            f"Controller layer DB leakage check passed across {len(inspected_details)} action file(s).",
            inspected_details[:8],
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

    def _read_changed_prod_files(
        self,
        base_ref: Optional[str],
        suffixes: Tuple[str, ...],
        require_src_prefix: bool = False,
    ) -> Tuple[Optional[List[Tuple[str, str]]], str]:
        rel_paths, _, err = self._get_changed_rel_paths(base_ref or "HEAD~1")
        if rel_paths is None:
            return None, err
        items: List[Tuple[str, str]] = []
        for rel_path in rel_paths:
            if not _is_eligible_prod_path(rel_path, suffixes, require_src_prefix):
                continue
            full_path = self.target_repo / rel_path
            if full_path.is_file():
                items.append((rel_path, full_path.read_text(encoding="utf-8", errors="replace")))
        return items, ""

    # =========================================================================
    # STAGE: Omission & Safety Heuristic Gates
    # =========================================================================
    def check_mock_fallbacks(self, base_ref: Optional[str] = "HEAD~1") -> GateResult:
        """Detects DEFAULT_* and MOCK_* synthetic fallback constants in production src/ files."""
        files, err = self._read_changed_prod_files(
            base_ref, (".ts", ".tsx", ".js", ".jsx"), require_src_prefix=True
        )
        if files is None:
            return GateResult(1, "Mock Fallback Purity Gate", False, f"Git diff failed: {err}")

        violations: List[str] = []
        for rel_path, content in files:
            violations.extend(_find_mock_fallback_violations(rel_path, content))

        if violations:
            return GateResult(
                1,
                "Mock Fallback Purity Gate",
                False,
                f"Found {len(violations)} synthetic mock/default fallback violation(s) in production code.",
                violations[:10],
            )
        return GateResult(1, "Mock Fallback Purity Gate", True, "Zero production DEFAULT_*/MOCK_* fallbacks detected.")

    def check_type_escapes(self, base_ref: Optional[str] = "HEAD~1") -> GateResult:
        """Detects `as any`, `as unknown as`, `@ts-ignore`, and `@ts-expect-error` in changed .ts/.tsx files."""
        files, err = self._read_changed_prod_files(base_ref, (".ts", ".tsx"), require_src_prefix=False)
        if files is None:
            return GateResult(1, "Type Escape Gate", False, f"Git diff failed: {err}")

        violations: List[str] = []
        for rel_path, content in files:
            violations.extend(_find_type_escape_violations(rel_path, content))

        if violations:
            return GateResult(
                1,
                "Type Escape Gate",
                False,
                f"Found {len(violations)} TypeScript type-safety escape(s).",
                violations[:10],
            )
        return GateResult(1, "Type Escape Gate", True, "Zero TypeScript type-safety escapes detected.")

    def check_dual_theme_and_a11y(self, base_ref: Optional[str] = "HEAD~1") -> GateResult:
        """Checks changed .tsx files for unpaired bg-white (missing dark:bg-*) and icon <X> buttons missing aria-label."""
        files, err = self._read_changed_prod_files(base_ref, (".tsx",), require_src_prefix=False)
        if files is None:
            return GateResult(1, "Dual-Theme & A11y Heuristic Gate", False, f"Git diff failed: {err}")

        violations: List[str] = []
        for rel_path, content in files:
            violations.extend(_find_dual_theme_and_a11y_violations(rel_path, content))

        if violations:
            return GateResult(
                1,
                "Dual-Theme & A11y Heuristic Gate",
                False,
                f"Found {len(violations)} dual-theme or accessibility heuristic warning(s).",
                violations[:10],
            )
        return GateResult(1, "Dual-Theme & A11y Heuristic Gate", True, "Dual-theme and icon-button aria-label checks passed.")

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
        code, stdout, stderr = self._run_cmd(["npm", "run", "test:unit"], timeout=360)
        if code != 0:
            details = [l for l in (stdout + stderr).splitlines() if "FAIL" in l or "Error" in l][:8]
            return GateResult(1, "Hermetic Verification Gate", False, "Unit tests failed.", details)

        return GateResult(1, "Hermetic Verification Gate", True, "TypeScript clean and all unit tests passed.")

    def check_differential_mutation_gate(
        self,
        base_ref: Optional[str] = "HEAD~1",
        skip_verify: bool = False,
        test_cmd: Optional[List[str]] = None,
    ) -> GateResult:
        """Runs differential SDL mutation verification on changed src/core/ production files."""
        rel_paths, _, _ = self._get_changed_rel_paths(base_ref or "HEAD~1")
        return check_differential_mutation_gate(
            self.target_repo,
            rel_paths or [],
            skip_verify=skip_verify,
            base_ref=base_ref,
            test_cmd=test_cmd,
        )

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

        results: List[GateResult] = []

        # Stage 0: Ghost root directory check (fail fast)
        ghost_result = self.check_ghost_root_directories()
        results.append(ghost_result)
        if not ghost_result.passed:
            print(str(ghost_result))
            print("-" * 70)
            print("\n" + ("=" * 70))
            print("🚫 GATE CHECK FAILED: Ghost root directories present. Halting audit immediately.")
            print("=" * 70)
            return False

        results.append(self.check_navigation_gate())

        if is_refactor and track != "feature":
            results.append(self.check_migration_gate(base_ref=base_ref))

        results.append(self.check_complexity_non_regression(base_ref=base_ref))
        results.extend([
            self.check_mock_fallbacks(base_ref=base_ref),
            self.check_type_escapes(base_ref=base_ref),
            self.check_dual_theme_and_a11y(base_ref=base_ref),
        ])

        # Core track specific gates
        if track in ("core", "all"):
            results.append(self.check_layer_leakage(base_ref=base_ref))
            results.append(
                self.check_differential_mutation_gate(base_ref=base_ref, skip_verify=skip_verification)
            )

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
        for idx, r in enumerate(results):
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


_SDL_CORE_SUFFIXES: Tuple[str, ...] = (".ts", ".tsx", ".js", ".py")


def _filter_core_sdl_files(repo_path: Path, changed_files: List[str]) -> List[str]:
    core_files: List[str] = []
    for raw in changed_files:
        norm = raw.strip().replace("\\", "/").lstrip("./")
        if not norm.startswith("src/core/") or _is_excluded_non_prod_path(norm):
            continue
        if norm.endswith(_SDL_CORE_SUFFIXES) and (repo_path / norm).is_file() and norm not in core_files:
            core_files.append(norm)
    return core_files


def _resolve_sdl_test_cmd(repo_path: Path, test_cmd: Optional[List[str]]) -> List[str]:
    if test_cmd:
        return list(test_cmd)
    pkg_file = repo_path / "package.json"
    if pkg_file.is_file():
        try:
            scripts = json.loads(pkg_file.read_text(encoding="utf-8")).get("scripts") or {}
            if isinstance(scripts, dict) and "test:unit" in scripts:
                return ["npm", "run", "test:unit"]
        except Exception:
            pass
    return ["pytest"]


def _run_static_sdl_scan(repo_path: Path, core_files: List[str], base_ref: Optional[str]) -> GateResult:
    from tools.mutator.runner import extract_git_diff_changed_lines
    from tools.mutator.sites import discover_mutation_sites

    total_sites = 0
    details: List[str] = []
    for rel in core_files:
        changed_lines = extract_git_diff_changed_lines(repo_path, repo_path / rel, base_ref=base_ref)
        sites = discover_mutation_sites(repo_path / rel, rel, covered_lines=(changed_lines or None), mode="sdl")
        total_sites += len(sites)
        details.extend(f"{rel}:{s.line} {s.original[:60]}" for s in sites[:3])
    msg = f"Static differential SDL scan found {total_sites} deletion site(s) across {len(core_files)} src/core/ file(s)."
    return GateResult(1, "Differential SDL Mutation Gate", True, msg, details[:10])


def _run_exec_sdl_scan(
    repo_path: Path,
    core_files: List[str],
    base_ref: Optional[str],
    resolved_cmd: List[str],
) -> GateResult:
    from tools.mutator.runner import run_mutations

    failed_files: List[str] = []
    details: List[str] = []
    for rel in core_files:
        summary = run_mutations(
            repo_path, repo_path / rel, resolved_cmd, mode="sdl", diff_only=True, base_ref=base_ref, threshold=80.0
        )
        if not summary.passed:
            failed_files.append(rel)
            details.extend(
                f"{rel}:{o.site.line} SURVIVED {o.site.original[:50]}"
                for o in summary.outcomes if o.status != "KILLED"
            )
    if failed_files:
        return GateResult(
            1,
            "Differential SDL Mutation Gate",
            False,
            f"Differential SDL mutation score below 80% on {len(failed_files)} file(s).",
            details[:10],
        )
    return GateResult(
        1,
        "Differential SDL Mutation Gate",
        True,
        f"Differential SDL mutation gate passed across {len(core_files)} src/core/ file(s).",
        details[:10],
    )


def check_differential_mutation_gate(
    repo_path: Path,
    changed_files: List[str],
    skip_verify: bool = False,
    base_ref: Optional[str] = None,
    test_cmd: Optional[List[str]] = None,
) -> GateResult:
    """Runs static SDL discovery (skip_verify=True) or differential SDL mutation testing on src/core/ changes."""
    repo = Path(repo_path).resolve()
    core_files = _filter_core_sdl_files(repo, changed_files)
    if not core_files:
        return GateResult(
            1, "Differential SDL Mutation Gate", True, "No src/core/ production files changed; differential SDL gate bypassed."
        )
    if skip_verify:
        return _run_static_sdl_scan(repo, core_files, base_ref)
    resolved_cmd = _resolve_sdl_test_cmd(repo, test_cmd)
    return _run_exec_sdl_scan(repo, core_files, base_ref, resolved_cmd)


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge Architectural Quality & Complexity Gate")
    parser.add_argument("target", nargs="?", default=".", help="Target repository directory (e.g. /home/oguz/my-project or .)")
    parser.add_argument("--base", default="HEAD~1", help="Base commit/branch to compare diff against (default: HEAD~1)")
    parser.add_argument("--no-refactor", action="store_true", help="Set if this is a feature addition (skips refactor-only schema lock)")
    parser.add_argument("--skip-verify", action="store_true", help="Skip running tsc and unit tests (fast static audit only)")
    parser.add_argument("--target-file", default=None, help="(Deprecated/Legacy) Retained for CLI compatibility; SLOC contraction is retired")
    parser.add_argument("--allow-scaffolding", type=int, default=0, help="(Deprecated/Legacy) Retained for CLI compatibility; SLOC budget is retired")
    parser.add_argument("--track", choices=["core", "ui", "all", "feature"], default="all", help="Audit track: core, ui, all, or feature (default: all)")

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
