"""
DRYER: Tree-Sitter Structural AST Clone and Duplication Detector.
"""

import hashlib
import itertools
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

try:
    import tree_sitter
    import tree_sitter_language_pack as tslp
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

from tools.audit.dryer_ast import (
    IGNORED_NODE_TYPES,
    LITERAL_NODE_TYPES,
    AstUnit,
    CloneCluster,
    ClonePair,
    _count_ast_nodes,
    _extract_shingles,
    extract_units_from_tree,
    jaccard_similarity,
    normalize_ast,
)

_SUPPORTED_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py"}
_IGNORED_SUBSTRINGS = (".test.", ".spec.", "node_modules", ".venv", ".git", "dist", ".next", "build")


def _collect_scan_files(target_path: Union[Path, str], scoped_files: Optional[List[str]]) -> List[Path]:
    path = Path(target_path)
    if path.is_file():
        files = [path]
    elif path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTS and not any(ign in str(p) for ign in _IGNORED_SUBSTRINGS)]
    else:
        files = []
    if scoped_files is None:
        return files
    scoped_set = {str(Path(sf)) for sf in scoped_files}
    return [f for f in files if str(f) in scoped_set or f.name in scoped_set]


def _bfs_component(start: str, adj: Dict[str, Set[str]], visited: Set[str]) -> List[str]:
    comp, queue = [], [start]
    visited.add(start)
    while queue:
        curr = queue.pop(0)
        comp.append(curr)
        for nb in adj.get(curr, set()):
            if nb not in visited:
                visited.add(nb)
                queue.append(nb)
    return comp


def _cluster_max_score(comp: List[str], pair_scores: Dict[Tuple[str, str], float]) -> float:
    keys = ((min(a, b), max(a, b)) for a, b in itertools.combinations(comp, 2))
    return max((pair_scores[k] for k in keys if k in pair_scores), default=0.0)


class DryerScanner:
    """Structural clone and duplicate detector using Tree-Sitter ASTs."""

    def __init__(self, threshold: float = 0.82, min_lines: int = 5, min_nodes: int = 20):
        self.threshold = threshold
        self.min_lines = min_lines
        self.min_nodes = min_nodes

    def _get_parser_for_ext(self, ext: str):
        if not TREE_SITTER_AVAILABLE:
            return None, None
        mapping = {".ts": "typescript", ".tsx": "tsx", ".jsx": "tsx", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".py": "python"}
        lang = mapping.get(ext.lower())
        return (tslp.get_parser(lang), lang) if lang else (None, None)

    def _extract_units_from_source(self, file_path: str, source_bytes: bytes, lang: str) -> List[AstUnit]:
        if not TREE_SITTER_AVAILABLE:
            return []
        parser, _ = self._get_parser_for_ext(Path(file_path).suffix)
        if not parser:
            return []
        return extract_units_from_tree(parser.parse(source_bytes).root_node, file_path, source_bytes, self.min_lines, self.min_nodes)

    def _collect_file_units(self, f: Path) -> Tuple[Optional[str], List[AstUnit]]:
        try:
            _, lang = self._get_parser_for_ext(f.suffix)
            if not lang:
                return None, []
            return lang, self._extract_units_from_source(str(f), f.read_bytes(), lang)
        except Exception:
            return None, []

    def _pair_if_clone(self, u_a: AstUnit, u_b: AstUnit, unit_langs: Dict[str, str]) -> Optional[ClonePair]:
        if (u_a.file_path, u_a.symbol, u_a.start_line) == (u_b.file_path, u_b.symbol, u_b.start_line):
            return None
        score = jaccard_similarity(u_a.fingerprints, u_b.fingerprints)
        if score < self.threshold:
            return None
        lang = unit_langs.get(f"{u_a.file_path}:{u_a.symbol}:{u_a.start_line}", "unknown")
        return ClonePair(score=score, language=lang, left=u_a, right=u_b)

    def scan_path(self, target_path: Union[Path, str], scoped_files: Optional[List[str]] = None) -> List[ClonePair]:
        """Scans a file or directory for structural AST clones."""
        if not TREE_SITTER_AVAILABLE:
            sys.stderr.write("⚠️ tree-sitter or tree-sitter-language-pack not found. Run with 'uv run --with tree-sitter --with tree-sitter-language-pack' to enable AST clone detection.\n")
            return []

        all_units: List[AstUnit] = []
        unit_langs: Dict[str, str] = {}
        for f in _collect_scan_files(target_path, scoped_files):
            lang, units = self._collect_file_units(f)
            if not lang:
                continue
            all_units.extend(units)
            for u in units:
                unit_langs[f"{u.file_path}:{u.symbol}:{u.start_line}"] = lang

        pairs = [
            pair
            for u_a, u_b in itertools.combinations(all_units, 2)
            if (pair := self._pair_if_clone(u_a, u_b, unit_langs)) is not None
        ]
        pairs.sort(key=lambda p: p.score, reverse=True)
        return pairs

    def cluster_clones(self, pairs: List[ClonePair]) -> List[CloneCluster]:
        """Groups clone pairs into connected equivalence clusters."""
        if not pairs:
            return []
        unit_by_uid: Dict[str, AstUnit] = {}
        adj: Dict[str, Set[str]] = {}
        pair_scores: Dict[Tuple[str, str], float] = {}

        for p in pairs:
            uid_l = f"{p.left.file_path}::{p.left.symbol}::{p.left.start_line}"
            uid_r = f"{p.right.file_path}::{p.right.symbol}::{p.right.start_line}"
            unit_by_uid[uid_l], unit_by_uid[uid_r] = p.left, p.right
            adj.setdefault(uid_l, set()).add(uid_r)
            adj.setdefault(uid_r, set()).add(uid_l)
            pair_scores[(min(uid_l, uid_r), max(uid_l, uid_r))] = p.score

        visited: Set[str] = set()
        clusters: List[CloneCluster] = []
        for uid in list(adj.keys()):
            if uid in visited:
                continue
            comp = _bfs_component(uid, adj, visited)
            members = [unit_by_uid[nid] for nid in comp]
            cid = f"CLONE-{hashlib.sha256(':'.join(sorted(m.symbol for m in members)).encode('utf-8')).hexdigest()[:8]}"
            clusters.append(CloneCluster(cid, members, sorted({Path(m.file_path).name for m in members}), _cluster_max_score(comp, pair_scores)))
        return clusters
