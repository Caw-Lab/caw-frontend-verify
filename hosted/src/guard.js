// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
//
// What the hosted service accepts as a site, and how it reads one. Anyone can type an address, so
// the address is checked hard before any request is made, and the reading is bounded in size and time.

import { Invalid, Unreadable } from './check.js';

const LABEL = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;
const INTERNAL_SUFFIXES = ['.local', '.localhost', '.internal', '.lan', '.home', '.home.arpa', '.corp', '.intranet', '.private', '.test', '.invalid', '.example', '.onion'];
export const MAX_INPUT = 300;

// 'cawnest.com' and 'https://cawnest.com/any/path?x#y' both become 'https://cawnest.com'.
// Throws Invalid with a message that is safe to show to the person who typed it.
export function normalizeSite(input, selfHostname = '') {
  if (typeof input !== 'string') throw new Invalid('give the address of a site');
  const text = input.trim();
  if (!text || text.length > MAX_INPUT) throw new Invalid('give the address of a site');
  if (/[\s\u0000-\u001f\u007f\\]/.test(text) || text.startsWith('/')) throw new Invalid('that is not an address');

  const withScheme = text.includes('://') ? text : 'https://' + text;
  let u;
  try {
    u = new URL(withScheme);
  } catch {
    throw new Invalid('that is not an address');
  }
  if (u.protocol !== 'https:') throw new Invalid('only https:// addresses can be checked');
  if (u.username || u.password) throw new Invalid('an address has no user name or password');
  if (u.port && u.port !== '443') throw new Invalid('only the standard port can be checked');

  const host = u.hostname.toLowerCase().replace(/\.$/, '');
  if (!host || host.length > 253) throw new Invalid('that is not a host name');
  if (host.includes(':') || host.startsWith('[')) throw new Invalid('an IP address cannot be checked; use the site\'s name');
  const labels = host.split('.');
  if (labels.length < 2) throw new Invalid('that is not a public host name');
  if (!labels.every((l) => LABEL.test(l) || /^xn--[a-z0-9-]+$/.test(l))) throw new Invalid('that is not a host name');
  // the last label of a real name has a letter; an all-number ending is an IP address in disguise (127.1, 0x7f.1, 2130706433)
  if (!/[a-z]/.test(labels[labels.length - 1]) || /^0x/.test(labels[labels.length - 1])) throw new Invalid('an IP address cannot be checked; use the site\'s name');
  if (INTERNAL_SUFFIXES.some((s) => host === s.slice(1) || host.endsWith(s))) throw new Invalid('that is not a public host name');
  if (selfHostname && (host === selfHostname.toLowerCase() || host.endsWith('.' + selfHostname.toLowerCase()))) throw new Invalid('this service does not check itself');
  return { origin: 'https://' + host, host };
}

// Reads files of one origin: no redirects, a size limit, a time limit.
export class HttpSource {
  constructor(origin, { fetchImpl = fetch, timeoutMs = 10000, userAgent = 'caw-frontend-verify-hosted/0 (+https://github.com/Zinsanjp/caw-frontend-verify)' } = {}) {
    this.origin = origin;
    // fetch must not be called as a method of this object: the platform refuses ("Illegal invocation")
    this.fetchImpl = (...args) => fetchImpl(...args);
    this.timeoutMs = timeoutMs;
    this.userAgent = userAgent;
    this.requests = 0;
  }

  async get(path, limit) {
    this.requests += 1;
    const url = `${this.origin}/${path.replace(/^\/+/, '')}`;
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), this.timeoutMs);
    try {
      let resp;
      try {
        resp = await this.fetchImpl(url, {
          method: 'GET', redirect: 'manual', signal: ctl.signal,
          headers: { 'user-agent': this.userAgent, accept: '*/*' },
        });
      } catch (e) {
        throw new Unreadable(`${path}: ${e && e.name === 'AbortError' ? 'timed out' : 'could not be reached'}`);
      }
      if (resp.type === 'opaqueredirect' || (resp.status >= 300 && resp.status < 400)) {
        throw new Unreadable(`${path} redirected (enter the address the site answers at)`);
      }
      if (resp.status < 200 || resp.status >= 300) throw new Unreadable(`${path} answered HTTP ${resp.status}`);
      const declared = resp.headers.get('content-length');
      if (declared && /^\d+$/.test(declared) && Number(declared) > limit) throw new Unreadable(`${path} declares more than ${limit} bytes`);
      if (!resp.body) return new Uint8Array(0);

      const reader = resp.body.getReader();
      const chunks = [];
      let total = 0;
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          total += value.length;
          if (total > limit) {
            await reader.cancel().catch(() => {});
            throw new Unreadable(`${path} is larger than ${limit} bytes`);
          }
          chunks.push(value);
        }
      } catch (e) {
        if (e instanceof Unreadable) throw e;
        throw new Unreadable(`${path}: ${e && e.name === 'AbortError' ? 'timed out' : 'could not be read'}`);
      }
      const out = new Uint8Array(total);
      let off = 0;
      for (const c of chunks) { out.set(c, off); off += c.length; }
      return out;
    } finally {
      clearTimeout(timer);
    }
  }
}

// ---------------------------------------------------------------- where a name points
// A name can look ordinary and still point at a private or loopback address (127.0.0.1.nip.io). Before
// anything is fetched, the name is looked up (DNS over HTTPS) and refused unless every address it
// points at is a public one. This is a second line: the platform does not let a Worker reach private
// networks either. A name that changes its answer between this look-up and the request is not caught here.

function v4ToInt(s) {
  const m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/.exec(s);
  if (!m) return null;
  const o = m.slice(1).map(Number);
  if (o.some((x) => x > 255)) return null;
  return ((o[0] * 256 + o[1]) * 256 + o[2]) * 256 + o[3];
}

export function isPublicIPv4(s) {
  const n = v4ToInt(s);
  if (n === null) return false;
  const blocks = [
    ['0.0.0.0', 8], ['10.0.0.0', 8], ['100.64.0.0', 10], ['127.0.0.0', 8], ['169.254.0.0', 16], ['172.16.0.0', 12],
    ['192.0.0.0', 24], ['192.0.2.0', 24], ['192.88.99.0', 24], ['192.168.0.0', 16], ['198.18.0.0', 15],
    ['198.51.100.0', 24], ['203.0.113.0', 24], ['224.0.0.0', 4], ['240.0.0.0', 4],
  ];
  for (const [base, bits] of blocks) {
    const b = v4ToInt(base);
    const size = 2 ** (32 - bits);
    if (n >= b && n < b + size) return false;
  }
  return true;
}

function parseIPv6(s) {
  let t = s.toLowerCase();
  if (t.includes('%')) return null;
  const v4 = /(\d{1,3}(?:\.\d{1,3}){3})$/.exec(t);
  if (v4) {
    const n = v4ToInt(v4[1]);
    if (n === null) return null;
    t = t.slice(0, v4.index) + ((n >>> 16) & 0xffff).toString(16) + ':' + (n & 0xffff).toString(16);
  }
  const halves = t.split('::');
  if (halves.length > 2) return null;
  const head = halves[0] ? halves[0].split(':') : [];
  const tail = halves.length === 2 && halves[1] ? halves[1].split(':') : [];
  const fill = 8 - head.length - tail.length;
  if (halves.length === 2 ? fill < 1 : fill !== 0) return null;
  const parts = [...head, ...Array(halves.length === 2 ? fill : 0).fill('0'), ...tail];
  if (parts.length !== 8 || parts.some((p) => !/^[0-9a-f]{1,4}$/.test(p))) return null;
  return parts.map((p) => parseInt(p, 16));
}

export function isPublicIPv6(s) {
  const h = parseIPv6(s);
  if (h === null) return false;
  if (h.every((x) => x === 0)) return false;                              // ::
  if (h.slice(0, 7).every((x) => x === 0) && h[7] === 1) return false;    // ::1
  if (h[0] === 0 && h.slice(1, 5).every((x) => x === 0) && h[5] === 0xffff) {   // ::ffff:a.b.c.d (mapped)
    return isPublicIPv4(`${h[6] >> 8}.${h[6] & 255}.${h[7] >> 8}.${h[7] & 255}`);
  }
  if ((h[0] & 0xffc0) === 0xfe80) return false;                           // fe80::/10 link-local
  if ((h[0] & 0xfe00) === 0xfc00) return false;                           // fc00::/7 unique local
  if ((h[0] & 0xff00) === 0xff00) return false;                           // multicast
  if (h[0] === 0x2001 && h[1] === 0x0db8) return false;                   // documentation
  if (h[0] === 0x0064 && h[1] === 0xff9b) return false;                   // NAT64 (embeds an IPv4 address)
  if (h[0] === 0x2002) return false;                                      // 6to4 (embeds an IPv4 address)
  if (h[0] === 0x0100 && h[1] === 0 && h[2] === 0 && h[3] === 0) return false;   // discard prefix
  return (h[0] & 0xe000) === 0x2000;                                      // only global unicast 2000::/3
}

// Throws Invalid when the name does not resolve or points at a non-public address; Unreadable when the look-up fails.
export async function requirePublicResolution(host, fetchImpl = fetch, timeoutMs = 5000) {
  const found = [];
  for (const [type, code] of [['A', 1], ['AAAA', 28]]) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), timeoutMs);
    let data;
    try {
      const r = await fetchImpl(`https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(host)}&type=${type}`, {
        headers: { accept: 'application/dns-json' }, redirect: 'manual', signal: ctl.signal,   // the platform has no 'error' mode
      });
      if (!r.ok) throw new Error('bad status');   // a redirect is not an answer either
      data = await r.json();
    } catch {
      throw new Unreadable('the name could not be looked up');
    } finally {
      clearTimeout(timer);
    }
    if (data && data.Status === 3) throw new Invalid('that name does not exist');
    for (const a of (data && Array.isArray(data.Answer) ? data.Answer : [])) {
      if (a && a.type === code && typeof a.data === 'string') found.push([type, a.data]);
    }
  }
  if (!found.length) throw new Invalid('that name does not point at any address');
  for (const [type, ip] of found) {
    if (!(type === 'A' ? isPublicIPv4(ip) : isPublicIPv6(ip))) throw new Invalid('that name points at a non-public address');
  }
}
