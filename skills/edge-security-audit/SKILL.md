---
name: edge-security-audit
description: Incremental 4-class security audit with shared SHA-256 coverage ledger, automated refutation, Cloudflare 3-verdict schema, TOON reporting, and automatic TICK-SEC triage.
user-invocable: true
---

# 🔐 /edge-security-audit — Incremental Security Audit & Shared Coverage Ledger

`brigade security-audit` performs deterministic entrypoint-to-sink security auditing across four attack classes while tracking cumulative repository audit coverage inside `.edge/security/coverage-ledger.json`.

---

## ⚡ CLI Usage

```bash
# Scoped audit (repeatable --scope or comma-separated)
python3 tools/brigade/cli.py security-audit . --scope src/actions --scope src/core/modules/portal --format toon

# Differential audit against base ref (also runs automatically in Tier 2 prepare-ship)
python3 tools/brigade/cli.py security-audit . --diff-only --base origin/staging

# Full recursive codebase audit
python3 tools/brigade/cli.py security-audit . --recursive --profile deep --format toon
```

---

## 🏛️ Shared Incremental Coverage Ledger & Automated Refutation

1. **Shared Ledger (`.edge/security/coverage-ledger.json`):**
   - Keyed by `file_sha256`. Unchanged `"covered"` files preserve their audited status across separate `--scope` and `--diff-only` runs; modified covered files are automatically re-audited; unscanned files stay `"out_of_scope"`.
2. **4 Attack Classes:**
   - `ACCESS_CONTROL_ABAC`: Unauthenticated Server Action / API Route mutations (`db.insert`, `db.update`, `db.delete`, `Repository.*`, `.upsert`) and privilege bypasses (`system-caller`, `bypassAuth`, `skipAuth`).
   - `DATA_ISOLATION`: Unscoped `db.update` / `db.delete` mutations missing `.where(...)`.
   - `INJECTION_AND_SINKS`: `sql.raw(${...})`, `dangerouslySetInnerHTML`, shell exec, and `eval` sinks.
   - `CRYPTO_AND_SECRETS`: `Math.random()` in auth/token contexts and hardcoded secret literals.
3. **Cloudflare 3-Verdict Discipline & Automated Refutation:**
   - Every finding carries `verdict` in `{"confirmed", "needs_validation", "rejected"}`.
   - Upstream auth guards (`requireAuth`, `assert*Access`, `evaluate*Access`, `getSession`, `checkPermission`) or HTML sanitizers (`DOMPurify`, `sanitize`) automatically downgrade candidates to `rejected` with `severity=None` (`validate_security_artifacts` strictly enforces `severity is None` on any non-confirmed finding).
4. **Automatic Core Triage (`TICK-SEC-*`):**
   - Confirmed vulnerabilities upsert `CRITICAL` `TICK-SEC-<SLUG>` tickets into `.edge/ledger/core.json` and transition an `IDLE` Brigade into `CycleState.TRIAGE`.
