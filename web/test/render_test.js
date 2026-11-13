// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
//
// Tests for render.js and static checks on the page. Run from the web/ folder:  node --test test/
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const V = require('../render.js');

const root = path.join(__dirname, '..');
const read = (f) => fs.readFileSync(path.join(root, f), 'utf8');

const bridgeMatch = { verdict: 'MATCH', present: 15, required: 15, missing: [], unexpected: [], recognized: ['L1.CawProfile'] };
const chainPass = { verdict: 'PASS', summary: { OK: 173 }, codeEvidence: { 'recompile-identical': 34, 'recompile-except-metadata': 1, 'sourcify-match': 3 }, flagged: [] };
const rel = (over) => Object.assign({
  id: 'rel-a', publisher: { name: 'Publisher A', kind: 'upstream' }, network: 'testnet',
  source: { repo: 'Org/Repo', commit: 'a'.repeat(40), tagged: false }, lineage: { note: 'as it is' },
  facts: { frontendFiles: { verdict: 'NOT_AVAILABLE', reason: 'no list' }, contractsNamed: bridgeMatch, contractsOnChain: chainPass },
  matched: true, incomplete: false }, over || {});
const result = (releases, site) => ({ site: site || 'https://a.example', releases });
const status = (sites) => ({ schemaVersion: 1, kind: 'caw-verify-status', generatedAt: '2026-11-13T00:00:00Z', sites });

// ---------------------------------------------------------------- normalize
test('accepts a status file, one result, and an array of results', () => {
  assert.equal(V.normalize(status([{ site: 'https://a.example', result: result([rel()]) }])).sites.length, 1);
  assert.equal(V.normalize(result([rel()])).sites[0].releases[0].id, 'rel-a');
  assert.equal(V.normalize([result([rel()]), result([rel()], 'https://b.example')]).sites.length, 2);
  assert.equal(V.normalize(status([{ site: 'x', result: result([rel()]) }])).generatedAt, '2026-11-13T00:00:00Z');
});

test('refuses what is not a result', () => {
  for (const bad of [null, undefined, 1, 'x', true, {}, [], { releases: 'no' }, { kind: 'other' }])
    assert.throws(() => V.normalize(bad), /./, JSON.stringify(bad));
  assert.throws(() => V.normalize(status([])), /no sites/);
  assert.throws(() => V.normalize({ schemaVersion: 2, kind: 'caw-verify-status', sites: [] }), /version/);
});

test('a site that could not be checked is kept, with its error, and is never a match', () => {
  const m = V.normalize(status([{ site: 'https://x.example', error: 'the check timed out' }]));
  assert.equal(m.sites[0].error, 'the check timed out');
  assert.deepEqual(m.sites[0].releases, []);
});

test('an unknown or missing verdict becomes an error with no tone of success', () => {
  const m = V.normalize(result([rel({ facts: { frontendFiles: { verdict: 'GREAT' }, contractsNamed: null, contractsOnChain: { verdict: 'PASS' } } })]));
  const f = m.sites[0].releases[0].facts;
  assert.equal(f.frontendFiles.verdict, 'ERROR');
  assert.equal(f.frontendFiles.tone, 'unknown');
  assert.equal(f.contractsNamed.verdict, 'ERROR');
});

test('"matched" is true only when the data says exactly true', () => {
  for (const v of ['true', 1, 'yes', {}, [], null]) assert.equal(V.normalize(result([rel({ matched: v })])).sites[0].releases[0].matched, false, String(v));
  assert.equal(V.normalize(result([rel({ matched: true })])).sites[0].releases[0].matched, true);
});

test('long text is cut and lists are capped', () => {
  const long = 'x'.repeat(5000);
  const many = Array.from({ length: 500 }, (_, i) => ({ address: '0x' + i, label: 'l' }));
  const m = V.normalize(result([rel({ id: long, lineage: { note: long }, facts: { frontendFiles: { verdict: 'NOT_AVAILABLE' }, contractsNamed: { verdict: 'DIFFERENT', missing: many, unexpected: many }, contractsOnChain: chainPass } })], long));
  const r = m.sites[0].releases[0];
  assert.ok(r.id.length <= 80 && r.lineage.length <= 400 && m.sites[0].site.length <= 200);
  assert.equal(r.facts.contractsNamed.missing.length, V.LIMITS.list);
});

test('too many releases or sites are cut to the limits', () => {
  const m = V.normalize(result(Array.from({ length: 200 }, (_, i) => rel({ id: 'r' + i }))));
  assert.equal(m.sites[0].releases.length, V.LIMITS.releases);
  const s = V.normalize(Array.from({ length: 500 }, () => result([rel()])));
  assert.equal(s.sites.length, V.LIMITS.sites);
});

test('markup in the data stays plain text in the view model', () => {
  const evil = '<img src=x onerror=alert(1)><script>alert(2)</script>';
  const m = V.normalize(result([rel({ id: evil, publisher: { name: evil, kind: 'upstream' } })], evil));
  assert.equal(m.sites[0].releases[0].id, evil.slice(0, 80));
  assert.equal(typeof m.sites[0].site, 'string');
});

test('numbers that are not numbers become null, not text', () => {
  const m = V.normalize(result([rel({ facts: { frontendFiles: { verdict: 'MATCH', match: '3', listed: NaN, mismatch: Infinity, missing: {}, error: null }, contractsNamed: bridgeMatch, contractsOnChain: chainPass } })]));
  const f = m.sites[0].releases[0].facts.frontendFiles;
  assert.equal(f.match, null); assert.equal(f.listed, null); assert.equal(f.mismatch, null);
});

// ---------------------------------------------------------------- wording
test('every verdict has a sentence in English and Japanese; a failure never reads like the success sentence', () => {
  const cases = {
    frontendFiles: { ok: ['MATCH'], bad: ['DIFFERENT', 'INCOMPLETE', 'NOT_AVAILABLE', 'ERROR'] },
    contractsNamed: { ok: ['MATCH'], bad: ['DIFFERENT', 'UNREADABLE', 'ERROR'] },
    contractsOnChain: { ok: ['PASS'], bad: ['FAIL', 'SKIPPED', 'ERROR'] },
  };
  const base = { reason: 'why', match: 1, listed: 2, mismatch: 1, missing: 1, error: 1, present: 1, required: 2, checks: 5, built: 3 };
  for (const lang of ['en', 'ja']) for (const [key, c] of Object.entries(cases)) {
    const make = (verdict) => Object.assign({}, base, { verdict, tone: V.TONES[verdict] || 'unknown',
      missing: key === 'contractsNamed' ? [{}] : 1, unexpected: [{}], flagged: ['a'] });
    const success = V.sentence(key, make(c.ok[0]), lang);
    for (const verdict of c.ok.concat(c.bad)) {
      const s = V.sentence(key, make(verdict), lang);
      assert.ok(typeof s === 'string' && s.length > 3, `${key} ${verdict} ${lang}`);
      assert.ok(!/\{\w+\}/.test(s), `unfilled placeholder in ${s}`);
      if (c.bad.includes(verdict)) assert.ok(!s.includes(success.slice(-10)) && s !== success, `${key} ${verdict} ${lang}: ${s}`);
    }
  }
});

test('a number that is missing is shown as ?, never as undefined or NaN', () => {
  const f = V.normalize(result([rel({ facts: { frontendFiles: { verdict: 'MATCH' }, contractsNamed: bridgeMatch, contractsOnChain: chainPass } })])).sites[0].releases[0].facts.frontendFiles;
  const s = V.sentence('frontendFiles', f, 'en');
  assert.ok(s.includes('?') && !/undefined|NaN|null/.test(s));
});

test('the overall line follows matched / incomplete', () => {
  const r = V.normalize(result([rel()])).sites[0].releases[0];
  assert.match(V.overall(r, 'en'), /every check that ran/);
  assert.match(V.overall(Object.assign({}, r, { matched: false, incomplete: true }), 'en'), /Cannot tell/);
  assert.match(V.overall(Object.assign({}, r, { matched: false, incomplete: false }), 'en'), /Does not match/);
  assert.match(V.overall(Object.assign({}, r, { matched: false, incomplete: false }), 'ja'), /違います/);
});

test('English and Japanese text tables have the same keys', () => {
  assert.deepEqual(Object.keys(V.T.en).sort(), Object.keys(V.T.ja).sort());
  assert.equal(V.T.en.limits.length, V.T.ja.limits.length);
  assert.deepEqual(Object.keys(V.T.en.chip).sort(), Object.keys(V.T.ja.chip).sort());
  assert.deepEqual(Object.keys(V.T.en.chipRelease).sort(), Object.keys(V.T.ja.chipRelease).sort());
  assert.deepEqual(Object.keys(V.T.en.networkName).sort(), Object.keys(V.T.ja.networkName).sort());
});

// ---------------------------------------------------------------- static checks on the page
test('no script builds HTML from data or runs strings as code', () => {
  for (const f of ['app.js', 'render.js']) {
    const src = read(f);
    for (const bad of [/innerHTML/, /outerHTML/, /insertAdjacentHTML/, /document\.write/, /\beval\s*\(/, /new Function/, /setTimeout\s*\(\s*['"`]/, /setInterval\s*\(\s*['"`]/, /\.srcdoc/, /createContextualFragment/])
      assert.ok(!bad.test(src), `${f} uses ${bad}`);
  }
});

test('the page sets a strict content security policy and loads nothing from elsewhere', () => {
  const html = read('index.html');
  const csp = (html.match(/Content-Security-Policy" content="([^"]+)"/) || [])[1] || '';
  for (const d of ["default-src 'none'", "script-src 'self'", "style-src 'self'", "connect-src 'self'", "base-uri 'none'", "form-action 'none'"])
    assert.ok(csp.includes(d), `missing ${d}`);
  assert.ok(!/unsafe-inline|unsafe-eval|\*/.test(csp), 'CSP is loosened');
  assert.ok(!/(src|href)=["']?(https?:)?\/\//i.test(html), 'an external resource is referenced');
  assert.ok(!/<script(?![^>]*\bsrc=)[^>]*>/i.test(html), 'an inline script');
  assert.ok(!/\sstyle=/i.test(html) && !/<style/i.test(html), 'inline style');
  assert.ok(!/@import|url\(\s*['"]?https?:/i.test(read('style.css')), 'the stylesheet loads something');
});

test('the page only talks to its own directory and its own local API, without redirects or credentials', () => {
  const src = read('app.js');
  const raw = src.match(/\bfetch\(/g) || [];
  assert.equal(raw.length, 2, 'only the status file and the api helper may call fetch');
  assert.ok(/fetch\('status\.json'/.test(src));
  assert.ok(/fetch\(path,/.test(src));
  assert.equal((src.match(/redirect\s*[:=]\s*'error'/g) || []).length, 2);
  assert.equal((src.match(/credentials\s*[:=]\s*'omit'/g) || []).length, 2);
  for (const m of src.matchAll(/\bapi\(([^,)]*)/g)) if (m[1] !== 'path' && !/^'\/api\//.test(m[1])) assert.fail('api() called with ' + m[1]);
  assert.ok(!/XMLHttpRequest|WebSocket|sendBeacon|EventSource|importScripts/.test(src));
});

test('the check box shows only when the local server or the hosted service answers for itself', () => {
  assert.ok(/id="checker"[^>]*\shidden/.test(read('index.html')));
  const src = read('app.js');
  // local: only a loopback page over http that answers local:true with a token
  assert.ok(/p === 'http:' && loopback/.test(src) && /'127\.0\.0\.1'/.test(src));
  assert.ok(/p === 'http:' && r\.ok && b\.local === true && typeof b\.token === 'string'/.test(src));
  // hosted: only over https, and only when the page's own origin says hosted:true
  assert.ok(/p === 'https:' && r\.ok && b\.hosted === true/.test(src));
  // a page opened from a file, or over http away from loopback, never shows the box
  assert.ok(/!\(\(p === 'http:' && loopback\) \|\| p === 'https:'\)/.test(src));
  assert.ok(/'X-Requested-With': 'caw-frontend-verify'/.test(src));
});

test('data is shown with textContent, and no script sets a link or a source from data', () => {
  const src = read('app.js');
  assert.ok(/textContent/.test(src));
  assert.ok(!/\.(src|href|action|formAction|data)\s*=[^=]/.test(src), 'a link or source is assigned');
  assert.ok(!/setAttribute\(\s*['"](src|href|action|style|on\w+)['"]/.test(src), 'a dangerous attribute is set');
});

test('the Japanese note of a release is carried, and cut like other text', () => {
  const m = V.normalize(result([rel({ lineage: { note: 'n', noteJa: 'あ'.repeat(900) } })]));
  const r = m.sites[0].releases[0];
  assert.equal(r.lineage, 'n');
  assert.ok(r.lineageJa.length <= 400);
  assert.equal(V.normalize(result([rel({ lineage: { note: 'n' } })])).sites[0].releases[0].lineageJa, '');
});

test('no Japanese sentence uses the old hard-to-read terms', () => {
  const all = JSON.stringify(V.T.ja) + JSON.stringify(V.sentence('contractsNamed', { verdict: 'MATCH', present: 1, required: 1 }, 'ja'));
  const verdicts = { frontendFiles: ['MATCH', 'DIFFERENT', 'INCOMPLETE', 'NOT_AVAILABLE', 'ERROR'], contractsNamed: ['MATCH', 'DIFFERENT', 'UNREADABLE', 'ERROR'],
    namedOnChain: ['MATCH', 'DIFFERENT', 'NOT_AVAILABLE', 'SKIPPED', 'ERROR'], contractsOnChain: ['PASS', 'FAIL', 'SKIPPED', 'ERROR'] };
  let words = all;
  for (const [k, vs] of Object.entries(verdicts)) for (const v of vs) words += V.sentence(k, { verdict: v, tone: 'x', missing: [{}], unexpected: [{}], flagged: [1] }, 'ja');
  assert.ok(!words.includes('リリース'), 'the word リリース is still shown to readers');
  for (const bad of ['名指', '出し手', '基づくもの', '対象外'])
    assert.ok(!all.includes(bad), `still uses ${bad}`);
});

test('the chain state of unlisted addresses: carried, worded, and old files without it still work', () => {
  const probe = { verdict: 'DIFFERENT', checked: 3, sameCode: 1, otherCode: 1, noCode: 1, notChecked: 4,
    addresses: [{ address: '0x' + 'a'.repeat(40), status: 'same-code', chain: 'L1', bytes: 10, sameAs: 'CawProfile' },
      { address: '0x' + 'b'.repeat(40), status: 'other-code', chain: 'L2', bytes: 19729 },
      { address: '0x' + 'c'.repeat(40), status: 'no-code' }, { address: 'x', status: 'EVIL<b>' }, 'junk'] };
  const withProbe = V.normalize(result([rel({ facts: { frontendFiles: { verdict: 'NOT_AVAILABLE' }, contractsNamed: bridgeMatch, contractsOnChain: chainPass, namedOnChain: probe } })])).sites[0].releases[0].facts;
  const f = withProbe.namedOnChain;
  assert.equal(f.verdict, 'DIFFERENT'); assert.equal(f.tone, 'differs');
  assert.equal(f.addresses.length, 4); assert.equal(f.addresses[3].status, 'unreadable');
  for (const lang of ['en', 'ja']) {
    const s = V.sentence('namedOnChain', f, lang);
    assert.ok(s.includes('3') && !/undefined|NaN|\{/.test(s), s);
    const lines = f.addresses.map((a) => V.addressLine(a, lang));
    assert.ok(lines[0].includes('Sepolia') && lines[0].includes('CawProfile'), lines[0]);
    assert.ok(lines[1].includes('Base Sepolia') && lines[1].includes('19729'), lines[1]);
    assert.ok(!lines.join('').includes('undefined'));
  }
  // an older result without the field: the row is simply absent
  assert.equal(V.normalize(result([rel()])).sites[0].releases[0].facts.namedOnChain, undefined);
  // a verdict nobody knows is never shown as success
  const bad = V.normalize(result([rel({ facts: { frontendFiles: { verdict: 'NOT_AVAILABLE' }, contractsNamed: bridgeMatch, contractsOnChain: chainPass, namedOnChain: { verdict: 'WONDERFUL' } } })])).sites[0].releases[0].facts.namedOnChain;
  assert.equal(bad.tone, 'unknown');
});

test('the release section is hidden when the release check was not run', () => {
  const src = read('app.js');
  assert.ok(/contractsOnChain\.verdict !== 'SKIPPED'/.test(src));
});

test('the name of a list is carried in both languages and cut like other text', () => {
  const m = V.normalize(result([rel({ title: 'T', titleJa: 'あ'.repeat(500) })])).sites[0].releases[0];
  assert.equal(m.title, 'T');
  assert.ok(m.titleJa.length <= 120);
  assert.equal(V.normalize(result([rel()])).sites[0].releases[0].title, '');
});

test('the chain-state row shows only when the site names addresses that are not in the list', () => {
  const mk = (named, contractsNamed) => V.normalize(result([rel({ facts: { frontendFiles: { verdict: 'NOT_AVAILABLE' },
    contractsNamed: contractsNamed || bridgeMatch, contractsOnChain: chainPass, namedOnChain: named } })])).sites[0].releases[0];
  const unlisted = Object.assign({}, bridgeMatch, { verdict: 'DIFFERENT', unexpected: [{ address: '0x' + 'a'.repeat(40) }] });
  assert.equal(V.showNamedOnChain(mk({ verdict: 'NOT_AVAILABLE', reason: 'none' })), false, 'nothing to look at');
  assert.equal(V.showNamedOnChain(mk({ verdict: 'SKIPPED' })), false, 'skipped and nothing unlisted');
  assert.equal(V.showNamedOnChain(mk({ verdict: 'SKIPPED' }, unlisted)), true, 'skipped but there are unlisted addresses');
  assert.equal(V.showNamedOnChain(mk({ verdict: 'DIFFERENT', checked: 1 }, unlisted)), true);
  assert.equal(V.showNamedOnChain(mk({ verdict: 'ERROR' }, unlisted)), true, 'an error must stay visible');
  assert.equal(V.showNamedOnChain(V.normalize(result([rel()])).sites[0].releases[0]), false, 'an older result without the field');
});

test('the file check says it is planned for the future while there are no fingerprints', () => {
  const f = V.normalize(result([rel()])).sites[0].releases[0].facts.frontendFiles;
  assert.equal(f.verdict, 'NOT_AVAILABLE');
  assert.match(V.sentence('frontendFiles', f, 'ja'), /将来実装予定/);
  assert.match(V.sentence('frontendFiles', f, 'en'), /Planned for the future/);
  assert.ok(V.T.ja.chipPlanned && V.T.en.chipPlanned);
  assert.ok(/chipPlanned/.test(read('app.js')));
});

test('the name of the list is shown inside the contract check, not above the checks', () => {
  const src = read('app.js');
  assert.ok(/checkBlock\(t\(\)\.checkContracts, t\(\)\.checkContractsHelp, 'contractsNamed', r\.facts\.contractsNamed, intro\)/.test(src));
  const releaseFn = src.slice(src.indexOf('function releaseBlock'));
  assert.ok(releaseFn.indexOf("'list-name'") > releaseFn.indexOf('checkFiles'), 'the list name comes after the file check');
});

test('the source of the code is named concretely, in both languages, and cut like other text', () => {
  const m = V.normalize(result([rel({ sourceDesc: 'S', sourceDescJa: 'あ'.repeat(900) })])).sites[0].releases[0];
  assert.equal(m.sourceDesc, 'S');
  assert.ok(m.sourceDescJa.length <= 200);
  assert.equal(V.normalize(result([rel()])).sites[0].releases[0].sourceDesc, '');
  for (const lang of ['en', 'ja']) assert.ok(V.T[lang].checkFilesHelp.includes('{source}'), 'the file check names its source');
  assert.ok(/replace\('\{source\}'/.test(read('app.js')));
});

test('the title does not claim to be only about contracts, and the vague term is gone', () => {
  assert.ok(!/コントラクト一覧との照合|Contract list check/.test(JSON.stringify(V.T)));
  assert.ok(!/上流の GitHub|upstream GitHub/.test(JSON.stringify(V.T)));
  assert.match(V.T.ja.title, /フロントエンド/);
  assert.match(V.T.en.title, /frontend/i);
  assert.match(V.T.ja.title, /CAW/);
  assert.match(V.T.en.title, /CAW/);
  assert.match(V.T.ja.lead, /CAW/);
  assert.match(V.T.en.lead, /CAW/);
});

test('a link can fill in the address, but never starts the check', () => {
  const src = read('app.js');
  const m = /function prefillFromLink\(\) \{([\s\S]*?)\n  \}\n/.exec(src);
  assert.ok(m, 'prefillFromLink exists');
  assert.ok(/URLSearchParams/.test(m[1]) && /\.get\('site'\)/.test(m[1]));
  assert.ok(!/startCheck|api\(|fetch\(|innerHTML/.test(m[1]), 'it only fills the box');
  assert.ok(/\.value = v/.test(m[1]) && /length > 300/.test(m[1]));
  assert.ok(/if \(isLocal\) \{ prefillFromLink\(\); return; \}/.test(src), 'only where the box is shown');
  for (const lang of ['en', 'ja']) assert.ok(V.T[lang].prefilled.length > 10);
});

test('opening or pasting a result file is hidden when the check box is shown, and shown otherwise', () => {
  const html = read('index.html'), src = read('app.js'), css = read('style.css');
  assert.ok(/id="loader"/.test(html));
  assert.ok(!/id="loader"[^>]*\shidden/.test(html), 'it must be visible unless the local server answers');
  assert.ok(/\$\('checker'\)\.hidden = false;[\s\S]{0,160}\$\('loader'\)\.hidden = true/.test(src));
  assert.ok(/id="how"/.test(html) && !/id="how"[^>]*\shidden/.test(html));
  assert.ok(/\$\('how'\)\.hidden = true/.test(src), 'the command example is hidden with the box');
  assert.ok(/\.loader\[hidden\]\s*\{\s*display:\s*none/.test(css), 'the hidden attribute must win over the flex layout');
});

test('the list of what the checks show has no line for a row the service does not produce, and the row itself carries the caveat', () => {
  for (const lang of ['en', 'ja']) {
    const t = V.T[lang];
    assert.equal(t.limits.length, 3, 'three lines: addresses, files, who asks');
    assert.ok(!t.limits.some((l) => l.includes(lang === 'ja' ? '一覧にないアドレスの、チェーン上の状態' : 'Chain state of the addresses')), 'no line about the opt-in row');
  }
  assert.match(V.T.ja.namedOnChainHelp, /ノードが実際にそれを使っているかは、分かりません/);
  assert.match(V.T.en.namedOnChainHelp, /nor that a node really uses it/);
});
