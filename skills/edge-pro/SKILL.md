---
name: edge-pro
description: Switch Edge Brigade execution tier to Pro mode (branchless runtime switching by default, single-worker invoke_subagent, cost-effective flash models).
---

# ⚡ /edge-pro — Activate Edge Brigade Pro Execution Tier

Switches the active Edge Brigade execution environment to **Pro Tier** (branchless runtime toggle by default):
- **Unified Codebase / Branch Behavior:** Preserves your active Git branch by default (`checkout=False`); pass `--checkout` only if you explicitly want to check out `main`.
- **Agent Transport:** `invoke_subagent` (Isolated single-worker execution)
- **Model Matrix SSOT (`tools/brigade/station_models.json`):** Cost-efficient `flash` models (with `gemini-3.8-flash-high` for `spec_critic` and `fork="spec_writer"` for `examiner`)

---

## 🛠️ Execution Protocol

When this skill is invoked, run the tier switcher CLI via WSL2:

```bash
wsl --cd /mnt/c/Users/oguz_/.gemini/config/plugins/edge python3 tools/brigade/tier.py switch pro
```

Optional commands:
- **Legacy branch checkout (opt-in):** `python3 tools/brigade/tier.py switch pro . --checkout`
- **Customize a station model in `station_models.json`:** `python3 tools/brigade/tier.py set-model <role> <model> [--effort <low|medium|high|xhigh>] --tier pro`

Output the returned Markdown status card directly to the user.
