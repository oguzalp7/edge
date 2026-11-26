"""TSX/TS import/export extraction and relative path helpers for GraphBuilder."""

from pathlib import Path
import re
from typing import List, Optional

from .models import ComponentImport

_NAMED_EXPORT_RE = re.compile(r"export\s+(?:default\s+)?(?:function|const|class|let)\s+([A-Za-z0-9_]+)")
_DEFAULT_EXPORT_RE = re.compile(r"export\s+default\s+([A-Za-z0-9_]+)\s*;")
_IMPORT_STMT_RE = re.compile(r"import\s+(?:type\s+)?(?:([A-Za-z0-9_]+)\s*,?\s*)?(?:\{([^}]+)\})?\s*from\s*['\"]([^'\"]+)['\"]", re.MULTILINE)
_STRIP_IMPORTS_RE = re.compile(r"import\s+(?:type\s+)?(?:[\s\S]*?from\s+)?['\"][^'\"]+['\"]\s*;?")


def relativize_src_path(file_path: Path, root_dir: Path, src_dir: Path) -> Optional[str]:
    """Normalize file_path relative to root_dir or src_dir."""
    try:
        return file_path.relative_to(root_dir).as_posix()
    except ValueError:
        try:
            p = file_path.relative_to(src_dir).as_posix()
            return p if p.startswith("src/") else f"src/{p}"
        except ValueError:
            return None


def extract_exports(content: str, default_name: str) -> List[str]:
    """Extract exported symbol names from TSX/TS source."""
    exports = list(_NAMED_EXPORT_RE.findall(content))
    default_match = _DEFAULT_EXPORT_RE.search(content)
    if default_match:
        exports.append(default_match.group(1))
    elif "export default" in content:
        exports.append(default_name)
    return list(set(exports))


def _parse_import_symbols(default_sym: Optional[str], named_block: Optional[str]) -> List[str]:
    symbols: List[str] = [default_sym.strip()] if default_sym else []
    for part in (named_block or "").split(","):
        p = part.strip()
        if not p:
            continue
        local_sym = p.split(" as ")[1].strip() if " as " in p else p
        if local_sym:
            symbols.append(local_sym)
    return symbols


def extract_imports(content: str) -> List[ComponentImport]:
    """Extract import statements and identify dead vs used symbols."""
    body_content = _STRIP_IMPORTS_RE.sub("", content)
    imports: List[ComponentImport] = []
    for match in _IMPORT_STMT_RE.finditer(content):
        symbols = _parse_import_symbols(match.group(1), match.group(2))
        used = [s for s in symbols if re.search(rf"\b{re.escape(s)}\b", body_content)]
        dead = [s for s in symbols if s not in used]
        imports.append(ComponentImport(source_str=match.group(3), imported_symbols=symbols, used_symbols=used, dead_symbols=dead))
    return imports


def resolve_import_path(current_file: Path, source_str: str, root_dir: Path, src_dir: Path) -> Optional[str]:
    """Resolve @/ or relative import target to normalized repository-relative path."""
    if source_str.startswith("@/"):
        target_path = src_dir / source_str[2:]
    elif source_str.startswith("."):
        target_path = (current_file.parent / source_str).resolve()
    else:
        return None
    for cand in (target_path.with_suffix(".tsx"), target_path.with_suffix(".ts"), target_path / "index.tsx", target_path / "index.ts", target_path):
        if cand.is_file():
            return relativize_src_path(cand, root_dir, src_dir)
    return None
