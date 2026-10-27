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

        # Discover LCOV report for CRAP analysis
        lcov_records = {}
        try:
            from tools.audit.crapper import discover_existing_lcov, parse_lcov
            lcov_file = discover_existing_lcov(self.repo_path)
            if lcov_file:
                lcov_records = parse_lcov(lcov_file.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            pass

        for fmetric in summary.file_results:
            rel = fmetric.rel_path
            # Normalize path
            if rel.startswith("./"):
                rel = rel[2:]

            # Scoping filter
            if file_paths is not None and rel not in file_paths:
                continue

            # Look up LCOV data for file
            file_lcov = None
            if lcov_records:
                repo_rel = ""
                try:
                    repo_rel = str(fmetric.path.relative_to(self.repo_path)).replace("\\", "/")
                except Exception:
                    pass
                file_lcov = (
                    lcov_records.get(repo_rel)
                    or lcov_records.get(rel)
                    or lcov_records.get(fmetric.path.name)
                )
                if not file_lcov:
                    for lk, lrec in lcov_records.items():
                        if (repo_rel and (lk.endswith(repo_rel) or repo_rel.endswith(lk))) or \
                           (rel and (lk.endswith(rel) or rel.endswith(lk))) or \
                           lk.endswith(fmetric.path.name):
                            file_lcov = lrec
                            break

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

            # 3. God Functions / Fat Actions & CRAP Risk Engine
            for fn in fmetric.functions:
                limit = 80 if "action" in rel else 60

                # Compute CRAP if coverage data is available
                crap_score = None
                if file_lcov is not None:
                    try:
                        from tools.audit.crapper import function_coverage_from_lcov, compute_crap
                        cov = function_coverage_from_lcov(file_lcov, fn.start_line, fn.end_line)
                        crap_score = compute_crap(fn.complexity, cov)
                    except Exception:
                        crap_score = None

                # CRAP Critical Smell (RULE-HIGH-CRAP)
                if crap_score is not None and crap_score >= 30.0:
                    fp = LedgerItem.generate_fingerprint("RULE-HIGH-CRAP", rel, fn.name, str(round(crap_score, 1)))
                    findings.append(LedgerItem(
                        fingerprint=fp,
                        track=Track.CORE.value,
                        rule_id="RULE-HIGH-CRAP",
                        title=f"High Change Risk (CRAP {crap_score:.1f} >= 30.0): '{fn.name}' in {rel}",
                        file_path=rel,
                        line_number=fn.start_line,
                        symbol=fn.name,
                        severity=FindingSeverity.CRITICAL.value,
                        status=FindingStatus.OPEN.value,
                        details={"crap_score": crap_score, "complexity": fn.complexity, "sloc": fn.sloc},
                        suggested_fix="Break function into smaller units or write missing branch tests.",
                        first_seen_at="",
                        last_seen_at="",
                    ))

                # Fat Function check (suppressed if well-tested and CRAP < 15.0)
                if fn.sloc > limit:
                    is_crap_clean = (crap_score is not None and crap_score < 15.0)
                    if not is_crap_clean:
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

        # 5. DRYER Structural AST Clones (RULE-AST-DUPLICATE)
        try:
            from tools.audit.dryer import DryerScanner, TREE_SITTER_AVAILABLE
            if TREE_SITTER_AVAILABLE:
                dryer = DryerScanner(threshold=0.82)
                clone_pairs = dryer.scan_path(target_dir, scoped_files=file_paths)
                for pair in clone_pairs:
                    score = pair.score
                    sev = FindingSeverity.CRITICAL.value if score >= 0.92 else FindingSeverity.WARNING.value
                    rel_left = pair.left.file_path
                    if rel_left.startswith("./"):
                        rel_left = rel_left[2:]
                    fp = LedgerItem.generate_fingerprint("RULE-AST-DUPLICATE", rel_left, pair.left.symbol, str(round(score, 2)))
                    findings.append(LedgerItem(
                        fingerprint=fp,
                        track=Track.CORE.value,
                        rule_id="RULE-AST-DUPLICATE",
                        title=f"Structural AST Duplicate ({score * 100:.1f}%): '{pair.left.symbol}' in {Path(rel_left).name} matches '{pair.right.symbol}' in {Path(pair.right.file_path).name}",
                        file_path=rel_left,
                        line_number=pair.left.start_line,
                        symbol=pair.left.symbol,
                        severity=sev,
                        status=FindingStatus.OPEN.value,
                        details={"score": score, "right_file": pair.right.file_path, "right_symbol": pair.right.symbol},
                        suggested_fix="Extract duplicate logic into shared domain helper under src/core/ or src/lib/.",
                        first_seen_at="",
                        last_seen_at="",
                    ))
        except Exception:
            pass

        return findings

    # =========================================================================
    # UI / FRONTEND SCANNER
    # =========================================================================
    def scan_ui(self, file_paths: Optional[List[str]] = None, include_mechanical: bool = False) -> List[LedgerItem]:
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

        if include_mechanical:
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
