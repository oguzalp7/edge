"""
Deterministic CODE_LEAK_IN_DOMAIN_DOC and domain deed validator for edge-drift.
"""

import re
from typing import Dict, List, Optional, Set, Tuple

from tools.drift.models import CanonicalDomainDoc, OntologyIssue

_ALLOWED_FENCE_LANGS = {"mermaid", "pseudo", "pseudocode"}
_ENFORCED_BY_LEAK_RE = re.compile(r"(?i)^\s*[*_]{1,2}enforced\s+by\b")
_CODE_EXT_RE = re.compile(
    r"(?<![\w-])(?:[\w*-]+\.)+(?:py|ts|tsx|js|jsx|mjs|cjs|sql|sh|json|yaml|yml)\b"
)
_CODE_PATH_RE = re.compile(
    r"(?:^|[\s`(\[\"'])(?:"
    r"(?:\.edge|src|tools|tests|app|lib|skills|agents|docs)/(?:[\w.*-]+(?:/[\w.*-]+)*|(?=\s|$|[`.,;:)\]]))"
    r"|rules/(?:[\w.*-]+(?:/[\w.*-]+)+|[\w.*-]+\.(?:md|py|ts|json|yaml|yml)|(?=\s|$|[`.,;:)\]]))"
    r")"
)
_BACKTICK_SPAN_RE = re.compile(r"`([^`]+)`")
_BACKTICK_CALL_RE = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\([^)]*\)")
_SNAKE_CASE_RE = re.compile(r"[A-Za-z0-9]*[a-z][A-Za-z0-9]*_[A-Za-z0-9_]+|[A-Za-z0-9_]+_[a-z][A-Za-z0-9]*")
_CAMEL_CASE_RE = re.compile(r"[a-z][a-zA-Z0-9]*[A-Z][a-zA-Z0-9]*")
_PASCAL_CASE_RE = re.compile(r"(?:[A-Z][a-z0-9]+){2,}")
_DOTTED_IDENT_RE = re.compile(r"[A-Za-z_]\w*\.[A-Za-z_]\w*")
_ALLOWED_BACKTICK_PATTERNS = (
    re.compile(r"v\d+(?:\.\d+)+"),
    re.compile(r"(?:[A-Z]+\s*)?(?:<=|>=|<|>|==)\s*\d+"),
    re.compile(r"[A-Z][A-Z0-9_-]*"),
    re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*"),
    re.compile(r"[A-Z][a-z0-9]+"),
    re.compile(r"[a-z]\.[a-z]"),
)


def _extract_domain_body_lines(dom_text: str) -> List[str]:
    """Returns DOMAIN.md body lines starting at the first ## heading (or after metadata)."""
    lines = dom_text.lstrip("\ufeff").splitlines()
    for idx, line in enumerate(lines):
        if line.strip().startswith("## "):
            return lines[idx:]
    return [
        line
        for line in lines
        if not line.strip().startswith(("# Domain:", "- **Paths:**", "- **Owner", "- **Concepts:**"))
    ]


def _is_allowed_backtick_token(token: str) -> bool:
    if token in {"CONTEXT.md", "DOMAIN.md"} or token.startswith(("--", "/")):
        return True
    return any(pat.fullmatch(token) for pat in _ALLOWED_BACKTICK_PATTERNS)


def _check_backtick_leak(token: str) -> Optional[str]:
    if _is_allowed_backtick_token(token):
        return None
    if "/" in token and not token.startswith("/"):
        return f"Code/file path '{token}' not allowed in abstract DOMAIN.md"
    for regex, label in (
        (_CODE_EXT_RE, "Code file reference"),
        (_BACKTICK_CALL_RE, "Function call"),
        (_DOTTED_IDENT_RE, "Dotted code identifier"),
    ):
        if regex.search(token):
            return f"{label} '{token}' not allowed in abstract DOMAIN.md"
    for regex, label in (
        (_SNAKE_CASE_RE, "snake_case identifier"),
        (_CAMEL_CASE_RE, "camelCase identifier"),
        (_PASCAL_CASE_RE, "PascalCase identifier"),
    ):
        if regex.fullmatch(token):
            return f"{label} '{token}' not allowed in abstract DOMAIN.md"
    return None


def _check_path_or_ext_leak(line: str) -> Optional[str]:
    cleaned = line.replace("CONTEXT.md", "").replace("DOMAIN.md", "")
    if _CODE_EXT_RE.search(cleaned):
        return f"Code file extension in DOMAIN.md: '{line.strip()}'"
    if _CODE_PATH_RE.search(line):
        return f"Repository path in DOMAIN.md: '{line.strip()}'"
    return None


def _check_prose_line_leaks(line: str, doc_path: str) -> List[OntologyIssue]:
    issues: List[OntologyIssue] = []
    if _ENFORCED_BY_LEAK_RE.match(line):
        issues.append(
            OntologyIssue(
                "ERROR",
                "CODE_LEAK_IN_DOMAIN_DOC",
                doc_path,
                "Legacy '*Enforced by:*' reference not allowed in v1.1 DOMAIN.md",
            )
        )
    path_err = _check_path_or_ext_leak(line)
    if path_err:
        issues.append(OntologyIssue("ERROR", "CODE_LEAK_IN_DOMAIN_DOC", doc_path, path_err))
    for match in _BACKTICK_SPAN_RE.finditer(line):
        bt_err = _check_backtick_leak(match.group(1).strip())
        if bt_err:
            issues.append(OntologyIssue("ERROR", "CODE_LEAK_IN_DOMAIN_DOC", doc_path, bt_err))
    return issues


def _handle_backtick_fence(stripped: str, in_fence: bool, doc_path: str) -> Tuple[bool, Optional[OntologyIssue]]:
    if in_fence:
        return False, None
    lang = stripped[3:].strip().lower()
    if lang not in _ALLOWED_FENCE_LANGS:
        issue = OntologyIssue(
            "ERROR",
            "CODE_LEAK_IN_DOMAIN_DOC",
            doc_path,
            f"Disallowed or untyped code fence '```{lang}' in DOMAIN.md",
        )
        return True, issue
    return True, None


def _scan_domain_doc_leaks(dom_text: str, doc_path: str) -> List[OntologyIssue]:
    """Deterministic CODE_LEAK_IN_DOMAIN_DOC check on a canonical DOMAIN.md body."""
    issues: List[OntologyIssue] = []
    in_fence = False
    for line in _extract_domain_body_lines(dom_text):
        stripped = line.strip()
        if stripped.startswith("~~~"):
            issues.append(
                OntologyIssue("ERROR", "CODE_LEAK_IN_DOMAIN_DOC", doc_path, "Tilde code fence not allowed in DOMAIN.md")
            )
            in_fence = not in_fence
            continue
        if stripped.startswith("```"):
            in_fence, fence_issue = _handle_backtick_fence(stripped, in_fence, doc_path)
            if fence_issue:
                issues.append(fence_issue)
            continue
        if in_fence:
            path_err = _check_path_or_ext_leak(line)
            if path_err:
                issues.append(OntologyIssue("ERROR", "CODE_LEAK_IN_DOMAIN_DOC", doc_path, path_err))
            continue
        issues.extend(_check_prose_line_leaks(line, doc_path))

    if in_fence:
        issues.append(OntologyIssue("ERROR", "CODE_LEAK_IN_DOMAIN_DOC", doc_path, "Unclosed fenced code block in DOMAIN.md"))
    return issues


def _validate_domain_doc_entry(
    doc: CanonicalDomainDoc,
    dom_text: str,
    valid_concepts: Set[str],
    context_globs: Dict[str, List[str]],
    has_context_file: bool,
) -> List[OntologyIssue]:
    """Validates one CanonicalDomainDoc against CONTEXT.md and code-leak rules."""
    issues: List[OntologyIssue] = []
    if has_context_file or doc.concepts:
        issues.extend(
            OntologyIssue("ERROR", "UNKNOWN_CONCEPT", doc.doc_path, f"Unknown concept '{c}' not in CONTEXT.md")
            for c in doc.concepts if c not in valid_concepts
        )

    if doc.domain in context_globs and doc.tracked_paths:
        ctx_paths = [g.strip() for g in context_globs[doc.domain]]
        dom_paths = [g.strip() for g in doc.tracked_paths]
        if ctx_paths != dom_paths:
            issues.append(
                OntologyIssue("WARNING", "GLOB_MISMATCH", doc.doc_path, f"CONTEXT.md globs differ from {doc.doc_path} Paths:")
            )

    issues.extend(_scan_domain_doc_leaks(dom_text, doc.doc_path))
    return issues
