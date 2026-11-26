"""Ship-prep submodule: danger_diff."""

from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.danger_paths import _extract_balanced_parens

def _parse_reexports_and_cjs(
    text: str, named_exports: set, star_exports: set, module_export_keys: set
) -> Tuple[bool, bool]:
    for m in re.finditer(r"\bexport\s+(?:type\s+)?\{([^}]+)\}", text, re.DOTALL):
        for part in m.group(1).split(","):
            tok = part.strip()
            if tok.startswith("type "):
                tok = tok[5:].strip()
            if " as " in tok:
                tok = tok.split(" as ", 1)[1].strip()
            if tok:
                named_exports.add(tok)
    for m in re.finditer(r"\bexport\s+\*(?:\s+as\s+([A-Za-z_$][\w$]*))?\s+from\s+['\"]([^'\"]+)['\"]", text):
        star_exports.add((m.group(1) or "", m.group(2)))
    has_default = bool(re.search(r"\bexport\s+default\b", text))
    has_module_exports = bool(re.search(r"\bmodule\.exports\s*=", text))
    for m in re.finditer(r"\bmodule\.exports\s*=\s*\{([^}]+)\}", text, re.DOTALL):
        for part in m.group(1).split(","):
            key = part.split(":", 1)[0].strip()
            if key:
                module_export_keys.add(key)
    return has_default, has_module_exports


def _extract_export_summary(text: str) -> Dict[str, Any]:
    named_exports: set = set()
    func_sigs: Dict[str, set] = {}
    star_exports: set = set()
    module_export_keys: set = set()
    for m in re.finditer(r"\bexport\s+(?:declare\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*(?:<[^>]*>)?\s*\(", text):
        fn_name = m.group(1)
        named_exports.add(fn_name)
        func_sigs.setdefault(fn_name, set()).add(_extract_balanced_parens(text, m.end() - 1))
    for m in re.finditer(r"\bexport\s+(?:declare\s+)?(?:const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)", text):
        named_exports.add(m.group(1))
    has_default, has_module_exports = _parse_reexports_and_cjs(text, named_exports, star_exports, module_export_keys)
    return {
        "named_exports": named_exports,
        "func_sigs": func_sigs,
        "star_exports": star_exports,
        "has_default": has_default,
        "has_module_exports": has_module_exports,
        "module_export_keys": module_export_keys,
    }
