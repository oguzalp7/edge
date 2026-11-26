"""
Shared Rule Definitions and AST/Regex Patterns
Single Source of Truth for edge-gate and edge-radar.
"""

import re

# Raw HTML <th> header containing static text instead of schema/dictionary binding
RAW_TH_PATTERN = re.compile(r"<th\b[^>]*>\s*([A-Za-z0-9ğüşıöçĞÜŞİÖÇ\s]{2,})\s*</th>")

# Hardcoded canonical array/list in frontend UI code
CANONICAL_ARRAY_PATTERN = re.compile(r"\b(?:export\s+)?const\s+CANONICAL_[A-Z0-9_]+\s*=")

# Direct database queries, transactions or mutations inside Server Actions
SQL_LEAK_PATTERN = re.compile(r"\bdb\.(transaction|insert|update|delete|select|query)\b")

# Pass-through component wrapper: returns <Target ...>{children}</Target>
SHALLOW_WRAPPER_PATTERN = re.compile(
    r"return\s*\(\s*<([A-Z][A-Za-z0-9]+)\b([^>]*?)>\s*\{children\}\s*</\1>\s*\);?",
    re.DOTALL
)

# Synthetic mock/default fallback constants in production code
MOCK_FALLBACK_PATTERN = re.compile(r"\b(?:DEFAULT|MOCK)_[A-Z0-9_]+\b")

# TypeScript type-safety escapes (`as any`, `as unknown as`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`)
TYPE_ESCAPE_PATTERN = re.compile(r"\bas\s+(?:any|unknown\s+as)\b|@ts-(?:ignore|expect-error|nocheck)\b")

# Explicit `any` type annotations, generic args, casts, and array types (`: any`, `<any>`, `as any`, `any[]`, `Array<any>`)
TS_EXPLICIT_ANY_PATTERN = re.compile(
    r"(?::|\bas\b|[|&])\s*any\b|<\s*any\s*>|\bany\s*\[\s*\]|,\s*any\s*(?=[>,\]])"
)

# Shipped production console.log calls
TS_CONSOLE_LOG_PATTERN = re.compile(r"\bconsole\.log\s*\(")

# JSX className attribute extractor for dual-theme checks
BG_WHITE_NO_DARK_PATTERN = re.compile(
    r"""className\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|\{(?P<br>[^}]*)\})""",
    re.DOTALL,
)

# Icon-only <X> close button pattern for aria-label audit
ICON_X_BUTTON_NO_ARIA_PATTERN = re.compile(
    r"<button\b(?P<attrs>[^>]*?)>\s*<X\b[^>]*/?>\s*(?:</X>\s*)?</button>",
    re.DOTALL,
)

RULE_PACKS = {
    "core": (
        "MOCK_FALLBACK_PATTERN",
    ),
    "typescript": (
        "TYPE_ESCAPE_PATTERN",
        "TS_EXPLICIT_ANY_PATTERN",
        "TS_CONSOLE_LOG_PATTERN",
    ),
    "nextjs-drizzle-tailwind": (
        "SQL_LEAK_PATTERN",
        "RAW_TH_PATTERN",
        "CANONICAL_ARRAY_PATTERN",
        "SHALLOW_WRAPPER_PATTERN",
        "BG_WHITE_NO_DARK_PATTERN",
        "ICON_X_BUTTON_NO_ARIA_PATTERN",
    ),
}
