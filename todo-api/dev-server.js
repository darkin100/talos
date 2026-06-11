// Local dev server — routes requests through the same single Vercel
// function used in production, without requiring the Vercel CLI or auth.
//
// Vercel deploys `api/handler.js` as one serverless function (with a
// `/api/:path*` rewrite in vercel.json); this file reproduces just
// enough of that runtime (body parsing, req.query.slug, res.status/
// res.json) for the local-demo and contributors. It also serves the
// static files under `public/` the same way Vercel does in production.

import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, join, normalize, resolve } from 'node:path';
import { URL } from 'node:url';
import { fileURLToPath } from 'node:url';

import handler from './api/handler.js';
import { logEvent } from './lib/logging.js';

const port = Number(process.env.PORT) || 3000;
const publicDir = resolve(dirname(fileURLToPath(import.meta.url)), 'public');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
};

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

async function serveStatic(req, res, urlPath) {
  const relative = urlPath === '/' ? '/index.html' : urlPath;
  // Resolve under publicDir and reject any path that escapes it.
  const candidate = normalize(join(publicDir, relative));
  if (!candidate.startsWith(publicDir)) {
    res.status(403).json({ error: 'forbidden' });
    return;
  }
  try {
    const body = await readFile(candidate);
    const ext = candidate.slice(candidate.lastIndexOf('.'));
    res.setHeader('content-type', MIME[ext] || 'application/octet-stream');
    res.status(200).end(body);
  } catch (err) {
    if (err.code === 'ENOENT') {
      res.status(404).json({ error: 'not found' });
      return;
    }
    throw err;
  }
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
    req.query.slug = path.slice('/api/'.length).split('/');
    return handler(req, res);
  }
  return serveStatic(req, res, path);
});

server.listen(port, () => {
  logEvent('info', 'server_starting', { port });
});
