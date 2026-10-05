'use strict';
// Verhoog VERSION bij elke wijziging aan dit bestand of aan de cachestrategie:
// oude caches worden bij activate verwijderd.
const VERSION = 'v2';
const SHELL = `ommeke-shell-${VERSION}`;
const STATIC = `ommeke-static-${VERSION}`;
const PAGES = `ommeke-pages-${VERSION}`;
const KEEP = [SHELL, STATIC, PAGES];
const ASSETS = ['/offline.html', '/offline.js', '/favicon.svg'];
const MAX_STATIC = 150;
const MAX_PAGES = 12;

self.addEventListener('install', event => {
  event.waitUntil(caches.open(SHELL).then(cache => cache.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(key => key.startsWith('ommeke-') && !KEEP.includes(key)).map(key => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

async function trim(cacheName, max) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  await Promise.all(keys.slice(0, Math.max(0, keys.length - max)).map(key => cache.delete(key)));
}

// Alleen publieke, niet-persoonlijke antwoorden worden bewaard.
function cacheable(request, response) {
  if (!response || response.status !== 200 || response.type !== 'basic' || response.redirected) return false;
  if (request.headers.has('authorization')) return false;
  const control = (response.headers.get('cache-control') || '').toLowerCase();
  return !/no-store|private/.test(control) && !response.headers.has('set-cookie');
}

async function networkFirstPage(event) {
  const { request } = event;
  const url = new URL(request.url);
  try {
    const response = await fetch(request);
    if (cacheable(request, response) && (response.headers.get('content-type') || '').includes('text/html')) {
      const copy = response.clone();
      event.waitUntil(caches.open(PAGES).then(cache => cache.put(url.pathname, copy)).then(() => trim(PAGES, MAX_PAGES)));
    }
    return response;
  } catch (error) {
    // Routepagina's tonen offline zonder API alleen een foutmelding; de offline-viewer
    // toont de bewaarde routelijn en het hoogteprofiel wel.
    const routeMatch = url.pathname.match(/^\/routes\/([^/]+)\/?$/);
    if (routeMatch) {
      const viewer = await caches.match('/offline.html');
      if (viewer) return viewer;
    }
    return (await caches.match(url.pathname)) || (await caches.match('/offline.html')) || Response.error();
  }
}

async function cacheFirstStatic(event) {
  const cached = await caches.match(event.request);
  if (cached) return cached;
  const response = await fetch(event.request);
  if (cacheable(event.request, response)) {
    const copy = response.clone();
    event.waitUntil(caches.open(STATIC).then(cache => cache.put(event.request, copy)).then(() => trim(STATIC, MAX_STATIC)));
  }
  return response;
}

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || request.method !== 'GET') return;
  if (url.pathname.startsWith('/api/')) return;
  if (ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(url.pathname).then(cached => cached || fetch(request)));
  } else if (url.pathname.startsWith('/_next/static/')) {
    event.respondWith(cacheFirstStatic(event));
  } else if (request.mode === 'navigate') {
    event.respondWith(networkFirstPage(event));
  }
});
