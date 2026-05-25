import { logEvent } from '../lib/logging.js';

export default function handler(req, res) {
  const start = Date.now();
  res.status(200).json({ status: 'ok' });
  logEvent('info', 'http_request', {
    method: req.method,
    path: '/api/healthz',
    status: 200,
    duration_ms: Date.now() - start,
  });
}
