"""
DRYER: Tree-Sitter Structural AST Clone and Duplication Detector.
Analyzes TypeScript, TSX, JavaScript, and Python code to discover structural
code clones using normalized AST subtree fingerprinting and Jaccard similarity.
"""

import sys
import os
import hashlib
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any, Dict, Set, Union

try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False


@dataclass
class AstUnit:
    file_path: str
    symbol: str
    kind: str  # "function" | "method" | "block" | "jsx"
    start_line: int
    end_line: int
    node_count: int
    fingerprints: frozenset[str]


@dataclass
class ClonePair:
    score: float
    language: str
    left: AstUnit
    right: AstUnit


@dataclass
class CloneCluster:
    cluster_id: str
    members: List[AstUnit]
    distinct_files: List[str]
    max_score: float


def jaccard_similarity(fp_a: frozenset[str], fp_b: frozenset[str]) -> float:
    """Computes Jaccard similarity between two fingerprint sets."""
    if not fp_a or not fp_b:
        return 0.0
    intersection = len(fp_a & fp_b)
    union = len(fp_a | fp_b)
    return round(float(intersection) / float(union), 4) if union > 0 else 0.0


# Node types ignored during normalization (comments, type annotations, modifiers)
IGNORED_NODE_TYPES = {
    "comment",
    "line_comment",
    "block_comment",
    "type_annotation",
    "type_arguments",
    "type_parameters",
    "return_type",
    "accessibility_modifier",
    "type",
}

# Literal node types mapped to "$LIT"
LITERAL_NODE_TYPES = {
    "string",
    "string_fragment",
    "template_string",
    "number",
    "integer",
    "float",
    "true",
    "false",
    "null",
    "undefined",
    "none",
}


def _is_callee(node: Any) -> bool:
    """Checks if an identifier or member expression is the callee of a call expression."""
    parent = node.parent
    if not parent:
        return False
    if parent.type in ("call_expression", "call"):
        fn_child = parent.child_by_field_name("function")
        if fn_child and fn_child.id == node.id:
            return True
    if parent.type in ("member_expression", "attribute"):
        prop_child = parent.child_by_field_name("property") or parent.child_by_field_name("attribute")
        if prop_child and prop_child.id == node.id:
            grandparent = parent.parent
            if grandparent and grandparent.type in ("call_expression", "call"):
                return True
    return False


def _is_jsx_tag(node: Any) -> bool:
    """Checks if a node is the tag name in a JSX element."""
    parent = node.parent
    if not parent:
        return False
    if parent.type in ("jsx_opening_element", "jsx_self_closing_element", "jsx_closing_element"):
        name_child = parent.child_by_field_name("name")
        if name_child and (name_child.id == node.id or (node.parent and node.parent.id == name_child.id)):
            return True
        if node.type in ("jsx_identifier", "identifier"):
            return True
    return False


def normalize_ast(node: Any, source_bytes: bytes) -> Optional[Tuple[Any, ...]]:
    """
    Normalizes a tree-sitter node into an immutable structural tuple.
    Preserves call names, JSX tags, and operators; abstracts identifiers and literals.
    """
    if node is None or node.type in IGNORED_NODE_TYPES:
        return None

    # Check for JSX tag preservation
    if _is_jsx_tag(node):
        tag_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
        return ("JSX_TAG", tag_text)

    # Check for callee / method call preservation
    if _is_callee(node) and node.type in ("identifier", "property_identifier"):
        callee_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")
        return ("CALLEE", callee_text)

    # Literals
    if node.type in LITERAL_NODE_TYPES:
        return ("$LIT",)

    # Identifiers (non-callee, non-tag)
    if node.type in ("identifier", "property_identifier", "shorthand_property_identifier"):
        return ("$ID",)

    # Operators & punctuation preserved
    if len(node.children) == 0:
        token_text = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="ignore").strip()
        if token_text in ("+", "-", "*", "/", "%", "&&", "||", "===", "!==", "==", "!=", "<", ">", "<=", ">=", "??", "=", "+=", "-="):
            return ("OP", token_text)
        return (node.type,)

    # Composite node: recursively normalize children
    normalized_children = []
    for child in node.children:
        norm_child = normalize_ast(child, source_bytes)
        if norm_child is not None:
            normalized_children.append(norm_child)

    return (node.type, *normalized_children)


def _extract_shingles(norm_tree: Tuple[Any, ...], depth_limit: int = 3) -> Set[str]:
    """Generates subtree structural shingles from a normalized AST tuple."""
    shingles: Set[str] = set()

    def _traverse(sub: Any, path: List[str]):
        if not isinstance(sub, tuple) or not sub:
            return
        head = str(sub[0])
        current_path = path + [head]

        # Record 1-hop, 2-hop, 3-hop paths
        for k in range(1, min(depth_limit + 1, len(current_path) + 1)):
            shingles.add("->".join(current_path[-k:]))

        # Record local signature of node and its direct child types
        children = sub[1:]
        child_types = [str(c[0]) if isinstance(c, tuple) and c else str(c) for c in children]
        if child_types:
            shingles.add(f"{head}({','.join(child_types)})")

        for c in children:
            if isinstance(c, tuple):
                _traverse(c, current_path)

    _traverse(norm_tree, [])
    return shingles


def _count_ast_nodes(node: Any) -> int:
    """Counts total non-comment AST nodes."""
    count = 1
    for child in node.children:
        if child.type not in IGNORED_NODE_TYPES:
            count += _count_ast_nodes(child)
    return count


class DryerScanner:
    """
    Structural clone and duplicate detector using Tree-Sitter ASTs.
    """
    def __init__(self, threshold: float = 0.82, min_lines: int = 5, min_nodes: int = 20):
        self.threshold = threshold
        self.min_lines = min_lines
        self.min_nodes = min_nodes

    def _get_parser_for_ext(self, ext: str):
        if not TREE_SITTER_AVAILABLE:
            return None
        ext = ext.lower()
        if ext in (".ts",):
            return tslp.get_parser("typescript"), "typescript"
        elif ext in (".tsx", ".jsx"):
            return tslp.get_parser("tsx"), "tsx"
        elif ext in (".js", ".mjs", ".cjs"):
            return tslp.get_parser("javascript"), "javascript"
        elif ext in (".py",):
            return tslp.get_parser("python"), "python"
        return None, None

    def _extract_units_from_source(self, file_path: str, source_bytes: bytes, lang: str) -> List[AstUnit]:
        if not TREE_SITTER_AVAILABLE:
            return []

        parser, _ = self._get_parser_for_ext(Path(file_path).suffix)
        if not parser:
            return []

        tree = parser.parse(source_bytes)
        root = tree.root_node

        target_node_types = {
            "function_declaration",
            "function_definition",
            "arrow_function",
            "method_definition",
            "function_expression",
        }

        units: List[AstUnit] = []

        def _find_symbol(node: Any) -> str:
            # Check direct identifier child
            name_node = node.child_by_field_name("name")
            if name_node:
                return source_bytes[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="ignore")
            # Check parent variable declarator: const foo = () => ...
            p = node.parent
            if p and p.type == "variable_declarator":
                var_name = p.child_by_field_name("name")
                if var_name:
                    return source_bytes[var_name.start_byte:var_name.end_byte].decode("utf-8", errors="ignore")
            # For class methods
            for c in node.children:
                if c.type in ("identifier", "property_identifier"):
                    return source_bytes[c.start_byte:c.end_byte].decode("utf-8", errors="ignore")
            return f"anonymous_L{node.start_point[0] + 1}"

        def _visit(node: Any):
            if node.type in target_node_types:
                start_l = node.start_point[0] + 1
                end_l = node.end_point[0] + 1
                lines = end_l - start_l + 1
                node_cnt = _count_ast_nodes(node)

                if lines >= self.min_lines and node_cnt >= self.min_nodes:
                    symbol = _find_symbol(node)
                    norm = normalize_ast(node, source_bytes)
                    if norm:
                        shingles = _extract_shingles(norm)
                        kind = "method" if node.type == "method_definition" else "function"
                        units.append(AstUnit(
                            file_path=file_path,
                            symbol=symbol,
                            kind=kind,
                            start_line=start_l,
                            end_line=end_l,
                            node_count=node_cnt,
                            fingerprints=frozenset(shingles),
                        ))
                    return  # Do not extract inner functions if outer was captured

            for child in node.children:
                _visit(child)

        _visit(root)
        return units

    def scan_path(self, target_path: Union[Path, str], scoped_files: Optional[List[str]] = None) -> List[ClonePair]:
        """Scans a file or directory for structural AST clones."""
        if not TREE_SITTER_AVAILABLE:
            sys.stderr.write(
                "⚠️ tree-sitter or tree-sitter-language-pack not found. "
                "Run with 'uv run --with tree-sitter --with tree-sitter-language-pack' to enable AST clone detection.\n"
            )
            return []

        path = Path(target_path)
        supported_exts = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py"}
        ignored_substrings = [".test.", ".spec.", "node_modules", ".venv", ".git", "dist", ".next", "build"]

        files_to_scan = []
        if path.is_file():
            files_to_scan = [path]
        elif path.is_dir():
            for p in path.rglob("*"):
                if p.is_file() and p.suffix.lower() in supported_exts:
                    p_str = str(p)
                    if not any(ign in p_str for ign in ignored_substrings):
                        files_to_scan.append(p)

        if scoped_files is not None:
            scoped_set = {str(Path(sf)) for sf in scoped_files}
            files_to_scan = [f for f in files_to_scan if str(f) in scoped_set or f.name in scoped_set]

        all_units: List[AstUnit] = []
        unit_langs: Dict[str, str] = {}
        for f in files_to_scan:
            try:
                src_bytes = f.read_bytes()
                _, lang = self._get_parser_for_ext(f.suffix)
                if lang:
                    units = self._extract_units_from_source(str(f), src_bytes, lang)
                    all_units.extend(units)
                    for u in units:
                        unit_langs[f"{u.file_path}:{u.symbol}:{u.start_line}"] = lang
            except Exception:
                continue

        # Compare pairs
        pairs: List[ClonePair] = []
        n = len(all_units)
        for i in range(n):
            for j in range(i + 1, n):
                u_a = all_units[i]
                u_b = all_units[j]

                # Avoid comparing the exact same function with itself
                if u_a.file_path == u_b.file_path and u_a.symbol == u_b.symbol and u_a.start_line == u_b.start_line:
                    continue

                score = jaccard_similarity(u_a.fingerprints, u_b.fingerprints)
                if score >= self.threshold:
                    lang = unit_langs.get(f"{u_a.file_path}:{u_a.symbol}:{u_a.start_line}", "unknown")
                    pairs.append(ClonePair(score=score, language=lang, left=u_a, right=u_b))

        # Sort descending by score
        pairs.sort(key=lambda p: p.score, reverse=True)
        return pairs

    def cluster_clones(self, pairs: List[ClonePair]) -> List[CloneCluster]:
        """
        Groups clone pairs into connected equivalence clusters using Disjoint Set Union (DSU).
        """
        if not pairs:
            return []

        # Map each unit to a unique ID
        def _uid(u: AstUnit) -> str:
            return f"{u.file_path}::{u.symbol}::{u.start_line}"

        unit_by_uid: Dict[str, AstUnit] = {}
        adj: Dict[str, Set[str]] = {}
        pair_scores: Dict[Tuple[str, str], float] = {}

        for p in pairs:
            uid_l = _uid(p.left)
            uid_r = _uid(p.right)
            unit_by_uid[uid_l] = p.left
            unit_by_uid[uid_r] = p.right

            adj.setdefault(uid_l, set()).add(uid_r)
            adj.setdefault(uid_r, set()).add(uid_l)

            pair_scores[(min(uid_l, uid_r), max(uid_l, uid_r))] = p.score

        # Find connected components via BFS
        visited: Set[str] = set()
        clusters: List[CloneCluster] = []

        for uid in list(adj.keys()):
            if uid in visited:
                continue

            comp: List[str] = []
            queue = [uid]
            visited.add(uid)

            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for neighbor in adj.get(curr, set()):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            members = [unit_by_uid[node_id] for node_id in comp]
            distinct_files = sorted(list({Path(m.file_path).name for m in members}))

            # Deterministic cluster ID from sorted member symbols
            sorted_symbols = sorted([m.symbol for m in members])
            hash_input = ":".join(sorted_symbols).encode("utf-8")
            cluster_hash = hashlib.sha256(hash_input).hexdigest()[:8]
            cluster_id = f"CLONE-{cluster_hash}"

            # Compute max score in this cluster
            max_s = 0.0
            for i in range(len(comp)):
                for j in range(i + 1, len(comp)):
                    k = (min(comp[i], comp[j]), max(comp[i], comp[j]))
                    if k in pair_scores:
                        max_s = max(max_s, pair_scores[k])

            clusters.append(CloneCluster(
                cluster_id=cluster_id,
                members=members,
                distinct_files=distinct_files,
                max_score=max_s,
            ))

        return clusters
