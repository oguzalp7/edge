from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Optional
from .models import FileMetrics

class LanguageAdapter(ABC):
    @property
    @abstractmethod
    def extensions(self) -> List[str]:
        """List of supported file extensions (e.g. ['.ts', '.tsx'])."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Name of the adapter (e.g. 'TypeScript/Next.js')."""
        pass

    @abstractmethod
    def is_test_file(self, path: Path) -> bool:
        """Determines if the given file is a test/spec file."""
        pass

    @abstractmethod
    def analyze(
        self,
        path: Path,
        rel_path: str,
        content: str,
        workspace_root: Path,
        test_index: Optional[Dict[str, List[str]]] = None
    ) -> FileMetrics:
        """Parses the file syntactically and calculates standard metrics."""
        pass
