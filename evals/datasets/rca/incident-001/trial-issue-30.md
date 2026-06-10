## Root Cause Analysis

The error `TypeError: q.toLowerCase is not a function` indicates that the variable `q` (search query) is not a string when the `.toLowerCase()` method is called on it at `lib/store.js:54:22`.

### Most Probable Root Cause

The search query parameter `q` is being passed as a non-string type (likely `undefined`, `null`, or an object) from the HTTP request handler to the `Store.search()` method. The code assumes `q` is always a string without validating or coercing the input type.

### Affected Files and Lines

1. **`lib/store.js:54`** - The `.toLowerCase()` call on an unvalidated `q` parameter
2. **`api/handler.js:46`** - The `handleSearch()` function that passes `q` to `Store.search()`
3. **`api/handler.js:122`** - The main handler that extracts the query parameter from the request

### Recommended Fix

**In `api/handler.js` (around line 46 in `handleSearch()`):**

```javascript
function handleSearch(req) {
  // Extract and validate the query parameter
  const q = req.query?.q || req.queryStringParameters?.q || '';
  
  // Ensure q is a string and trim whitespace
  const searchQuery = String(q).trim();
  
  // Validate that we have a non-empty search query
  if (!searchQuery) {
    return {
      statusCode: 400,
      body: JSON.stringify({ error: 'Search query parameter "q" is required' })
    };
  }
  
  return Store.search(searchQuery);
}
```

**Alternative: In `lib/store.js` (around line 54 in `Store.search()`):**

```javascript
search(q) {
  // Defensive programming: ensure q is a string
  if (typeof q !== 'string') {
    q = String(q || '');
  }
  
  const lowerQ = q.toLowerCase();
  // ... rest of search logic
}
```

### Why This Happens

When a query parameter is missing from the URL (e.g., `/api/todos/search` without `?q=something`), it may be `undefined` rather than an empty string. The handler is not validating this before passing it to the store's search method.

### Prevention

- Always validate and coerce input parameters from HTTP requests
- Use TypeScript or JSDoc type annotations to catch type mismatches during development
- Add unit tests for edge cases (missing parameters, null values, etc.)
- Implement middleware for request validation

---
Commit: `8bb498482bec189ce762bf5a68d7e09d0e9f8e6e`
Triggering PR: #29
