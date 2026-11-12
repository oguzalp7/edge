---
name: edge-pro
description: Switch Edge Brigade execution tier to Pro mode (single-worker invoke_subagent, cost-effective flash models, main branch).
---

# ⚡ /edge-pro — Activate Edge Brigade Pro Execution Tier

Switches the active Edge Brigade execution environment to **Pro Tier**:
- **Operating Branch:** `main`
- **Agent Transport:** `invoke_subagent` (Isolated single-worker execution)
- **Model Profile:** Cost-efficient `flash` models (with `gemini-3.8-flash-high` for `spec_critic`)

---

## 🛠️ Execution Protocol

When this skill is invoked, run the tier switcher CLI via WSL2:

```bash
wsl --cd /mnt/c/Users/oguz_/.gemini/config/plugins/edge python3 tools/brigade/tier.py switch pro
```

Output the returned Markdown status card directly to the user.
