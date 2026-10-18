from typing import List
from .models import FileMetrics, RiskCategory, IssueTag, AuditSummary


class HealthScorer:
    @staticmethod
    def score_file(m: FileMetrics) -> FileMetrics:
        score = 0.0
        tags: List[IssueTag] = []
        recs: List[str] = []

        # 1. SLOC Penalty
        if m.sloc > 500:
            score += 45.0
            tags.append(IssueTag.GOD_FILE)
            recs.append(f"Critical God file ({m.sloc} SLOC). Severely dilutes model attention; decompose into 3-4 cohesive submodules.")
        elif m.sloc > 350:
            score += 25.0
            tags.append(IssueTag.GOD_FILE)
            recs.append(f"Hotspot candidate for vertical slicing ({m.sloc} SLOC). Plan refactoring to reach < 200 SLOC clean boundary.")
        elif m.sloc > 200:
            score += 12.0
            recs.append(f"Approaching complexity boundary ({m.sloc} SLOC). Plan refactoring before adding new features.")

        # 2. Complexity Penalty
        if m.complexity_score > 35:
            score += 25.0
            tags.append(IssueTag.HIGH_COMPLEXITY)
            recs.append(f"High cyclomatic complexity ({m.complexity_score} decision points). Flatten nested control flows.")
        elif m.complexity_score > 20:
            score += 12.0
            tags.append(IssueTag.HIGH_COMPLEXITY)

        # 3. Indent Nesting Penalty
        if m.max_indent_level >= 5:
            score += 15.0
            tags.append(IssueTag.DEEP_NESTING)
            recs.append(f"Deep indentation nesting (level {m.max_indent_level}). Apply early returns and guard clauses.")
        elif m.max_indent_level == 4:
            score += 5.0

        # 4. Shallow Module Penalty (Ousterhout - Interface vs Body)
        if m.public_exports > 10 and m.sloc > 250:
            score += 15.0
            tags.append(IssueTag.SHALLOW_MODULE)
            recs.append(f"Shallow module warning: Leaking {m.public_exports} public exports. Encapsulate behind a unified facade/interface.")
        elif m.public_exports > 15:
            score += 10.0
            tags.append(IssueTag.SHALLOW_MODULE)

        # 5. Long Functions (God Functions)
        long_funcs = [f for f in m.functions if f.sloc > 50]
        if long_funcs:
            score += 10.0
            tags.append(IssueTag.GOD_FUNCTION)
            names = ", ".join([f.name for f in long_funcs[:3]])
            recs.append(f"Excessive function length ({names} > 50 lines). Extract pure calculations into helper utilities.")

        # 6. Test Seam Coverage
        if not m.has_test_seam and m.sloc > 120:
            score += 15.0
            tags.append(IssueTag.MISSING_TEST_SEAM)
            recs.append("Missing companion test seam. Pin existing behavior with tests before attempting refactoring.")

        # 7. UI Action / Direct DB Mixing Penalty
        if getattr(m, "has_ui_action_mixing", False) or IssueTag.UI_ACTION_MIXING in m.issue_tags:
            score += 25.0
            if IssueTag.UI_ACTION_MIXING not in tags:
                tags.append(IssueTag.UI_ACTION_MIXING)
            recs.append("UI component mixes direct DB queries or SQL operations. Extract data access to dedicated server actions or repositories.")

        # Final Score Cap & Categorization
        m.risk_score = min(100.0, round(score, 1))
        m.issue_tags = tags
        m.slicing_recommendations = recs

        if m.risk_score >= 60.0:
            m.risk_category = RiskCategory.CRITICAL
        elif m.risk_score >= 35.0:
            m.risk_category = RiskCategory.HOTSPOT
        elif m.risk_score >= 18.0:
            m.risk_category = RiskCategory.ATTENTION
        else:
            m.risk_category = RiskCategory.CLEAN

        return m

    @staticmethod
    def calculate_summary(summary: AuditSummary) -> AuditSummary:
        if not summary.file_results:
            summary.overall_health_score = 100.0
            return summary

        summary.critical_hotspots = sum(1 for f in summary.file_results if f.risk_category == RiskCategory.CRITICAL)
        summary.attention_files = sum(1 for f in summary.file_results if f.risk_category in (RiskCategory.HOTSPOT, RiskCategory.ATTENTION))
        summary.clean_files = sum(1 for f in summary.file_results if f.risk_category == RiskCategory.CLEAN)

        total_sloc = sum(f.sloc for f in summary.file_results)
        if total_sloc > 0:
            sloc_weighted_risk = sum(f.risk_score * f.sloc for f in summary.file_results) / total_sloc
        else:
            sloc_weighted_risk = sum(f.risk_score for f in summary.file_results) / len(summary.file_results)

        # Hotspot penalty: critical hotspots apply an additional drag so barrel files cannot hide God files
        hotspot_penalty = summary.critical_hotspots * 3.0
        combined_risk = sloc_weighted_risk + hotspot_penalty

        summary.overall_health_score = max(0.0, min(100.0, round(100.0 - combined_risk, 1)))
        return summary
