// Local dev server — routes requests through the same single Vercel
// function used in production, without requiring the Vercel CLI or auth.
//
// Vercel deploys `api/handler.js` as one serverless function (with a
// `/api/:path*` rewrite in vercel.json); this file reproduces just
// enough of that runtime (body parsing, req.query.slug, res.status/
// res.json) for the local-demo and contributors.

import { createServer } from 'node:http';
import { URL } from 'node:url';

import handler from './api/handler.js';
import { logEvent } from './lib/logging.js';

const port = Number(process.env.PORT) || 3000;

function readBody(req) {
  return new Promise((resolve, reject) => {
    let buf = '';
    req.on('data', (chunk) => {
      buf += chunk;
    });
    req.on('end', () => {
      if (!buf) return resolve(undefined);
      const ctype = req.headers['content-type'] || '';
      if (ctype.includes('application/json')) {
        try {
          return resolve(JSON.parse(buf));
        } catch (err) {
          return reject(err);
        }
      }
      resolve(buf);
    });
    req.on('error', reject);
  });
}

function patchResponse(res) {
  res.status = (code) => {
    res.statusCode = code;
    return res;
  };
  res.json = (obj) => {
    res.setHeader('content-type', 'application/json');
    res.end(JSON.stringify(obj));
    return res;
  };
  return res;
}

const server = createServer(async (req, res) => {
  patchResponse(res);
  try {
    req.body = await readBody(req);
  } catch (err) {
    return res.status(400).json({ error: 'invalid body' });
  }

  const url = new URL(req.url, `http://localhost:${port}`);
  req.query = Object.fromEntries(url.searchParams);
  const path = url.pathname;

  if (path.startsWith('/api/')) {
    req.query.slug = path.slice('/api/'.length).split('/').filter(Boolean);
    return handler(req, res);
  }
  res.status(404).json({ error: 'not found' });
});

server.listen(port, () => {
  logEvent('info', 'server_starting', { port });
});
