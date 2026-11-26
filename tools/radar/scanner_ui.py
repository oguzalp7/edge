"""Frontend UI orphan, dead import, JSX cluster, and shallow-wrapper scanner."""

from pathlib import Path
from typing import Dict, List, Optional

from tools.rules import CANONICAL_ARRAY_PATTERN, RAW_TH_PATTERN, SHALLOW_WRAPPER_PATTERN
from tools.ui_audit.cluster_engine import ClusterEngine
from tools.ui_audit.graph_builder import GraphBuilder
from tools.ui_audit.jsx_fingerprint import JSXFingerprinter
from .models import FindingSeverity, FindingStatus, LedgerItem, Track


def _collect_graph_findings(
    repo_path: Path, file_paths: Optional[List[str]], include_mechanical: bool, findings: List[LedgerItem],
) -> Dict[str, object]:
    graph_builder = GraphBuilder(repo_path)
    nodes = graph_builder.build_graph()
    for orphan in graph_builder.find_orphans():
        if file_paths is not None and orphan.rel_path not in file_paths:
            continue
        findings.append(LedgerItem(
            fingerprint=LedgerItem.generate_fingerprint("RULE-ORPHAN-COMPONENT", orphan.rel_path),
            track=Track.UI.value, rule_id="RULE-ORPHAN-COMPONENT",
            title=f"Orphan Component: '{orphan.rel_path}' (0 incoming references, {orphan.sloc} SLOC)",
            file_path=orphan.rel_path, line_number=1, symbol=None,
            severity=FindingSeverity.ADVISORY.value, status=FindingStatus.OPEN.value,
            details={"sloc": orphan.sloc}, suggested_fix="Delete unused component if obsolete, or connect to intended parent screen.",
            first_seen_at="", last_seen_at="",
        ))
    if include_mechanical:
        for rel, dead_sym, imp_src in graph_builder.find_all_dead_imports():
            if file_paths is not None and rel not in file_paths:
                continue
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-DEAD-IMPORT", rel, dead_sym),
                track=Track.UI.value, rule_id="RULE-DEAD-IMPORT",
                title=f"Dead Symbol Import: '{dead_sym}' from '{imp_src}' in {rel}",
                file_path=rel, line_number=1, symbol=dead_sym,
                severity=FindingSeverity.ADVISORY.value, status=FindingStatus.OPEN.value,
                details={"source": imp_src, "symbol": dead_sym}, suggested_fix="Remove unused import to reduce module bundle size.",
                first_seen_at="", last_seen_at="",
            ))
    return nodes


def _collect_jsx_clusters(nodes: Dict[str, object], file_paths: Optional[List[str]], findings: List[LedgerItem]) -> None:
    fingerprinter = JSXFingerprinter()
    all_patterns = [p for node in nodes.values() for p in fingerprinter.scan_file(node.file_path, node.rel_path)]
    for cluster in ClusterEngine().cluster_patterns(all_patterns, min_instances=3):
        if file_paths is not None and not any(f in file_paths for f in cluster.distinct_files):
            continue
        findings.append(LedgerItem(
            fingerprint=LedgerItem.generate_fingerprint("RULE-JSX-DUPLICATE-CLUSTER", cluster.category, cluster.signature),
            track=Track.UI.value, rule_id="RULE-JSX-DUPLICATE-CLUSTER",
            title=f"JSX Duplicate Cluster: {cluster.count} instances of {cluster.category} across {len(cluster.distinct_files)} files",
            file_path=cluster.distinct_files[0], line_number=cluster.instances[0].line_number, symbol=cluster.category,
            severity=FindingSeverity.WARNING.value, status=FindingStatus.OPEN.value,
            details={"category": cluster.category, "count": cluster.count, "files": cluster.distinct_files, "estimated_sloc_saving": cluster.estimated_sloc_saving, "suggested_primitive": cluster.suggested_primitive},
            suggested_fix=f"Consolidate into centralized primitive '{cluster.suggested_primitive}' ({cluster.props_proposal}).",
            first_seen_at="", last_seen_at="",
        ))


def _scan_tsx_component(tsx: Path, rel: str, findings: List[LedgerItem]) -> None:
    try:
        content = tsx.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return
    sloc_lines = [ln for ln in content.splitlines() if ln.strip() and not ln.strip().startswith("//")]
    wrapper_match = SHALLOW_WRAPPER_PATTERN.search(content) if len(sloc_lines) < 55 else None
    if wrapper_match and tsx.stem != wrapper_match.group(1):
        target_comp = wrapper_match.group(1)
        findings.append(LedgerItem(
            fingerprint=LedgerItem.generate_fingerprint("RULE-SHALLOW-WRAPPER", rel, target_comp),
            track=Track.UI.value, rule_id="RULE-SHALLOW-WRAPPER",
            title=f"Shallow Wrapper Component: '{tsx.stem}' delegates to '{target_comp}' in {rel}",
            file_path=rel, line_number=1, symbol=tsx.stem,
            severity=FindingSeverity.CRITICAL.value, status=FindingStatus.OPEN.value,
            details={"target": target_comp}, suggested_fix="Delete shallow wrapper and migrate callers directly to the target primitive.",
            first_seen_at="", last_seen_at="",
        ))
    emitted_th = False
    for line_idx, line in enumerate(content.splitlines(), start=1):
        m = RAW_TH_PATTERN.search(line) if not emitted_th else None
        if m and not m.group(1).strip().startswith("{"):
            header_text = m.group(1).strip()
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-MAGIC-TABLE-HEADER", rel, header_text),
                track=Track.UI.value, rule_id="RULE-MAGIC-TABLE-HEADER",
                title=f"Hardcoded raw <th> header '{header_text}' in {rel}:{line_idx}",
                file_path=rel, line_number=line_idx, symbol=header_text,
                severity=FindingSeverity.WARNING.value, status=FindingStatus.OPEN.value,
                details={"header_text": header_text}, suggested_fix="Derive table columns from schema metadata or central bilingual dictionary.",
                first_seen_at="", last_seen_at="",
            ))
            emitted_th = True
        if CANONICAL_ARRAY_PATTERN.search(line):
            findings.append(LedgerItem(
                fingerprint=LedgerItem.generate_fingerprint("RULE-CANONICAL-IN-UI", rel, str(line_idx)),
                track=Track.UI.value, rule_id="RULE-CANONICAL-IN-UI",
                title=f"Hardcoded CANONICAL array in UI component ({rel}:{line_idx})",
                file_path=rel, line_number=line_idx, symbol="CANONICAL",
                severity=FindingSeverity.CRITICAL.value, status=FindingStatus.OPEN.value,
                details={"code_line": line.strip()}, suggested_fix="Move canonical business data to DB schema or domain configuration; UI must remain dynamic.",
                first_seen_at="", last_seen_at="",
            ))


def scan_ui_findings(repo_path: Path, file_paths: Optional[List[str]] = None, include_mechanical: bool = False) -> List[LedgerItem]:
    """Scan frontend components, JSX duplication clusters, and UI hygiene rules."""
    if not (repo_path / "src").exists() or (file_paths is not None and len(file_paths) == 0):
        return []
    findings: List[LedgerItem] = []
    nodes = _collect_graph_findings(repo_path, file_paths, include_mechanical, findings)
    _collect_jsx_clusters(nodes, file_paths, findings)
    from tools.common.profiles import is_stack_gate_enabled, resolve_active_profiles

    profiles = resolve_active_profiles(repo_path)
    check_ui_rules = profiles.source not in ("explicit", "explicit_none") or is_stack_gate_enabled(profiles, "zero_wrappers")
    components_dir = repo_path / "src" / "components"
    if check_ui_rules and components_dir.exists():
        for tsx in components_dir.rglob("*.tsx"):
            if ".test." in tsx.name:
                continue
            rel = str(tsx.relative_to(repo_path)).replace("\\", "/")
            if file_paths is None or rel in file_paths:
                _scan_tsx_component(tsx, rel, findings)
    return findings
