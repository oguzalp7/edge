"""
Domain deed consolidation and spec synthesis for edge-drift.
"""

import json
import os
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from tools.common.paths import normalize_target_path
from tools.common.runner import run_command
from tools.drift.diff_checks import DRIFT_MODEL, get_head_sha
from tools.drift.models import DriftStateStore
from tools.drift.spec_discovery import archive_ephemeral_spec


def _read_source_specs(norm_repo: Path, source_specs: Optional[List[Path]]) -> Tuple[str, List[Path]]:
    sources_text = ""
    valid_paths: List[Path] = []
    for s in source_specs or []:
        s_path = Path(s) if Path(s).is_absolute() else (norm_repo / s)
        if not (s_path.exists() and s_path.is_file()):
            continue
        valid_paths.append(s_path)
        try:
            with open(s_path, "r", encoding="utf-8") as f:
                sources_text += f"\n--- SOURCE SPEC: {s_path.name} ---\n" + f.read() + "\n"
        except Exception:
            pass
    return sources_text, valid_paths


def _unwrap_markdown_fence(content: str) -> str:
    if content.startswith("```markdown") and content.endswith("```"):
        return content[len("```markdown"): -3].strip()
    if content.startswith("```") and content.endswith("```"):
        return content[3:-3].strip()
    return content


def _build_consolidation_prompt(domain: str, tracked_paths: List[str], paths_yaml: str, sources_text: str) -> str:
    return f"""You are the Edge Domain Architect. Consolidate and distill the domain specification for '{domain}'.
Synthesize the provided source specifications and live code matching tracked paths into a canonical Domain Deed ('Tapu').

Tracked Paths for '{domain}':
{json.dumps(tracked_paths, indent=2)}

Source Specifications Content:
{sources_text if sources_text else "No prior source specs provided. Synthesize from live domain code."}

Generate the canonical domain contract document with:
1. Leading YAML Frontmatter:
---
domain: {domain}
tracked_paths:
{paths_yaml}
---

2. Required Markdown Sections:
# {domain.capitalize()} Domain Contract

## Core Invariants
(State absolute rules, immutable business constraints, and non-negotiables)

## Domain Boundaries
(Explicit definitions of what belongs in this domain, data ownership, and what must be rejected or routed elsewhere)

## Intentional Anchors & Deferred Scope
(Record intentional technical debt, future phase boundaries, and deliberate seams)
"""


def consolidate_domain(
    repo_path: Union[Path, str],
    domain: str,
    tracked_paths: List[str],
    source_specs: Optional[List[Path]] = None,
    archive_sources: bool = False,
    model: str = DRIFT_MODEL,
    timeout: int = 180,
    runner: Callable = run_command,
) -> Tuple[bool, Path, str]:
    """Distills source specifications and live code into a canonical Domain Deed."""
    norm_repo = normalize_target_path(repo_path)
    domains_dir = norm_repo / "docs" / "domains"
    domains_dir.mkdir(parents=True, exist_ok=True)
    target_path = domains_dir / f"{domain}.md"

    sources_text, valid_source_paths = _read_source_specs(norm_repo, source_specs)
    paths_yaml = "\n".join(f"  - {p}" for p in tracked_paths)
    prompt = _build_consolidation_prompt(domain, tracked_paths, paths_yaml, sources_text)
    code, stdout, stderr = runner(["agy", "--mode", "plan", "--model", model, "-p", prompt], cwd=norm_repo, timeout=timeout)
    if code != 0:
        return False, target_path, f"Failed to run agy: {stderr or stdout}"

    content = _unwrap_markdown_fence(stdout.strip())
    if not content.startswith("---"):
        content = f"---\ndomain: {domain}\ntracked_paths:\n{paths_yaml}\n---\n\n" + content

    tmp_target = target_path.with_name(f"{target_path.name}.tmp.{os.getpid()}")
    with open(tmp_target, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_target, target_path)

    head_sha = get_head_sha(norm_repo, runner=runner)
    rel_doc_path = target_path.relative_to(norm_repo).as_posix()
    DriftStateStore.load_from_repo(norm_repo).update_record(
        domain=domain, sha=head_sha, doc_path=rel_doc_path, tracked_paths=tracked_paths
    )
    for s_path in (valid_source_paths if archive_sources else []):
        archive_ephemeral_spec(norm_repo, s_path)

    return True, target_path, f"Successfully consolidated domain '{domain}' into {rel_doc_path}"
