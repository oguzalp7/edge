---
name: edge-ultra
description: Switch Edge Brigade execution tier to Ultra mode (swarm collaborative multi-agent board, frontier models Gemini-4/Claude-Opus-5.5, ultra branch).
---

# 🚀 /edge-ultra — Activate Edge Brigade Ultra Execution Tier

Switches the active Edge Brigade execution environment to **Ultra Tier**:
- **Operating Branch:** `ultra`
- **Agent Transport:** `swarm` (Collaborative multi-agent message board)
- **Model Profile:** Frontier reasoning engines (`gemini-4-hydrogen-high`, `gemini-4-hydrogen-xhigh`, `claude-opus-5-5-high`, `gemini-4-hydrogen-medium`)

---

## 🛠️ Execution Protocol

When this skill is invoked, run the tier switcher CLI via WSL2:

```bash
wsl --cd /mnt/c/Users/oguz_/.gemini/config/plugins/edge python3 tools/brigade/tier.py switch ultra
```

Output the returned Markdown status card directly to the user.
