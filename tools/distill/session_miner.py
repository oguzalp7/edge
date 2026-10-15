#!/usr/bin/env python3
"""
Antigravity Transcript Miner & Architectural Intent Analyzer.
Part of the edge-distill toolset (tools/distill/session_miner.py).

Features:
- Deterministic, streaming discovery of transcript.jsonl across Antigravity brains.
- Zero external dependencies: pure Python standard library.
- Zero-crash streaming: silently skips malformed JSON or partial lines.
- Hierarchical project grouping (workspaceUris -> tool args -> UNASSIGNED/SCRATCH).
- Chronological session ordering and metric computation.
- Architectural intent clustering across 5 core engineering invariants with quotes.
"""

import os
import sys
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any, Tuple, Set, Union


# ---------------------------------------------------------------------------
# Default Brain Search Roots & Path Invariants
# ---------------------------------------------------------------------------

DEFAULT_BRAIN_ROOTS = [
    Path(r"C:\Users\oguz_\.gemini\antigravity\brain"),
    Path(r"C:\Users\oguz_\.gemini\antigravity-cli\brain"),
    Path("/mnt/c/Users/oguz_/.gemini/antigravity/brain"),
    Path("/mnt/c/Users/oguz_/.gemini/antigravity-cli/brain"),
    Path.home() / ".gemini" / "antigravity" / "brain",
    Path.home() / ".gemini" / "antigravity-cli" / "brain",
]

BRAIN_REGEX = re.compile(r'[/\\]\.gemini[/\\]antigravity(?:-cli)?[/\\]brain', re.IGNORECASE)
MCP_REGEX = re.compile(r'[/\\]\.gemini[/\\]antigravity(?:-cli)?[/\\]mcp', re.IGNORECASE)


# ---------------------------------------------------------------------------
# 5 Core Architectural Intent Clusters
# ---------------------------------------------------------------------------

INTENT_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "Context Hygiene": {
        "title": "Bağlam Hijyeni & Delegasyon (Context Hygiene)",
        "rule_hint": "rules/AGENTS.md & rules/playbooks/pause-safely.md",
        "patterns": [
            "bağlam", "baglam", "balon", "temiz tut", "alt ajan", "altajan",
            "delege", "koda boğulma", "koda bogulma", "yeşil alan", "yesil alan",
            "hafıza şiş", "hafiza sis", "soğuk başlangıç",
            "soguk baslangic", "kirletme"
        ]
    },
    "Vertical Slice": {
        "title": "Dikey Dilim & Bütünlük (Vertical Slice & Pocock/Dex Invariant)",
        "rule_hint": "rules/feature.md & rules/AGENTS.md",
        "patterns": [
            "dikey dilim", "vertical slice", "uçtan uca", "uctan uca",
            "yarım bırakma", "yarim birakma", "sadece db", "katman",
            "asılı kal", "asili kal"
        ]
    },
    "Seam & Contracts": {
        "title": "Seam & Sözleşme Disiplini (Feathers Seams & Contracts)",
        "rule_hint": "rules/refactor.md & rules/edge-core-refactor",
        "patterns": [
            "seam", "dikiş yeri", "dikis yeri", "sözleşme", "sozlesme",
            "contract", "interface", "repo", "controller şişkin", "controller siskin"
        ]
    },
    "Test Immutability": {
        "title": "TDD & Test İntizamı (Test Immutability & Anti-Cheating)",
        "rule_hint": "rules/refactor.md & rules/feature.md (Karakterizasyon Testi)",
        "patterns": [
            "önce test", "once test", "kırmızı test", "kirmizi test",
            "testi bozma", "sahte test", "hile yapma", "karakterizasyon",
            "kodu teste uydurma"
        ]
    },
    "Visual Gate": {
        "title": "Görsel Doğrulama & UI (Visual Gate)",
        "rule_hint": "skills/edge-orchestrator/SKILL.md (lavish-axi)",
        "patterns": [
            "lavish", "prototip", "görsel", "gorsel", "arayüz", "arayuz",
            "bana göster", "bana goster", "onay almadan yazma", "tarayıcı", "tarayici"
        ]
    }
}


# ---------------------------------------------------------------------------
# Path & Project Extraction Helpers
# ---------------------------------------------------------------------------

def normalize_path_string(p: str) -> str:
    """Cleans up raw path/URI strings, normalizing separators and removing URL prefixes."""
    if not p:
        return ""
    p = str(p).strip().strip('"\'')
    if p.startswith("file:///"):
        p = p[8:]
    elif p.startswith("file://"):
        p = p[7:]
    p = p.replace("\\\\", "/").replace("\\", "/")
    return p


def extract_project_from_path(p: str) -> Optional[str]:
    """
    Extracts high-confidence project name from path or URI string.
    Filters out internal brain/mcp scratch paths, filenames, and test directories.
    """
    norm = normalize_path_string(p)
    if not norm or BRAIN_REGEX.search(norm) or MCP_REGEX.search(norm):
        return None

    # Strip Windows drive letters or WSL mount prefixes
    stripped = re.sub(r'^(?:[a-zA-Z]:/|//wsl\.localhost/[^/]+/|/mnt/[a-z]/)', '/', norm)

    # If it's just a file without directory slashes, ignore it
    if "/" not in stripped.strip("/"):
        return None

    # If the path ends with a file name containing an extension, strip the file
    if re.search(r'/[^/]+\.[a-zA-Z0-9_\-]+$', stripped):
        stripped = re.sub(r'/[^/]+\.[a-zA-Z0-9_\-]+$', '', stripped)

    # 1. Match plugins/<name>
    m_plugin = re.search(r'(?:^|/)plugins/([a-zA-Z0-9_\-]+)', stripped)
    if m_plugin:
        return m_plugin.group(1)

    # 2. Match worktrees/<name>
    m_wt = re.search(r'(?:^|/)worktrees/([a-zA-Z0-9_\-]+)', stripped)
    if m_wt:
        wt_target = m_wt.group(1)
        # If worktree target is a hex hash, resolve to the repo folder before worktrees
        if re.match(r'^[0-9a-f]{8,}$', wt_target):
            m_repo = re.search(r'/([^/]+)/worktrees/' + wt_target, stripped)
            if m_repo:
                repo_name = m_repo.group(1).lstrip(".")
                if repo_name and repo_name not in ("antigravity", "antigravity-cli", "var", "tmp"):
                    return repo_name
        else:
            return wt_target

    # 3. Match home/<user>/<name> or Desktop/<name>
    m_user = re.search(r'(?:/home/[^/]+|/Users/[^/]+/Desktop|/Desktop)/([a-zA-Z0-9_\-]+)', stripped)
    if m_user:
        name = m_user.group(1).lstrip(".")
        if name not in ("tmp", "temp", "cache", "var"):
            return name

    # 4. Check segments for common dev directory structure
    parts = [part for part in stripped.strip("/").split("/") if part]
    ignored_subdirs = {"tests", "test", "unit", "src", "dist", "build", "resources", "node_modules"}

    if len(parts) >= 2:
        if parts[0] in ("tmp", "temp", "var", "opt") and len(parts) >= 2:
            cand = parts[1]
            if cand not in ignored_subdirs:
                return cand
        if len(parts) >= 2 and parts[1] in ("src", "lib", "tests", "test", "app", "components"):
            cand = parts[0]
            if cand not in ignored_subdirs:
                return cand

    return None

    return None


def extract_paths_from_command(cmd: str) -> List[str]:
    """Extracts path-like tokens from a command line string."""
    if not cmd or not isinstance(cmd, str):
        return []
    # Match potential paths like /foo/bar or C:\foo\bar
    matches = re.findall(r'(?:[a-zA-Z]:[\\/]|/[a-zA-Z0-9_.-]+)[^\s"\'><;|]+', cmd)
    return matches


def extract_conversation_id(transcript_path: Path) -> str:
    """Extracts conversation_id from standard brain path layout."""
    parts = transcript_path.parts
    if len(parts) >= 4 and parts[-3] == ".system_generated":
        return parts[-4]
    return transcript_path.parent.name


def parse_timestamp(ts: str) -> Optional[datetime]:
    """Parses ISO timestamp safely, handling Z suffix and timezone offsets."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        clean = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(clean)
    except Exception:
        return None


def extract_clean_quote(text: str, keyword: str) -> str:
    """Extracts a crisp, meaningful sentence or snippet containing the target keyword."""
    if not text:
        return ""
    # Strip XML tags such as <USER_REQUEST>
    cleaned = re.sub(r'<[^>]+>', ' ', text)
    sentences = re.split(r'[\n.!?]+', cleaned)
    for s in sentences:
        s = s.strip()
        if keyword.lower() in s.lower() and len(s) >= 12:
            return s[:180].strip()
    # Fallback to truncated text
    return cleaned.strip()[:180]


# ---------------------------------------------------------------------------
# SessionMiner Engine
# ---------------------------------------------------------------------------

class SessionMiner:
    """
    Deterministic streaming analyzer for Antigravity conversation transcripts.
    Identifies projects, tracks metrics, and clusters architectural directives.
    """

    def __init__(
        self,
        brain_roots: Optional[List[Union[str, Path]]] = None,
        repo_path: Optional[Union[str, Path]] = None,
    ):
        self.repo_path = Path(repo_path) if repo_path else Path.cwd()
        if brain_roots:
            self.brain_roots = [Path(r) for r in brain_roots]
        else:
            self.brain_roots = self._resolve_default_roots()

    @staticmethod
    def _resolve_default_roots() -> List[Path]:
        """Resolves existing default brain roots across Windows and WSL mounts."""
        valid_roots = []
        seen = set()
        for root in DEFAULT_BRAIN_ROOTS:
            try:
                if root.is_dir():
                    norm_str = str(root.resolve()).lower()
                    if norm_str not in seen:
                        seen.add(norm_str)
                        valid_roots.append(root)
            except Exception:
                pass
        return valid_roots

    def discover_transcript_files(self) -> List[Path]:
        """
        Discovers all transcript.jsonl files within configured brain roots.
        Looks under <session_dir>/.system_generated/logs/transcript.jsonl.
        """
        transcript_files = []
        for root in self.brain_roots:
            if not root.is_dir():
                continue
            try:
                for entry in root.iterdir():
                    if entry.is_dir():
                        transcript = entry / ".system_generated" / "logs" / "transcript.jsonl"
                        if transcript.is_file():
                            transcript_files.append(transcript)
                        else:
                            # Fallback check for direct transcript
                            alt_transcript = entry / "transcript.jsonl"
                            if alt_transcript.is_file():
                                transcript_files.append(alt_transcript)
            except Exception:
                continue

        # Sort for determinism
        return sorted(transcript_files, key=lambda p: str(p))

    def parse_transcript(self, transcript_path: Path) -> Optional[Dict[str, Any]]:
        """
        Streams a single transcript.jsonl line-by-line with zero-crash resilience.
        Computes timing, steps, human turns, project attribution, and architectural intents.
        """
        if not transcript_path.is_file():
            return None

        conv_id = extract_conversation_id(transcript_path)

        total_steps = 0
        human_turns = 0
        min_dt: Optional[datetime] = None
        max_dt: Optional[datetime] = None
        first_raw_timestamp: Optional[str] = None

        workspace_project: Optional[str] = None
        tool_project_candidates: List[str] = []

        session_intents: Set[str] = set()
        session_quotes: Dict[str, str] = {}

        try:
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        step_data = json.loads(line)
                    except Exception:
                        # Zero-Crash: Silently ignore broken/truncated JSON lines
                        continue

                    if not isinstance(step_data, dict):
                        continue

                    total_steps += 1

                    # 1. Timestamps
                    ts_str = step_data.get("created_at")
                    if ts_str and isinstance(ts_str, str):
                        if not first_raw_timestamp:
                            first_raw_timestamp = ts_str
                        dt = parse_timestamp(ts_str)
                        if dt:
                            if min_dt is None or dt < min_dt:
                                min_dt = dt
                            if max_dt is None or dt > max_dt:
                                max_dt = dt

                    # 2. Priority 1: workspaceUris
                    if not workspace_project:
                        ws_uris = step_data.get("workspaceUris")
                        if ws_uris:
                            if isinstance(ws_uris, list):
                                for u in ws_uris:
                                    proj = extract_project_from_path(str(u))
                                    if proj:
                                        workspace_project = proj
                                        break
                            elif isinstance(ws_uris, str):
                                proj = extract_project_from_path(ws_uris)
                                if proj:
                                    workspace_project = proj

                    # 3. Priority 2: Tool call arguments
                    tool_calls = step_data.get("tool_calls")
                    if tool_calls and isinstance(tool_calls, list):
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue
                            args = tc.get("args")
                            if isinstance(args, dict):
                                for arg_key in ("Cwd", "AbsolutePath", "TargetFile"):
                                    val = args.get(arg_key)
                                    if val and isinstance(val, str):
                                        proj = extract_project_from_path(val)
                                        if proj:
                                            tool_project_candidates.append(proj)

                                # Inspect command line tokens
                                cmd_val = args.get("CommandLine")
                                if cmd_val and isinstance(cmd_val, str):
                                    cmd_paths = extract_paths_from_command(cmd_val)
                                    for cp in cmd_paths:
                                        proj = extract_project_from_path(cp)
                                        if proj:
                                            tool_project_candidates.append(proj)

                    # 4. Human Turn & Intent Scanning
                    source = step_data.get("source")
                    step_type = step_data.get("type")
                    if source == "USER_EXPLICIT" or step_type == "USER_INPUT":
                        human_turns += 1
                        content = step_data.get("content")
                        if content and isinstance(content, str):
                            content_norm = content.lower().replace("İ", "i").replace("I", "ı")
                            for intent_name, defn in INTENT_DEFINITIONS.items():
                                for pat in defn["patterns"]:
                                    if pat in content_norm:
                                        session_intents.add(intent_name)
                                        if intent_name not in session_quotes:
                                            quote = extract_clean_quote(content, pat)
                                            if quote:
                                                session_quotes[intent_name] = quote
                                        break

        except Exception:
            return None

        if total_steps == 0:
            return None

        # Determine Final Project Attribution (Hierarchy)
        if workspace_project:
            final_project = workspace_project
        elif tool_project_candidates:
            # Pick most frequent candidate
            final_project = Counter(tool_project_candidates).most_common(1)[0][0]
        else:
            final_project = "UNASSIGNED / SCRATCH"

        # Format Start Time & Duration
        if min_dt:
            start_time = min_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        elif first_raw_timestamp:
            start_time = first_raw_timestamp
        else:
            start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if min_dt and max_dt:
            duration_minutes = max(0, int(round((max_dt - min_dt).total_seconds() / 60.0)))
        else:
            duration_minutes = 0

        return {
            "conversation_id": conv_id,
            "project": final_project,
            "start_time": start_time,
            "duration_minutes": duration_minutes,
            "total_steps": total_steps,
            "human_turns": human_turns,
            "detected_intents": sorted(list(session_intents)),
            "quotes_by_intent": session_quotes,
        }

    def mine_sessions(self) -> Dict[str, Any]:
        """
        Discovers and processes all transcripts, groups them chronologically by project,
        and aggregates architectural intent summaries.
        """
        transcript_files = self.discover_transcript_files()
        all_parsed: List[Dict[str, Any]] = []

        for tf in transcript_files:
            parsed = self.parse_transcript(tf)
            if parsed:
                all_parsed.append(parsed)

        # Group by project
        projects_dict: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "session_count": 0,
            "sessions": []
        })

        intent_counts: Counter = Counter()
        intent_sample_quotes: Dict[str, str] = {}
        intent_project_dist: Dict[str, Counter] = defaultdict(Counter)

        for session in all_parsed:
            proj = session["project"]
            session_entry = {
                "conversation_id": session["conversation_id"],
                "start_time": session["start_time"],
                "duration_minutes": session["duration_minutes"],
                "total_steps": session["total_steps"],
                "human_turns": session["human_turns"],
                "detected_intents": session["detected_intents"]
            }
            projects_dict[proj]["sessions"].append(session_entry)

            for intent in session["detected_intents"]:
                intent_counts[intent] += 1
                intent_project_dist[intent][proj] += 1
                if intent not in intent_sample_quotes and intent in session["quotes_by_intent"]:
                    intent_sample_quotes[intent] = session["quotes_by_intent"][intent]

        # Chronologically sort sessions under each project
        for proj, pdata in projects_dict.items():
            pdata["sessions"].sort(key=lambda s: s["start_time"])
            pdata["session_count"] = len(pdata["sessions"])

        # Construct intent summary adhering strictly to specification
        intent_summary: Dict[str, Dict[str, Any]] = {}
        for intent_name in INTENT_DEFINITIONS.keys():
            freq = intent_counts.get(intent_name, 0)
            quote = intent_sample_quotes.get(intent_name, "")
            intent_summary[intent_name] = {
                "session_frequency": freq,
                "sample_quote": quote
            }

        return {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_sessions": len(all_parsed),
            "projects": dict(projects_dict),
            "intent_summary": intent_summary
        }

    def save_sessions_json(
        self,
        data: Dict[str, Any],
        output_path: Optional[Union[str, Path]] = None
    ) -> Path:
        """Persists mined session data to .edge/distilled/sessions.json or custom path."""
        if output_path:
            out_file = Path(output_path)
        else:
            out_file = self.repo_path / ".edge" / "distilled" / "sessions.json"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        return out_file

    def format_sessions_report(self, data: Dict[str, Any], by_project: bool = False) -> str:
        """Formats a human-readable terminal report of sessions."""
        lines = []
        lines.append("=" * 75)
        lines.append("📊 ANTIGRAVITY TRANSCRIPT MINER — SESSION SUMMARY")
        lines.append("=" * 75)
        lines.append(f"Oluşturulma Zamanı: {data.get('generated_at')}")
        lines.append(f"Toplam Oturum:      {data.get('total_sessions', 0)}")
        projects = data.get("projects", {})
        lines.append(f"Toplam Proje Sayısı:{len(projects)}")
        lines.append("-" * 75)

        if by_project:
            for proj_name, pinfo in sorted(projects.items(), key=lambda kv: kv[1]["session_count"], reverse=True):
                sess_list = pinfo.get("sessions", [])
                total_duration = sum(s.get("duration_minutes", 0) for s in sess_list)
                lines.append(f"\n📁 PROJE: {proj_name} ({pinfo['session_count']} Oturum, Toplam: {total_duration} dk)")
                lines.append("-" * 75)
                lines.append(f"  {'#':<3} | {'Konuşma ID':<10} | {'Başlangıç Tarihi':<20} | {'Süre(dk)':<8} | {'Adım':<6} | {'İnsan':<5} | Niyetler")
                lines.append("  " + "-" * 73)
                for i, s in enumerate(sess_list, 1):
                    cid = s.get("conversation_id", "")[:8]
                    st = s.get("start_time", "")
                    dur = s.get("duration_minutes", 0)
                    steps = s.get("total_steps", 0)
                    turns = s.get("human_turns", 0)
                    intents = ", ".join(s.get("detected_intents", []))
                    if not intents:
                        intents = "—"
                    lines.append(f"  {i:<3} | {cid:<10} | {st:<20} | {dur:<8} | {steps:<6} | {turns:<5} | {intents}")
        else:
            lines.append(f"{'Proje Adı':<25} | {'Oturum':<8} | {'Toplam Süre(dk)':<15} | En Sık Niyetler")
            lines.append("-" * 75)
            for proj_name, pinfo in sorted(projects.items(), key=lambda kv: kv[1]["session_count"], reverse=True):
                sess_list = pinfo.get("sessions", [])
                total_duration = sum(s.get("duration_minutes", 0) for s in sess_list)
                # Count intents in this project
                p_intents = Counter()
                for s in sess_list:
                    for intent in s.get("detected_intents", []):
                        p_intents[intent] += 1
                top_intents = ", ".join(f"{k}({v})" for k, v in p_intents.most_common(2)) or "—"
                lines.append(f"{proj_name:<25} | {pinfo['session_count']:<8} | {total_duration:<15} | {top_intents}")

        lines.append("=" * 75)
        return "\n".join(lines)

    def format_intents_report(self, data: Dict[str, Any]) -> str:
        """Formats the Intent & Directive Mirror Report (Ayna Raporu)."""
        lines = []
        lines.append("=" * 75)
        lines.append("🧠 EDGE DISTILL — KULLANICI MİMARİ NİYET & SİTEM AYNASI (INTENT MIRROR)")
        lines.append("=" * 75)
        total_sessions = data.get("total_sessions", 0)
        lines.append(f"Toplam Taranan Oturum: {total_sessions}")
        lines.append("Kullanıcının En Çok Tembihlediği 5 Mimari Direktif Kümesi:")
        lines.append("-" * 75)

        summary = data.get("intent_summary", {})
        # Sort by frequency descending
        sorted_intents = sorted(summary.items(), key=lambda kv: kv[1].get("session_frequency", 0), reverse=True)

        for i, (intent_name, idata) in enumerate(sorted_intents, 1):
            freq = idata.get("session_frequency", 0)
            pct = (freq / total_sessions * 100) if total_sessions > 0 else 0.0
            defn = INTENT_DEFINITIONS.get(intent_name, {})
            title = defn.get("title", intent_name)
            rule_hint = defn.get("rule_hint", "rules/AGENTS.md")
            quote = idata.get("sample_quote", "")

            lines.append(f"\n{i}. 🎯 {title}")
            lines.append(f"   • Tekrarlanma Frekansı : {freq} oturumda (%{pct:.1f})")
            lines.append(f"   • Sisteme Kazınacak Kural : {rule_hint}")
            if quote:
                lines.append(f"   • Temsili Kullanıcı Alıntısı:")
                lines.append(f'     "{quote}"')
            else:
                lines.append("   • Temsili Kullanıcı Alıntısı: (Henüz bu kalıba rastlanmadı)")

        lines.append("\n" + "=" * 75)
        lines.append("💡 İPUCU: Sık tekrarlanan direktifleri 'coding_standards.md' ve ajan kurallarına")
        lines.append("   ekleyerek kullanıcının bilişsel tembih yükünü sıfırlayabilirsiniz.")
        lines.append("=" * 75)
        return "\n".join(lines)
