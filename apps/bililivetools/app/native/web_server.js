'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const net = require('net');
const { URL } = require('url');

const FRONTEND_PORT = Number(process.env.FRONTEND_PORT || 3000);
const BACKEND_PORT = Number(process.env.BACKEND_PORT || 18010);
const BACKEND_HOST = process.env.BACKEND_HOST || '127.0.0.1';
const WEB_ROOT = path.resolve(process.env.WEB_ROOT || path.join(process.cwd(), 'webui'));
const PASSKEY = String(process.env.BILILIVE_TOOLS_PASSKEY || '');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.map': 'application/json; charset=utf-8',
};

const OLD_NATIVE5_MARKER = '<script>try{localStorage.setItem("api",window.location.origin)}catch(e){}</script>';

function proxyHttp(req, res) {
  const headers = { ...req.headers, host: `${BACKEND_HOST}:${BACKEND_PORT}` };
  const upstream = http.request({
    hostname: BACKEND_HOST,
    port: BACKEND_PORT,
    method: req.method,
    path: req.url,
    headers,
  }, (upRes) => {
    res.writeHead(upRes.statusCode || 502, upRes.headers);
    upRes.pipe(res);
  });
  upstream.on('error', (err) => {
    if (!res.headersSent) res.writeHead(502, { 'content-type': 'text/plain; charset=utf-8' });
    res.end(`biliLive-tools backend unavailable: ${err.message}`);
  });
  req.pipe(upstream);
}

function safeStaticPath(urlPath) {
  let decoded;
  try { decoded = decodeURIComponent(urlPath); } catch (_) { return null; }
  const clean = decoded.replace(/^\/+/, '');
  const candidate = path.resolve(WEB_ROOT, clean || 'index.html');
  if (candidate !== WEB_ROOT && !candidate.startsWith(WEB_ROOT + path.sep)) return null;
  return candidate;
}

function staticFileFor(urlPath) {
  const candidate = safeStaticPath(urlPath);
  if (!candidate) return null;
  try {
    const st = fs.statSync(candidate);
    return st.isFile() ? { path: candidate, stat: st } : null;
  } catch (_) {
    return null;
  }
}

function sendKnownFile(file, st, res) {
  const ext = path.extname(file).toLowerCase();
  const headers = {
    'content-type': MIME[ext] || 'application/octet-stream',
    'content-length': st.size,
    'cache-control': 'public, max-age=86400',
  };
  res.writeHead(200, headers);
  fs.createReadStream(file).pipe(res);
}

function buildBootstrapScript() {
  // The upstream WebUI requires both localStorage.api and localStorage.key.
  // Its Login component deletes "api" and reloads when only api exists, so native5's
  // api-only marker caused an infinite reload/flicker loop.  Inject both values here.
  // Also escape a stale #/login route before Vue Router starts, otherwise the Login
  // component would still execute its removeItem('api') + reload behavior.
  const keyLiteral = JSON.stringify(PASSKEY);
  return `<script id="fnos-native1-bootstrap">(function(){try{` +
    `localStorage.setItem("api",window.location.origin);` +
    `localStorage.setItem("key",${keyLiteral});` +
    `if(/^#\\/login(?:[?]|$)/.test(window.location.hash)){` +
      `history.replaceState(null,"",window.location.pathname+window.location.search+"#/home");` +
    `}` +
  `}catch(e){console.error("fnOS bootstrap",e)}})();</script>`;
}

function sendIndex(res) {
  const file = path.join(WEB_ROOT, 'index.html');
  fs.readFile(file, 'utf8', (err, raw) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('WebUI not installed');
      return;
    }
    if (!PASSKEY) {
      res.writeHead(500, { 'content-type': 'text/plain; charset=utf-8' });
      res.end('fnOS passKey is missing');
      return;
    }
    // Remove the native5 api-only injection from an existing runtime after an in-place upgrade.
    let html = raw.split(OLD_NATIVE5_MARKER).join('');
    const bootstrap = buildBootstrapScript();
    if (html.includes('</head>')) html = html.replace('</head>', `${bootstrap}\n</head>`);
    else html = bootstrap + '\n' + html;
    const body = Buffer.from(html, 'utf8');
    res.writeHead(200, {
      'content-type': 'text/html; charset=utf-8',
      'content-length': body.length,
      'cache-control': 'no-store, no-cache, must-revalidate',
      'pragma': 'no-cache',
    });
    res.end(body);
  });
}

function isBrowserDocumentRequest(req) {
  const dest = String(req.headers['sec-fetch-dest'] || '').toLowerCase();
  if (dest === 'document' || dest === 'iframe') return true;
  const accept = String(req.headers.accept || '').toLowerCase();
  return accept.includes('text/html');
}

const server = http.createServer((req, res) => {
  const u = new URL(req.url, `http://${req.headers.host || 'localhost'}`);

  if (u.pathname === '/healthz') {
    res.writeHead(200, { 'content-type': 'text/plain; charset=utf-8' });
    res.end('ok');
    return;
  }

  // Always transform the SPA entry page.  Do this before static-file handling so '/'
  // cannot bypass the native1 auth/bootstrap injection.
  if ((req.method === 'GET' || req.method === 'HEAD') && (u.pathname === '/' || u.pathname === '/index.html')) {
    sendIndex(res);
    return;
  }

  if (req.method === 'GET' || req.method === 'HEAD') {
    const found = staticFileFor(u.pathname);
    if (found) {
      sendKnownFile(found.path, found.stat, res);
      return;
    }
    if (isBrowserDocumentRequest(req)) {
      sendIndex(res);
      return;
    }
  }

  proxyHttp(req, res);
});

server.on('upgrade', (req, socket, head) => {
  const upstream = net.connect(BACKEND_PORT, BACKEND_HOST, () => {
    let raw = `${req.method} ${req.url} HTTP/${req.httpVersion}\r\n`;
    const h = req.rawHeaders || [];
    let hasHost = false;
    for (let i = 0; i < h.length; i += 2) {
      if (String(h[i]).toLowerCase() === 'host') {
        raw += `Host: ${BACKEND_HOST}:${BACKEND_PORT}\r\n`;
        hasHost = true;
      } else {
        raw += `${h[i]}: ${h[i + 1]}\r\n`;
      }
    }
    if (!hasHost) raw += `Host: ${BACKEND_HOST}:${BACKEND_PORT}\r\n`;
    raw += '\r\n';
    upstream.write(raw);
    if (head && head.length) upstream.write(head);
    socket.pipe(upstream);
    upstream.pipe(socket);
  });
  upstream.on('error', () => socket.destroy());
  socket.on('error', () => upstream.destroy());
});

server.listen(FRONTEND_PORT, '0.0.0.0', () => {
  console.log(`[fnOS wrapper native1] WebUI: 0.0.0.0:${FRONTEND_PORT}, backend: ${BACKEND_HOST}:${BACKEND_PORT}`);
});
