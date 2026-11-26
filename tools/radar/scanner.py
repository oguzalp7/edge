"""RadarScanner Facade for Core and UI debt scanning."""

from pathlib import Path
from typing import List, Optional

from .models import LedgerItem
from .scanner_core import scan_core_findings
from .scanner_ui import scan_ui_findings


class RadarScanner:
    """Scans core backend and UI frontend tracks for Edge debt items."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def scan_core(self, file_paths: Optional[List[str]] = None) -> List[LedgerItem]:
        """Scan backend actions and core logic files for architectural smells."""
        return scan_core_findings(self.repo_path, file_paths=file_paths)

    def scan_ui(self, file_paths: Optional[List[str]] = None, include_mechanical: bool = False) -> List[LedgerItem]:
        """Scan frontend components, JSX duplication clusters, and UI hygiene rules."""
        return scan_ui_findings(self.repo_path, file_paths=file_paths, include_mechanical=include_mechanical)
