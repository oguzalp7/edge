from pathlib import Path
from typing import List, Tuple, Optional
from collections import Counter
from tools.common.runner import run_command


class ChurnAnalyzer:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        return run_command(["git"] + args, cwd=self.repo_path)

    def get_churn_hotspots(self, since: str = "14.days", max_files: int = 25) -> List[Tuple[str, int]]:
        """
        Ranks files by git commit frequency over the last N days.
        Returns a list of (rel_file_path, commit_count).
        """
        code, stdout, stderr = self._run_git(["log", f"--since={since}", "--name-only", "--pretty=format:"])
        if code != 0:
            return []

        counts = Counter()
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Filter out non-code files and tests
            if not (line.endswith(".ts") or line.endswith(".tsx") or line.endswith(".js") or line.endswith(".jsx")):
                continue
            if ".test." in line or ".spec." in line or line.startswith("tests/"):
                continue
            counts[line] += 1

        return counts.most_common(max_files)

    def get_pr_changed_files(self, base_ref: str = "main") -> List[str]:
        """Returns files changed between base_ref and HEAD."""
        code, stdout, stderr = self._run_git(["diff", "--name-only", f"{base_ref}...HEAD"])
        if code != 0:
            # Fallback to HEAD~1
            code, stdout, stderr = self._run_git(["diff", "--name-only", "HEAD~1...HEAD"])
            if code != 0:
                return []

        files = []
        for line in stdout.splitlines():
            line = line.strip()
            if line and (line.endswith(".ts") or line.endswith(".tsx")):
                files.append(line)
        return files
