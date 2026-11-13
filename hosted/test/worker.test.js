// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import worker, { SETTINGS, _reset } from '../src/worker.js';
import { MAX_LISTED } from '../src/check.js';
import DATA from '../src/data.json' with { type: 'json' };

const REQ = DATA.releases[0].fingerprint.addresses;
const HOST = 'svc.workers.dev';
const js = (...addrs) => addrs.map((a, i) => `const k${i}="${a}";`).join('') + 'function f(){return 1}';
const goodSite = () => ({ 'index.html': '<script type="module" src="/assets/index-A.js"></script>', 'assets/index-A.js': js(...REQ) });

// A fake outside world: sites by host name (files by path) and DNS answers by host name.
function world({ sites = {}, dns = {} } = {}) {
  const log = { site: [], dns: [] };
  const fetchImpl = async function (url, o) {
    assert.ok(['manual', 'follow', undefined].includes(o && o.redirect), `the platform does not accept redirect: ${o && o.redirect}`);
    assert.ok(this === undefined || this === globalThis, 'fetch was called as a method of another object (the platform refuses)');
    const u = new URL(url);
    if (u.hostname === 'cloudflare-dns.com') {
      const name = u.searchParams.get('name');
      log.dns.push(name);
      const ips = dns[name] ?? (sites[name] ? { A: ['93.184.216.34'] } : null);
      if (!ips) return Response.json({ Status: 3 });
      const type = u.searchParams.get('type');
      return Response.json({ Status: 0, Answer: (ips[type] || []).map((data) => ({ type: type === 'A' ? 1 : 28, data })) });
    }
    log.site.push(url);
    const files = sites[u.hostname];
    const path = u.pathname.slice(1);
    if (!files || !(path in files)) return new Response('not found', { status: 404 });
    return new Response(files[path]);
  };
  const env = { fetchImpl, ASSETS: { fetch: async () => new Response('<html>the page</html>', { headers: { 'content-type': 'text/html' } }) } };
  return { env, log };
}

const post = (body, { ip = '203.0.113.5', origin = `https://${HOST}`, headers = {}, raw } = {}) => new Request(`https://${HOST}/api/check`, {
  method: 'POST',
  headers: { 'content-type': 'application/json', 'x-requested-with': 'caw-frontend-verify', 'cf-connecting-ip': ip, ...(origin ? { origin } : {}), ...headers },
  body: raw ?? JSON.stringify(body),
});
const run = async (req, env) => { const r = await worker.fetch(req, env); return { r, body: await r.json() }; };

beforeEach(() => { _reset(); SETTINGS.perIpPerMinute = 10; SETTINGS.globalPerMinute = 300; });

test('a site that names exactly the published addresses: 200, matched, in the same shape as the command-line tool', async () => {
  const { env, log } = world({ sites: { 'good.org': goodSite() } });
  const { r, body } = await run(post({ site: 'good.org/anything?x' }), env);
  assert.equal(r.status, 200);
  assert.equal(body.site, 'https://good.org');
  const rel = body.releases[0];
  assert.equal(rel.id, DATA.releases[0].id);
  assert.equal(rel.matched, true); assert.equal(rel.incomplete, false);
  assert.equal(rel.facts.contractsNamed.verdict, 'MATCH');
  assert.equal(rel.facts.frontendFiles.verdict, 'NOT_AVAILABLE');
  assert.equal(rel.facts.contractsOnChain.verdict, 'SKIPPED');
  assert.equal(rel.titleJa, DATA.releases[0].titleJa);
  assert.deepEqual(log.site, ['https://good.org/index.html', 'https://good.org/assets/index-A.js'], 'exactly two requests to the site');
  assert.equal(r.headers.get('x-cache'), 'miss');
  assert.equal(r.headers.get('cache-control'), 'no-store');
  assert.equal(r.headers.get('access-control-allow-origin'), null, 'no cross-origin use');
  assert.equal(r.headers.get('x-content-type-options'), 'nosniff');
});

test('a second request for the same site within the window is answered from memory, without touching the site again', async () => {
  const { env, log } = world({ sites: { 'good.org': goodSite() } });
  await run(post({ site: 'good.org' }), env);
  const n = log.site.length, d = log.dns.length;
  const { r, body } = await run(post({ site: 'https://GOOD.org/' }, { ip: '203.0.113.9' }), env);
  assert.equal(r.headers.get('x-cache'), 'hit');
  assert.equal(body.releases[0].matched, true);
  assert.equal(log.site.length, n); assert.equal(log.dns.length, d);
});

test('a site with other addresses is not a match, and the result says which; a huge list is cut', async () => {
  const other = '0x' + 'ab'.repeat(20);
  const { env } = world({ sites: { 'other.org': { 'index.html': '<script type="module" src="/a.js"></script>', 'a.js': js(REQ[0], other) } } });
  const { body } = await run(post({ site: 'other.org' }), env);
  const f = body.releases[0].facts.contractsNamed;
  assert.equal(body.releases[0].matched, false);
  assert.equal(f.verdict, 'DIFFERENT');
  assert.ok(f.unexpected.some((u) => u.address === other));
  assert.equal(f.missing.length, REQ.length - 1);

  _reset();
  const many = Array.from({ length: 5000 }, (_, i) => '0x1' + (i + 1).toString(16).padStart(39, '0'));  // all different, none generic
  const big = world({ sites: { 'big.org': { 'index.html': '<script type="module" src="/a.js"></script>', 'a.js': js(...REQ, ...many) } } });
  const r2 = await run(post({ site: 'big.org' }), big.env);
  const g = r2.body.releases[0].facts.contractsNamed;
  assert.equal(g.unexpected.length, MAX_LISTED);
  assert.equal(g.unexpectedTotal, 5000);
  assert.ok(JSON.stringify(r2.body).length < 100000, 'the answer stays small');
});

test('a site that cannot be read gives an answer that is never a match', async () => {
  const { env } = world({ sites: { 'down.org': {} } });
  const { r, body } = await run(post({ site: 'down.org' }), env);
  assert.equal(r.status, 200);
  const rel = body.releases[0];
  assert.equal(rel.facts.contractsNamed.verdict, 'UNREADABLE');
  assert.equal(rel.matched, false); assert.equal(rel.incomplete, true);
});

test('requests that should not be served are refused before any outside request is made', async () => {
  const { env, log } = world({ sites: { 'good.org': goodSite() } });
  const cases = [
    [post({ site: 'good.org' }, { origin: 'https://evil.example.org' }), 403],
    [post({ site: 'good.org' }, { origin: 'null' }), 403],
    [post({ site: 'good.org' }, { headers: { 'x-requested-with': 'XMLHttpRequest' } }), 403],
    [post({ site: 'good.org' }, { headers: { 'x-requested-with': '' } }), 403],
    [post({ site: 'good.org' }, { headers: { 'content-type': 'text/plain' } }), 415],
    [post(null, { raw: '{"site":"good.org"' }), 400],
    [post(null, { raw: '[]' }), 400],
    [post(null, { raw: 'null' }), 400],
    [post(null, { raw: '"good.org"' }), 400],
    [post({}), 400], [post({ site: 5 }), 400], [post({ site: '' }), 400],
    [post({ site: 'http://good.org' }), 400], [post({ site: '127.0.0.1' }), 400], [post({ site: 'localhost' }), 400],
    [post({ site: '169.254.169.254' }), 400], [post({ site: 'https://good.org:8443' }), 400], [post({ site: 'user:pw@good.org' }), 400],
    [post({ site: HOST }), 400], [post({ site: 'x'.repeat(2000) }), 413],
    [post({ site: 'good.org' }, { headers: { 'content-length': '999999' } }), 413],
  ];
  for (const [req, status] of cases) {
    const { r, body } = await run(req, env);
    assert.equal(r.status, status, JSON.stringify(body));
    assert.equal(typeof body.error, 'string');
  }
  assert.deepEqual(log.site, []); assert.deepEqual(log.dns, []);
});

test('a name that points at a private address is refused after the look-up and before any request to it', async () => {
  const { env, log } = world({ sites: { 'rebind.org': goodSite() }, dns: { 'rebind.org': { A: ['127.0.0.1'] }, 'meta.org': { A: ['169.254.169.254'] }, 'mixed.org': { A: ['93.184.216.34', '10.1.1.1'] }, 'v6.org': { AAAA: ['fd00::1'] } } });
  for (const site of ['rebind.org', 'meta.org', 'mixed.org', 'v6.org']) {
    const { r, body } = await run(post({ site }), env);
    assert.equal(r.status, 400, site);
    assert.match(body.error, /non-public/);
  }
  const gone = await run(post({ site: 'doesnotexist.org' }), env);
  assert.equal(gone.r.status, 400); assert.match(gone.body.error, /does not exist/);
  assert.deepEqual(log.site, []);
});

test('each address may ask for only so many checks a minute, and others are not affected', async () => {
  const { env } = world({ sites: { 'good.org': goodSite() } });
  for (let i = 0; i < SETTINGS.perIpPerMinute; i++) assert.equal((await run(post({ site: 'good.org' }, { ip: '198.51.100.1' }), env)).r.status, 200);
  const { r, body } = await run(post({ site: 'good.org' }, { ip: '198.51.100.1' }), env);
  assert.equal(r.status, 429); assert.equal(r.headers.get('retry-after'), '60'); assert.match(body.error, /too many/);
  assert.equal((await run(post({ site: 'good.org' }, { ip: '198.51.100.2' }), env)).r.status, 200);
});

test('the service as a whole also has a limit, so many addresses together cannot overload it', async () => {
  SETTINGS.globalPerMinute = 3;
  const { env } = world({ sites: { 'good.org': goodSite() } });
  for (let i = 0; i < 3; i++) assert.equal((await run(post({ site: 'good.org' }, { ip: `192.0.2.${i}` }), env)).r.status, 200);
  assert.equal((await run(post({ site: 'good.org' }, { ip: '192.0.2.99' }), env)).r.status, 429);
});

test('when the rate-limit binding exists it decides, and a refusal there is a 429', async () => {
  const { env } = world({ sites: { 'good.org': goodSite() } });
  const keys = [];
  env.RATE_LIMITER = { limit: async ({ key }) => { keys.push(key); return { success: false }; } };
  const { r } = await run(post({ site: 'good.org' }, { ip: '198.51.100.7' }), env);
  assert.equal(r.status, 429);
  assert.deepEqual(keys, ['198.51.100.7']);
  env.RATE_LIMITER = { limit: async () => ({ success: true }) };
  assert.equal((await run(post({ site: 'good.org' }, { ip: '198.51.100.7' }), env)).r.status, 200);
});

test('other methods, other paths and other origins get nothing; the page gets security headers', async () => {
  const { env } = world();
  const get = (path, init = {}) => worker.fetch(new Request(`https://${HOST}${path}`, init), env);
  assert.deepEqual(await (await get('/api/info')).json(), { hosted: true });
  assert.equal((await get('/api/check')).status, 405);
  assert.equal((await get('/api/check', { method: 'PUT' })).status, 405);
  assert.equal((await get('/api/check', { method: 'OPTIONS' })).status, 405);
  assert.equal((await get('/api/job')).status, 404);
  assert.equal((await get('/api/info', { method: 'POST', body: '{}' })).status, 405);
  assert.equal((await get('/', { method: 'POST', body: '{}' })).status, 405);
  const page = await get('/');
  assert.equal(page.status, 200);
  assert.match(page.headers.get('content-security-policy'), /default-src 'none'/);
  assert.match(page.headers.get('content-security-policy'), /connect-src 'self'/);
  assert.equal(page.headers.get('x-frame-options'), 'DENY');
  assert.equal(page.headers.get('access-control-allow-origin'), null);
  assert.equal(await page.text(), '<html>the page</html>');
});

test('an unexpected failure shows nothing of the inside', async () => {
  const env = { ASSETS: { fetch: async () => { throw new Error('boom: /srv/secret/path token=abc'); } } };
  const r = await worker.fetch(new Request(`https://${HOST}/`), env);
  assert.equal(r.status, 500);
  const text = await r.text();
  assert.ok(!/secret|boom|token/.test(text), text);
});

test('a site that is slow to answer makes the whole check give up in time', async () => {
  const { env } = world({ sites: { 'good.org': goodSite() } });
  const never = new Promise(() => {});
  const inner = env.fetchImpl;
  const slowEnv = { ...env, fetchImpl: async (url, o) => (new URL(url).hostname === 'cloudflare-dns.com' ? inner(url, o) : never) };
  const saved = SETTINGS.overallTimeoutMs;
  SETTINGS.overallTimeoutMs = 50;
  try {
    const { r, body } = await run(post({ site: 'good.org' }), slowEnv);
    assert.equal(r.status, 504);
    assert.match(body.error, /took too long/);
  } finally {
    SETTINGS.overallTimeoutMs = saved;
  }
});
