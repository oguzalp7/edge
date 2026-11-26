"""UI Component Graph Builder: DAG of TSX components, orphans, and dead imports."""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .graph_parser import extract_exports, extract_imports, relativize_src_path, resolve_import_path
from .models import ComponentImport, ComponentNode


def _link_imports_for_file(file_path: Path, root_dir: Path, src_dir: Path, nodes: Dict[str, ComponentNode]) -> None:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return
    rel_path = relativize_src_path(file_path, root_dir, src_dir) or file_path.name
    for imp in extract_imports(content):
        resolved_rel = resolve_import_path(file_path, imp.source_str, root_dir, src_dir)
        if resolved_rel and resolved_rel in nodes and rel_path not in nodes[resolved_rel].incoming_references:
            nodes[resolved_rel].incoming_references.append(rel_path)


class GraphBuilder:
    """Builds the component import graph across src/app, src/components, src/lib, and src/hooks."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.src_dir = (root_dir / "src") if (root_dir / "src").is_dir() else root_dir
        self.nodes: Dict[str, ComponentNode] = {}

    def scan_files(self) -> List[Path]:
        """Collect all .tsx files inside app/ and components/ directories."""
        from tools.common.profiles import is_stack_gate_enabled, resolve_active_profiles

        profiles = resolve_active_profiles(self.root_dir)
        if profiles.source in ("explicit", "explicit_none") and not is_stack_gate_enabled(profiles, "zero_wrappers"):
            return []
        tsx_files: List[Path] = []
        for base in (self.src_dir / "app", self.src_dir / "components"):
            if base.exists():
                tsx_files.extend(p for p in base.rglob("*.tsx") if ".test." not in p.name and ".spec." not in p.name)
        return tsx_files

    def _extract_exports(self, content: str, default_name: str) -> List[str]:
        return extract_exports(content, default_name)

    def _extract_imports(self, content: str) -> List[ComponentImport]:
        return extract_imports(content)

    def _resolve_import_path(self, current_file: Path, source_str: str) -> Optional[str]:
        return resolve_import_path(current_file, source_str, self.root_dir, self.src_dir)

    def _link_node_imports(self, rel_path: str, node: ComponentNode) -> None:
        for imp in node.imports:
            resolved_rel = self._resolve_import_path(node.file_path, imp.source_str)
            if not resolved_rel or resolved_rel not in self.nodes:
                continue
            imp.resolved_file = resolved_rel
            refs = self.nodes[resolved_rel].incoming_references
            if rel_path not in refs:
                refs.append(rel_path)

    def _scan_extra_dir(self, base: Path) -> None:
        if not base.exists():
            return
        for p in base.rglob("*"):
            if p.is_file() and p.suffix in (".ts", ".tsx") and not p.name.endswith((".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")):
                _link_imports_for_file(p, self.root_dir, self.src_dir, self.nodes)

    def build_graph(self) -> Dict[str, ComponentNode]:
        """Parse TSX files and construct bidirectional component dependency graph."""
        self.nodes = {node.rel_path: node for node in (self._parse_file(f) for f in self.scan_files())}
        for rel_path, node in self.nodes.items():
            self._link_node_imports(rel_path, node)
        for base in (self.src_dir / "lib", self.src_dir / "hooks"):
            self._scan_extra_dir(base)
        return self.nodes

    def _parse_file(self, file_path: Path) -> ComponentNode:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""
        rel_path = relativize_src_path(file_path, self.root_dir, self.src_dir) or file_path.name
        sloc = sum(1 for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("//"))
        return ComponentNode(
            file_path=file_path, rel_path=rel_path, sloc=sloc,
            is_app_route=rel_path.startswith("app/") or "/app/" in rel_path,
            is_component=rel_path.startswith("components/") or "/components/" in rel_path,
            exported_symbols=extract_exports(content, file_path.stem),
            imports=extract_imports(content), raw_content=content,
        )

    def find_orphans(self) -> List[ComponentNode]:
        """Return all unreferenced component nodes sorted by relative path."""
        return sorted((n for n in self.nodes.values() if n.is_orphan), key=lambda n: n.rel_path)

    def find_all_dead_imports(self) -> List[Tuple[str, str, str]]:
        """Return (file_rel_path, dead_symbol, source_path) across all nodes."""
        return [(rel, sym, imp.source_str) for rel, node in self.nodes.items() for imp in node.imports for sym in imp.dead_symbols]
