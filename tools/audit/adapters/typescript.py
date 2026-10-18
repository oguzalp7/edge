import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from ..base_adapter import LanguageAdapter
from ..models import FileMetrics, FunctionMetrics
from tools.rules import SQL_LEAK_PATTERN


class TypeScriptAdapter(LanguageAdapter):
    GENERIC_STEMS = {
        "index", "repository", "service", "utils", "actions", "schema",
        "types", "constants", "cli", "models", "scanner"
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
        if "tests" in parts or "__tests__" in parts or "spec" in parts:
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
        base_name = stem.split(".")[0]
        parent_dir = path.parent.name.lower()

        matches = []
        if stem in self.GENERIC_STEMS:
            # 1. Match combo: <parent_dir>/<stem>
            combo_key = f"{parent_dir}/{stem}"
            if combo_key in test_index:
                matches.extend(test_index[combo_key])
            # 2. Check domain tests for parent_dir: domain:<parent_dir> or test_<parent_dir> or <parent_dir>
            if f"domain:{parent_dir}" in test_index:
                matches.extend(test_index[f"domain:{parent_dir}"])
            if parent_dir in test_index and parent_dir not in self.GENERIC_STEMS:
                matches.extend(test_index[parent_dir])
            if f"test_{parent_dir}" in test_index:
                matches.extend(test_index[f"test_{parent_dir}"])
        else:
            if stem in test_index:
                matches.extend(test_index[stem])
            if base_name in test_index:
                matches.extend(test_index[base_name])
            combo_key = f"{parent_dir}/{stem}"
            if combo_key in test_index:
                matches.extend(test_index[combo_key])

        return list(set(matches))

    def _count_lines(self, lines: List[str]) -> Tuple[int, int, int, int]:
        total = len(lines)
        blank = 0
        comment = 0
        in_multiline_comment = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                blank += 1
                continue

            if in_multiline_comment:
                comment += 1
                if "*/" in stripped:
                    in_multiline_comment = False
                continue

            if stripped.startswith("/*"):
                comment += 1
                if "*/" not in stripped or stripped.count("/*") > stripped.count("*/"):
                    in_multiline_comment = True
                continue

            if stripped.startswith("//"):
                comment += 1
                continue

        sloc = total - blank - comment
        return total, sloc, comment, blank

    def _calc_max_indent(self, lines: List[str]) -> int:
        space_indents = [len(l) - len(l.lstrip(" ")) for l in lines if l.strip() and (len(l) - len(l.lstrip(" "))) > 0]
        indent_unit = 2
        if space_indents:
            min_indent = min(space_indents)
            multiples_of_4 = sum(1 for i in space_indents if i % 4 == 0)
            if min_indent >= 4 and (multiples_of_4 / len(space_indents)) >= 0.5:
                indent_unit = 4

        max_indent = 0
        for line in lines:
            if not line.strip():
                continue
            leading_spaces = len(line) - len(line.lstrip(" "))
            leading_tabs = len(line) - len(line.lstrip("\t"))
            indent_level = leading_tabs if leading_tabs > 0 else leading_spaces // indent_unit
            if indent_level > max_indent:
                max_indent = indent_level
        return min(max_indent, 20)

    def _calc_complexity(self, content: str) -> int:
        patterns = [
            r"\bif\b",
            r"\belse\s+if\b",
            r"\bswitch\b",
            r"\bcase\b",
            r"\bwhile\b",
            r"\bfor\b",
            r"\bcatch\b",
            r"&&",
            r"\|\|",
            r"\?\?",
            r"\?[^:.\s]+\s*:",
        ]
        score = 1
        for pat in patterns:
            score += len(re.findall(pat, content))
        return score

    def _count_exports(self, content: str) -> int:
        patterns = [
            r"\bexport\s+default\b",
            r"\bexport\s+(?:async\s+)?function\b",
            r"\bexport\s+(?:const|let|var)\b",
            r"\bexport\s+class\b",
            r"\bexport\s+(?:type|interface)\b",
            r"\bexport\s+enum\b",
            r"\bexport\s*\{[^}]+\}",
        ]
        count = 0
        for pat in patterns:
            count += len(re.findall(pat, content))
        return count

    def _find_functions(self, lines: List[str]) -> List[FunctionMetrics]:
        funcs = []
        func_sig_pat = re.compile(
            r"^(?:\s*export\s+)?(?:async\s+)?(?:function\s+(\w+)|(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>|(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?function)"
        )

        limit = min(len(lines), 3000)
        for idx in range(limit):
            line = lines[idx]
            match = func_sig_pat.search(line)
            if match:
                name = match.group(1) or match.group(2) or match.group(3) or "anonymous"
                is_exported = "export" in line
                start_line = idx + 1

                brace_count = 0
                started = False
                end_line = start_line

                for scan_idx in range(idx, min(idx + 500, len(lines))):
                    scan_line = lines[scan_idx]
                    brace_count += scan_line.count("{") - scan_line.count("}")
                    if "{" in scan_line:
                        started = True
                    if started and brace_count <= 0:
                        end_line = scan_idx + 1
                        break

                sloc = max(1, end_line - start_line + 1)
                func_body = "\n".join(lines[start_line - 1 : end_line])
                complexity = self._calc_complexity(func_body)
                funcs.append(
                    FunctionMetrics(
                        name=name,
                        start_line=start_line,
                        end_line=end_line,
                        sloc=sloc,
                        complexity=complexity,
                        is_exported=is_exported,
                    )
                )
        return funcs

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
        complexity = self._calc_complexity(content)
        exports = self._count_exports(content)
        funcs = self._find_functions(lines)

        companion_tests = self.find_companion_tests(path, workspace_root, test_index)
        has_test_seam = len(companion_tests) > 0

        has_ui_action_mixing = False
        if path.suffix.lower() in (".tsx", ".jsx"):
            has_ui_action_mixing = bool(SQL_LEAK_PATTERN.search(content))

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
            has_ui_action_mixing=has_ui_action_mixing,
        )
