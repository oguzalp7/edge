"""JSX Fingerprint Analyzer: extracts structural Tailwind signatures from TSX files."""

from pathlib import Path
import re
from typing import List, Optional

from .jsx_rules import categorize_jsx_pattern
from .models import JSXPattern

STRUCTURAL_KEYWORDS = {
    "fixed", "absolute", "relative", "sticky",
    "inset-0", "inset-y-0", "top-0", "right-0", "bottom-0", "left-0",
    "z-10", "z-20", "z-30", "z-40", "z-50",
    "flex", "inline-flex", "grid", "hidden", "block",
    "items-center", "items-start", "items-end",
    "justify-center", "justify-between", "justify-end", "justify-start",
    "animate-pulse", "animate-spin", "transition-all", "transition-transform",
    "backdrop-blur", "backdrop-blur-sm", "backdrop-blur-md",
    "rounded", "rounded-md", "rounded-lg", "rounded-xl", "rounded-2xl", "rounded-full",
    "shadow", "shadow-sm", "shadow-md", "shadow-lg", "shadow-xl",
    "border", "border-b", "border-t", "divide-y",
    "p-2", "p-3", "p-4", "p-5", "p-6", "p-8",
    "px-2", "px-3", "px-4", "px-5", "px-6",
    "py-1", "py-1.5", "py-2", "py-2.5", "py-3",
    "gap-1", "gap-2", "gap-3", "gap-4", "gap-6",
}
_STRUCTURAL_PREFIXES = ("bg-black/", "bg-zinc-", "bg-white", "max-w-", "w-full", "translate-x")


class JSXFingerprinter:
    """Extracts classified JSX structural patterns from TSX files."""

    def __init__(self):
        self.jsx_tag_pattern = re.compile(
            r"<([a-zA-Z0-9_\.]+)[^>]*?className=(?:\"([^\"]*)\"|'([^']*)'|\{`([^`]*)`\}|\{cn\(([^)]*)\)\}|\{clsx\(([^)]*)\)\})",
            re.DOTALL,
        )

    def scan_file(self, file_path: Path, rel_path: str) -> List[JSXPattern]:
        """Scan a TSX file and extract classified JSX patterns."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
        patterns: List[JSXPattern] = []
        for match in self.jsx_tag_pattern.finditer(content):
            tag = match.group(1)
            raw_cls = match.group(2) or match.group(3) or match.group(4) or match.group(5) or match.group(6) or ""
            clean_classes = self._clean_class_string(raw_cls)
            category = self._categorize_pattern(tag, clean_classes) if clean_classes else None
            if not category:
                continue
            structural = [c for c in clean_classes if c in STRUCTURAL_KEYWORDS or self._is_structural(c)]
            if len(structural) < 2:
                continue
            patterns.append(JSXPattern(
                tag=tag, category=category, file_path=rel_path, line_number=content[: match.start()].count("\n") + 1,
                class_string=" ".join(clean_classes), structural_classes=structural,
                signature=f"{category}[{':'.join(sorted(set(structural)))}]",
                snippet=match.group(0)[:120].replace("\n", " ").strip(),
            ))
        return patterns

    def _clean_class_string(self, class_str: str) -> List[str]:
        cleaned = re.sub(r"\$\{[^}]*\}", "", class_str)
        cleaned = re.sub(r"['\",]", " ", cleaned)
        return [t.strip() for t in cleaned.split() if t.strip()]

    def _is_structural(self, token: str) -> bool:
        return token.startswith(_STRUCTURAL_PREFIXES)

    def _categorize_pattern(self, tag: str, classes: List[str]) -> Optional[str]:
        return categorize_jsx_pattern(tag, classes)
