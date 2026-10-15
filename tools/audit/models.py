from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Dict, Any, Optional

class RiskCategory(str, Enum):
    CLEAN = "CLEAN"           # < 200 SLOC, low complexity
    ATTENTION = "ATTENTION"   # 200 - 350 SLOC, moderate complexity
    HOTSPOT = "HOTSPOT"       # > 350 SLOC or high complexity
    CRITICAL = "CRITICAL"     # > 500 SLOC, high complexity, missing tests

class IssueTag(str, Enum):
    GOD_FILE = "GOD_FILE"                     # Excessive lines of code (>400 SLOC)
    GOD_FUNCTION = "GOD_FUNCTION"             # Excessive function length (>50 SLOC)
    SHALLOW_MODULE = "SHALLOW_MODULE"         # Shallow module (excessive public exports, leaky internals)
    DEEP_NESTING = "DEEP_NESTING"             # Excessive indentation level (>=5)
    HIGH_COMPLEXITY = "HIGH_COMPLEXITY"       # High cyclomatic / branching complexity (>15)
    MISSING_TEST_SEAM = "MISSING_TEST_SEAM"   # Missing companion test seam
    UI_ACTION_MIXING = "UI_ACTION_MIXING"     # Mixing JSX UI with Server Actions / direct DB queries

@dataclass
class FunctionMetrics:
    name: str
    start_line: int
    end_line: int
    sloc: int
    complexity: int
    is_exported: bool = False

@dataclass
class FileMetrics:
    path: Path
    rel_path: str
    extension: str
    total_lines: int
    sloc: int
    comment_lines: int
    blank_lines: int
    complexity_score: int
    max_indent_level: int
    public_exports: int
    functions: List[FunctionMetrics] = field(default_factory=list)
    has_test_seam: bool = False
    companion_tests: List[str] = field(default_factory=list)
    risk_score: float = 0.0
    risk_category: RiskCategory = RiskCategory.CLEAN
    issue_tags: List[IssueTag] = field(default_factory=list)
    slicing_recommendations: List[str] = field(default_factory=list)

@dataclass
class AuditSummary:
    target_path: Path
    total_files: int = 0
    analyzed_files: int = 0
    total_lines: int = 0
    total_sloc: int = 0
    total_comments: int = 0
    critical_hotspots: int = 0
    attention_files: int = 0
    clean_files: int = 0
    overall_health_score: float = 100.0  # 0 to 100
    file_results: List[FileMetrics] = field(default_factory=list)
