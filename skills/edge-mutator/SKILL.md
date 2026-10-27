---
name: edge-mutator
description: Alias-aware differential core mutation testing gate. Validates unit test assertions by injecting AST operator mutations into isolated worker overlays with Next.js @/ alias materialization and differential caching.
---

# 🧬 /edge-mutator — Alias-Aware Differential Core Mutation Gate

`edge-mutator` executes deterministic mutation testing against core business logic (`src/core/`, `core/`, `tools/`). By applying AST operator mutations and checking whether tests fail (mutants killed) or pass (mutants survived), it mathematically measures assertion quality.

---

## ⚡ Usage & CLI Reference

### 1. Run Mutation Suite on Core File
```bash
uv run python tools/mutator/cli.py --target src/core/pricing.ts --test-cmd "npm run test:unit -- src/core/pricing.test.ts"
```

### 2. Custom Mutation Score Threshold
Exit with code 1 if mutation score is below 85%:
```bash
uv run python tools/mutator/cli.py --target src/core/pricing.ts --test-cmd "npm test" --threshold 85.0
```

### 3. Scan Mutation Sites Only (Dry Run)
Inspect all mutation sites discovered by Tree-Sitter without executing tests:
```bash
uv run python tools/mutator/cli.py --target src/core/pricing.ts --scan-only
```

---

## 🏛️ Architecture & Invariants

1. **Core Scope Guard:** Mutation testing is restricted to core logic (`src/core/`, `core/`, `tools/`). UI components or actions produce false timeouts and are rejected unless `--allow-non-core` is passed.
2. **Materialized Overlays:** Isolated worker environments under `.edge/mutation-workers/` physically copy build/test configs (`vitest.config.ts`, `tsconfig.json`, `package.json`), write mutated bytes, and materialize all dependent test files importing Next.js `@/` path aliases.
3. **Differential Result Cache:** Previously killed mutants are cached in `.edge/metrics/mutator.json`. Unchanged functions bypass re-execution on subsequent runs.
