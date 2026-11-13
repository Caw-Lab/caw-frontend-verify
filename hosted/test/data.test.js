// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { validateFingerprint } from '../src/check.js';
import DATA from '../src/data.json' with { type: 'json' };

const read = (rel) => JSON.parse(readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8'));

test('src/data.json is what the registry and its files say (an independent recomputation)', () => {
  const reg = read('../../references/releases.json');
  assert.equal(DATA.releases.length, reg.releases.length);
  reg.releases.forEach((r, i) => {
    const d = DATA.releases[i];
    const fp = read('../../references/' + r.frontend.addressFingerprint);
    const ref = read('../../references/' + r.contracts.reference);
    assert.equal(d.id, r.id);
    assert.deepEqual(d.fingerprint.addresses, fp.addresses.map((a) => a.toLowerCase()).sort());
    const labels = {};
    for (const [chain, cs] of Object.entries(ref.contracts)) for (const [name, e] of Object.entries(cs)) {
      const a = e.address.toLowerCase();
      if (d.fingerprint.addresses.includes(a) && !(a in labels)) labels[a] = `${chain}.${name}`;
    }
    assert.deepEqual(d.labels, labels);
    for (const k of ['title', 'titleJa', 'sourceDesc', 'sourceDescJa']) assert.equal(d[k], r[k] ?? null, k);
    assert.deepEqual(d.source, r.source);
    assert.deepEqual(d.publisher, r.publisher);
    assert.deepEqual(validateFingerprint(d.fingerprint), []);
  });
});
