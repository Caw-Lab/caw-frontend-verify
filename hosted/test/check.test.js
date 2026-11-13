// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
import test from 'node:test';
import assert from 'node:assert/strict';
import { check, assemble, failed, extract, genericLabel, pageScripts, validateFingerprint, looksLikeHtml, Invalid, Unreadable, MAX_PRELOADS_READ } from '../src/check.js';

const A = (n) => '0x' + n.toString(16).padStart(40, 'a').slice(-40);
const REQ = [A(0x1111), A(0x2222), A(0x3333)];
const FP = { schemaVersion: 1, kind: 'caw-frontend-address-fingerprint', name: 'fp', addresses: REQ };
const LABELS = { [REQ[0]]: 'L1.One', [REQ[1]]: 'L2.Two' };
const enc = (s) => new TextEncoder().encode(s);

// A fake site: files by path; a path that is missing throws Unreadable like a 404.
function site(files) {
  const calls = [];
  return {
    calls,
    async get(path) {
      calls.push(path);
      if (!(path in files)) throw new Unreadable(`${path} answered HTTP 404`);
      return enc(files[path]);
    },
  };
}
const page = (extra = '') => `<!doctype html><script type="module" src="/assets/index-AAA.js"></script>${extra}`;
const js = (...addrs) => addrs.map((a, i) => `const k${i}="${a}";`).join('') + 'function f(){return 1}';

test('the entry script names exactly the fingerprint: MATCH, with labels and counts', async () => {
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(...REQ) });
  const r = await check(s, 'https://x.org', FP, LABELS);
  assert.equal(r.verdict, 'MATCH');
  assert.equal(r.required, 3); assert.equal(r.present, 3);
  assert.deepEqual(r.missing, []); assert.deepEqual(r.unexpected, []);
  assert.deepEqual(r.recognized, ['L1.One', 'L2.Two']);
  assert.equal(r.entry, 'assets/index-AAA.js');
  assert.equal(r.tool, 'bridge');
});

test('a missing and an unexpected address: DIFFERENT, both listed (with the label where one is known)', async () => {
  const other = A(0x9999);
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(REQ[0], REQ[2], other) });
  const r = await check(s, 'https://x.org', FP, LABELS);
  assert.equal(r.verdict, 'DIFFERENT');
  assert.deepEqual(r.missing, [{ address: REQ[1], label: 'L2.Two' }]);
  assert.deepEqual(r.unexpected, [{ address: other, label: null }]);
});

test('only an extra address, nothing missing: still DIFFERENT (the extra one is what differs)', async () => {
  const extra = A(0x8888);
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(...REQ, extra) });
  const r = await check(s, 'https://x.org', FP, LABELS);
  assert.equal(r.verdict, 'DIFFERENT');
  assert.deepEqual(r.missing, []);
  assert.deepEqual(r.unexpected, [{ address: extra, label: null }]);
  assert.equal(r.present, 3);
});

test('generic addresses say nothing and are ignored; case does not matter; a longer hex run is not an address', async () => {
  for (const g of ['0x000000000000000000000000000000000000dead', '0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEEEEeeeeEEEe', '0xcA11bde05977b3631167028862bE2a173976CA11',
    '0x0000000000000000000000000000000000000001', '0x4200000000000000000000000000000000000006']) {
    assert.notEqual(genericLabel(g), null, g);
    assert.equal(extract(`x="${g}"`).size, 0, g);
  }
  assert.equal(extract('0x' + 'a'.repeat(41)).size, 0, 'hex run of 41 digits');
  assert.deepEqual([...extract('0xABCDEFabcdefABCDEFabcdefABCDEFabcdefABCD')], ['0xabcdefabcdefabcdefabcdefabcdefabcdefabcd']);
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(...REQ) + 'x="0x000000000000000000000000000000000000dead"' });
  assert.equal((await check(s, 'https://x.org', FP)).verdict, 'MATCH');
});

test('the entry is the first module script with a src; other scripts are ignored; external ones are counted, not read', () => {
  const html = '<script src="/old.js"></script><script type="module" src="https://cdn.example.org/a.js"></script>' +
    '<script type="module" src="//cdn.example.org/b.js"></script><script type="MODULE" src=\'./assets/main.js?v=3#x\'></script><script type="module" src="/other.js"></script>';
  assert.deepEqual(pageScripts(html), { entry: 'assets/main.js', preloads: [], external: 2 });
  assert.equal(pageScripts('<script type="module">inline()</script>').entry, null);
});

test('a script path that leaves the site, or no entry script, is unreadable', async () => {
  assert.throws(() => pageScripts('<script type="module" src="/a/../../etc/x.js"></script>'), Unreadable);
  await assert.rejects(check(site({ 'index.html': '<html></html>' }), 'https://x.org', FP), Unreadable);
  await assert.rejects(check(site({}), 'https://x.org', FP), Unreadable);
  await assert.rejects(check(site({ 'index.html': page() }), 'https://x.org', FP), Unreadable);
});

test('preloaded files are read only when an address is still missing, and a required address found there counts', async () => {
  const html = page('<link rel="modulepreload" href="/assets/chunk-1.js"><link rel="MODULEPRELOAD" href="/assets/chunk-2.js">');
  const base = { 'index.html': html, 'assets/index-AAA.js': js(REQ[0], REQ[1]), 'assets/chunk-1.js': 'nothing here', 'assets/chunk-2.js': js(REQ[2]) };
  const s = site(base);
  const r = await check(s, 'https://x.org', FP);
  assert.equal(r.verdict, 'MATCH'); assert.equal(r.present, 3);
  // nothing missing: the preloads are not fetched at all
  const s2 = site({ ...base, 'assets/index-AAA.js': js(...REQ) });
  await check(s2, 'https://x.org', FP);
  assert.deepEqual(s2.calls, ['index.html', 'assets/index-AAA.js']);
  // an address found only in a preload is never "unexpected": unexpected is judged on the entry script alone
  const s3 = site({ ...base, 'assets/chunk-1.js': js(A(0x7777), REQ[2]), 'assets/chunk-2.js': '' });
  const r3 = await check(s3, 'https://x.org', FP);
  assert.equal(r3.verdict, 'MATCH');
});

test('a preload that cannot be read only weakens the presence check', async () => {
  const html = page('<link rel="modulepreload" href="/assets/gone.js"><link rel="modulepreload" href="/assets/c.js">');
  const s = site({ 'index.html': html, 'assets/index-AAA.js': js(REQ[0], REQ[1]), 'assets/c.js': js(REQ[2]) });
  assert.equal((await check(s, 'https://x.org', FP)).verdict, 'MATCH');
  const s2 = site({ 'index.html': html, 'assets/index-AAA.js': js(REQ[0], REQ[1]) });
  assert.equal((await check(s2, 'https://x.org', FP)).verdict, 'DIFFERENT');
});

test('too many preloads to read while an address is still missing: no verdict is given', async () => {
  const links = Array.from({ length: MAX_PRELOADS_READ + 3 }, (_, i) => `<link rel="modulepreload" href="/assets/c${i}.js">`).join('');
  const files = { 'index.html': page(links), 'assets/index-AAA.js': js(REQ[0], REQ[1]) };
  for (let i = 0; i < MAX_PRELOADS_READ + 3; i++) files[`assets/c${i}.js`] = 'empty';
  const s = site(files);
  await assert.rejects(check(s, 'https://x.org', FP), (e) => e instanceof Unreadable && /run the check locally/.test(e.message));
  assert.equal(s.calls.filter((c) => c.startsWith('assets/c')).length, MAX_PRELOADS_READ, 'the limit is kept');
  // but the same site with the address found within the limit is judged
  files['assets/c0.js'] = js(REQ[2]);
  assert.equal((await check(site(files), 'https://x.org', FP)).verdict, 'MATCH');
});

test('a fingerprint that checks nothing, or is malformed, is refused', async () => {
  const bad = [
    null, [], 'x', {}, { ...FP, schemaVersion: 2 }, { ...FP, kind: 'other' }, { ...FP, addresses: [] }, { ...FP, addresses: 'x' },
    { ...FP, addresses: ['0x12'] }, { ...FP, addresses: [REQ[0], REQ[0].toUpperCase().replace('0X', '0x')] },
    { ...FP, addresses: ['0x000000000000000000000000000000000000dead'] }, { ...FP, addresses: [5] },
  ];
  for (const fp of bad) {
    assert.ok(validateFingerprint(fp).length > 0, JSON.stringify(fp));
    await assert.rejects(check(site({ 'index.html': page(), 'assets/index-AAA.js': js(...REQ) }), 'https://x.org', fp), Invalid);
  }
  assert.deepEqual(validateFingerprint(FP), []);
});

test('assemble: matched only on MATCH; an unreadable site is incomplete and never a match', () => {
  const rel = { id: 'r', publisher: { name: 'p', kind: 'upstream' }, network: 'testnet', source: { repo: 'a/b', commit: 'c'.repeat(40), tagged: false }, title: 'T' };
  const m = assemble(rel, 'https://x.org', { tool: 'bridge', verdict: 'MATCH' }).releases[0];
  assert.equal(m.matched, true); assert.equal(m.incomplete, false);
  assert.equal(m.facts.frontendFiles.verdict, 'NOT_AVAILABLE'); assert.equal(m.facts.contractsOnChain.verdict, 'SKIPPED');
  const d = assemble(rel, 'https://x.org', { tool: 'bridge', verdict: 'DIFFERENT' }).releases[0];
  assert.equal(d.matched, false); assert.equal(d.incomplete, false);
  const u = assemble(rel, 'https://x.org', failed('UNREADABLE', 'x'.repeat(500))).releases[0];
  assert.equal(u.matched, false); assert.equal(u.incomplete, true);
  assert.equal(u.facts.contractsNamed.reason.length, 200);
});

// ---------------------------------------------------------------- a script that is an HTML page, and notes
const HTML_PAGE = '<!doctype html><html><head></head><body><div id="root"></div></body></html>';

test('the entry script answers with an HTML page: unreadable, never a verdict on addresses', async () => {
  for (const body of [HTML_PAGE, '\n  ' + HTML_PAGE, '\ufeff' + HTML_PAGE.toUpperCase(), '<html lang="en"></html>']) {
    const s = site({ 'index.html': page(), 'assets/index-AAA.js': body });
    await assert.rejects(() => check(s, 'https://x.org', FP, LABELS), (e) => e instanceof Unreadable && /HTML page/.test(e.message));
  }
});

test('a real script that merely mentions html is not mistaken for a page', async () => {
  assert.equal(looksLikeHtml(enc('const a="<!doctype html>";')), false);
  assert.equal(looksLikeHtml(enc('import"./v.js";const h="<html>";')), false);
  assert.equal(looksLikeHtml(enc('')), false);
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(...REQ) + 'const h="<html></html>";' });
  assert.equal((await check(s, 'https://x.org', FP, LABELS)).verdict, 'MATCH');
});

test('a preload that answers with an HTML page only weakens the presence check', async () => {
  const s = site({
    'index.html': page('<link rel="modulepreload" href="/assets/vendor.js">'),
    'assets/index-AAA.js': js(REQ[0], REQ[1]),
    'assets/vendor.js': HTML_PAGE,
  });
  const r = await check(s, 'https://x.org', FP, LABELS);
  assert.equal(r.verdict, 'DIFFERENT');
  assert.deepEqual(r.missing.map((m) => m.address), [REQ[2]]);
});

const NOTE = { en: 'A note.', ja: '注記。' };

test('notes are attached to missing and unexpected addresses only', async () => {
  const other = A(0x9999);
  const fp = { ...FP, addressNotes: { [other]: NOTE, [REQ[2]]: NOTE, [A(0x7777)]: NOTE } };
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(REQ[0], REQ[1], other) });
  const r = await check(s, 'https://x.org', fp, LABELS);
  assert.deepEqual(r.unexpected, [{ address: other, label: null, note: 'A note.', noteJa: '注記。' }]);
  assert.deepEqual(r.missing, [{ address: REQ[2], label: null, note: 'A note.', noteJa: '注記。' }]);
  const plain = await check(s, 'https://x.org', FP, LABELS);
  assert.deepEqual(plain.unexpected, [{ address: other, label: null }]);
});

test('notes never change a verdict, and bad notes are refused', async () => {
  const s = site({ 'index.html': page(), 'assets/index-AAA.js': js(...REQ) });
  assert.equal((await check(s, 'https://x.org', { ...FP, addressNotes: { [A(0x7777)]: NOTE } }, LABELS)).verdict, 'MATCH');
  for (const bad of [{ '0x12': NOTE }, { [A(0x7777).replace('7', 'A')]: NOTE }, { [A(0x7777)]: { en: 'x' } },
    { [A(0x7777)]: { en: 'x'.repeat(301), ja: 'y' } }, [NOTE], 'text']) {
    assert.ok(validateFingerprint({ ...FP, addressNotes: bad }).some((p) => /addressNotes/.test(p)), JSON.stringify(bad).slice(0, 40));
  }
});
