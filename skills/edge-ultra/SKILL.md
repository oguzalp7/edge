---
name: edge-ultra
description: Switch Edge Brigade execution tier to Ultra mode (branchless runtime switching by default, swarm collaborative multi-agent board, frontier models from station_models.json).
---

# 🚀 /edge-ultra — Activate Edge Brigade Ultra Execution Tier

Switches the active Edge Brigade execution environment to **Ultra Tier** (branchless runtime toggle on the unified `main` codebase by default):
- **Unified Codebase / Branch Behavior:** Preserves your active Git branch (`checkout=False`) without switching to a separate `ultra` branch; pass `--checkout` only for opt-in legacy branch switching.
- **Agent Transport:** `swarm` (Collaborative multi-agent message board with `post_message` / `read_board`)
- **Model Matrix SSOT (`tools/brigade/station_models.json`):** Frontier reasoning engines (`gemini-4-hydrogen-high`, `gemini-4-hydrogen-xhigh` for `seam_architect`, `claude-opus-5-5-high` for `spec_critic`, `gemini-4-hydrogen-medium` for `qa_engineer`, and `fork="spec_writer"` for `examiner`)
- **Runtime Guardrails:** PreTool hooks automatically preload SSOT `model`/`effort`/`fork` into `swarm(action="add")` calls and enforce the **Swarm Daemon Ban** (blocking `narrator` and `monitor` workers).

---

## 🛠️ Execution Protocol

When this skill is invoked, run the tier switcher CLI in the active environment (Windows, WSL2, macOS, or Linux):

```bash
brigade tier switch ultra
# or directly from the plugin root:
python3 tools/brigade/tier.py switch ultra
```

Optional commands:
- **Legacy branch checkout (opt-in):** `python3 tools/brigade/tier.py switch ultra . --checkout`
- **Customize a station model in `station_models.json`:** `python3 tools/brigade/tier.py set-model <role> <model> [--effort <low|medium|high|xhigh>] --tier ultra`

Output the returned Markdown status card directly to the user.
