# Edge Plugin

Cross-OS multi-station engineering orchestrator and lifecycle guardrails for Antigravity (`windows`, `wsl`, `macos`, `linux`).

---

## Quick Start & Installation

### Windows (Native, via `winget`)

```powershell
winget install Python.Python.3.12 Git.Git Astral-sh.uv GitHub.cli OpenJS.NodeJS
python -m tools.doctor --init
```

*(Optional WSL2 bridge: `wsl --install` if your target repositories live inside WSL2; Edge auto-detects WSL2 without requiring a hardcoded distro.)*

### macOS (via `brew`)

```bash
brew install python git uv gh node
python3 -m tools.doctor --init
```

### Ubuntu / Debian Linux (via `apt`)

```bash
sudo apt-get update && sudo apt-get install -y python3 git gh nodejs npm
curl -LsSf https://astral.sh/uv/install.sh | sh
python3 -m tools.doctor --init
```

---

## Verify & Initialize (`edge doctor`)

Run the read-only preflight check or initialize `~/.edge/machine.json` and cache the resolved Python executable for fast hook startup:

```bash
python3 -m tools.doctor --json
python3 tools/doctor/cli.py --init --hooks-mode session --profile core
```

Available flags:
- `--json`: Emit machine-readable diagnostic report (`os_mode`, `hooks_health`, `tools`, `capabilities`, `recommended_profile`).
- `--init`: Atomically write `~/.edge/machine.json` and cache `sys.executable` into `python_exe.txt`.
- `--hooks-mode session|off|strict`: Set lifecycle guard enforcement mode.
- `--profile lite|core|full`: Override the recommended capability tier.
- `--wsl-distro <name>`: Optional WSL2 distro override (omit when using default distro).

---

## Session-Gated Lifecycle Hooks

Edge hooks (`hooks.json` -> `"hooks/dispatch.cmd"`) run cross-OS via `cmd /c` on Windows and `sh -c` on Unix, with fail-open behavior if Python is unavailable:

- **Vanilla Antigravity by default (`session` mode):** Conversations where `/edge-orchestrator` was never invoked pass through immediately (`{"decision": "allow"}` / `{}` / `{"injectSteps": []}`) with zero side-effects.
- **Activated sessions:** Invoking `/edge-orchestrator` (on turn 1 or any later turn) activates orchestrator and Brigade station guards for that conversation and its spawned `[edge-station:<role>]` workers.
- **Emergency Kill Switch:** Set `EDGE_HOOKS=off` in your environment or `"hooks_mode": "off"` in `~/.edge/machine.json` to bypass all hooks immediately.

---

## Capability Tiers (`Lite` / `Core` / `Full`)

| Tier | Requirements | Included Capabilities |
| :--- | :--- | :--- |
| **Lite** | `python`, `git` | Session-gated hooks, local `.edge/issues/` backlog, standard git worktrees |
| **Core** | `python`, `git`, `uv`, `node`, `gh` / `gh-axi` | Everything in Lite + ephemeral `uv` gates & GitHub Issues SSOT sync |
| **Full** | Core + `treehouse`, `lavish-axi`, `chrome-devtools-axi` | Everything in Core + pooled Treehouse worktrees, UI mockup visual gate, and headless Chrome E2E verification |
