---
name: edge-mutator
description: Alias-aware differential core mutation testing gate with Statement Deletion (SDL), zero-dependency TS/JS regex fallback, --diff-only line scoping, --recursive scanning, TOON reporting, and tools/gate.py integration.
---

# 🧬 /edge-mutator — SDL Deletion & Differential Core Mutation Gate

`edge-mutator` executes deterministic mutation testing against core business logic (`src/core/`, `core/`, `tools/`). It pairs AST/regex operator flips with **Statement Deletion (`SDL`)** (`/* [SDL-DELETED] */` in TS/JS, `pass  # [SDL-DELETED]` in Python) to mathematically catch dead assertions, useless guards, and unasserted side effects.

---

## ⚡ Usage & CLI Reference

### 1. Statement Deletion (`--mode sdl`), Operators, or Combined (`--mode all`)
```bash
# Run both Statement Deletion and operator mutations (default TOON output)
python3 tools/mutator/cli.py --target src/core/pricing.ts --mode all --test-cmd "npm run test:unit -- src/core/pricing.test.ts"

# Statement Deletion only
python3 tools/mutator/cli.py --target src/core/pricing.ts --mode sdl --test-cmd "npm run test:unit -- src/core/pricing.test.ts"
```

### 2. Differential Line Scoping (`--diff-only`)
Restrict mutations strictly to lines modified or added against `--base`:
```bash
python3 tools/mutator/cli.py --target src/core/pricing.ts --mode sdl --diff-only --base HEAD~1 --test-cmd "npm run test:unit"
```

### 3. Recursive Repo-Wide Core Scan (`--recursive`)
Walk `src/core/` (or an explicit `--target <dir>`) recursively, optionally combined with `--diff-only` and `--scan-only`:
```bash
python3 tools/mutator/cli.py --recursive --mode sdl --format toon --test-cmd "npm run test:unit"
python3 tools/mutator/cli.py --recursive --scan-only --mode sdl --format toon
```

### 4. Output Formats (`--format toon|json|human`)
- `--format toon` (default): Token-frugal AXI header + pipe-delimited table (`mutator[N]{...}:`).
- `--format json`: Machine-readable JSON (`MutationSummary` / `RecursiveMutationSummary`).
- `--format human`: Verbose human-readable ASCII summary banner.

---

## 🏛️ Architecture & Gate Integration

1. **Zero-Dependency TS/JS Fallback:** When `tree_sitter` is unavailable, `_discover_with_regex_fallback` scans `.ts/.tsx/.js/.jsx` files safely (ignoring comments, imports, and type declarations) for both operators and `SDL` deletion sites.
2. **Cached Worker Overlays (`_IMPORTER_CACHE`):** `tools/mutator/overlay.py` caches repo source/test candidate paths per repository root to eliminate repeated `rglob` traversals across mutants.
3. **Automatic `tools/gate.py` Integration (`check_differential_mutation_gate`):** When changed files touch `src/core/**/*.{ts,tsx,js,py}`, `tools/gate.py` automatically executes static SDL discovery (`--skip-verify`) or differential SDL mutation verification (`threshold >= 80%`).
