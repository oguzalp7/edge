"""
Unit tests for DRYER: Tree-Sitter Structural AST Clone and Duplication Detector.
Covers AST normalization, Jaccard similarity, TypeScript/TSX/Python structural clone detection,
JSX tag preservation, connected-component clustering, and graceful tree-sitter fallback.
"""

import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import pytest

from tools.audit.dryer import (
    AstUnit,
    ClonePair,
    CloneCluster,
    normalize_ast,
    jaccard_similarity,
    DryerScanner,
    TREE_SITTER_AVAILABLE,
)


class TestDryerSimilarity:
    def test_jaccard_similarity_identical_sets(self):
        fp1 = frozenset(["path:a->b", "path:b->c", "path:c->d"])
        fp2 = frozenset(["path:a->b", "path:b->c", "path:c->d"])
        self_score = jaccard_similarity(fp1, fp2)
        assert self_score == 1.0

    def test_jaccard_similarity_completely_disjoint(self):
        fp1 = frozenset(["path:a->b", "path:b->c"])
        fp2 = frozenset(["path:x->y", "path:y->z"])
        score = jaccard_similarity(fp1, fp2)
        assert score == 0.0

    def test_jaccard_similarity_partial_overlap(self):
        # 2 in intersection, 4 in union -> 2/4 = 0.5
        fp1 = frozenset(["sub:1", "sub:2", "sub:3"])
        fp2 = frozenset(["sub:2", "sub:3", "sub:4"])
        score = jaccard_similarity(fp1, fp2)
        assert score == 0.5

    def test_jaccard_similarity_empty_sets(self):
        empty = frozenset()
        non_empty = frozenset(["sub:1", "sub:2"])
        assert jaccard_similarity(empty, non_empty) == 0.0
        assert jaccard_similarity(non_empty, empty) == 0.0
        assert jaccard_similarity(empty, empty) == 0.0


class TestDryerFallback:
    def test_graceful_fallback_when_tree_sitter_unavailable(self, monkeypatch, tmp_path):
        # When tree-sitter or tree-sitter-language-pack is not available,
        # scan_path must return an empty list [] without raising any exception.
        monkeypatch.setattr("tools.audit.dryer.TREE_SITTER_AVAILABLE", False)
        
        sample_file = tmp_path / "sample.ts"
        sample_file.write_text("function foo() { return 1; }", encoding="utf-8")

        scanner = DryerScanner(threshold=0.82)
        result = scanner.scan_path(tmp_path)
        assert result == []


@pytest.mark.skipif(not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed")
class TestDryerAstClones:
    def test_typescript_structural_clone_detection_with_renamed_identifiers(self, tmp_path):
        """
        Two functions with completely renamed local variables, distinct literals,
        and added comments must normalize to the same AST structure with Jaccard score >= 0.82.
        """
        fn_a = """
        export function calculateStaffCommission(sales: number, rate: number): number {
            const baseCommission = 100;
            const computedTotal = sales * rate + baseCommission;
            if (computedTotal > 5000) {
                return computedTotal * 1.15;
            } else if (computedTotal > 2000) {
                return computedTotal * 1.05;
            }
            return computedTotal;
        }
        """

        fn_b = """
        // Calculate employee bonus with different variable names and comments
        export function computeEmployeeBonus(revenue: number, pct: number): number {
            const initialAllowance = 250;
            const grossPayout = revenue * pct + initialAllowance;
            if (grossPayout > 10000) {
                return grossPayout * 1.20;
            } else if (grossPayout > 4000) {
                return grossPayout * 1.08;
            }
            return grossPayout;
        }
        """

        (tmp_path / "commission.ts").write_text(fn_a, encoding="utf-8")
        (tmp_path / "bonus.ts").write_text(fn_b, encoding="utf-8")

        scanner = DryerScanner(threshold=0.82, min_lines=5, min_nodes=15)
        pairs = scanner.scan_path(tmp_path)

        assert len(pairs) >= 1, "Expected at least 1 structural clone pair between commission.ts and bonus.ts"
        pair = pairs[0]
        assert pair.score >= 0.82, f"Expected clone similarity >= 0.82, got {pair.score}"
        names = {pair.left.symbol, pair.right.symbol}
        assert "calculateStaffCommission" in names
        assert "computeEmployeeBonus" in names

    def test_clone_clustering_three_or_more_functions(self, tmp_path):
        """
        Three structurally similar functions across three files must be grouped
        into a single connected CloneCluster with deterministic CLONE-xxxxxx ID.
        """
        t1 = """
        export function processAlpha(items: string[], factor: number): number[] {
            const results: number[] = [];
            for (let i = 0; i < items.length; i++) {
                const len = items[i].length;
                if (len > 10) {
                    results.push(len * factor * 2);
                } else {
                    results.push(len * factor);
                }
            }
            return results;
        }
        """
        t2 = """
        export function transformBeta(words: string[], mult: number): number[] {
            const output: number[] = [];
            for (let idx = 0; idx < words.length; idx++) {
                const count = words[idx].length;
                if (count > 20) {
                    output.push(count * mult * 3);
                } else {
                    output.push(count * mult);
                }
            }
            return output;
        }
        """
        t3 = """
        export function handleGamma(entries: string[], weight: number): number[] {
            const accumulated: number[] = [];
            for (let k = 0; k < entries.length; k++) {
                const sz = entries[k].length;
                if (sz > 15) {
                    accumulated.push(sz * weight * 4);
                } else {
                    accumulated.push(sz * weight);
                }
            }
            return accumulated;
        }
        """

        (tmp_path / "alpha.ts").write_text(t1, encoding="utf-8")
        (tmp_path / "beta.ts").write_text(t2, encoding="utf-8")
        (tmp_path / "gamma.ts").write_text(t3, encoding="utf-8")

        scanner = DryerScanner(threshold=0.82, min_lines=5, min_nodes=15)
        pairs = scanner.scan_path(tmp_path)
        clusters = scanner.cluster_clones(pairs)

        assert len(clusters) == 1, f"Expected 1 connected CloneCluster for 3 clones, got {len(clusters)}"
        cluster = clusters[0]
        assert cluster.cluster_id.startswith("CLONE-")
        assert len(cluster.members) == 3
        assert set(cluster.distinct_files) == {"alpha.ts", "beta.ts", "gamma.ts"}
        assert cluster.max_score >= 0.82

    def test_jsx_tag_preservation_avoids_false_positive(self, tmp_path):
        """
        Two TSX components with identical layout structure EXCEPT genuinely different JSX tags
        (<ModalHeader> vs <DrawerFooter>) must NOT be collapsed together with 1.0 similarity.
        Conversely, components sharing the same JSX layout with different text DO match.
        """
        comp_modal_1 = """
        export function ModalHeaderPrimary({ heading, note }: { heading: string, note: string }) {
            return (
                <ModalHeader className="px-6 py-4 border-b">
                    <h2 className="text-xl font-semibold">{heading}</h2>
                    <span className="text-sm text-muted">{note}</span>
                </ModalHeader>
            );
        }
        """

        comp_modal_2 = """
        export function ModalHeaderSecondary({ title, description }: { title: string, description: string }) {
            return (
                <ModalHeader className="px-4 py-2 border-b">
                    <h2 className="text-lg font-bold">{title}</h2>
                    <span className="text-xs text-gray-400">{description}</span>
                </ModalHeader>
            );
        }
        """

        comp_drawer = """
        export function DrawerFooterPrimary({ actionLabel, helpText }: { actionLabel: string, helpText: string }) {
            return (
                <DrawerFooter className="px-6 py-4 border-t">
                    <button className="text-xl font-semibold">{actionLabel}</button>
                    <div className="text-sm text-muted">{helpText}</div>
                </DrawerFooter>
            );
        }
        """

        (tmp_path / "modal1.tsx").write_text(comp_modal_1, encoding="utf-8")
        (tmp_path / "modal2.tsx").write_text(comp_modal_2, encoding="utf-8")
        (tmp_path / "drawer.tsx").write_text(comp_drawer, encoding="utf-8")

        scanner = DryerScanner(threshold=0.80, min_lines=4, min_nodes=10)
        pairs = scanner.scan_path(tmp_path)

        # Modal 1 and Modal 2 have the same JSX tags (<ModalHeader>, <h2>, <span>) and must match
        modal_pairs = [p for p in pairs if {"ModalHeaderPrimary", "ModalHeaderSecondary"}.issubset({p.left.symbol, p.right.symbol})]
        assert len(modal_pairs) == 1, "Expected ModalHeaderPrimary and ModalHeaderSecondary to be detected as clones"
        assert modal_pairs[0].score >= 0.80

        # Drawer footer has distinct tags (<DrawerFooter>, <button>, <div>) and must not match ModalHeaderPrimary at 1.0
        for p in pairs:
            if "DrawerFooterPrimary" in {p.left.symbol, p.right.symbol}:
                assert p.score < 1.0, f"DrawerFooter with distinct JSX tags falsely matched at {p.score}"

    def test_python_structural_clone_detection(self, tmp_path):
        """
        Two Python functions with identical control flow structures, renamed variables,
        and different numerical literals must be detected as clones.
        """
        py_a = """
        def compute_tax(income: float, tier: int) -> float:
            base_allowance = 500.0
            taxable = income - base_allowance
            if taxable > 50000.0:
                surcharge = taxable * 0.10
                return taxable * 0.25 + surcharge
            elif taxable > 20000.0:
                return taxable * 0.15
            return taxable * 0.05
        """

        py_b = """
        def calc_customs_duty(declared_val: float, category: int) -> float:
            # Customs duty calculation with different names
            exemption = 200.0
            dutiable = declared_val - exemption
            if dutiable > 80000.0:
                fee = dutiable * 0.12
                return dutiable * 0.30 + fee
            elif dutiable > 30000.0:
                return dutiable * 0.18
            return dutiable * 0.08
        """

        (tmp_path / "tax.py").write_text(py_a, encoding="utf-8")
        (tmp_path / "customs.py").write_text(py_b, encoding="utf-8")

        scanner = DryerScanner(threshold=0.82, min_lines=5, min_nodes=15)
        pairs = scanner.scan_path(tmp_path)

        assert len(pairs) >= 1, "Expected Python structural clone pair"
        assert pairs[0].score >= 0.82
        symbols = {pairs[0].left.symbol, pairs[0].right.symbol}
        assert "compute_tax" in symbols
        assert "calc_customs_duty" in symbols
