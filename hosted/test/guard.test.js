// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
import test from 'node:test';
import assert from 'node:assert/strict';
import { normalizeSite, HttpSource, isPublicIPv4, isPublicIPv6, requirePublicResolution } from '../src/guard.js';
import { Invalid, Unreadable } from '../src/check.js';

test('addresses that are accepted become an origin, without path, query, fragment or default port', () => {
  const ok = {
    'cawnest.com': 'cawnest.com', 'https://cawnest.com': 'cawnest.com', 'HTTPS://CawNest.COM/': 'cawnest.com',
    '  https://cawnest.com/any/path?x=1#y  ': 'cawnest.com', 'https://cawnest.com:443/': 'cawnest.com',
    'node.tencaw-node.com': 'node.tencaw-node.com', 'cawnest.com.': 'cawnest.com', 'https://xn--n8jok5ay5dzabd5bym9f0cm5685rrjetr6pdxa.com': 'xn--n8jok5ay5dzabd5bym9f0cm5685rrjetr6pdxa.com',
  };
  for (const [input, host] of Object.entries(ok)) {
    const r = normalizeSite(input, 'verify.workers.dev');
    assert.equal(r.origin, 'https://' + host, input);
    assert.equal(r.host, host, input);
  }
});

test('everything that is not a plain public https host name is refused before any request', () => {
  const bad = [
    '', '   ', null, undefined, 5, {}, [], 'x'.repeat(301),
    'http://cawnest.com', 'ftp://cawnest.com', 'javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,hi', '//cawnest.com',
    'https://user@cawnest.com', 'https://user:pw@cawnest.com', 'https://cawnest.com@evil.org.evil', 'https://cawnest.com:8443', 'https://cawnest.com:80',
    'localhost', 'https://localhost', 'intranet', 'a.local', 'a.localhost', 'printer.lan', 'db.internal', 'x.home.arpa', 'x.corp', 'x.test', 'a.example', 'abc.onion',
    '127.0.0.1', 'https://127.0.0.1', '10.0.0.1', '192.168.0.1', '169.254.169.254', '0.0.0.0', '127.1', '2130706433', '0x7f.1', '0x7f000001', '017700000001',
    '[::1]', 'https://[::1]', 'https://[2001:db8::1]', '::1', '1.2.3.4.5',
    'a b.com', 'cawnest.com/ x', 'caw\nnest.com', 'cawnest.com\\@evil.org', 'ca_wnest.com', '-cawnest.com', 'cawnest-.com', '.cawnest.com', 'a..com',
    'verify.workers.dev', 'sub.verify.workers.dev', 'VERIFY.workers.dev',
  ];
  for (const input of bad) {
    assert.throws(() => normalizeSite(input, 'verify.workers.dev'), Invalid, JSON.stringify(input));
  }
});

test('IPv4: public addresses pass, private, loopback, link-local, shared, reserved and multicast do not', () => {
  for (const ip of ['1.1.1.1', '8.8.8.8', '93.184.216.34', '172.15.255.255', '172.32.0.1', '100.63.255.255', '100.128.0.1', '198.17.0.1', '198.20.0.1']) assert.equal(isPublicIPv4(ip), true, ip);
  for (const ip of ['0.0.0.0', '0.1.2.3', '10.0.0.1', '10.255.255.255', '100.64.0.1', '100.127.255.255', '127.0.0.1', '127.255.255.255', '169.254.169.254',
    '172.16.0.1', '172.31.255.255', '192.0.0.1', '192.0.2.1', '192.168.1.1', '198.18.0.1', '198.19.255.255', '198.51.100.7', '203.0.113.9', '224.0.0.1', '239.1.1.1',
    '240.0.0.1', '255.255.255.255', 'abc', '1.2.3', '1.2.3.256', '01.2.3.4.5', '']) assert.equal(isPublicIPv4(ip), false, ip);
});

test('IPv6: only global unicast passes; loopback, link-local, unique-local, mapped private, documentation, NAT64, 6to4 do not', () => {
  for (const ip of ['2606:4700:4700::1111', '2001:4860:4860::8888', '2a00:1450:4001:81b::200e']) assert.equal(isPublicIPv6(ip), true, ip);
  assert.equal(isPublicIPv6('::ffff:1.1.1.1'), true, 'mapped public IPv4');
  for (const ip of ['::', '::1', '0:0:0:0:0:0:0:1', 'fe80::1', 'febf::1', 'fc00::1', 'fd12:3456::1', 'ff02::1', '::ffff:127.0.0.1', '::ffff:10.0.0.1', '::ffff:a00:1',
    '2001:db8::1', '64:ff9b::7f00:1', '2002:7f00:1::1', '100::1', 'fe80::1%eth0', ':::', '1:2:3:4:5:6:7:8:9', 'gggg::1', '']) assert.equal(isPublicIPv6(ip), false, ip);
});

// ---------------------------------------------------------------- reading a site
const respond = (body, init = {}) => new Response(body, init);

test('a file is read when the answer is 200 and small enough', async () => {
  const seen = [];
  const s = new HttpSource('https://x.org', { fetchImpl: async (url, o) => { seen.push([url, o]); return respond('hello'); } });
  assert.equal(new TextDecoder().decode(await s.get('/assets/a.js', 100)), 'hello');
  assert.equal(seen[0][0], 'https://x.org/assets/a.js');
  assert.equal(seen[0][1].redirect, 'manual', 'redirects are never followed');
  assert.match(seen[0][1].headers['user-agent'], /caw-frontend-verify/);
  assert.equal(seen[0][1].headers.cookie, undefined);
});

test('a redirect, an error status, an unreachable site and a timeout are unreadable, with no detail from the other side', async () => {
  const cases = [
    [async () => respond(null, { status: 301, headers: { location: 'https://evil.org/' } }), /redirected/],
    [async () => respond(null, { status: 302, headers: { location: '/' } }), /redirected/],
    [async () => ({ type: 'opaqueredirect', status: 0, headers: new Headers(), body: null }), /redirected/],
    [async () => respond('no', { status: 404 }), /HTTP 404/],
    [async () => respond('no', { status: 500 }), /HTTP 500/],
    [async () => { throw new TypeError('connect ECONNREFUSED 10.0.0.5:443 secret-host'); }, /could not be reached/],
  ];
  for (const [fetchImpl, re] of cases) {
    const s = new HttpSource('https://x.org', { fetchImpl });
    await assert.rejects(s.get('a', 100), (e) => e instanceof Unreadable && re.test(e.message) && !/10\.0\.0\.5|secret-host|evil\.org/.test(e.message));
  }
  const slow = new HttpSource('https://x.org', { timeoutMs: 20, fetchImpl: (u, { signal }) => new Promise((_, rej) => signal.addEventListener('abort', () => rej(Object.assign(new Error('x'), { name: 'AbortError' })))) });
  await assert.rejects(slow.get('a', 100), /timed out/);
});

test('a body that is too large is refused whether it says so or not, and the rest is not downloaded', async () => {
  const declared = new HttpSource('https://x.org', { fetchImpl: async () => respond('x', { headers: { 'content-length': '1000' } }) });
  await assert.rejects(declared.get('a', 100), /declares more than 100/);

  let pulled = 0;
  const stream = new ReadableStream({
    pull(ctl) { pulled += 1; ctl.enqueue(new Uint8Array(40)); if (pulled > 1000) ctl.close(); },
  });
  const s = new HttpSource('https://x.org', { fetchImpl: async () => new Response(stream) });
  await assert.rejects(s.get('a', 100), /larger than 100/);
  assert.ok(pulled < 20, `stopped after ${pulled} chunks`);
});

test('a body that stalls after the headers is cut off by the timeout', async () => {
  const s = new HttpSource('https://x.org', { timeoutMs: 30, fetchImpl: async (u, { signal }) => {
    return new Response(new ReadableStream({
      start(ctl) { ctl.enqueue(new Uint8Array(3)); signal.addEventListener('abort', () => ctl.error(Object.assign(new Error('x'), { name: 'AbortError' }))); },
    }));
  } });
  await assert.rejects(s.get('a', 100), /timed out/);
});

// ---------------------------------------------------------------- where a name points
const doh = (table) => async (url) => {
  const u = new URL(url);
  assert.equal(u.hostname, 'cloudflare-dns.com');
  const entry = table[u.searchParams.get('name')];
  if (entry === 'fail') throw new Error('network');
  if (entry === 'bad') return new Response('x', { status: 500 });
  const type = u.searchParams.get('type');
  if (!entry) return Response.json({ Status: 3 });
  const code = type === 'A' ? 1 : 28;
  return Response.json({ Status: 0, Answer: (entry[type] || []).map((data) => ({ type: code, data })) });
};

test('a name is accepted only when every address it points at is public', async () => {
  await requirePublicResolution('ok.org', doh({ 'ok.org': { A: ['93.184.216.34'], AAAA: ['2606:4700:4700::1111'] } }));
  await requirePublicResolution('v4.org', doh({ 'v4.org': { A: ['1.1.1.1'] } }));
  const refuse = async (table, re) => assert.rejects(requirePublicResolution('h.org', doh({ 'h.org': table })), (e) => e instanceof Invalid && re.test(e.message));
  await refuse({ A: ['127.0.0.1'] }, /non-public/);
  await refuse({ A: ['169.254.169.254'] }, /non-public/);
  await refuse({ A: ['93.184.216.34', '10.0.0.1'] }, /non-public/);
  await refuse({ A: ['1.1.1.1'], AAAA: ['::1'] }, /non-public/);
  await refuse({ AAAA: ['fd00::1'] }, /non-public/);
  await refuse({ A: [] }, /does not point/);
  await assert.rejects(requirePublicResolution('gone.org', doh({})), (e) => e instanceof Invalid && /does not exist/.test(e.message));
  await assert.rejects(requirePublicResolution('x.org', doh({ 'x.org': 'fail' })), Unreadable);
  await assert.rejects(requirePublicResolution('x.org', doh({ 'x.org': 'bad' })), Unreadable);
});
