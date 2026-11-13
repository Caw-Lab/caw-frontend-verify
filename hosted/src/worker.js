// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
//
// The hosted service: serves the page of ../web and answers POST /api/check with the contract check of
// one site. Anyone can use it, so it refuses what it can before doing any work: other origins, bad
// input, too many requests. A result is kept for a few minutes, which also spares the checked site.

import { check, assemble, failed, Invalid, Unreadable } from './check.js';
import { normalizeSite, HttpSource, requirePublicResolution } from './guard.js';
import DATA from './data.json' with { type: 'json' };

export const SETTINGS = {
  perIpPerMinute: 10,        // checks one address may ask for per minute (best effort without the rate-limit binding)
  globalPerMinute: 300,      // checks this running copy of the service does per minute
  cacheSeconds: 300,         // how long a result is kept
  cacheSecondsShort: 60,     // how long a result is kept when the site could not be read
  maxBodyBytes: 1024,
  overallTimeoutMs: 25000,
};

const CSP = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; " +
  "base-uri 'none'; form-action 'none'; frame-ancestors 'none'";
const SECURITY_HEADERS = {
  'x-content-type-options': 'nosniff',
  'referrer-policy': 'no-referrer',
  'cross-origin-resource-policy': 'same-origin',
  'x-frame-options': 'DENY',
  'strict-transport-security': 'max-age=31536000',
};

// A short fingerprint of the data, so that a result made with older data is never served after a new one is deployed.
const DATA_VERSION = (() => {
  let h = 5381;
  for (const ch of JSON.stringify(DATA)) h = ((h * 33) ^ ch.charCodeAt(0)) >>> 0;
  return h.toString(36);
})();

// ---------------------------------------------------------------- limits and cache (best effort, per running copy)
const hits = new Map();      // ip -> [timestamps]
let globalHits = [];
const memCache = new Map();  // key -> { exp, value }

function recent(list, now, windowMs) {
  while (list.length && now - list[0] > windowMs) list.shift();
  return list;
}

async function allowed(env, ip) {
  const now = Date.now();
  globalHits = recent(globalHits, now, 60000);
  if (globalHits.length >= SETTINGS.globalPerMinute) return false;
  if (env && env.RATE_LIMITER && typeof env.RATE_LIMITER.limit === 'function') {
    const { success } = await env.RATE_LIMITER.limit({ key: ip });
    if (!success) return false;
  } else {
    if (hits.size > 5000) hits.clear();
    const mine = recent(hits.get(ip) || [], now, 60000);
    if (mine.length >= SETTINGS.perIpPerMinute) return false;
    mine.push(now);
    hits.set(ip, mine);
  }
  globalHits.push(now);
  return true;
}

const cacheKey = (host) => `https://cache.invalid/check/${DATA_VERSION}/${host}`;

async function cacheGet(host) {
  const key = cacheKey(host);
  try {
    if (typeof caches !== 'undefined' && caches.default) {
      const r = await caches.default.match(new Request(key));
      if (r) return await r.json();
    }
  } catch { /* the cache is an optimisation only */ }
  const m = memCache.get(key);
  if (m && m.exp > Date.now()) return m.value;
  return null;
}

async function cachePut(host, value, seconds) {
  const key = cacheKey(host);
  if (memCache.size > 200) memCache.clear();
  memCache.set(key, { exp: Date.now() + seconds * 1000, value });
  try {
    if (typeof caches !== 'undefined' && caches.default) {
      await caches.default.put(new Request(key), new Response(JSON.stringify(value), {
        headers: { 'content-type': 'application/json', 'cache-control': `public, max-age=${seconds}` },
      }));
    }
  } catch { /* the cache is an optimisation only */ }
}

// For tests only: forget what this running copy remembers.
export function _reset() { hits.clear(); globalHits = []; memCache.clear(); }

// ---------------------------------------------------------------- responses
function json(status, body, extra = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', ...SECURITY_HEADERS, ...extra },
  });
}

// ---------------------------------------------------------------- the check
export async function runCheck(origin, host, { fetchImpl = fetch } = {}) {
  const source = new HttpSource(origin, { fetchImpl });
  const memo = new Map();
  const memoSource = { get: (p, limit) => { if (!memo.has(p)) memo.set(p, source.get(p, limit)); return memo.get(p); } };
  const out = { site: origin, releases: [] };
  for (const release of DATA.releases) {
    let bridge;
    try {
      bridge = await check(memoSource, origin, release.fingerprint, release.labels);
    } catch (e) {
      if (e instanceof Unreadable) bridge = failed('UNREADABLE', e.message);
      else if (e instanceof Invalid) throw e;
      else throw e;
    }
    out.releases.push(assemble(release, origin, bridge).releases[0]);
  }
  return out;
}

async function handleCheck(request, env, url) {
  const origin = request.headers.get('origin');
  if (origin !== null && origin !== url.origin) return json(403, { error: 'forbidden origin' });
  if (request.headers.get('x-requested-with') !== 'caw-frontend-verify') return json(403, { error: 'forbidden' });
  if (!(request.headers.get('content-type') || '').includes('application/json')) return json(415, { error: 'send JSON' });
  const declared = request.headers.get('content-length');
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > SETTINGS.maxBodyBytes)) return json(413, { error: 'the request is too large' });
  const raw = await request.text();
  if (raw.length > SETTINGS.maxBodyBytes) return json(413, { error: 'the request is too large' });

  let body;
  try { body = JSON.parse(raw); } catch { return json(400, { error: 'that is not a valid request' }); }
  if (body === null || typeof body !== 'object' || Array.isArray(body)) return json(400, { error: 'that is not a valid request' });

  let site;
  try {
    site = normalizeSite(body.site, url.hostname);
  } catch (e) {
    if (e instanceof Invalid) return json(400, { error: e.message });
    throw e;
  }

  const ip = request.headers.get('cf-connecting-ip') || 'unknown';
  if (!(await allowed(env, ip))) return json(429, { error: 'too many checks; try again in a minute' }, { 'retry-after': '60' });

  const cached = await cacheGet(site.host);
  if (cached) return json(200, cached, { 'x-cache': 'hit' });

  try {
    await requirePublicResolution(site.host, env && env.fetchImpl);
  } catch (e) {
    if (e instanceof Invalid) return json(400, { error: e.message });
    if (e instanceof Unreadable) return json(503, { error: e.message });
    throw e;
  }

  let timer;
  const result = await Promise.race([
    runCheck(site.origin, site.host, { fetchImpl: env && env.fetchImpl }),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Unreadable('the check took too long')), SETTINGS.overallTimeoutMs); }),
  ]).finally(() => clearTimeout(timer));
  const unreadable = result.releases.some((r) => r.facts.contractsNamed.verdict === 'UNREADABLE');
  await cachePut(site.host, result, unreadable ? SETTINGS.cacheSecondsShort : SETTINGS.cacheSeconds);
  return json(200, result, { 'x-cache': 'miss' });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname === '/api/info') {
        if (request.method !== 'GET') return json(405, { error: 'method not allowed' });
        return json(200, { hosted: true });
      }
      if (url.pathname === '/api/check') {
        if (request.method !== 'POST') return json(405, { error: 'method not allowed' }, { allow: 'POST' });
        return await handleCheck(request, env, url);
      }
      if (url.pathname.startsWith('/api/')) return json(404, { error: 'not found' });
      if (request.method !== 'GET' && request.method !== 'HEAD') return json(405, { error: 'method not allowed' });
      const resp = await env.ASSETS.fetch(request);
      const headers = new Headers(resp.headers);
      headers.set('content-security-policy', CSP);
      for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
      return new Response(resp.body, { status: resp.status, headers });
    } catch (e) {
      if (e instanceof Unreadable) return json(504, { error: e.message });
      return json(500, { error: 'the check failed' });  // no detail: nothing of the inside is shown
    }
  },
};
