import { test } from 'node:test';
import { strict as assert } from 'node:assert';

import { Store } from '../lib/store.js';

test('list is empty initially', () => {
  const s = new Store();
  assert.deepEqual(s.list(), []);
});

test('create assigns ids and returns the new todo', () => {
  const s = new Store();
  const a = s.create('Buy milk');
  const b = s.create('Walk dog');
  assert.equal(a.id, 1);
  assert.equal(b.id, 2);
  assert.equal(a.title, 'Buy milk');
  assert.equal(a.completed, false);
});

test('search returns empty list for empty query', () => {
  const s = new Store();
  s.create('Buy milk');
  s.create('Walk dog');
  assert.deepEqual(s.search(''), []);
});

test('search is case-insensitive substring match', () => {
  const s = new Store();
  s.create('Buy MILK');
  s.create('Walk dog');
  const results = s.search('milk');
  assert.equal(results.length, 1);
  assert.equal(results[0].title, 'Buy MILK');
});

test('update modifies an existing todo and returns null on missing id', () => {
  const s = new Store();
  s.create('original');
  const updated = s.update(1, 'updated', true);
  assert.equal(updated.title, 'updated');
  assert.equal(updated.completed, true);
  assert.equal(s.update(999, 'x', false), null);
});

test('delete returns true for existing id and false for missing', () => {
  const s = new Store();
  s.create('something');
  assert.equal(s.delete(1), true);
  assert.equal(s.delete(1), false);
});

test('update preserves completed when not provided in request', () => {
  const s = new Store();
  s.create('original');
  // Mark as completed
  s.update(1, 'original', true);
  // Update title without providing completed field
  const updated = s.update(1, 'updated', undefined);
  assert.equal(updated.title, 'updated');
  assert.equal(updated.completed, true, 'completed should remain true');
});
