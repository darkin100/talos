import { store } from '../lib/store.js';
import { logEvent } from '../lib/logging.js';

export default function handler(req, res) {
  const start = Date.now();
  let status = 500;
  try {
    if (req.method === 'GET') {
      status = 200;
      return res.status(status).json(store.list());
    }
    if (req.method === 'POST') {
      const title = req.body && req.body.title;
      if (!title || typeof title !== 'string') {
        status = 400;
        logEvent('error', 'title is required', { status });
        return res.status(status).json({ error: 'title is required' });
      }
      const todo = store.create(title);
      status = 201;
      return res.status(status).json(todo);
    }
    status = 405;
    return res.status(status).json({ error: 'method not allowed' });
  } finally {
    logEvent('info', 'http_request', {
      method: req.method,
      path: '/api/todos',
      status,
      duration_ms: Date.now() - start,
    });
  }
}
