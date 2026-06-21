import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import handler from '../api/handler.js';

// Minimal Express/Vercel-style res double: records status + json body.
function mockRes() {
  return {
    statusCode: null,
    body: undefined,
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    },
    end() {
      return this;
    },
  };
}

test('GET /api/healthz returns 200 ok', () => {
  const res = mockRes();
  handler({ method: 'GET', query: { slug: 'healthz' } }, res);
  assert.equal(res.statusCode, 200);
  assert.deepEqual(res.body, { status: 'ok' });
});

test('POST /api/healthz returns 405 (method guard)', () => {
  const res = mockRes();
  handler({ method: 'POST', query: { slug: 'healthz' } }, res);
  assert.equal(res.statusCode, 405);
  assert.deepEqual(res.body, { error: 'method not allowed' });
});
