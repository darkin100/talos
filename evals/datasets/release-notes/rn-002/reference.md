## Summary

`GET /api/todos/` with an empty id now returns **400 Bad Request** instead of 404, matching the OpenAPI contract for an invalid id.

## Changes

- Empty path id is validated and rejected with 400 in `api/handler.js`.
- `dev-server.js` routing updated so the empty-id case reaches the handler.
- Handler-level test added for the empty-id 400 response.

## Notes for operators

Closes the contract-test violation raised in #46. No API surface added; clients relying on the old 404 for `/api/todos/` will now see 400.
