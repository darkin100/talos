# Reference release note (hand-edited ideal)

<!-- Edited from generated-v48.md: tightened the Changes wording; content was
     fully grounded so edits are stylistic only. SME may refine further. -->

## Summary

Fixed a bug where `PUT /api/todos/:id` silently reset the `completed` field
to `false` when the request body omitted it.

## Changes

- **store.js**: `update()` now leaves `completed` untouched unless the field
  is explicitly provided in the request.
- **store.test.js**: Added a regression test covering title-only updates
  preserving completion state.

## Notes for operators

The OpenAPI specification already defines `completed` as optional on PUT;
this fix aligns the implementation with the spec. Clients can now safely
perform title-only updates without losing a todo's completion state.
