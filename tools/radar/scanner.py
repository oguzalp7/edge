import re
from pathlib import Path
from typing import List, Dict, Any, Optional

from tools.audit.scanner import FileScanner
from tools.ui_audit.graph_builder import GraphBuilder
from tools.ui_audit.jsx_fingerprint import JSXFingerprinter
from tools.ui_audit.cluster_engine import ClusterEngine
from tools.rules import (
    RAW_TH_PATTERN,
    CANONICAL_ARRAY_PATTERN,
    SQL_LEAK_PATTERN,
    SHALLOW_WRAPPER_PATTERN,
)
from .models import LedgerItem, Track, FindingStatus, FindingSeverity


class RadarScanner:
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    # =========================================================================
    # CORE / BACKEND SCANNER
    # =========================================================================
    def scan_core(self, file_paths: Optional[List[str]] = None) -> List[LedgerItem]:
        """Scans backend actions and core logic files for architectural smells."""
        scanner = FileScanner()
        target_dir = self.repo_path / "src"
        if not target_dir.exists():
            return []

        # If scoped and empty list, return immediately
        if file_paths is not None and len(file_paths) == 0:
            return []

        summary = scanner.scan(target_dir, scoped_files=file_paths)
        findings: List[LedgerItem] = []

        for fmetric in summary.file_results:
            rel = fmetric.rel_path
            # Normalize path
            if rel.startswith("./"):
                rel = rel[2:]

            # Scoping filter
            if file_paths is not None and rel not in file_paths:
                continue

            # 1. Action Layer DB / SQL Leak (Rule from coding_standards.md)
            if rel.startswith("src/actions/") or rel.startswith("actions/"):
                try:
                    content = fmetric.path.read_text(encoding="utf-8", errors="replace")
                    for line_idx, line in enumerate(content.splitlines(), start=1):
                        if SQL_LEAK_PATTERN.search(line):
                            fp = LedgerItem.generate_fingerprint(
                                "RULE-ACTION-DB-LEAK",
                                rel,
                                symbol="db_call",
                                signature=str(line_idx)
                            )
                            findings.append(LedgerItem(
                                fingerprint=fp,
                                track=Track.CORE.value,
                                rule_id="RULE-ACTION-DB-LEAK",
                                title=f"Raw SQL/DB operation in Server Action ({rel}:{line_idx})",
                                file_path=rel,
                                line_number=line_idx,
                                symbol="db_call",
                                severity=FindingSeverity.CRITICAL.value,
                                status=FindingStatus.OPEN.value,
                                details={"code_line": line.strip()},
                                suggested_fix="Extract database transaction into domain repository under src/lib/<domain>/repository.ts.",
                                first_seen_at="",
                                last_seen_at="",
                            ))
                            break  # 1 finding per action file
                except (OSError, UnicodeDecodeError):
                    pass

            # 2. Arrow Anti-Pattern: Deep Nesting (> 5 levels)
            if fmetric.max_indent_level > 5:
                fp = LedgerItem.generate_fingerprint("RULE-DEEP-NESTING", rel, str(fmetric.max_indent_level))
                findings.append(LedgerItem(
                    fingerprint=fp,
                    track=Track.CORE.value,
                    rule_id="RULE-DEEP-NESTING",
                    title=f"Arrow Anti-Pattern: Deep indentation ({fmetric.max_indent_level} levels) in {rel}",
                    file_path=rel,
                    line_number=1,
                    symbol=None,
                    severity=FindingSeverity.WARNING.value,
                    status=FindingStatus.OPEN.value,
                    details={"max_indent": fmetric.max_indent_level, "sloc": fmetric.sloc},
                    suggested_fix="Flatten nested callbacks/conditions using early returns, guard clauses, or reducer extraction.",
                    first_seen_at="",
                    last_seen_at="",
                ))

            # 3. God Functions / Fat Actions (> 80 SLOC for actions, > 60 for core functions)
            for fn in fmetric.functions:
                limit = 80 if "action" in rel else 60
                if fn.sloc > limit:
                    fp = LedgerItem.generate_fingerprint("RULE-FAT-FUNCTION", rel, fn.name)
                    findings.append(LedgerItem(
                        fingerprint=fp,
                        track=Track.CORE.value,
                        rule_id="RULE-FAT-FUNCTION",
                        title=f"Fat Function: '{fn.name}' has {fn.sloc} SLOC (limit: {limit}) in {rel}",
                        file_path=rel,
                        line_number=fn.start_line,
                        symbol=fn.name,
                        severity=FindingSeverity.WARNING.value,
                        status=FindingStatus.OPEN.value,
                        details={"sloc": fn.sloc, "complexity": fn.complexity},
                        suggested_fix="Decompose into pure helper functions or delegate business calculation to src/core.",
                        first_seen_at="",
                        last_seen_at="",
                    ))

            # 4. Missing Test Seam in Domain Core (Exclude types, definitions, and examples)
            is_type_or_example = (
                rel.endswith("types.ts")
                or rel.endswith(".d.ts")
                or "/examples/" in rel
                or rel.endswith("index.ts")
            )
            if rel.startswith("src/core/") and not is_type_or_example and not fmetric.has_test_seam and fmetric.sloc > 40:
                fp = LedgerItem.generate_fingerprint("RULE-MISSING-TEST-SEAM", rel)
                findings.append(LedgerItem(
                    fingerprint=fp,
                    track=Track.CORE.value,
                    rule_id="RULE-MISSING-TEST-SEAM",
                    title=f"Untested Core Domain Module: {rel} ({fmetric.sloc} SLOC)",
                    file_path=rel,
                    line_number=1,
                    symbol=None,
                    severity=FindingSeverity.CRITICAL.value,
                    status=FindingStatus.OPEN.value,
                    details={"sloc": fmetric.sloc},
                    suggested_fix="Add companion in-memory unit tests under tests/unit/ to guarantee hermetic domain verification.",
                    first_seen_at="",
                    last_seen_at="",
                ))

        return findings

    # =========================================================================
    # UI / FRONTEND SCANNER
    # =========================================================================
    def scan_ui(self, file_paths: Optional[List[str]] = None) -> List[LedgerItem]:
        """Scans frontend components, JSX duplication clusters, and magic headers."""
        findings: List[LedgerItem] = []
        target_dir = self.repo_path / "src"
        if not target_dir.exists():
            return []

        # If scoped and empty list, return immediately
        if file_paths is not None and len(file_paths) == 0:
            return []

        # 1. Build Component Graph (Orphans & Dead Imports)
        graph_builder = GraphBuilder(self.repo_path)
        nodes = graph_builder.build_graph()

        orphans = graph_builder.find_orphans()
        dead_imports = graph_builder.find_all_dead_imports()

        for orphan in orphans:
            rel = orphan.rel_path
            if file_paths is not None and rel not in file_paths:
                continue
            fp = LedgerItem.generate_fingerprint("RULE-ORPHAN-COMPONENT", rel)
            findings.append(LedgerItem(
                fingerprint=fp,
                track=Track.UI.value,
                rule_id="RULE-ORPHAN-COMPONENT",
                title=f"Orphan Component: '{rel}' (0 incoming references, {orphan.sloc} SLOC)",
                file_path=rel,
                line_number=1,
                symbol=None,
                severity=FindingSeverity.ADVISORY.value,
                status=FindingStatus.OPEN.value,
                details={"sloc": orphan.sloc},
                suggested_fix="Delete unused component if obsolete, or connect to intended parent screen.",
                first_seen_at="",
                last_seen_at="",
            ))

        for rel, dead_sym, imp_src in dead_imports:
            if file_paths is not None and rel not in file_paths:
                continue
            fp = LedgerItem.generate_fingerprint("RULE-DEAD-IMPORT", rel, dead_sym)
            findings.append(LedgerItem(
                fingerprint=fp,
                track=Track.UI.value,
                rule_id="RULE-DEAD-IMPORT",
                title=f"Dead Symbol Import: '{dead_sym}' from '{imp_src}' in {rel}",
                file_path=rel,
                line_number=1,
                symbol=dead_sym,
                severity=FindingSeverity.ADVISORY.value,
                status=FindingStatus.OPEN.value,
                details={"source": imp_src, "symbol": dead_sym},
                suggested_fix="Remove unused import to reduce module bundle size.",
                first_seen_at="",
                last_seen_at="",
            ))

        # 2. JSX Duplication Clustering
        fingerprinter = JSXFingerprinter()
        all_patterns = []
        for rel_path, node in nodes.items():
            patterns = fingerprinter.scan_file(node.file_path, node.rel_path)
            all_patterns.extend(patterns)

        cluster_engine = ClusterEngine()
        clusters = cluster_engine.cluster_patterns(all_patterns, min_instances=3)

        for cluster in clusters:
            # Scoping: if file_paths is specified, only include cluster if at least one file in cluster is in file_paths
            if file_paths is not None:
                if not any(f in file_paths for f in cluster.distinct_files):
                    continue

            fp = LedgerItem.generate_fingerprint("RULE-JSX-DUPLICATE-CLUSTER", cluster.category, cluster.signature)
            findings.append(LedgerItem(
                fingerprint=fp,
                track=Track.UI.value,
                rule_id="RULE-JSX-DUPLICATE-CLUSTER",
                title=f"JSX Duplicate Cluster: {cluster.count} instances of {cluster.category} across {len(cluster.distinct_files)} files",
                file_path=cluster.distinct_files[0],
                line_number=cluster.instances[0].line_number,
                symbol=cluster.category,
                severity=FindingSeverity.WARNING.value,
                status=FindingStatus.OPEN.value,
                details={
                    "category": cluster.category,
                    "count": cluster.count,
                    "files": cluster.distinct_files,
                    "estimated_sloc_saving": cluster.estimated_sloc_saving,
                    "suggested_primitive": cluster.suggested_primitive,
                },
                suggested_fix=f"Consolidate into centralized primitive '{cluster.suggested_primitive}' ({cluster.props_proposal}).",
                first_seen_at="",
                last_seen_at="",
            ))

        # 3. Magic String <th> Table Headers, Hardcoded Canonical Arrays & Shallow Wrappers
        components_dir = self.repo_path / "src" / "components"
        if components_dir.exists():
            for tsx in components_dir.rglob("*.tsx"):
                if ".test." in tsx.name:
                    continue
                rel = str(tsx.relative_to(self.repo_path)).replace("\\", "/")
                if file_paths is not None and rel not in file_paths:
                    continue
                try:
                    content = tsx.read_text(encoding="utf-8", errors="replace")
                    lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("//")]

                    # Check Shallow Wrapper
                    if len(lines) < 55 and SHALLOW_WRAPPER_PATTERN.search(content):
                        target_comp = SHALLOW_WRAPPER_PATTERN.search(content).group(1)
                        comp_name = tsx.stem
                        if comp_name != target_comp:
                            fp = LedgerItem.generate_fingerprint("RULE-SHALLOW-WRAPPER", rel, target_comp)
                            findings.append(LedgerItem(
                                fingerprint=fp,
                                track=Track.UI.value,
                                rule_id="RULE-SHALLOW-WRAPPER",
                                title=f"Shallow Wrapper Component: '{comp_name}' delegates to '{target_comp}' in {rel}",
                                file_path=rel,
                                line_number=1,
                                symbol=comp_name,
                                severity=FindingSeverity.CRITICAL.value,
                                status=FindingStatus.OPEN.value,
                                details={"target": target_comp},
                                suggested_fix="Delete shallow wrapper and migrate callers directly to the target primitive.",
                                first_seen_at="",
                                last_seen_at="",
                            ))

                    # Check Table Headers & Canonical Arrays
                    for line_idx, line in enumerate(content.splitlines(), start=1):
                        m = RAW_TH_PATTERN.search(line)
                        if m:
                            header_text = m.group(1).strip()
                            if not header_text.startswith("{"):
                                fp = LedgerItem.generate_fingerprint("RULE-MAGIC-TABLE-HEADER", rel, header_text)
                                findings.append(LedgerItem(
                                fingerprint=fp,
                                track=Track.UI.value,
                                rule_id="RULE-MAGIC-TABLE-HEADER",
                                title=f"Hardcoded raw <th> header '{header_text}' in {rel}:{line_idx}",
                                file_path=rel,
                                line_number=line_idx,
                                symbol=header_text,
                                severity=FindingSeverity.WARNING.value,
                                status=FindingStatus.OPEN.value,
                                details={"header_text": header_text},
                                suggested_fix="Derive table columns from schema metadata or central bilingual dictionary.",
                                first_seen_at="",
                                last_seen_at="",
                            ))
                            break  # 1 warning per table file
                        if CANONICAL_ARRAY_PATTERN.search(line):
                            fp = LedgerItem.generate_fingerprint("RULE-CANONICAL-IN-UI", rel, str(line_idx))
                            findings.append(LedgerItem(
                                fingerprint=fp,
                                track=Track.UI.value,
                                rule_id="RULE-CANONICAL-IN-UI",
                                title=f"Hardcoded CANONICAL array in UI component ({rel}:{line_idx})",
                                file_path=rel,
                                line_number=line_idx,
                                symbol="CANONICAL",
                                severity=FindingSeverity.CRITICAL.value,
                                status=FindingStatus.OPEN.value,
                                details={"code_line": line.strip()},
                                suggested_fix="Move canonical business data to DB schema or domain configuration; UI must remain dynamic.",
                                first_seen_at="",
                                last_seen_at="",
                            ))
                except (OSError, UnicodeDecodeError):
                    pass

        return findings
