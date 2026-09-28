/*
 * Mirror — Gate 6 customer app. A RENDERER of the validated mirror.app/1.0 contract.
 *
 * Rules this file keeps (x-frontend-rules):
 *   - every sentence, date, amount, status and label comes from the payload or the server's gated vocabulary;
 *   - it never computes or adjusts an amount, date, deadline or status (dates and numbers are only FORMATTED;
 *     relative wording comes only from days_left; horizon positions are layout);
 *   - it never strengthens an evidence class, never hides an "if", never drops SIMULATED, never shows a balance;
 *   - all text goes in through textContent: nothing from the payload is ever parsed as HTML.
 */
'use strict';

const TOKEN = document.querySelector('meta[name="mirror-token"]').content;
const $ = (id) => document.getElementById(id);
const S = {
  meta: null, vocab: null, p: null, prev: null, view: 'now', busy: false,
  forgotten: false, history: null, focus: null, open: new Set(), scenario: 'rerouted', justResolved: new Set(), editing: null,
};
const VIEWS = [
  { id: 'now', label: 'Now', color: 'var(--t-now)', icon: ['o.o', '.x.', 'o.o'] },
  { id: 'ahead', label: 'Ahead', color: 'var(--t-ahead)', icon: ['..x', '.xo', 'xo.'] },
  { id: 'household', label: 'Household', color: 'var(--t-home)', icon: ['.x.', 'xxx', 'xox'] },
  { id: 'know', label: 'What we know', color: 'var(--t-know)', icon: ['xxx', 'xox', '.x.'] },
];
// which evidence class a closure rests on (display only; the basis itself comes from the engine)
const BASIS_CLASS = { you_told_us: 'U', seen_in_data: 'O', rule_implied: 'I', source_record: 'O' };
const CLS_NAME = { O: 'Seen in your bank data', R: 'Published rule', I: 'Our reading', U: 'Only you can tell us' };

/* ---------------------------------------------------------------- DOM helpers */
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'style') el.style.cssText = v;          // CSSOM: allowed by the page's CSP (style attributes are not)
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return el;
}
const NS = 'http://www.w3.org/2000/svg';   // the SVG namespace name: an identifier, never fetched
function s(tag, attrs, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v != null) el.setAttribute(k, v);
  for (const k of kids.flat(Infinity)) if (k != null) el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  return el;
}
/* pixel-grid marks: 'x' = colour, 'o' = colour at low opacity */
function pix(rows, color, size = 22) {
  const n = rows.length, c = size / n, g = c * 0.16;
  const kids = [];
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (ch === '.') return;
    kids.push(s('rect', { x: x * c + g / 2, y: y * c + g / 2, width: c - g, height: c - g, rx: c * 0.12,
      fill: color, 'fill-opacity': ch === 'o' ? 0.3 : 1 }));
  }));
  return s('svg', { width: size, height: size, viewBox: `0 0 ${size} ${size}`, 'aria-hidden': 'true' }, kids);
}
const LOGO = ['x..o', '.xo.', '.ox.', 'o..x'];
// one small line glyph per kind of line or card — the same stroke language as the tick, arrow and chevron
// (pixel marks are kept for identity and navigation: the logo, the tabs, Ask Mirror)
const KIND_GLYPH = {
  ATTENTION: { d: ['M7 2.6v5.6'], dot: [7, 11.2], color: 'var(--attn)', label: 'Needs attention' },
  RESOLVED: { d: ['M2.8 7.4 5.7 10.2 11.2 4.2'], color: 'var(--o)', label: 'Closed' },
  CHANGE: { d: ['M1.8 7.6c1.7-3.2 3.5-3.2 5.2 0s3.5 3.2 5.2 0'], color: 'var(--i)', label: 'Changed' },
  DOOR: { d: ['M2.5 7h8.5', 'M8 3.8 11.2 7 8 10.2'], color: 'var(--r)', label: 'Worth checking' },
  QUESTION: { d: ['M4.8 4.9a2.3 2.3 0 1 1 3.4 2c-.8.4-1.2 1-1.2 1.8v.3'], dot: [7, 11.4], color: 'var(--u)', label: 'A question for you' },
  FACT: { d: [], dot: [7, 7], r: 2.4, color: 'var(--ink-2)', label: 'Noted' },
  LEARNED: { d: ['M7 3.2a3.8 3.8 0 1 1 0 7.6a3.8 3.8 0 1 1 0-7.6'], color: 'var(--ink-2)', label: 'Learned' },
  NOTE: { d: ['M4 7h6'], color: 'var(--muted)', label: '' },
};
function glyphSvg(g) {
  return s('svg', { width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true' },
    g.d.map((d) => s('path', { d, fill: 'none', stroke: g.color, 'stroke-width': 1.7, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' })),
    g.dot ? s('circle', { cx: g.dot[0], cy: g.dot[1], r: g.r || 1.05, fill: g.color }) : null);
}
const CARD_GLYPH = { CLOCK: 'ATTENTION', DOOR: 'DOOR', QUESTION: 'QUESTION', SUPPRESSION: 'NOTE' };
function kindGlyph(kind, speak = false) {
  const g = KIND_GLYPH[kind] || KIND_GLYPH.NOTE;
  const mark = h('span', { class: 'k', 'aria-hidden': 'true', title: g.label || null }, glyphSvg(g));
  return speak && g.label ? [mark, h('span', { class: 'sr-only' }, `${g.label}: `)] : mark;
}
function arrowIcon(color = 'currentColor') {
  return s('svg', { width: 16, height: 16, viewBox: '0 0 16 16', 'aria-hidden': 'true' },
    s('path', { d: 'M3 8h9M8.5 4.5 12 8l-3.5 3.5', fill: 'none', stroke: color, 'stroke-width': 1.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
}
function chevron() {
  return s('svg', { class: 'chev', width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true' },
    s('path', { d: 'M3 5.5 7 9.5l4-4', fill: 'none', stroke: 'currentColor', 'stroke-width': 1.6, 'stroke-linecap': 'round' }));
}
function tick(color = 'var(--o)') {
  return s('svg', { width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true' },
    s('path', { d: 'M3 7.4 5.8 10 11 4.4', fill: 'none', stroke: color, 'stroke-width': 1.8, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }));
}

/* ---------------------------------------------------------------- formatting only (never arithmetic on claims) */
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtDate(iso) {
  if (!iso) return '';
  const [y, m, d] = String(iso).split('-').map(Number);
  return d ? `${d} ${MON[m - 1]} ${y}` : `${MON[m - 1]} ${y}`;
}
function dayMon(iso) { const [, m, d] = iso.split('-').map(Number); return { d, m: MON[m - 1] }; }
function inr(n) {
  if (n == null) return '';
  const frac = Math.abs(n % 1) > 0.001;
  return '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: frac ? 2 : 0, maximumFractionDigits: 2 });
}
function ordinal(d) { const t = d % 100; const s1 = (t > 10 && t < 14) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[d % 10] || 'th'); return d + s1; }
function humanise(code) { return code.toLowerCase().replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()); }
function evLabel(code) { return (S.vocab.evidence_labels || {})[code] || humanise(code); }
function short(sha) { return sha ? `${sha.slice(0, 4)}…${sha.slice(-3)}` : ''; }

/* ---------------------------------------------------------------- API */
async function api(path, body) {
  const opt = body === undefined ? { cache: 'no-store' } : {
    method: 'POST', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', 'X-Mirror-Token': TOKEN }, body: JSON.stringify(body),
  };
  const r = await fetch(path, opt);
  let j = null;
  try { j = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw new Error((j && j.error) || `Mirror could not do that (${r.status})`);
  return j;
}
async function act(path, body, after) {
  if (S.busy) return;
  S.busy = true; busy(true);
  try {
    const res = await api(path, body);
    S.meta = await api('/api/meta');
    S.history = await api('/api/history').catch(() => S.history);
    if (res && res.state === 'forgotten') { S.forgotten = true; S.p = null; render(); }
    else if (res && res.contract) { accept(res); if (after) after(res); }
    else if (after) after(res);
  } catch (e) {
    toast(e.message, true);
  } finally {
    S.busy = false; busy(false);
  }
}
function busy(on) { $('progress').classList.toggle('on', on); }
function accept(p) {
  S.prev = S.p; S.p = p; S.forgotten = false;
  const before = new Set((S.prev ? S.prev.now.resolved : []).map((r) => r.card_id));
  S.justResolved = new Set(p.now.resolved.map((r) => r.card_id).filter((id) => S.prev && !before.has(id)));
  render();
}

let toastTimer = null;
function toast(msg, err = false) {
  const t = $('toast');
  t.replaceChildren(err ? '' : tick('#9fe0b7'), msg);
  t.setAttribute('role', err ? 'alert' : 'status');
  t.classList.toggle('err', err); t.classList.add('on');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('on'), 3200);
}

/* ---------------------------------------------------------------- shell */
/* Hindi: an editorial accent on two page heads only (lang="hi"). English stays the functional language for
   navigation, evidence, actions, numbers and trust information — so WHAT WE KNOW and AHEAD carry none. */
const HI = {
  now: 'इस घड़ी',                       // "at this hour" — घड़ी is also the clock the NOW card is built around
  household: 'घर की आर्थिक तस्वीर',     // "the household's financial picture"
};
function hiLine(text) { return h('p', { class: 'hi hi-line', lang: 'hi' }, text); }
function pageHead(title, hi, lede) {
  return h('div', { class: 'page-head' }, h('h1', { class: 'page-title', tabindex: '-1' }, title), hi ? hiLine(hi) : null,
    lede ? h('p', { class: 'page-lede' }, lede) : null, modeChips());
}
function modeChips() {
  const g = S.p.generated;
  const chips = [
    S.meta.corpus_source === 'live'
      ? h('span', { class: 'chip live', title: 'Fetched through this app from the Anumati sandbox during this session' }, h('span', { class: 'dot' }), S.meta.corpus_label)
      : h('span', { class: 'chip recorded', title: S.meta.corpus_is_e8 ? 'The bank data is one recorded, hash-sealed AA sandbox fetch' : 'The bank data is one recorded AA sandbox fetch' }, h('span', { class: 'dot' }), S.meta.corpus_label),
    h('span', { class: 'chip replay', title: 'Real data, replayed time' }, `REPLAY · as of ${fmtDate(g.as_of)}`),
    h('span', { class: 'chip sim', title: 'The LPG record path runs on a schema-true SIMULATED record' }, 'SIMULATED LPG'),
    S.meta.demo_login ? h('span', { class: 'chip sim', title: 'Opened with a demo number for a sandbox household; not authentication' }, 'DEMO LOGIN') : null,
  ];
  return h('div', { class: 'chips' }, chips);
}
function renderTop() {
  const top = $('topbar');
  top.replaceChildren(
    h('div', { class: 'brand' }, pix(LOGO, 'var(--ink)', 20), h('span', null, 'Mirror'),
      S.p && !inJourney() ? h('span', { class: 'brand-sub' }, (S.meta && S.meta.household && S.meta.household.label) || 'SELA household') : null),
    h('div', { class: 'top-actions' },
      h('button', { class: 'icon-btn only-mobile', type: 'button', onclick: openOperator, 'aria-label': 'Replay controls' },
        pix(['x.x', '.x.', 'x.x'], 'var(--muted)', 12), 'Replay')),
  );
}
function renderTabs() {
  const nav = $('tabbar');
  nav.replaceChildren(...VIEWS.map((v) => h('button', {
    class: 'tab', type: 'button', 'aria-current': S.view === v.id ? 'page' : null,
    onclick: () => go(v.id),
  }, pix(v.icon, S.view === v.id ? 'var(--ink)' : 'var(--faint)', 22), v.label)));
}
function go(view) {
  if (view === S.view) { $('scroller').scrollTo({ top: 0 }); return; }
  S.view = view; S.pendingFocus = 'h1';
  const el = $('view');
  el.classList.add('leaving');
  setTimeout(() => { el.classList.remove('leaving'); $('scroller').scrollTo({ top: 0, behavior: 'instant' }); render(); }, 150);
}
function inJourney() {
  const c = S.meta && S.meta.connect;
  if (!c) return false;
  if (c.entry === 'login') return true;                 // --demo-login: the phone-entry screen
  if (!c.enabled) return false;
  if (c.entry === 'connect') return true;
  return !!(S.connect && S.connect.state === 'ready' && S.meta.corpus_source === 'live' && !S.connectDone);
}
function render(opts = {}) {
  const before = document.activeElement;
  renderTop(); renderTabs(); renderRails();
  const view = $('view');
  const fab = $('fab');
  const journey = inJourney();
  $('tabbar').hidden = journey;
  const c = S.connect;
  const screen = journey ? `j:${c && c.state === 'ready' ? 'ready' : (c && JOURNEY_ACTIVE.includes(c.state) ? 'wait' : S.phase || 'welcome')}` : `v:${S.view}`;
  if (screen !== S.lastScreen) { $('scroller').scrollTo({ top: 0, behavior: 'instant' }); S.lastScreen = screen; }
  if (journey) {
    fab.hidden = true;
    view.replaceChildren(connectView());
  } else if (S.forgotten || !S.p) {
    fab.hidden = true;
    view.replaceChildren(S.forgotten ? forgottenView() : startView());
  } else {
    fab.hidden = false;
    fab.replaceChildren(pix(['x.x', '.x.', 'x.x'], '#9fe0b7', 16), 'Ask Mirror');
    const v = { now: nowView, ahead: aheadView, household: householdView, know: knowView }[S.view]();
    view.replaceChildren(v);
  }
  if (!opts.quiet) { view.style.animation = 'none'; void view.offsetWidth; view.style.animation = ''; }
  // a keyboard or screen-reader user must not be dropped on <body> when the view is rebuilt
  if ((S.pendingFocus || (before && before !== document.body && !document.contains(before))) && $('sheet').hidden) {
    const want = S.pendingFocus === 'h1' ? null : S.focus;
    const t = (want && document.querySelector(`[data-card="${want}"] .card-title`)) || document.querySelector('#view h1');
    if (t) { if (!t.hasAttribute('tabindex')) t.setAttribute('tabindex', '-1'); t.focus({ preventScroll: true }); }
  }
  S.pendingFocus = null;
}

/* ---------------------------------------------------------------- the Mirror card */
function badge(cls, text, extra = '') {
  return h('span', { class: `badge ${cls} ${extra}` }, h('i', { class: `mk ${cls}` }), text);
}
function clsDots(classes) {
  return h('span', { class: 'cls-dots', 'aria-hidden': 'true', title: classes.map((c) => CLS_NAME[c]).join(' · ') }, classes.map((c) => h('i', { class: `mk ${c}` })));
}
function isQuestionLine(card, line) {
  return card.question && line.startsWith(card.question.question) && line.includes('[');
}
function card(c, opts = {}) {
  const hero = !!opts.hero, compact = !!opts.compact;
  const expanded = hero || S.open.has(c.id);
  const lines = c.body.filter((l) => !isQuestionLine(c, l));
  const shown = expanded ? lines : lines.slice(0, 1);
  const el = h('article', {
    class: `card ${hero ? 'hero' : ''} ${compact ? 'compact' : ''} ${c.simulated ? 'sim' : ''}`,
    'data-card': c.id,
  });
  const inner = h('div', { class: 'card-inner' },
    h('div', { class: 'card-meta' },
      h('span', { class: `kind ${c.type}` }, kindGlyph(CARD_GLYPH[c.type]), S.vocab.kind_labels[c.type] || c.type,
        h('span', { class: 'who' }, ` · ${c.member}`)),
      c.simulated ? h('span', { class: 'chip sim' }, 'SIMULATED') : h('span', { class: 'since' }, `since ${fmtDate(c.first_seen)}`)),
    h(opts.level || (hero ? 'h2' : 'h3'), { class: 'card-title' }, c.title),
    h('div', { class: 'card-body' }, shown.map((l, i) => h('p', { class: i === 0 ? 'lede' : null }, l))),
  );
  if (expanded) {
    if (c.deadline) inner.append(clock(c.deadline));
    if (c.action) inner.append(h('div', { class: 'action' }, arrowIcon('var(--ink)'),
      h('div', null, h('strong', null, c.action.action_text),
        h('span', null, "You act in the institution's own channel. Mirror never moves money."))));
    if (c.question) inner.append(questionBlock(c));
    inner.append(h('div', { class: 'card-built' }, clsDots(c.evidence_classes),
      'Built from: ' + c.evidence_classes.map((k) => CLS_NAME[k]).join(' · ')));
    inner.append(whyBlock(c));
  } else {
    inner.append(h('button', {
      class: 'more-btn', type: 'button',
      onclick: () => { S.open.add(c.id); S.focus = c.id; render(); requestAnimationFrame(() => scrollToCard(c.id)); },
    }, c.question ? 'Answer this' : 'Read more', arrowIcon()));
  }
  el.append(inner);
  return el;
}
function clock(d) {
  const passed = d.days_left < 0;
  return h('div', { class: 'clock' },
    h('div', { class: 'clock-num' }, passed ? '—' : String(d.days_left),
      h('small', null, passed ? (d.conditional ? 'passed, if as assumed' : 'passed') : (d.days_left === 1 ? 'day' : 'days'))),
    h('div', null,
      h('div', { class: 'clock-date' }, `Around ${fmtDate(d.date)}`),
      d.conditional ? h('div', { class: 'clock-if' },
        h('em', { class: 'clock-cond' }, 'A conditional date. It depends on what only you can tell us:'),
        h('ul', null, d.depends_on_text.map((t) => h('li', null, t)))) : null,
      h('div', { class: 'clock-rule' }, badge('R', `Published rule · ${d.rules.join(', ')}`))));
}
function questionBlock(c) {
  const q = c.question;
  const said = S.p.what_we_know.facts.filter((f) => f.card_id === c.id);      // answers the engine kept (payload)
  const box = h('div', { class: 'question' },
    h('p', { class: 'question-text' }, q.question),
    said.length ? h('div', { class: 'answered-note' }, tick(), `You told us: ${said[said.length - 1].answer} (${fmtDate(said[said.length - 1].stated_on)}). You can still change it.`) : null,
    h('div', { class: 'options' }, q.options.map((o) => h('button', {
      class: 'opt', type: 'button',
      onclick: (e) => answer(c, o, e.currentTarget),
    }, o.label))),
    h('div', { class: 'fine mt8' }, "Your answer is kept as “You told us”. It never becomes “seen in your bank data”."));
  return box;
}
function answer(c, o, btn) {
  S.focus = c.id; S.pendingFocus = 'card';
  btn.classList.add('chosen');
  btn.parentElement.querySelectorAll('.opt').forEach((b) => { b.disabled = true; });
  const el = document.querySelector(`[data-card="${c.id}"]`);
  act('/api/answers', { answers: [{ card_id: c.id, option: o.id }] }, (p) => {
    const closed = p.now.resolved.find((r) => r.card_id === c.id);
    S.focus = c.id;
    if (closed) {
      toast(`Closed — ${closed.basis_label}`);
      if (S.view === 'now') requestAnimationFrame(() => document.querySelector('.resolved li.new')?.scrollIntoView({ behavior: smooth(), block: 'center' }));
    } else {
      toast('Noted — kept as “You told us”');
      requestAnimationFrame(() => document.querySelector(`[data-card="${c.id}"]`)?.classList.add('flash'));
    }
  });
  if (el) el.classList.add('flash');
}
function whyBlock(c) {
  const open = S.open.has('why:' + c.id);
  const btn = h('button', { class: 'why-btn', type: 'button', 'aria-expanded': String(open) },
    h('span', null, 'Why am I seeing this?'), chevron());
  const reveal = h('div', { class: `reveal ${open ? 'open' : ''}` }, h('div', null, ledger(c)));
  btn.addEventListener('click', () => {
    const now = !reveal.classList.contains('open');
    reveal.classList.toggle('open', now);
    btn.setAttribute('aria-expanded', String(now));
    if (now) { S.open.add('why:' + c.id); S.focus = c.id; } else S.open.delete('why:' + c.id);
  });
  return h('div', null, btn, reveal);
}
function ledger(c) {
  let n = 0;
  const steps = [];
  for (const g of S.vocab.chain_groups) {
    const items = c.why.filter((w) => w.class === g.class);
    if (!items.length) continue;
    const answeredAll = g.class === 'U' && items.every((w) => w.answered);
    steps.push(h('div', { class: `step ${g.class}`, style: `animation-delay:${n++ * 70}ms` },
      h('span', { class: 'step-node' }),
      h('div', { class: 'step-head' }, answeredAll ? S.vocab.badges.U_answered : g.heading),
      items.map(evidenceItem)));
  }
  const result = [];
  if (c.deadline) result.push(h('div', { class: 'ev' },
    h('div', { class: 'ev-label' }, `${c.deadline.conditional ? 'A conditional date' : 'A date'}: around ${fmtDate(c.deadline.date)}`),
    c.deadline.conditional ? h('div', { class: 'ev-sub' }, 'It depends on what only you can tell us: ' + c.deadline.depends_on_text.join('; ')) : null));
  if (c.question) result.push(h('div', { class: 'ev' },
    h('div', { class: 'ev-label' }, 'A question instead of a claim'), h('div', { class: 'ev-sub' }, c.question.question)));
  if (!result.length) result.push(h('div', { class: 'ev' }, h('div', { class: 'ev-label' }, c.title)));
  steps.push(h('div', { class: 'step result', style: `animation-delay:${n * 70}ms` },
    h('span', { class: 'step-node' }), h('div', { class: 'step-head' }, 'What Mirror concludes'), result));
  return h('div', { class: 'ledger' }, steps);
}
function evidenceItem(w) {
  const box = h('div', { class: 'ev' });
  if (w.class === 'R') {
    box.append(h('div', { class: 'ev-label' }, w.rule_name || evLabel(w.code)),
      w.citation ? h('div', { class: 'ev-quote' }, w.citation) : null,
      h('div', { class: 'ev-sub' }, `${w.rule}${w.last_verified ? ' · checked ' + fmtDate(w.last_verified) : ''}${w.source ? ' · ' + w.source : ''}`));
    return box;
  }
  box.append(h('div', { class: 'ev-label' }, evLabel(w.code)));
  if (w.class === 'U') {
    box.append(h('div', { class: 'ev-sub' }, w.answered
      ? `You told us: ${w.answer} (${fmtDate(w.stated_on)})` : 'Bank data cannot show this — we ask instead of guessing.'));
  }
  if (w.class === 'O' && w.mode) {
    box.append(h('div', { class: 'mt8' }, badge(w.simulated ? 'S' : 'O', w.badge)),
      h('div', { class: 'ev-sub' }, `Request ${w.request_ref}`));
  }
  if (w.txn_ids && w.txn_ids.length) {
    const refs = h('div', { class: 'mono', hidden: true }, w.txn_ids.join(' · '));
    const n = w.txn_ids.length;
    box.append(h('div', { class: 'ev-sub' }, w.class === 'O' ? `${n} ${n === 1 ? 'row' : 'rows'} in the bank data` : `Uses ${n} ${n === 1 ? 'row' : 'rows'} of bank data`),
      h('button', { class: 'ev-toggle', type: 'button', onclick: (e) => { refs.hidden = !refs.hidden; e.currentTarget.textContent = refs.hidden ? 'Show references' : 'Hide references'; } }, 'Show references'),
      refs);
  } else if (w.class === 'O' && !w.mode) {
    box.append(h('div', { class: 'ev-sub' }, w.detail));
  }
  return box;
}
function smooth() { return matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'; }
function scrollToCard(id) {
  const el = document.querySelector(`[data-card="${id}"]`);
  if (el) el.scrollIntoView({ behavior: smooth(), block: 'start' });
}

/* ---------------------------------------------------------------- NOW */
function nowView() {
  const p = S.p, now = p.now, b = now.since_last_time;
  const cards = now.cards;
  const clocks = cards.filter((c) => c.type === 'CLOCK');
  const doors = cards.filter((c) => c.type === 'DOOR');
  const questions = cards.filter((c) => c.type === 'QUESTION');
  const hero = clocks[0];
  const root = h('div', null,
    pageHead('Now', HI.now));

  if (hero) {
    root.append(h('div', { class: 'section flush' }, card(hero, { hero: true })));
  } else {
    root.append(h('div', { class: 'section flush' }, h('div', { class: 'calm' },
      h('div', { class: 'eyebrow' }, 'No clock open'),
      h('div', { class: 'big' }, b.silent ? 'Nothing needs you.' : 'Here is what changed.'),
      h('div', { class: 'note' }, questions.length ? `${questions.length} question${questions.length === 1 ? '' : 's'} below, only if you want to answer.` : 'Mirror stays quiet until something in the data or a published rule needs you.'))));
  }

  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, b.since ? `Since ${fmtDate(b.since)}` : 'First look'),
    h('p', { class: 'section-sub' }, 'What changed, in the order it matters. Every line points at evidence.'),
    h('ul', { class: 'brief' }, b.lines.map((l) => h('li', null,
      kindGlyph(l.kind, true),
      h('div', null, h('div', { class: 'txt' }, l.text),
        h('div', { class: 'basis' }, l.evidence_classes.length ? clsDots(l.evidence_classes) : null, l.basis_label || null,
          l.card_id && cards.some((c) => c.id === l.card_id) && (!hero || l.card_id !== hero.id)
            ? h('button', { class: 'go', type: 'button', onclick: () => { S.open.add(l.card_id); render(); requestAnimationFrame(() => scrollToCard(l.card_id)); } }, 'Open') : null))))),
    b.more ? h('p', { class: 'fine' }, `…and ${b.more} more, lower in priority.`) : null));

  if (clocks.length > 1) root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Also running'), clocks.slice(1).map((c) => card(c, { compact: true }))));

  if (doors.length) root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Worth checking'),
    h('p', { class: 'section-sub' }, 'Government protections that run on the same bank rails. Only a bank, post office or insurer can enrol anyone.'),
    h('div', { class: 'rail-scroll' }, doors.map(doorTile))));

  if (questions.length) root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Questions for you'),
    h('p', { class: 'section-sub' }, 'Where the bank data cannot know, Mirror asks instead of guessing.'),
    questions.map((c) => card(c, { compact: true }))));

  if (now.resolved.length) root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Closed'),
    h('p', { class: 'section-sub' }, 'Each one says why it closed — and on whose word.'),
    h('ul', { class: 'resolved' }, now.resolved.map((r) => h('li', { class: S.justResolved.has(r.card_id) ? 'new' : null },
      h('span', { class: 'tick' }, tick()),
      h('div', null, h('div', { class: 't' }, r.title), h('div', { class: 'd' }, r.text),
        h('div', { class: 'mt8' }, badge(r.simulated ? 'S' : (BASIS_CLASS[r.basis] || 'O'), r.basis_label),
          h('span', { class: 'fine' }, `  ${fmtDate(r.closed_on)}`)),
        r.simulated ? h('div', { class: 'callout mt8' }, S.vocab.lpg_disclosure) : null))))));

  if (b.lines.some((l) => l.kind !== 'ROUTINE')) root.append(previewSection());
  root.append(provenance());
  return root;
}
function doorTile(c) {
  return h('button', { class: 'door', type: 'button', onclick: () => openCardSheet(c) },
    h('div', { class: 'door-top' }, h('span', { class: 'tag' }, S.vocab.kind_labels.DOOR), pix(['x.x', 'xxx', 'x.x'], 'var(--r)', 34)),
    h('div', { class: 'door-body' }, h('div', { class: 't' }, c.title), h('div', { class: 's' }, `${c.member} · tap to see why`)));
}
function previewSection() {
  const np = S.vocab.notification_preview;
  const open = S.open.has('preview');
  const btn = h('button', { class: 'why-btn', type: 'button', 'aria-expanded': String(open) }, h('span', null, 'How would the household hear about this?'), chevron());
  const reveal = h('div', { class: `reveal ${open ? 'open' : ''}` }, h('div', null,
    h('div', { class: 'preview mt12' },
      h('div', { class: 'from' }, pix(LOGO, '#f3f1ec', 14), 'Mirror', h('span', { class: 'chip sim', style: 'margin-left:auto' }, np.badge)),
      h('div', { class: 'bubble' }, np.text),
      h('div', { class: 'not' }, 'This message never contains: ' + np.does_not_contain.join(', ') + '.')),
    h('p', { class: 'fine mt8' }, 'Preview only. Nothing is sent from this prototype; the message says that something changed, and the app says what.')));
  btn.addEventListener('click', () => { const o = !reveal.classList.contains('open'); reveal.classList.toggle('open', o); btn.setAttribute('aria-expanded', String(o)); o ? S.open.add('preview') : S.open.delete('preview'); });
  return h('div', { class: 'section' }, btn, reveal);
}
function provenance() {
  const g = S.p.generated;
  return h('div', { class: 'footer-prov' },
    `${g.authored_by} · engines ${g.engines.protect} / ${g.engines.unlock} · rulebook ${g.rulebook_version} · corpus ${short(g.corpus_sha256)} · ${S.p.contract}`);
}

/* ---------------------------------------------------------------- AHEAD */
function aheadView() {
  const a = S.p.ahead;
  const root = h('div', null, pageHead('Ahead', null,
    `The next ${a.days} days, ${fmtDate(a.from)} – ${fmtDate(a.to)}. Only what repeats reliably, and rule dates with their “if”.`));
  if (a.pressure_points.length) root.append(h('div', { class: 'section flush' },
    a.pressure_points.map((pp) => h('div', { class: 'pressure' },
      h('div', { class: 'card-meta' }, badge('I', CLS_NAME.I), h('span', { class: 'since' }, pp.severity === 'LIKELY_SHORT' ? 'likely short' : 'could be tight')),
      h('div', { class: 't' }, pp.text),
      pp.conditions && pp.conditions.length ? h('ul', null, pp.conditions.map((c) => h('li', null, c))) : null))));
  root.append(h('div', { class: 'section' + (a.pressure_points.length ? '' : ' flush') },
    h('h2', { class: 'section-title' }, 'The horizon'), horizonStrip(a),
    h('ul', { class: 'agenda mt16' }, a.items.map(agendaRow))));
  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'What Mirror never projects'),
    h('p', { class: 'section-sub' }, 'Left out on purpose, so nothing on this page is a guess dressed up as a date.'),
    h('ul', { class: 'brief' }, a.not_projected.map((n) => h('li', null, kindGlyph('NOTE'),
      h('div', null, h('div', { class: 'txt' }, [n.member, n.what].filter(Boolean).join(' · ')), h('div', { class: 'basis' }, n.why)))))));
  root.append(provenance());
  return root;
}
function agendaRow(it) {
  const f = dayMon(it.date_from);
  const range = it.date_to && it.date_to !== it.date_from ? `to ${fmtDate(it.date_to)}` : null;
  return h('li', { class: it.kind },
    h('div', { class: 'day' }, String(f.d), h('span', { class: 'mon' }, f.m), range ? h('span', { class: 'range' }, range) : null),
    h('div', null, h('div', { class: 'txt' }, it.text),
      h('div', { class: 'row' }, badge(it.evidence_class, CLS_NAME[it.evidence_class]),
        it.conditional_on ? h('span', { class: 'fine' }, 'depends on: ' + it.conditional_on.map(evLabel).join('; ').toLowerCase()) : null),
      (it.notes || []).map((n) => h('div', { class: 'fine mt8' }, n))));
}
function horizonStrip(a) {
  const W = 340, pad = 8, from = Date.parse(a.from), to = Date.parse(a.to);
  const x = (iso) => pad + (Math.min(Math.max(Date.parse(iso), from), to) - from) / (to - from) * (W - 2 * pad);   // layout only
  const members = [...new Set(a.items.map((i) => i.member))];
  const drawn = Math.max(240, ($('view').clientWidth || 350) - 40);                      // layout only
  const fz = 12 * (parseFloat(getComputedStyle(document.documentElement).fontSize) / 16) * (W / drawn);
  const rowH = 34, top = fz + 10, H = top + members.length * rowH + fz + 10;
  const kids = [];
  const ticks = [];
  for (let t = from; t <= to; t += 7 * 864e5) ticks.push(new Date(t).toISOString().slice(0, 10));
  ticks.forEach((iso) => {
    kids.push(s('line', { class: 'hz-tick', x1: x(iso), x2: x(iso), y1: top - 6, y2: H - fz - 8 }));
    const f = dayMon(iso);
    kids.push(s('text', { class: 'hz-date', x: x(iso), y: H - 2, 'font-size': fz.toFixed(2), 'text-anchor': 'middle' }, `${f.d} ${f.m}`));
  });
  a.pressure_points.forEach((pp) => kids.push(s('rect', { class: 'hz-band', x: x(pp.date) - 5, y: top - 8, width: 10, height: H - top - fz - 4, rx: 3 })));
  members.forEach((m, i) => {
    const y = top + i * rowH + rowH / 2;
    kids.push(s('text', { class: 'hz-who', x: 0, y: top + i * rowH + 4, 'font-size': fz.toFixed(2) }, m));
    kids.push(s('line', { class: 'hz-lane', x1: pad, x2: W - pad, y1: y, y2: y }));
    a.items.filter((it) => it.member === m).forEach((it) => {
      const x1 = x(it.date_from), x2 = x(it.date_to || it.date_from);
      if (it.kind === 'REGULAR_CREDIT_DAYS') kids.push(s('rect', { class: 'hz-credit', x: x1 - 3, y: y - 4, width: Math.max(x2 - x1, 0) + 6, height: 8, rx: 4 }));
      else if (it.kind === 'DEADLINE') kids.push(s('rect', { class: 'hz-deadline', x: x1 - 6, y: y - 6, width: 12, height: 12, transform: `rotate(45 ${x1} ${y})` }));
      else if (it.kind === 'RENEWAL') kids.push(s('rect', { class: 'hz-renewal', x: x1 - 5, y: y - 5, width: 10, height: 10, rx: 2 }));
      else kids.push(s('rect', { class: 'hz-collect', x: x1 - 5, y: y - 5, width: 10, height: 10, rx: 2.5 }));
    });
  });
  return h('div', { class: 'horizon' },
    s('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'The next 30 days, drawn from the items listed below' }, kids),
    h('div', { class: 'hz-legend' },
      h('span', null, hzMark('collect'), 'usual collection'),
      h('span', null, hzMark('credit'), 'usual credit days'),
      h('span', null, hzMark('deadline'), 'rule date, with its “if”'),
      a.items.some((it) => it.kind === 'RENEWAL') ? h('span', null, hzMark('renewal'), 'renewal') : null,
      a.pressure_points.length ? h('span', null, hzMark('band'), 'could be tight') : null));
}
function hzMark(kind) {
  const shape = {
    collect: s('rect', { class: 'hz-collect', x: 2, y: 2, width: 10, height: 10, rx: 2.5 }),
    credit: s('rect', { class: 'hz-credit', x: 0, y: 3, width: 14, height: 8, rx: 4 }),
    deadline: s('rect', { class: 'hz-deadline', x: 3, y: 3, width: 8, height: 8, transform: 'rotate(45 7 7)' }),
    renewal: s('rect', { class: 'hz-renewal', x: 2, y: 2, width: 10, height: 10, rx: 2 }),
    band: s('rect', { class: 'hz-band', x: 4, y: 0, width: 6, height: 14, rx: 2, style: null }),
  }[kind];
  return s('svg', { width: 14, height: 14, viewBox: '0 0 14 14', 'aria-hidden': 'true' }, shape);
}

/* ---------------------------------------------------------------- OUR HOUSEHOLD */
function householdView() {
  const hh = S.p.our_household;
  const root = h('div', null, pageHead('Our household', HI.household,
    'How the money actually moves, learned from the accounts you connected — no balances, no scores.'));
  root.append(h('div', { class: 'section flush' }, h('div', { class: 'rail-scroll', tabindex: '0', role: 'region', 'aria-label': 'Household members' }, hh.members.map((m) => h('div', { class: 'member-card' },
    h('div', { class: 'n' }, m.display_name), h('div', { class: 'a' }, m.account),
    h('div', { class: 'note mt8' }, `Data from ${fmtDate(m.data_from)} to ${fmtDate(m.data_until)}`),
    h('span', { class: 'status-pill' }, m.status === 'watched' ? 'watched' : `not used — ${m.not_used_reason || ''}`))))));

  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Regular collections'),
    h('p', { class: 'section-sub' }, 'Recognised after three sightings on a steady day. Month by month, as the bank data shows them.'),
    hh.commitments.map(laneCard),
    h('div', { class: 'legend-row' },
      h('span', null, h('i', { class: 'pip', 'aria-hidden': 'true' }), 'collected'),
      h('span', null, h('i', { class: 'pip returned', 'aria-hidden': 'true' }), 'returned'),
      h('span', null, h('i', { class: 'pip not', 'aria-hidden': 'true' }), 'not collected'),
      h('span', null, h('i', { class: 'pip notdue', 'aria-hidden': 'true' }), 'not yet due'),
      h('span', null, h('i', { class: 'pip nodata', 'aria-hidden': 'true' }), 'no data'))));

  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Regular credits'),
    hh.regular_credits.map((c) => h('div', { class: 'lane-card' },
      h('div', { class: 'lane-top' }, h('div', { class: 'lane-name' }, c.label), badge('O', CLS_NAME.O)),
      h('div', { class: 'lane-sub' }, `${c.member} · usually the ${ordinal(c.usual_days[0])}–${ordinal(c.usual_days[1])} · seen in ${c.months_seen} months`),
      c.notes.map((n) => h('div', { class: 'fine mt8' }, n)))),
    h('div', { class: 'block mt12' },
      h('div', { class: 'eyebrow' }, 'Other money coming in'),
      Object.entries(hh.other_credit_sources).map(([who, n]) => h('div', { class: 'mt8' },
        h('strong', null, who), ` · ${n} irregular credit source${n === 1 ? '' : 's'}, never projected and never called income`)))));

  root.append(protectionsSection(hh.protections));

  if (hh.visual_data && hh.visual_data.pay_cycle.length) root.append(payCycle(hh.visual_data));

  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Bank charges seen'),
    h('p', { class: 'section-sub' }, 'The small footprints that sometimes mark a payment that failed.'),
    hh.charges.map((c) => h('div', { class: 'scheme' },
      h('div', { class: 'n' }, `${c.member} · ${c.label}`), h('div', { class: 'lane-amt' }, inr(c.total)),
      h('div', { class: 's' }, `${c.count} ${c.count === 1 ? 'charge' : 'charges'}`)))));
  root.append(provenance());
  return root;
}
const LANE_CLASS = { collected: '', returned: 'returned', 'not collected': 'not', 'no data': 'nodata', 'not yet due': 'notdue' };
function laneCard(c) {
  const days = c.usual_days[0] === c.usual_days[1] ? `the ${ordinal(c.usual_days[0])}` : `the ${ordinal(c.usual_days[0])}–${ordinal(c.usual_days[1])}`;
  return h('div', { class: 'lane-card' },
    h('div', { class: 'lane-top' }, h('div', { class: 'lane-name' }, c.label), h('div', { class: 'lane-amt' }, inr(c.last_amount))),
    h('div', { class: 'lane-sub' }, `${c.member} · ${c.cadence.toLowerCase()} · usually around ${days}`),
    h('div', { class: 'lane', role: 'list', 'aria-label': `${c.label}, month by month` }, c.lane.map((o) => {
      const said = `${fmtDate(o.period)}: ${o.status}${o.amount ? ' · ' + inr(o.amount) : ''}`;
      return h('div', { class: 'cell', role: 'listitem', title: said, 'aria-label': said },
        h('span', { class: `pip ${LANE_CLASS[o.status] ?? ''}`, 'aria-hidden': 'true' }), h('span', { class: 'm', 'aria-hidden': 'true' }, MON[Number(o.period.slice(5)) - 1][0]));
    })),
    h('span', { class: `status-pill ${c.status.startsWith('gap') ? 'gap' : ''}` }, c.status));
}
function protectionsSection(pr) {
  const sec = h('div', { class: 'section' }, h('h2', { class: 'section-title' }, 'Government protections'));
  if (!pr.switched_on) {
    sec.append(h('p', { class: 'section-sub' }, pr.text),
      h('button', { class: 'btn', type: 'button', onclick: () => confirmPurpose('GOV_PROTECT') }, 'Switch on the check'));
    if (S.meta.options) sec.append(optionsLink());
    return sec;
  }
  sec.append(h('p', { class: 'section-sub' }, 'What the bank data shows for each member, with where each line comes from.'));
  pr.members.forEach((m) => sec.append(h('div', { class: 'scheme-group' },
    h('div', { class: 'eyebrow' }, m.member),
    m.schemes.map((x) => h('div', { class: 'scheme' },
      h('div', { class: 'n' }, x.label),
      badge(x.badge && x.badge.startsWith('SIMULATED') ? 'S' : x.evidence_class, x.badge),
      h('div', { class: 's' }, x.status_text))))));
  if (pr.context.length) sec.append(h('div', { class: 'mt16' }, pr.context.map((c) => h('div', { class: 'block' },
    h('div', { class: 'card-meta' }, h('span', { class: 'eyebrow' }, c.what), badge(c.simulated ? 'S' : c.evidence_class, c.badge)),
    h('div', null, c.text),
    c.simulated ? h('div', { class: 'callout mt8' }, S.vocab.lpg_disclosure) : null))));
  if (pr.not_shown.length) {
    const d = h('details', { class: 'details mt16' }, h('summary', null, `Checked, not shown (${pr.not_shown.length})`, chevron()));
    pr.not_shown.forEach((c) => d.append(h('div', { class: 'block mt8' }, h('div', { class: 'eyebrow' }, c.member), h('h3', null, c.title), c.body.map((l) => h('p', { class: 'note' }, l)))));
    sec.append(d);
  }
  if (S.meta.options) sec.append(optionsLink());
  return sec;
}
function payCycle(vd) {
  const byMember = {};
  vd.pay_cycle.forEach((r) => (byMember[r.member] = byMember[r.member] || []).push(r));
  const sec = h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Month by month'),
    h('p', { class: 'section-sub' }, 'Collections the pattern expected (outline) against collections made (filled).'),
    h('div', { class: 'feeds' }, badge('I', 'Expected · ' + CLS_NAME.I), badge('O', 'Made · ' + CLS_NAME.O)));
  for (const [who, rows] of Object.entries(byMember)) {
    const used = rows.filter((r) => r.collections_expected > 0);
    if (!used.length) continue;
    const max = Math.max(...used.map((r) => r.collections_expected));                       // layout scale only
    sec.append(h('div', { class: 'block' }, h('h3', null, who),
      h('div', { class: 'cycle' }, used.map((r) => h('div', { class: 'cycle-row' },
        h('span', { class: 'mo' }, fmtDate(r.month)),
        h('div', { class: 'bars', title: `expected ${inr(r.collections_expected)} · collected ${inr(r.collections_made)}` },
          h('span', { class: 'bar exp', style: `width:${(r.collections_expected / max) * 100}%` }),
          r.collections_made > 0 ? h('span', { class: 'bar made', style: `width:calc(${(r.collections_made / max) * 100}% - 6px)` }) : null),
        h('span', { class: 'in' }, `expected ${inr(r.collections_expected)} · collected ${inr(r.collections_made)} · money in ${inr(r.money_in)}`)))),
      vd.pay_cycle_notes.map((n) => h('div', { class: 'fine mt8' }, n))));
  }
  return sec;
}

/* ---------------------------------------------------------------- WHAT WE KNOW */
function knowView() {
  const k = S.p.what_we_know;
  const root = h('div', null, pageHead('What we know', null,
    'Why Mirror knows each thing, what it read, and how to make it forget.'));
  root.append(h('div', { class: 'section flush' }, h('div', { class: 'quick' },
    h('button', { type: 'button', onclick: () => document.getElementById('k-told')?.scrollIntoView({ behavior: smooth() }) }, 'Why does Mirror know this?', h('span', null, 'What you told us · the rules')),
    h('button', { type: 'button', onclick: () => document.getElementById('k-read')?.scrollIntoView({ behavior: smooth() }) }, 'What did Mirror access?', h('span', null, 'Data read · lookups · forgetting')))));

  // data read
  const aa = k.sources[0];
  root.append(h('div', { class: 'section', id: 'k-read' },
    h('h2', { class: 'section-title' }, 'What Mirror read'),
    sessionConsentBlock(),
    h('div', { class: 'block' },
      h('div', { class: 'card-meta' }, h('span', { class: 'eyebrow' }, 'Account Aggregator'), h('span', { class: S.meta.corpus_source === 'live' ? 'chip live' : 'chip recorded' }, S.meta.corpus_label)),
      h('h3', null, aa.name),
      h('dl', { class: 'kv' }, h('dt', null, 'Type'), h('dd', null, aa.fi_type), h('dt', null, 'Mode'), h('dd', null, aa.mode),
        h('dt', null, 'Fingerprint'), h('dd', { class: 'mono' }, short(aa.corpus_sha256))),
      aa.accounts.map((a) => h('div', { class: 'scheme' }, h('div', { class: 'n' }, `${a.member} · ${a.account}`),
        h('span', { class: 'fine' }, a.used ? 'used' : 'not used'),
        h('div', { class: 's' }, `${fmtDate(a.data_from)} to ${fmtDate(a.data_until)}`)))),
    k.sources.slice(1).map((src) => h('div', { class: 'block' },
      h('div', { class: 'card-meta' }, h('span', { class: 'eyebrow' }, 'Second DPI source'), src.mode.includes('simulated') ? h('span', { class: 'chip sim' }, 'SIMULATED') : null),
      h('h3', null, src.name),
      src.records.map((r) => h('div', { class: 'fine' }, `${fmtDate(r.on)} · ${r.mode} · ${r.status}${r.reason ? ' · ' + r.reason : ''}`))))));

  // consent terms
  const c = k.consent;
  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Your AA consent'),
    h('p', { class: 'section-sub' }, `As configured: ${c.terms_source}.`),
    h('div', { class: 'block' }, h('dl', { class: 'kv' },
      [['Rail', c.rail], ['Purpose', `${c.purpose_code} · ${c.purpose_text}`], ['Data', c.fi_types.join(', ')], ['Fetch', c.fetch_type],
        ['How often', c.frequency], ['Kept for', c.data_life], ['Looks back', c.data_range], ['Ends', c.expiry],
        ['Status', c.status ? `${c.status} (${c.status_source})` : 'not part of this replay']].map(([a, b]) => [h('dt', null, a), h('dd', null, b)])))));

  // purposes
  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, "What you've switched on"),
    h('p', { class: 'section-sub' }, 'Each purpose is separate. Switching one off forgets what it used — from this laptop, not just the screen.'),
    k.purposes.map(purposeBlock)));

  // told us
  root.append(h('div', { class: 'section', id: 'k-told' },
    h('h2', { class: 'section-title' }, 'What you told us'),
    h('p', { class: 'section-sub' }, 'Kept as “You told us” — never turned into “seen in your bank data”. Household facts can be changed here; an account question can be answered again on its card while it is open.'),
    !k.household_facts.length && !k.facts.length ? h('p', { class: 'note' }, 'Nothing yet.') : null,
    k.household_facts.map(factBlock),
    k.facts.map((f) => h('div', { class: 'block' },
      h('div', { class: 'fact-q' }, f.question), h('div', { class: 'fact-a' }, f.answer),
      h('div', { class: 'mt8' }, badge('U', S.vocab.badges.U_answered), h('span', { class: 'fine' }, `  ${fmtDate(f.stated_on)}`)))),
    k.corrections.length ? h('div', { class: 'block' }, h('h3', null, 'Corrections'), k.corrections.map((x) => h('div', { class: 'scheme' },
      h('div', { class: 'n' }, `${x.member} · ${evLabel(x.fact)}`), h('span', { class: 'fine' }, fmtDate(x.stated_on)),
      h('div', { class: 's' }, `${x.before} → ${x.after}`)))) : null));

  // access log
  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Who looked at your data'),
    h('p', { class: 'section-sub' }, 'Every outside lookup and every forgetting. A forgotten lookup keeps only that it happened.'),
    k.access_log.length ? h('ul', { class: 'log' }, k.access_log.map(logRow)) : h('p', { class: 'note' }, 'No outside lookups for this household. Mirror has only read the connected bank data above.'),
    liveLookups().length ? h('div', { class: 'mt16' }, h('div', { class: 'eyebrow' }, "Live lookups on a holder's own ID — never joined"),
      h('ul', { class: 'log' }, liveLookups().map(liveLogRow))) : null));

  // DPI integration
  root.append(dpiSection(k.dpi_integrations[0]));

  // rules
  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'Rules Mirror applies'),
    h('p', { class: 'section-sub' }, 'Published by regulators, insurers and schemes. Each is versioned and was checked on the date shown.'),
    k.rules_in_use.map((r) => h('details', { class: 'block details' },
      h('summary', null, h('span', null, r.name), chevron()),
      h('div', { class: 'ev-quote mt8' }, r.citation),
      h('div', { class: 'fine mt8' }, `${r.rule} · checked ${fmtDate(r.last_verified)} · ${r.source}`)))));

  // limits
  root.append(h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'What Mirror cannot see'),
    h('ul', { class: 'brief' }, k.limits.map((l) => h('li', null, kindGlyph('NOTE'), h('div', { class: 'txt' }, l))))));

  // stop & forget
  root.append(h('div', { class: 'section', id: 'k-stop' },
    h('h2', { class: 'section-title' }, 'Stop and forget'),
    h('p', { class: 'section-sub' }, 'Deletes everything Mirror saved for this household on this laptop: answers, records, closures and history. It needs no extra verification. Your AA consent itself is revoked in your AA app.'),
    h('button', { class: 'btn danger', type: 'button', onclick: confirmErase }, 'Stop and forget')));
  root.append(provenance());
  return root;
}
function purposeBlock(p) {
  const switchable = S.meta.switchable.includes(p.purpose);
  const gov = S.p.generated.purposes_on.includes('GOV_PROTECT');
  const disabled = !switchable || (p.purpose === 'DPI_LPG_CHECK' && !gov && !p.on);
  const sw = switchable ? h('button', {
    class: 'switch', role: 'switch', type: 'button', 'aria-checked': String(p.on), 'aria-label': p.label, disabled: disabled || null,
    onclick: () => (p.on ? setPurpose(p.purpose, false) : (p.purpose === 'DPI_LPG_CHECK' ? confirmLpg() : confirmPurpose(p.purpose))),
  }) : h('span', { class: 'lock' }, 'follows your AA consent');
  return h('div', { class: 'block' },
    h('div', { class: 'purpose' }, h('div', null, h('h3', null, p.label), h('div', { class: 'fine' }, `${p.granted_through} · ${p.status_source}`)), sw),
    h('details', { class: 'details' }, h('summary', null, 'What it uses, and never uses', chevron()),
      h('div', { class: 'eyebrow mt8' }, 'Uses'), h('ul', { class: 'list' }, p.uses.map((u) => h('li', null, u))),
      h('div', { class: 'eyebrow mt8' }, 'Never uses'), h('ul', { class: 'list' }, p.never_uses.map((u) => h('li', null, u))),
      h('div', { class: 'eyebrow mt8' }, 'To stop'), h('p', { class: 'note' }, p.withdraw)));
}
function factBlock(f) {
  const editing = S.editing === f.id;
  return h('div', { class: 'block' },
    h('div', { class: 'fact-row' },
      h('div', null, h('div', { class: 'fact-q' }, `${f.member} · ${evLabel(f.fact)}${f.scheme ? ' · ' + f.scheme : ''}`), h('div', { class: 'fact-a' }, f.answer)),
      h('button', { class: 'icon-btn', type: 'button', onclick: () => { S.editing = editing ? null : f.id; render(); } }, editing ? 'Cancel' : 'Change')),
    h('div', { class: 'mt8' }, badge('U', f.badge), h('span', { class: 'fine' }, `  said on ${fmtDate(f.stated_on)}`)),
    h('div', { class: 'feeds' }, h('span', { class: 'fine' }, 'Feeds:'), f.feeds_rules.map((r) => badge('R', r))),
    h('p', { class: 'note mt8' }, f.why),
    editing ? h('div', { class: 'options mt12' }, f.options.map((o) => h('button', {
      class: `opt ${o.id === f.value ? 'chosen' : ''}`, type: 'button', disabled: o.id === f.value || null,
      onclick: () => act('/api/facts', { account: f.account, code: f.fact, scheme: f.scheme, value: o.id }, () => { S.editing = null; toast('Corrected — the old answer is kept in history'); render(); }),
    }, o.label))) : null);
}
function purposeLabel(id) {
  const p = S.p && S.p.what_we_know.purposes.find((x) => x.purpose === id);
  return p ? p.label : 'a purpose';
}
function outcomeText(e) {
  if (e.outcome === 'ok') return 'record received';
  if (e.outcome === 'refused') return 'refused before any call';
  return "we couldn't check";
}
function logRow(e) {
  if (e.what === 'forgotten') {
    const f = e.forgot || {};
    const parts = [['answer', 'answers', f.answers], ['record', 'records', f.records], ['closed item', 'closed items', f.closed_items]]
      .filter(([, , n]) => typeof n === 'number').map(([one, many, n]) => `${n} ${n === 1 ? one : many}`);
    return h('li', null, h('div', { class: 'when' }, fmtDate(e.on)),
      h('div', null, h('div', null, `Forgotten — you switched off “${purposeLabel(e.purpose)}”`),
        parts.length ? h('div', { class: 'fine mt8' }, 'Removed: ' + parts.join(' · ')) : null,
        h('div', { class: 'fine' }, 'The log keeps only that it happened.')));
  }
  const sim = e.mode === 'simulated';
  return h('li', null, h('div', { class: 'when' }, fmtDate(e.on)),
    h('div', null,
      h('div', null, e.source_label || e.source || e.what),
      h('div', { class: 'mt8' }, e.mode && e.mode !== 'n/a' ? badge(sim ? 'S' : 'O', e.mode.toUpperCase()) : null,
        h('span', { class: 'fine' }, `  ${outcomeText(e)}${e.outcome !== 'ok' && e.reason ? ' · ' + e.reason : ''}`)),
      e.fields_kept && e.fields_kept.length ? h('div', { class: 'fine mt8' }, `Kept ${e.fields_kept.length} fields: ${e.fields_kept.join(', ')}`) : null,
      e.fields_dropped && e.fields_dropped.length ? h('div', { class: 'fine' }, `Dropped on arrival: ${e.fields_dropped.length} fields`) : null,
      e.redacted ? h('div', { class: 'fine' }, `Redacted: ${e.redacted}`) : null));
}
function liveLookups() { return (S.history && S.history.standalone_live_lookups) || []; }
function liveLogRow(e) {
  return h('li', null, h('div', { class: 'when' }, fmtDate(e.on)),
    h('div', null, h('div', null, e.source_label),
      h('div', { class: 'mt8' }, h('span', { class: 'chip live' }, 'LIVE · NOT JOINED'),
        h('span', { class: 'fine' }, `  ${outcomeText(e)}${e.outcome !== 'ok' && e.reason ? ' · ' + e.reason : ''}`)),
      h('div', { class: 'fine mt8' }, `A holder's own ID ending ${e.lpg_id_last4 || '—'}. Shown on its own; never part of this household.`)));
}
function dpiSection(d) {
  const sec = h('div', { class: 'section' },
    h('h2', { class: 'section-title' }, 'The second DPI source'),
    h('p', { class: 'section-sub' }, d.role));
  const status = d.live_lookup_for_this_household;
  sec.append(h('div', { class: 'block' }, h('h3', null, d.name),
    h('dl', { class: 'kv' }, h('dt', null, 'Live lookup for this household'), h('dd', null, status.status),
      h('dt', null, 'Responses used here'), h('dd', null, d.responses_used_here.join(', '))),
    status.reason ? h('p', { class: 'note mt8' }, status.reason) : null));
  if (d.disclosure) sec.append(h('div', { class: 'callout mt12' }, h('div', { class: 'h' }, 'Live capability vs simulated result'), d.disclosure));
  sec.append(h('details', { class: 'block details mt12' }, h('summary', null, 'What is built for a live lookup', chevron()),
    h('ul', { class: 'list' }, d.live_capability.map((x) => h('li', null, x))),
    h('div', { class: 'eyebrow mt12' }, 'Checked against the Hub'), h('ul', { class: 'list' }, d.verified_against_the_hub.map((x) => h('li', null, x))),
    h('div', { class: 'eyebrow mt12' }, 'Not yet verified'), h('ul', { class: 'list' }, d.not_yet_verified.map((x) => h('li', null, x)))));
  const gov = S.p.generated.purposes_on.includes('GOV_PROTECT');
  sec.append(h('div', { class: 'block mt12' },
    h('h3', null, "Check the oil company's record"),
    h('p', { class: 'note' }, gov ? 'Runs the record check with a SIMULATED record: real field names, the same code as a live one, labelled everywhere.' : "Switch on 'Check government protections' first."),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', disabled: !gov || null, onclick: confirmLpg }, 'Run the SIMULATED check')),
    S.meta.lpg.live_enabled ? liveForm() : h('p', { class: 'fine mt8' }, 'Live lookups are off on this laptop.')));
  return sec;
}
function liveForm() {
  const id = h('input', { class: 'field', type: 'password', inputmode: 'numeric', autocomplete: 'off', placeholder: 'Your own 17-digit LPG ID' });
  const own = h('input', { type: 'checkbox' }), credit = h('input', { type: 'checkbox' });
  return h('div', { class: 'mt12' }, h('div', { class: 'eyebrow' }, 'Live lookup — your own LPG ID only'), id,
    h('label', { class: 'check' }, own, 'This is my own LPG ID and I consent to one lookup.'),
    h('label', { class: 'check' }, credit, 'I understand one call spends a Hub credit, even if it fails.'),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn', type: 'button', onclick: () => {
      const body = { mode: 'live', lpg_id: id.value.trim(), holder_confirmed: own.checked, spend_credit: credit.checked };
      id.value = '';
      act('/api/lpg-check', body, (res) => showLive(res));
    } }, 'Make one live call')));
}
function showLive(res) {
  if (!res || !res.standalone_live_record) return;
  const r = res.standalone_live_record;
  openSheet(h('div', null, h('h2', { class: 'sheet-title' }, r.status === 'ok' ? 'Live record' : "We couldn't check"),
    h('div', { class: 'chips' }, h('span', { class: 'chip live' }, 'LIVE · NOT JOINED')), h('p', { class: 'note mt12' }, res.note),
    h('dl', { class: 'kv mt12' }, [['Status', r.status], ['Reason', r.reason || '—'], ['LPG ID', r.lpg_id || '—']].map(([a, b]) => [h('dt', null, a), h('dd', null, b)]),
      Object.entries(r.fields || {}).map(([a, b]) => [h('dt', null, a.replace(/_/g, ' ')), h('dd', null, String(b))]))));
}

/* ---------------------------------------------------------------- actions with a pause for consent */
function setPurpose(purpose, on) {
  act('/api/purposes', { purpose, on }, () => toast(on ? 'Switched on' : 'Switched off — what it used is forgotten'));
}
function confirmPurpose(id) {
  const pur = S.p.what_we_know.purposes.find((p) => p.purpose === id);
  if (!pur) return;
  openSheet(h('div', null,
    h('h2', { class: 'sheet-title' }, pur.label),
    h('p', { class: 'note' }, pur.granted_through),
    h('div', { class: 'block mt12' }, h('div', { class: 'eyebrow' }, 'Uses'), h('ul', { class: 'list' }, pur.uses.map((u) => h('li', null, u))),
      h('div', { class: 'eyebrow mt8' }, 'Never uses'), h('ul', { class: 'list' }, pur.never_uses.map((u) => h('li', null, u))),
      pur.withdraw ? [h('div', { class: 'eyebrow mt8' }, 'To stop'), h('p', { class: 'note' }, pur.withdraw)] : null),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onclick: () => { closeSheet(); setPurpose(id, true); } }, 'OK — switch on'),
      h('button', { class: 'btn ghost', type: 'button', onclick: closeSheet }, 'Not now'))));
}
function confirmLpg() {
  const dpiOn = S.p.generated.purposes_on.includes('DPI_LPG_CHECK');
  const pur = S.p.what_we_know.purposes.find((p) => p.purpose === 'DPI_LPG_CHECK');
  openSheet(h('div', null,
    h('h2', { class: 'sheet-title' }, "Check the oil company's LPG record"),
    h('p', { class: 'note' }, pur.granted_through),
    h('div', { class: 'block mt12' }, h('div', { class: 'eyebrow' }, 'Uses'), h('ul', { class: 'list' }, pur.uses.map((u) => h('li', null, u))),
      h('div', { class: 'eyebrow mt8' }, 'Never keeps'), h('ul', { class: 'list' }, pur.never_uses.map((u) => h('li', null, u)))),
    h('div', { class: 'callout mt12' }, h('div', { class: 'h' }, 'SIMULATED in this prototype'), S.vocab.lpg_disclosure),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onclick: () => { closeSheet(); act('/api/lpg-check', { mode: 'simulated', scenario: S.scenario, consent_to_purpose: !dpiOn || undefined }, (p) => {
        const last = (p && p.what_we_know ? p.what_we_know.access_log : []).filter((x) => x.what === 'lookup').slice(-1)[0];
        if (last && last.outcome === 'ok') toast('SIMULATED record received — see Now');
        else toast(`SIMULATED check — we couldn't check${last && last.reason ? ' (' + last.reason + ')' : ''}`, true);
      }); } },
        dpiOn ? 'Run the SIMULATED check' : 'OK — switch on and check'),
      h('button', { class: 'btn ghost', type: 'button', onclick: closeSheet }, 'Not now'))));
}
function confirmErase() {
  openSheet(h('div', null,
    h('h2', { class: 'sheet-title' }, 'Stop and forget?'),
    h('p', { class: 'note' }, 'Mirror deletes everything it saved for this household on this laptop. Nothing else is asked of you.'),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn danger', type: 'button', onclick: () => { closeSheet(); act('/api/erase', {}); } }, 'Stop and forget'),
      h('button', { class: 'btn ghost', type: 'button', onclick: closeSheet }, 'Keep watching'))));
}
function startView() {
  const err = S.meta && S.meta.store_error;
  return h('div', { class: 'forgotten' }, h('div', null,
    pix(LOGO, 'var(--faint)', 44),
    h('h1', { class: 'big' }, err ? 'Saved state refused.' : 'Not started.'),
    h('p', null, err ? 'The saved replay state could not be reproduced from the recording, so Mirror shows nothing rather than something unchecked.' : 'The replay has not started on this laptop yet.'),
    err ? h('p', { class: 'note' }, `Reason: ${err}`) : null,
    h('div', { class: 'btn-row', style: 'justify-content:center' },
      h('button', { class: 'btn ghost', type: 'button', onclick: () => act('/api/replay/restart', { as_of: S.meta.start }) }, err ? 'Start a fresh replay (demo operator)' : 'Start the replay (demo operator)'))));
}
function forgottenView() {
  return h('div', { class: 'forgotten' }, h('div', null,
    pix(LOGO, 'var(--faint)', 44),
    h('h1', { class: 'big' }, 'Forgotten.'),
    h('p', null, 'Mirror deleted what it saved for this household on this laptop: answers, records, closures and history.'),
    h('p', { class: 'note' }, 'The sealed recording this replay reads from was never copied into Mirror, and stays where it was. To use Mirror again, the household would connect again.'),
    h('div', { class: 'btn-row', style: 'justify-content:center' },
      h('button', { class: 'btn ghost', type: 'button', onclick: () => act('/api/replay/restart', { as_of: S.meta.start }) }, 'Restart the replay (demo operator)'))));
}

/* ---------------------------------------------------------------- sheets */
const BEHIND_SHEET = ['topbar', 'scroller', 'fab', 'tabbar', 'rail-left', 'rail-right'];
let sheetReturn = null;
function openSheet(content) {
  const layer = $('sheet');
  if (layer.hidden) sheetReturn = document.activeElement;
  layer.hidden = false;
  const title = content.querySelector('.sheet-title, .card-title, h2');
  if (title) title.id = 'sheet-title';
  const dlg = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true', tabindex: '-1',
    'aria-labelledby': title ? 'sheet-title' : null, 'aria-label': title ? null : 'Details' },
    h('div', { class: 'sheet-head' }, h('div', { class: 'grabber', 'aria-hidden': 'true' }),
      h('button', { class: 'sheet-close', type: 'button', onclick: closeSheet, 'aria-label': 'Close' }, '×')), content);
  layer.replaceChildren(h('div', { class: 'scrim', onclick: closeSheet }), dlg);
  BEHIND_SHEET.forEach((id) => $(id) && $(id).setAttribute('inert', ''));
  requestAnimationFrame(() => (title ? (title.setAttribute('tabindex', '-1'), title) : dlg).focus({ preventScroll: true }));
}
function closeSheet() {
  const layer = $('sheet');
  if (layer.hidden) return;
  layer.hidden = true; layer.replaceChildren();
  BEHIND_SHEET.forEach((id) => $(id) && $(id).removeAttribute('inert'));
  const back = sheetReturn && document.contains(sheetReturn) ? sheetReturn : $('fab');
  sheetReturn = null;
  if (back && !back.hidden) back.focus({ preventScroll: true });
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') { closeSheet(); return; }
  const dlg = document.querySelector('#sheet .sheet');
  if (e.key !== 'Tab' || !dlg) return;                       // keep keyboard focus inside an open sheet
  const f = [...dlg.querySelectorAll('button:not([disabled]), select, input, summary, [href], [tabindex]:not([tabindex="-1"])')].filter((x) => x.offsetParent);
  if (!f.length) return;
  const first = f[0], last = f[f.length - 1];
  if (e.shiftKey && (document.activeElement === first || !dlg.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && (document.activeElement === last || !dlg.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
});
function openCardSheet(c) {
  S.focus = c.id; S.open.add(c.id);
  openSheet(h('div', null, card(c, { compact: true, level: 'h2' })));
}

/* ---------------------------------------------------------------- Ask Mirror (S2): five fixed questions */
function openAsk(which) {
  const answerBox = h('div', { class: 'ask-answer' });
  const chips = h('div', { class: 'ask-chips' }, S.vocab.ask_mirror.map((q) => h('button', {
    type: 'button', 'aria-pressed': 'false', onclick: (e) => {
      chips.querySelectorAll('button').forEach((b) => b.setAttribute('aria-pressed', 'false'));
      e.currentTarget.setAttribute('aria-pressed', 'true');
      answerBox.replaceChildren(askAnswer(q));
    },
  }, q.label)));
  openSheet(h('div', null, h('h2', { class: 'sheet-title' }, 'Ask Mirror'),
    h('p', { class: 'note' }, 'Fixed questions. Every answer is built only from what Mirror already shows you — no AI writes anything here.'),
    chips, answerBox));
  if (which) chips.querySelectorAll('button')[S.vocab.ask_mirror.findIndex((q) => q.id === which)]?.click();
}
function askAnswer(q) {
  const p = S.p, k = p.what_we_know;
  const focus = p.now.cards.find((c) => c.id === S.focus) || p.now.cards[0];
  if (q.id === 'why') {
    if (!focus) return h('div', null, h('h3', null, 'Nothing is open right now'), p.now.since_last_time.lines.map((l) => h('p', { class: 'note' }, l.text)));
    return h('div', null, h('h3', null, focus.title), h('p', { class: 'note' }, focus.body[0]), ledgerOpen(focus));
  }
  if (q.id === 'know') {
    const row = (cls, label, text, sub) => h('div', { class: 'ev' }, h('div', { class: 'ev-label' }, text), sub ? h('div', { class: 'ev-sub' }, sub) : null, h('div', { class: 'mt8' }, badge(cls, label)));
    const pr = p.our_household.protections;
    return h('div', null,
      h('h3', null, 'Learned from your bank data'),
      p.our_household.commitments.map((c) => row('O', CLS_NAME.O, c.label, `${c.member} · ${c.cadence.toLowerCase()} · ${c.status}`)),
      p.our_household.regular_credits.map((c) => row('O', CLS_NAME.O, c.label, c.member)),
      h('h3', null, 'What you told us'),
      k.household_facts.length || k.facts.length
        ? [k.household_facts.map((f) => row('U', f.badge, f.answer, `${f.member} · ${evLabel(f.fact)}`)),
          k.facts.map((f) => row('U', S.vocab.badges.U_answered, f.answer, f.question))]
        : h('p', { class: 'note' }, 'Nothing yet.'),
      pr && pr.context && pr.context.length ? [h('h3', null, 'Records from outside the bank data'),
        pr.context.map((c) => h('div', { class: 'ev' }, h('div', { class: 'ev-label' }, c.text), h('div', { class: 'mt8' }, badge(c.simulated ? 'S' : c.evidence_class, c.badge)),
          c.simulated ? h('div', { class: 'callout mt8' }, S.vocab.lpg_disclosure) : null))] : null,
      h('h3', null, 'What we cannot see'), h('ul', { class: 'list' }, k.limits.map((l) => h('li', null, l))));
  }
  if (q.id === 'who') {
    return h('div', null,
      h('h3', null, 'Data read'), k.sources.map((src) => h('p', { class: 'note' }, `${src.name} — ${Array.isArray(src.mode) ? src.mode.join(', ') : src.mode}`)),
      h('h3', null, 'Outside lookups and forgetting'),
      k.access_log.length ? h('ul', { class: 'log' }, k.access_log.map(logRow)) : h('p', { class: 'note' }, 'None.'));
  }
  if (q.id === 'wrong') {
    const openQs = p.now.cards.filter((c) => c.question);
    return h('div', null,
      h('h3', null, 'Change something you told us'),
      k.household_facts.length ? k.household_facts.map((f) => h('p', { class: 'note' }, `${f.member} · ${evLabel(f.fact)}: ${f.answer}`)) : h('p', { class: 'note' }, 'Nothing yet.'),
      h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => { closeSheet(); go('know'); setTimeout(() => document.getElementById('k-told')?.scrollIntoView({ behavior: smooth() }), 260); } }, 'Open what you told us')),
      h('h3', null, 'Answer what Mirror asked'),
      openQs.length ? h('ul', { class: 'list' }, openQs.map((c) => h('li', null, `${c.member}: ${c.question.question}`))) : h('p', { class: 'note' }, 'No open questions.'),
      k.corrections.length ? [h('h3', null, 'Your corrections so far'), k.corrections.map((x) => h('p', { class: 'note' }, `${x.member}: ${x.before} → ${x.after} (${fmtDate(x.stated_on)})`))] : null);
  }
  if (q.id === 'stop') {
    return h('div', null,
      h('h3', null, 'Stop one purpose'), k.purposes.map((pp) => h('p', { class: 'note' }, h('strong', null, pp.label), ` — ${pp.withdraw}`)),
      h('h3', null, 'Stop everything'),
      h('div', { class: 'btn-row' }, h('button', { class: 'btn danger', type: 'button', onclick: confirmErase }, 'Stop and forget')));
  }
  if (q.id === 'advice' && S.meta.options) return optionsIntro();      // --options only
  return h('div', null, h('h3', null, q.fixed_reply),
    focus ? [h('p', { class: 'note' }, focus.title), ledgerOpen(focus)] : null);
}
/* --options: "Within an amount you set". The server computes and validates every line (options.py, fail
   closed); the page only lays it out. Three concepts, three looks: context from the cards (tinted rows),
   published options (bordered cards, one look for within and for more than), observed context (ruled rows). */
function optionsLink() {
  return h('div', { class: 'btn-row mt16' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => openOptions() }, S.meta.options.link));
}
function optionsIntro() {
  const o = S.meta.options;
  return h('div', null, h('h3', null, o.reply),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn', type: 'button', onclick: () => openOptions() }, o.button)));
}
function openOptions() {
  const o = S.meta.options.step1;
  const members = (S.p ? S.p.our_household.members : []).filter((m) => m.status === 'watched').map((m) => m.display_name.split(' ')[0]);
  const prev = S.opt || {};
  S.opt = { member: members.includes(prev.member) ? prev.member : members[0], amount: prev.amount || null };
  const setup = h('div', null);
  const result = h('div', { class: 'mt16', 'aria-live': 'polite' });
  const chips = (items, current, pick, label) => h('div', { class: 'options', role: 'group', 'aria-label': label },
    items.map((it) => h('button', { class: `opt ${it.value === current ? 'chosen' : ''}`, type: 'button',
      'aria-pressed': it.value === current ? 'true' : 'false', onclick: () => pick(it.value) }, it.label)));
  const show = async () => {
    try {
      const res = await api('/api/options', { member: S.opt.member, amount: S.opt.amount });
      result.replaceChildren(optionsResult(res));
    } catch (e) { toast(e.message, true); }
  };
  const draw = () => setup.replaceChildren(
    h('div', { class: 'jfield-label mt12' }, o.for_label),
    chips(members.map((n) => ({ value: n, label: n })), S.opt.member, (v) => { S.opt.member = v; draw(); if (S.opt.amount) show(); }, o.for_label),
    h('div', { class: 'jfield-label mt12' }, o.amount_label),
    chips(o.amounts, S.opt.amount, (v) => { S.opt.amount = v; draw(); show(); }, o.amount_label),
    h('p', { class: 'fine mt8' }, o.fine),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn', type: 'button', disabled: (!S.opt.amount || !S.opt.member) || null, onclick: show }, o.show)));
  draw();
  openSheet(h('div', null, h('h2', { class: 'sheet-title' }, o.title), h('p', { class: 'note' }, o.lede),
    members.length ? [setup, result] : h('p', { class: 'note mt12' }, o.none_watched)));
}
function optionsResult(res) {
  const sec = Object.fromEntries(res.sections.map((x) => [x.kind, x]));
  const badges = (classes) => h('div', { class: 'mt8' }, classes.map((c) => badge(c, CLS_NAME[c])));
  const head = (x) => h('h3', { class: 'mt16' }, x.heading);
  const empty = (x) => (x.items.length ? null : h('p', { class: 'note' }, x.empty));
  const go2 = (view) => () => { closeSheet(); go(view); };
  const running = sec.RUNNING, nocost = sec.NO_COST, within = sec.WITHIN, over = sec.OVER, notShown = sec.NOT_SHOWN, out = sec.GOING_OUT;
  const optionCard = (it) => h('div', { class: 'block' },
    h('div', { class: 'card-meta' }, h('span', { class: 'eyebrow' }, it.label), h('span', { class: 'chip replay' }, it.tag)),
    h('p', { class: 'note' }, it.pays),
    it.rows ? h('ul', { class: 'list' }, it.rows.map((r) => h('li', null, r.text))) : null,
    it.facts_text ? h('p', { class: 'note mt8' }, it.facts_text) : null,
    h('p', { class: 'fine mt8' }, it.sources_text), badges(it.classes));
  return h('div', null,
    h('div', null, h('h3', null, res.header.title), badge('U', res.header.badge), res.header.lines.map((l) => h('p', { class: 'note mt8' }, l))),
    // 1 · context from the member's own cards: obligations and zero-cost actions, never options
    h('div', { class: 'mt16', style: 'border-left: 3px solid var(--line); padding-left: var(--sp-3)' },
      h('div', { class: 'eyebrow' }, res.groups.context_cards),
      head(running), h('p', { class: 'note' }, running.lede),
      running.items.map((it) => h('div', { class: 'ev' }, h('div', { class: 'ev-label' }, it.title),
        it.amount_text ? h('div', { class: 'ev-sub' }, it.amount_text) : null,
        it.deadline_line ? h('div', { class: 'ev-sub' }, it.deadline_line) : null,
        it.action_text ? h('div', { class: 'ev-sub' }, it.action_text) : null, badges(it.classes))),
      empty(running),
      running.blocked_text ? h('div', { class: 'ev' }, h('div', { class: 'ev-sub' }, running.blocked_text),
        h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', onclick: go2('now') }, 'Open the questions'))) : null,
      head(nocost),
      nocost.items.map((it) => h('div', { class: 'ev' }, h('div', { class: 'ev-label' }, it.action_text),
        it.simulated ? h('span', { class: 'chip sim mt8' }, 'SIMULATED record') : null, badges(it.classes))),
      empty(nocost)),
    // 2 · published options: one look for "within" and for "more than"; never ranked
    h('div', { class: 'mt16' },
      h('div', { class: 'eyebrow' }, res.groups.options),
      head(within),
      res.protections_off
        ? [h('p', { class: 'note' }, within.off_text),
          h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => { closeSheet(); confirmPurpose('GOV_PROTECT'); } }, 'Switch on'))]
        : [h('div', { class: 'eyebrow mt8' }, within.subheading), within.items.map(optionCard), empty(within),
          head(over), over.items.map(optionCard), empty(over),
          head(notShown), notShown.items.map((it) => h('div', null, h('p', { class: 'note' }, it.text),
            it.type === 'needs_answer' ? h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', onclick: go2('now') }, 'Answer it')) : null)),
          empty(notShown)]),
    // 3 · observed context: what already goes out, never set against the amount
    h('div', { class: 'mt16', style: 'border-left: 3px dotted var(--line); padding-left: var(--sp-3)' },
      h('div', { class: 'eyebrow' }, res.groups.observed),
      head(out), h('p', { class: 'note' }, out.lede),
      out.items.map((it) => h('div', { class: 'scheme' }, h('div', { class: 'n' }, it.text), badge('O', CLS_NAME.O))),
      empty(out)),
    head(sec.CANNOT_TELL), h('ul', { class: 'list' }, sec.CANNOT_TELL.lines.map((l) => h('li', null, l))),
    h('div', { class: 'block mt16' }, h('h3', null, sec.NONE.heading), sec.NONE.lines.map((l) => h('p', { class: 'note' }, l))),
    h('p', { class: 'fine mt16' }, res.footer));
}
function ledgerOpen(c) {
  const wrap = h('div', { class: 'reveal open' }, h('div', null, ledger(c)));
  return wrap;
}

/* ---------------------------------------------------------------- Gate 7: identify → consent on the AA → data arrives → Mirror learns */
const JOURNEY_ACTIVE = ['starting', 'requested', 'approved', 'data_ready', 'fetching', 'decrypting', 'verifying', 'learning'];
let pollTimer = null;
function pollJourney() {
  clearTimeout(pollTimer);
  if (!S.connect || !JOURNEY_ACTIVE.includes(S.connect.state)) return;
  pollTimer = setTimeout(async () => {
    try {
      const was = S.connect.state;
      S.connect = await api('/api/connect');
      if (S.connect.state === 'ready' && was !== 'ready') { await refreshAll(); return; }
      if (inJourney()) render({ quiet: true });
      else renderRails();
    } catch (e) { /* the next poll tries again; the server keeps the truth */ }
    pollJourney();
  }, 1000);
}
async function refreshAll() {
  try { await refreshAllInner(); } catch (e) { toast(e.message, true); render(); }
}
async function refreshAllInner() {
  S.meta = await api('/api/meta');
  if (S.meta.connect && S.meta.connect.enabled) S.connect = await api('/api/connect');
  S.history = await api('/api/history').catch(() => null);
  const p = await api('/api/payload');
  if (p && p.contract) { S.prev = null; S.p = p; S.forgotten = false; } else { S.p = null; S.forgotten = p && p.state === 'forgotten'; }
  S.view = 'now';
  render();
}
/* --demo-login: the phone screen opens a sandbox household. DEMO / SANDBOX, not authentication: the server
   decides which household (if any) a demo number opens, and only the AA test customer can start a consent. */
async function demoLogin(v) {
  if (S.busy) return;
  S.busy = true; busy(true);
  let res = null;
  try { res = await api('/api/login', { mobile: v }); } catch (e) { toast(e.message, true); }
  S.busy = false; busy(false);
  if (!res) return;
  S.connectDone = false; S.open.clear(); S.justResolved = new Set(); S.editing = null; S.focus = null;
  if (res.route === 'aa') { S.mobileDraft = v; S.phase = 'terms'; S.pendingFocus = 'h1'; } else { S.mobileDraft = null; S.phase = 'welcome'; }
  await refreshAll();
}
function demoSignOut() {
  closeSheet();
  act('/api/logout', {}, () => {
    S.phase = 'welcome'; S.mobileDraft = null; S.connectDone = false; S.open.clear(); S.justResolved = new Set(); S.editing = null;
    refreshAll();
  });
}
function demoLoginPanel() {
  const hh = S.meta.household;
  return h('div', { class: 'panel' },
    h('div', { class: 'eyebrow' }, 'Demo login'),
    h('p', { class: 'fine mt8' }, `Signed in to the ${hh ? hh.label : 'sandbox household'} with a demo number. Not authentication.`),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', onclick: demoSignOut }, 'Sign out')));
}
function startJourney(mobile) {
  S.opened = false;
  act('/api/connect/start', { mobile }, (st) => {
    S.connect = st; S.phase = 'welcome';
    if (st.state === 'failed') toast(st.error, true);
    render(); pollJourney();
  });
}
function stepList(c) {
  const current = JOURNEY_ACTIVE.includes(c.state) ? c.steps.find((x) => !x.done) : null;
  return h('ol', { class: 'jsteps' }, c.steps.map((st) => h('li', { class: st.done ? 'done' : (st === current ? 'now' : '') },
    h('span', { class: 'jmark', 'aria-hidden': 'true' }, st.done ? tick('var(--o)') : null),
    h('div', null,
      h('div', { class: 'jlabel' }, st.label, st === current ? h('span', { class: 'sr-only' }, ' — in progress') : null),
      h('div', { class: 'jsrc' }, st.done ? `${st.at} · ${st.source}${st.detail ? ' · ' + st.detail : ''}` : st.source)))));
}
function welcomeView(c) {
  const demo = !!(S.meta && S.meta.demo_login);
  const input = h('input', { class: 'field mobile', id: 'mobile', type: 'tel', inputmode: 'numeric', autocomplete: 'tel-national', maxlength: '10',
    'aria-describedby': 'mobile-help', placeholder: '10-digit mobile' });
  const go = () => {
    const v = input.value.replace(/\D/g, '');
    if (!/^[6-9]\d{9}$/.test(v)) { toast('Enter the 10-digit mobile number linked to your bank accounts', true); input.focus(); return; }
    if (demo) { demoLogin(v); return; }
    S.mobileDraft = v; S.phase = 'terms'; S.pendingFocus = 'h1'; render();
  };
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
  if (S.mobileDraft) input.value = S.mobileDraft;
  const failed = c && (c.state === 'failed' || c.state === 'rejected');
  return h('div', { class: 'journey' },
    h('div', { class: 'jhead' }, pix(LOGO, 'var(--ink)', 36),
      demo ? h('div', { class: 'chips' }, h('span', { class: 'chip sim', title: 'A demo sign-in for the sandbox households; not authentication' }, 'DEMO · SANDBOX')) : null,
      h('h1', { class: 'page-title', tabindex: '-1' }, 'Your household, seen clearly.'),
      h('p', { class: 'page-lede' }, 'Mirror watches the bank accounts your household chooses to share, and tells you when something needs you — and why.')),
    failed ? h('div', { class: 'callout warn', role: 'alert' }, h('div', { class: 'h' }, c.state === 'rejected' ? 'The consent was not approved' : 'That did not finish'), c.error) : null,
    h('div', { class: 'jform' },
      h('label', { for: 'mobile', class: 'jfield-label' }, 'Mobile number linked to your bank accounts'),
      h('div', { class: 'prefixed' }, h('span', { class: 'prefix', 'aria-hidden': 'true' }, '+91'), input),
      h('p', { class: 'fine', id: 'mobile-help' }, demo ? S.meta.demo_login.note : 'Used only to ask your Account Aggregator. In the sandbox, use Anumati’s test customer number.'),
      h('div', { class: 'btn-row' }, h('button', { class: 'btn wide', type: 'button', onclick: go }, 'Continue', arrowIcon('#fff')))),
    h('ol', { class: 'how' },
      h('li', null, h('div', null, h('b', null, 'You approve on your Account Aggregator’s own page.'), ' Mirror never sees your bank login or your OTP.')),
      h('li', null, h('div', null, h('b', null, 'Your bank sends the data once, encrypted.'), ' It is opened on this device.')),
      h('li', null, h('div', null, h('b', null, 'Mirror reads it and tells you what needs you.'), ' Every card shows where it came from.'))));
}
function termsView(c) {
  const t = c.terms;
  const rows = t ? [['Through', t.rail], ['Purpose', `${t.purpose_code} · ${t.purpose_text}`], ['Data', t.fi_types.join(', ')],
    ['Updates', t.frequency], ['Kept for', t.data_life], ['Looks back', t.data_range], ['Ends', t.expiry]] : [];
  return h('div', { class: 'journey' },
    h('div', { class: 'jhead' },
      h('div', { class: 'eyebrow' }, `For ••••••${(S.mobileDraft || '').slice(-4)}`),
      h('h1', { class: 'page-title', tabindex: '-1' }, 'What Mirror will ask for'),
      h('p', { class: 'page-lede' }, 'Your Account Aggregator will show you this same request. You can revoke it there at any time.')),
    t ? h('div', { class: 'block' }, h('dl', { class: 'kv' }, rows.map(([a, b]) => [h('dt', null, a), h('dd', null, b)]))) : null,
    h('p', { class: 'note mt12' }, 'Only “Watch our bank accounts” starts with this. Checking government protections and the LPG record each ask you separately, later.'),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn wide', type: 'button', onclick: (e) => { e.currentTarget.disabled = true; const m = S.mobileDraft; S.mobileDraft = null; startJourney(m); } }, 'Ask my Account Aggregator'),
      h('button', { class: 'btn ghost', type: 'button', onclick: () => { S.phase = 'welcome'; S.pendingFocus = 'h1'; render(); } }, 'Back')));
}
function waitingView(c) {
  const titles = { starting: 'Asking your Account Aggregator…', requested: 'Approve on Anumati', approved: 'Your AA said yes',
    data_ready: 'Your data is ready at the AA', fetching: 'Collecting it, once', decrypting: 'Opening it on this device',
    verifying: 'Checking it', learning: 'Mirror is reading your household' };
  const slow = c.state === 'requested' && c.waited_s > 90;
  return h('div', { class: 'journey' },
    h('div', { class: 'jhead' },
      h('div', { class: 'eyebrow' }, c.mobile ? `For ${c.mobile}` : 'Connecting'),
      h('h1', { class: 'page-title', tabindex: '-1' }, titles[c.state] || 'Connecting'),
      c.state === 'requested' ? h('p', { class: 'page-lede' }, 'Your Account Aggregator shows you exactly what Mirror asked for. Choose your bank there and confirm with the OTP it sends.') : null),
    c.state === 'requested' && c.redirect_url ? h('div', { class: 'jaa' },
      h('button', { class: 'btn wide', type: 'button', disabled: S.opened || null, onclick: (e) => {
        S.opened = true; e.currentTarget.disabled = true; e.currentTarget.textContent = 'Opened — finish on Anumati';
        window.open(c.redirect_url, '_blank', 'noopener');
      } }, S.opened ? 'Opened — finish on Anumati' : 'Open Anumati to approve'),
      h('p', { class: 'fine' }, 'The link works once. Sandbox: choose ACME Bank; the AA’s test OTP is 812093.')) : null,
    slow ? h('div', { class: 'callout warn', role: 'status' }, h('div', { class: 'h' }, 'Still waiting for Anumati'), 'If you approved, the callback may not be reaching this laptop. The operator can run the pre-flight.') : null,
    h('div', { class: 'section-sub mt16' }, 'Each step appears when it really happens.'),
    stepList(c));
}
function learnedView(c) {
  const hh = S.p ? S.p.our_household : null;
  return h('div', { class: 'journey' },
    h('div', { class: 'jhead' },
      h('div', { class: 'eyebrow' }, 'Connected'),
      h('h1', { class: 'page-title', tabindex: '-1' }, 'Mirror has read your household'),
      h('p', { class: 'page-lede' }, c.result && c.result.matches_e8
        ? 'What your bank just sent decrypts to exactly the same bytes as the sealed recording this demo was built and tested on.'
        : 'This is new data from your bank, read just now.')),
    hh ? h('div', { class: 'rail-scroll', tabindex: '0', role: 'region', 'aria-label': 'Household members' }, hh.members.map((m) => h('div', { class: 'member-card' },
      h('div', { class: 'n' }, m.display_name), h('div', { class: 'a' }, m.account),
      h('div', { class: 'note mt8' }, `Data from ${fmtDate(m.data_from)} to ${fmtDate(m.data_until)}`)))) : null,
    h('div', { class: 'callout live-note' }, h('div', { class: 'h' }, 'What is live, and what is replayed'),
      'The consent, the callbacks, the fetch and the decryption happened just now. The sandbox bank’s data stops by early September, so Mirror replays time through it, day by day.'),
    stepList(c),
    h('div', { class: 'btn-row' }, h('button', { class: 'btn wide', type: 'button', onclick: () => { S.connectDone = true; S.view = 'now'; S.pendingFocus = 'h1'; render(); } }, 'See what needs attention', arrowIcon('#fff'))));
}
function connectView() {
  if (S.meta.connect.entry === 'login') return welcomeView(null);   // --demo-login: signed out
  const c = S.connect || { state: 'idle', steps: [] };
  if (c.state === 'ready') return learnedView(c);
  if (JOURNEY_ACTIVE.includes(c.state)) return waitingView(c);
  return S.phase === 'terms' ? termsView(c) : welcomeView(c);
}
function sessionConsentBlock() {
  const c = S.connect && S.connect.live_session;              // the consent that produced THIS household
  if (!c || S.meta.corpus_source !== 'live' || !c.steps) return null;
  const at = (id) => (c.steps.find((x) => x.id === id) || {}).at;
  const approved = c.steps.find((x) => x.id === 'approved') || {};
  return h('div', { class: 'block live-block' },
    h('div', { class: 'card-meta' }, h('span', { class: 'eyebrow' }, 'This session'), h('span', { class: 'chip live' }, 'FETCHED LIVE')),
    h('h3', null, 'Your consent, from Anumati’s own callback'),
    h('dl', { class: 'kv' },
      [['Mobile', c.mobile], ['Consent', c.consent_ref], ['Approved', approved.at ? `${approved.at} · ${approved.detail}` : '—'],
        ['Collected once', at('fetched') || '—'], ['Fingerprint', c.result ? c.result.fingerprint : '—'],
        ['Sealed recording', c.result ? (c.result.matches_e8 ? 'same bytes' : 'different data') : '—']].map(([a, b]) => [h('dt', null, a), h('dd', null, b || '—')])));
}

/* ---------------------------------------------------------------- operator (replay) + legend rails */
function journeyPanel() {
  const c = S.connect;
  const box = h('div', { class: 'panel' }, h('div', { class: 'eyebrow' }, 'Live AA journey'),
    h('p', { class: 'fine mt8' }, c ? `State: ${c.state.replace(/_/g, ' ')}${c.consent_ref ? ' · consent ' + c.consent_ref : ''}` : 'Off'));
  if (S.preflight) box.append(h('ul', { class: 'checks' }, S.preflight.checks.map((k) => h('li', { class: k.ok === true ? 'ok' : (k.ok === false ? 'bad' : 'na') },
    h('span', { class: 'ck', 'aria-hidden': 'true' }, k.ok === true ? '✓' : (k.ok === false ? '×' : '–')),
    h('div', null, h('div', null, k.label), h('div', { class: 'fine' }, (k.ok === true ? 'Ready · ' : (k.ok === false ? 'Not ready · ' : 'Not checked · ')) + k.detail))))));
  box.append(h('div', { class: 'btn-row' },
    h('button', { class: 'btn ghost', type: 'button', onclick: runPreflight }, 'Run pre-flight'),
    h('button', { class: 'btn ghost', type: 'button', onclick: () => { closeSheet(); S.connectDone = false; S.phase = 'welcome'; S.opened = false; act('/api/connect/reset', {}, (st) => { S.connect = st; refreshAll(); }); } }, 'Back to welcome'),
    h('button', { class: 'btn ghost', type: 'button', onclick: () => { closeSheet(); act('/api/connect/use-recorded', {}, () => { S.connectDone = true; refreshAll(); }); } }, 'Use the sealed recording')),
    h('p', { class: 'fine mt8' }, 'Pre-flight reads this laptop only: no call to Anumati.'));
  return box;
}
async function runPreflight() {
  try { S.preflight = await api('/api/connect/preflight'); renderRails(); if (!$('sheet').hidden) openOperator(); }
  catch (e) { toast(e.message, true); }
}
function operatorPanel() {
  const m = S.meta;
  const asOf = m.as_of;
  const restart = h('select', { class: 'select', 'aria-label': 'Restart the replay at' },
    m.stops.map((st) => h('option', { value: st.date, selected: st.date === m.start || null }, fmtDate(st.date))));
  const scen = h('select', { class: 'select', 'aria-label': 'Simulated LPG scenario', onchange: (e) => { S.scenario = e.target.value; } },
    m.lpg.scenarios.map((sc) => h('option', { value: sc, selected: sc === S.scenario || null }, sc.replace(/_/g, ' '))));
  return h('div', null,
    h('div', { class: 'brand' }, pix(LOGO, 'var(--ink)', 18), 'Mirror', h('span', { class: 'brand-sub' }, 'this laptop only')),
    h('h2', null, 'Replay controls'),
    h('p', null, 'For the demo operator. The bank data is one recorded AA sandbox fetch; time moves forward only.'),
    m.connect && m.connect.enabled ? journeyPanel() : null,
    m.demo_login && m.demo_login.signed_in ? demoLoginPanel() : null,
    h('div', { class: 'panel' },
      h('div', { class: 'eyebrow' }, 'Replaying as of'),
      h('div', { class: 'date-now' }, fmtDate(asOf)),
      h('ul', { class: 'stops' }, m.stops.map((st) => {
        const cls = st.date < asOf ? 'past' : (st.date === asOf ? 'here' : '');
        return h('li', { class: cls }, h('span', { class: 'pt' }),
          h('div', null, h('div', { class: 'd' }, fmtDate(st.date)), h('div', { class: 'hint' }, st.hint)),
          h('button', { type: 'button', disabled: (st.date <= asOf || S.forgotten) || null, onclick: () => { closeSheet(); act('/api/clock', { as_of: st.date }, () => toast(`Refreshed — as of ${fmtDate(st.date)}`)); } }, st.date === asOf ? 'Now' : 'Go'));
      }))),
    h('div', { class: 'panel' },
      h('div', { class: 'eyebrow' }, 'Start again at'), restart,
      h('div', { class: 'btn-row' }, h('button', { class: 'btn ghost', type: 'button', onclick: () => { closeSheet(); S.open.clear(); act('/api/replay/restart', { as_of: restart.value }, () => toast(`Replay restarted — ${fmtDate(restart.value)}`)); } }, 'Restart replay')),
      h('p', { class: 'fine mt8' }, 'Erases this replay\'s saved state first.')),
    h('div', { class: 'panel' },
      h('div', { class: 'eyebrow' }, 'Simulated LPG scenario'), scen,
      h('p', { class: 'fine mt8' }, m.lpg.live_enabled ? 'Live lookups: enabled for one deliberate call.' : 'Live lookups: off on this laptop.')));
}
function openOperator() { if (S.meta) openSheet(h('div', null, operatorPanel(), h('div', { class: 'mt16' }, legendPanel()))); }
function legendPanel() {
  const b = S.vocab.badges;
  return h('div', null,
    h('h2', null, 'Reading Mirror'),
    h('p', null, 'Every card shows where it came from — by colour, shape and name. Nothing on screen is computed by the page.'),
    h('div', { class: 'panel' }, h('div', { class: 'eyebrow' }, 'Evidence'),
      h('ul', { class: 'legend-list' },
        h('li', null, badge('O', 'O'), b.O), h('li', null, badge('R', 'R'), b.R), h('li', null, badge('I', 'I'), b.I),
        h('li', null, badge('U', 'U'), `${b.U} — once answered: “${b.U_answered}”, still never a fact`))),
    h('div', { class: 'panel' }, h('div', { class: 'eyebrow' }, 'Data modes'),
      h('ul', { class: 'legend-list' },
        S.meta.corpus_source === 'live'
          ? h('li', null, h('span', { class: 'chip live' }, 'FETCHED LIVE'), 'Fetched through this app from the Anumati sandbox during this session: consent, callbacks, one fetch, decrypted here')
          : h('li', null, h('span', { class: 'chip recorded' }, 'RECORDED'), S.meta.corpus_is_e8 ? 'One sealed AA sandbox fetch (E8, 23 Sep), the same bytes on four runs' : 'One recorded AA sandbox fetch (not the sealed E8 file)'),
        h('li', null, h('span', { class: 'chip replay' }, 'REPLAY'), 'Real data, replayed time: each refresh is an as-of date'),
        h('li', null, h('span', { class: 'chip sim' }, 'SIMULATED'), 'The LPG record: real field names, same code path, never shown as live'),
        S.meta.demo_login ? h('li', null, h('span', { class: 'chip sim' }, 'DEMO LOGIN'), 'A demo number opened this sandbox household. Not authentication; in real use each household would consent for itself') : null)),
    h('p', { class: 'fine' }, 'The engine decides; this page only renders the validated contract.'));
}
function renderRails() {
  if (!S.meta || !S.vocab) return;
  $('rail-left').replaceChildren(operatorPanel());
  $('rail-right').replaceChildren(legendPanel());
}

/* ---------------------------------------------------------------- boot */
async function boot() {
  $('fab').addEventListener('click', () => openAsk());
  try {
    const [meta, vocab] = await Promise.all([api('/api/meta'), api('/api/vocab')]);
    S.meta = meta; S.vocab = vocab;
    if (meta.connect && meta.connect.enabled) { S.connect = await api('/api/connect'); pollJourney(); }
    let p;
    try { p = await api('/api/payload'); } catch (e) { if (!S.meta.store_error) throw e; p = { state: 'store_error' }; }
    S.meta = await api('/api/meta');
    S.history = await api('/api/history').catch(() => null);
    if (p.state === 'forgotten') { S.forgotten = true; render(); return; }
    if (p.state === 'connect') { S.p = null; render(); return; }
    if (p.state) { S.p = null; render(); return; }
    S.p = p;
    render();
  } catch (e) {
    $('view').replaceChildren(h('div', { class: 'forgotten' }, h('div', null, h('h1', { class: 'big' }, 'Mirror stopped.'),
      h('p', null, e.message), h('p', { class: 'note' }, 'Nothing unvalidated is ever shown. Check the server window on this laptop.'))));
  }
}
boot();
