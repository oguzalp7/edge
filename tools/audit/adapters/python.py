import ast
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from ..base_adapter import LanguageAdapter
from ..models import FileMetrics, FunctionMetrics

class PythonAdapter(LanguageAdapter):
    @property
    def extensions(self) -> List[str]:
        return [".py"]

    @property
    def name(self) -> str:
        return "Python"

    def is_test_file(self, path: Path) -> bool:
        name = path.name.lower()
        parts = [p.lower() for p in path.parts]
        if name.startswith("test_") or name.endswith("_test.py"):
            return True
        if "tests" in parts or "test" in parts:
            return True
        return False

    def find_companion_tests(
        self,
        path: Path,
        workspace_root: Path,
        test_index: Optional[Dict[str, List[str]]] = None
    ) -> List[str]:
        if test_index is None:
            return []
        stem = path.stem.lower()
        matches = []
        if stem in test_index:
            matches.extend(test_index[stem])
        return list(set(matches))

    def _count_lines(self, lines: List[str]) -> Tuple[int, int, int, int]:
        total = len(lines)
        blank = 0
        comment = 0
        in_multiline = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                blank += 1
                continue

            if in_multiline:
                comment += 1
                if '"""' in stripped or "'''" in stripped:
                    in_multiline = False
                continue

            if stripped.startswith('"""') or stripped.startswith("'''"):
                comment += 1
                delim = '"""' if stripped.startswith('"""') else "'''"
                if stripped.count(delim) < 2:
                    in_multiline = True
                continue

            if stripped.startswith("#"):
                comment += 1
                continue

        sloc = total - blank - comment
        return total, sloc, comment, blank

    def _calc_max_indent(self, lines: List[str]) -> int:
        max_indent = 0
        for line in lines:
            if not line.strip():
                continue
            leading_spaces = len(line) - len(line.lstrip(" "))
            leading_tabs = len(line) - len(line.lstrip("\t"))
            indent_level = leading_tabs if leading_tabs > 0 else leading_spaces // 4
            if indent_level > max_indent:
                max_indent = indent_level
        return min(max_indent, 20)

    def analyze(
        self,
        path: Path,
        rel_path: str,
        content: str,
        workspace_root: Path,
        test_index: Optional[Dict[str, List[str]]] = None
    ) -> FileMetrics:
        lines = content.splitlines()
        total, sloc, comment, blank = self._count_lines(lines)
        max_indent = self._calc_max_indent(lines)
        
        complexity = 1
        exports = 0
        funcs = []

        try:
            tree = ast.parse(content)
            for node in ast.walk(tree):
                if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With)):
                    complexity += 1
                elif isinstance(node, ast.BoolOp):
                    complexity += len(node.values) - 1

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = node.lineno
                    end = getattr(node, "end_lineno", start)
                    func_sloc = end - start + 1
                    is_public = not node.name.startswith("_")
                    if is_public:
                        exports += 1
                    funcs.append(
                        FunctionMetrics(
                            name=node.name,
                            start_line=start,
                            end_line=end,
                            sloc=func_sloc,
                            complexity=1,
                            is_exported=is_public,
                        )
                    )
                elif isinstance(node, ast.ClassDef):
                    if not node.name.startswith("_"):
                        exports += 1

        except SyntaxError:
            complexity = 10

        companion_tests = self.find_companion_tests(path, workspace_root, test_index)
        has_test_seam = len(companion_tests) > 0

        return FileMetrics(
            path=path,
            rel_path=rel_path,
            extension=path.suffix,
            total_lines=total,
            sloc=sloc,
            comment_lines=comment,
            blank_lines=blank,
            complexity_score=complexity,
            max_indent_level=max_indent,
            public_exports=exports,
            functions=funcs,
            has_test_seam=has_test_seam,
            companion_tests=companion_tests,
        )
