// SPDX-License-Identifier: MIT
// Copyright (c) 2026 zinsanjp and contributors
//
// Turns the JSON written by verify_site.py / make_status.py into a plain view model, and words the
// facts in English or Japanese. No DOM, no network: it only reads data it is given. Everything it
// returns is plain text or numbers; the page shows it with textContent.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.CawVerifyView = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var LIMITS = { sites: 200, releases: 50, text: 400, list: 50 };
  var TONES = {
    MATCH: 'ok', PASS: 'ok',
    DIFFERENT: 'differs', FAIL: 'differs',
    INCOMPLETE: 'unknown', UNREADABLE: 'unknown', ERROR: 'unknown', INVALID: 'unknown',
    NOT_AVAILABLE: 'na', SKIPPED: 'na'
  };
  var KEYS = ['frontendFiles', 'contractsNamed', 'contractsOnChain'];
  var OPTIONAL_KEYS = ['namedOnChain']; // absent in older result files
  var ADDR_STATUS = ['same-code', 'other-code', 'no-code', 'unreadable'];

  function isObj(x) { return x !== null && typeof x === 'object' && !Array.isArray(x); }
  function text(x, n) { return typeof x === 'string' ? x.slice(0, n || LIMITS.text) : ''; }
  function int(x) { return typeof x === 'number' && isFinite(x) ? Math.trunc(x) : null; }
  function arr(x) { return Array.isArray(x) ? x.slice(0, LIMITS.list) : []; }

  function addressList(x) {
    return arr(x).map(function (e) {
      return isObj(e) ? { address: text(e.address, 80), label: text(e.label, 120) || null } : null;
    }).filter(Boolean);
  }

  function fact(key, f) {
    var out = { verdict: 'ERROR', tone: 'unknown', reason: '' };
    if (!isObj(f)) { out.reason = 'no result'; return out; }
    var v = text(f.verdict, 20);
    if (!Object.prototype.hasOwnProperty.call(TONES, v)) { out.reason = 'unrecognised result'; return out; }
    out.verdict = v; out.tone = TONES[v]; out.reason = text(f.reason);
    if (key === 'frontendFiles') {
      out.match = int(f.match); out.listed = int(f.listed); out.mismatch = int(f.mismatch);
      out.missing = int(f.missing); out.error = int(f.error);
    } else if (key === 'contractsNamed') {
      out.present = int(f.present); out.required = int(f.required);
      out.missing = addressList(f.missing); out.unexpected = addressList(f.unexpected);
      out.recognized = arr(f.recognized).map(function (s) { return text(s, 120); });
    } else if (key === 'namedOnChain') {
      out.checked = int(f.checked); out.sameCode = int(f.sameCode); out.otherCode = int(f.otherCode);
      out.noCode = int(f.noCode); out.notChecked = int(f.notChecked);
      out.addresses = arr(f.addresses).map(function (e) {
        if (!isObj(e)) return null;
        var st = text(e.status, 20);
        return { address: text(e.address, 80), status: ADDR_STATUS.indexOf(st) >= 0 ? st : 'unreadable',
                 chain: text(e.chain, 8), bytes: int(e.bytes), sameAs: text(e.sameAs, 80) || null };
      }).filter(Boolean);
    } else {
      var sum = 0, s = isObj(f.summary) ? f.summary : {};
      Object.keys(s).forEach(function (k) { var n = int(s[k]); if (n !== null) sum += n; });
      out.checks = sum;
      var ev = isObj(f.codeEvidence) ? f.codeEvidence : {};
      out.built = (int(ev['recompile-identical']) || 0) + (int(ev['recompile-except-metadata']) || 0);
      out.flagged = arr(f.flagged).map(function (e) { return isObj(e) ? text(e.text, 200) : ''; }).filter(Boolean);
    }
    return out;
  }

  function release(r) {
    if (!isObj(r)) return null;
    var pub = isObj(r.publisher) ? r.publisher : {}, src = isObj(r.source) ? r.source : {};
    var facts = isObj(r.facts) ? r.facts : {};
    var out = {
      id: text(r.id, 80), publisher: { name: text(pub.name, 120), kind: text(pub.kind, 20) },
      network: text(r.network, 40),
      source: { repo: text(src.repo, 120), commit: text(src.commit, 40), tagged: src.tagged === true },
      title: text(r.title, 120), titleJa: text(r.titleJa, 120), sourceDesc: text(r.sourceDesc, 200), sourceDescJa: text(r.sourceDescJa, 200),
      lineage: isObj(r.lineage) ? text(r.lineage.note) : '', lineageJa: isObj(r.lineage) ? text(r.lineage.noteJa) : '',
      matched: r.matched === true, incomplete: r.incomplete === true, facts: {}
    };
    KEYS.forEach(function (k) { out.facts[k] = fact(k, facts[k]); });
    OPTIONAL_KEYS.forEach(function (k) { if (isObj(facts[k])) out.facts[k] = fact(k, facts[k]); });
    return out;
  }

  function siteFromResult(name, res) {
    var rels = isObj(res) ? arr(res.releases).slice(0, LIMITS.releases).map(release).filter(Boolean) : [];
    return { site: text(name, 200), error: null, releases: rels };
  }

  // Accepts a status file (kind caw-verify-status), one verify_site.py result, or an array of those.
  function normalize(input) {
    var sites = [], generatedAt = null;
    function addResult(o) {
      if (isObj(o) && Array.isArray(o.releases)) { sites.push(siteFromResult(o.site, o)); return true; }
      return false;
    }
    if (isObj(input) && input.kind === 'caw-verify-status') {
      if (input.schemaVersion !== 1) throw new Error('unsupported status version');
      generatedAt = text(input.generatedAt, 40) || null;
      arr2(input.sites).forEach(function (s) {
        if (!isObj(s)) return;
        if (isObj(s.result)) sites.push(siteFromResult(s.site || s.result.site, s.result));
        else sites.push({ site: text(s.site, 200), error: text(s.error) || 'no result', releases: [] });
      });
    } else if (Array.isArray(input)) {
      input.slice(0, LIMITS.sites).forEach(addResult);
    } else if (!addResult(input)) {
      throw new Error('not a verification result');
    }
    if (!sites.length) throw new Error('no sites in the file');
    return { generatedAt: generatedAt, sites: sites };
  }
  function arr2(x) { return Array.isArray(x) ? x.slice(0, LIMITS.sites) : []; }

  // ---------------------------------------------------------------- wording
  var T = {
    en: {
      title: 'CAW frontend integrity check',
      lead: 'For websites that serve the CAW Protocol (decentralized social network) frontend: compares the frontend files a site serves, and the contract addresses it uses, with published CAW code, and states what was found. It does not say which code is right or which one to trust.',
      unofficial: 'Not an official CAW page. “Same” means the site was found identical to the published code in the ways shown below; it is not a guarantee of safety.',
      generated: 'Results made',
      loadFile: 'Open a result file', paste: 'Paste a result', show: 'Show', pastePlaceholder: 'Paste the JSON printed by verify_site.py --json',
      noStatus: 'No status.json was found next to this page. Open a result file, or paste one.',
      checkLabel: 'Address of the site to check (https:// can be left out)', checkPlaceholder: 'example.org', checkButton: 'Check',
      checking: 'Checking… this takes a few seconds', checkFailed: 'The check could not be completed',
      checkBusy: 'Another check is already running', rateLimited: 'Too many checks in a short time. Please try again in a minute',
      badFile: 'That is not a verification result', tooBig: 'That file is too large',
      aboutRelease: 'The contract list itself (not about this site; the same for every site)',
      checkFiles: 'Frontend file check', checkFilesHelp: 'Checks that the files the site serves are the same as the files built from the code of {source}.',
      checkContracts: 'Contract check', checkContractsHelp: 'Compares the contract addresses written in the site with the list. Addresses that are not in the list are also looked up on the chains.',
      namedOnChain: 'Chain state of the addresses not in the list',
      namedOnChainHelp: 'For addresses written in the site but not in the list: is there contract code on the chains, and is it the same code as one of the list’s contracts. This does not show what a contract does, nor that a node really uses it.',
      releaseChain: 'Contracts of the list on the chains', releaseChainHelp: 'The contracts of the list, compared with what is actually on the chains',
      chainName: { L1: 'Sepolia', L2: 'Base Sepolia', L2b: 'Arbitrum Sepolia' },
      addrSame: '{chain}: same code as the list’s {name}', addrOther: '{chain}: contract code ({bytes} bytes) that is none of the list’s',
      addrNone: 'no contract code on any of the chains', addrUnreadable: 'could not be read', notCheckedMore: '{n} more address(es) were not checked',
      listLabel: 'Compared with', sourceLabel: 'Source', notTagged: 'a version without a tag', tagged: 'a tagged version', network: 'network',
      networkName: { testnet: 'testnet', mainnet: 'mainnet' },
      overallMatch: 'Same as the published code on every check that ran', overallIncomplete: 'Cannot tell (something could not be read)', overallNo: 'Does not match the published code',
      chip: { ok: 'same', differs: 'different', unknown: 'cannot tell', na: 'not compared' }, chipPlanned: 'planned for the future',
      chipRelease: { ok: 'consistent', differs: 'inconsistent', unknown: 'cannot tell', na: 'not checked' },
      siteError: 'This site could not be checked', details: 'details',
      missingAddr: 'In the list, but not written in the site', unexpectedAddr: 'Written in the site, but not in the list', flaggedTitle: 'Checks that were flagged',
      limitsTitle: 'What these checks show, and what they do not',
      limits: [
        'Contract addresses in the site: only the addresses written in the site’s main script (the first JavaScript file it loads) are looked at. This does not show that the files are unchanged, nor what the node’s server side actually reads.',
        'Frontend file check: planned to compare the site’s files with fingerprints of the files built from published code (at present, Gilgamesh’s master branch). There are no such fingerprints yet, so it is not done at present.',
        'A site can answer differently depending on who asks, and a page can build addresses while it runs. These checks cannot tell those cases apart.'
      ],
      howTitle: 'Check a site yourself',
      how: 'python3 verify/verify_site.py https://your-node.example',
      lang: 'Language'
    },
    ja: {
      title: 'CAW フロントエンド整合性検証',
      lead: 'CAW Protocol(分散型SNS)のフロントエンドを配っているサイトについて、サイトが配っているフロントエンドのファイルと、サイトが使っているコントラクトのアドレスを、公開されている CAW のコードと比べて、分かったことを並べます。どのコードが正しいか、どれを信頼すべきかは、判断しません。',
      unofficial: 'CAW の公式ページではありません。「同じ」は、下に書いた点で、公開されているコードと同じだと分かった、という意味で、安全の保証ではありません。',
      generated: '結果を作った時刻',
      loadFile: '結果ファイルを開く', paste: '結果を貼り付け', show: '表示', pastePlaceholder: 'verify_site.py --json が出力した JSON を貼り付けてください',
      noStatus: 'このページと同じ場所に status.json がありません。結果ファイルを開くか、貼り付けてください。',
      checkLabel: '検査するサイトのアドレス(https:// は省略できます)', checkPlaceholder: 'example.org', checkButton: '検査',
      checking: '検査中です。数秒かかります', checkFailed: '検査を最後まで行えませんでした',
      checkBusy: '別の検査をしている最中です', rateLimited: '短い時間に、検査が多すぎます。1 分ほど待って、もう一度お試しください',
      badFile: '検査結果のファイルではありません', tooBig: 'ファイルが大きすぎます',
      aboutRelease: 'コントラクト一覧そのものの検査(サイトとは関係なく、どのサイトでも同じです)',
      checkFiles: 'フロントエンドのファイルチェック', checkFilesHelp: 'サイトが配っているファイルが、{source} のコードをビルドしたファイルと同じかを確かめます。',
      checkContracts: 'コントラクトのチェック', checkContractsHelp: 'サイトに書かれているコントラクトのアドレスを、一覧と比べます。一覧にないアドレスは、チェーン上で何があるかも調べます。',
      namedOnChain: '一覧にないアドレスの、チェーン上の状態',
      namedOnChainHelp: 'サイトに書かれているが、一覧にないアドレスについて、チェーン上にコントラクトのコードがあるか、一覧のコントラクトと同じコードかを調べます。コントラクトが何をするかや、ノードが実際にそれを使っているかは、分かりません。',
      releaseChain: '一覧のコントラクトの、チェーン上の状態', releaseChainHelp: '一覧にあるコントラクトを、チェーン上にある実物と比べます',
      chainName: { L1: 'Sepolia', L2: 'Base Sepolia', L2b: 'Arbitrum Sepolia' },
      addrSame: '{chain}: 一覧の {name} と同じコード', addrOther: '{chain}: 一覧のどれとも違うコード({bytes} バイト)',
      addrNone: 'どのチェーンにもコントラクトのコードがありません', addrUnreadable: '読めませんでした', notCheckedMore: 'ほか {n} 個のアドレスは調べていません',
      listLabel: '比べた一覧', sourceLabel: '出どころ', notTagged: 'タグの付いていない版', tagged: 'タグの付いた版', network: 'ネットワーク',
      networkName: { testnet: 'テストネット', mainnet: 'メインネット' },
      overallMatch: '実施した検査のすべてで、公開コードと同じ', overallIncomplete: '判断できません(読めなかったものがあります)', overallNo: '公開コードとは違います',
      chip: { ok: '同じ', differs: '違う', unknown: '判断できない', na: '比べていない' }, chipPlanned: '将来実装予定',
      chipRelease: { ok: '整合', differs: '不整合', unknown: '判断できない', na: '検査していない' },
      siteError: 'このサイトは検査できませんでした', details: '詳細',
      missingAddr: '一覧にはあるが、サイトに書かれていないアドレス', unexpectedAddr: 'サイトに書かれているが、一覧にないアドレス', flaggedTitle: '指摘された検査',
      limitsTitle: 'この検査で分かること、分からないこと',
      limits: [
        'サイトに書かれたコントラクトのアドレス: サイトの主なスクリプト(最初に読み込まれる JavaScript)に書かれたアドレスだけを見ます。ファイルが書き換えられていないことや、ノードのサーバー側が実際に何を読んでいるかは、分かりません。',
        'フロントエンドのファイルチェック: 公開されているコード(いまは Gilgamesh の master ブランチ)をビルドしたファイルの指紋と、サイトのファイルを比べる予定です。その指紋がまだないので、いまは行っていません。',
        'サイトは、アクセスした相手によって違う内容を返すことができ、ページは動いている間にアドレスを組み立てることもできます。この検査では、それを見分けられません。'
      ],
      howTitle: '自分でサイトを検査する',
      how: 'python3 verify/verify_site.py https://your-node.example',
      lang: '言語'
    }
  };

  function fmt(s, vars) {
    return s.replace(/\{(\w+)\}/g, function (_, k) { return vars[k] === null || vars[k] === undefined ? '?' : String(vars[k]); });
  }

  var S = {
    en: {
      frontendFiles: {
        MATCH: '{match} of the {listed} files in the list are identical',
        DIFFERENT: 'Differs from the files in the list ({mismatch} with different content, {missing} missing from the site)',
        INCOMPLETE: 'Cannot tell: {error} file(s) could not be read',
        NOT_AVAILABLE: 'Cannot be compared yet: there are no fingerprints of the built files so far. Planned for the future'
      },
      contractsNamed: {
        MATCH: 'The site names {present} of the list’s {required} contract addresses, and no others',
        DIFFERENT: 'Different addresses are written in the site: {missingCount} of the list’s addresses are not there, and {unexpectedCount} addresses that are not in the list are',
        UNREADABLE: 'The site could not be read'
      },
      namedOnChain: {
        MATCH: 'All {checked} address(es) not in the list carry the same code as a contract of the list (placed at other addresses)',
        DIFFERENT: 'Of the {checked} address(es) not in the list: {sameCode} with the same code as a contract of the list, {otherCode} with code that is none of the list’s, {noCode} with no code on the chains',
        NOT_AVAILABLE: 'Nothing to look at',
        SKIPPED: 'Not checked this time'
      },
      contractsOnChain: {
        PASS: 'The contracts of the list are consistent with the chains ({checks} checks; {built} contract(s) were rebuilt from public source and are identical to the code on the chain)',
        FAIL: 'What is on the chains differs from the list ({flaggedCount} check(s) flagged)',
        SKIPPED: 'Not checked this time'
      },
      other: 'Cannot tell'
    },
    ja: {
      frontendFiles: {
        MATCH: '一覧にあるファイル {listed} 個のうち、{match} 個が同じです',
        DIFFERENT: '一覧のファイルと違います(内容が違うもの {mismatch} 個、サイトにないもの {missing} 個)',
        INCOMPLETE: '判断できません。{error} 個のファイルを読めませんでした',
        NOT_AVAILABLE: 'まだ比べられません。ビルドしたファイルの指紋が、まだないためです。将来実装予定です'
      },
      contractsNamed: {
        MATCH: '一覧のコントラクト {required} 個のうち {present} 個のアドレスが書かれていて、それ以外のアドレスはありません',
        DIFFERENT: '一覧とは別のアドレスが書かれています。一覧のアドレスのうち {missingCount} 個が書かれておらず、一覧にないアドレスが {unexpectedCount} 個書かれています',
        UNREADABLE: 'サイトを読めませんでした'
      },
      namedOnChain: {
        MATCH: '一覧にないアドレス {checked} 個は、すべて一覧のコントラクトと同じコードです(別の場所に置かれた同じコードです)',
        DIFFERENT: '一覧にないアドレス {checked} 個のうち、一覧のコントラクトと同じコードが {sameCode} 個、一覧のどれとも違うコードが {otherCode} 個、どのチェーンにもコードがないものが {noCode} 個です',
        NOT_AVAILABLE: '調べるものがありません',
        SKIPPED: '今回は調べていません'
      },
      contractsOnChain: {
        PASS: '一覧のコントラクトは、チェーン上の実物と整合しています(検査 {checks} 件。うち {built} 個は、公開されているソースから作り直したコードが、チェーン上のコードと同一でした)',
        FAIL: 'チェーン上の実物が、一覧と違います(指摘された検査 {flaggedCount} 件)',
        SKIPPED: '今回は検査していません'
      },
      other: '判断できません'
    }
  };

  function sentence(key, f, lang) {
    var L = S[lang] || S.en, table = L[key] || {};
    var vars = {};
    Object.keys(f).forEach(function (k) { vars[k] = f[k]; });
    vars.missingCount = Array.isArray(f.missing) ? f.missing.length : null;
    vars.unexpectedCount = Array.isArray(f.unexpected) ? f.unexpected.length : null;
    vars.flaggedCount = Array.isArray(f.flagged) ? f.flagged.length : null;
    var s = table[f.verdict] ? fmt(table[f.verdict], vars) : L.other;
    return f.reason && !table[f.verdict] ? s + ': ' + f.reason : s;
  }

  function addressLine(a, lang) {
    var t = T[lang] || T.en;
    var chain = t.chainName[a.chain] || a.chain;
    var st = a.status === 'same-code' ? fmt(t.addrSame, { chain: chain, name: a.sameAs })
      : a.status === 'other-code' ? fmt(t.addrOther, { chain: chain, bytes: a.bytes })
      : a.status === 'no-code' ? t.addrNone : t.addrUnreadable;
    return a.address + '  ' + st;
  }

  // The chain-state row exists only when the site names addresses that are not in the list.
  // Nothing to look at -> no row. Skipped -> a row only if there are such addresses (so the reader sees it was not looked at).
  function showNamedOnChain(r) {
    var f = r.facts.namedOnChain;
    if (!f || f.verdict === 'NOT_AVAILABLE') return false;
    if (f.verdict === 'SKIPPED') return (r.facts.contractsNamed.unexpected || []).length > 0;
    return true;
  }

  function overall(r, lang) {
    var t = T[lang] || T.en;
    return r.matched ? t.overallMatch : (r.incomplete ? t.overallIncomplete : t.overallNo);
  }

  return { normalize: normalize, sentence: sentence, overall: overall, addressLine: addressLine, showNamedOnChain: showNamedOnChain, T: T, TONES: TONES, KEYS: KEYS, LIMITS: LIMITS };
});
