"""
TypeScript/JavaScript language adapter for edge-audit.
"""

from pathlib import Path
from typing import Dict, List, Optional

from tools.rules import SQL_LEAK_PATTERN
from ..base_adapter import LanguageAdapter
from ..models import FileMetrics, FunctionMetrics
from .ts_metrics import (
    calc_ts_complexity,
    calc_ts_max_indent,
    count_ts_exports,
    count_ts_lines,
    find_ts_functions,
)


class TypeScriptAdapter(LanguageAdapter):
    GENERIC_STEMS = {
        "index", "repository", "service", "utils", "actions", "schema",
        "types", "constants", "cli", "models", "scanner",
    }

    @property
    def extensions(self) -> List[str]:
        return [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]

    @property
    def name(self) -> str:
        return "TypeScript/Next.js"

    def is_test_file(self, path: Path) -> bool:
        name = path.name.lower()
        parts = [p.lower() for p in path.parts]
        if ".test." in name or ".spec." in name or "_test." in name:
            return True
        return "tests" in parts or "__tests__" in parts or "spec" in parts

    def find_companion_tests(
        self, path: Path, workspace_root: Path, test_index: Optional[Dict[str, List[str]]] = None
    ) -> List[str]:
        if test_index is None:
            return []
        stem = path.stem.lower()
        base_name = stem.split(".")[0]
        parent_dir = path.parent.name.lower()
        combo_key = f"{parent_dir}/{stem}"
        matches: List[str] = list(test_index.get(combo_key, []))
        if stem in self.GENERIC_STEMS:
            matches.extend(test_index.get(f"domain:{parent_dir}", []))
            if parent_dir not in self.GENERIC_STEMS:
                matches.extend(test_index.get(parent_dir, []))
            matches.extend(test_index.get(f"test_{parent_dir}", []))
        else:
            matches.extend(test_index.get(stem, []))
            matches.extend(test_index.get(base_name, []))
        return list(set(matches))

    def _count_lines(self, lines: List[str]):
        return count_ts_lines(lines)

    def _calc_max_indent(self, lines: List[str]) -> int:
        return calc_ts_max_indent(lines)

    def _calc_complexity(self, content: str) -> int:
        return calc_ts_complexity(content)

    def _count_exports(self, content: str) -> int:
        return count_ts_exports(content)

    def _find_functions(self, lines: List[str], path: Optional[Path] = None, rel_path: Optional[str] = None) -> List[FunctionMetrics]:
        return find_ts_functions(lines, path=path, rel_path=rel_path)

    def analyze(
        self, path: Path, rel_path: str, content: str, workspace_root: Path, test_index: Optional[Dict[str, List[str]]] = None
    ) -> FileMetrics:
        lines = content.splitlines()
        total, sloc, comment, blank = self._count_lines(lines)
        companion_tests = self.find_companion_tests(path, workspace_root, test_index)
        has_ui_action_mixing = bool(SQL_LEAK_PATTERN.search(content)) if path.suffix.lower() in (".tsx", ".jsx") else False
        return FileMetrics(
            path=path,
            rel_path=rel_path,
            extension=path.suffix,
            total_lines=total,
            sloc=sloc,
            comment_lines=comment,
            blank_lines=blank,
            complexity_score=self._calc_complexity(content),
            max_indent_level=self._calc_max_indent(lines),
            public_exports=self._count_exports(content),
            functions=self._find_functions(lines, path=path, rel_path=rel_path),
            has_test_seam=len(companion_tests) > 0,
            companion_tests=companion_tests,
            has_ui_action_mixing=has_ui_action_mixing,
        )
