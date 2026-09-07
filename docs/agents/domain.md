# Domain Documentation

This is a single-context repository.

## Layout

- `CONTEXT.md` at the repository root is the domain glossary and source of truth for domain terminology.
- `docs/adr/` contains architecture decision records.

These files are created lazily when domain terms or architectural decisions are resolved. If a relevant file does not exist, proceed without creating placeholder documentation.

## Agent guidance

Before exploring a domain area, read the relevant sections of `CONTEXT.md` and applicable records in `docs/adr/`. Use the glossary's vocabulary in issue titles, plans, tests, and implementation discussions. If a proposed change conflicts with an ADR, call out the conflict explicitly rather than silently overriding the decision.
