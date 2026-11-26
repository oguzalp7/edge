"""Pre-tool boundary guard for Edge Brigade stations (stdlib-only)."""

from pathlib import Path
import sys
from typing import Any, Dict, Optional

from tools.brigade.guard.afk_guard import _is_schema_target, apply_afk_guard, is_afk_session
from tools.brigade.guard.no_mistakes import is_no_mistakes_invocation
from tools.brigade.guard.role_detection import detect_session_role, get_target_file, normalize_role
from tools.brigade.guard.station_selector import _handle_invoke_subagent_guard
from tools.brigade.guard.swarm_guard import _handle_swarm_guard
from tools.brigade.guard.wsl_guard import _handle_run_command_wsl_guard

_SPEC_WRITER_ALLOWED_DIRS = ("specs/", "/specs/", ".edge/", "/.edge/", ".lavish/", "/.lavish/")
_SPEC_WRITER_ROOT_DOCS = ("coding_standards.md", "agents.md", "program_system_instructions.md", "context.md")
_SPEC_WRITER_FORBIDDEN_CODE_SEGMENTS = ("/src/", "src/", "/tests/", "tests/", "/test/", "test/", "/app/", "app/", "/lib/", "lib/", "/db/", "db/", "/drizzle/", "drizzle/")
_ALLOWED_READ_KEYWORDS = ("/brain/", "brain/", ".edge/", "/.edge/", ".lavish/", "/.lavish/", "specs/", "/specs/", "coding_standards", "agents.md", "gemini.md", "readme.md", "architecture.md", "package.json", "tsconfig.json", "treehouse.toml")
_CODE_OR_TEST_KEYWORDS = ("/src/", "src/", "/app/", "app/", "/lib/", "lib/", "/db/", "db/", "/drizzle/", "drizzle/", "/tests/", "tests/", ".test.", ".spec.")
_MUTATION_TOOLS = ("write_file", "edit_file", "write_to_file", "replace_file_content")
_READ_ONLY_ROLES = ("EXAMINER", "RESEARCHER", "SPEC_CRITIC")


def _is_spec_writer_allowed_target(target_file: str) -> bool:
    norm = target_file.strip().replace("\\", "/").lower()
    if any(k in norm for k in _SPEC_WRITER_ALLOWED_DIRS):
        return True
    if any(seg in norm for seg in _SPEC_WRITER_FORBIDDEN_CODE_SEGMENTS):
        return False
    return Path(norm).name in _SPEC_WRITER_ROOT_DOCS


def _check_role_write_boundaries(role: str, target_file: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if role == "ORCHESTRATOR":
        if not (any(k in target_file for k in ("/brain/", "brain/", ".edge/", "/.edge/")) or "artifactmetadata" in str(args).lower()):
            return {"decision": "deny", "reason": "❌ [EDGE ORCHESTRATOR HARD GUARD]: Kök Ajan (Orkestratör) Yeşil Alandadır ve doğrudan kaynak kod yazamaz / dosya düzenleyemez! Yalnızca Antigravity brain artifact'leri (`<appDataDir>/brain/**`) ve `.edge/**` durum dosyalarını yazabilirsiniz. Kaynak kod değişikliklerini ilgili istasyon çalışanına (coder, surgeon, seam_architect vb.) delege etmelisiniz."}
    canonical_role = normalize_role(role) or role
    if canonical_role in _READ_ONLY_ROLES or role in _READ_ONLY_ROLES:
        st_name = canonical_role if canonical_role in _READ_ONLY_ROLES else role
        return {"decision": "deny", "reason": f"❌ [STATION PURITY GUARD]: '{st_name}' istasyonu salt-okunur (read-only) denetçidir. Hiçbir dosyada değişiklik yapamaz / kod yazamaz!"}
    if role == "SPEC_WRITER" and not _is_spec_writer_allowed_target(target_file):
        return {"decision": "deny", "reason": f"❌ [SPEC BOUNDARY GUARD]: SPEC_WRITER yalnızca `specs/**`, `.edge/**` ve `.lavish/**` dizinlerinde şartname ve prototip yazabilir. Üretim koduna (`{target_file}`) dokunamaz!"}
    if role == "SEAM_ARCHITECT":
        if not (any(k in target_file for k in ("tests/", "/tests/", ".test.", ".spec.")) or any(k in target_file for k in ("types/", "/types/", "contracts/", "/contracts/"))):
            return {"decision": "deny", "reason": f"❌ [TDD SEAM GUARD]: SEAM_ARCHITECT yalnızca `tests/**` altında kırmızı testler ve `src/types/**` altında sözleşmeler yazabilir. Üretim kodunu (`{target_file}`) CODER istasyonuna bırakmalıdır!"}
    if role == "CODER" and any(k in target_file for k in ("tests/", "/tests/", ".test.", ".spec.")):
        return {"decision": "deny", "reason": f"❌ [TEST IMMUTABILITY GUARD]: CODER istasyonu test dosyalarını (`{target_file}`) değiştiremez veya gevşetemez! Kırmızı testleri yeşile çevirmek için yalnızca `src/` altındaki üretim kodunu düzenlemelisiniz."}
    if role == "SURGEON" and _is_schema_target(target_file):
        return {"decision": "deny", "reason": f"❌ [MIGRATIONGATE GUARD]: SURGEON istasyonu veritabanı şemasını veya migrasyonları (`{target_file}`) doğrudan değiştiremez! Şema değişiklikleri ayrı bir mimari migrasyon gerektirir."}
    if role == "QA_ENGINEER" and any(k in target_file for k in ("/src/", "src/", "/app/", "app/", "/lib/", "lib/", "/db/", "db/", "/drizzle/", "drizzle/")):
        return {"decision": "deny", "reason": f"❌ [QA BOUNDARY GUARD]: QA_ENGINEER (Sommelier) istasyonu uçtan uca tarayıcı ve davranış denetçisidir. Üretim kodunu (`{target_file}`) düzenleyemez! Bulunan hatalar ve görsel kusurlar Orkestratör üzerinden SURGEON veya CODER istasyonuna raporlanmalıdır."}
    return None


def _check_orchestrator_read_guard(role: str, target_file: str) -> Optional[Dict[str, Any]]:
    if role != "ORCHESTRATOR":
        return None
    if any(k in target_file for k in _CODE_OR_TEST_KEYWORDS) and not any(k in target_file for k in _ALLOWED_READ_KEYWORDS):
        return {"decision": "deny", "reason": f"❌ [EDGE ORCHESTRATOR LEAN CONTEXT GUARD]: Kök Ajan (Orkestratör) Yeşil Alandadır ve doğrudan üretim veya test kodu okuyamaz! Hedef dosya: `{target_file}`. Kod incelemesi ve kök neden analizi (RCA) için RESEARCHER istasyonunu (`invoke_subagent` / `send_message`) görevlendiriniz. Orkestratör yalnızca `.edge/**`, `specs/**`, `coding_standards.md` ve artifact belgelerini okuyabilir."}
    return None


def handle_pre_tool(payload: dict) -> dict:
    """Evaluate pre-tool lifecycle policies, preserving facade monkeypatch hooks."""
    facade = sys.modules.get("tools.brigade.orchestrator_guard")
    nm_fn = getattr(facade, "is_no_mistakes_invocation", is_no_mistakes_invocation) if facade else is_no_mistakes_invocation
    if nm_fn(payload)[0]:
        return {"decision": "allow", "reason": "NO_MISTAKES_HEADLESS_EXEMPTION"}
    afk_fn = getattr(facade, "is_afk_session", is_afk_session) if facade else is_afk_session
    is_afk, afk_mode = afk_fn(payload)
    if is_afk:
        apply_fn = getattr(facade, "apply_afk_guard", apply_afk_guard) if facade else apply_afk_guard
        return apply_fn(payload, afk_mode) or {"decision": "allow"}
    tool_call = payload.get("toolCall", {})
    tool_name, args = tool_call.get("name", ""), tool_call.get("args", {})
    role_fn = getattr(facade, "detect_session_role", detect_session_role) if facade else detect_session_role
    role, _ = role_fn(payload)
    parent_cid = payload.get("conversationId", "")
    wsl_fn = getattr(facade, "_handle_run_command_wsl_guard", _handle_run_command_wsl_guard) if facade else _handle_run_command_wsl_guard
    wsl_res = wsl_fn(tool_name, args)
    if wsl_res is not None:
        return wsl_res
    if tool_name == "invoke_subagent":
        sub_fn = getattr(facade, "_handle_invoke_subagent_guard", _handle_invoke_subagent_guard) if facade else _handle_invoke_subagent_guard
        return sub_fn(args, parent_cid)
    if tool_name == "swarm":
        sw_fn = getattr(facade, "_handle_swarm_guard", _handle_swarm_guard) if facade else _handle_swarm_guard
        return sw_fn(args, parent_cid) or {"decision": "allow"}
    target_file = get_target_file(args)
    if tool_name in _MUTATION_TOOLS:
        res = _check_role_write_boundaries(role, target_file, args)
        if res is not None:
            return res
    if tool_name in ("read_file", "view_file"):
        res = _check_orchestrator_read_guard(role, target_file)
        if res is not None:
            return res
    return {"decision": "allow"}
