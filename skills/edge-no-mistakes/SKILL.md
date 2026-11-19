---
name: edge-no-mistakes
description: Independent External Auditor & GitHub Issue Hunter via no-mistakes. Runs fast docs/CI sync (--skip review,test) or non-blocking external multi-agent audits that route findings to GitHub Issues (gh issue create) and frontier-axi without blocking Brigade-verified delivery.
user-invocable: true
---

# 🔍 /edge-no-mistakes — Independent External Auditor & GitHub Issue Hunter

> *"Brigade ships verified vertical slices via `/edge-ship`. `/edge-no-mistakes` operates independently as an external second-opinion auditor, fast documentation/CI sync runner, and non-blocking GitHub issue hunter."*

---

## 🎯 Purpose & Decoupled Modes

Unlike `/edge-ship` (the Brigade-native `1 Spec = 1 PR` delivery engine), `/edge-no-mistakes` is **optional and non-blocking**. Headless `no-mistakes` subagent invocations are automatically exempted from `orchestrator_guard.py` Orchestrator directives via `is_no_mistakes_invocation()`.

### Mode 1: Fast Docs + CI Sync (`--skip review,test`)
When Brigade (`GATE`, `QA_ENGINEER`, `EXAMINER`) has already verified code and tests, skip redundant review/test steps and sync docs + CI quickly:
```bash
wsl -e /bin/bash -lc "cd /home/oguz/<project> && no-mistakes axi run --base-branch staging --skip review,test --intent '<intent>' -y"
```

### Mode 2: Full External Audit (Non-Blocking Issue Hunter)
Run `no-mistakes` as an external read-only second-opinion auditor. Do **not** let it mutate Brigade-verified code or block local delivery; convert actionable findings into tracked backlog items:

1. **GitHub Issues (Out-of-band Debt / Risks):**
   ```bash
   gh issue create --title "[Audit] <concise finding>" --body "<file, impact, reproduction>"
   ```
2. **Local Backlog Staging (`frontier-axi`):**
   ```bash
   frontier-axi add "<finding title>" --body "<evidence & context>"
   ```

---

## ⚙️ Monitoring & Operator Controls
```bash
no-mistakes axi status
no-mistakes axi logs --step <step_name>
no-mistakes axi respond --answer "<decision>"
no-mistakes axi abort
```
