import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import handler from '../api/[...slug].js';
import { store } from '../lib/store.js';

function createResponse() {
  return {
    statusCode: 200,
    body: undefined,
    status(code) {
      this.statusCode = code;
      return this;
    },
    json(payload) {
      this.body = payload;
      return this;
    },
    end() {},
  };
}

test('todos created via /api/todos are visible to other routes in same handler', () => {
  store.todos.clear();
  store.nextId = 1;

  const createReq = { method: 'POST', body: { title: 'demo' }, query: { slug: ['todos'] } };
  const createRes = createResponse();
  handler(createReq, createRes);
  assert.equal(createRes.statusCode, 201);
  assert.equal(createRes.body.title, 'demo');
  assert.equal(createRes.body.id, 1);

  const listReq = { method: 'GET', query: { slug: ['todos'] } };
  const listRes = createResponse();
  handler(listReq, listRes);
  assert.equal(listRes.statusCode, 200);
  assert.equal(listRes.body.length, 1);
  assert.equal(listRes.body[0].id, 1);

  const byIdReq = { method: 'GET', query: { slug: ['todos', '1'] } };
  const byIdRes = createResponse();
  handler(byIdReq, byIdRes);
  assert.equal(byIdRes.statusCode, 200);
  assert.equal(byIdRes.body.title, 'demo');
});
