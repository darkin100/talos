## Issue
The `/api/healthz` endpoint is accepting POST requests when it should only allow GET requests.

## Details
- **Endpoint**: `POST /api/healthz`
- **Expected status**: 405 Method Not Allowed
- **Actual status**: 200 OK
- **Actual response**: `{"status": "ok"}`

## Root Cause
The healthz endpoint handler is not properly restricting HTTP methods. It's currently accepting all request methods (or at least POST) instead of limiting to GET only.

## Recommended Fix
1. Add HTTP method validation to the `/api/healthz` route handler
2. Return 405 Method Not Allowed for any non-GET requests
3. Ensure the route is configured to only accept GET method (e.g., using `.get()` instead of `.all()` or `.use()`)

## Example
```javascript
// Instead of accepting all methods
app.all('/api/healthz', handler);

// Use only GET
app.get('/api/healthz', handler);
```

---
Deployment: https://talos-2kiq1eyz0-darkin100s-projects.vercel.app
Commit: `b1542389f6eb12d8e815cb754fe7a240e0cc5c7c`
Triggering PR: #37
