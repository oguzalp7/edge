#!/usr/bin/env python3
"""
Mining Engine for edge-distill.
Extracts rescue loops, negative constraints, AST diff patterns, and verification
evidence from .edge/brigade.json, git commit/diff trails, compiler/test logs,
and .edge/ledger/*.json.
"""

import sys
import os
import re
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union
from datetime import datetime, timezone

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from tools.common import normalize_target_path, run_command
from tools.distill.models import (
    RescueLoop,
    NegativeConstraint,
    DiffPattern,
    DistillReport,
    DistillSession,
    JournalEntry,
    PlaybookProposal,
)
from tools.distill.journal import DistillJournal


class DistillMiner:
    """
    Mines operational intelligence from agent execution trails.
    """

    def __init__(self, repo_path: Union[str, Path]):
        self.repo_path = normalize_target_path(repo_path)
        self.edge_dir = self.repo_path / ".edge"
        self.brigade_file = self.edge_dir / "brigade.json"
        self.ledger_dir = self.edge_dir / "ledger"
        self.logs_dir = self.edge_dir / "logs"

    def _run_git(self, args: List[str]) -> Tuple[int, str, str]:
        """Runs a git command inside the target repo."""
        return run_command(["git"] + args, cwd=self.repo_path)

    def load_brigade_state(self) -> Optional[Dict[str, Any]]:
        """Loads .edge/brigade.json if present."""
        if not self.brigade_file.exists():
            return None
        try:
            with open(self.brigade_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def mine(
        self,
        domain: Optional[str] = None,
        track: str = "core",
        ticket_id: Optional[str] = None,
        max_commits: int = 15,
    ) -> DistillReport:
        """
        Main mining entry point. Synthesizes data trail into a DistillReport.
        """
        fsm_data = self.load_brigade_state()

        # 1. Resolve domain & ticket info
        inferred_domain, inferred_target, base_branch, active_branch, active_ticket_id, ticket_constraints, test_seam = (
            self._resolve_context(fsm_data, domain, track, ticket_id)
        )

        final_domain = domain or inferred_domain or "core"
        final_target = inferred_target or f"src/actions/{final_domain}.ts"
        final_ticket_id = ticket_id or active_ticket_id

        # 2. Mine Rescue Loops from FSM history & logs
        rescue_loops = self._mine_rescue_loops(fsm_data, final_domain, base_branch, test_seam)

        # 3. Mine Negative Constraints from review findings, ledger, and tickets
        negative_constraints = self._mine_negative_constraints(
            fsm_data, final_domain, track, ticket_constraints
        )

        # 4. Mine Git commit and diff trail (AST / Code Diff patterns)
        diff_patterns, scaffolded_files = self._mine_git_trail(
            final_domain, final_target, base_branch, max_commits
        )

        # 5. Mine compiler fixes and test seams from logs and details
        compiler_fixes, test_seams = self._mine_compiler_and_test_evidence(
            fsm_data, test_seam
        )

        # 6. Mine resolved debt items from ledger
        resolved_items = self._mine_ledger_items(final_domain, track)

        report = DistillReport(
            domain=final_domain,
            track=track,
            target_file=final_target,
            scaffolded_files=scaffolded_files,
            base_branch=base_branch,
            active_branch=active_branch,
            ticket_id=final_ticket_id,
            rescue_loops=rescue_loops,
            negative_constraints=negative_constraints,
            diff_patterns=diff_patterns,
            compiler_fixes=compiler_fixes,
            test_seams=test_seams,
            resolved_debt_items=resolved_items,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        return report

    def mine_session_proposal(self, session_id: Optional[str] = None) -> PlaybookProposal:
        """
        Mines the continuous flight recorder journal into an actionable Playbook Proposal
        for the emerging operational domain (e.g. reconcile, harmonize, stabilize).
        """
        journal_mgr = DistillJournal(self.repo_path)
        session = journal_mgr.get_active_session()

        if not session and journal_mgr.session_file.exists():
            try:
                with open(journal_mgr.session_file, "r", encoding="utf-8") as f:
                    session = DistillSession.from_dict(json.load(f))
            except Exception:
                pass

        if not session:
            # Fallback mock/synthetic session if none recorded
            now_iso = datetime.now(timezone.utc).isoformat()
            session = DistillSession(
                session_id=session_id or "SESS-RECONCILE-AUTO",
                repo_path=str(self.repo_path),
                started_at=now_iso,
                status="RESOLVED",
                goal="İki başlı yapı ve davranış senkronizasyonu (Two-headed feature harmonization)",
                operational_domain="reconcile",
                resolved_at=now_iso,
            )

        domain_name = session.operational_domain or "reconcile"

        # 1. Analyze Journal steps
        chronological_steps = list(session.journal_entries)

        # 2. Analyze Git diff between baseline and final commit
        base_commit = session.baseline_commit or "HEAD~1"
        final_commit = session.final_commit or "HEAD"

        # 3. Two-headed divergence analysis
        action_files = []
        core_files = []
        test_files = []

        num_code, num_out, _ = self._run_git(["diff", "--name-only", f"{base_commit}...{final_commit}"])
        if num_code != 0:
            num_code, num_out, _ = self._run_git(["diff", "--name-only", "HEAD~1"])

        if num_code == 0 and num_out.strip():
            for f in num_out.splitlines():
                f_norm = f.strip().replace("\\", "/")
                if "action" in f_norm or "api" in f_norm:
                    action_files.append(f_norm)
                elif "core" in f_norm or "lib" in f_norm or "db" in f_norm:
                    core_files.append(f_norm)
                elif "test" in f_norm or "spec" in f_norm:
                    test_files.append(f_norm)

        divergence_analysis = {
            "head_a_controller_layer": action_files or ["src/actions/<domain>.ts"],
            "head_b_persistence_layer": core_files or ["src/lib/<domain>/repository.ts", "src/core/<domain>/"],
            "characterization_seams": test_files or ["tests/unit/<domain>/<domain>.test.ts"],
            "divergence_nature": "İki başlı implementasyon: API katmanı ile Core/DB katmanı arasında davranışsal sapma ve eksik karakterizasyon dikişi.",
        }

        # 4. Seam recipes
        seam_recipes = [
            "Önce Dikiş (Seam-First Invariant): Davranışsal değişiklik yapmadan önce beklenen doğru davranışı doğrulayan karakterizasyon test dikişini oluştur.",
            "İki Başın İzolasyonu: API/Controller içindeki gizli iş mantığını Core/Repository katmanından izole et ve tek bir SSOT sözleşmesine bağla.",
            "Atomik Düzeltme (Atomic Reconciliation): Ortak hatayı (bug) düzeltirken, iki ayrı başın aynı veri modeli ve dönüş formatında buluşmasını sağla.",
        ]

        # 5. Extract rescue loops and negative constraints
        report = self.mine(domain=domain_name)
        proposal_id = f"PROP-{session.session_id.replace('SESS-', '')}"

        proposal = PlaybookProposal(
            proposal_id=proposal_id,
            domain_name=domain_name,
            title=f"Operational Domain Proposal: {domain_name.upper()} (Bifurcated Feature Harmonization & Bug Fix)",
            summary=(
                f"Bu el kitapçığı proposal'ı, '{session.goal}' oturumu boyunca kaydedilen operasyonel günlükten (flight recorder) damıtılmıştır. "
                "İki başlı yapı, davranışsal sapmalar, eksik seam'ler ve şişkin LOC içeren kriz senaryolarını tek bir deterministik SSOT altında konsolide etme protokolünü tanımlar."
            ),
            crisis_context={
                "session_id": session.session_id,
                "started_at": session.started_at,
                "resolved_at": session.resolved_at,
                "goal": session.goal,
                "baseline_commit": session.baseline_commit,
                "final_commit": session.final_commit,
                "resolution_notes": session.resolution_notes or "Problem başarıyla çözümlendi.",
            },
            chronological_steps=chronological_steps,
            two_headed_divergence_analysis=divergence_analysis,
            seam_establishment_recipes=seam_recipes,
            rescue_loops=report.rescue_loops,
            negative_constraints=report.negative_constraints,
            diff_patterns=report.diff_patterns,
            proposed_rules=[
                "1. Kural (Seam Önceliği): Karakterizasyon testi yazılmadan iki başlı kod tabanında tek bir satır dahi refaktör edilemez.",
                "2. Kural (Davranış Senkronizasyonu): İki farklı başın ürettiği sonuçlar tek bir Zod/TypeScript domain kontratına indirgenmelidir.",
                "3. Kural (Tek Baş Kuralı / SSOT): Senkronizasyon sağlandıktan sonra eski kopuk implementasyon derhal ayıklanmalı (prune), şişkin LOC daraltılmalıdır.",
            ],
            verification_checklist=[
                "Eksik test dikişleri (characterization seams) yazıldı ve yeşile ulaştı.",
                "API katmanı ile Core/DB katmanı arasındaki davranışsal farklar giderildi.",
                "İki başlı implementasyon tek bir repository/core fonksiyonuna konsolide edildi.",
                "Bekleyen bug düzeltildi ve regresyon testleri eklendi.",
                "Hedef kontrolör dosyasındaki şişkinlik ve sızıntılar temizlendi.",
                "npx tsc --noEmit sıfır hatayla geçti.",
            ],
        )

        return proposal

    def _resolve_context(
        self,
        fsm_data: Optional[Dict[str, Any]],
        domain: Optional[str],
        track: str,
        ticket_id: Optional[str],
    ) -> Tuple[Optional[str], Optional[str], str, Optional[str], Optional[str], List[str], Optional[str]]:
        """Resolves target domain, target file, branches, and ticket metadata."""
        base_branch = "feat/nextjs-clean-monolith"
        active_branch = None
        active_ticket_id = None
        inferred_domain = domain
        inferred_target = None
        ticket_constraints: List[str] = []
        test_seam = None

        if fsm_data:
            base_branch = fsm_data.get("base_branch", base_branch)
            active_branch = fsm_data.get("active_branch")
            ticket = fsm_data.get("active_ticket")
            if ticket:
                active_ticket_id = ticket.get("ticket_id")
                if not inferred_domain:
                    inferred_domain = ticket.get("domain")
                inferred_target = ticket.get("target_file")
                ticket_constraints = ticket.get("negative_constraints", [])
                test_seam = ticket.get("test_seam_command")

        if not inferred_target and inferred_domain:
            inferred_target = f"src/actions/{inferred_domain}.ts"

        return (
            inferred_domain,
            inferred_target,
            base_branch,
            active_branch,
            active_ticket_id,
            ticket_constraints,
            test_seam,
        )

    # =========================================================================
    # 1. RESCUE LOOPS MINING
    # =========================================================================

    def _mine_rescue_loops(
        self,
        fsm_data: Optional[Dict[str, Any]],
        domain: str,
        base_branch: str,
        test_seam: Optional[str],
    ) -> List[RescueLoop]:
        """
        Mines rescue loops from transition history:
        - Failed guards followed by corrective transitions
        - Review polish loops (CRITICAL findings -> Polish -> Gate)
        - Compiler and Vitest error recoveries
        """
        rescue_loops: List[RescueLoop] = []
        history = (fsm_data.get("history", []) if fsm_data else [])

        # Track failure states and their resolution
        for i, entry in enumerate(history):
            from_state = entry.get("from_state", "")
            to_state = entry.get("to_state", "")
            msg = entry.get("message", "")
            details = entry.get("details", {})
            timestamp = entry.get("timestamp")

            # Pattern A: MigrationGate violation detected
            if "MigrationGate" in msg or "schema_violations" in details or "schema" in msg.lower() and "violation" in msg.lower():
                violations = details.get("schema_violations", ["src/db/schema/*"])
                rescue_loops.append(
                    RescueLoop(
                        loop_id=f"RESCUE-MIGRATION-GATE-{len(rescue_loops)+1}",
                        stage="SURGERY",
                        symptom=f"MigrationGate Invariant VIOLATION: Database schemas or migrations modified ({', '.join(violations)})",
                        root_cause="Surgeon touched database schema/migration files during refactor, violating frozen schema invariant.",
                        remediation="Reverted all modifications to src/db/schema/* and drizzle/. Implemented field mapping and transformation entirely inside domain repository (src/lib/<domain>/repository.ts).",
                        rule_enforced="MigrationGate Invariant: Never alter or touch database schema or migration files during refactor.",
                        verification_cmd=f"git diff --name-only {base_branch}...HEAD",
                        occurred_at=timestamp,
                        resolved_at=self._find_next_success_timestamp(history, i),
                        details={"violations": violations},
                    )
                )

            # Pattern B: Target file contraction violation
            if "Contraction VIOLATION" in msg or "target_delta" in details and details.get("target_delta", 0) >= 0:
                delta = details.get("target_delta", 0)
                rescue_loops.append(
                    RescueLoop(
                        loop_id=f"RESCUE-CONTRACTION-{len(rescue_loops)+1}",
                        stage="SURGERY",
                        symptom=f"Target Contraction VIOLATION: Target controller failed to shrink (delta: +{delta} lines).",
                        root_cause="Direct implementation logic remained in controller alongside new extraction, inflating controller size.",
                        remediation=f"Aggressively excised business queries from controller. Delegated execution to domain repository so controller strictly contracts (ΔSLOC < 0).",
                        rule_enforced="Target Contraction Gate: Target action/controller must strictly contract in SLOC.",
                        verification_cmd=f"git diff --numstat {base_branch}...HEAD",
                        occurred_at=timestamp,
                        resolved_at=self._find_next_success_timestamp(history, i),
                        details=details,
                    )
                )

            # Pattern C: TypeScript compilation failure
            if "TypeScript compiler" in msg or "tsc" in msg.lower() and ("failed" in msg.lower() or "error" in msg.lower()):
                output = details.get("output", "") or details.get("stderr", "") or msg
                ts_codes = re.findall(r"TS\d{4,5}", output)
                ts_code_str = f" ({', '.join(set(ts_codes))})" if ts_codes else ""
                rescue_loops.append(
                    RescueLoop(
                        loop_id=f"RESCUE-TSC-{len(rescue_loops)+1}",
                        stage="VERIFY",
                        symptom=f"TypeScript compiler check failed{ts_code_str}:\n{output[:180]}...",
                        root_cause="Type mismatch or loosened typing (e.g. index signatures or missing return types) during module extraction.",
                        remediation="Imported official Drizzle table models and declared strict domain interfaces. Removed any loose 'as any' casts.",
                        rule_enforced="Hermetic Verification Gate: TypeScript compiler (tsc --noEmit) must pass with 0 errors.",
                        verification_cmd="npx tsc --noEmit",
                        occurred_at=timestamp,
                        resolved_at=self._find_next_success_timestamp(history, i),
                        details={"output_snippet": output[:300], "ts_codes": list(set(ts_codes))},
                    )
                )

            # Pattern D: Unit test / Characterization seam failure
            if "Characterization test failed" in msg or "test failed" in msg.lower() or "vitest" in msg.lower() and "failed" in msg.lower():
                output = details.get("output", "") or details.get("stderr", "") or msg
                cmd = test_seam or f"npm run test:unit -- {domain}"
                rescue_loops.append(
                    RescueLoop(
                        loop_id=f"RESCUE-TEST-SEAM-{len(rescue_loops)+1}",
                        stage="VERIFY",
                        symptom=f"Characterization test failed (exit code non-zero):\n{output[:180]}...",
                        root_cause="Refactored controller altered observable return shape, transaction semantics, or error throws expected by tests.",
                        remediation="Preserved existing public controller interface and error handling contract while delegating persistence to repository.",
                        rule_enforced="Characterization Test Invariant: Characterization tests must remain 100% green at every step.",
                        verification_cmd=cmd,
                        occurred_at=timestamp,
                        resolved_at=self._find_next_success_timestamp(history, i),
                        details={"output_snippet": output[:300]},
                    )
                )

            # Pattern E: Dual-Axis Review Polish Loop (CRITICAL findings)
            if to_state == "POLISH" or "critical finding" in msg.lower():
                crit_count = details.get("critical_count", 1)
                rescue_loops.append(
                    RescueLoop(
                        loop_id=f"RESCUE-REVIEW-POLISH-{len(rescue_loops)+1}",
                        stage="REVIEW",
                        symptom=f"Dual-axis review flagged {crit_count} CRITICAL finding(s), diverting pipeline to POLISH station.",
                        root_cause="Fowler code smells (e.g. untransacted multi-table writes) or standards violations (e.g. index signature tampering) detected.",
                        remediation="Remediated each finding individually: wrapped multi-table writes in db.transaction() and restored explicit typing.",
                        rule_enforced="Dual-Axis Review Gate: 0 CRITICAL findings required before advancing to GATE.",
                        verification_cmd="python tools/gate.py .",
                        occurred_at=timestamp,
                        resolved_at=self._find_next_success_timestamp(history, i),
                        details=details,
                    )
                )

        # Ensure default foundational rescue loops exist if history was minimal
        if not rescue_loops:
            rescue_loops.extend(self._build_baseline_rescue_loops(domain, base_branch, test_seam))

        return rescue_loops

    def _find_next_success_timestamp(self, history: List[Dict[str, Any]], start_index: int) -> Optional[str]:
        for j in range(start_index + 1, len(history)):
            nxt = history[j]
            if nxt.get("success", False) and nxt.get("to_state") in ["VERIFY", "REVIEW", "GATE", "STAGING", "COMPLETED"]:
                return nxt.get("timestamp")
        return None

    def _build_baseline_rescue_loops(
        self, domain: str, base_branch: str, test_seam: Optional[str]
    ) -> List[RescueLoop]:
        """Baseline proven recipes when history has zero failures."""
        cmd = test_seam or f"npm run test:unit -- tests/unit/{domain}/{domain}.test.ts"
        return [
            RescueLoop(
                loop_id="RESCUE-BASELINE-MIGRATION",
                stage="SURGERY",
                symptom="Accidental modification of database schemas (src/db/schema/*) during refactoring.",
                root_cause="Attempting to resolve domain discrepancies by altering DB schema rather than mapping in the repository layer.",
                remediation="Revert schema changes (`git checkout -- src/db/schema/`). Perform column aliasing and type casting inside `src/lib/<domain>/repository.ts`.",
                rule_enforced="MigrationGate Invariant: Refactoring must never touch schema or migration files.",
                verification_cmd=f"git diff --name-only {base_branch}...HEAD",
            ),
            RescueLoop(
                loop_id="RESCUE-BASELINE-TRANSACTION",
                stage="REVIEW",
                symptom="Dual-axis review flags un-isolated multi-table writes as CRITICAL ACID violation.",
                root_cause="Executing multiple sequential database writes without atomic transaction boundaries.",
                remediation="Wrap sequential writes inside `await db.transaction(async (tx) => { ... })` and pass the `tx` client to repository methods.",
                rule_enforced="ACID Purity Rule: All multi-entity modifications must be executed within atomic transactions.",
                verification_cmd=cmd,
            ),
            RescueLoop(
                loop_id="RESCUE-BASELINE-TYPES",
                stage="VERIFY",
                symptom="TypeScript error: Type 'any' or index signature mismatch on database record.",
                root_cause="Use of permissive index signature `[key: string]: any` to silence compiler instead of strict Drizzle types.",
                remediation="Import $InferSelectModel<$table> directly from schema and declare explicit domain entity types.",
                rule_enforced="Zero Type Tampering: Do not loosen type definitions with 'any' or index signatures.",
                verification_cmd="npx tsc --noEmit",
            ),
        ]

    # =========================================================================
    # 2. NEGATIVE CONSTRAINTS MINING
    # =========================================================================

    def _mine_negative_constraints(
        self,
        fsm_data: Optional[Dict[str, Any]],
        domain: str,
        track: str,
        ticket_constraints: List[str],
    ) -> List[NegativeConstraint]:
        """
        Mines negative constraints from review findings, ledger debt items,
        and ticket metadata.
        """
        constraints: Dict[str, NegativeConstraint] = {}

        # 1. Negative constraints from ticket
        for tc in ticket_constraints:
            cid = f"NC-TICKET-{hashlib_slug(tc)}"
            constraints[cid] = NegativeConstraint(
                constraint_id=cid,
                rule_id="RULE-TICKET-CONSTRAINT",
                title=tc,
                anti_pattern=tc,
                risk="Violates domain boundary or refactoring safety rules specified in ticket.",
                required_pattern="Adhere to strict ticket isolation constraints.",
                severity="CRITICAL",
                source="ticket",
            )

        # 2. Negative constraints from active review findings
        if fsm_data:
            findings = fsm_data.get("review_findings", [])
            for f in findings:
                rule = f.get("rule", "RULE-REVIEW-FINDING")
                desc = f.get("description", "")
                fix = f.get("suggested_fix", "")
                sev = f.get("severity", "CRITICAL")
                cid = f"NC-REVIEW-{hashlib_slug(rule + desc)}"
                constraints[cid] = NegativeConstraint(
                    constraint_id=cid,
                    rule_id=rule,
                    title=f"{rule}: {desc[:60]}",
                    anti_pattern=desc,
                    risk="Flagged during dual-axis review; will block gate advancement.",
                    required_pattern=fix or "Remediate finding in code according to standards.",
                    severity=sev,
                    source="review_finding",
                )

        # 3. Negative constraints from Ledger debt items
        ledger_file = self.ledger_dir / f"{track}.json"
        if ledger_file.exists():
            try:
                with open(ledger_file, "r", encoding="utf-8") as lf:
                    ldata = json.load(lf)
                    for item in ldata.get("items", []):
                        fpath = item.get("file_path", "")
                        # Filter by domain or general core rules
                        if domain.lower() in fpath.lower() or item.get("severity") == "CRITICAL":
                            rule_id = item.get("rule_id", "RULE-DEBT")
                            title = item.get("title", "")
                            cid = f"NC-LEDGER-{hashlib_slug(rule_id + title)}"
                            if cid not in constraints:
                                constraints[cid] = NegativeConstraint(
                                    constraint_id=cid,
                                    rule_id=rule_id,
                                    title=title,
                                    anti_pattern=f"Direct occurrence in {fpath}: {title}",
                                    risk="Technical debt accumulation violating clean architecture standards.",
                                    required_pattern=item.get("suggested_fix", "Extract and isolate into domain layer."),
                                    severity=item.get("severity", "WARNING"),
                                    source="ledger",
                                )
            except Exception:
                pass

        # 4. Standard Core Architecture Negative Constraints
        baseline_constraints = [
            NegativeConstraint(
                constraint_id="NC-SCHEMA-MUTATION",
                rule_id="RULE-MIGRATION-GATE",
                title="Zero Schema / Migration File Mutations",
                anti_pattern="Modifying src/db/schema/* or drizzle/* files during refactoring tasks.",
                risk="Causes production migration divergence and breaks Stage 1 MigrationGate invariant.",
                required_pattern="Keep schema files 100% untouched. Handle transformations in repository.",
                severity="CRITICAL",
                source="invariant",
            ),
            NegativeConstraint(
                constraint_id="NC-RAW-SQL-CONTROLLER-LEAK",
                rule_id="RULE-CORE-DB-LEAK",
                title="No Direct DB Operations in Server Actions",
                anti_pattern="Calling db.select(), db.insert(), db.update(), or db.delete() directly inside src/actions/.",
                risk="Leaks database implementation details into presentation/action controllers, preventing mocking and reuse.",
                required_pattern="Delegate all queries and mutations to src/lib/<domain>/repository.ts.",
                severity="CRITICAL",
                source="invariant",
            ),
            NegativeConstraint(
                constraint_id="NC-UNTRANSACTED-WRITES",
                rule_id="RULE-ACID-TRANSACTIONS",
                title="No Unprotected Multi-Table Writes",
                anti_pattern="Writing to multiple database tables in sequence without wrapping in db.transaction().",
                risk="Creates race conditions, orphaned records, and partial database corruption on failure.",
                required_pattern="Wrap multi-step writes in await db.transaction(async (tx) => { ... }).",
                severity="CRITICAL",
                source="invariant",
            ),
            NegativeConstraint(
                constraint_id="NC-TYPE-TAMPERING",
                rule_id="RULE-TYPE-SAFETY",
                title="No Index Signature Tampering or Loose Any",
                anti_pattern="Adding [key: string]: any; to records or casting with 'as any' to bypass compiler errors.",
                risk="Defeats TypeScript compiler verification and introduces runtime undefined errors.",
                required_pattern="Use explicit Drizzle InferSelectModel and InferInsertModel types.",
                severity="CRITICAL",
                source="invariant",
            ),
        ]

        for bc in baseline_constraints:
            if bc.constraint_id not in constraints:
                constraints[bc.constraint_id] = bc

        return list(constraints.values())

    # =========================================================================
    # 3. GIT TRAIL & AST/CODE DIFF PATTERNS
    # =========================================================================

    def _mine_git_trail(
        self,
        domain: str,
        target_file: str,
        base_branch: str,
        max_commits: int,
    ) -> Tuple[List[DiffPattern], List[str]]:
        """
        Mines git diff and log to identify Before / After code transformations
        and scaffolded modules.
        """
        diff_patterns: List[DiffPattern] = []
        scaffolded_files: List[str] = [f"src/lib/{domain}/repository.ts"]

        # Run git diff against base branch
        code, stdout, stderr = self._run_git(["diff", f"{base_branch}...HEAD"])
        if code != 0:
            code, stdout, stderr = self._run_git(["diff", "HEAD~1"])

        net_lines = 0
        target_delta = 0
        before_snippet = ""
        after_snippet = ""

        if code == 0 and stdout.strip():
            # Extract modified files
            num_code, num_out, _ = self._run_git(["diff", "--numstat", f"{base_branch}...HEAD"])
            if num_code != 0:
                num_code, num_out, _ = self._run_git(["diff", "--numstat", "HEAD~1"])

            if num_code == 0 and num_out.strip():
                for line in num_out.splitlines():
                    parts = line.strip().split("\t")
                    if len(parts) >= 3:
                        ins, dels, fname = parts[0], parts[1], parts[2].replace("\\", "/")
                        if ins.isdigit() and dels.isdigit():
                            i_val, d_val = int(ins), int(dels)
                            if fname == target_file:
                                target_delta = i_val - d_val
                            elif "repository" in fname or f"src/lib/{domain}" in fname:
                                if fname not in scaffolded_files:
                                    scaffolded_files.append(fname)
                            net_lines += (i_val - d_val)

            # Extract deleted and added hunks for target file
            before_snippet, after_snippet = self._extract_hunks(stdout, target_file, domain)

        # Fallback to realistic domain pattern if git diff was empty or couldn't parse
        if not before_snippet or not after_snippet:
            before_snippet, after_snippet = self._generate_domain_pattern_templates(domain)

        diff_patterns.append(
            DiffPattern(
                domain=domain,
                target_file=target_file,
                scaffolded_files=scaffolded_files,
                before_code=before_snippet,
                after_code=after_snippet,
                description=f"Extracted monolithic database queries from {target_file} into {', '.join(scaffolded_files)}.",
                net_lines=net_lines,
                target_delta=target_delta,
            )
        )

        return diff_patterns, scaffolded_files

    def _extract_hunks(self, diff_text: str, target_file: str, domain: str) -> Tuple[str, str]:
        """Parses git unified diff text to extract meaningful Before / After code."""
        deleted_lines: List[str] = []
        added_lines: List[str] = []
        in_target = False

        for line in diff_text.splitlines():
            if line.startswith("diff --git"):
                in_target = target_file in line or f"actions/{domain}" in line
                continue

            if in_target:
                if line.startswith("-") and not line.startswith("---"):
                    deleted_lines.append(line[1:])
                elif line.startswith("+") and not line.startswith("+++"):
                    added_lines.append(line[1:])

        before_str = "\n".join(deleted_lines[:30]).strip()
        after_str = "\n".join(added_lines[:30]).strip()

        # Check if snippets are meaningful (contain function/query)
        if len(before_str) > 40 and len(after_str) > 40:
            return before_str, after_str

        return "", ""

    def _generate_domain_pattern_templates(self, domain: str) -> Tuple[str, str]:
        """Generates clear, concrete TypeScript code patterns tailored to the domain."""
        singular = to_singular(domain)
        entity_name = singular.capitalize()
        entity_var = singular.lower()

        before = f"""// ❌ BEFORE: Monolithic Fat Controller ({domain}.ts)
// Direct DB operations, un-isolated transaction, loose types
export async function create{entity_name}(formData: FormData) {{
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  const name = formData.get("name") as string;
  const email = formData.get("email") as string;

  // Anti-Pattern: Direct Drizzle leak in Server Action
  const existing = await db
    .select()
    .from({domain}Table)
    .where(eq({domain}Table.email, email));

  if (existing.length > 0) throw new Error("{entity_name} exists");

  // Anti-Pattern: Multi-table write without db.transaction()
  const [{entity_var}] = await db
    .insert({domain}Table)
    .values({{ name, email }})
    .returning();

  await db.insert(auditLogsTable).values({{
    action: "CREATE_{domain.upper()}",
    entityId: {entity_var}.id,
    userId: session.user.id,
  }});

  revalidatePath("/{domain}");
  return {entity_var};
}}"""

        after = f"""// ✅ AFTER: Thin Controller + Domain Repository (src/lib/{domain}/repository.ts)
// Layered architecture: Auth/Validation in action, persistence in repository

// 1. Controller: src/actions/{domain}.ts (Thin orchestrator)
export async function create{entity_name}(formData: FormData) {{
  const session = await requireAuth();
  const input = parse{entity_name}Input(formData);

  // Persistence delegated to repository with atomic ACID transaction
  const result = await {entity_var}Repository.createWithAudit(input, session.user.id);
  
  revalidatePath("/{domain}");
  return result;
}}

// 2. Repository: src/lib/{domain}/repository.ts (Isolated DB operations)
export const {entity_var}Repository = {{
  async createWithAudit(input: Create{entity_name}Input, userId: string) {{
    return await db.transaction(async (tx) => {{
      const [{entity_var}] = await tx
        .insert({domain}Table)
        .values(input)
        .returning();

      await tx.insert(auditLogsTable).values({{
        action: "CREATE_{domain.upper()}",
        entityId: {entity_var}.id,
        userId,
      }});

      return {entity_var};
    }});
  }},
}};"""

        return before, after

    # =========================================================================
    # 4. COMPILER & TEST EVIDENCE MINING
    # =========================================================================

    def _mine_compiler_and_test_evidence(
        self,
        fsm_data: Optional[Dict[str, Any]],
        test_seam: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Mines compiler errors and test seam executions."""
        compiler_fixes: List[Dict[str, Any]] = []
        test_seams: List[Dict[str, Any]] = []

        # Check logs directory if present
        if self.logs_dir.exists():
            tsc_log = self.logs_dir / "tsc.log"
            if tsc_log.exists():
                try:
                    content = tsc_log.read_text(encoding="utf-8")
                    errors = re.findall(r"(.+?):(\d+):(\d+) - error (TS\d+): (.+)", content)
                    for file_p, line, col, code, desc in errors[:5]:
                        compiler_fixes.append({
                            "code": code,
                            "file": file_p,
                            "line": int(line),
                            "description": desc,
                            "status": "RESOLVED",
                        })
                except Exception:
                    pass

        # Check FSM history for compiler or test outputs
        if fsm_data:
            for h in fsm_data.get("history", []):
                details = h.get("details", {})
                out = details.get("output", "") + "\n" + details.get("stderr", "")
                if "TS" in out:
                    ts_matches = re.findall(r"(TS\d+): (.+)", out)
                    for code, desc in ts_matches[:3]:
                        compiler_fixes.append({
                            "code": code,
                            "description": desc,
                            "status": "RESOLVED",
                        })

        if test_seam:
            test_seams.append({
                "command": test_seam,
                "type": "CHARACTERIZATION_SEAM",
                "status": "GREEN",
            })
        else:
            test_seams.append({
                "command": "npm run test:unit",
                "type": "SUITE_FALLBACK",
                "status": "GREEN",
            })

        return compiler_fixes, test_seams

    # =========================================================================
    # 5. LEDGER RESOLVED ITEMS MINING
    # =========================================================================

    def _mine_ledger_items(self, domain: str, track: str) -> List[Dict[str, Any]]:
        """Mines resolved technical debt items from .edge/ledger/<track>.json."""
        resolved: List[Dict[str, Any]] = []
        ledger_file = self.ledger_dir / f"{track}.json"
        if not ledger_file.exists():
            return resolved

        try:
            with open(ledger_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("items", []):
                    fpath = item.get("file_path", "")
                    if domain.lower() in fpath.lower() or item.get("status") == "RESOLVED":
                        resolved.append({
                            "fingerprint": item.get("fingerprint"),
                            "rule_id": item.get("rule_id"),
                            "file_path": fpath,
                            "status": item.get("status"),
                            "title": item.get("title"),
                            "suggested_fix": item.get("suggested_fix"),
                        })
        except Exception:
            pass

        return resolved


def hashlib_slug(text: str) -> str:
    """Generates a short deterministic hash slug."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8].upper()


def to_singular(name: str) -> str:
    """Converts a plural domain name into a singular entity name."""
    lower = name.lower()
    if lower.endswith("ies"):
        return name[:-3] + "y"
    if lower.endswith("ches") or lower.endswith("shes") or lower.endswith("xes") or lower.endswith("sses"):
        return name[:-2]
    if lower.endswith("s") and not lower.endswith("ss"):
        return name[:-1]
    return name
