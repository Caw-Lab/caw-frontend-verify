// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
//
// The contract check of the hosted service: a port of bridge/bridge_check.py. The Python tool is the
// reference; hosted/test checks this port against the same situations. It reads the page of a site
// and the entry script, extracts the contract addresses compiled into it, and compares them with the
// address fingerprint of a published build. It does not talk to any chain.

export class Unreadable extends Error {}
export class Invalid extends Error {}

const ADDR_RE = /0x[0-9a-fA-F]{40}(?![0-9a-fA-F])/g;
const HEX40 = /^0x[0-9a-fA-F]{40}$/;
export const MAX_INDEX = 2 * 1024 * 1024;
export const MAX_SCRIPT = 8 * 1024 * 1024;
export const MAX_PRELOADS_READ = 8;
export const MAX_NOTES = 50;
export const MAX_NOTE_LEN = 300;
export const MAX_LISTED = 100;   // addresses listed in a result; a site can put any number into its script

// Addresses that appear in almost any bundle and say nothing about which deployment is meant.
const GENERIC_EXACT = {
  '0x000000000000000000000000000000000000dead': 'burn address',
  '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee': 'native-token placeholder',
  '0xca11bde05977b3631167028862be2a173976ca11': 'Multicall3',
};

export function genericLabel(addr) {
  const a = addr.toLowerCase();
  if (Object.prototype.hasOwnProperty.call(GENERIC_EXACT, a)) return GENERIC_EXACT[a];
  if (a.startsWith('0x' + '0'.repeat(36))) return 'low address (zero, precompile)';
  if (new RegExp('^0x42' + '0'.repeat(36) + '[0-9a-f]{2}$').test(a)) return 'OP-stack predeploy';
  return null;
}

// All 20-byte hex addresses in a text, lowercased, without the generic ones.
export function extract(text) {
  const out = new Set();
  for (const m of text.matchAll(ADDR_RE)) {
    const a = m[0].toLowerCase();
    if (genericLabel(a) === null) out.add(a);
  }
  return out;
}

function attr(tag, name) {
  const m = new RegExp('\\b' + name + '\\s*=\\s*(?:"([^"]*)"|\'([^\']*)\'|([^\\s>]+))', 'i').exec(tag);
  return m === null ? null : (m[1] || m[2] || m[3] || '');
}

// { entry, preloads, external }: the entry module script, the preloaded module files, and how many scripts are external.
export function pageScripts(html) {
  let entry = null;
  const pre = [];
  let external = 0;
  function local(p) {
    if (p === null) return null;
    if (p.includes('://') || p.startsWith('//')) { external += 1; return null; }
    const segments = p.split('?')[0].split('#')[0].split('/').filter((x) => x !== '' && x !== '.');
    if (segments.includes('..')) throw new Unreadable('a script path points outside the site');
    return segments.join('/');
  }
  for (const m of html.matchAll(/<script\b[^>]*>/gi)) {
    const tag = m[0];
    if ((attr(tag, 'type') || '').toLowerCase() === 'module' && attr(tag, 'src') !== null) {
      const p = local(attr(tag, 'src'));
      if (p && entry === null) entry = p;
    }
  }
  for (const m of html.matchAll(/<link\b[^>]*>/gi)) {
    const tag = m[0];
    if ((attr(tag, 'rel') || '').toLowerCase() === 'modulepreload') {
      const p = local(attr(tag, 'href'));
      if (p && p.endsWith('.js')) pre.push(p);
    }
  }
  return { entry, preloads: pre, external };
}

export function validateFingerprint(fp) {
  const p = [];
  if (fp === null || typeof fp !== 'object' || Array.isArray(fp)) return ['fingerprint is not an object'];
  if (fp.schemaVersion !== 1) p.push('unsupported schemaVersion');
  if (fp.kind !== 'caw-frontend-address-fingerprint') p.push("kind must be 'caw-frontend-address-fingerprint'");
  const a = fp.addresses;
  if (!Array.isArray(a) || a.length === 0) {
    p.push('addresses missing or empty (a fingerprint that checks nothing is refused)');
  } else {
    if (a.some((x) => !(typeof x === 'string' && HEX40.test(x)))) p.push('addresses: not a 20-byte hex address');
    const low = a.filter((x) => typeof x === 'string').map((x) => x.toLowerCase());
    if (new Set(low).size !== low.length) p.push('addresses: duplicates');
    if (low.some((x) => HEX40.test(x) && genericLabel(x) !== null)) p.push('addresses: a generic address says nothing about a deployment');
  }
  const notes = fp.addressNotes;
  if (notes !== undefined && notes !== null) {
    if (typeof notes !== 'object' || Array.isArray(notes) || Object.keys(notes).length > MAX_NOTES) {
      p.push(`addressNotes: must be an object with at most ${MAX_NOTES} entries`);
    } else {
      for (const [k, v] of Object.entries(notes)) {
        const text = (x) => typeof x === 'string' && x.length > 0 && x.length <= MAX_NOTE_LEN;
        const ok = HEX40.test(k) && k === k.toLowerCase() && v !== null && typeof v === 'object' && text(v.en) && text(v.ja);
        if (!ok) { p.push(`addressNotes: '${k.slice(0, 60)}' needs a lowercase address and an 'en' and a 'ja' text of at most ${MAX_NOTE_LEN} characters`); break; }
      }
    }
  }
  return p;
}

const decode = (bytes) => new TextDecoder('utf-8', { fatal: false }).decode(bytes);

// A file that should be a script but is an HTML page (a site that answers every unknown path with its index
// page) holds no addresses, which must not be read as "the site names none of them".
export function looksLikeHtml(bytes) {
  let i = 0;
  if (bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) i = 3;
  while (i < bytes.length && (bytes[i] === 0x20 || bytes[i] === 0x09 || bytes[i] === 0x0d || bytes[i] === 0x0a)) i += 1;
  const head = decode(bytes.subarray(i, i + 16)).toLowerCase();
  return head.startsWith('<!doctype html') || head.startsWith('<html');
}

async function readScript(source, path) {
  const bytes = await source.get(path, MAX_SCRIPT);
  if (looksLikeHtml(bytes)) throw new Unreadable(`${path} answers with an HTML page, not a script (the script is not served at this address)`);
  return decode(bytes);
}

// source.get(path, limit) -> Promise<Uint8Array>; throws Unreadable.
// labels: { address: 'L1.CawProfile' } for the addresses of the fingerprint.
export async function check(source, siteName, fp, labels = {}) {
  const problems = validateFingerprint(fp);
  if (problems.length) throw new Invalid(problems.join('; '));

  const html = decode(await source.get('index.html', MAX_INDEX));
  const { entry, preloads, external } = pageScripts(html);
  if (!entry) throw new Unreadable('index.html has no module entry script');

  const entryAddresses = extract(await readScript(source, entry));
  const all = new Set(entryAddresses);
  const required = new Set(fp.addresses.map((a) => a.toLowerCase()));
  const filesRead = [entry];

  // The preloaded files only matter for the presence of a required address. Read them only when something
  // is still missing, up to a limit; a verdict that rests on files that were not read is not given.
  const stillMissing = () => [...required].filter((a) => !all.has(a));
  let skipped = 0;
  if (stillMissing().length) {
    for (const p of new Set(preloads)) {
      if (p === entry) continue;
      if (!stillMissing().length) break;
      if (filesRead.length - 1 >= MAX_PRELOADS_READ) { skipped += 1; continue; }
      try {
        for (const a of extract(await readScript(source, p))) all.add(a);
        filesRead.push(p);
      } catch (e) {
        if (!(e instanceof Unreadable)) throw e; // a preload that cannot be read only weakens the presence check
      }
    }
  }
  if (stillMissing().length && skipped) {
    throw new Unreadable(`some preloaded files were not read (the hosted service reads at most ${MAX_PRELOADS_READ}); run the check locally`);
  }

  const missing = stillMissing().sort();
  const unexpected = [...entryAddresses].filter((a) => !required.has(a)).sort();
  const present = [...required].filter((a) => all.has(a)).sort();
  const label = (a) => (Object.prototype.hasOwnProperty.call(labels, a) ? labels[a] : null);
  const notes = fp.addressNotes && typeof fp.addressNotes === 'object' ? fp.addressNotes : {};
  const listedEntry = (a) => {
    const e = { address: a, label: label(a) };
    if (Object.prototype.hasOwnProperty.call(notes, a)) { e.note = notes[a].en; e.noteJa = notes[a].ja; }
    return e;
  };
  return {
    tool: 'bridge',
    verdict: !missing.length && !unexpected.length ? 'MATCH' : 'DIFFERENT',
    site: siteName, fingerprint: fp.name ?? null, entry,
    required: required.size, present: present.length,
    missing: missing.map(listedEntry),
    unexpected: unexpected.slice(0, MAX_LISTED).map(listedEntry),
    unexpectedTotal: unexpected.length,
    recognized: present.filter((a) => label(a) !== null).map(label).sort(),
    externalScripts: external,
  };
}

// The same shape as verify/verify_site.py gives for one release when the release has no file manifest and
// the release's own chain check is not run. matched needs the contract check to match.
export function assemble(release, siteName, bridge) {
  const facts = {
    frontendFiles: { verdict: 'NOT_AVAILABLE', reason: 'this release publishes no file manifest' },
    contractsNamed: bridge,
    contractsOnChain: { verdict: 'SKIPPED', reason: 'the release itself is not re-checked each time' },
  };
  const matched = bridge.verdict === 'MATCH';
  const incomplete = ['ERROR', 'INCOMPLETE', 'UNREADABLE'].includes(bridge.verdict);
  return {
    site: siteName,
    releases: [{
      id: release.id, title: release.title ?? null, titleJa: release.titleJa ?? null,
      sourceDesc: release.sourceDesc ?? null, sourceDescJa: release.sourceDescJa ?? null,
      publisher: release.publisher, network: release.network, source: release.source, lineage: release.lineage ?? null,
      facts, matched, incomplete: incomplete && !matched,
    }],
  };
}

// A result for a site that could not be read or checked: never a match.
export function failed(verdict, reason) {
  return { tool: 'bridge', verdict, reason: String(reason).slice(0, 200) };
}
