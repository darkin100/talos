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

test('GET /api/todos/ with empty id returns 400', () => {
  const res = mockRes();
  handler({ method: 'GET', query: { slug: 'todos/' } }, res);
  assert.equal(res.statusCode, 400);
  assert.deepEqual(res.body, { error: 'invalid todo id' });
});

test('POST /api/todos with 500-char title returns 201', () => {
  const res = mockRes();
  const title = 'a'.repeat(500);
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title },
    },
    res,
  );
  assert.equal(res.statusCode, 201);
  assert.equal(res.body.title, title);
});

test('POST /api/todos with 501-char title returns 400', () => {
  const res = mockRes();
  const title = 'a'.repeat(501);
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title },
    },
    res,
  );
  assert.equal(res.statusCode, 400);
  assert(res.body.error.includes('exceeds maximum length'));
});

test('GET /api/todos without filter returns all todos', () => {
  // Get initial count
  const resInitial = mockRes();
  handler({ method: 'GET', query: { slug: 'todos' } }, resInitial);
  const initialCount = resInitial.body.length;

  const res1 = mockRes();
  // Create one open todo
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Open Task' },
    },
    res1,
  );
  const openTodoId = res1.body.id;

  const res2 = mockRes();
  // Create one completed todo
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Completed Task' },
    },
    res2,
  );
  const completedTodoId = res2.body.id;

  // Mark second todo as completed
  const res3 = mockRes();
  handler(
    {
      method: 'PUT',
      query: { slug: ['todos', String(completedTodoId)] },
      body: { title: 'Completed Task', completed: true },
    },
    res3,
  );

  // List all todos without filter
  const res4 = mockRes();
  handler({ method: 'GET', query: { slug: 'todos' } }, res4);
  assert.equal(res4.statusCode, 200);
  assert.equal(res4.body.length, initialCount + 2);
});

test('GET /api/todos?completed=true returns only completed todos', () => {
  const res1 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Another Open' },
    },
    res1,
  );
  const openId = res1.body.id;

  const res2 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Another Completed' },
    },
    res2,
  );
  const completedId = res2.body.id;

  const res3 = mockRes();
  handler(
    {
      method: 'PUT',
      query: { slug: ['todos', String(completedId)] },
      body: { title: 'Another Completed', completed: true },
    },
    res3,
  );

  const res4 = mockRes();
  handler(
    { method: 'GET', query: { slug: 'todos', completed: 'true' } },
    res4,
  );
  assert.equal(res4.statusCode, 200);
  assert.equal(res4.body.length >= 1, true);
  res4.body.forEach(t => assert.equal(t.completed, true));
});

test('GET /api/todos?completed=false returns only open todos', () => {
  const res1 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Yet Another Open' },
    },
    res1,
  );
  const openId = res1.body.id;

  const res2 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Yet Another Completed' },
    },
    res2,
  );
  const completedId = res2.body.id;

  const res3 = mockRes();
  handler(
    {
      method: 'PUT',
      query: { slug: ['todos', String(completedId)] },
      body: { title: 'Yet Another Completed', completed: true },
    },
    res3,
  );

  const res4 = mockRes();
  handler(
    { method: 'GET', query: { slug: 'todos', completed: 'false' } },
    res4,
  );
  assert.equal(res4.statusCode, 200);
  assert.equal(res4.body.length >= 1, true);
  res4.body.forEach(t => assert.equal(t.completed, false));
});

test('GET /api/todos?completed=invalid returns 400', () => {
  const res = mockRes();
  handler(
    { method: 'GET', query: { slug: 'todos', completed: 'invalid' } },
    res,
  );
  assert.equal(res.statusCode, 400);
  assert(res.body.error.includes('true') || res.body.error.includes('false'));
});

test('DELETE /api/todos?completed=true deletes only completed todos', () => {
  // Create one open and one completed todo
  const res1 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Will Stay' },
    },
    res1,
  );
  const openId = res1.body.id;

  const res2 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Will Be Deleted' },
    },
    res2,
  );
  const completedId = res2.body.id;

  // Mark second as completed
  const res3 = mockRes();
  handler(
    {
      method: 'PUT',
      query: { slug: ['todos', String(completedId)] },
      body: { title: 'Will Be Deleted', completed: true },
    },
    res3,
  );

  // Get count before deletion
  const resBeforeDelete = mockRes();
  handler(
    { method: 'GET', query: { slug: 'todos', completed: 'true' } },
    resBeforeDelete,
  );
  const completedCountBefore = resBeforeDelete.body.length;

  // Delete all completed
  const res4 = mockRes();
  handler(
    { method: 'DELETE', query: { slug: 'todos', completed: 'true' } },
    res4,
  );
  assert.equal(res4.statusCode, 200);
  assert.equal(res4.body.deleted, completedCountBefore);

  // Verify the completed one is gone but open one remains
  const res5 = mockRes();
  handler({ method: 'GET', query: { slug: ['todos', String(openId)] } }, res5);
  assert.equal(res5.statusCode, 200);
  assert.equal(res5.body.id, openId);
});

test('DELETE /api/todos?completed=true returns 0 when no todos are completed', () => {
  // Create only open todos
  const res1 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Open Task 1' },
    },
    res1,
  );

  const res2 = mockRes();
  handler(
    {
      method: 'POST',
      query: { slug: 'todos' },
      body: { title: 'Open Task 2' },
    },
    res2,
  );

  // Delete with completed=true (should delete 0 items)
  const res3 = mockRes();
  handler(
    { method: 'DELETE', query: { slug: 'todos', completed: 'true' } },
    res3,
  );
  assert.equal(res3.statusCode, 200);
  assert.equal(res3.body.deleted, 0);
});

test('DELETE /api/todos without completed=true filter returns 400', () => {
  const res = mockRes();
  handler(
    { method: 'DELETE', query: { slug: 'todos' } },
    res,
  );
  assert.equal(res.statusCode, 400);
  assert(res.body.error.includes('filter') || res.body.error.includes('true'));
});

test('DELETE /api/todos?completed=false returns 400 (invalid filter)', () => {
  const res = mockRes();
  handler(
    { method: 'DELETE', query: { slug: 'todos', completed: 'false' } },
    res,
  );
  assert.equal(res.statusCode, 400);
  assert(res.body.error.includes('filter') || res.body.error.includes('true'));
});

test('DELETE /api/todos?completed=invalid returns 400', () => {
  const res = mockRes();
  handler(
    { method: 'DELETE', query: { slug: 'todos', completed: 'invalid' } },
    res,
  );
  assert.equal(res.statusCode, 400);
  assert(res.body.error.includes('filter') || res.body.error.includes('true'));
});
