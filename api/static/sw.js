// Aria service worker: lets the app open and Python practice run after a connection is lost.
//
// - App shell and static files: network-first (updates arrive when online), cache when offline.
// - Read-only lists (challenges, lessons): network-first with cache fallback.
// - The Python engine (Pyodide, from the CDN or /static/vendor): cache-first, it never changes.
// - POST requests (chat, tutor, grading) are never cached or answered here.
// - Media (/static/media) and any range request bypass the worker so the tour video streams normally.
const VERSION = 'aria-v5';
const SHELL = [
  '/chat', '/static/styles.css', '/static/app.js', '/static/voice.js', '/static/practice.js', '/static/challenge_harness.py',
  '/static/aria-wave.svg', '/static/aria-mark.svg', '/static/aria-call.svg',
];
const NETWORK_TIMEOUT_MS = 5000;

// importScripts() requests are 'opaque', which a cache-on-success rule would skip, so the two
// script files the Python engine needs are fetched explicitly with CORS (jsDelivr allows it).
const PYODIDE_CDN = 'https://cdn.jsdelivr.net/pyodide/v0.26.4/full/';
const PYODIDE_SCRIPTS = [PYODIDE_CDN + 'pyodide.js', PYODIDE_CDN + 'pyodide.asm.js'];

async function precacheCors(cache, url) {
  const response = await fetch(url, { mode: 'cors' });
  if (response.ok) await cache.put(url, response);
}

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(VERSION)
      .then(cache => Promise.allSettled([...SHELL.map(url => cache.add(url)), ...PYODIDE_SCRIPTS.map(url => precacheCors(cache, url))]))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== VERSION).map(k => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

// Fonts are cached after the first visit so the type stays consistent offline.
function isFont(url) {
  return url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
}

function isPyodide(url) {
  return (url.hostname === 'cdn.jsdelivr.net' && url.pathname.startsWith('/pyodide/'))
    || (url.origin === self.location.origin && url.pathname.startsWith('/static/vendor/pyodide/'));
}

async function cacheFirst(request) {
  const cache = await caches.open(VERSION);
  const hit = await cache.match(request);
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) cache.put(request, response.clone());
  return response;
}

async function networkFirst(request) {
  const cache = await caches.open(VERSION);
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), NETWORK_TIMEOUT_MS);
    const response = await fetch(request, { signal: controller.signal });
    clearTimeout(timer);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch (_) {
    // Static files may match ignoring ?v=... cache-busters. Data endpoints must match EXACTLY, or a
    // request for one track's challenges could be answered with another track's cached list.
    const url = new URL(request.url);
    const hit = (await cache.match(request)) || (url.pathname.startsWith('/static/') ? await cache.match(request, { ignoreSearch: true }) : undefined);
    if (hit) return hit;
    throw _;
  }
}

self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET') return;
  // Video and other range requests go straight to the network: partial (206) responses cannot be cached.
  if (request.headers.has('range')) return;
  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/static/media/')) return;
  const sameOrigin = url.origin === self.location.origin;
  if (isPyodide(url) || isFont(url)) {
    event.respondWith(cacheFirst(request));
  } else if (sameOrigin && (url.pathname.startsWith('/static/') || url.pathname === '/chat' || url.pathname === '/challenges' || url.pathname === '/tutor/lessons')) {
    event.respondWith(networkFirst(request));
  }
});
