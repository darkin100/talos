import { store } from '../../lib/store.js';
import { logEvent } from '../../lib/logging.js';

export default function handler(req, res) {
  const start = Date.now();
  const rawId = req.query && req.query.id;
  let status = 500;
  try {
    const id = parseInt(rawId, 10);
    if (!Number.isInteger(id) || String(id) !== String(rawId)) {
      status = 400;
      logEvent('error', 'invalid todo id', { status, raw_id: rawId });
      return res.status(status).json({ error: 'invalid todo id' });
    }

    if (req.method === 'GET') {
      const todo = store.get(id);
      if (!todo) {
        status = 404;
        logEvent('error', 'todo not found', { status, id });
        return res.status(status).json({ error: 'todo not found' });
      }
      status = 200;
      return res.status(status).json(todo);
    }
    if (req.method === 'PUT') {
      const title = req.body && req.body.title;
      const completed = req.body && req.body.completed;
      if (typeof title !== 'string') {
        status = 400;
        logEvent('error', 'invalid body', { status });
        return res.status(status).json({ error: 'invalid body' });
      }
      const todo = store.update(id, title, completed);
      if (!todo) {
        status = 404;
        logEvent('error', 'todo not found', { status, id });
        return res.status(status).json({ error: 'todo not found' });
      }
      status = 200;
      return res.status(status).json(todo);
    }
    if (req.method === 'DELETE') {
      if (!store.delete(id)) {
        status = 404;
        logEvent('error', 'todo not found', { status, id });
        return res.status(status).json({ error: 'todo not found' });
      }
      status = 204;
      return res.status(status).end();
    }
    status = 405;
    return res.status(status).json({ error: 'method not allowed' });
  } finally {
    logEvent('info', 'http_request', {
      method: req.method,
      path: `/api/todos/${rawId}`,
      status,
      duration_ms: Date.now() - start,
    });
  }
}
