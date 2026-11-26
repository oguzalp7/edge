"""Screenshot, URL, and auth-wall verification mixin for ProofVerifier."""

from collections import Counter
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.models import Ticket
from tools.common import normalize_target_path
from tools.common.paths import is_wsl_path


class ProofVerifierMediaMixin:
    """Provides screenshot hashing/resolution and URL/auth-wall verification helpers."""

    AUTH_TOKENS: Tuple[str, ...] = (
        "auth", "login", "signin", "sign-in", "oauth", "session", "sso", "password",
    )
    AUTH_URL_MARKERS: Tuple[str, ...] = ("/login", "/signin", "redirect=")

    @staticmethod
    def is_auth_ticket(ticket: Optional[Ticket]) -> bool:
        if not ticket:
            return False
        fields = (ticket.domain or "", ticket.branch_name or "", ticket.ticket_id or "", ticket.description or "", ticket.spec_path or "")
        combined = " ".join(fields).lower()
        tokens = set(re.findall(r"[a-z0-9-]+", combined)) | set(re.findall(r"[a-z0-9]+", combined))
        return any(tok in tokens for tok in ProofVerifierMediaMixin.AUTH_TOKENS)

    @staticmethod
    def resolve_screenshot_file(raw_path: str, search_roots: List[Path]) -> Optional[Path]:
        cleaned = str(raw_path or "").strip()
        if not cleaned:
            return None
        p = Path(cleaned)
        if p.is_absolute() or is_wsl_path(cleaned):
            norm = normalize_target_path(cleaned)
            return norm if norm.is_file() else None
        rel = cleaned[2:] if cleaned.startswith("./") else cleaned
        return next((cand for root in search_roots if (cand := Path(root) / rel).is_file()), None)

    @staticmethod
    def _hash_single_screenshot(raw_path: Any, search_roots: List[Path]) -> Tuple[bool, str, Dict[str, Any]]:
        if not isinstance(raw_path, str) or not raw_path.strip():
            return False, "QA proof receipt invariant failed: screenshot path must be a non-empty string.", {"error": "MISSING_SCREENSHOTS"}
        resolved = ProofVerifierMediaMixin.resolve_screenshot_file(raw_path, search_roots)
        if not resolved:
            return False, f"QA proof verification failed: screenshot file not found '{raw_path}'.", {"error": "MISSING_SCREENSHOT_FILE", "missing_file": raw_path}
        if resolved.stat().st_size <= 0:
            return False, f"QA proof verification failed: screenshot file is zero bytes '{raw_path}'.", {"error": "EMPTY_SCREENSHOT_FILE", "empty_file": raw_path}
        return True, "", {"digest": hashlib.sha256(resolved.read_bytes()).hexdigest()}

    @staticmethod
    def verify_screenshots(screenshot_paths: Any, search_roots: List[Path]) -> Tuple[bool, str, Dict[str, Any]]:
        if not isinstance(screenshot_paths, list) or len(screenshot_paths) == 0:
            return False, "QA proof receipt invariant failed: 'screenshot_paths' must be a non-empty list.", {"error": "MISSING_SCREENSHOTS"}
        hashes: Dict[str, str] = {}
        for raw_path in screenshot_paths:
            ok, msg, info = ProofVerifierMediaMixin._hash_single_screenshot(raw_path, search_roots)
            if not ok:
                return False, msg, info
            hashes[str(raw_path)] = info["digest"]
        if len(screenshot_paths) > 1 and len(set(hashes.values())) < len(screenshot_paths):
            dups = [d for d, c in Counter(hashes.values()).items() if c > 1]
            return False, "QA proof verification failed: duplicate SHA-256 screenshot hashes detected.", {
                "error": "DUPLICATE_SCREENSHOT_EVIDENCE", "duplicate_hashes": dups, "screenshot_hashes": hashes,
            }
        return True, "", {"screenshot_hashes": hashes}

    @staticmethod
    def _is_non_empty_str_list(val: Any) -> bool:
        return isinstance(val, list) and len(val) > 0 and all(isinstance(x, str) and x.strip() for x in val)

    @staticmethod
    def _is_auth_wall_url(url: str) -> bool:
        low = url.lower()
        return any(marker in low for marker in ProofVerifierMediaMixin.AUTH_URL_MARKERS)

    @staticmethod
    def verify_urls(data: Dict[str, Any], ticket: Optional[Ticket]) -> Tuple[bool, str, Dict[str, Any]]:
        visited = data.get("visited_urls")
        if not ProofVerifierMediaMixin._is_non_empty_str_list(visited):
            return False, "QA proof receipt invariant failed: 'visited_urls' must be a non-empty list.", {"error": "INVALID_VISITED_URLS"}
        all_urls = [str(u).strip() for u in visited]
        final_urls = data.get("final_urls")
        if isinstance(final_urls, list):
            all_urls.extend(str(u).strip() for u in final_urls if isinstance(u, str) and u.strip())
        if not ProofVerifierMediaMixin.is_auth_ticket(ticket):
            trapped = [u for u in all_urls if ProofVerifierMediaMixin._is_auth_wall_url(u)]
            if trapped:
                return False, f"QA proof verification failed: auth-wall redirect trap detected in {trapped}.", {"error": "AUTH_WALL_REDIRECT_TRAP", "trapped_urls": trapped}
        return True, "", {"visited_urls": visited}
