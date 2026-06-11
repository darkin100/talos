// Single Vercel function handling every /api/* route.
//
// Why one file? Vercel deploys each file under `api/` as a separate
// serverless function, so split per-route files do not share in-memory
// state. A single function keeps the demo's CRUD semantics intact within
// a warm function instance. State still resets on cold start; upgrade to
// Vercel KV for real persistence.
//
// Routing: `vercel.json` rewrites every `/api/*` request to
// `/api/handler?slug=*`. The dev-server.js shim builds the same `slug`
// value locally so both code paths agree.

import { store } from '../lib/store.js';
import { logEvent } from '../lib/logging.js';

function handleHealthz(req, res) {
  if (req.method !== 'GET') {
    res.status(405).json({ error: 'method not allowed' });
    return 405;
  }
  res.status(200).json({ status: 'ok' });
  return 200;
}

function handleTodos(req, res) {
  if (req.method === 'GET') {
    res.status(200).json(store.list());
    return 200;
  }
  if (req.method === 'POST') {
    const title = req.body && req.body.title;
    if (typeof title !== 'string' || !title) {
      logEvent('error', 'title is required', { status: 400 });
      res.status(400).json({ error: 'title is required' });
      return 400;
    }
    res.status(201).json(store.create(title));
    return 201;
  }
  res.status(405).json({ error: 'method not allowed' });
  return 405;
}

function handleSearch(req, res) {
  if (req.method !== 'GET') {
    res.status(405).json({ error: 'method not allowed' });
    return 405;
  }
  // Extract query parameter and coerce to string
  const rawQ = (req.query && req.query.q) || '';
  const q = String(rawQ).trim();
  res.status(200).json(store.search(q));
  return 200;
}

function handleTodoById(req, res, rawId) {
  const id = parseInt(rawId, 10);
  if (!Number.isInteger(id) || String(id) !== String(rawId)) {
    logEvent('error', 'invalid todo id', { status: 400, raw_id: rawId });
    res.status(400).json({ error: 'invalid todo id' });
    return 400;
  }
  if (req.method === 'GET') {
    const todo = store.get(id);
    if (!todo) {
      logEvent('error', 'todo not found', { status: 404, id });
      res.status(404).json({ error: 'todo not found' });
      return 404;
    }
    res.status(200).json(todo);
    return 200;
  }
  if (req.method === 'PUT') {
    const title = req.body && req.body.title;
    const completed = req.body && req.body.completed;
    if (typeof title !== 'string') {
      logEvent('error', 'invalid body', { status: 400 });
      res.status(400).json({ error: 'invalid body' });
      return 400;
    }
    const todo = store.update(id, title, completed);
    if (!todo) {
      logEvent('error', 'todo not found', { status: 404, id });
      res.status(404).json({ error: 'todo not found' });
      return 404;
    }
    res.status(200).json(todo);
    return 200;
  }
  if (req.method === 'DELETE') {
    if (!store.delete(id)) {
      logEvent('error', 'todo not found', { status: 404, id });
      res.status(404).json({ error: 'todo not found' });
      return 404;
    }
    res.status(200).json({ deleted: true, id });
    return 200;
  }
  res.status(405).json({ error: 'method not allowed' });
  return 405;
}

export default function handler(req, res) {
  const start = Date.now();
  // The `slug` value depends on the caller:
  //   * Vercel rewrite (`source: /api/:path*` -> `dest: /api/handler?slug=:path*`)
  //     delivers a slash-joined string like "todos/1".
  //   * dev-server.js passes an array of segments for parity.
  const slugRaw = (req.query && req.query.slug) || '';
  const slug = Array.isArray(slugRaw)
    ? slugRaw
    : slugRaw
      ? slugRaw.split('/')
      : [];
  const path = '/api/' + slug.join('/');
  let status = 500;

  try {
    if (slug.length === 1 && slug[0] === 'healthz') {
      status = handleHealthz(req, res);
      return;
    }
    if (slug.length === 1 && slug[0] === 'todos') {
      status = handleTodos(req, res);
      return;
    }
    if (slug.length === 2 && slug[0] === 'todos' && slug[1] === 'search') {
      status = handleSearch(req, res);
      return;
    }
    if (slug.length === 2 && slug[0] === 'todos') {
      status = handleTodoById(req, res, slug[1]);
      return;
    }
    status = 404;
    res.status(404).json({ error: 'not found' });
  } finally {
    logEvent('info', 'http_request', {
      method: req.method,
      path,
      status,
      duration_ms: Date.now() - start,
    });
  }
}
