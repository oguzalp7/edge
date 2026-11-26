# Stack Overlay: TypeScript Surgeon (`typescript`)

1. **TypeScript Baseline & Verification:**
   - Run `npx tsc --noEmit` and `npm run test:unit` (Vitest) BEFORE touching code and after every extraction step; both must exit `0`.
2. **Type-Safety & Dead-Code Cleanup:**
   - Eliminate `any`, `as unknown as`, `@ts-*` suppressions, postfix `!`, and production `console.log(...)` in touched files.
   - Delete shallow 1-line pass-through wrappers (`Zero-Wrapper`) and unreferenced exports; consolidate behind deep TypeScript interfaces.
   - Preserve exported public signatures unless breaking them is explicitly authorized by the refactor ticket.
