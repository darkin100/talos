## Summary

`POST /api/healthz` (and any non-GET method) now returns **405 Method Not Allowed** instead of 200, consistent with every other route.

## Changes

- Added a method guard to `handleHealthz` in `api/handler.js`.
- Documented the 405 response in `openapi.yaml`.
- Added handler-level tests for the guard.

## Notes for operators

Closes the contract-test violation in #38. Implemented by hand after the code agent stalled on this issue. All todo-api tests pass.
