// Local dev server — routes requests to the same handlers Vercel uses in
// production, without requiring the Vercel CLI or a Vercel auth token.
//
// Vercel deploys `api/**.js` as individual serverless functions; this file
// reproduces just enough of that behaviour (req.body parsing, req.query,
// res.status/res.json) for the local-demo and contributors.

import { createServer } from 'node:http';
import { URL } from 'node:url';

import healthz from './api/healthz.js';
import todos from './api/todos.js';
import todosId from './api/todos/[id].js';
import search from './api/todos/search.js';
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

  if (path === '/api/healthz') return healthz(req, res);
  if (path === '/api/todos') return todos(req, res);
  if (path === '/api/todos/search') return search(req, res);
  if (path.startsWith('/api/todos/')) {
    req.query.id = path.slice('/api/todos/'.length);
    return todosId(req, res);
  }
  res.status(404).json({ error: 'not found' });
});

server.listen(port, () => {
  logEvent('info', 'server_starting', { port });
});
