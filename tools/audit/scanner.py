import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Set
from collections import defaultdict
from .base_adapter import LanguageAdapter
from .adapters.typescript import TypeScriptAdapter
from .adapters.python import PythonAdapter
from .models import FileMetrics, AuditSummary
from .scorer import HealthScorer

class FileScanner:
    DEFAULT_EXCLUDES = {
        "node_modules", ".git", ".next", "dist", "build", ".scratch",
        "coverage", ".archive", ".vscode", "public", ".npm", "__pycache__",
        ".pytest_cache", ".venv", "venv", ".idea", ".staging", "scratch"
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
        if sys.platform == "win32" and path_str.startswith("/home/"):
            win_wsl_path = "\\\\wsl.localhost\\Ubuntu-24.04" + path_str.replace("/", "\\")
            p = Path(win_wsl_path)
            if p.exists():
                return p
        return Path(path_str).resolve()

    def _build_test_index(self, root: Path) -> Dict[str, List[str]]:
        """Indexes all test files across the repository in a single pass (O(1) lookup)."""
        test_index = defaultdict(list)
        for scan_target in [root / "tests", root / "__tests__", root / "src"]:
            if not scan_target.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(scan_target):
                dirnames[:] = [d for d in dirnames if d not in self.DEFAULT_EXCLUDES and not d.startswith(".")]
                for filename in filenames:
                    filepath = Path(dirpath) / filename
                    ext = filepath.suffix.lower()
                    adapter = self.ext_map.get(ext)
                    if adapter and adapter.is_test_file(filepath):
                        clean_stem = filepath.name.lower()
                        for strip_term in [".test", ".spec", "_test"]:
                            clean_stem = clean_stem.replace(strip_term, "")
                        clean_stem = Path(clean_stem).stem
                        
                        try:
                            rel_p = str(filepath.relative_to(root))
                        except ValueError:
                            rel_p = str(filepath)
                            
                        test_index[clean_stem].append(rel_p)
                        test_index[filepath.stem.lower()].append(rel_p)
        return test_index

    def scan(self, target_dir: Path) -> AuditSummary:
        if not target_dir.exists():
            raise FileNotFoundError(f"Target directory not found: {target_dir}")

        root = self.workspace_root or (target_dir.parent if target_dir.name in ("src", "lib") else target_dir)
        summary = AuditSummary(target_path=target_dir)

        test_index = self._build_test_index(root)

        for dirpath, dirnames, filenames in os.walk(target_dir):
            dirnames[:] = [d for d in dirnames if d not in self.DEFAULT_EXCLUDES and not d.startswith(".")]

            for filename in filenames:
                summary.total_files += 1
                filepath = Path(dirpath) / filename
                ext = filepath.suffix.lower()

                adapter = self.ext_map.get(ext)
                if not adapter:
                    continue

                if adapter.is_test_file(filepath):
                    continue

                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except Exception:
                    continue

                try:
                    rel_path = str(filepath.relative_to(root))
                except ValueError:
                    rel_path = str(filepath.relative_to(target_dir))

                file_metric = adapter.analyze(
                    path=filepath,
                    rel_path=rel_path,
                    content=content,
                    workspace_root=root,
                    test_index=test_index
                )

                file_metric = HealthScorer.score_file(file_metric)

                summary.analyzed_files += 1
                summary.total_lines += file_metric.total_lines
                summary.total_sloc += file_metric.sloc
                summary.total_comments += file_metric.comment_lines
                summary.file_results.append(file_metric)

        return HealthScorer.calculate_summary(summary)
