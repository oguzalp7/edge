"""
UI Component Graph Builder
Constructs the Directed Acyclic Graph (DAG) of TSX components, maps exports to imports,
and identifies orphan (unreferenced) components and dead imports across src/app and src/components.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from .models import ComponentNode, ComponentImport


class GraphBuilder:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        # Determine src root: either root_dir is src, or it contains src
        if (root_dir / "src").is_dir():
            self.src_dir = root_dir / "src"
        else:
            self.src_dir = root_dir

        self.nodes: Dict[str, ComponentNode] = {}  # Normalized relative path -> ComponentNode

    def scan_files(self) -> List[Path]:
        """Collect all .tsx files inside app/ and components/ directories."""
        tsx_files: List[Path] = []
        target_dirs = [self.src_dir / "app", self.src_dir / "components"]
        
        for base in target_dirs:
            if not base.exists():
                continue
            for p in base.rglob("*.tsx"):
                if p.is_file() and not p.name.endswith(".test.tsx") and not p.name.endswith(".spec.tsx"):
                    tsx_files.append(p)
                    
        return sorted(tsx_files)

    def build_graph(self) -> Dict[str, ComponentNode]:
        """Parse all TSX files and build the full component dependency graph."""
        files = self.scan_files()

        # Step 1: Initial parsing of each file
        for file_path in files:
            node = self._parse_file(file_path)
            self.nodes[node.rel_path] = node

        # Step 2: Resolve imported files and link incoming references
        for rel_path, node in self.nodes.items():
            for imp in node.imports:
                resolved_rel = self._resolve_import_path(node.file_path, imp.source_str)
                if resolved_rel and resolved_rel in self.nodes:
                    imp.resolved_file = resolved_rel
                    # Add current node as incoming reference to target node
                    target_node = self.nodes[resolved_rel]
                    if rel_path not in target_node.incoming_references:
                        target_node.incoming_references.append(rel_path)

        # Step 3: Scan src/lib and src/hooks for outgoing references to components
        extra_dirs = [self.src_dir / "lib", self.src_dir / "hooks"]
        for base in extra_dirs:
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if (
                    p.is_file()
                    and p.suffix in (".ts", ".tsx")
                    and not p.name.endswith(".test.ts")
                    and not p.name.endswith(".test.tsx")
                    and not p.name.endswith(".spec.ts")
                    and not p.name.endswith(".spec.tsx")
                ):
                    try:
                        extra_content = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    extra_imports = self._extract_imports(extra_content)
                    for imp in extra_imports:
                        resolved_rel = self._resolve_import_path(p, imp.source_str)
                        if resolved_rel and resolved_rel in self.nodes:
                            try:
                                rel_path = p.relative_to(self.root_dir).as_posix()
                            except ValueError:
                                try:
                                    rel_path = p.relative_to(self.src_dir).as_posix()
                                    if not rel_path.startswith("src/"):
                                        rel_path = f"src/{rel_path}"
                                except ValueError:
                                    rel_path = p.name
                            target_node = self.nodes[resolved_rel]
                            if rel_path not in target_node.incoming_references:
                                target_node.incoming_references.append(rel_path)

        return self.nodes

    def _parse_file(self, file_path: Path) -> ComponentNode:
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            content = ""

        # Normalize relative path to root_dir (e.g., 'src/components/bookings/CalendarView.tsx')
        try:
            rel_path = file_path.relative_to(self.root_dir).as_posix()
        except ValueError:
            try:
                rel_path = file_path.relative_to(self.src_dir).as_posix()
                if not rel_path.startswith("src/"):
                    rel_path = f"src/{rel_path}"
            except ValueError:
                rel_path = file_path.name

        lines = content.splitlines()
        sloc = sum(1 for line in lines if line.strip() and not line.strip().startswith("//"))

        is_app = rel_path.startswith("app/") or "/app/" in rel_path
        is_comp = rel_path.startswith("components/") or "/components/" in rel_path

        # Extract exports
        exports = self._extract_exports(content, file_path.stem)

        # Extract imports and detect dead symbol imports
        imports = self._extract_imports(content)

        return ComponentNode(
            file_path=file_path,
            rel_path=rel_path,
            sloc=sloc,
            is_app_route=is_app,
            is_component=is_comp,
            exported_symbols=exports,
            imports=imports,
            raw_content=content
        )

    def _extract_exports(self, content: str, default_name: str) -> List[str]:
        exports = []
        # Named function/const exports
        # export function Foo, export const Foo = , export default function Foo
        named_matches = re.findall(
            r"export\s+(?:default\s+)?(?:function|const|class|let)\s+([A-Za-z0-9_]+)",
            content
        )
        exports.extend(named_matches)

        # export default Identifier;
        default_match = re.search(r"export\s+default\s+([A-Za-z0-9_]+)\s*;", content)
        if default_match:
            exports.append(default_match.group(1))
        elif "export default" in content:
            exports.append(default_name)

        return list(set(exports))

    def _extract_imports(self, content: str) -> List[ComponentImport]:
        """Extract import statements and detect symbols not used in the file body."""
        imports: List[ComponentImport] = []
        
        # Matches:
        # import Foo, { Bar, Baz as Qux } from 'source'
        # import type { ... } from 'source'
        import_stmt_pattern = re.compile(
            r"import\s+(?:type\s+)?(?:([A-Za-z0-9_]+)\s*,?\s*)?(?:\{([^}]+)\})?\s*from\s*['\"]([^'\"]+)['\"]",
            re.MULTILINE
        )

        # Remove import statements safely without eating non-import code in semicolon-free files
        body_content = re.sub(
            r"import\s+(?:type\s+)?(?:[\s\S]*?from\s+)?['\"][^'\"]+['\"]\s*;?",
            "",
            content
        )

        for match in import_stmt_pattern.finditer(content):
            default_sym = match.group(1)
            named_block = match.group(2)
            source_str = match.group(3)

            symbols: List[str] = []
            if default_sym:
                symbols.append(default_sym.strip())

            if named_block:
                for part in named_block.split(","):
                    p = part.strip()
                    if not p:
                        continue
                    # Handle 'as' alias: 'Foo as Bar' -> Bar is the local symbol
                    if " as " in p:
                        local_sym = p.split(" as ")[1].strip()
                    else:
                        local_sym = p.strip()
                    if local_sym:
                        symbols.append(local_sym)

            # Analyze usage in file body
            used_symbols = []
            dead_symbols = []
            for sym in symbols:
                # Word boundary check in body_content
                if re.search(rf"\b{re.escape(sym)}\b", body_content):
                    used_symbols.append(sym)
                else:
                    dead_symbols.append(sym)

            imports.append(ComponentImport(
                source_str=source_str,
                imported_symbols=symbols,
                used_symbols=used_symbols,
                dead_symbols=dead_symbols
            ))

        return imports

    def _resolve_import_path(self, current_file: Path, source_str: str) -> Optional[str]:
        """Resolves an import string (@/components/... or ../...) to a normalized relative path."""
        # We only care about internal imports
        target_path: Optional[Path] = None

        if source_str.startswith("@/"):
            # Maps to src/...
            subpath = source_str[2:]
            target_path = self.src_dir / subpath
        elif source_str.startswith("."):
            # Relative import
            target_path = (current_file.parent / source_str).resolve()
        else:
            return None

        # Check candidate extensions
        candidates = [
            target_path.with_suffix(".tsx"),
            target_path.with_suffix(".ts"),
            target_path / "index.tsx",
            target_path / "index.ts",
            target_path
        ]

        for cand in candidates:
            if cand.is_file():
                try:
                    return cand.relative_to(self.root_dir).as_posix()
                except ValueError:
                    try:
                        p = cand.relative_to(self.src_dir).as_posix()
                        return f"src/{p}" if not p.startswith("src/") else p
                    except ValueError:
                        return None

        return None

    def find_orphans(self) -> List[ComponentNode]:
        """Return all component nodes in src/components that have 0 incoming references."""
        orphans = []
        for rel_path, node in self.nodes.items():
            if node.is_orphan:
                # Filter out pure index/barrel re-export files unless they have nothing importing them
                orphans.append(node)
        return sorted(orphans, key=lambda n: n.rel_path)

    def find_all_dead_imports(self) -> List[Tuple[str, str, str]]:
        """Return (file_rel_path, dead_symbol, source_path) across all nodes."""
        dead_imports = []
        for rel_path, node in self.nodes.items():
            for imp in node.imports:
                for dead_sym in imp.dead_symbols:
                    dead_imports.append((rel_path, dead_sym, imp.source_str))
        return dead_imports
