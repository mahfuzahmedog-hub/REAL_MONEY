# Domain Docs — Layout

This repo uses **single-context** layout.

## Structure

```
/
├── CONTEXT.md        ← domain glossary (create when first term is resolved)
└── docs/
    └── adr/         ← architectural decision records (create when first ADR is needed)
```

## Consumer rules

Skills that read domain docs (`improve-codebase-architecture`, `diagnose`, `tdd`) should:

1. Read `CONTEXT.md` at the repo root to learn domain language
2. Read `docs/adr/` for past architectural decisions
3. Use the glossary vocabulary when discussing the project

## Creating docs

- `CONTEXT.md`: create only when the first domain term is resolved. Contains **only** the glossary — no implementation details, no specs.
- `docs/adr/`: create only when the first ADR is needed. Use format in `skills/engineering/grill-with-docs/ADR-FORMAT.md`.
