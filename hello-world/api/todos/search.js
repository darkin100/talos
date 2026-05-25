import { store } from '../../lib/store.js';
import { logEvent } from '../../lib/logging.js';

export default function handler(req, res) {
  const start = Date.now();
  let status = 500;
  try {
    if (req.method !== 'GET') {
      status = 405;
      return res.status(status).json({ error: 'method not allowed' });
    }
    const q = (req.query && req.query.q) || '';
    status = 200;
    return res.status(status).json(store.search(q));
  } finally {
    logEvent('info', 'http_request', {
      method: req.method,
      path: '/api/todos/search',
      status,
      duration_ms: Date.now() - start,
    });
  }
}
