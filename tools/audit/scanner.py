from pathlib import Path
from typing import List, Dict, Optional
from collections import defaultdict
from tools.common.paths import normalize_target_path
from .base_adapter import LanguageAdapter
from .adapters.typescript import TypeScriptAdapter
from .adapters.python import PythonAdapter
from .models import AuditSummary
from .scorer import HealthScorer
from .scanner_helpers import (
    index_test_dir,
    iter_unignored_files,
    read_text_safely,
    resolve_scoped_path,
)


class FileScanner:
    """Scans source directories and builds per-file structural health metrics."""

    DEFAULT_EXCLUDES = {
        "node_modules", ".git", ".next", "dist", "build", ".scratch",
        "coverage", ".archive", ".vscode", "public", ".npm", "__pycache__",
        ".pytest_cache", ".venv", "venv", ".idea", ".staging", "scratch"
    }

    GENERIC_STEMS = {
        "index", "repository", "service", "utils", "actions", "schema",
        "types", "constants", "cli", "models", "scanner"
    }

    def __init__(self, workspace_root: Optional[Path] = None):
        self.workspace_root = workspace_root
        self.adapters: List[LanguageAdapter] = [
            TypeScriptAdapter(),
            PythonAdapter(),
        ]
        self.ext_map: Dict[str, LanguageAdapter] = {}
        for adapter in self.adapters:
            for ext in adapter.extensions:
                self.ext_map[ext.lower()] = adapter

    @staticmethod
    def normalize_target_path(path_str: str) -> Path:
        """Converts WSL path strings (e.g. /home/oguz/...) to UNC format on Windows."""
        return normalize_target_path(path_str)

    def _build_test_index(self, root: Path) -> Dict[str, List[str]]:
        """Indexes all test files across the repository in a single pass (O(1) lookup)."""
        test_index: Dict[str, List[str]] = defaultdict(list)
        for scan_target in (root / "tests", root / "__tests__", root / "src"):
            index_test_dir(
                test_index,
                scan_target,
                root,
                self.DEFAULT_EXCLUDES,
                self.ext_map,
                self.GENERIC_STEMS,
            )
        return test_index

    def _analyze_file_into_summary(
        self,
        filepath: Path,
        root: Path,
        target_dir: Path,
        test_index: Dict[str, List[str]],
        summary: AuditSummary,
    ) -> None:
        summary.total_files += 1
        adapter = self.ext_map.get(filepath.suffix.lower())
        if not adapter or adapter.is_test_file(filepath):
            return
        content = read_text_safely(filepath)
        if content is None:
            return
        try:
            rel_path = str(filepath.relative_to(root))
        except ValueError:
            rel_path = str(filepath.relative_to(target_dir))
        file_metric = HealthScorer.score_file(
            adapter.analyze(
                path=filepath,
                rel_path=rel_path,
                content=content,
                workspace_root=root,
                test_index=test_index,
            )
        )
        summary.analyzed_files += 1
        summary.total_lines += file_metric.total_lines
        summary.total_sloc += file_metric.sloc
        summary.total_comments += file_metric.comment_lines
        summary.file_results.append(file_metric)

    def scan(self, target_dir: Path, scoped_files: Optional[List[str]] = None) -> AuditSummary:
        """Scans target_dir (or scoped_files) and returns scored AuditSummary."""
        if not target_dir.exists():
            raise FileNotFoundError(f"Target directory not found: {target_dir}")

        root = self.workspace_root or (
            target_dir.parent if target_dir.name in ("src", "lib") else target_dir
        )
        summary = AuditSummary(target_path=target_dir)
        test_index = self._build_test_index(root)

        if scoped_files is not None:
            resolved = (resolve_scoped_path(e, root, target_dir) for e in scoped_files)
            candidates = (p for p in resolved if p is not None)
        else:
            candidates = iter_unignored_files(target_dir, self.DEFAULT_EXCLUDES)

        for filepath in candidates:
            self._analyze_file_into_summary(
                filepath, root, target_dir, test_index, summary
            )

        return HealthScorer.calculate_summary(summary)
