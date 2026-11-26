# Edge Plugin

Cross-OS multi-station engineering orchestrator and deterministic Brigade FSM for Antigravity (`windows`, `wsl`, `macos`, `linux`).

---

## Quick Start & Installation

### Windows (Native, via `winget`)

**Lite (zero extra package install beyond Python & Git):**
```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.12
python tools/doctor/cli.py --init
.\bin\brigade.cmd --help
```

**Core / Full (`winget` + optional `uv` & `lavish-axi`):**
```powershell
winget install -e --id Git.Git
winget install -e --id Python.Python.3.12
winget install -e --id GitHub.cli
winget install -e --id OpenJS.NodeJS.LTS
winget install -e --id Astral-sh.uv
npm i -g lavish-axi

git clone https://github.com/<org>/edge.git
cd edge
python tools/doctor/cli.py --init --hooks-mode session --profile core
.\bin\brigade.cmd --help
```

Or install globally as editable console scripts (`brigade`, `edge-doctor`, `edge-drift`, `edge-audit`, `edge-tracker`, `edge-radar`):
```powershell
uv tool install -e .
# or inside an active virtual environment:
pip install -e .
```

*(Optional WSL2 bridge: `wsl --install` if your target repositories live inside WSL2; Edge auto-detects WSL2 without requiring a hardcoded distro.)*

### macOS (via `brew`)

```bash
brew install python git uv gh node
python3 tools/doctor/cli.py --init
./bin/brigade --help
# or editable global install:
uv tool install -e .
```

### Ubuntu / Debian Linux (via `apt`)

```bash
sudo apt-get update && sudo apt-get install -y python3 git gh nodejs npm
curl -LsSf https://astral.sh/uv/install.sh | sh
python3 tools/doctor/cli.py --init
./bin/brigade --help
# or editable global install:
uv tool install -e .
```

> **Note for `uv` Users:** Use `uv run --no-project ...` for standalone script or test invocations; `pyproject.toml` also sets `[tool.uv] managed = false` so `uv run --with pytest pytest -q` creates zero `.venv/` or `uv.lock` artifacts in the repository.

---

## Verify & Initialize (`edge-doctor`)

Run the read-only preflight check or initialize `~/.edge/machine.json` and cache the resolved Python executable for fast hook startup:

```bash
./bin/edge-doctor --json
python3 tools/doctor/cli.py --init --hooks-mode session --profile core
```

On Windows without editable install:
```powershell
.\bin\edge-doctor.cmd --json
python tools/doctor/cli.py --init --hooks-mode session --profile core
```

Available flags:
- `--json`: Emit machine-readable diagnostic report (`os_mode`, `hooks_health`, `tools`, `capabilities`, `recommended_profile`).
- `--init`: Atomically write `~/.edge/machine.json` and cache `sys.executable` into `python_exe.txt`.
- `--hooks-mode session|off|strict`: Set lifecycle guard enforcement mode.
- `--profile lite|core|full`: Override the recommended capability tier.
- `--wsl-distro <name>`: Optional WSL2 distro override (omit when using default distro).

---

## Cross-OS Fallback Matrix

| Capability | Primary | Automatic Fallback Chain |
| :--- | :--- | :--- |
| **Isolated Worktrees** | `treehouse` pool (or Swarm `workspace="share"`/`"branch"`) | Native `git worktree` under `~/.edge/worktrees/<repo>-<hash6>/<branch>` with zero-data-loss `edge/aborted/...` preservation and `brigade worktree --action prune` |
| **`SPEC_CRITIC` Station** | `agy` CLI (`brigade critique-spec`) | Native Swarm Board (`claude-opus-5-5-high` in Ultra) or `invoke_subagent` (`Model: "pro"` in Pro) via `--native` or missing-`agy` fallback |
| **Interactive UI Mockups (`lavish-axi`)** | `lavish-axi` CLI (Windows `.cmd` unwrapped directly to `node.exe`) | `npx --yes lavish-axi` $\rightarrow$ HTML `file://` artifact preview + `ask_question` approval |
| **Browser QA & Visual Parity** | Built-in `browser` subagent (E2E) + `chrome-devtools-axi` (visual parity / Fiber) | `chrome-devtools-mcp` (`evaluate_script`, `take_screenshot`) $\rightarrow$ built-in `browser` subagent |
| **Brigade & Doctor CLIs** | Editable console scripts (`uv tool install -e .` / `pip install -e .`) | Zero-install wrappers: `bin/brigade` & `bin/edge-doctor` (macOS/Linux/WSL), `bin\brigade.cmd` & `bin\edge-doctor.cmd` (Windows) |

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
| **Lite** | `python`, `git` | Session-gated hooks, local `.edge/issues/` backlog, native `git worktree` isolation, HTML artifact preview, built-in `browser` QA |
| **Core** | `python`, `git`, `uv`, `node`, `gh` / `gh-axi` | Everything in Lite + ephemeral `uv` gates, `npx` fallback, & GitHub Issues SSOT sync |
| **Full** | Core + `treehouse`, `lavish-axi`, `chrome-devtools-axi` | Everything in Core + pooled Treehouse worktrees, `lavish-axi` visual gate, and headless Chrome E2E verification |
