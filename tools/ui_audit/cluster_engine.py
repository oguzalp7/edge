"""
UI Pattern Cluster Engine
Groups structural JSX patterns, calculates duplicate density,
and formulates concrete proposals for centralized primitives under src/components/ui/.
"""

from collections import defaultdict
from typing import Dict, List
from .models import JSXPattern, DuplicateCluster


PRIMITIVE_SUGGESTIONS = {
    "modal_overlay": ("src/components/ui/Modal.tsx", "interface ModalProps {\n  isOpen: boolean;\n  onClose: () => void;\n  title?: string;\n  children: React.ReactNode;\n  size?: 'sm' | 'md' | 'lg' | 'xl';\n}"),
    "modal_container": ("src/components/ui/Modal.tsx", "interface ModalProps {\n  isOpen: boolean;\n  onClose: () => void;\n  title?: string;\n  children: React.ReactNode;\n  size?: 'sm' | 'md' | 'lg' | 'xl';\n}"),
    "drawer": ("src/components/ui/Drawer.tsx", "interface DrawerProps {\n  isOpen: boolean;\n  onClose: () => void;\n  position?: 'left' | 'right';\n  title?: string;\n  children: React.ReactNode;\n}"),
    "skeleton": ("src/components/ui/Skeleton.tsx", "interface SkeletonProps {\n  className?: string;\n  variant?: 'text' | 'circular' | 'rectangular';\n  width?: string | number;\n  height?: string | number;\n}"),
    "button": ("src/components/ui/Button.tsx", "interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {\n  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';\n  size?: 'sm' | 'md' | 'lg';\n  isLoading?: boolean;\n}"),
    "alert_banner": ("src/components/ui/Alert.tsx", "interface AlertProps {\n  variant?: 'info' | 'success' | 'warning' | 'error';\n  title?: string;\n  description?: string;\n  onClose?: () => void;\n}"),
    "card": ("src/components/ui/Card.tsx", "interface CardProps {\n  children: React.ReactNode;\n  className?: string;\n  padding?: 'none' | 'sm' | 'md' | 'lg';\n  variant?: 'flat' | 'elevated' | 'bordered';\n}"),
    "table_container": ("src/components/ui/TableWrapper.tsx", "interface TableWrapperProps {\n  children: React.ReactNode;\n  className?: string;\n  striped?: boolean;\n  dense?: boolean;\n}"),
}


class ClusterEngine:
    def cluster_patterns(self, patterns: List[JSXPattern], min_instances: int = 2) -> List[DuplicateCluster]:
        """Group patterns by category and signature."""
        grouped: Dict[str, List[JSXPattern]] = defaultdict(list)

        for p in patterns:
            # Group key based on category and signature
            grouped[p.signature].append(p)

        clusters: List[DuplicateCluster] = []

        for sig, items in grouped.items():
            if len(items) < min_instances:
                continue

            distinct_files = sorted(list(set(item.file_path for item in items)))
            # Prioritize patterns appearing across multiple files
            if len(distinct_files) < 2 and len(items) < 3:
                continue

            category = items[0].category
            suggested_file, props_def = PRIMITIVE_SUGGESTIONS.get(
                category,
                ("src/components/ui/SharedPrimitive.tsx", "interface PrimitiveProps {\n  variant?: string;\n  children: React.ReactNode;\n}")
            )

            # Estimate SLOC savings: (count - 1) * ~10 lines per block
            est_saving = max(0, (len(items) - 1) * 8)

            clusters.append(DuplicateCluster(
                category=category,
                signature=sig,
                instances=items,
                count=len(items),
                distinct_files=distinct_files,
                suggested_primitive=suggested_file,
                props_proposal=props_def,
                estimated_sloc_saving=est_saving
            ))

        # Sort clusters by impact: distinct files desc, count desc
        clusters.sort(key=lambda c: (len(c.distinct_files), c.count), reverse=True)
        return clusters
