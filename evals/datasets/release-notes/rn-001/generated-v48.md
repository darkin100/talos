## Summary

Fixed a bug where `PUT /api/todos/:id` was silently resetting the `completed` field to `false` when the request body omitted it.

## Changes

- **store.js**: Modified the `update()` method to only update the `completed` field when explicitly provided in the request, rather than converting `undefined` to `false`
- **store.test.js**: Added test case to verify that title-only updates preserve the existing completion state

## Notes for operators

The OpenAPI specification already correctly defines `completed` as optional (not required). This fix aligns the implementation with the spec. Clients can now safely perform title-only updates without losing the todo's completion state.
