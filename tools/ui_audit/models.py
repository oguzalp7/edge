"""
UI Audit Data Models
Defines typed data structures for TSX component graph, orphan analysis,
JSX structural duplication fingerprinting, and UI consolidation proposals.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Tuple


@dataclass
class ComponentImport:
    source_str: str
    imported_symbols: List[str]
    resolved_file: Optional[str] = None
    used_symbols: List[str] = field(default_factory=list)
    dead_symbols: List[str] = field(default_factory=list)


@dataclass
class ComponentNode:
    file_path: Path
    rel_path: str
    sloc: int
    is_app_route: bool
    is_component: bool
    exported_symbols: List[str] = field(default_factory=list)
    imports: List[ComponentImport] = field(default_factory=list)
    incoming_references: List[str] = field(default_factory=list)  # Files that import this component
    raw_content: str = ""

    @property
    def is_orphan(self) -> bool:
        """A component in src/components is an orphan if no app route or other component imports it."""
        if not self.is_component:
            return False
        # If it's a primitive or ui index, it might be an intentional library file, but we still report it
        return len(self.incoming_references) == 0


@dataclass
class JSXPattern:
    tag: str
    category: str  # 'modal', 'drawer', 'skeleton', 'button', 'badge', 'card', 'alert', 'table'
    file_path: str
    line_number: int
    class_string: str
    structural_classes: List[str]
    signature: str
    snippet: str


@dataclass
class DuplicateCluster:
    category: str
    signature: str
    instances: List[JSXPattern]
    count: int
    distinct_files: List[str]
    suggested_primitive: str
    props_proposal: str
    estimated_sloc_saving: int


@dataclass
class UIAuditSummary:
    target_path: str
    total_tsx_files: int
    total_sloc: int
    app_routes_count: int
    components_count: int
    orphan_components: List[ComponentNode]
    dead_imports: List[Tuple[str, str, str]]  # (file_rel_path, imported_symbol, import_source)
    clusters: List[DuplicateCluster]
    health_score: float

    @property
    def total_orphans(self) -> int:
        return len(self.orphan_components)

    @property
    def total_dead_imports(self) -> int:
        return len(self.dead_imports)

    @property
    def total_duplicated_jsx_blocks(self) -> int:
        return sum(c.count for c in self.clusters)
