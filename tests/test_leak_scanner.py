"""Companion unit tests for tools.drift.leak_scanner."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.drift.domain_doc import CanonicalDomainDoc
from tools.drift.leak_scanner import _scan_domain_doc_leaks, _validate_domain_doc_entry


def test_scan_domain_doc_leaks_and_validate_entry() -> None:
    clean_md = "# Domain: `core`\n- **Concepts:** `safe-concept`\n\n## Rules\n- Pure `safe-concept` invariant.\n"
    doc = CanonicalDomainDoc(domain="core", doc_path="docs/core/DOMAIN.md", concepts=["safe-concept"])
    assert _validate_domain_doc_entry(doc, clean_md, {"safe-concept"}, {}, True) == []

    leaky_md = "## Rules\n- Calls `do_something()` in `tools/core/foo.py`.\n"
    issues = _scan_domain_doc_leaks(leaky_md, "docs/core/DOMAIN.md")
    assert len(issues) >= 2
    assert all(i.code == "CODE_LEAK_IN_DOMAIN_DOC" for i in issues)
