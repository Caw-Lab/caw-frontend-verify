// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
//
// The page: loads a status file (status.json next to the page, a file the reader opens, or pasted
// JSON), turns it into a view model with render.js and shows it. Every piece of data is put on the page
// with textContent; no HTML is ever built from data. The page reads only its own directory.
(function () {
  'use strict';
  var V = window.CawVerifyView;
  var MAX_BYTES = 5 * 1024 * 1024;
  var state = { model: null, lang: 'en' };

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt !== undefined && txt !== null) e.textContent = txt;
    return e;
  }
  function t() { return V.T[state.lang]; }
  function $(id) { return document.getElementById(id); }

  function guardedStorage(fn) { try { return fn(); } catch (e) { return null; } }

  function chip(tone, key) {
    var table = key === 'contractsOnChain' ? t().chipRelease : t().chip;
    var label = key === 'frontendFiles' && tone === 'na' ? t().chipPlanned : table[tone];
    return el('span', 'chip chip-' + tone, label);
  }

  function addressList(title, items) {
    if (!items.length) return null;
    var d = el('details', 'detail');
    d.appendChild(el('summary', null, title + ' (' + items.length + ')'));
    var ul = el('ul', 'addr');
    items.forEach(function (a) {
      ul.appendChild(el('li', null, a.address + (a.label ? '  ' + a.label : '')));
    });
    d.appendChild(ul);
    return d;
  }

  // The sentence of one fact, with the lists that belong to it (addresses, flagged checks).
  function factBody(key, f) {
    var body = el('div', 'fact-body');
    body.appendChild(el('p', 'fact-text', V.sentence(key, f, state.lang)));
    if (key === 'contractsNamed') {
      var a = addressList(t().missingAddr, f.missing || []);
      var b = addressList(t().unexpectedAddr, f.unexpected || []);
      if (a) body.appendChild(a);
      if (b) body.appendChild(b);
    }
    if (key === 'namedOnChain' && f.addresses && f.addresses.length) {
      var dn = el('details', 'detail');
      dn.appendChild(el('summary', null, t().details + ' (' + f.addresses.length + ')'));
      var un = el('ul', 'addr');
      f.addresses.forEach(function (x) { un.appendChild(el('li', null, V.addressLine(x, state.lang))); });
      dn.appendChild(un);
      body.appendChild(dn);
      if (f.notChecked) body.appendChild(el('p', 'meta', t().notCheckedMore.replace('{n}', String(f.notChecked))));
    }
    if (key === 'contractsOnChain' && f.flagged && f.flagged.length) {
      var d = el('details', 'detail');
      d.appendChild(el('summary', null, t().flaggedTitle + ' (' + f.flagged.length + ')'));
      var ul = el('ul', 'addr');
      f.flagged.forEach(function (x) { ul.appendChild(el('li', null, x)); });
      d.appendChild(ul);
      body.appendChild(d);
    }
    return body;
  }

  // One of the two big checks: a title, its result in a large label, what it compares, and the facts.
  function checkBlock(title, help, key, f, intro) {
    var box = el('section', 'check check-' + f.tone);
    var head = el('div', 'check-head');
    head.appendChild(el('h4', 'check-title', title));
    head.appendChild(chip(f.tone, key));
    box.appendChild(head);
    box.appendChild(el('p', 'check-help', help));
    (intro || []).forEach(function (n) { box.appendChild(n); });
    box.appendChild(factBody(key, f));
    return box;
  }

  function releaseBlock(r) {
    var box = el('section', 'release');
    var head = el('div', 'release-head');
    var tone = r.matched ? 'ok' : (r.incomplete ? 'unknown' : 'differs');
    head.appendChild(el('span', 'overall overall-' + tone, V.overall(r, state.lang)));
    box.appendChild(head);

    // 1. frontend files
    var srcDesc = (state.lang === 'ja' && r.sourceDescJa) ? r.sourceDescJa : (r.sourceDesc || (r.source.repo + ' @ ' + r.source.commit.slice(0, 8)));
    box.appendChild(checkBlock(t().checkFiles, t().checkFilesHelp.replace('{source}', srcDesc), 'frontendFiles', r.facts.frontendFiles));

    // 2. contracts: the addresses in the site against the list, and what is on the chains at the ones not in the list
    // The list that the addresses are compared with belongs to this check, so it is named here.
    var title = (state.lang === 'ja' && r.titleJa) ? r.titleJa : (r.title || r.id);
    var intro = [el('p', 'list-name', t().listLabel + ': ' + title)];
    var src = r.source;
    var sep = '  ·  ';
    intro.push(el('p', 'meta', t().sourceLabel + ': ' + src.repo + ' @ ' + src.commit.slice(0, 8) + sep +
      (src.tagged ? t().tagged : t().notTagged) + sep + t().network + ': ' + (t().networkName[r.network] || r.network)));
    var note = state.lang === 'ja' && r.lineageJa ? r.lineageJa : r.lineage;
    if (note) intro.push(el('p', 'meta', note));
    var c = checkBlock(t().checkContracts, t().checkContractsHelp, 'contractsNamed', r.facts.contractsNamed, intro);
    if (V.showNamedOnChain(r)) {
      var nc = r.facts.namedOnChain;
      var sub = el('div', 'subcheck');
      var sh = el('div', 'subcheck-head');
      sh.appendChild(el('h5', null, t().namedOnChain));
      sh.appendChild(chip(nc.tone, 'namedOnChain'));
      sub.appendChild(sh);
      sub.appendChild(el('p', 'check-help', t().namedOnChainHelp));
      sub.appendChild(factBody('namedOnChain', nc));
      c.appendChild(sub);
    }
    box.appendChild(c);

    // The list's own check is the same for every site; it is shown only when it was run.
    if (r.facts.contractsOnChain.verdict !== 'SKIPPED') {
      box.appendChild(el('h4', 'aside-title', t().aboutRelease));
      box.appendChild(checkBlock(t().releaseChain, t().releaseChainHelp, 'contractsOnChain', r.facts.contractsOnChain));
    }
    return box;
  }

  function siteCard(s) {
    var card = el('article', 'site');
    card.appendChild(el('h2', null, s.site || '(no address)'));
    if (s.error) {
      card.appendChild(el('p', 'site-error', t().siteError + ': ' + s.error));
      return card;
    }
    s.releases.forEach(function (r) { card.appendChild(releaseBlock(r)); });
    return card;
  }

  function renderStatic() {
    var tx = t();
    document.documentElement.lang = state.lang;
    document.title = tx.title;
    $('title').textContent = tx.title;
    $('lead').textContent = tx.lead;
    $('unofficial').textContent = tx.unofficial;
    $('btn-file-label').textContent = tx.loadFile;
    $('paste-label').textContent = tx.paste;
    $('paste-input').placeholder = tx.pastePlaceholder;
    $('btn-show').textContent = tx.show;
    $('limits-title').textContent = tx.limitsTitle;
    $('how-title').textContent = tx.howTitle;
    $('how-cmd').textContent = tx.how;
    $('lang-label').textContent = tx.lang;
    $('check-label').textContent = tx.checkLabel;
    $('check-input').placeholder = tx.checkPlaceholder;
    $('btn-check').textContent = tx.checkButton;
    var ul = $('limits-list');
    ul.textContent = '';
    tx.limits.forEach(function (s) { ul.appendChild(el('li', null, s)); });
    $('lang-en').setAttribute('aria-pressed', String(state.lang === 'en'));
    $('lang-ja').setAttribute('aria-pressed', String(state.lang === 'ja'));
  }

  function renderResults() {
    var host = $('results');
    host.textContent = '';
    if (!state.model) return;
    if (state.model.generatedAt) host.appendChild(el('p', 'generated', t().generated + ': ' + state.model.generatedAt));
    state.model.sites.forEach(function (s) { host.appendChild(siteCard(s)); });
  }

  function message(txt) {
    var m = $('message');
    m.textContent = txt || '';
  }

  function show(json) {
    try {
      state.model = V.normalize(json);
      message('');
    } catch (e) {
      state.model = null;
      message(t().badFile);
    }
    renderResults();
  }

  function parseText(txt) {
    if (txt.length > MAX_BYTES) { message(t().tooBig); return; }
    try { show(JSON.parse(txt)); } catch (e) { state.model = null; renderResults(); message(t().badFile); }
  }

  // Local mode: only when this page is served by verify/serve_local.py on this computer, which answers
  // /api/info. Anywhere else the box stays hidden and the page only shows results it is given.
  var local = { on: false, token: '', busy: false };

  function api(path, opts) {
    opts = opts || {};
    opts.cache = 'no-store'; opts.credentials = 'omit'; opts.redirect = 'error';
    opts.headers = Object.assign({ 'X-Token': local.token }, opts.headers || {});
    return fetch(path, opts).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, status: r.status, body: j }; });
    });
  }

  function setBusy(b) {
    local.busy = b;
    $('btn-check').disabled = b;
    $('check-input').disabled = b;
  }

  function pollJob(id) {
    api('/api/job?id=' + encodeURIComponent(id)).then(function (r) {
      var j = r.body || {};
      if (r.ok && j.state === 'running') {
        message(t().checking + ' (' + (typeof j.elapsed === 'number' ? j.elapsed : 0) + 's)');
        window.setTimeout(function () { pollJob(id); }, 2000);
        return;
      }
      setBusy(false);
      if (r.ok && j.state === 'done') { show(j.result); return; }
      message(t().checkFailed + (typeof j.error === 'string' ? ': ' + j.error.slice(0, 200) : ''));
    }, function () { setBusy(false); message(t().checkFailed); });
  }

  function startCheck() {
    if (local.busy) return;
    var site = $('check-input').value.trim();
    if (!site) return;
    setBusy(true);
    state.model = null; renderResults();
    message(t().checking);
    api('/api/check', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site: site }) }).then(function (r) {
      var j = r.body || {};
      if (r.ok && typeof j.job === 'string') { pollJob(j.job); return; }
      setBusy(false);
      message(r.status === 429 ? t().checkBusy : t().checkFailed + (typeof j.error === 'string' ? ': ' + j.error.slice(0, 200) : ''));
    }, function () { setBusy(false); message(t().checkFailed); });
  }

  function detectLocal(done) {
    var h = location.hostname;
    if (location.protocol !== 'http:' || (h !== '127.0.0.1' && h !== 'localhost')) { done(false); return; }
    api('/api/info').then(function (r) {
      var b = r.body || {};
      if (r.ok && b.local === true && typeof b.token === 'string') {
        local.on = true; local.token = b.token;
        $('checker').hidden = false;
        $('loader').hidden = true; // results are shown directly; opening or pasting a result file is not needed
        $('how').hidden = true; // the box replaces the command example
      }
      done(local.on);
    }, function () { done(false); });
  }

  function setLang(l) {
    state.lang = l;
    guardedStorage(function () { localStorage.setItem('lang', l); });
    renderStatic();
    renderResults();
    if (!state.model && !$('message').textContent) message('');
  }

  function init() {
    var saved = guardedStorage(function () { return localStorage.getItem('lang'); });
    var guess = (navigator.language || '').toLowerCase().indexOf('ja') === 0 ? 'ja' : 'en';
    state.lang = saved === 'ja' || saved === 'en' ? saved : guess;
    renderStatic();

    $('lang-en').addEventListener('click', function () { setLang('en'); });
    $('lang-ja').addEventListener('click', function () { setLang('ja'); });
    $('file-input').addEventListener('change', function (ev) {
      var f = ev.target.files && ev.target.files[0];
      if (!f) return;
      if (f.size > MAX_BYTES) { message(t().tooBig); return; }
      f.text().then(parseText, function () { message(t().badFile); });
    });
    $('btn-show').addEventListener('click', function () { parseText($('paste-input').value); });

    $('btn-check').addEventListener('click', startCheck);
    $('check-input').addEventListener('keydown', function (ev) { if (ev.key === 'Enter') startCheck(); });

    detectLocal(function (isLocal) {
      if (isLocal) return;
      fetch('status.json', { cache: 'no-store', credentials: 'omit', redirect: 'error' }).then(function (r) {
        if (!r.ok) throw new Error('no status file');
        return r.text();
      }).then(parseText, function () { message(t().noStatus); });
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
