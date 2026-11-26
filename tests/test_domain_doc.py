"""Companion unit tests for tools.drift.domain_doc and tools.drift.path_matcher."""

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.drift.domain_doc import (
    CanonicalDomainDoc,
    OntologyIssue,
    OntologyReport,
    parse_canonical_domain_doc,
    parse_context_glossary,
)
from tools.drift.path_matcher import matches_tracked_paths, parse_domain_frontmatter


def test_parse_canonical_domain_doc_and_glossary() -> None:
    doc = parse_canonical_domain_doc(
        "# Domain: `demo`\n- **Owner / DRI:** @demo\n- **Concepts:** `a`, `b`\n"
        "- **[INV-DEMO-SAFE]** Must stay safe.\n- **[PAT-DEMO-CLEAN]** Clean pattern.\n",
        doc_path="docs/demo/DOMAIN.md",
    )
    assert isinstance(doc, CanonicalDomainDoc)
    assert doc.domain == "demo"
    assert doc.concepts == ["a", "b"]
    assert doc.invariant_ids == ["INV-DEMO-SAFE"]
    assert doc.pattern_ids == ["PAT-DEMO-CLEAN"]

    globs, concepts = parse_context_glossary(
        "## Domain Map\n| `demo` | `tools/demo/**` | @demo |\n"
        "## Closed Concept Glossary\n| `a` | sym | desc |\n"
    )
    assert globs == {"demo": ["tools/demo/**"]}
    assert concepts == ["a"]

    rep = OntologyReport(issues=[OntologyIssue("ERROR", "UNKNOWN_CONCEPT", "x", "bad")])
    assert rep.has_errors


def test_path_matcher_and_frontmatter() -> None:
    assert matches_tracked_paths(["./src/a/b.py", "docs/x.md"], ["src/**"]) == ["./src/a/b.py"]
    dom, paths, body = parse_domain_frontmatter(
        "---\ndomain: core\ntracked_paths:\n  - src/**\n---\nHello\n"
    )
    assert dom == "core"
    assert paths == ["src/**"]
    assert body.strip() == "Hello"
