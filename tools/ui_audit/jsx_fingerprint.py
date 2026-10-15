"""
JSX Fingerprint Analyzer
Extracts JSX elements and Tailwind class signatures, detects structural markup duplication,
and categorizes them into candidates for centralized UI primitives (Modal, Drawer, Skeleton, Button, Card, Toast).
"""

import re
from pathlib import Path
from typing import List, Optional
from .models import JSXPattern


# Tailwind structural class whitelist used to build resilient signatures
STRUCTURAL_KEYWORDS = {
    # Layout & Position
    "fixed", "absolute", "relative", "sticky",
    "inset-0", "inset-y-0", "top-0", "right-0", "bottom-0", "left-0",
    "z-10", "z-20", "z-30", "z-40", "z-50",
    "flex", "inline-flex", "grid", "hidden", "block",
    "items-center", "items-start", "items-end",
    "justify-center", "justify-between", "justify-end", "justify-start",
    # Animation & Effects
    "animate-pulse", "animate-spin", "transition-all", "transition-transform",
    "backdrop-blur", "backdrop-blur-sm", "backdrop-blur-md",
    # Common Shapes & Shadows
    "rounded", "rounded-md", "rounded-lg", "rounded-xl", "rounded-2xl", "rounded-full",
    "shadow", "shadow-sm", "shadow-md", "shadow-lg", "shadow-xl",
    "border", "border-b", "border-t", "divide-y",
    # Typical Primitive Paddings
    "p-2", "p-3", "p-4", "p-5", "p-6", "p-8",
    "px-2", "px-3", "px-4", "px-5", "px-6",
    "py-1", "py-1.5", "py-2", "py-2.5", "py-3",
    "gap-1", "gap-2", "gap-3", "gap-4", "gap-6",
}


class JSXFingerprinter:
    def __init__(self):
        # Regex to locate JSX tags with className
        # Matches: <tag ... className="..." or className={`...`}
        self.jsx_tag_pattern = re.compile(
            r"<([a-zA-Z0-9_\.]+)[^>]*?className=(?:\"([^\"]*)\"|'([^']*)'|\{`([^`]*)`\}|\{cn\(([^)]*)\)\}|\{clsx\(([^)]*)\)\})",
            re.DOTALL
        )

    def scan_file(self, file_path: Path, rel_path: str) -> List[JSXPattern]:
        """Scan a TSX file and extract classified JSX patterns."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        patterns: List[JSXPattern] = []
        lines = content.splitlines()

        for match in self.jsx_tag_pattern.finditer(content):
            tag = match.group(1)
            # Find which capture group matched the class string
            class_str = match.group(2) or match.group(3) or match.group(4) or match.group(5) or match.group(6) or ""
            
            # Clean up class string (remove dynamic JS interpolations if any)
            clean_classes = self._clean_class_string(class_str)
            if not clean_classes:
                continue

            # Calculate line number
            start_pos = match.start()
            line_no = content[:start_pos].count("\n") + 1

            # Categorize the pattern
            category = self._categorize_pattern(tag, clean_classes)
            if not category:
                continue

            # Extract structural signature
            structural_classes = [c for c in clean_classes if c in STRUCTURAL_KEYWORDS or self._is_structural(c)]
            if len(structural_classes) < 2:
                continue

            signature = ":".join(sorted(set(structural_classes)))

            snippet = match.group(0)[:120].replace("\n", " ").strip()

            patterns.append(JSXPattern(
                tag=tag,
                category=category,
                file_path=rel_path,
                line_number=line_no,
                class_string=" ".join(clean_classes),
                structural_classes=structural_classes,
                signature=f"{category}[{signature}]",
                snippet=snippet
            ))

        return patterns

    def _clean_class_string(self, class_str: str) -> List[str]:
        # Remove quotes, backticks, template interpolations ${...}
        cleaned = re.sub(r"\$\{[^}]*\}", "", class_str)
        cleaned = re.sub(r"['\",]", " ", cleaned)
        tokens = [t.strip() for t in cleaned.split() if t.strip()]
        return tokens

    def _is_structural(self, token: str) -> bool:
        # Match pattern-based structural classes like bg-black/50, h-4, w-full, etc.
        if token.startswith("bg-black/") or token.startswith("bg-zinc-") or token.startswith("bg-white"):
            return True
        if token.startswith("max-w-") or token.startswith("w-full"):
            return True
        if token.startswith("translate-x"):
            return True
        return False

    def _categorize_pattern(self, tag: str, classes: List[str]) -> Optional[str]:
        class_set = set(classes)

        # 1. Modal / Dialog Overlay
        if ("fixed" in class_set or "absolute" in class_set) and (
            "inset-0" in class_set or any(c.startswith("bg-black/") for c in class_set) or "backdrop-blur" in class_set
        ):
            return "modal_overlay"

        if ("fixed" in class_set or "absolute" in class_set) and (
            "items-center" in class_set and "justify-center" in class_set
        ):
            return "modal_container"

        # 2. Drawer / Slide-Over
        if ("fixed" in class_set or "absolute" in class_set) and (
            "inset-y-0" in class_set or ("right-0" in class_set or "left-0" in class_set)
        ) and any(c.startswith("max-w-") or "translate-x" in c or "transition" in c for c in class_set):
            return "drawer"

        # 3. Skeleton Loader
        if "animate-pulse" in class_set or (
            any("bg-gray-200" in c or "bg-zinc-200" in c or "bg-muted" in c for c in class_set) and
            any(c.startswith("h-") for c in class_set) and
            any(c.startswith("rounded") for c in class_set)
        ):
            return "skeleton"

        # 4. Action Button
        if tag.lower() in ("button", "link") or "cursor-pointer" in class_set:
            has_padding = any(c.startswith("px-") or c.startswith("p-") for c in class_set)
            has_shape = any(c.startswith("rounded") for c in class_set)
            has_action = any(c.startswith("hover:") or c.startswith("bg-") or "font-medium" in c or "font-semibold" in c for c in class_set)
            if has_padding and has_shape and has_action:
                return "button"

        # 5. Toast / Alert Banner
        if any(c.startswith("border-l-") or "alert" in c for c in class_set) or (
            any(c.startswith("bg-red-") or c.startswith("bg-green-") or c.startswith("bg-yellow-") or c.startswith("bg-amber-") or c.startswith("bg-blue-") for c in class_set) and
            any(c.startswith("p-") for c in class_set) and
            any(c.startswith("rounded") for c in class_set)
        ):
            return "alert_banner"

        # 6. Container / Card
        if (
            any(c.startswith("bg-white") or c.startswith("bg-zinc-") or c.startswith("bg-slate-") for c in class_set) and
            any(c.startswith("rounded-") for c in class_set) and
            any(c in ("p-4", "p-5", "p-6", "p-8") for c in class_set) and
            ("shadow" in class_set or "shadow-sm" in class_set or "shadow-md" in class_set or "border" in class_set)
        ):
            return "card"

        # 7. Table / Data Container
        if tag.lower() == "table" or "overflow-x-auto" in class_set or "min-w-full" in class_set:
            return "table_container"

        return None
