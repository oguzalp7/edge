"""Zero-token lexical stack gate and rubric promotion file helpers."""

from pathlib import Path
import re
from typing import List, Optional, Tuple

from tools.distill.models import CandidateRule


class LexicalStackGate:
    """Zero-token lexical gate classifying candidates as REPO_LOCAL or PLUGIN_CANDIDATE."""

    TECH_REGEX = re.compile(
        r"\b(nextjs|react|vue|svelte|fastapi|django|flask|express|drizzle|prisma|typeorm|sqlalchemy|mongo|postgres|mysql|sqlite|tailwind|daisyui|radix|shadcn)\b",
        re.IGNORECASE,
    )
    EXT_REGEX = re.compile(r"\.(tsx|jsx|vue|ts|py)\b", re.IGNORECASE)
    PATH_REGEX = re.compile(r"(src/(?:actions|components|lib|db|app)/[^\s]*|src/(?:actions|components|lib|db|app)/)", re.IGNORECASE)

    @classmethod
    def classify(cls, rule_text: str, target_path: Optional[str] = None) -> Tuple[str, List[str]]:
        matched = [m.group(1).lower() for m in cls.TECH_REGEX.finditer(rule_text)]
        matched.extend(f".{m.group(1).lower()}" for m in cls.EXT_REGEX.finditer(rule_text))
        matched.extend(m.group(1).lower() for m in cls.PATH_REGEX.finditer(rule_text))
        if target_path:
            matched.extend(m.group(1).lower() for m in cls.TECH_REGEX.finditer(target_path))
            matched.extend(f".{m.group(1).lower()}" for m in cls.EXT_REGEX.finditer(target_path))
        unique_tokens = sorted(set(matched))
        return ("REPO_LOCAL", unique_tokens) if unique_tokens else ("PLUGIN_CANDIDATE", [])


def append_rule_to_agent_rubric(agent_file: Path, cand: CandidateRule) -> None:
    """Append promoted candidate rule to core agent rubric enforcing 60-line budget."""
    if not agent_file.exists():
        return
    existing = agent_file.read_text(encoding="utf-8")
    if cand.rule_text in existing:
        return
    new_text = existing.rstrip() + f"\n\n### Distilled Invariant ({cand.candidate_id})\n- {cand.rule_text}\n"
    new_lines = len(new_text.splitlines())
    if new_lines > 60:
        raise ValueError(f"Line budget exceeded (> 60 lines: {new_lines} lines)")
    agent_file.write_text(new_text, encoding="utf-8")


def _strip_rule_from_file(ov: Path, rule_text: str) -> None:
    if not ov.exists():
        return
    try:
        text = ov.read_text(encoding="utf-8")
        if rule_text in text:
            ov.write_text("\n".join(ln for ln in text.splitlines() if rule_text not in ln) + "\n", encoding="utf-8")
    except Exception:
        pass


def clean_rule_from_all_projects(source_projects: List[str], cand: CandidateRule) -> None:
    """Remove promoted candidate rule text from project station overlay files."""
    role = cand.target_role.lower()
    variants = {role, role.replace("_", "-"), role.replace("-", "_")}
    for proj_str in source_projects:
        p = Path(proj_str)
        if not p.exists():
            continue
        for v in variants:
            _strip_rule_from_file(p / ".edge" / "stations" / f"{v}.md", cand.rule_text)
