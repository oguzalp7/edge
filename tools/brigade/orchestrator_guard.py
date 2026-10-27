#!/usr/bin/env python3
"""
Antigravity Lifecycle Hook: Edge Brigade Multi-Station Tool & Lifecycle Guard.

Enforces deterministic role boundaries and Anti-Graveyard station persistence:
1. ORCHESTRATOR:
   - Denied: write_to_file, replace_file_content.
   - Guarded: invoke_subagent -> MUST reuse existing idle station via send_message if already active!
   - Injected: PreInvocation reminder of canonical 7 Brigade stations and anti-graveyard protocol.

2. EXAMINER / RESEARCHER:
   - Denied: write_to_file, replace_file_content (Pure read-only!).

3. SPEC_WRITER:
   - Allowed: specs/**, .edge/**, .lavish/**.
   - Denied: production code (src/**, app/**, lib/**, db/**).

4. SEAM_ARCHITECT:
   - Allowed: tests/**, *.test.ts, *.spec.ts, src/types/**, src/contracts/**.
   - Denied: implementation files in src/** (reserved for CODER).

5. CODER:
   - Allowed: src/**.
   - Denied: tests/**, *.test.ts, *.spec.ts (Test Immutability Invariant).

6. SURGEON:
   - Allowed: src/** within ticket boundaries.
   - Denied: src/db/schema/**, drizzle/** (MigrationGate Invariant).

7. QA_ENGINEER:
   - Denied: production code (src/**, app/**, lib/**, db/**, drizzle/**).

8. Anti-Graveyard Station Persistence:
   - Tracks active stations in ~/.gemini/antigravity/edge_active_stations.json.
   - When invoke_subagent is called: checks if requested role already exists and is active.
     If exists: DENY with explicit instruction to use send_message(Recipient: <id>, Message: ...).
   - PostToolUse: catches newly created subagents and registers them to edge_active_stations.json.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, Tuple, List, Union


# =============================================================================
# Antigraveyard Station Persistence, Discovery & Rotation Contracts (SPEC-001)
# =============================================================================

@dataclass
class TokenHeatRecord:
    tokens: int
    heat_zone: str  # "GREEN" | "YELLOW" | "RED"
    last_calculated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tokens": self.tokens,
            "heatZone": self.heat_zone,
            "heat_zone": self.heat_zone,
            "lastCalculatedAt": self.last_calculated_at,
        }


@dataclass
class StationRecord:
    conversation_id: str
    role: str
    canonical_role: str
    parent_conversation_id: str
    status: str = "IDLE"  # "IDLE" | "BUSY" | "EXHAUSTED" | "ROTATED"
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_active_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    token_heat: TokenHeatRecord = field(default_factory=lambda: TokenHeatRecord(tokens=0, heat_zone="GREEN"))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "conversationId": self.conversation_id,
            "role": self.canonical_role or self.role,
            "canonicalRole": self.canonical_role,
            "parentConversationId": self.parent_conversation_id,
            "status": self.status,
            "registeredAt": self.registered_at,
            "lastActiveAt": self.last_active_at,
            "tokenHeat": self.token_heat.to_dict(),
        }


class StationStoreEnvelope(dict):
    """
    Transparent dictionary envelope supporting both legacy flat access:
        data[cid] -> returns station record
        cid in data -> checks station presence
    and structured template access:
        data["version"], data["stations"], data["sessions"]
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        legacy_keys = [k for k in list(self.keys()) if k not in ("version", "initializedAt", "sessions", "stations")]
        if "stations" not in self:
            super().__setitem__("stations", {})
        if "sessions" not in self:
            super().__setitem__("sessions", {})
        if "version" not in self:
            super().__setitem__("version", "1.0")
        if "initializedAt" not in self:
            super().__setitem__("initializedAt", datetime.now(timezone.utc).isoformat())

        if legacy_keys:
            stations = super().__getitem__("stations")
            for k in legacy_keys:
                stations[k] = super().__getitem__(k)
                super().__delitem__(k)

    def __getitem__(self, key: str) -> Any:
        if key in ("version", "initializedAt", "sessions", "stations"):
            return super().__getitem__(key)
        stations = super().__getitem__("stations")
        if key in stations:
            return stations[key]
        return super().__getitem__(key)

    def __setitem__(self, key: str, value: Any) -> None:
        if key in ("version", "initializedAt", "sessions", "stations"):
            super().__setitem__(key, value)
        else:
            stations = super().setdefault("stations", {})
            stations[key] = value

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        stations = super().get("stations", {})
        return key in stations

    def get(self, key: str, default: Any = None) -> Any:
        if key in ("version", "initializedAt", "sessions", "stations"):
            return super().get(key, default)
        stations = super().get("stations", {})
        if key in stations:
            return stations[key]
        return super().get(key, default)

    def __delitem__(self, key: str) -> None:
        stations = super().get("stations", {})
        if key in stations:
            del stations[key]
            return
        super().__delitem__(key)

    def get_stations(self) -> Dict[str, Dict[str, Any]]:
        return super().get("stations", {})


class StationStore:
    def __init__(self, store_path: Path):
        self.store_path = Path(store_path)

    def load(self) -> StationStoreEnvelope:
        """Loads store from disk, initializing template atomically if missing."""
        if not self.store_path.exists():
            envelope = StationStoreEnvelope({
                "version": "1.0",
                "initializedAt": datetime.now(timezone.utc).isoformat(),
                "sessions": {},
                "stations": {},
            })
            self.save(envelope)
            return envelope

        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception:
            raw_data = {}

        if not isinstance(raw_data, dict):
            raw_data = {}

        envelope = StationStoreEnvelope(raw_data)

        # Legacy flat format migration check
        is_legacy = "version" not in raw_data and "stations" not in raw_data
        if is_legacy:
            self.save(envelope)

        return envelope

    def save(self, envelope: Union[StationStoreEnvelope, Dict[str, Any]]) -> None:
        """Atomically persists envelope to disk via temporary file rename."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(envelope, StationStoreEnvelope):
            payload = {
                "version": envelope.get("version", "1.0"),
                "initializedAt": envelope.get("initializedAt", datetime.now(timezone.utc).isoformat()),
                "sessions": envelope.get("sessions", {}),
                "stations": envelope.get_stations(),
            }
        elif isinstance(envelope, dict):
            if "version" not in envelope and "stations" not in envelope:
                payload = {
                    "version": "1.0",
                    "initializedAt": datetime.now(timezone.utc).isoformat(),
                    "sessions": {},
                    "stations": dict(envelope),
                }
            else:
                payload = {
                    "version": envelope.get("version", "1.0"),
                    "initializedAt": envelope.get("initializedAt", datetime.now(timezone.utc).isoformat()),
                    "sessions": envelope.get("sessions", {}),
                    "stations": envelope.get("stations", {}),
                }
        else:
            payload = {
                "version": "1.0",
                "initializedAt": datetime.now(timezone.utc).isoformat(),
                "sessions": {},
                "stations": {},
            }

        temp_file = self.store_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        temp_file.replace(self.store_path)

    def register(self, conversation_id: str, role: str, parent_cid: str = "") -> StationRecord:
        """Registers a newly spawned subagent station worker."""
        if not conversation_id:
            raise ValueError("conversation_id is required")

        canonical = normalize_role(role) or role.strip().upper()
        now_iso = datetime.now(timezone.utc).isoformat()
        record = StationRecord(
            conversation_id=conversation_id,
            role=role,
            canonical_role=canonical,
            parent_conversation_id=parent_cid,
            status="IDLE",
            registered_at=now_iso,
            last_active_at=now_iso,
            token_heat=TokenHeatRecord(tokens=0, heat_zone="GREEN", last_calculated_at=now_iso),
        )

        envelope = self.load()
        envelope.get_stations()[conversation_id] = record.to_dict()

        if parent_cid:
            sessions = envelope.setdefault("sessions", {})
            session = sessions.setdefault(parent_cid, {
                "parentConversationId": parent_cid,
                "registeredStations": [],
                "lastScannedAt": now_iso,
            })
            reg_stations = session.setdefault("registeredStations", [])
            if conversation_id not in reg_stations:
                reg_stations.append(conversation_id)
            session["lastScannedAt"] = now_iso

        self.save(envelope)
        return record

    def mark_exhausted(self, conversation_id: str) -> None:
        """Marks a saturated worker as EXHAUSTED prior to rotation."""
        envelope = self.load()
        stations = envelope.get_stations()
        if conversation_id in stations:
            stations[conversation_id]["status"] = "EXHAUSTED"
            stations[conversation_id]["lastActiveAt"] = datetime.now(timezone.utc).isoformat()
            self.save(envelope)


class TranscriptStationScanner:
    def __init__(self, brain_root: Path):
        self.brain_root = to_wsl_path(str(brain_root))

    def discover_session_stations(self, parent_transcript_path: Path) -> List[Tuple[str, str]]:
        """
        Parses parent transcript to pair invoke_subagent calls with subsequent
        system confirmation steps, returning list of (conversation_id, raw_role).
        """
        parent_path = to_wsl_path(str(parent_transcript_path))
        if not parent_path.exists():
            return []

        pairs: List[Tuple[str, str]] = []
        pending_roles: List[str] = []

        try:
            with open(parent_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        step = json.loads(line_str)
                    except Exception:
                        step = {}

                    tool_calls = step.get("tool_calls", [])
                    for tc in tool_calls:
                        if tc.get("name") == "invoke_subagent":
                            tc_args = tc.get("args", {})
                            req_roles = extract_requested_roles(tc_args)
                            for r in req_roles:
                                canonical = normalize_role(r) or r
                                pending_roles.append(canonical)

                    content = step.get("content", "")
                    text_to_search = content if "conversationId" in content else line_str
                    if "conversationId" in text_to_search:
                        cids = re.findall(r'\\?["\']conversationId\\?["\']\s*:\s*\\?["\']([a-f0-9\-]+)\\?["\']', text_to_search)
                        for cid in cids:
                            role = pending_roles.pop(0) if pending_roles else "STATION_WORKER"
                            pairs.append((cid, role))
        except Exception:
            pass

        return pairs

    def calculate_subagent_heat(self, conversation_id: str) -> TokenHeatRecord:
        """
        Inspects subagent transcript at brain/<cid>/.system_generated/logs/transcript.jsonl
        and computes exact token count (input + cache_read) or character fallback.
        """
        brain_root = to_wsl_path(str(self.brain_root))
        subagent_transcript = brain_root / conversation_id / ".system_generated" / "logs" / "transcript.jsonl"

        now_iso = datetime.now(timezone.utc).isoformat()
        if not subagent_transcript.exists():
            return TokenHeatRecord(tokens=0, heat_zone="GREEN", last_calculated_at=now_iso)

        total_tokens = 0
        total_chars = 0
        found_explicit_tokens = False

        try:
            with open(subagent_transcript, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    total_chars += len(line)
                    line_str = line.strip()
                    if not line_str:
                        continue
                    try:
                        step = json.loads(line_str)
                    except Exception:
                        continue

                    inp = step.get("input_tokens")
                    cache = step.get("cache_read_tokens")
                    tok = step.get("total_tokens") or step.get("tokens")

                    if inp is not None or cache is not None or tok is not None:
                        found_explicit_tokens = True
                        step_tokens = (inp or 0) + (cache or 0)
                        if step_tokens == 0 and tok:
                            step_tokens = tok
                        total_tokens = step_tokens
        except Exception:
            pass

        if not found_explicit_tokens:
            total_tokens = total_chars // 4

        if total_tokens < 180000:
            heat_zone = "GREEN"
        elif total_tokens <= 250000:
            heat_zone = "YELLOW"
        else:
            heat_zone = "RED"

        return TokenHeatRecord(tokens=total_tokens, heat_zone=heat_zone, last_calculated_at=now_iso)


class StationSelector:
    @staticmethod
    def evaluate_spawn_request(
        store: StationStore,
        scanner: TranscriptStationScanner,
        parent_cid: str,
        requested_role: str
    ) -> Dict[str, str]:
        """
        Evaluates an invoke_subagent request against Cases A, B, and C.
        Returns {"decision": "allow"} or {"decision": "deny", "reason": "..."}.
        """
        canonical = normalize_role(requested_role) or requested_role.strip().upper()
        envelope = store.load()
        stations = envelope.get_stations()

        matching_candidates = []
        for cid, info in stations.items():
            if not isinstance(info, dict):
                continue
            st_role = normalize_role(info.get("role", "") or info.get("canonicalRole", "")) or info.get("role", "").upper()
            if st_role != canonical:
                continue
            st_parent = info.get("parentConversationId", "")
            if parent_cid and st_parent and st_parent != parent_cid:
                continue
            status = info.get("status", "IDLE")
            if status in ("EXHAUSTED", "ROTATED", "TERMINATED"):
                continue

            heat_info = info.get("tokenHeat") or {}
            tokens = heat_info.get("tokens", 0)
            heat_zone = heat_info.get("heatZone") or heat_info.get("heat_zone") or "GREEN"

            if scanner:
                try:
                    live_heat = scanner.calculate_subagent_heat(cid)
                    if live_heat.tokens > 0:
                        tokens = live_heat.tokens
                        heat_zone = live_heat.heat_zone
                except Exception:
                    pass

            matching_candidates.append((cid, info, tokens, heat_zone))

        # Case A: No active worker exists for role
        if not matching_candidates:
            return {"decision": "allow"}

        # Case B: At least one green worker (< 180k tokens)
        green_candidates = [c for c in matching_candidates if c[2] < 180000 and c[3] == "GREEN"]
        if green_candidates:
            greenest_cid, greenest_info, greenest_tokens, _ = min(green_candidates, key=lambda c: c[2])
            return {
                "decision": "deny",
                "reason": (
                    f"❌ [PERSISTENT STATION REUSE REQUIRED]: An active, healthy station worker for role '{canonical}' "
                    f"already exists in this session (conversationId: '{greenest_cid}', heat: GREEN, {greenest_tokens} tokens).\n\n"
                    f"🛑 ANTI-GRAVEYARD PROTOCOL ENFORCED:\n"
                    f"Do NOT call `invoke_subagent` to spawn duplicate subagents!\n"
                    f"You must reuse the existing persistent station worker by sending your task package via:\n"
                    f"`send_message(Recipient: \"{greenest_cid}\", Message: ...)`"
                ),
            }

        # Case C: All matching workers are saturated (>= 180k tokens or heat_zone in ("YELLOW", "RED"))
        for cid, _, _, _ in matching_candidates:
            store.mark_exhausted(cid)

        return {"decision": "allow", "reason": "ROTATION: Worker saturated"}


def get_active_stations_path() -> Path:
    candidates = [
        Path("/mnt/c/Users/oguz_/.gemini/antigravity/edge_active_stations.json"),
        Path.home() / ".gemini" / "antigravity" / "edge_active_stations.json",
        Path("/tmp/edge_active_stations.json"),
    ]
    for p in candidates:
        if p.parent.exists():
            return p
    return candidates[-1]


ACTIVE_STATIONS_FILE = get_active_stations_path()

CANONICAL_ROLES = {
    "SPEC_WRITER": ["spec_writer", "spec writer", "spec-writer", "translator", "slicer", "n-spec"],
    "RESEARCHER": ["researcher", "research", "recon", "reconnaissance", "investigator", "rca", "root cause"],
    "SEAM_ARCHITECT": ["seam_architect", "seam architect", "seam-architect", "contract", "test author", "red test", "tdd"],
    "CODER": ["coder", "programmer", "worker", "implementer", "production worker"],
    "SURGEON": ["surgeon", "refactor", "refactorer", "chef de partie", "decoupling"],
    "EXAMINER": ["examiner", "reviewer", "code reviewer", "standards_examiner", "standards examiner", "standards-examiner", "spec_examiner", "spec examiner", "spec-examiner", "sous chef", "maitre d"],
    "QA_ENGINEER": ["qa_engineer", "qa", "e2e", "e2e_tester", "sommelier", "inspector", "test_agent", "qa agent"],
}


def to_wsl_path(p_str: str) -> Path:
    if not p_str:
        return Path("")
    p = p_str.replace("\\", "/")
    if ":" in p:
        drive, rest = p.split(":", 1)
        p = f"/mnt/{drive.lower()}{rest}"
    return Path(p)


def normalize_role(raw_role: str) -> Optional[str]:
    if not raw_role:
        return None
    raw_lower = raw_role.strip().lower()
    for canonical, aliases in CANONICAL_ROLES.items():
        if canonical.lower() == raw_lower:
            return canonical
        for alias in aliases:
            if alias in raw_lower:
                return canonical
    return None


def load_active_stations() -> StationStoreEnvelope:
    store = StationStore(ACTIVE_STATIONS_FILE)
    return store.load()


def save_active_stations(data: Union[StationStoreEnvelope, Dict[str, Any]]) -> None:
    store = StationStore(ACTIVE_STATIONS_FILE)
    store.save(data)


def register_station(conversation_id: str, role: str, parent_cid: str = "") -> Optional[StationRecord]:
    if not conversation_id:
        return None
    store = StationStore(ACTIVE_STATIONS_FILE)
    return store.register(conversation_id, role, parent_cid)


def find_active_station(role: str, parent_cid: str = "") -> Optional[Tuple[str, Dict[str, Any]]]:
    canonical = normalize_role(role) or role.strip().upper()
    data = load_active_stations()
    stations = data.get_stations() if isinstance(data, StationStoreEnvelope) else (data.get("stations") if isinstance(data, dict) and "stations" in data else data)
    for cid, info in stations.items():
        if not isinstance(info, dict):
            continue
        st_role = normalize_role(info.get("role", "") or info.get("canonicalRole", "")) or info.get("role", "").upper()
        if st_role == canonical:
            status = info.get("status", "IDLE")
            if status in ("EXHAUSTED", "ROTATED", "TERMINATED"):
                continue
            if not parent_cid or info.get("parentConversationId") == parent_cid:
                return cid, info
    return None


def detect_session_role(payload: dict) -> Tuple[str, str]:
    cid = payload.get("conversationId", "")
    active_data = load_active_stations()
    if cid and cid in active_data:
        return active_data[cid].get("role", "UNKNOWN"), "active_registry"

    transcript_path = payload.get("transcriptPath", "")
    if transcript_path:
        tp = to_wsl_path(transcript_path)
        if tp.exists():
            try:
                with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                    first_lines = []
                    for idx, line in enumerate(f):
                        if idx > 25:
                            break
                        first_lines.append(line)

                if first_lines:
                    first_obj = json.loads(first_lines[0])
                    # If step 0 has sender, it is a subagent session!
                    if first_obj.get("source") == "SYSTEM" and "[Message]" in first_obj.get("content", ""):
                        msg_content = first_obj.get("content", "").lower()
                        for canonical, aliases in CANONICAL_ROLES.items():
                            if canonical.lower() in msg_content:
                                return canonical, "transcript_subagent_keyword"
                            for alias in aliases:
                                if alias in msg_content:
                                    return canonical, "transcript_subagent_alias"
                        return "SUBAGENT_GENERIC", "transcript_subagent"

                    # If step 0 is user input or contains edge-orchestrator
                    if first_obj.get("source") == "USER_EXPLICIT" or any("edge-orchestrator" in l for l in first_lines):
                        return "ORCHESTRATOR", "transcript_root"
            except Exception:
                pass

    return "UNKNOWN", "default"


def parse_subagents(raw_subagents: Any) -> List[Dict[str, Any]]:
    if not raw_subagents:
        return []
    if isinstance(raw_subagents, list):
        return raw_subagents
    if isinstance(raw_subagents, str):
        try:
            parsed = json.loads(raw_subagents)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
    return []


def extract_requested_roles(args: dict) -> List[str]:
    """Extracts role names from Antigravity native (Role) or legacy (Subagents) invoke_subagent tool args."""
    roles = []
    # 1. Direct Antigravity invoke_subagent: Role parameter
    role_arg = args.get("Role") or args.get("role")
    if role_arg:
        roles.append(str(role_arg).strip())
    # 2. Legacy / multi-subagent array
    subagents_arg = args.get("Subagents") or args.get("subagents")
    if subagents_arg:
        subagents = parse_subagents(subagents_arg)
        for sa in subagents:
            if isinstance(sa, dict) and sa.get("Role"):
                roles.append(str(sa.get("Role")).strip())
    return roles


def get_target_file(args: dict) -> str:
    """Extracts target file path from Antigravity (Path) or legacy (TargetFile/path/file_path) args."""
    path_val = (
        args.get("Path")
        or args.get("path")
        or args.get("TargetFile")
        or args.get("target_file")
        or args.get("file_path")
        or ""
    )
    return str(path_val).replace("\\", "/").lower()


def handle_pre_tool(payload: dict) -> dict:
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    role, detection_source = detect_session_role(payload)
    parent_cid = payload.get("conversationId", "")

    # 1. invoke_subagent: Anti-Graveyard & Station Reuse Enforcement
    if tool_name == "invoke_subagent":
        store = StationStore(ACTIVE_STATIONS_FILE)
        brain_root = ACTIVE_STATIONS_FILE.parent / "brain"
        scanner = TranscriptStationScanner(brain_root)
        requested_roles = extract_requested_roles(args)
        for req_role in requested_roles:
            eval_res = StationSelector.evaluate_spawn_request(
                store=store,
                scanner=scanner,
                parent_cid=parent_cid,
                requested_role=req_role
            )
            if eval_res.get("decision") == "deny":
                return eval_res
        return {"decision": "allow"}

    target_file = get_target_file(args)

    # 2. write_file, edit_file & legacy file mutation: Physical Tool Boundaries
    if tool_name in ("write_file", "edit_file", "write_to_file", "replace_file_content"):
        # A. Orchestrator: Sovereign Commander in Green Zone
        if role == "ORCHESTRATOR":
            # Allowed: Antigravity brain artifacts and .edge state/checkpoints
            is_artifact_or_state = any(k in target_file for k in ["/brain/", "brain/", ".edge/", "/.edge/"]) or "artifactmetadata" in str(args).lower()
            if not is_artifact_or_state:
                return {
                    "decision": "deny",
                    "reason": (
                        "❌ [EDGE ORCHESTRATOR HARD GUARD]: Kök Ajan (Orkestratör) Yeşil Alandadır ve doğrudan kaynak kod yazamaz / dosya düzenleyemez! "
                        "Yalnızca Antigravity brain artifact'leri (`<appDataDir>/brain/**`) ve `.edge/**` durum dosyalarını yazabilirsiniz. "
                        "Kaynak kod değişikliklerini ilgili istasyon çalışanına (coder, surgeon, seam_architect vb.) delege etmelisiniz."
                    ),
                }

        # B. Pure Read-Only Stations: EXAMINER, RESEARCHER
        if role in ("EXAMINER", "RESEARCHER"):
            return {
                "decision": "deny",
                "reason": (
                    f"❌ [STATION PURITY GUARD]: '{role}' istasyonu salt-okunur (read-only) denetçidir. "
                    "Hiçbir dosyada değişiklik yapamaz / kod yazamaz!"
                ),
            }

        # D. SPEC_WRITER: Specifications & Prototypes Only
        if role == "SPEC_WRITER":
            if not any(k in target_file for k in ["specs/", "/specs/", ".edge/", "/.edge/", ".lavish/", "/.lavish/"]):
                return {
                    "decision": "deny",
                    "reason": (
                        f"❌ [SPEC BOUNDARY GUARD]: SPEC_WRITER yalnızca `specs/**`, `.edge/**` ve `.lavish/**` dizinlerinde şartname ve prototip yazabilir. "
                        f"Üretim koduna (`{target_file}`) dokunamaz!"
                    ),
                }

        # E. SEAM_ARCHITECT: Red Tests & Interface Contracts Only
        if role == "SEAM_ARCHITECT":
            is_test = any(k in target_file for k in ["tests/", "/tests/", ".test.", ".spec."])
            is_contract = any(k in target_file for k in ["types/", "/types/", "contracts/", "/contracts/"])
            if not (is_test or is_contract):
                return {
                    "decision": "deny",
                    "reason": (
                        f"❌ [TDD SEAM GUARD]: SEAM_ARCHITECT yalnızca `tests/**` altında kırmızı testler ve `src/types/**` altında sözleşmeler yazabilir. "
                        f"Üretim kodunu (`{target_file}`) CODER istasyonuna bırakmalıdır!"
                    ),
                }

        # F. CODER: Production Code Worker (Test Immutability Invariant)
        if role == "CODER":
            if any(k in target_file for k in ["tests/", "/tests/", ".test.", ".spec."]):
                return {
                    "decision": "deny",
                    "reason": (
                        f"❌ [TEST IMMUTABILITY GUARD]: CODER istasyonu test dosyalarını (`{target_file}`) değiştiremez veya gevşetemez! "
                        "Kırmızı testleri yeşile çevirmek için yalnızca `src/` altındaki üretim kodunu düzenlemelisiniz."
                    ),
                }

        # G. SURGEON: Refactor Specialist (MigrationGate Invariant)
        if role == "SURGEON":
            if any(k in target_file for k in ["db/schema/", "/db/schema/", "drizzle/", "/drizzle/"]):
                return {
                    "decision": "deny",
                    "reason": (
                        f"❌ [MIGRATIONGATE GUARD]: SURGEON istasyonu veritabanı şemasını veya migrasyonları (`{target_file}`) doğrudan değiştiremez! "
                        "Şema değişiklikleri ayrı bir mimari migrasyon gerektirir."
                    ),
                }

        # H. QA_ENGINEER: Sommelier & E2E Browser / Visual Quality Inspector
        if role == "QA_ENGINEER":
            if any(k in target_file for k in ["/src/", "src/", "/app/", "app/", "/lib/", "lib/", "/db/", "db/", "/drizzle/", "drizzle/"]):
                return {
                    "decision": "deny",
                    "reason": (
                        f"❌ [QA BOUNDARY GUARD]: QA_ENGINEER (Sommelier) istasyonu uçtan uca tarayıcı ve davranış denetçisidir. "
                        f"Üretim kodunu (`{target_file}`) düzenleyemez! Bulunan hatalar ve görsel kusurlar Orkestratör üzerinden "
                        "SURGEON veya CODER istasyonuna raporlanmalıdır."
                    ),
                }

    # 3. read_file & view_file: Lean Context Guard for ORCHESTRATOR
    if tool_name in ("read_file", "view_file"):
        if role == "ORCHESTRATOR":
            allowed_read_keywords = [
                "/brain/", "brain/",
                ".edge/", "/.edge/",
                ".lavish/", "/.lavish/",
                "specs/", "/specs/",
                "coding_standards",
                "agents.md",
                "gemini.md",
                "readme.md",
                "architecture.md",
                "package.json",
                "tsconfig.json",
                "treehouse.toml",
            ]
            is_allowed = any(k in target_file for k in allowed_read_keywords)

            code_or_test_keywords = [
                "/src/", "src/",
                "/app/", "app/",
                "/lib/", "lib/",
                "/db/", "db/",
                "/drizzle/", "drizzle/",
                "/tests/", "tests/",
                ".test.", ".spec.",
            ]
            is_code_or_test = any(k in target_file for k in code_or_test_keywords)

            if is_code_or_test and not is_allowed:
                return {
                    "decision": "deny",
                    "reason": (
                        "❌ [EDGE ORCHESTRATOR LEAN CONTEXT GUARD]: Kök Ajan (Orkestratör) Yeşil Alandadır ve doğrudan üretim veya test kodu okuyamaz! "
                        f"Hedef dosya: `{target_file}`. "
                        "Kod incelemesi ve kök neden analizi (RCA) için RESEARCHER istasyonunu (`invoke_subagent` / `send_message`) görevlendiriniz. "
                        "Orkestratör yalnızca `.edge/**`, `specs/**`, `coding_standards.md` ve artifact belgelerini okuyabilir."
                    ),
                }

    return {"decision": "allow"}


def handle_post_tool(payload: dict) -> dict:
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    parent_cid = payload.get("conversationId", "")

    if tool_name == "invoke_subagent":
        transcript_path = payload.get("transcriptPath", "")
        if transcript_path:
            tp = to_wsl_path(transcript_path)
            if tp.exists():
                try:
                    with open(tp, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                    for line in reversed(lines[-15:]):
                        match = re.search(r'\\?["\']conversationId\\?["\']\s*:\s*\\?["\']([a-f0-9\-]+)\\?["\']', line)
                        if match:
                            created_cid = match.group(1)
                            requested_roles = extract_requested_roles(args)
                            role = requested_roles[0] if requested_roles else "STATION_WORKER"
                            register_station(created_cid, role, parent_cid)
                            break
                except Exception:
                    pass

    return {}


def handle_pre_invocation(payload: dict) -> dict:
    role, source = detect_session_role(payload)

    if role == "ORCHESTRATOR":
        return {
            "injectSteps": [
                {
                    "ephemeralMessage": (
                        "🚨 [EDGE ORCHESTRATOR ENFORCED]: You are the Sovereign Commander (Orchestrator) in the Green Zone.\n"
                        "- You do NOT write production source code (only Antigravity brain artifacts and `.edge/**` checkpoints are permitted).\n"
                        "- UI Visual Gate (`lavish-axi`): When SPEC_WRITER produces `.lavish/*.html`, present the active session URL to the human and run `lavish-axi poll <file>` in the background (WaitMsBeforeAsync: 1000, IsDaemon: false). Await user approval before advancing to SEAM_ARCHITECT.\n"
                        "- Canonical Brigade Stations: SPEC_WRITER, RESEARCHER, SEAM_ARCHITECT, CODER, SURGEON, EXAMINER, QA_ENGINEER.\n"
                        "- Anti-Graveyard Protocol: ALWAYS check existing stations with `manage_subagents(Action: 'list')`. "
                        "If an active station exists for the role, REUSE it via `send_message`. Only call `invoke_subagent` if no station exists yet."
                    )
                }
            ]
        }
    elif role == "QA_ENGINEER":
        return {
            "injectSteps": [
                {
                    "ephemeralMessage": (
                        "🚨 [BRIGADE STATION ENFORCED - QA_ENGINEER]: You are the persistent Sommelier & E2E QA Engineer in Edge Brigade.\n"
                        "- Primary Tooling: Use `chrome-dev-tools-axi` or `chrome-devtools-mcp` tools (`navigate_page`, `click`, `fill`, `evaluate_script`, `take_screenshot`, `list_console_messages`, `list_network_requests`).\n"
                        "- Negative Invariant: You CANNOT edit production code (`src/**`). Found defects must be reported back to the Orchestrator with exact reproduction steps and screenshots."
                    )
                }
            ]
        }
    elif role in CANONICAL_ROLES:
        return {
            "injectSteps": [
                {
                    "ephemeralMessage": (
                        f"🚨 [BRIGADE STATION ENFORCED - {role}]: You are operating as the persistent {role} station worker.\n"
                        f"Operate strictly within your station boundaries. When your task package is complete, report back cleanly."
                    )
                }
            ]
        }

    return {"injectSteps": []}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre_tool"

    try:
        raw_input = sys.stdin.read()
        if not raw_input.strip():
            payload = {}
        else:
            payload = json.loads(raw_input)
    except Exception:
        payload = {}

    if mode == "pre_invocation":
        result = handle_pre_invocation(payload)
    elif mode == "post_tool":
        result = handle_post_tool(payload)
    else:
        result = handle_pre_tool(payload)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()

