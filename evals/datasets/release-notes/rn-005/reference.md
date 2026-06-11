## Summary

The search handler no longer 500s when `q` arrives as a repeated query parameter (an array). The value is coerced to a string before searching.

## Changes

- `handleSearch` in `api/handler.js` coerces `q` to a string, so `?q=a&q=b` returns 200 instead of throwing.

## Notes for operators

Closes #30 — the incident behind RCA issue #30 / replay task incident-001. No regression test was added in this PR (tracked separately).
