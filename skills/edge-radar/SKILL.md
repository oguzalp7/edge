---
name: edge-radar
description: Scoped code debt radar, churn-driven pattern observation, and idempotent technical debt ledger. Synthesizes findings across frontend (UI) and backend (Core) tracks without premature code mutation.
---

# 📡 /edge-radar — Scoped Pattern Observation & Idempotent Debt Ledger

> *"Turn the deterministic parts into code, and leave only the parts that actually require judgment to the agent. Don't fix issues immediately; append them to a buffer to recognize systemic macro patterns."* — **Poteto (Lauren Tan)**

`edge-radar` is an autonomous observation radar and technical debt ledger. It decouples **Debt Detection** from **Code Mutation**, maintaining an idempotent ledger under `.edge/ledger/`.

---

## 🧭 The 3 Operating Scopes (No Blind Full-Scans)

To avoid alert fatigue, false positives on WIP branches, and noise from untouched legacy code:

```
                  ┌───────────────────────────────┐
                  │      edge-radar scan          │
                  └───────────────┬───────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
         ▼                        ▼                        ▼
 1. Churn Mode (Default)   2. PR Mode               3. Full-Spectrum (Cron)
 `--mode churn`            `--mode pr`              `--mode all`
 Ranks top active files    Scans git diff           Runs on main/production
 from last 14 days.        against base ref.        at scheduled cron times.
```

1. **`--mode churn` (Default):** Targets the top 20–25 most frequently committed files in the last 14 days via `git log`. Fixes hotspots where bugs actually recur.
2. **`--mode pr`:** Scans files changed between `HEAD` and base branch (`git diff <base>...HEAD`).
3. **`--mode all`:** Full repository scan (reserved for weekly cron or intentional codebase health surveys).

---

## 🛣️ Dual-Channel Architecture

Findings are strictly partitioned to prevent cognitive context dilution:

```
.edge/ledger/
├── ui.json       <-- Frontend Track (JSX Tailwind clusters, orphan components, magic headers)
├── core.json     <-- Backend Track (Fat actions >80 LOC, SQL leaks, deep indent >3, missing tests)
└── meta.json     <-- Executive index & systemic macro pattern detector
```

---

## ⚡ CLI Reference & Usage

Run from repository root:

```bash
# 1. Scoped scan on active churn files (Hotspots)
python3 /path/to/plugins/edge/tools/radar/cli.py scan . --mode churn

# 2. PR scan before merging
python3 /path/to/plugins/edge/tools/radar/cli.py scan . --mode pr --base main

# 3. View executive health dashboard
python3 /path/to/plugins/edge/tools/radar/cli.py status .

# 4. Generate proposal report for user review
python3 /path/to/plugins/edge/tools/radar/cli.py report . --top 10 -o debt-proposals.md
```

---

## 🔁 The Meta-Loop: Observation to Gate Rule Promotion

```
[ Radar Scan ] ➔ [ Idempotent Ledger ] ➔ [ Macro Pattern Detection ] ➔ [ User Proposal ] ➔ [ tools/gate.py Promotion ]
```

When 3+ distinct files share the same violation (e.g. `RULE-MAGIC-TABLE-HEADER` or `RULE-DEEP-NESTING`), `edge-radar` flags it as a **Systemic Macro Pattern**. 

Instead of opening 10 separate PRs, the chief architect can:
1. Review the grouped proposal report.
2. Promote the check into a permanent blocking rule inside `tools/gate.py`.
3. Dispatch a single bounded subagent (`edge-ui-refactor` or `edge-core-refactor`) to eradicate the pattern in one clean PR.
