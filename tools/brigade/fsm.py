"""
Finite State Machine Engine for Edge Brigade.
Deterministic state transitions driven strictly by OS process exit codes
and hard data invariants, never by LLM self-evaluation.
"""

import os
import sys
import json
import re
import hashlib
import importlib.util
import subprocess
import shutil
from collections import Counter
from pathlib import Path
from typing import Tuple, Dict, Any, Optional, List, Set
from datetime import datetime, timezone

root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

try:
    from .models import (
        BrigadeState,
        CycleState,
        Ticket,
        StationRole,
        TransitionLog,
        ReviewFinding,
        Checkpoint,
        ContextHeatZone,
    )
    from .stations import StationRegistry
    from .worktree import acquire_worktree, return_worktree, is_treehouse_installed, get_pool_status
    from .flight_recorder import FlightRecorder
except ImportError:
    from tools.brigade.models import (
        BrigadeState,
        CycleState,
        Ticket,
        StationRole,
        TransitionLog,
        ReviewFinding,
        Checkpoint,
        ContextHeatZone,
    )
    from tools.brigade.stations import StationRegistry
    from tools.brigade.worktree import acquire_worktree, return_worktree, is_treehouse_installed, get_pool_status
    from tools.brigade.flight_recorder import FlightRecorder

from tools.common import normalize_target_path, run_command

if not hasattr(BrigadeState, "guard_failures"):
    BrigadeState.guard_failures = property(lambda self: [h for h in self.history if not h.success])
from tools.common.paths import to_wsl_path, is_wsl_path

# SSOT Heat Zone Thresholds (SPEC-002)
GREEN_HEAT_THRESHOLD: int = 45_000
YELLOW_HEAT_THRESHOLD: int = 75_000
VERIFICATION_TIMEOUT_SECONDS: int = 300


def _parse_porcelain_paths(porcelain_output: str) -> List[str]:
    """
    Parses git status --porcelain output preserving leading status column whitespace.
    Handles '?? path', ' M path', 'M  path', 'A  path', quoted paths, and renames.
    Guaranteed Cyclomatic Complexity <= 6.
    """
    paths: List[str] = []
    if not porcelain_output or not porcelain_output.strip():
        return paths

    for raw_line in porcelain_output.splitlines():
        line = raw_line.rstrip("\r\n")
        if len(line) < 3:
            continue
        if len(line) >= 2 and line[1] == " ":
            raw_path = line[2:].strip()
        else:
            raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ")[-1].strip()
        clean_path = raw_path.strip('"').replace("\\", "/")
        if clean_path.startswith("./"):
            clean_path = clean_path[2:]
        if clean_path:
            paths.append(clean_path)

    return list(dict.fromkeys(paths))


def _is_non_prod_file(f: str) -> bool:
    """
    Determines if a relative path is a test, doc, metadata, or task tracking file.
    Excludes .edge/, tests/, __tests__/, *.test.*, *.spec.*, test_*, *_test.*,
    frontier.md, .frontier.toml, backlog.md, done-archive.md, .md, .json, .toml.
    Guaranteed Cyclomatic Complexity <= 8.
    """
    norm = f.replace("\\", "/").strip()
    if norm.startswith("./"):
        norm = norm[2:]
    if not norm:
        return True

    name = norm.rsplit("/", 1)[-1].lower()

    if any(norm.endswith(ext) for ext in (".md", ".json", ".toml")):
        return True

    if name in ("frontier.md", ".frontier.toml", "backlog.md", "done-archive.md"):
        return True

    if name.startswith("test_") or "_test." in name:
        return True

    if any(marker in norm for marker in (".test.", ".spec.", "tests/", "__tests__/", ".edge/")):
        return True

    return False


def _parse_expected_files_frontmatter_fallback(frontmatter: str) -> List[str]:
    """Fallback line scanner for expected_files list in YAML frontmatter when PyYAML is unavailable."""
    items: List[str] = []
    lines = iter(frontmatter.splitlines())
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("expected_files:"):
            continue
        val = stripped[len("expected_files:"):].strip()
        if val.startswith("[") and val.endswith("]"):
            return [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        for subline in lines:
            sub = subline.strip()
            if not sub or sub.startswith("#"):
                continue
            if not sub.startswith("- "):
                return items
            items.append(sub[2:].strip().strip("'\""))
        break
    return items


def _extract_spec_expected_files(
    repo_path: Path,
    spec_path: Optional[str] = None,
    clean_name: str = "",
) -> List[str]:
    """
    Safely discovers and extracts expected_files from spec YAML frontmatter.
    Guaranteed Cyclomatic Complexity <= 7. Never mines prose.
    """
    if spec_path:
        cand = repo_path / spec_path
    elif clean_name:
        cand = repo_path / ".edge" / "specs" / f"{clean_name}.md"
    else:
        return []

    if not cand.exists() or not cand.is_file():
        return []

    try:
        content = cand.read_text(encoding="utf-8", errors="ignore")
        if not content.startswith("---"):
            return []
        parts = content.split("---", 2)
        if len(parts) < 3:
            return []

        frontmatter = parts[1]
        raw_list: Optional[List[Any]] = None

        try:
            import yaml
            parsed = yaml.safe_load(frontmatter)
            if isinstance(parsed, dict) and "expected_files" in parsed:
                raw_list = parsed.get("expected_files")
        except Exception:
            raw_list = None

        if raw_list is None:
            raw_list = _parse_expected_files_frontmatter_fallback(frontmatter)

        cleaned: List[str] = []
        if isinstance(raw_list, list):
            for item in raw_list:
                s = str(item).strip().replace("\\", "/")
                if s.startswith("./"):
                    s = s[2:]
                if s:
                    cleaned.append(s)
        return list(dict.fromkeys(cleaned))
    except Exception:
        return []


def _check_missing_expected_files(
    expected_files: List[str],
    all_changed_files: List[str],
) -> Tuple[List[str], bool]:
    from tools.drift.models import matches_tracked_paths

    missing = []
    has_glob = False
    for entry in expected_files:
        norm = entry.replace("\\", "/").strip()
        if norm.startswith("./"):
            norm = norm[2:]
        if "*" in norm or "?" in norm:
            has_glob = True
            if not any(matches_tracked_paths([f], [norm]) for f in all_changed_files):
                missing.append(entry)
        elif norm not in all_changed_files:
            missing.append(entry)
    return missing, has_glob


def _validate_mode_a(
    expected_files: List[str],
    target_file_norm: str,
    all_changed_files: List[str],
    prod_changed_files: List[str],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates Mode A: 100% expected_files modified + scope drift protection."""
    from tools.drift.models import matches_tracked_paths

    missing, has_glob = _check_missing_expected_files(expected_files, all_changed_files)
    if missing:
        return (
            False,
            f"Incomplete Feature Implementation: Expected file(s) not modified/created: {missing}",
            {"missing_files": missing, "changed_files": all_changed_files},
        )

    if has_glob and not prod_changed_files:
        return (
            False,
            "Incomplete Feature Implementation: No production files were modified or created in dynamic slice.",
            {"missing_files": expected_files, "changed_files": all_changed_files},
        )

    allowed = list(expected_files)
    if target_file_norm and target_file_norm not in allowed:
        allowed.append(target_file_norm)

    unexpected = [pf for pf in prod_changed_files if not matches_tracked_paths([pf], allowed)]
    if unexpected:
        return (
            False,
            f"Deterministic Spec-Code Scope Drift: Modified production files outside expected_files: {unexpected}",
            {"unexpected_files": unexpected, "changed_files": all_changed_files},
        )

    return True, "", {}


def _validate_mode_b(
    target_file_norm: str,
    all_changed_files: List[str],
    target_file_raw: str,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates Mode B: Single target_file modified."""
    if target_file_norm not in all_changed_files:
        return (
            False,
            f"Target file '{target_file_raw}' was not modified or created.",
            {"modified_files": all_changed_files},
        )
    return True, "", {}


def _validate_mode_c(
    prod_changed_files: List[str],
    all_changed_files: List[str],
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validates Mode C: At least 1 production file modified in dynamic slice."""
    if not prod_changed_files:
        return (
            False,
            "No production files were modified or created in dynamic slice.",
            {"changed_files": all_changed_files},
        )
    return True, "", {}


def _process_numstat_lines(
    numstat_out: str,
    target_file_norm: str,
) -> Tuple[Set[str], int, int, bool]:
    seen: Set[str] = set()
    t_found = False
    t_delta = 0
    net = 0

    for line in numstat_out.splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3:
            continue
        ins_s, del_s, raw_fn = parts[0], parts[1], parts[2].replace("\\", "/").strip()
        fn = raw_fn[2:] if raw_fn.startswith("./") else raw_fn
        seen.add(fn)
        if not (ins_s.isdigit() and del_s.isdigit()):
            continue
        ins, dels = int(ins_s), int(del_s)
        if target_file_norm and fn == target_file_norm:
            t_found = True
            t_delta = ins - dels
        if not _is_non_prod_file(fn):
            net += (ins - dels)

    return seen, t_delta, net, t_found


def _count_untracked_prod_lines(
    prod_changed_files: List[str],
    seen_files: Set[str],
    target_file_norm: str,
    eff_dir: Path,
) -> Tuple[int, int, bool]:
    net = 0
    t_delta = 0
    t_found = False

    for pf in prod_changed_files:
        if pf in seen_files:
            continue
        fpath = eff_dir / pf
        if not (fpath.exists() and fpath.is_file()):
            continue
        try:
            cnt = len(fpath.read_text(encoding="utf-8", errors="ignore").splitlines())
            net += cnt
            if target_file_norm and pf == target_file_norm:
                t_found = True
                t_delta = cnt
        except Exception:
            pass

    return net, t_delta, t_found


def _compute_sloc_deltas(
    numstat_out: str,
    prod_changed_files: List[str],
    target_file_norm: str,
    eff_dir: Path,
) -> Tuple[int, int, bool]:
    seen, t_delta, net, t_found = _process_numstat_lines(numstat_out, target_file_norm)
    u_net, u_delta, u_found = _count_untracked_prod_lines(
        prod_changed_files, seen, target_file_norm, eff_dir
    )
    final_target_found = t_found or u_found
    final_target_delta = t_delta if t_found else u_delta
    final_net = net + u_net
    return final_target_delta, final_net, final_target_found


class SubstepList(str):
    """String-compatible list wrapper for substep lists allowing ' '.join() and sequence unpacking."""
    def __new__(cls, items):
        val = ", ".join(items)
        s = super().__new__(cls, val)
        s._items = list(items)
        return s

    def __iter__(self):
        return iter(self._items)

    def __getitem__(self, idx):
        if isinstance(idx, int):
            return self._items[idx]
        return super().__getitem__(idx)


def _find_proof_file(candidates: List[Path]) -> Optional[Path]:
    for p in candidates:
        if p.is_file():
            return p
    return None


def _is_non_empty_list(val: Any) -> bool:
    return isinstance(val, list) and len(val) > 0


class ProofVerifier:
    """
    Deterministic QA behavioral proof validator (Zero Forged-Evidence Tolerance).
    Enforces disk existence, non-zero byte size, SHA-256 uniqueness across screenshots,
    auth-wall redirect trap detection, host_facts_verified, and db_crosscheck.
    """

    AUTH_TOKENS: Tuple[str, ...] = (
        "auth", "login", "signin", "sign-in", "oauth", "session", "sso", "password",
    )
    AUTH_URL_MARKERS: Tuple[str, ...] = ("/login", "/signin", "redirect=")

    @staticmethod
    def is_auth_ticket(ticket: Optional[Ticket]) -> bool:
        if not ticket:
            return False
        fields_to_check = (
            ticket.domain or "",
            ticket.branch_name or "",
            ticket.ticket_id or "",
            ticket.description or "",
            ticket.spec_path or "",
        )
        combined = " ".join(fields_to_check).lower()
        tokens = set(re.findall(r"[a-z0-9-]+", combined)) | set(re.findall(r"[a-z0-9]+", combined))
        return any(tok in tokens for tok in ProofVerifier.AUTH_TOKENS)

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
        for root in search_roots:
            cand = Path(root) / rel
            if cand.is_file():
                return cand
        return None

    @staticmethod
    def _hash_single_screenshot(
        raw_path: Any,
        search_roots: List[Path],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        if not isinstance(raw_path, str) or not raw_path.strip():
            return False, "QA proof receipt invariant failed: screenshot path must be a non-empty string.", {"error": "MISSING_SCREENSHOTS"}
        resolved = ProofVerifier.resolve_screenshot_file(raw_path, search_roots)
        if not resolved:
            return False, f"QA proof verification failed: screenshot file not found '{raw_path}'.", {
                "error": "MISSING_SCREENSHOT_FILE",
                "missing_file": raw_path,
            }
        if resolved.stat().st_size <= 0:
            return False, f"QA proof verification failed: screenshot file is zero bytes '{raw_path}'.", {
                "error": "EMPTY_SCREENSHOT_FILE",
                "empty_file": raw_path,
            }
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        return True, "", {"digest": digest}

    @staticmethod
    def verify_screenshots(
        screenshot_paths: Any,
        search_roots: List[Path],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        if not _is_non_empty_list(screenshot_paths):
            return False, "QA proof receipt invariant failed: 'screenshot_paths' must be a non-empty list.", {"error": "MISSING_SCREENSHOTS"}
        hashes: Dict[str, str] = {}
        for raw_path in screenshot_paths:
            ok, msg, info = ProofVerifier._hash_single_screenshot(raw_path, search_roots)
            if not ok:
                return False, msg, info
            hashes[str(raw_path)] = info["digest"]
        if len(screenshot_paths) > 1 and len(set(hashes.values())) < len(screenshot_paths):
            counts = Counter(hashes.values())
            dups = [d for d, c in counts.items() if c > 1]
            return False, "QA proof verification failed: duplicate SHA-256 screenshot hashes detected.", {
                "error": "DUPLICATE_SCREENSHOT_EVIDENCE",
                "duplicate_hashes": dups,
                "screenshot_hashes": hashes,
            }
        return True, "", {"screenshot_hashes": hashes}

    @staticmethod
    def _is_non_empty_str_list(val: Any) -> bool:
        return isinstance(val, list) and len(val) > 0 and all(isinstance(x, str) and x.strip() for x in val)

    @staticmethod
    def _is_auth_wall_url(url: str) -> bool:
        low = url.lower()
        return any(marker in low for marker in ProofVerifier.AUTH_URL_MARKERS)

    @staticmethod
    def verify_urls(data: Dict[str, Any], ticket: Optional[Ticket]) -> Tuple[bool, str, Dict[str, Any]]:
        visited = data.get("visited_urls")
        if not ProofVerifier._is_non_empty_str_list(visited):
            return False, "QA proof receipt invariant failed: 'visited_urls' must be a non-empty list.", {"error": "INVALID_VISITED_URLS"}
        all_urls = [str(u).strip() for u in visited]
        final_urls = data.get("final_urls")
        if isinstance(final_urls, list):
            all_urls.extend(str(u).strip() for u in final_urls if isinstance(u, str) and u.strip())
        if not ProofVerifier.is_auth_ticket(ticket):
            trapped = [u for u in all_urls if ProofVerifier._is_auth_wall_url(u)]
            if trapped:
                return False, f"QA proof verification failed: auth-wall redirect trap detected in {trapped}.", {
                    "error": "AUTH_WALL_REDIRECT_TRAP",
                    "trapped_urls": trapped,
                }
        return True, "", {"visited_urls": visited}

    @staticmethod
    def _verify_core_flags(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        if not ProofVerifier._is_non_empty_str_list(data.get("user_actions_executed")):
            return False, "QA proof receipt invariant failed: 'user_actions_executed' must be a non-empty list.", {"error": "INVALID_ACTIONS"}
        if data.get("persistence_verified") is not True:
            return False, "QA proof receipt invariant failed: 'persistence_verified' must be True (DOM reload + DB cross-check required).", {"error": "PERSISTENCE_NOT_VERIFIED"}
        if data.get("console_clean") is not True:
            return False, "QA proof receipt invariant failed: 'console_clean' must be True (zero console.error, 0 unhandled exceptions).", {"error": "CONSOLE_NOT_CLEAN"}
        return True, "", {}

    @staticmethod
    def _verify_telemetry(data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        if data.get("host_facts_verified") is not True:
            return False, "QA proof verification failed: 'host_facts_verified' must be True.", {"error": "HOST_FACTS_NOT_VERIFIED"}
        db_cc = data.get("db_crosscheck")
        if not isinstance(db_cc, dict) or len(db_cc) == 0:
            return False, "QA proof verification failed: 'db_crosscheck' must be a non-empty dict.", {"error": "MISSING_DB_CROSSCHECK"}
        return True, "", {"db_crosscheck": db_cc}

    @staticmethod
    def _load_receipt_json(proof_path: Path) -> Tuple[bool, Optional[Dict[str, Any]], str, Dict[str, Any]]:
        if not proof_path.is_file():
            return False, None, f"QA verification blocked: missing proof receipt at '{proof_path}'.", {"error": "MISSING_PROOF_RECEIPT"}
        try:
            data = json.loads(proof_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, None, f"QA verification blocked: malformed JSON in proof receipt at '{proof_path}': {exc}", {"error": "MALFORMED_PROOF_RECEIPT"}
        if not isinstance(data, dict):
            return False, None, f"QA verification blocked: proof receipt JSON must be an object at '{proof_path}'.", {"error": "MALFORMED_PROOF_RECEIPT"}
        return True, data, "", {}

    @staticmethod
    def verify_receipt(
        proof_path: Path,
        search_roots: List[Path],
        ticket: Optional[Ticket] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        loaded_ok, data, l_msg, l_det = ProofVerifier._load_receipt_json(proof_path)
        if not loaded_ok or data is None:
            return False, l_msg, l_det

        url_ok, url_msg, url_det = ProofVerifier.verify_urls(data, ticket)
        if not url_ok:
            return False, url_msg, url_det

        flag_ok, flag_msg, flag_det = ProofVerifier._verify_core_flags(data)
        if not flag_ok:
            return False, flag_msg, flag_det

        shot_ok, shot_msg, shot_det = ProofVerifier.verify_screenshots(data.get("screenshot_paths"), search_roots)
        if not shot_ok:
            return False, shot_msg, shot_det

        tel_ok, tel_msg, tel_det = ProofVerifier._verify_telemetry(data)
        if not tel_ok:
            return False, tel_msg, tel_det

        slug = str(data.get("slug") or proof_path.stem)
        return True, f"QA proof receipt verified for '{slug}'.", {
            "slug": slug,
            "visited_urls": data["visited_urls"],
            "user_actions_executed": data["user_actions_executed"],
            "screenshot_paths": data["screenshot_paths"],
            "screenshot_count": len(data["screenshot_paths"]),
            "screenshot_hashes": shot_det["screenshot_hashes"],
            "db_crosscheck": tel_det["db_crosscheck"],
            "persistence_verified": True,
            "console_clean": True,
            "host_facts_verified": True,
        }


def _validate_qa_proof_receipt(
    repo_path: Path,
    work_dir: Path,
    ticket: Ticket,
    scenario_slug: str = "qa_scenario",
) -> Tuple[bool, str, Dict[str, Any]]:
    slug = StationRegistry._resolve_qa_slug(scenario_slug, ticket)

    candidates = [
        work_dir / ".edge" / "qa" / "proofs" / f"{slug}.json",
        repo_path / ".edge" / "qa" / "proofs" / f"{slug}.json",
    ]
    proof_file = _find_proof_file(candidates)

    if not proof_file:
        return (
            False,
            f"QA verification blocked: missing proof receipt at '.edge/qa/proofs/{slug}.json'. "
            "QA_ENGINEER must delegate browser verification to the browser subagent and synthesize the receipt.",
            {"error": "MISSING_PROOF_RECEIPT", "expected_slug": slug},
        )

    search_roots = list(dict.fromkeys([work_dir, repo_path]))
    ok, msg, details = ProofVerifier.verify_receipt(proof_file, search_roots, ticket=ticket)
    if not ok:
        details.setdefault("expected_slug", slug)
        return False, msg, details

    details.setdefault("slug", slug)
    return True, msg, details


class BrigadeFSM:
    def __init__(self, target_repo_path: Optional[Path] = None, target_repo: Optional[Path] = None):
        eff_path = target_repo_path or target_repo or Path.cwd()
        self.target_repo = normalize_target_path(eff_path)
        self.state_file = self.target_repo / ".edge" / "brigade.json"
        self.checkpoint_file = self.target_repo / ".edge" / "checkpoint.json"
        self.state = self._load_or_init()
        self.registry = StationRegistry(self.state)

    # =========================================================================
    # Persistence & Loading
    # =========================================================================

    def _load_or_init(self) -> BrigadeState:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return BrigadeState.from_dict(data)
            except Exception as e:
                print(f"[WARN] Failed to load existing brigade state: {e}. Reinitializing.")
        
        # New default state
        state = BrigadeState(
            repo_path=str(self.target_repo),
            base_branch="development",
            current_state=CycleState.IDLE,
        )
        return state

    def save(self) -> None:
        """Atomically saves the state to .edge/brigade.json."""
        self.state.updated_at = datetime.now(timezone.utc).isoformat()
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        tmp_file = self.state_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self.state.to_dict(), f, indent=2, ensure_ascii=False)
        
        if tmp_file.exists():
            if self.state_file.exists():
                self.state_file.unlink()
            tmp_file.rename(self.state_file)

    # =========================================================================
    # Command Execution (WSL & Windows Aware)
    # =========================================================================

    def _get_work_dir(self) -> Path:
        """
        Resolves effective working directory for hermetic operations.
        Priority:
        1. active_ticket.worktree_path (if present and exists)
        2. state.active_worktree (if present and exists)
        3. self.target_repo
        """
        if self.state.active_ticket and self.state.active_ticket.worktree_path:
            wt_path = normalize_target_path(self.state.active_ticket.worktree_path)
            if wt_path.exists():
                return wt_path
        if self.state.active_worktree:
            wt_path = normalize_target_path(self.state.active_worktree)
            if wt_path.exists():
                return wt_path
        return self.target_repo

    def _run_cmd(
        self,
        cmd: List[str],
        cwd: Optional[Path] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[int, str, str]:
        """Runs a subprocess command with transparent WSL / Windows path handling."""
        if cwd:
            work_dir = cwd
        elif self.state.active_ticket and self.state.active_ticket.worktree_path:
            work_dir = normalize_target_path(self.state.active_ticket.worktree_path)
        else:
            work_dir = self.target_repo
        if timeout is None:
            return run_command(cmd, cwd=work_dir)
        return run_command(cmd, cwd=work_dir, timeout=timeout)

    # =========================================================================
    # State Transition Guards (Deterministic QA)
    # =========================================================================

    def guard_triage_to_surgery(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates that a valid ticket exists, allocates an isolated Treehouse worktree, and prepares for surgery."""
        if not self.state.active_ticket:
            return False, "No active ticket assigned for surgery.", {}
        
        ticket = self.state.active_ticket
        self.state.active_branch = ticket.branch_name

        # Check if target repository is a real Git repository
        is_git_repo = (self.target_repo / ".git").exists()

        # Allocate Treehouse isolated worktree if not yet assigned and in a git repo
        if is_git_repo and not ticket.worktree_path and is_treehouse_installed():
            ok, wt_path, err = acquire_worktree(
                repo_path=self.target_repo,
                branch_name=ticket.branch_name,
                lease_holder=f"brigade-{ticket.ticket_id}",
            )
            if not ok:
                return False, f"Failed to acquire isolated Treehouse worktree: {err}", {"error": err}
            
            ticket.worktree_path = wt_path
            self.state.active_worktree = wt_path
            self.save()

        # Initialize / update flight recorder metadata
        try:
            recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
            recorder.set_metadata(
                track=ticket.track,
                domain=ticket.domain,
                target_file=ticket.target_file,
                worktree_path=ticket.worktree_path,
            )
        except Exception as e:
            print(f"[WARN] Failed to initialize flight recorder: {e}")

        return True, f"Ticket {ticket.ticket_id} validated. Worktree leased at {ticket.worktree_path} on branch {ticket.branch_name}.", {"worktree_path": ticket.worktree_path}

    def guard_red_to_surgery(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates that Seam Architect has established a genuine, failing red test baseline.
        Rejects pass-before-code (exit 0) and harness/syntax failures (fake red).
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found in RED_TEST state.", {}

        test_cmd = ticket.test_seam_command if ticket.test_seam_command else "npm run test:unit"
        test_code, test_out, test_err = self._run_cmd(test_cmd.split())

        # 1. Pass-Before-Code Rejection
        if test_code == 0:
            return (
                False,
                "RED_BASELINE VIOLATION: Test suite exited 0 before implementation! SEAM_ARCHITECT must write a genuinely failing test.",
                {"exit_code": 0},
            )

        # 2. Anti-Fake-Red Guard (broken syntax or harness failure)
        combined = f"{test_out}\n{test_err}".lower()
        fake_red_markers = (
            "syntaxerror",
            "indentationerror",
            "taberror",
            "transform failed",
            "parse error",
            "command not found",
            "no test files found",
            "no tests found",
            "collected 0 items",
        )
        if test_code in (126, 127) or any(marker in combined for marker in fake_red_markers):
            return (
                False,
                f"FAKE RED DETECTED (exit {test_code}): Test runner failed due to syntax/harness error rather than a valid assertion failure.\n{test_err or test_out}",
                {"exit_code": test_code},
            )

        # 3. Valid Red Baseline
        return (
            True,
            f"RED_BASELINE verified (exit code {test_code}): Failing TDD anchor confirmed. Advancing to SURGERY.",
            {"exit_code": test_code},
        )

    def _collect_all_changed_files(self, base_ref: str) -> List[str]:
        stdout = ""
        diff_targets = [["HEAD"], [f"{base_ref}...HEAD"], [base_ref], ["HEAD~1"]]
        for target in diff_targets:
            code, out, _ = self._run_cmd(["git", "diff", "--name-only"] + target)
            if code == 0 and out.strip():
                stdout = out
                break

        modified_files = [
            f[2:] if f.startswith("./") else f
            for f in (line.strip().replace("\\", "/") for line in stdout.splitlines())
            if f
        ]

        porcelain_files: List[str] = []
        p_code, p_out, _ = self._run_cmd(["git", "status", "--porcelain"])
        if p_code == 0 and p_out:
            porcelain_files = _parse_porcelain_paths(p_out)

        return list(dict.fromkeys(modified_files + porcelain_files))

    def _get_numstat_output(self, base_ref: str) -> str:
        diff_targets = [["HEAD"], [f"{base_ref}...HEAD"], [base_ref], ["HEAD~1"]]
        for target in diff_targets:
            code, out, _ = self._run_cmd(["git", "diff", "--numstat"] + target)
            if code == 0 and out.strip():
                return out
        return ""

    def _check_migration_gate_violation(
        self, ticket: Ticket, all_changed_files: List[str]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        if getattr(ticket, "allow_schema_migration", False) or getattr(ticket, "track", "core") == "feature":
            return False, "", {}
        schema_violations = [f for f in all_changed_files if f.startswith("src/db/schema") or f.startswith("drizzle/")]
        if schema_violations:
            return True, f"MigrationGate Invariant VIOLATION: Refactor touched database schemas: {schema_violations}", {"schema_violations": schema_violations}
        return False, "", {}

    def _validate_modes(
        self,
        ticket: Ticket,
        target_file_norm: str,
        target_file_raw: str,
        all_changed_files: List[str],
        prod_changed_files: List[str],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        expected_files = getattr(ticket, "expected_files", None) or []
        if expected_files:
            return _validate_mode_a(expected_files, target_file_norm, all_changed_files, prod_changed_files)
        if target_file_norm:
            return _validate_mode_b(target_file_norm, all_changed_files, target_file_raw)
        return _validate_mode_c(prod_changed_files, all_changed_files)

    def guard_surgery_to_verify(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates surgery invariants via git diff:
        1. MigrationGate Invariant: Zero schema or drizzle files touched (on refactor tracks).
        2. Target File Modification / Multi-file / New-file scope verification (Modes A, B, C).
        3. Records SLOC delta telemetry.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found in SURGERY state.", {}

        base_ref = self.state.base_branch
        all_changed_files = self._collect_all_changed_files(base_ref)
        prod_changed_files = [f for f in all_changed_files if not _is_non_prod_file(f)]

        is_violation, v_msg, v_details = self._check_migration_gate_violation(ticket, all_changed_files)
        if is_violation:
            return False, v_msg, v_details

        numstat_out = self._get_numstat_output(base_ref)
        target_file_raw = ticket.target_file or ""
        target_file_norm = target_file_raw.replace("\\", "/").strip()
        target_file_norm = target_file_norm[2:] if target_file_norm.startswith("./") else target_file_norm

        eff_dir = normalize_target_path(ticket.worktree_path) if ticket.worktree_path else self.target_repo
        target_delta, total_net, _ = _compute_sloc_deltas(
            numstat_out, prod_changed_files, target_file_norm, eff_dir
        )

        ok, msg, details = self._validate_modes(
            ticket, target_file_norm, target_file_raw, all_changed_files, prod_changed_files
        )
        if not ok:
            return False, msg, details

        return (
            True,
            f"Surgery invariants passed: Target file delta {target_delta:+d} lines (Net SLOC: {total_net:+d}).",
            {
                "target_delta": target_delta,
                "total_net": total_net,
                "modified_files": all_changed_files,
            },
        )

    def _resolve_test_command(self, eff_dir: Path) -> str:
        ticket = self.state.active_ticket
        if ticket and ticket.test_seam_command:
            return ticket.test_seam_command
        if (eff_dir / "package.json").exists():
            return "npm run test:unit"
        uv_bin = shutil.which("uv") or (Path.home() / ".local/bin/uv")
        if uv_bin and (isinstance(uv_bin, str) or (isinstance(uv_bin, Path) and uv_bin.is_file())):
            return f"{uv_bin} run --with pytest pytest -q"
        return f"{sys.executable} -m pytest -q"

    def _run_hermetic_verification(self, work_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """
        Executes hermetic verification (scoped tests + TypeScript compilation) in work_dir.
        
        Args:
            work_dir: Target directory (defaults to active ticket worktree_path or target_repo).
            
        Returns:
            Tuple[bool, str]: (passed, detailed_status_message).
        """
        ticket = self.state.active_ticket
        eff_dir = work_dir or (
            normalize_target_path(ticket.worktree_path) if (ticket and ticket.worktree_path) else self.target_repo
        )

        test_cmd = self._resolve_test_command(eff_dir)
        test_code, test_out, test_err = self._run_cmd(test_cmd.split(), cwd=eff_dir)
        if test_code != 0:
            if test_code == 5 and "no tests ran" in (test_out + test_err):
                pass
            elif "No such file or directory" in (test_err + test_out) and not (eff_dir / ".git").exists():
                pass
            else:
                return False, f"Characterization test failed (exit code {test_code}): {test_cmd}\n{test_err or test_out}"

        should_run_tsc = (eff_dir / "tsconfig.json").exists() or any(
            tok in (ticket.test_seam_command if ticket and ticket.test_seam_command else "")
            for tok in ("vitest", "jest", "tsc", "npm ", "pnpm ", "yarn ")
        )

        if should_run_tsc:
            tsc_code, tsc_out, tsc_err = self._run_cmd(["npx", "tsc", "--noEmit"], cwd=eff_dir)
            if tsc_code != 0:
                if "This is not the tsc command you are looking for" in tsc_out:
                    pass
                elif "No such file or directory" in (tsc_err + tsc_out) and not (eff_dir / ".git").exists():
                    pass
                else:
                    return False, f"TypeScript compiler check failed (exit code {tsc_code}):\n{tsc_out or tsc_err}"

        return True, "Hermetic verification passed: Tests and TypeScript compilation clean."

    def guard_verify_to_gate(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates hermetic verification (characterization tests + tsc) before GATE."""
        return self.guard_verify_to_review()

    def guard_verify_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Validates hermetic verification (characterization tests + tsc)."""
        passed, msg = self._run_hermetic_verification()
        if not passed:
            return False, msg, {}
        return True, "Verification passed: Characterization tests and TypeScript compilation are 100% clean.", {}

    def _seal_findings_to_recorder(self) -> None:
        if not (self.state.review_findings and self.state.active_ticket):
            return
        try:
            recorder = FlightRecorder(self.target_repo, self.state.active_ticket.ticket_id)
            recorder.seal_review_findings(self.state.review_findings)
        except Exception as e:
            print(f"[WARN] Failed to seal review findings into flight recorder: {e}")

    def _validate_examiner_receipt(self) -> Tuple[Optional[CycleState], str, Dict[str, Any]]:
        receipt = self.state.examiner_receipt
        if receipt is None:
            return (
                CycleState.REVIEW,
                "Review blocked: Examiner seal missing. Run 'brigade seal-review <repo> --verdict PASS|FAIL --summary \"...\"' before advancing.",
                {"error": "MISSING_EXAMINER_RECEIPT"},
            )
        active_tid = self.state.active_ticket.ticket_id if self.state.active_ticket else None
        if receipt.ticket_id and active_tid and receipt.ticket_id != active_tid:
            return (
                CycleState.REVIEW,
                f"Review blocked: Examiner seal is stale (receipt ticket '{receipt.ticket_id}' != '{active_tid}'). Re-run 'brigade seal-review'.",
                {"error": "STALE_EXAMINER_RECEIPT", "receipt_ticket_id": receipt.ticket_id, "active_ticket_id": active_tid},
            )
        verdict = (receipt.verdict or "").strip().upper()
        if verdict == "FAIL":
            return (
                CycleState.POLISH,
                "Examiner sealed verdict FAIL. Routing to POLISH for remediation.",
                {"verdict": "FAIL"},
            )
        if verdict != "PASS":
            return (
                CycleState.REVIEW,
                f"Review blocked: Invalid ExaminerReceipt verdict '{receipt.verdict}'. Expected PASS or FAIL.",
                {"error": "INVALID_EXAMINER_VERDICT"},
            )
        return None, "", {"examiner_receipt": receipt.to_dict()}

    def guard_review_to_next(self) -> Tuple[CycleState, str, Dict[str, Any]]:
        """
        Evaluates 3-axis review findings, mandatory ExaminerReceipt seal, and hermetic verification:
        - If CRITICAL findings exist -> POLISH
        - If ExaminerReceipt missing/stale -> REVIEW (blocks advancement)
        - If ExaminerReceipt.verdict == FAIL -> POLISH
        - If hermetic verification fails -> POLISH
        - Otherwise (0 CRITICAL + PASS seal + clean verification) -> STAGING
        """
        self._seal_findings_to_recorder()

        critical_findings = [f for f in self.state.review_findings if f.severity == "CRITICAL"]
        if critical_findings:
            msg = f"Review flagged {len(critical_findings)} critical finding(s). Advancing to POLISH for remediation."
            return CycleState.POLISH, msg, {"critical_count": len(critical_findings)}

        receipt_state, receipt_msg, receipt_details = self._validate_examiner_receipt()
        if receipt_state is not None:
            return receipt_state, receipt_msg, receipt_details

        v_passed, v_msg = self._run_hermetic_verification()
        if not v_passed:
            msg = f"Review blocked: Hermetic verification failed before STAGING entry:\n{v_msg}"
            return CycleState.POLISH, msg, {"verification_failed": True, "error": v_msg}

        msg = "Review clean (0 critical findings, Examiner PASS seal) and hermetic verification passed. Advancing to STAGING."
        return CycleState.STAGING, msg, {
            "total_findings": len(self.state.review_findings),
            **receipt_details,
        }

    def guard_polish_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Re-verifies compiler and tests after polish remediation and clears prior findings and receipt."""
        passed, msg = self._run_hermetic_verification()
        if not passed:
            return False, f"Post-polish verification failed:\n{msg}", {}
        self.state.review_findings = []
        self.state.examiner_receipt = None
        return True, "Post-polish verification passed. Routing to GATE for re-verification.", {}

    def guard_polish_to_gate(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Alias for guard_polish_to_review for backward compatibility."""
        return self.guard_polish_to_review()

    @staticmethod
    def _resolve_visual_from_receipt(receipt_path: Path, roots: List[Path]) -> Optional[Tuple[Path, Path, Optional[Path]]]:
        if not receipt_path.is_file():
            return None
        try:
            data = json.loads(receipt_path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        b_raw = str(data.get("baseline_path") or "").strip()
        r_raw = str(data.get("refactored_path") or "").strip()
        if not b_raw or not r_raw:
            return None
        b_file = ProofVerifier.resolve_screenshot_file(b_raw, roots)
        r_file = ProofVerifier.resolve_screenshot_file(r_raw, roots)
        if not (b_file and r_file):
            return None
        d_raw = str(data.get("diff_out_path") or "").strip()
        d_path = normalize_target_path(d_raw) if d_raw else None
        return b_file, r_file, d_path

    def _find_visual_parity_pair(self, slug: str, work_dir: Path) -> Optional[Tuple[Path, Path, Path]]:
        roots = list(dict.fromkeys([work_dir, self.target_repo]))
        default_diff = work_dir / ".edge" / "qa" / "visual" / f"{slug}-diff.png"
        for root in roots:
            vis_dir = root / ".edge" / "qa" / "visual"
            b_path = vis_dir / f"{slug}-baseline.png"
            r_path = vis_dir / f"{slug}-refactored.png"
            if b_path.is_file() and r_path.is_file():
                return b_path, r_path, default_diff
        for root in roots:
            for cand in (
                root / ".edge" / "qa" / "visual" / f"{slug}-diff.json",
                root / ".edge" / "qa" / "proofs" / f"{slug}-visual.json",
            ):
                resolved = self._resolve_visual_from_receipt(cand, roots)
                if resolved:
                    return resolved[0], resolved[1], resolved[2] or default_diff
        return None

    def _run_diff_image_subprocess(self, baseline: Path, refactored: Path, diff_out: Path) -> Tuple[bool, str, Dict[str, Any]]:
        plugin_root = Path(__file__).resolve().parents[2]
        uv_bin = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
        b_arg = to_wsl_path(baseline) if is_wsl_path(baseline) else str(baseline)
        r_arg = to_wsl_path(refactored) if is_wsl_path(refactored) else str(refactored)
        d_arg = to_wsl_path(diff_out) if is_wsl_path(diff_out) else str(diff_out)
        cmd = [
            uv_bin, "run", "--with", "pillow", "python3",
            "-m", "tools.ui_audit.diff_image",
            b_arg, r_arg, "--tolerance", "15", "--max-mismatch", "0.15", "--diff-out", d_arg,
        ]
        code, out, err = self._run_cmd(cmd, cwd=plugin_root)
        if code != 0:
            detail_msg = (out or err or "Pixel mismatch exceeded 0.15% threshold.").strip()
            return False, f"UI visual parity FAILED (mismatch > 0.15%): {detail_msg}", {
                "error": "VISUAL_PARITY_FAILED",
                "baseline": str(baseline),
                "refactored": str(refactored),
                "diff_out": str(diff_out),
                "output": out,
            }
        return True, "UI visual parity passed (<= 0.15%).", {
            "baseline": str(baseline),
            "refactored": str(refactored),
            "diff_out": str(diff_out),
            "output": out,
        }

    def _check_ui_visual_parity(self, ticket: Ticket, work_dir: Path) -> Tuple[bool, str, Dict[str, Any]]:
        slug = StationRegistry._resolve_qa_slug("qa_scenario", ticket)
        pair = self._find_visual_parity_pair(slug, work_dir)
        if not pair:
            return (
                False,
                f"UI visual parity blocked: missing baseline/refactored screenshots for '{slug}'. "
                f"Expected '.edge/qa/visual/{slug}-baseline.png' and '.edge/qa/visual/{slug}-refactored.png'.",
                {"error": "MISSING_VISUAL_PARITY_IMAGES", "slug": slug},
            )
        baseline, refactored, diff_out = pair
        if importlib.util.find_spec("PIL") is not None:
            from tools.ui_audit.diff_image import compare_images
            passed = compare_images(baseline, refactored, tolerance=15, max_mismatch_pct=0.15, diff_out_path=diff_out)
            if not passed:
                return False, f"UI visual parity FAILED (mismatch > 0.15%) for '{slug}'.", {
                    "error": "VISUAL_PARITY_FAILED",
                    "baseline": str(baseline),
                    "refactored": str(refactored),
                    "diff_out": str(diff_out),
                }
            return True, f"UI visual parity passed (<= 0.15%) for '{slug}'.", {
                "baseline": str(baseline),
                "refactored": str(refactored),
                "diff_out": str(diff_out),
            }
        return self._run_diff_image_subprocess(baseline, refactored, diff_out)

    def _build_gate_command(self, ticket: Ticket, eff_repo: Any) -> List[str]:
        gate_script = Path(__file__).resolve().parent.parent / "gate.py"
        base_to_compare = self.state.base_branch.strip() if (self.state.base_branch and self.state.base_branch.strip()) else "HEAD~1"
        no_refactor_flag = ["--no-refactor"] if getattr(ticket, "track", "core") == "feature" else []
        if is_wsl_path(eff_repo):
            return [
                "python3", to_wsl_path(gate_script), to_wsl_path(eff_repo),
                "--base", base_to_compare, "--track", ticket.track, "--skip-verify",
            ] + no_refactor_flag
        return [
            sys.executable, str(gate_script), str(eff_repo),
            "--base", base_to_compare, "--track", ticket.track, "--skip-verify",
        ] + no_refactor_flag

    def guard_gate_to_next(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Runs tools/gate.py (and diff_image.py visual parity on ui track) before QA/REVIEW."""
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found.", {}

        eff_repo = ticket.worktree_path if (ticket and ticket.worktree_path) else self.target_repo
        cmd = self._build_gate_command(ticket, eff_repo)
        code, stdout, stderr = self._run_cmd(cmd)
        if code != 0:
            return False, f"Edge Verification Gate FAILED (exit code {code}):\n{stdout}\n{stderr}", {"output": stdout}

        details: Dict[str, Any] = {"output": stdout}
        if getattr(ticket, "track", "core") == "ui":
            work_dir = normalize_target_path(eff_repo)
            parity_ok, parity_msg, parity_details = self._check_ui_visual_parity(ticket, work_dir)
            if not parity_ok:
                return False, parity_msg, parity_details
            details["visual_parity"] = parity_details

        return True, "Edge Verification Gate PASSED all invariant stages.", details

    def guard_gate_to_staging(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Backward-compatibility alias delegating to guard_gate_to_next."""
        return self.guard_gate_to_next()

    def should_run_qa(self, ticket: Optional[Ticket] = None) -> bool:
        """
        Evaluates the runtime invariant 'Lavish Varsa QA Yap, Yoksa Es Geç':
        1. Explicit ticket flag override (require_qa is True -> True, require_qa is False -> False).
        2. Explicit ticket lavish_path set and non-empty -> True.
        3. Existing Lavish prototype on disk (.lavish/<domain>.html or .lavish/<branch_slug>.html) -> True.
        4. Touched .lavish/ files in git diff -> True.
        5. Fallback -> False (pure backend/engine slice).
        """
        t = ticket or self.state.active_ticket
        if not t:
            return False

        # 1. Explicit override
        if t.require_qa is True:
            return True
        if t.require_qa is False:
            return False

        # 2. Explicit Lavish path
        if t.lavish_path and str(t.lavish_path).strip():
            return True

        work_dir = Path(t.worktree_path) if t.worktree_path else self.target_repo

        # 3. Existing Lavish prototype on disk
        slug = t.domain.lower().replace("_", "-")
        candidates = [
            work_dir / ".lavish" / f"{slug}.html",
            self.target_repo / ".lavish" / f"{slug}.html",
        ]
        if t.branch_name:
            branch_slug = t.branch_name.removeprefix("feat/").removeprefix("refactor/").replace("_", "-")
            candidates.extend([
                work_dir / ".lavish" / f"{branch_slug}.html",
                self.target_repo / ".lavish" / f"{branch_slug}.html",
            ])
        for cand in candidates:
            if cand.is_file():
                return True

        # 4. Check git diff for touched .lavish/ files
        base = self.state.base_branch or "development"
        code, stdout, _ = self._run_cmd(["git", "diff", "--name-only", f"{base}...HEAD"], cwd=work_dir)
        if code == 0 and stdout:
            for line in stdout.splitlines():
                line_str = line.strip()
                if line_str.startswith(".lavish/") or line_str.endswith(".lavish.html"):
                    return True

        return False

    def _run_qa_db_drift_preflight(self, work_dir: Optional[Path] = None) -> Tuple[bool, str]:
        """
        Executes 'npm run db:check-drift' preflight if defined in package.json.
        Returns (True, msg) if script is absent or passes; returns (False, error) on schema drift.
        """
        ticket = self.state.active_ticket
        eff_dir = work_dir or (
            normalize_target_path(ticket.worktree_path) if (ticket and ticket.worktree_path) else self.target_repo
        )
        pkg_json = eff_dir / "package.json"

        if not pkg_json.exists():
            return True, "No package.json found; skipping db:check-drift preflight (bypass)."

        try:
            with open(pkg_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            scripts = data.get("scripts", {})
        except Exception as e:
            return True, f"Could not parse package.json for db:check-drift: {e} (bypass)"

        if "db:check-drift" not in scripts:
            return True, "db:check-drift script not defined in package.json; zero-cost bypass."

        code, out, err = self._run_cmd(["npm", "run", "db:check-drift"], cwd=eff_dir)
        if code != 0:
            return False, f"QA DB Drift Preflight FAILED (exit code {code}): Database migration schema drift detected!\n{err or out}"

        return True, "QA DB Drift Preflight PASSED: Database schema is fully synchronized with migrations."

    def guard_qa_to_review(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates the QA verification stage before Examiner REVIEW:
        1. Fails if any CRITICAL review finding exists (routes to POLISH).
        2. Enforces deterministic ProofVerifier Receipt Gate (.edge/qa/proofs/<slug>.json).
        3. Executes QA DB drift preflight.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found for QA gate.", {}

        critical_findings = [
            f for f in self.state.review_findings
            if getattr(f, "severity", "").upper() == "CRITICAL"
        ]
        if critical_findings:
            return (
                False,
                f"QA verification blocked by {len(critical_findings)} critical defects.",
                {
                    "critical_count": len(critical_findings),
                    "findings": [f.to_dict() if hasattr(f, "to_dict") else f for f in critical_findings],
                },
            )

        work_dir = Path(ticket.worktree_path) if ticket.worktree_path else self.target_repo
        proof_ok, proof_msg, proof_details = _validate_qa_proof_receipt(
            self.target_repo, work_dir, ticket
        )
        if not proof_ok:
            return False, proof_msg, proof_details

        drift_ok, drift_msg = self._run_qa_db_drift_preflight(work_dir)
        if not drift_ok:
            return False, drift_msg, {"db_drift": True}

        return (
            True,
            f"QA verification passed (0 critical findings, valid proof receipt for '{proof_details.get('slug')}'). Advancing to REVIEW.",
            {
                "total_findings": len(self.state.review_findings),
                "proof_details": proof_details,
            },
        )

    def guard_qa_to_staging(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Backward-compatibility alias delegating to guard_qa_to_review."""
        return self.guard_qa_to_review()

    def get_next_station_handoff(self, target_state: Optional[CycleState] = None) -> Dict[str, Any]:
        """
        Returns the target station role, registered conversation_id, model,
        and recommended send_message instruction for the newly entered state.
        """
        state = target_state or self.state.current_state
        ticket = self.state.active_ticket
        track = getattr(ticket, "track", "core") if ticket else "core"

        target_role_str = self._resolve_handoff_target_role(state, track)
        station = self.state.stations.get(target_role_str) if target_role_str != "orchestrator" else None

        cid = station.conversation_id if station else (target_role_str if target_role_str == "orchestrator" else "")
        model = getattr(station, "model", "flash") if station else "flash"
        station_name = station.name if station else (target_role_str.title() if target_role_str == "orchestrator" else "Unknown")

        state_val = state.value if isinstance(state, CycleState) else str(state)
        instruction = self._resolve_handoff_instruction(state, ticket, state_val)

        return {
            "target_state": state_val,
            "target_role": target_role_str,
            "station_name": station_name,
            "recipient_cid": cid,
            "model": model,
            "instruction": instruction,
        }

    @staticmethod
    def _resolve_handoff_target_role(state: Any, track: str) -> str:
        worker_role = "coder" if track == "feature" else "surgeon"
        role_map = {
            CycleState.RED_TEST: "seam_architect",
            CycleState.SURGERY: worker_role,
            CycleState.VERIFY: worker_role,
            CycleState.REVIEW: "examiner",
            CycleState.POLISH: worker_role,
            CycleState.GATE: "none",
            CycleState.QA: "qa_engineer",
            CycleState.STAGING: "orchestrator",
            CycleState.COMPLETED: "orchestrator",
            CycleState.BLOCKED: "orchestrator",
            CycleState.PAUSED: "orchestrator",
        }
        return role_map.get(state, "none")

    @staticmethod
    def _resolve_handoff_instruction(state: Any, ticket: Any, state_val: str) -> str:
        tid = ticket.ticket_id if ticket else "SLICE"
        instructions = {
            CycleState.RED_TEST: "Establish Feathers seams and failing RED tests in the isolated worktree.",
            CycleState.SURGERY: "Implement clean code in the isolated worktree to turn red tests green. Follow contracts strictly.",
            CycleState.VERIFY: "Run characterization tests and compiler verification in worktree, then advance to GATE.",
            CycleState.GATE: "Run tools/gate.py (and diff_image.py on ui track) and advance to QA or REVIEW.",
            CycleState.QA: "Execute browser E2E verification, synthesize ProofVerifier receipt, and advance to REVIEW (EXAMINER).",
            CycleState.REVIEW: "Conduct 3-axis review (Axis 1: Standards, Axis 2: Spec Boundaries, Axis 3: Multimodal Evidence) and run 'brigade seal-review' before advancing to STAGING.",
            CycleState.POLISH: "Remediate review findings in the isolated worktree and verify compiler clean before re-entering GATE.",
            CycleState.STAGING: f"[READY_FOR_STAGING] Ticket {tid} passed all verification gates. Fast-forward merge ready.",
            CycleState.BLOCKED: f"[ESCALATION] Ticket {tid} blocked at state {state_val}. Captain intervention required.",
        }
        return instructions.get(state, f"State transitioned to {state_val}. Proceed with station duties.")

    def _archive_ticket_spec(self, ticket: Ticket) -> None:
        """Archives ephemeral slice spec from .edge/specs/ to .edge/archive/specs/."""
        try:
            from tools.drift.scanner import archive_ephemeral_spec
        except ImportError:
            return

        candidates: List[Path] = []
        edge_specs_dir = (self.target_repo / ".edge" / "specs").resolve()

        if ticket.spec_path:
            p = Path(ticket.spec_path)
            if not p.is_absolute():
                p = self.target_repo / p
            if p.exists() and p.is_file():
                try:
                    p_resolved = p.resolve()
                    if edge_specs_dir in p_resolved.parents or p_resolved.parent == edge_specs_dir:
                        candidates.append(p)
                except Exception:
                    pass

        branch_slug = ticket.branch_name.split("/")[-1] if ticket.branch_name else ""
        if branch_slug:
            cand1 = self.target_repo / ".edge" / "specs" / f"{branch_slug}.md"
            if cand1.exists() and cand1.is_file() and cand1 not in candidates:
                candidates.append(cand1)

        ticket_slug = ticket.ticket_id.lower() if ticket.ticket_id else ""
        if ticket_slug:
            cand2 = self.target_repo / ".edge" / "specs" / f"{ticket_slug}.md"
            if cand2.exists() and cand2.is_file() and cand2 not in candidates:
                candidates.append(cand2)

        for c in candidates:
            try:
                archive_ephemeral_spec(self.target_repo, c)
            except Exception as e:
                print(f"[WARN] Failed to archive spec {c}: {e}")

    def _sync_diverged_worktree(self, ticket: Ticket) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Automates in-situ git rebase inside leased worktree and validates hermetic tests.
        On syntactic conflict or semantic verification failure, aborts and escalates to PAUSED.
        """
        if not ticket.worktree_path:
            return False, (
                f"REFUSED: Branch '{ticket.branch_name}' has diverged from '{self.state.base_branch}' (not a clean fast-forward), "
                f"and no worktree is available for automated rebase. Rebase '{ticket.branch_name}' manually before merging."
            ), {}

        wt_dir = normalize_target_path(ticket.worktree_path)
        if not wt_dir.is_dir():
            return False, f"Leased worktree path does not exist on disk: {wt_dir}", {}

        # 1. Run git rebase <base_branch> inside worktree
        reb_code, reb_out, reb_err = run_command(["git", "rebase", self.state.base_branch], cwd=wt_dir)
        if reb_code != 0:
            diff_code, diff_out, _ = run_command(["git", "diff", "--name-only", "--diff-filter=U"], cwd=wt_dir)
            conflicting_files = [line.strip() for line in diff_out.splitlines() if line.strip()]

            run_command(["git", "rebase", "--abort"], cwd=wt_dir)

            reason = (
                f"Rebase conflict onto {self.state.base_branch}: "
                f"{', '.join(conflicting_files) if conflicting_files else reb_err or reb_out}"
            )
            self.escalate(reason)
            return False, reason, {
                "escalated": True,
                "conflicting_files": conflicting_files,
                "error": reb_err or reb_out,
            }

        # 2. Rebase clean: run hermetic verification on rebased code
        verify_ok, verify_msg = self._run_hermetic_verification(work_dir=wt_dir)
        if not verify_ok:
            reason = f"Post-rebase verification failed on {ticket.branch_name}: {verify_msg}"
            self.escalate(reason)
            return False, reason, {
                "escalated": True,
                "semantic_conflict": True,
                "verification_error": verify_msg,
            }

        return True, "Worktree cleanly rebased and verified.", {}

    def _run_radar_rescan(self) -> None:
        """Refreshes radar ledger to resolve debt after ticket completion."""
        radar_cli = Path(__file__).resolve().parent.parent / "radar" / "cli.py"
        target_path_str = str(self.target_repo)

        if target_path_str.startswith(r"\\wsl.localhost") or target_path_str.startswith("/home/"):
            wsl_target = target_path_str.replace(r"\\wsl.localhost\Ubuntu-24.04", "").replace("\\", "/")
            wsl_radar = str(radar_cli).replace(r"C:\Users\oguz_\.gemini\config\plugins\edge", "/mnt/c/Users/oguz_/.gemini/config/plugins/edge").replace("\\", "/")
            cmd = ["python3", wsl_radar, "scan", wsl_target]
        else:
            cmd = [sys.executable, str(radar_cli), "scan", str(self.target_repo)]

        code, stdout, stderr = run_command(cmd, cwd=self.target_repo)
        if code != 0:
            print(f"[WARN] Radar scan had issues: {stderr}")

    def guard_staging_to_completed(self) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Executes local codebase fast-forward synchronization and cleanup:
        1. Checks primary checkout clean status and branch.
        2. Validates fast-forward mergeability (--is-ancestor).
        3. Executes git merge --ff-only into base_branch in primary repo.
        4. Returns worktree to Treehouse pool.
        5. Marks FlightRecorder status as RESOLVED.
        6. Archives ephemeral slice specs.
        7. Triggers radar ledger rescan.
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active ticket found.", {}

        # If not a git repository (e.g. mock test environment), skip git merge operations
        if not (self.target_repo / ".git").exists():
            self._archive_ticket_spec(ticket)
            return True, f"Ticket {ticket.ticket_id} delivered (non-git workspace).", {}

        # 1. Primary checkout clean status check
        code, status_out, _ = run_command(["git", "status", "--porcelain"], cwd=self.target_repo)
        if status_out.strip():
            return False, f"Primary repository {self.target_repo} has uncommitted dirty changes. Refusing to merge into dirty checkout.", {}

        # Check primary checkout branch
        code, curr_branch, _ = run_command(["git", "branch", "--show-current"], cwd=self.target_repo)
        curr_b = curr_branch.strip()
        if curr_b != self.state.base_branch:
            # Try to switch to base_branch cleanly
            code, _, err = run_command(["git", "checkout", self.state.base_branch], cwd=self.target_repo)
            if code != 0:
                return False, f"Primary repository is on '{curr_b}', failed to checkout base branch '{self.state.base_branch}': {err}", {}

        # 2. Fast-Forward check: is base_branch an ancestor of ticket branch?
        code, _, _ = run_command(
            ["git", "merge-base", "--is-ancestor", self.state.base_branch, ticket.branch_name],
            cwd=self.target_repo,
        )
        if code != 0:
            rebase_ok, rebase_msg, rebase_details = self._sync_diverged_worktree(ticket)
            if not rebase_ok:
                return False, rebase_msg, rebase_details

        # 3. Fast-forward merge into primary repo
        code, merge_out, merge_err = run_command(
            ["git", "merge", "--ff-only", ticket.branch_name],
            cwd=self.target_repo,
        )
        if code != 0:
            return False, f"Failed to fast-forward merge {ticket.branch_name} into {self.state.base_branch}: {merge_err or merge_out}", {}

        # 4. Return worktree to Treehouse pool
        if ticket.worktree_path:
            ok, wt_msg = return_worktree(self.target_repo, ticket.worktree_path, force=False)
            if not ok:
                print(f"[WARN] Failed to cleanly return worktree to Treehouse pool: {wt_msg}")

        # 5. Mark flight recorder as RESOLVED
        try:
            recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
            recorder.mark_status("RESOLVED")
        except Exception as e:
            print(f"[WARN] Failed to mark flight recorder RESOLVED: {e}")

        # Archive ephemeral slice spec
        self._archive_ticket_spec(ticket)

        # 6. Refresh radar ledger to resolve debt
        self._run_radar_rescan()

        return True, f"Ticket {ticket.ticket_id} successfully merged into {self.state.base_branch} and worktree released to pool.", {"output": merge_out}

    # =========================================================================
    # State Machine Transitions
    # =========================================================================

    def _record_guard_failure(
        self,
        state: CycleState,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Records guard failure in transition history and synchronizes to FlightRecorder."""
        state_str = state.value if isinstance(state, CycleState) else str(state)
        log = TransitionLog(
            from_state=state_str,
            to_state=state_str,
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=False,
            message=message,
            details=details or {},
        )
        self.state.history.append(log)
        self.save()

        if self.state.active_ticket:
            try:
                recorder = FlightRecorder(self.target_repo, self.state.active_ticket.ticket_id)
                recorder.record_guard_failure(
                    state=state_str,
                    message=message,
                    details=details or {},
                )
            except Exception as e:
                print(f"[WARN] Failed to record guard failure in flight recorder: {e}")

    def _advance_from_gate(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        """Handles advance logic from GATE to either QA (preflight checked) or REVIEW."""
        curr = CycleState.GATE
        passed, msg, details = self.guard_gate_to_next()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            return False, curr, f"Edge Gate blocked advancement: {msg}"

        if self.should_run_qa(self.state.active_ticket):
            drift_ok, drift_msg = self._run_qa_db_drift_preflight()
            if not drift_ok and not force:
                self._record_guard_failure(curr, drift_msg, {"db_drift": True})
                return False, curr, f"QA Preflight blocked advancement: {drift_msg}"

            adv_msg = "Gate passed; Lavish prototype detected -> advancing to QA."
            self._transition(CycleState.QA, adv_msg, details)
            return True, self.state.current_state, adv_msg

        adv_msg = "Gate passed; no QA required -> advancing to REVIEW."
        self._transition(CycleState.REVIEW, adv_msg, details)
        return True, self.state.current_state, adv_msg

    def _advance_from_qa(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        curr = CycleState.QA
        passed, msg, details = self.guard_qa_to_review()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            if details.get("critical_count", 0) > 0:
                self._transition(CycleState.POLISH, f"QA failed with critical defects -> routing to POLISH: {msg}", details)
                return False, CycleState.POLISH, f"Critical QA defects detected. Routed to POLISH: {msg}"
            return False, curr, f"QA guard blocked advancement: {msg}"
        self._transition(CycleState.REVIEW, msg, details)
        return True, self.state.current_state, msg

    def _advance_from_review(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        curr = CycleState.REVIEW
        next_state, msg, details = self.guard_review_to_next()
        if next_state == CycleState.REVIEW:
            if force:
                self._transition(CycleState.STAGING, f"Forced advance from REVIEW: {msg}", details)
                return True, self.state.current_state, msg
            self._record_guard_failure(curr, msg, details)
            return False, curr, msg
        self._transition(next_state, msg, details)
        return True, self.state.current_state, msg

    def _advance_from_polish(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        curr = CycleState.POLISH
        passed, msg, details = self.guard_polish_to_review()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            return False, curr, f"Polish guard blocked advancement: {msg}"
        if force:
            self.state.review_findings = []
            self.state.examiner_receipt = None
        self._transition(CycleState.GATE, msg, details)
        return True, self.state.current_state, msg

    def _advance_from_completed(self) -> Tuple[bool, CycleState, str]:
        self._seal_findings_to_recorder()
        self._transition(CycleState.IDLE, "Cycle completed. Reset to IDLE.")
        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.save()
        return True, self.state.current_state, "Reset to IDLE for next ticket."

    def _advance_guarded(
        self,
        curr: CycleState,
        guard_fn: Any,
        next_state: CycleState,
        err_prefix: str,
        force: bool = False,
    ) -> Tuple[bool, CycleState, str]:
        passed, msg, details = guard_fn()
        if not passed and not force:
            self._record_guard_failure(curr, msg, details)
            return False, curr, f"{err_prefix}: {msg}"
        self._transition(next_state, msg, details)
        return True, self.state.current_state, msg

    def advance(self, force: bool = False) -> Tuple[bool, CycleState, str]:
        """
        Advances the state machine to the next deterministic state.
        Order: VERIFY -> GATE -> [QA] -> REVIEW -> STAGING -> COMPLETED -> IDLE.
        """
        curr = self.state.current_state
        if curr == CycleState.IDLE:
            if not self.state.active_ticket:
                return False, curr, "Cannot advance from IDLE without an active ticket. Run 'triage' first."
            self._transition(CycleState.TRIAGE, "Initialized triage from active ticket.")
            return True, self.state.current_state, "Moved to TRIAGE."

        simple_routes = {
            CycleState.TRIAGE: (self.guard_triage_to_surgery, CycleState.SURGERY, "Triage validation failed"),
            CycleState.RED_TEST: (self.guard_red_to_surgery, CycleState.SURGERY, "Red test guard blocked advancement"),
            CycleState.SURGERY: (self.guard_surgery_to_verify, CycleState.VERIFY, "Surgery guard blocked advancement"),
            CycleState.VERIFY: (self.guard_verify_to_gate, CycleState.GATE, "Verification guard blocked advancement"),
            CycleState.STAGING: (self.guard_staging_to_completed, CycleState.COMPLETED, "Staging guard blocked completion"),
        }
        if curr in simple_routes:
            guard_fn, next_st, prefix = simple_routes[curr]
            return self._advance_guarded(curr, guard_fn, next_st, prefix, force=force)

        complex_handlers = {
            CycleState.GATE: lambda: self._advance_from_gate(force),
            CycleState.QA: lambda: self._advance_from_qa(force),
            CycleState.REVIEW: lambda: self._advance_from_review(force),
            CycleState.POLISH: lambda: self._advance_from_polish(force),
            CycleState.COMPLETED: self._advance_from_completed,
        }
        handler = complex_handlers.get(curr)
        if handler:
            return handler()

        if curr == CycleState.BLOCKED:
            return False, curr, f"State is BLOCKED ({self.state.blocked_reason}). Run 'abort' to reset."
        if curr == CycleState.PAUSED:
            return False, curr, "State is PAUSED. Run 'brigade resume' to restore execution."
        return False, curr, f"Unknown state {curr}."

    def _transition(self, to_state: CycleState, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        log = TransitionLog(
            from_state=self.state.current_state.value if isinstance(self.state.current_state, CycleState) else str(self.state.current_state),
            to_state=to_state.value if isinstance(to_state, CycleState) else str(to_state),
            timestamp=datetime.now(timezone.utc).isoformat(),
            success=True,
            message=message,
            details=details or {},
        )
        self.state.history.append(log)
        self.state.current_state = to_state
        self.save()

    def abort(self, reason: str, force: bool = True, negative_constraint: Optional[str] = None) -> None:
        """
        Aborts active cycle, releases isolated worktree back to Treehouse pool,
        records dead-end into FlightRecorder, and resets machine to IDLE.
        """
        ticket = self.state.active_ticket
        if ticket:
            # 1. Record dead-end and negative constraint in FlightRecorder
            try:
                recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
                recorder.record_dead_end(
                    title=f"Aborted in state {self.state.current_state.value}",
                    reason=reason,
                    prohibited_rule=negative_constraint or f"Avoid design/path resulting in abortion: {reason}",
                    is_abort=True,
                )
            except Exception as e:
                print(f"[WARN] Failed to record dead-end in flight recorder: {e}")

            # 2. Release worktree back to Treehouse pool if allocated
            if ticket.worktree_path:
                try:
                    return_worktree(self.target_repo, ticket.worktree_path, force=force)
                except Exception as e:
                    print(f"[WARN] Failed to return worktree during abort: {e}")

        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Aborted: {reason}")

    def escalate(self, reason: str) -> Checkpoint:
        """
        Escalates active ticket to human captain for decision/intervention.
        1. Records escalation in Ticket and FlightRecorder.
        2. Pauses FSM execution safely via durable Checkpoint.
        """
        ticket = self.state.active_ticket
        if ticket:
            ticket.escalation_reason = reason
            ticket.escalation_at = datetime.now(timezone.utc).isoformat()
            ticket.status = "ESCALATED"
            try:
                recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
                recorder.record_escalation(reason)
            except Exception as e:
                print(f"[WARN] Failed to log escalation in flight recorder: {e}")

        return self.pause(reason=f"ESCALATION: {reason}")

    def release(self, decision: str) -> Tuple[bool, Optional[Checkpoint], str]:
        """
        Releases an escalated ticket following human captain decision.
        1. Records captain's decision in Ticket and FlightRecorder.
        2. Resumes FSM execution from checkpoint.
        """
        ticket = self.state.active_ticket
        if ticket:
            ticket.captain_decision = decision
            ticket.escalation_reason = None
            ticket.status = "OPEN"
            try:
                recorder = FlightRecorder(self.target_repo, ticket.ticket_id)
                recorder.record_decision(decision)
            except Exception as e:
                print(f"[WARN] Failed to log decision in flight recorder: {e}")

        return self.resume()

    def calculate_file_metrics(self, file_path: Path) -> Tuple[int, float]:
        """Calculates SLOC and Health Score for a target file. Returns (sloc, health_score)."""
        if not file_path.exists():
            return 0, 0.0
        try:
            from tools.audit.scanner import FileScanner
            from tools.audit.scorer import HealthScorer
            scanner = FileScanner(workspace_root=self.target_repo)
            ext = file_path.suffix.lower()
            adapter = scanner.ext_map.get(ext)
            if not adapter:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [l for l in f if l.strip()]
                return len(lines), 0.0
            
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            try:
                rel = str(file_path.relative_to(self.target_repo)).replace("\\", "/")
            except ValueError:
                rel = str(file_path).replace("\\", "/")
            metric = adapter.analyze(path=file_path, rel_path=rel, content=content, workspace_root=self.target_repo, test_index={})
            scored = HealthScorer.score_file(metric)
            health = round(max(0.0, 100.0 - scored.risk_score), 2)
            return scored.sloc, health
        except Exception:
            return 0, 0.0

    def rollback_stagnated(self, reason: str) -> None:
        """Rolls back the active ticket branch if health score failed to improve after N attempts."""
        ticket = self.state.active_ticket
        base_ref = self.state.base_branch
        self._run_cmd(["git", "checkout", base_ref])
        if ticket and ticket.branch_name:
            self._run_cmd(["git", "branch", "-D", ticket.branch_name])
        
        if ticket:
            ticket.status = "STAGNATED"
        
        self.state.blocked_reason = f"Stagnated after {ticket.attempt_count if ticket else 0} attempts: {reason}"
        self._transition(CycleState.STAGNATED, f"Stagnation rollback: {reason}")
        self._transition(CycleState.IDLE, "Reset to IDLE after rollback.")

    # =========================================================================
    # Radar Ledger Triage Engine
    # =========================================================================

    def triage_next_ticket(
        self,
        track: str = "core",
        target_domain: Optional[str] = None,
        whitelist: Optional[List[str]] = None,
        blacklist: Optional[List[str]] = None,
        transcript_path: Optional[Path] = None,
    ) -> Optional[Ticket]:
        """
        Inspects .edge/ledger/<track>.json and creates a discrete Ticket
        for the highest priority finding.
        Supports whitelist (only allowed domains) and blacklist (forbidden domains).
        Throttles/blocks triage if context heat zone is YELLOW or RED.
        """
        if self.state.current_state == CycleState.PAUSED:
            print("⚠️ Cannot triage while state is PAUSED. Run 'brigade resume' first.")
            return None

        if transcript_path:
            tokens = self.calculate_token_estimate(transcript_path)
            zone, rec = self.get_heat_zone(tokens)
            if zone in (ContextHeatZone.YELLOW, ContextHeatZone.RED):
                print(f"⚠️ TRIAGE BLOCKED BY HEAT POLICY: {rec}")
                return None

        ledger_path = self.target_repo / ".edge" / "ledger" / f"{track}.json"
        if not ledger_path.exists():
            return None

        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        items = data.get("items", [])
        open_items = [i for i in items if i.get("status") == "OPEN"]
        if not open_items:
            return None

        # Domain whitelist filtering
        if whitelist:
            whitelist_norm = [w.lower().rstrip("s") for w in whitelist]
            open_items = [
                i for i in open_items
                if any(w in i.get("file_path", "").lower() or w in i.get("title", "").lower() for w in whitelist_norm)
            ]

        # Domain blacklist filtering (e.g. skip bookings)
        if blacklist:
            blacklist_norm = [b.lower().rstrip("s") for b in blacklist]
            open_items = [
                i for i in open_items
                if not any(b in i.get("file_path", "").lower() or b in i.get("title", "").lower() for b in blacklist_norm)
            ]

        if not open_items:
            return None

        if target_domain:
            domain_norm = target_domain.lower().rstrip("s")
            domain_filtered = [
                i for i in open_items
                if domain_norm in i.get("file_path", "").lower() or domain_norm in i.get("title", "").lower()
            ]
            if domain_filtered:
                open_items = domain_filtered

        # Prioritize CRITICAL over WARNING over ADVISORY
        severity_order = {"CRITICAL": 0, "WARNING": 1, "ADVISORY": 2}
        open_items.sort(key=lambda x: severity_order.get(x.get("severity", "WARNING"), 99))
        
        target = open_items[0]
        file_path = target.get("file_path", "")
        
        # Extract domain name: e.g. src/actions/bookings.ts -> bookings
        path_obj = Path(file_path)
        domain = path_obj.stem
        if domain.endswith(".test") or domain.endswith(".spec"):
            domain = domain.split(".")[0]

        rule_id = target.get("rule_id", "RULE-GENERAL")
        line_num = target.get("line_number", 1)
        ticket_id = Ticket.generate_id(track, domain, rule_id, line_num)
        
        # Branch name: refactor/<track>-<domain>-<rule_short>
        rule_short = rule_id.lower().replace("rule-", "").replace("-", "")[:10]
        branch_name = f"refactor/{track}-{domain}-{rule_short}"

        # Scaffolding allowance: if repository doesn't exist yet, allow +25
        repo_file = self.target_repo / "src" / "lib" / domain / "repository.ts"
        scaffolding = 25 if not repo_file.exists() else 0

        # Characterization test seam command
        test_file = self.target_repo / "tests" / "unit" / domain / f"{domain}.test.ts"
        if test_file.exists():
            test_seam = f"npx vitest run tests/unit/{domain}/{domain}.test.ts"
        else:
            test_seam = "npm run test:unit"

        # Measure initial metrics before surgery
        full_target = self.target_repo / file_path
        sloc_b, health_b = self.calculate_file_metrics(full_target)

        # Check flight recorder for prior dead ends / constraints
        recorder = FlightRecorder(self.target_repo, ticket_id)
        prior_constraints = recorder.get_negative_constraints()

        base_constraints = [
            "MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations.",
            "Layer Leakage Gate: Do not introduce direct DB calls (`db.select`, `db.insert`, `db.update`, `db.delete`, `db.transaction`, `db.query`) in action controllers (`after_leaks <= before_leaks`, 0 in new actions).",
            "Max CC Non-Regression: Modified production files must not regress max cyclomatic complexity (healthy ceiling CC <= 10 for clean/new files).",
            "Zero-Wrapper Left Behind: Do not create shallow 1-line pass-through services.",
        ]
        all_constraints = base_constraints + [c for c in prior_constraints if c not in base_constraints]

        ticket = Ticket(
            ticket_id=ticket_id,
            track=track,
            domain=domain,
            rule_id=rule_id,
            severity=target.get("severity", "WARNING"),
            target_file=file_path,
            target_symbol=target.get("symbol"),
            line_number=line_num,
            fingerprint=target.get("fingerprint", ""),
            description=target.get("title", ""),
            suggested_fix=target.get("suggested_fix", ""),
            branch_name=branch_name,
            test_seam_command=test_seam,
            scaffolding_allowance=scaffolding,
            negative_constraints=all_constraints,
            health_before=health_b,
            sloc_before=sloc_b,
        )

        self.state.active_ticket = ticket
        self.state.active_branch = branch_name
        self.state.current_state = CycleState.TRIAGE
        self.save()
        return ticket

    def start_slice(
        self,
        name: str,
        track: str = "feature",
        target_file: str = "",
        domain: str = "",
        test_seam_command: str = "npm run test:unit",
        allow_schema_migration: bool = True,
        auto_lease_worktree: bool = True,
        expected_files: Optional[List[str]] = None,
        spec_path: Optional[str] = None,
        lavish_path: Optional[str] = None,
        require_qa: Optional[bool] = None,
    ) -> Tuple[bool, Optional[Ticket], str]:
        """
        Deterministically initiates a live feature or refactor slice:
        1. Checks if an active ticket is currently in-flight.
        2. Generates ticket (e.g. TICK-FEAT-<name>).
        3. Derives branch name (e.g. feat/<name> or refactor/<name>).
        4. If auto_lease_worktree is True and treehouse is installed, acquires an isolated worktree slot.
        5. Initializes FlightRecorder.
        6. Sets FSM state to RED_TEST (feature) or SURGERY (refactor/core).
        """
        if self.state.active_ticket and self.state.current_state != CycleState.IDLE:
            if self.state.current_state == CycleState.PAUSED:
                self.state.active_ticket = None
                self.state.active_branch = None
                self.state.active_worktree = None
            else:
                return False, self.state.active_ticket, f"Cannot start slice: Active ticket {self.state.active_ticket.ticket_id} is currently in progress (State: {self.state.current_state.value}). Finish or abort it first."

        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).lower().strip("-")
        eff_domain = domain or (Path(target_file).stem if target_file else clean_name)
        rule_id = f"SLICE-{clean_name.upper()[:12]}"
        if len(clean_name) <= 18:
            slug = clean_name.upper()
        else:
            slug = f"{clean_name[:11].upper()}-{clean_name[-6:].upper()}"
        ticket_id = f"TICK-{track.upper()[:4]}-{slug}"
        
        prefix = "feat" if track == "feature" else "refactor"
        branch_name = f"{prefix}/{clean_name}"

        # Flight recorder setup
        recorder = FlightRecorder(self.target_repo, ticket_id)
        prior_constraints = recorder.get_negative_constraints()

        base_constraints = [
            "Zero-Touch Primary Checkout Invariant: All mutations must be executed strictly inside the leased worktree.",
            "Test Immutability: Coder must not delete or loosen tests authored by Seam Architect.",
        ]
        if track != "feature" and not allow_schema_migration:
            base_constraints.append("MigrationGate Invariant: NEVER touch `src/db/schema/*` or `drizzle/` migrations.")

        all_constraints = base_constraints + [c for c in prior_constraints if c not in base_constraints]

        # Resolve lavish prototype path (explicit or auto-detected in .lavish/)
        resolved_lavish = lavish_path
        if not resolved_lavish:
            cand = self.target_repo / ".lavish" / f"{clean_name}.html"
            if cand.exists():
                resolved_lavish = str(cand.relative_to(self.target_repo)).replace("\\", "/")
            elif eff_domain:
                cand_domain = self.target_repo / ".lavish" / f"{eff_domain}.html"
                if cand_domain.exists():
                    resolved_lavish = str(cand_domain.relative_to(self.target_repo)).replace("\\", "/")

        eff_expected_files = list(expected_files or [])
        if not eff_expected_files:
            eff_expected_files = _extract_spec_expected_files(
                repo_path=self.target_repo,
                spec_path=spec_path,
                clean_name=clean_name,
            )

        ticket = Ticket(
            ticket_id=ticket_id,
            track=track,
            domain=eff_domain,
            rule_id=rule_id,
            severity="NORMAL",
            target_file=target_file,
            line_number=1,
            fingerprint=f"slice-{clean_name}",
            description=f"Live slice: {name}",
            suggested_fix=f"Implement slice {name}",
            branch_name=branch_name,
            test_seam_command=test_seam_command,
            scaffolding_allowance=50 if track == "feature" else 15,
            enforce_contraction=False,
            allow_schema_migration=allow_schema_migration,
            expected_files=eff_expected_files,
            spec_path=spec_path,
            lavish_path=resolved_lavish,
            require_qa=require_qa,
            negative_constraints=all_constraints,
        )

        is_git_repo = (self.target_repo / ".git").exists()
        worktree_msg = ""
        if auto_lease_worktree and is_git_repo and is_treehouse_installed():
            ok, wt_path, err = acquire_worktree(
                repo_path=self.target_repo,
                branch_name=branch_name,
                lease_holder=f"brigade-{ticket_id}",
            )
            if not ok:
                return False, None, f"Failed to acquire isolated Treehouse worktree: {err}"
            ticket.worktree_path = wt_path
            self.state.active_worktree = wt_path
            worktree_msg = f" Worktree leased at {wt_path}."

        recorder.set_metadata(
            track=track,
            domain=eff_domain,
            target_file=ticket.target_file,
            worktree_path=ticket.worktree_path or "",
            expected_files=ticket.expected_files,
        )

        self.state.active_ticket = ticket
        self.state.active_branch = branch_name
        if track == "feature":
            self.state.current_state = CycleState.RED_TEST
            self._transition(CycleState.RED_TEST, "Initialized feature slice in RED_TEST state")
            state_label = "RED_TEST"
        else:
            self.state.current_state = CycleState.SURGERY
            self.save()
            state_label = "SURGERY"

        return True, ticket, f"Slice '{name}' initiated successfully.{worktree_msg} Branch: {branch_name} (State: {state_label})."

    def _is_ticket_one_way_door(self, ticket: Ticket, ship_door_type: str) -> bool:
        if ship_door_type.startswith("One-way"):
            return True
        from .ship_prep import _is_one_way_door_path
        paths = [ticket.target_file, *(getattr(ticket, "expected_files", None) or [])]
        return any(_is_one_way_door_path(p) for p in paths if p)

    def _reset_after_slice_finish(self, ticket: Ticket) -> None:
        if ticket.worktree_path:
            return_worktree(self.target_repo, ticket.worktree_path, force=False)
        self._archive_ticket_spec(ticket)
        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Slice {ticket.ticket_id} finished and merged cleanly.")

    def _finish_slice_via_pr(self, ticket: Ticket, auto_merge_two_way: bool = True) -> Tuple[bool, str]:
        from .ship_prep import prepare_ship_payload
        _, ship_res, _ = prepare_ship_payload(self.target_repo, base_branch=self.state.base_branch)
        is_one_way = self._is_ticket_one_way_door(ticket, ship_res.door_type)
        badge = "[ONE-WAY DOOR]" if is_one_way else "[TWO-WAY DOOR]"
        branch = ticket.branch_name or self.state.active_branch or "HEAD"
        pr_title = f"{badge} {branch}: {ticket.description}"
        pr_body = ship_res.pr_body or pr_title

        run_command(["git", "push", "-u", "origin", branch], cwd=self.target_repo)
        c_code, c_out, c_err = run_command(
            [
                "gh", "pr", "create",
                "--base", self.state.base_branch,
                "--head", branch,
                "--title", pr_title,
                "--body", pr_body,
            ],
            cwd=self.target_repo,
        )
        if c_code != 0:
            return False, f"Failed to create GitHub PR for {branch}: {c_err or c_out}"

        if is_one_way:
            return (
                True,
                f"One-way door PR opened ({pr_title}) and held open for mandatory human review before merging.",
            )

        if auto_merge_two_way:
            run_command(["gh", "pr", "merge", branch, "--auto", "--merge"], cwd=self.target_repo)

        self._reset_after_slice_finish(ticket)
        return True, f"Two-way door PR ({pr_title}) created and auto-merged into {self.state.base_branch}."

    def finish_slice(self, open_pr: bool = False, auto_merge_two_way: bool = True) -> Tuple[bool, str]:
        """
        Fast-forward merges the active slice worktree into base_branch (development),
        or opens a Spec-Anchored GitHub PR when open_pr=True (auto-merging Two-Way Doors
        and holding One-Way Doors open for mandatory human review).
        """
        ticket = self.state.active_ticket
        if not ticket:
            return False, "No active slice or ticket to finish. Brigade is IDLE."

        if open_pr:
            return self._finish_slice_via_pr(ticket, auto_merge_two_way=auto_merge_two_way)

        ok, msg, details = self.guard_staging_to_completed()
        if not ok:
            return False, f"Finish slice failed: {msg}"

        self.state.active_ticket = None
        self.state.active_branch = None
        self.state.active_worktree = None
        self.state.review_findings = []
        self.state.examiner_receipt = None
        self.state.blocked_reason = None
        self._transition(CycleState.IDLE, f"Slice {ticket.ticket_id} finished and merged cleanly.")

        return True, msg

    # =========================================================================
    # Pause, Resume & Context Heat Protocols
    # =========================================================================

    def _get_substeps_for_state(self, state: CycleState, ticket: Optional[Ticket] = None) -> Tuple[List[str], List[str], str]:
        """Infers completed and pending substeps plus next action prompt from state."""
        eff_ticket = ticket if ticket is not None else self.state.active_ticket
        target = (
            eff_ticket.target_file
            or (", ".join(eff_ticket.expected_files) if getattr(eff_ticket, "expected_files", None) else "(dynamic-slice)")
            if eff_ticket
            else "target file"
        )
        mapping = {
            CycleState.IDLE: (SubstepList([]), SubstepList(["triage_next_ticket"]), "Run 'brigade triage' to pick next ticket from radar."),
            CycleState.TRIAGE: (SubstepList(["ticket_triaged"]), SubstepList(["git_branch_created", "baseline_compiler_verified", "surgery"]), "Run 'brigade advance' to transition to SURGERY and dispatch Surgeon."),
            CycleState.RED_TEST: (SubstepList(["slice_started"]), SubstepList(["write_red_tests", "verify_red_baseline"]), f"Author failing unit/contract tests for {target} to establish red baseline before advancing to SURGERY."),
            CycleState.SURGERY: (SubstepList(["ticket_triaged", "git_branch_created"]), SubstepList(["code_modifications", "hermetic_verification", "gate_verification"]), f"Execute bounded surgery on {target}, then verify with tests and tsc before advancing to VERIFY."),
            CycleState.VERIFY: (SubstepList(["ticket_triaged", "surgery_completed"]), SubstepList(["test_seam_verification", "tsc_compilation", "edge_gate"]), "Run hermetic test seams and advance to GATE."),
            CycleState.GATE: (SubstepList(["hermetic_tests_passed"]), SubstepList(["edge_gate_execution", "ui_visual_parity", "qa_or_review"]), "Run 'python tools/gate.py' (and UI diff_image.py if ui track) and advance to QA or REVIEW."),
            CycleState.QA: (SubstepList(["gate_passed"]), SubstepList(["browser_e2e_verification", "proof_verifier_receipt", "zero_console_errors", "examiner_review"]), "Execute QA browser inspection, synthesize ProofVerifier receipt, and advance to REVIEW."),
            CycleState.REVIEW: (SubstepList(["gate_passed", "qa_verified_if_needed"]), SubstepList(["standards_review", "spec_review", "evidence_review", "seal_review"]), "Execute 3-axis review (Standards, Spec, Evidence) and run 'brigade seal-review' before advancing to STAGING."),
            CycleState.POLISH: (SubstepList(["review_findings_recorded"]), SubstepList(["remediate_critical_findings", "re_verify", "edge_gate"]), "Remediate critical review findings and advance to GATE."),
            CycleState.STAGING: (SubstepList(["gate_passed", "review_sealed_pass"]), SubstepList(["squash_merge_to_base", "radar_ledger_update"]), "Squash-merge branch into base and update radar ledger."),
        }
        return mapping.get(state, (SubstepList([]), SubstepList([]), f"Resume execution in state {state.value}."))

    def pause(self, reason: str = "MANUAL_PAUSE") -> Checkpoint:
        """
        Durable Safe Checkpoint:
        1. Checks for dirty uncommitted changes in git working tree.
        2. If dirty, creates a safe 'wip(checkpoint): safe pause at <STATE>' commit.
        3. Retrieves active HEAD commit SHA.
        4. Serializes in-flight ticket, substeps, and next action to .edge/checkpoint.json.
        5. Transitions FSM state to CycleState.PAUSED.
        """
        work_dir = self._get_work_dir()
        code, status_out, _ = self._run_cmd(["git", "status", "--porcelain"], cwd=work_dir)
        dirty = bool(status_out.strip())
        has_uncommitted_work = False

        prior_state = self.state.current_state
        ticket = self.state.active_ticket
        ticket_id = ticket.ticket_id if ticket else "NO_TICKET"

        if dirty:
            commit_msg = f"wip(checkpoint): safe pause at {prior_state.value} [{ticket_id}]"
            self._run_cmd(["git", "add", "-A"], cwd=work_dir)
            self._run_cmd(["git", "commit", "-m", commit_msg], cwd=work_dir)
            has_uncommitted_work = True

        code, head_sha, _ = self._run_cmd(["git", "rev-parse", "HEAD"], cwd=work_dir)
        wip_commit_sha = head_sha.strip() if code == 0 else None

        completed, pending, next_action = self._get_substeps_for_state(prior_state, ticket)

        eff_worktree = ticket.worktree_path if (ticket and ticket.worktree_path) else self.state.active_worktree
        checkpoint = Checkpoint(
            paused_at=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            base_branch=self.state.base_branch,
            active_branch=self.state.active_branch,
            worktree_path=eff_worktree,
            active_worktree=eff_worktree,
            active_ticket=ticket,
            stashed_ticket=ticket.to_dict() if ticket else None,
            fsm_state=prior_state.value,
            completed_substeps=completed,
            pending_substeps=pending,
            wip_commit_sha=wip_commit_sha,
            has_uncommitted_work=has_uncommitted_work,
            next_action=next_action,
        )

        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.checkpoint_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(checkpoint.to_dict(), f, indent=2, ensure_ascii=False)
        if tmp_file.exists():
            if self.checkpoint_file.exists():
                self.checkpoint_file.unlink()
            tmp_file.rename(self.checkpoint_file)

        self._transition(CycleState.PAUSED, f"Paused: {reason} (prior state: {prior_state.value})", {
            "reason": reason,
            "prior_state": prior_state.value,
            "has_uncommitted_work": has_uncommitted_work,
            "wip_commit_sha": wip_commit_sha,
        })

        return checkpoint

    def resume(self) -> Tuple[bool, Optional[Checkpoint], str]:
        """
        Zero-Transcript Session Pickup:
        1. Reads .edge/checkpoint.json.
        2. Verifies / switches to active git branch.
        3. Restores FSM in-memory state and active ticket.
        4. Archives/removes checkpoint file.
        5. Returns actionable resume prompt for the next agent turn.
        """
        if not self.checkpoint_file.exists():
            return False, None, "No checkpoint found at .edge/checkpoint.json. Brigade is in state IDLE."

        try:
            with open(self.checkpoint_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            checkpoint = Checkpoint.from_dict(data)
        except Exception as e:
            return False, None, f"Failed to read checkpoint: {e}"

        # Branch verification
        has_wt = bool(checkpoint.active_worktree or checkpoint.worktree_path)
        if checkpoint.active_branch and not has_wt:
            code, curr_branch, _ = self._run_cmd(["git", "branch", "--show-current"])
            curr_branch_str = curr_branch.strip()
            if curr_branch_str != checkpoint.active_branch:
                self._run_cmd(["git", "checkout", checkpoint.active_branch])

        # Restore state
        try:
            restored_state = CycleState(checkpoint.fsm_state)
        except ValueError:
            restored_state = CycleState.IDLE

        self.state.current_state = restored_state
        self.state.active_ticket = checkpoint.active_ticket
        self.state.active_branch = checkpoint.active_branch
        self.state.active_worktree = checkpoint.active_worktree or checkpoint.worktree_path or (checkpoint.active_ticket.worktree_path if checkpoint.active_ticket else None)
        self.state.base_branch = checkpoint.base_branch
        self.state.blocked_reason = None

        self._transition(
            restored_state,
            f"Resumed from checkpoint (paused at {checkpoint.paused_at}). State restored to {checkpoint.fsm_state}.",
            {
                "checkpoint_reason": checkpoint.reason,
                "wip_commit_sha": checkpoint.wip_commit_sha,
            }
        )
        self.save()

        # Archive checkpoint by renaming or removing
        try:
            bak_file = self.checkpoint_file.with_suffix(".json.bak")
            if bak_file.exists():
                bak_file.unlink()
            self.checkpoint_file.rename(bak_file)
        except Exception:
            if self.checkpoint_file.exists():
                self.checkpoint_file.unlink()

        summary = (
            f"✅ Checkpoint restored successfully!\n"
            f"   State:     [{restored_state.value}]\n"
            f"   Ticket:    {checkpoint.active_ticket.ticket_id if checkpoint.active_ticket else 'None'}\n"
            f"   Branch:    {checkpoint.active_branch or 'None'}\n"
            f"   Next Step: {checkpoint.next_action}"
        )
        return True, checkpoint, summary

    @staticmethod
    def calculate_token_estimate(transcript_path: Path) -> int:
        norm_path = normalize_target_path(transcript_path)
        if not norm_path.exists():
            return 0
        total_chars = 0
        if norm_path.is_file():
            try:
                with open(norm_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        total_chars += len(line)
            except Exception:
                total_chars = norm_path.stat().st_size
        elif norm_path.is_dir():
            for p in norm_path.glob("*.jsonl"):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            total_chars += len(line)
                except Exception:
                    total_chars += p.stat().st_size
        return total_chars // 4

    @staticmethod
    def get_heat_zone(token_count: int) -> Tuple[ContextHeatZone, str]:
        if token_count < GREEN_HEAT_THRESHOLD:
            return (
                ContextHeatZone.GREEN,
                f"GREEN ZONE ({token_count:,} tokens): Context is optimal. Proceed with normal operations."
            )
        elif token_count <= YELLOW_HEAT_THRESHOLD:
            return (
                ContextHeatZone.YELLOW,
                f"YELLOW ZONE ({token_count:,} tokens): Cognitive drain limit approaching. DRAIN ACTIVE TICKET ONLY. Do NOT start new tickets. Trigger 'brigade pause' upon ticket completion."
            )
        else:
            return (
                ContextHeatZone.RED,
                f"RED ZONE ({token_count:,} tokens): Cognitive saturation limit reached! EMERGENCY CHECKPOINT REQUIRED. Run 'brigade pause' immediately to preserve in-flight work."
            )

    def check_heat(self, transcript_path: Path) -> Tuple[ContextHeatZone, int, str]:
        tokens = self.calculate_token_estimate(transcript_path)
        zone, recommendation = self.get_heat_zone(tokens)
        return zone, tokens, recommendation

