// Site-root handler. Vercel routes `/` here via the `/` rewrite in
// vercel.json. Kept separate from api/handler.js so the slug-parsing
// router never has to consider an empty-path case.

import { logEvent } from '../lib/logging.js';

export default function handler(req, res) {
  const start = Date.now();
  res.setHeader('content-type', 'text/plain');
  res.status(200).end('hello');
  logEvent('info', 'http_request', {
    method: req.method,
    path: '/',
    status: 200,
    duration_ms: Date.now() - start,
  });
}
