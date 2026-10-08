/* Front Office — start/sit, waivers, trades and values for three Sleeper leagues.
   Player facts come from data/*.json (built by engine/build.py). League logic runs here on live Sleeper rosters. */
(() => {
'use strict';

const SL = 'https://api.sleeper.app/v1';
const SKILL = ['QB', 'RB', 'WR', 'TE'];
const ELIG = { QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], K: ['K'], DEF: ['DEF'], FLEX: ['RB', 'WR', 'TE'],
  SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'], REC_FLEX: ['WR', 'TE'], WRRB_FLEX: ['RB', 'WR'] };
const SLOT_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF', 'REC_FLEX', 'WRRB_FLEX', 'FLEX', 'SUPER_FLEX'];
const SLOT_LABEL = { SUPER_FLEX: 'SFLX', REC_FLEX: 'W/T', WRRB_FLEX: 'W/R', DEF: 'DST' };
const SIG_LABEL = { late: 'This week', ros: 'ROS move', split: 'Sources split', mkt: 'Market', hot: 'Trending',
  inj: 'Injury', snap: 'Snaps', experts: 'Experts split', ffb: 'Footballers' };
const UNAVAIL = 0.15;

const S = {
  D: null, league: 'maywood', tab: 'lineup', liveAt: null, ctx: {},
  trade: { opp: null, give: new Set(), get: new Set(), showKD: false },
  vals: { pos: 'ALL', filter: 'all', q: '' }, wv: { pos: 'SKILL' }, sig: { pos: 'ALL' },
};

// ---------------------------------------------------------------- utils
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const f1 = (x, d = 1) => (x == null || Number.isNaN(+x)) ? '–' : (+x).toFixed(d);
const sgn = (x, d = 1) => (x == null || Number.isNaN(+x)) ? '–' : ((x > 0 ? '+' : x < 0 ? '−' : '±') + Math.abs(x).toFixed(d));
const kfmt = n => n == null ? '–' : n >= 1000 ? (n / 1000).toFixed(1).replace(/\.0$/, '') + 'k' : String(Math.round(n));
const sum = a => a.reduce((s, x) => s + x, 0);
function erf(x) { const t = 1 / (1 + 0.3275911 * Math.abs(x)); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; }
const Phi = z => 0.5 * (1 + erf(z / Math.SQRT2));
const store = { get(k, d) { try { const v = localStorage.getItem('fo.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('fo.' + k, JSON.stringify(v)); } catch { /* private mode */ } } };
function ago(iso) {
  if (!iso) return '–';
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 60) return `${Math.max(m, 0)}m ago`;
  if (m < 60 * 36) return `${Math.round(m / 60)}h ago`;
  return `${Math.round(m / 1440)}d ago`;
}
const clock = iso => iso ? new Date(iso).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : '–';

// ---------------------------------------------------------------- data
async function loadData() {
  const emb = document.getElementById('fo-data');
  if (emb) return JSON.parse(emb.textContent);
  const bust = Math.floor(Date.now() / 600000);
  const get = n => fetch(`data/${n}.json?v=${bust}`).then(r => { if (!r.ok) throw new Error(n); return r.json(); });
  const [players, leagues, meta, model] = await Promise.all(['players', 'leagues', 'meta', 'model'].map(get));
  return { players, leagues, meta, model };
}

async function refreshLive() {
  const D = S.D; let ok = 0;
  await Promise.all(D.leagues.map(async L => {
    try {
      const j = u => fetch(u).then(r => { if (!r.ok) throw new Error(u); return r.json(); });
      const [rosters, users, mus] = await Promise.all([j(`${SL}/league/${L.id}/rosters`), j(`${SL}/league/${L.id}/users`),
        j(`${SL}/league/${L.id}/matchups/${D.meta.week}`)]);
      L.rosters = rosters.map(r => ({ rid: r.roster_id, owner: r.owner_id, players: r.players || [], starters: r.starters || [],
        reserve: r.reserve || [], w: r.settings?.wins || 0, l: r.settings?.losses || 0, t: r.settings?.ties || 0,
        pf: (r.settings?.fpts || 0) + (r.settings?.fpts_decimal || 0) / 100, fab: r.settings?.waiver_budget_used || 0 }));
      L.users = users.map(u => ({ id: u.user_id, name: u.metadata?.team_name || u.display_name, handle: u.display_name }));
      L.matchups = mus.map(m => ({ rid: m.roster_id, mid: m.matchup_id, pts: m.points, pp: m.players_points || {}, st: m.starters || [] }));
      ok++;
    } catch { /* offline or sandboxed: keep the snapshot */ }
  }));
  if (ok) { S.liveAt = new Date().toISOString(); S.ctx = {}; }
  return ok;
}

// ---------------------------------------------------------------- player index + curves
let P = new Map();
function index() { P = new Map(S.D.players.map(p => [p.id, p])); }
const pl = id => P.get(id) || { id, n: `Player ${id}`, pos: '?', tm: '', wk: {}, ros: {}, lens: {}, sig: [], unknown: true };
function curvePts(pos, rank) {
  const c = S.D.model.ros_curve[pos]; if (!c) return 0;
  const xs = c.rank, ys = c.ppw;
  if (rank <= xs[0]) return ys[0];
  if (rank >= xs[xs.length - 1]) return ys[ys.length - 1];
  let i = 1; while (xs[i] < rank) i++;
  return ys[i - 1] + (ys[i] - ys[i - 1]) * (rank - xs[i - 1]) / (xs[i] - xs[i - 1]);
}
const now = () => Date.now();
const started = p => !!(p.wk && p.wk.ko && new Date(p.wk.ko).getTime() <= now());

// ---------------------------------------------------------------- league context + value model
function ctx(key) {
  if (S.ctx[key]) return S.ctx[key];
  const L = S.D.leagues.find(l => l.key === key);
  const cnt = s => L.slots.filter(x => x === s).length;
  const slots = { QB: cnt('QB'), RB: cnt('RB'), WR: cnt('WR'), TE: cnt('TE'), K: cnt('K'), DEF: cnt('DEF'),
    FLEX: cnt('FLEX') + cnt('WRRB_FLEX') + cnt('REC_FLEX'), SFLEX: cnt('SUPER_FLEX'), BN: cnt('BN') };
  const T = L.teams;
  const owner = new Map(); const rostered = new Set();
  for (const r of L.rosters) for (const id of [...r.players, ...r.reserve]) { owner.set(id, r.rid); rostered.add(id); }
  const me = L.rosters.find(r => r.owner === S.D.meta.user) || L.rosters[0];
  const users = new Map(L.users.map(u => [u.id, u]));
  const teamName = r => (users.get(r.owner) || {}).name || `Team ${r.rid}`;
  const c = { L, key, T, slots, owner, rostered, me, teamName, rosterOf: rid => L.rosters.find(r => r.rid === rid) };

  // starter lines on the calibrated curve (an ideal league filled by rank)
  const cnts = { QB: T * slots.QB, RB: T * slots.RB, WR: T * slots.WR, TE: T * slots.TE };
  let flexLast = null;
  for (let i = 0; i < T * slots.FLEX; i++) {
    let best = 'WR', bv = -1;
    for (const p of ['RB', 'WR', 'TE']) { const v = curvePts(p, cnts[p] + 1); if (v > bv) { bv = v; best = p; } }
    cnts[best]++; flexLast = curvePts(best, cnts[best]);
  }
  if (flexLast == null) flexLast = Math.min(curvePts('RB', cnts.RB), curvePts('WR', cnts.WR));
  // waiver lines: 50/50 of a ranked fill of every roster spot and the live free agents; top-3 average
  const n = T * (slots.QB + slots.RB + slots.WR + slots.TE + slots.FLEX + slots.SFLEX + slots.BN + 1);
  const order = S.D.players.filter(p => SKILL.includes(p.pos) && p.ros.ovr != null).sort((a, b) => a.ros.ovr - b.ros.ovr).slice(0, n);
  const first = { QB: 1, RB: 1, WR: 1, TE: 1 }; order.forEach(p => first[p.pos]++);
  const top3 = a => { const v = a.sort((x, y) => y - x).slice(0, 3); return v.length ? sum(v) / v.length : 0; };
  const ranked = ps => top3(ps.flatMap(p => [0, 1, 2].map(j => curvePts(p, first[p] + j))));
  const free = ps => top3(S.D.players.filter(p => ps.includes(p.pos) && !rostered.has(p.id)).map(p => p.ros.ppw || 0));
  const line = (ps, starter, nSlots, bonus = 0) => { const W = (ranked(ps) + free(ps)) / 2 + bonus; return { S: Math.max(starter, W), W, b: 1 - (1 - UNAVAIL) ** nSlots }; };
  // QBs: a team can stream the best free-agent QB each week, so both QB lines sit higher by the streaming gain
  // (measured 2024-25; conservative share because waiver picks happen before Sunday news).
  const qbBonus = slots.SFLEX ? 0 : (S.D.model.qb_stream_bonus || 0);
  c.lines = {
    QB: line(['QB'], curvePts('QB', cnts.QB), slots.QB + slots.SFLEX, qbBonus),
    TE: line(['TE'], curvePts('TE', cnts.TE), slots.TE),
    FLEX: line(['RB', 'WR', 'TE'], flexLast, 2 + slots.FLEX),
  };
  const curve = (e, d) => Math.max(0, e - d.S) + d.b * Math.max(0, Math.min(e, d.S) - d.W);
  const raw = p => {
    if (!SKILL.includes(p.pos)) return 0;
    const e = p.ros.ppw || 0;
    if (p.pos === 'QB') return curve(e, c.lines.QB);
    const v = curve(e, c.lines.FLEX);
    return p.pos === 'TE' ? Math.max(v, curve(e, c.lines.TE)) : v;
  };
  const top = Math.max(...S.D.players.map(raw), 1);
  c.scale = 100 / top;
  const cache = new Map();
  c.value = id => { if (!cache.has(id)) cache.set(id, raw(pl(id)) * c.scale); return cache.get(id); };
  c.budgetLeft = r => (L.budget || 100) - (r.fab || 0);
  let rankCache = null;
  c.rank = id => {
    if (!rankCache) { rankCache = new Map(S.D.players.filter(p => SKILL.includes(p.pos)).map(p => [p.id, c.value(p.id)]).sort((a, b) => b[1] - a[1]).map(([pid], i) => [pid, i + 1])); }
    return rankCache.get(id);
  };
  S.ctx[key] = c;
  return c;
}

// ---------------------------------------------------------------- lineups
function slotList(L) { return L.slots.filter(s => s !== 'BN'); }

/** Weekly lineup. players: ids on the active roster. current: Sleeper starters aligned with slotList. */
function weekLineup(L, players, current) {
  const slots = slotList(L);
  const assign = new Array(slots.length).fill(null);
  const used = new Set();
  current = current || [];
  slots.forEach((s, i) => { const id = current[i]; if (id && id !== '0' && started(pl(id))) { assign[i] = id; used.add(id); } });
  const pool = players.filter(id => !used.has(id) && !started(pl(id)));
  const mu = id => pl(id).wk?.mu ?? 0;
  const order = slots.map((s, i) => i).sort((a, b) => SLOT_ORDER.indexOf(slots[a]) - SLOT_ORDER.indexOf(slots[b]));
  for (const i of order) {
    if (assign[i]) continue;
    const e = ELIG[slots[i]] || [];
    let best = null;
    for (const id of pool) if (!used.has(id) && e.includes(pl(id).pos) && (best == null || mu(id) > mu(best))) best = id;
    if (best) { assign[i] = best; used.add(best); }
  }
  const bench = players.filter(id => !used.has(id));
  return { slots, assign, bench };
}

function lineupDist(L, rid, ids, week) {
  const m = (L.matchups || []).find(x => x.rid === rid) || { pp: {} };
  let mu = 0, v = 0;
  for (const id of ids) {
    if (!id || id === '0') continue;
    const p = pl(id);
    if (started(p)) mu += +(m.pp[id] ?? p.wk?.mu ?? 0);
    else { mu += p.wk?.mu ?? 0; v += (p.wk?.sd ?? 5) ** 2; }
  }
  return { mu, sd: Math.sqrt(v) };
}

/** Rest-of-season points per week of the best lineup (skill slots only). */
function rosLineup(L, ids) {
  const slots = slotList(L).filter(s => !['K', 'DEF'].includes(s));
  const used = new Set(); let tot = 0;
  const order = [...slots].sort((a, b) => SLOT_ORDER.indexOf(a) - SLOT_ORDER.indexOf(b));
  const ppw = id => pl(id).ros?.ppw ?? 0;
  const sorted = [...ids].sort((a, b) => ppw(b) - ppw(a));
  for (const s of order) {
    const e = ELIG[s] || [];
    const id = sorted.find(x => !used.has(x) && e.includes(pl(x).pos));
    if (id) { used.add(id); tot += ppw(id); }
  }
  return tot;
}

const winPill = p => {
  const pct = Math.round(p * 100);
  if (p >= 0.7) return `<span class="pill good">${pct}%</span>`;
  if (p >= 0.58) return `<span class="pill lean">${pct}%</span>`;
  return `<span class="pill flip">${pct}% · coin flip</span>`;
};
const pWin = (a, b) => Phi(((a.wk?.mu ?? 0) - (b.wk?.mu ?? 0)) / Math.sqrt((a.wk?.sd ?? 5) ** 2 + (b.wk?.sd ?? 5) ** 2));

// ---------------------------------------------------------------- shared renderers
function sigChips(p, max = 3) {
  const s = (p.sig || []).slice(0, max);
  if (!s.length) return '';
  return `<div class="sigs">${s.map(x => `<span class="sg ${x.d > 0 ? 'up' : x.d < 0 ? 'dn' : ''}" title="${esc(x.t)}">${x.d > 0 ? '▲ ' : x.d < 0 ? '▼ ' : ''}${esc(SIG_LABEL[x.k] || x.k)}</span>`).join('')}</div>`;
}
function dots(id) {
  const ks = S.D.leagues.filter(L => { const c = ctx(L.key); return c.owner.get(id) === c.me.rid; }).map(L => L.key);
  return ks.length ? `<span class="mine-dots">${ks.map(k => `<i class="${k}" title="Yours in ${k}"></i>`).join('')}</span>` : '';
}
function oppText(p) {
  if (p.bye) return 'Bye';
  if (!p.wk?.opp) return p.tm || 'FA';
  return `${p.wk.home ? 'vs' : '@'} ${p.wk.opp}${started(p) ? ' · locked' : p.wk.ko ? ' · ' + clock(p.wk.ko) : ''}`;
}
const posTag = p => `<span class="pos p${esc(p.pos)}">${esc(p.pos === 'DEF' ? 'DST' : p.pos)}</span>`;
const injTag = p => p.inj ? `<span class="inj">${esc(p.inj === 'Questionable' ? 'Q' : p.inj === 'Doubtful' ? 'D' : p.inj)}</span>` : '';
function rangeBar(p) {
  const mu = p.wk?.mu ?? 0, sd = p.wk?.sd ?? 0, max = 35;
  const lo = Math.max(0, mu - 1.28 * sd), hi = Math.min(max, mu + 1.28 * sd);
  return `<div class="range" aria-hidden="true"><i style="left:${lo / max * 100}%;width:${(hi - lo) / max * 100}%"></i><b style="left:calc(${Math.min(mu, max) / max * 100}% - 1px)"></b></div>`;
}

// ---------------------------------------------------------------- LINEUP tab
function renderLineup() {
  const c = ctx(S.league), L = c.L, me = c.me, wk = S.D.meta.week;
  const active = me.players.filter(id => !me.reserve.includes(id));
  const opt = weekLineup(L, active, me.starters);
  const myM = (L.matchups || []).find(m => m.rid === me.rid);
  const oppM = myM ? (L.matchups || []).find(m => m.mid === myM.mid && m.rid !== me.rid) : null;
  let score = '';
  if (oppM) {
    const opp = c.rosterOf(oppM.rid);
    const mine = lineupDist(L, me.rid, opt.assign, wk);
    const oppStarters = (oppM.st && oppM.st.length ? oppM.st : opp.starters);
    const theirs = lineupDist(L, opp.rid, oppStarters, wk);
    const p = Phi((mine.mu - theirs.mu) / Math.sqrt(mine.sd ** 2 + theirs.sd ** 2 || 1));
    score = `<div class="score">
      <div class="side"><div class="who">${esc(c.teamName(me))}</div><div class="pts">${f1(mine.mu)}</div><div class="sub">${me.w}–${me.l} · ± ${f1(mine.sd, 0)}</div></div>
      <div class="winp"><div class="big">${Math.round(p * 100)}%</div><div class="lbl">Win</div></div>
      <div class="side r"><div class="who">${esc(c.teamName(opp))}</div><div class="pts">${f1(theirs.mu)}</div><div class="sub">${opp.w}–${opp.l} · their set lineup</div></div>
      <div class="meter"><i style="width:${p * 100}%"></i></div></div>`;
  }
  // moves vs the lineup set in Sleeper
  const moves = [];
  opt.slots.forEach((s, i) => {
    const want = opt.assign[i], have = me.starters[i];
    if (!want || want === have) return;
    if (have && have !== '0' && started(pl(have))) return;
    if (opt.assign.includes(have) && have) return; // just moved to another slot
    const a = pl(want), b = have && have !== '0' ? pl(have) : null;
    moves.push(`<div class="move"><span class="verb">Start</span><div class="what"><b>${esc(a.n)}</b> ${posTag(a)} ${injTag(a)}${b ? ` over <b>${esc(b.n)}</b>` : ' in an empty slot'}
      <span class="why">${esc(SLOT_LABEL[s] || s)} · ${f1(a.wk.mu)} vs ${b ? f1(b.wk.mu) : '0.0'} projected</span></div>${b ? winPill(pWin(a, b)) : ''}</div>`);
  });
  const movesHtml = moves.length ? `<div class="moves">${moves.join('')}</div>`
    : `<div class="ok">Your Sleeper lineup matches the projections.</div>`;

  const rows = opt.slots.map((s, i) => {
    const id = opt.assign[i];
    if (!id) return `<div class="row"><div class="slot">${esc(SLOT_LABEL[s] || s)}</div><div class="who"><div class="nm">Empty</div></div><div></div></div>`;
    const p = pl(id), lock = started(p);
    const alts = opt.bench.filter(b => (ELIG[s] || []).includes(pl(b).pos) && !started(pl(b)) && (pl(b).wk?.mu ?? 0) > 0)
      .sort((a, b) => (pl(b).wk?.mu ?? 0) - (pl(a).wk?.mu ?? 0));
    const alt = alts[0] ? pl(alts[0]) : null;
    const vs = !lock && alt ? `<div class="vs">vs ${esc(alt.n)} ${f1(alt.wk.mu)} ${winPill(pWin(p, alt))}</div>` : '';
    const actual = lock && myM ? myM.pp[id] : null;
    return `<button class="row${lock ? ' locked' : ''}" data-p="${esc(id)}"><div class="slot">${esc(SLOT_LABEL[s] || s)}</div>
      <div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}</div>
      <div class="meta">${posTag(p)} ${esc(p.tm || '')} · ${esc(oppText(p))}${p.wk?.it ? ` · team ${f1(p.wk.it)}` : ''}</div>${lock ? '' : rangeBar(p)}${vs}${sigChips(p, 2)}</div>
      <div class="fig"><div class="v">${lock && actual != null ? f1(actual) : f1(p.wk?.mu)}</div><div class="u">${lock ? 'scored' : 'proj'}</div></div></button>`;
  }).join('');
  const bench = opt.bench.sort((a, b) => (pl(b).wk?.mu ?? 0) - (pl(a).wk?.mu ?? 0)).map(id => {
    const p = pl(id);
    return `<button class="row${started(p) ? ' locked' : ''}" data-p="${esc(id)}"><div class="slot">BN</div>
      <div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}</div><div class="meta">${posTag(p)} ${esc(p.tm || '')} · ${esc(oppText(p))}</div>${sigChips(p, 2)}</div>
      <div class="fig"><div class="v">${f1(p.wk?.mu)}</div><div class="u">proj</div></div></button>`;
  }).join('');
  const ir = me.reserve.map(id => { const p = pl(id); return `<button class="row locked" data-p="${esc(id)}"><div class="slot">IR</div><div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}</div><div class="meta">${posTag(p)} ${esc(p.tm || '')}</div></div><div class="fig"><div class="u">ROS ${f1(p.ros?.ppw)}/wk</div></div></button>`; }).join('');
  return `${score}
  <section class="sec"><h2>Changes for week ${wk}<span class="aside">vs the lineup set in Sleeper</span></h2>${movesHtml}</section>
  <section class="sec"><h2>Best lineup<span class="aside">blend of FantasyPros + Rotowire · bar = likely range</span></h2><div class="list">${rows}</div></section>
  <section class="sec"><h2>Bench</h2><div class="list">${bench || '<div class="empty">No bench players.</div>'}${ir ? `<div class="divider">Injured reserve</div>${ir}` : ''}</div></section>
  <p class="note">Win % compares each starter with the best bench option for that slot, using how far projections typically miss at that position (2024–25). Below 58% is a coin flip: go with your read. Locked players count what they have scored.</p>`;
}

// ---------------------------------------------------------------- WAIVERS tab
// Swap score: half the next three weeks (this week's blend, then Rotowire; byes count 0), half rest-of-season points/week.
const n3 = p => p.n3 ?? (p.wk?.mu ?? 0);
const rosW = p => p.ros?.ppw ?? 0;
const swapScore = p => 0.5 * n3(p) + 0.5 * rosW(p);
function bidRange(dRos, kind, left) {
  if (kind === 'short' && dRos < 0.5) return '$0–2';
  let lo, hi;
  if (dRos >= 4) [lo, hi] = [0.25, 0.4]; else if (dRos >= 2) [lo, hi] = [0.1, 0.25];
  else if (dRos >= 1) [lo, hi] = [0.03, 0.1]; else if (dRos >= 0.3) [lo, hi] = [0.01, 0.03]; else return '$0–1';
  const a = Math.max(1, Math.round(left * lo)), b = Math.max(a, Math.round(left * hi));
  return `$${a}–${b}`;
}
function waiverPlan(c) {
  const me = c.me, L = c.L;
  const irOk = new Set(L.ir_ok || ['IR', 'PUP']);
  let irFree = Math.max(0, (L.ir || 0) - me.reserve.length);
  const irMoves = [];
  let active = me.players.filter(id => !me.reserve.includes(id));
  for (const id of [...active].sort((a, b) => rosW(pl(b)) - rosW(pl(a)))) {
    if (irFree > 0 && irOk.has(pl(id).inj)) { irMoves.push(pl(id)); irFree--; }
  }
  const moved = new Set(irMoves.map(p => p.id));
  active = active.filter(id => !moved.has(id));
  const openSpots = Math.max(0, L.slots.length - active.length);
  const need = { QB: c.slots.QB, RB: c.slots.RB, WR: c.slots.WR, TE: c.slots.TE, K: c.slots.K, DEF: c.slots.DEF };
  const cap = { QB: c.slots.QB + c.slots.SFLEX + 1, TE: c.slots.TE + 1 };
  const count = {}; active.forEach(id => { const p = pl(id).pos; count[p] = (count[p] || 0) + 1; });
  const lineOf = p => p.pos === 'QB' ? c.lines.QB : p.pos === 'TE' ? { W: Math.min(c.lines.TE.W, c.lines.FLEX.W) } : c.lines.FLEX;
  const board = active.filter(id => SKILL.includes(pl(id).pos)).map(id => {
    const p = pl(id);
    return { p, swap: swapScore(p), below: rosW(p) < lineOf(p).W, needed: (count[p.pos] || 0) <= (need[p.pos] || 0), irElig: irOk.has(p.inj) };
  }).sort((a, b) => a.swap - b.swap);
  const dropFor = fa => {
    if (openSpots > 0) return null;
    const full = cap[fa.pos] != null && (count[fa.pos] || 0) >= cap[fa.pos];
    const d = board.find(x => full ? x.p.pos === fa.pos : (x.p.pos === fa.pos || !x.needed));
    return d ? d.p : undefined;
  };
  const cands = S.D.players.filter(p => SKILL.includes(p.pos) && !c.rostered.has(p.id) && !['IR', 'Out', 'Sus', 'PUP'].includes(p.inj))
    .sort((a, b) => swapScore(b) - swapScore(a)).slice(0, 40)
    .map(p => {
      const d = dropFor(p);
      if (d === undefined) return null;
      const dRos = rosW(p) - (d ? rosW(d) : 0), dN3 = n3(p) - (d ? n3(d) : 0);
      return { add: p, drop: d, dRos, dN3, dSwap: swapScore(p) - (d ? swapScore(d) : 0), kind: (dRos >= 1 || dRos >= dN3) ? 'hold' : 'short' };
    }).filter(Boolean).sort((a, b) => b.dSwap - a.dSwap).slice(0, 10);
  const streams = [];
  for (const pos of ['K', 'DEF']) {
    if (!need[pos]) continue;
    const have = active.filter(id => pl(id).pos === pos).sort((a, b) => (pl(b).wk?.mu ?? 0) - (pl(a).wk?.mu ?? 0))[0];
    const best = S.D.players.filter(p => p.pos === pos && !c.rostered.has(p.id) && !started(p)).sort((a, b) => (b.wk?.mu ?? 0) - (a.wk?.mu ?? 0))[0];
    if (best) streams.push({ add: best, drop: have ? pl(have) : null, d: (best.wk?.mu ?? 0) - (have ? pl(have).wk?.mu ?? 0 : 0) });
  }
  return { irMoves, board, cands, streams, openSpots };
}
const dcls = x => x > 0.25 ? 'pos-v' : x < -0.25 ? 'neg-v' : '';
const nxText = p => (p.nx && p.nx.length ? p.nx.map(x => f1(x)).join(' · ') : f1(p.wk?.mu));
function renderWaivers() {
  const c = ctx(S.league), L = c.L, me = c.me, weeks = S.D.meta.next_weeks || [S.D.meta.week];
  const left = c.budgetLeft(me);
  const plan = waiverPlan(c);
  const wkLbl = `wk ${weeks[0]}${weeks.length > 1 ? '–' + weeks[weeks.length - 1] : ''}`;
  const irRows = plan.irMoves.map(p => `<div class="move"><span class="verb">IR</span><div class="what">Move <b>${esc(p.n)}</b> ${posTag(p)} to IR
      <span class="why">${esc(p.inj)} · frees a roster spot without a drop</span></div><span></span></div>`).join('');
  const shown = S.wv.all ? plan.board : plan.board.slice(0, 6);
  const board = shown.map((x, i) => {
    const p = x.p, tags = [
      x.irElig ? '<span class="pill warn">IR-eligible</span>' : '',
      x.below ? '<span class="pill flip">below waiver line</span>' : '',
      x.needed ? `<span class="pill lean">needed at ${esc(p.pos)}</span>` : ''].join('');
    return `<button class="row" data-p="${esc(p.id)}"><div class="slot">#${i + 1}<small>${esc(p.pos)}</small></div>
      <div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}</div>
      <div class="meta">ROS ${f1(rosW(p))}/wk${p.ros?.ecr ? ` (${p.pos}${Math.round(p.ros.ecr)})` : ''} · ${wkLbl}: ${nxText(p)} · value ${f1(c.value(p.id))}</div>
      ${tags ? `<div class="sigs">${tags}</div>` : ''}</div>
      <div class="fig"><div class="v">${f1(x.swap)}</div><div class="u">swap</div></div></button>`;
  }).join('');
  const cand = x => {
    const verdict = x.dSwap > 0.25 ? (x.kind === 'hold' ? '<span class="pill good">Hold</span>' : '<span class="pill lean">Short-term</span>')
      : x.dSwap >= -0.25 ? '<span class="pill flip">Even</span>' : '<span class="pill bad">Worse</span>';
    return `<button class="row" data-p="${esc(x.add.id)}"><div class="slot">${posTag(x.add)}<small>${x.add.ros?.ecr ? '#' + Math.round(x.add.ros.ecr) : ''}</small></div>
      <div class="who"><div class="nm"><span class="tx">${esc(x.add.n)}</span>${injTag(x.add)}${x.add.ffb?.wv ? `<span class="pill ff">FF ${x.add.ffb.wv}</span>` : ''}</div>
      <div class="meta">${x.drop ? `for ${esc(x.drop.n)}` : 'into an open spot'} · ROS <span class="${dcls(x.dRos)}">${sgn(x.dRos)}</span>/wk · ${wkLbl} <span class="${dcls(x.dN3)}">${sgn(x.dN3)}</span>/wk</div>
      <div class="sigs">${verdict}${x.dSwap > 0.25 ? `<span class="pill lean">bid ${bidRange(x.dRos, x.kind, left)}</span>` : ''}${(x.add.sig || []).slice(0, 2).map(s => `<span class="sg ${s.d > 0 ? 'up' : s.d < 0 ? 'dn' : ''}">${s.d > 0 ? '▲ ' : s.d < 0 ? '▼ ' : ''}${esc(SIG_LABEL[s.k] || s.k)}</span>`).join('')}</div></div>
      <div class="fig"><div class="v ${dcls(x.dSwap)}">${sgn(x.dSwap)}</div><div class="u">swap</div></div></button>`;
  };
  const stream = x => `<button class="row" data-p="${esc(x.add.id)}"><div class="slot">${posTag(x.add)}</div><div class="who"><div class="nm"><span class="tx">${esc(x.add.n)}</span></div>
      <div class="meta">${esc(oppText(x.add))}${x.drop ? ` · vs your ${esc(x.drop.n)} ${f1(x.drop.wk?.mu)}` : ''}</div></div>
      <div class="fig"><div class="v ${dcls(x.d)}">${sgn(x.d)}</div><div class="u">this week</div></div></button>`;
  const pos = S.wv.pos, kd = pos === 'K' || pos === 'DEF';
  const list = S.D.players.filter(p => !c.rostered.has(p.id) && (pos === 'SKILL' ? SKILL.includes(p.pos) : p.pos === pos))
    .sort((a, b) => kd ? (b.wk?.mu ?? 0) - (a.wk?.mu ?? 0) : swapScore(b) - swapScore(a))
    .slice(0, 25).map(p => `<button class="row" data-p="${esc(p.id)}"><div class="slot">${posTag(p)}<small>${p.ros?.ecr ? '#' + Math.round(p.ros.ecr) : ''}</small></div>
      <div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}${p.ffb?.wv ? `<span class="pill ff">FF ${p.ffb.wv}</span>` : ''}</div>
      <div class="meta">${esc(p.tm || 'FA')} · ROS ${f1(rosW(p))}/wk · ${wkLbl}: ${nxText(p)}${p.mkt?.v ? ` · mkt ${kfmt(p.mkt.v)}` : ''}</div>${sigChips(p, 3)}</div>
      <div class="fig"><div class="v">${kd ? f1(p.wk?.mu) : f1(swapScore(p))}</div><div class="u">${kd ? 'proj' : 'swap'}</div></div></button>`).join('');
  const comps = (L.fab_wins || []).filter(x => x.bid > 0).sort((a, b) => b.w - a.w || b.bid - a.bid).slice(0, 10)
    .map(x => `<div class="row" style="cursor:default"><div class="slot">Wk ${x.w}</div><div class="who"><div class="nm"><span class="tx">${esc(pl(x.p).n)}</span></div><div class="meta">${posTag(pl(x.p))} · ROS now ${f1(rosW(pl(x.p)))}/wk</div></div><div class="fig"><div class="v">$${x.bid}</div></div></div>`).join('');
  const chips = ['SKILL', 'QB', 'RB', 'WR', 'TE', 'K', 'DEF'].map(k => `<button class="chip" data-wv="${k}" aria-pressed="${pos === k}">${k === 'SKILL' ? 'All' : k === 'DEF' ? 'DST' : k}</button>`).join('');
  return `${irRows ? `<section class="sec"><h2>Roster moves first</h2><div class="moves">${irRows}</div></section>` : ''}
  <section class="sec"><h2>Your drop order<span class="aside">weakest first · swap = ½ ${wkLbl} + ½ rest of season</span></h2>
    <div class="list">${board || '<div class="empty">No droppable players.</div>'}${plan.board.length > 6 ? `<button class="divider" data-wvall="1" style="width:100%;border:0;cursor:pointer;text-align:left">${S.wv.all ? 'Show weakest 6' : `Show all ${plan.board.length}`}</button>` : ''}</div></section>
  <section class="sec"><h2>Claim options<span class="aside">FAB left $${left} of $${L.budget || 100}${plan.openSpots ? ` · ${plan.openSpots} open spot${plan.openSpots > 1 ? 's' : ''}` : ''}</span></h2>
    <div class="list">${plan.cands.map(cand).join('') || '<div class="empty">No free agents at your weakest spots.</div>'}</div>
    <p class="note">Each free agent is paired with the weakest player you could drop for him (keeping enough starters at each position, and one backup at most at QB and TE). Deltas are points per week: rest of season, and the average over ${wkLbl}. "Hold" means he's better for the rest of the season (by 1+ pt/wk, or more than over the next few weeks); "Short-term" means the gain is mostly the next few weeks. Bid ranges follow the rest-of-season gain; short-term adds stay near $0.</p></section>
  <section class="sec"><h2>K / DST this week</h2><div class="list">${plan.streams.map(stream).join('') || '<div class="empty">No kicker or defense slots.</div>'}</div></section>
  <section class="sec"><h2>Best available</h2><div class="chips">${chips}</div><div class="list">${list || '<div class="empty">Nobody left.</div>'}</div></section>
  <section class="sec"><h2>Winning bids in ${esc(L.name)}</h2><div class="list">${comps || '<div class="empty">No paid claims yet this season.</div>'}</div></section>`;
}

// ---------------------------------------------------------------- TRADES tab
function teamProfile(c, r) {
  const ids = r.players.filter(id => SKILL.includes(pl(id).pos));
  const byPos = {}; for (const p of SKILL) byPos[p] = ids.filter(id => pl(id).pos === p).map(id => c.value(id)).sort((a, b) => b - a);
  return byPos;
}
function fitText(c, r) {
  const mine = teamProfile(c, c.me), theirs = teamProfile(c, r);
  const startN = { QB: c.slots.QB, RB: c.slots.RB + 1, WR: c.slots.WR + 1, TE: c.slots.TE };
  const str = (prof, p) => sum(prof[p].slice(0, startN[p]));
  const depth = (prof, p) => sum(prof[p].slice(startN[p], startN[p] + 2));
  const theirNeed = SKILL.map(p => [p, str(theirs, p) - str(mine, p)]).sort((a, b) => a[1] - b[1])[0];
  const theirDepth = SKILL.map(p => [p, depth(theirs, p)]).sort((a, b) => b[1] - a[1])[0];
  return `Needs ${theirNeed[0]} · deep ${theirDepth[0]}`;
}
function tradeEval(c, oppR, give, get) {
  const L = c.L, me = c.me;
  const myIds = me.players.filter(id => !me.reserve.includes(id));
  const thIds = oppR.players.filter(id => !oppR.reserve.includes(id));
  const myAfter = myIds.filter(id => !give.has(id)).concat([...get]);
  const thAfter = thIds.filter(id => !get.has(id)).concat([...give]);
  const cap = L.slots.length;
  const dropsFor = ids => { const extra = ids.length - cap; if (extra <= 0) return []; return [...ids].filter(id => SKILL.includes(pl(id).pos)).sort((a, b) => c.value(a) - c.value(b)).slice(0, extra); };
  const myDrops = dropsFor(myAfter), thDrops = dropsFor(thAfter);
  const val = ids => sum([...ids].map(id => c.value(id)));
  const vIn = val(get), vOut = val(give);
  const valueDelta = vIn - vOut - val(myDrops);
  const myL = rosLineup(L, myAfter.filter(id => !myDrops.includes(id))) - rosLineup(L, myIds);
  const thL = rosLineup(L, thAfter.filter(id => !thDrops.includes(id))) - rosLineup(L, thIds);
  const mk = id => (c.T >= 10 ? pl(id).mkt?.v : (pl(id).mkt?.v8 ?? pl(id).mkt?.v)) || 0;
  const mIn = sum([...get].map(mk)), mOut = sum([...give].map(mk));
  const lens = id => pl(id).lens?.rw_ppw || 0;
  const sIn = sum([...get].map(lens)), sOut = sum([...give].map(lens));
  return { vIn, vOut, valueDelta, myL, thL, mIn, mOut, sIn, sOut, myDrops, thDrops };
}
function tradeIdeas(c, oppR) {
  const me = c.me, out = [];
  const mine = me.players.filter(id => SKILL.includes(pl(id).pos) && !me.reserve.includes(id) && c.value(id) > 0.5);
  const theirs = oppR.players.filter(id => SKILL.includes(pl(id).pos) && !oppR.reserve.includes(id) && c.value(id) > 0.5);
  for (const a of mine) for (const b of theirs) {
    const e = tradeEval(c, oppR, new Set([a]), new Set([b]));
    const mkFair = e.mOut >= e.mIn * 0.95 && e.mIn > 0;
    if (e.myL > 0.15 && (e.thL > -0.05 || mkFair) && e.valueDelta > -3) out.push({ give: [a], get: [b], e, why: e.thL > -0.05 ? 'Both lineups improve' : 'Market sees it as fair' });
  }
  out.sort((x, y) => (y.e.myL + y.e.valueDelta / 20) - (x.e.myL + x.e.valueDelta / 20));
  const seenGet = new Map(), seenGive = new Map(), pick = [];
  for (const x of out) {   // variety: each target and each chip at most twice
    const g = x.get[0], v = x.give[0];
    if ((seenGet.get(g) || 0) >= 1 || (seenGive.get(v) || 0) >= 2) continue;
    seenGet.set(g, (seenGet.get(g) || 0) + 1); seenGive.set(v, (seenGive.get(v) || 0) + 1); pick.push(x);
    if (pick.length >= 6) break;
  }
  return pick;
}
function renderTrades() {
  const c = ctx(S.league), L = c.L, me = c.me, T = S.trade;
  const others = L.rosters.filter(r => r.rid !== me.rid);
  if (!T.opp || !others.find(r => r.rid === T.opp)) { T.opp = others[0]?.rid; T.give.clear(); T.get.clear(); }
  const opp = c.rosterOf(T.opp);
  const teams = others.map(r => `<button class="team" data-opp="${r.rid}" aria-pressed="${r.rid === T.opp}"><span class="tn">${esc(c.teamName(r))}</span><span class="tr">${r.w}–${r.l}${r.t ? '–' + r.t : ''} · ${f1(r.pf, 0)} pts</span><span class="fit">${esc(fitText(c, r))}</span></button>`).join('');
  const side = (r, set, key, title) => {
    const ids = r.players.filter(id => T.showKD || SKILL.includes(pl(id).pos)).sort((a, b) => c.value(b) - c.value(a));
    return `<div class="list"><div class="side-h"><h3>${esc(title)}</h3><span>${esc(c.teamName(r))}</span></div>${ids.map(id => {
      const p = pl(id), on = set.has(id);
      return `<button class="row pbtn${on ? ' picked' : ''}" data-t="${key}" data-id="${esc(id)}" aria-pressed="${on}"><div class="slot"><span class="check">✓</span></div>
        <div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}${r.reserve.includes(id) ? '<span class="pill warn">IR</span>' : ''}</div>
        <div class="meta">${posTag(p)} <span class="m-long">${esc(p.tm || '')} · </span>${f1(p.ros?.ppw)}/wk<span class="m-long"> · Sleeper ${p.lens?.rk ? p.pos + p.lens.rk : '–'} · mkt ${kfmt(p.mkt?.v)}</span></div>${sigChips(p, 2)}</div>
        <div class="fig"><div class="v">${f1(c.value(id))}</div><div class="u">value</div></div></button>`; }).join('')}</div>`;
  };
  let verdict = '';
  if (T.give.size || T.get.size) {
    const e = tradeEval(c, opp, T.give, T.get);
    const cls = x => x > 0.05 ? 'pos-v' : x < -0.05 ? 'neg-v' : '';
    const mDelta = e.mIn - e.mOut;
    const drops = [...e.myDrops.map(id => `you drop ${pl(id).n}`), ...e.thDrops.map(id => `they drop ${pl(id).n}`)];
    verdict = `<div class="verdict" aria-live="polite"><div class="vhead"><strong>${e.valueDelta > 2 && e.myL >= 0 ? 'Good for you' : e.valueDelta < -2 ? 'You lose value' : 'Close to even'}</strong><button class="linkbtn" data-clear="1">Clear</button></div>
      <div class="vgrid">
        <div class="vcell"><div class="k">Value</div><div class="v ${cls(e.valueDelta)}">${sgn(e.valueDelta)}</div><div class="s">${f1(e.vIn)} in · ${f1(e.vOut)} out</div></div>
        <div class="vcell"><div class="k">Your lineup</div><div class="v ${cls(e.myL)}">${sgn(e.myL)}</div><div class="s">pts per week, rest of season</div></div>
        <div class="vcell"><div class="k">Their lineup</div><div class="v ${cls(e.thL)}">${sgn(e.thL)}</div><div class="s">${e.thL >= 0 ? 'they improve too' : 'they get worse'}</div></div>
        <div class="vcell"><div class="k">Market</div><div class="v ${cls(mDelta)}">${mDelta >= 0 ? '+' : '−'}${kfmt(Math.abs(mDelta))}</div><div class="s">FantasyCalc · ${mDelta <= 0 ? 'looks fair to them' : 'they may balk'}</div></div>
      </div>
      <div class="note">FantasyPros overall: you get ${[...T.get].map(id => `${esc(pl(id).n.split(' ').slice(-1)[0])} #${pl(id).ros?.ovr ? Math.round(pl(id).ros.ovr) : '–'}`).join(', ') || '–'}; you give ${[...T.give].map(id => `${esc(pl(id).n.split(' ').slice(-1)[0])} #${pl(id).ros?.ovr ? Math.round(pl(id).ros.ovr) : '–'}`).join(', ') || '–'}. On Sleeper's projections they see ${sgn(e.sOut - e.sIn)} pts/wk for their side.${drops.length ? ' Roster limit: ' + esc(drops.join('; ')) + '.' : ''}</div></div>`;
  }
  S._ideas = tradeIdeas(c, opp);
  const ideas = S._ideas.map((x, i) => `<button class="idea" data-idea="${i}"><div><span class="give">Give ${esc(x.give.map(id => pl(id).n).join(' + '))}</span> · <span class="get">Get ${esc(x.get.map(id => pl(id).n).join(' + '))}</span>
      <div class="meta">${esc(x.why)} · your lineup ${sgn(x.e.myL)}/wk · theirs ${sgn(x.e.thL)}/wk</div></div><span class="pill ${x.e.valueDelta >= 0 ? 'good' : 'lean'}">${sgn(x.e.valueDelta)}</span></button>`);
  return `<section class="sec"><h2>Trade partner<span class="aside">needs compare their starters with yours</span></h2><div class="teams">${teams}</div></section>
  <section class="sec"><h2>Ideas with ${esc(c.teamName(opp))}<span class="aside">one-for-one swaps</span></h2><div class="list">${ideas.join('') || '<div class="empty">No swap improves your lineup without hurting theirs. Try a two-for-one below.</div>'}</div></section>
  <section class="sec"><h2>Build a trade<span class="aside"><button class="linkbtn" data-kd="1">${T.showKD ? 'Hide' : 'Show'} K / DST</button></span></h2>
    <div class="sides">${side(me, T.give, 'give', 'You give')}${side(opp, T.get, 'get', 'You get')}</div></section>
  ${verdict}
  <p class="note">Value uses rest-of-season points in this league's format. Lineup change re-optimizes both starting lineups after the trade, including any drops the roster limit forces. Market is FantasyCalc (real trades). Sleeper's projections are what your trade partner sees in the app.</p>`;
}

// ---------------------------------------------------------------- VALUES tab
/** FantasyPros overall ROS rank, flagged when this league's value rank sits far from it. */
function fpCell(p, c) {
  const fp = p.ros?.ovr; if (fp == null) return '<td class="zero">–</td>';
  const ours = c.rank(p.id), gap = ours - fp;
  const big = ours <= 150 && Math.abs(gap) >= Math.max(15, 0.5 * Math.min(ours, fp));
  const tag = big ? `<span class="pill ${gap < 0 ? 'good' : 'warn'}" title="Our ${esc(c.L.name)} rank #${ours}">${gap < 0 ? 'we ▲' : 'we ▼'} #${ours}</span>` : '';
  return `<td>${Math.round(fp)}${tag ? ' ' + tag : ''}</td>`;
}
function renderValues() {
  const v = S.vals, cur = ctx(S.league);
  const all = S.D.leagues.map(L => ctx(L.key));
  let rows = S.D.players.filter(p => SKILL.includes(p.pos));
  if (v.pos !== 'ALL') rows = rows.filter(p => p.pos === v.pos);
  if (v.filter === 'mine') rows = rows.filter(p => all.some(c => c.owner.get(p.id) === c.me.rid));
  if (v.filter === 'fa') rows = rows.filter(p => !cur.rostered.has(p.id));
  if (v.q) rows = rows.filter(p => p.n.toLowerCase().includes(v.q));
  rows = rows.filter(p => all.some(c => c.value(p.id) >= 0.5) || all.some(c => c.owner.get(p.id) === c.me.rid))
    .sort((a, b) => cur.value(b.id) - cur.value(a.id) || (b.ros.ppw ?? 0) - (a.ros.ppw ?? 0)).slice(0, 220);
  const head = S.D.leagues.map(L => `<th class="${L.key}">${esc(L.name)}</th>`).join('');
  const body = rows.map(p => {
    const cells = all.map(c => { const val = c.value(p.id), mine = c.owner.get(p.id) === c.me.rid, fa = !c.rostered.has(p.id);
      return `<td class="${c.key}${mine ? ' mine' : ''}${c.key === S.league ? ' cur' : ''}"><span class="${val < 0.5 ? 'zero' : ''}">${f1(val)}</span>${fa ? '<span class="fa">FA</span>' : ''}</td>`; }).join('');
    return `<tr data-p="${esc(p.id)}"><td class="l pl"><div class="nm"><span class="tx">${esc(p.n)}</span>${dots(p.id)}${injTag(p)}</div><div class="meta">${posTag(p)}${p.ros.ecr ? Math.round(p.ros.ecr) : ''} · ${esc(p.tm || 'FA')}</div></td>
      <td>${f1(p.ros.ppw)}</td>${fpCell(p, cur)}${cells}<td>${kfmt(p.mkt?.v)}</td><td>${p.lens?.rk ? p.pos + p.lens.rk : '–'}</td><td>${f1(p.lens?.rw_ppw)}</td></tr>`;
  }).join('');
  const chips = ['ALL', 'QB', 'RB', 'WR', 'TE'].map(k => `<button class="chip" data-vpos="${k}" aria-pressed="${v.pos === k}">${k === 'ALL' ? 'All' : k}</button>`).join('')
    + `<button class="chip" data-vf="mine" aria-pressed="${v.filter === 'mine'}">Mine</button><button class="chip" data-vf="fa" aria-pressed="${v.filter === 'fa'}">Free in ${esc(cur.L.name)}</button>`
    + `<input class="search" id="vq" type="search" placeholder="Find a player" aria-label="Find a player" value="${esc(v.q)}">`;
  return `<section class="sec"><h2>Values<span class="aside">sorted by ${esc(cur.L.name)} · 100 = best player</span></h2><div class="chips">${chips}</div>
    <div class="scroll"><table class="t"><thead><tr><th class="l">Player</th><th>ROS/wk</th><th>FP #</th>${head}<th>Market</th><th>Sleeper</th><th>Sleeper proj</th></tr></thead><tbody>${body}</tbody></table></div>
    <p class="note">ROS/wk is expected points per remaining week at the player's FantasyPros rest-of-season rank, calibrated on what players at that rank actually scored in 2024–25. League values sit at zero on each league's waiver line; quarterback lines include the points a team gets by streaming free-agent QBs. FP # is FantasyPros' overall rest-of-season rank (a generic 12-team league); the tag flags players we rank far higher or lower in this league. Sleeper columns show what leaguemates see: season finish so far and Rotowire's projection per remaining week.</p></section>`;
}

// ---------------------------------------------------------------- SIGNALS tab
function renderSignals() {
  const c = ctx(S.league);
  const withSig = S.D.players.filter(p => p.sig && p.sig.length);
  const mine = withSig.filter(p => c.owner.get(p.id) === c.me.rid);
  const fa = withSig.filter(p => !c.rostered.has(p.id) && (c.value(p.id) >= 0.5 || (p.wk?.mu ?? 0) >= 7 || p.sig.some(s => s.k === 'hot' && s.d > 0)))
    .sort((a, b) => c.value(b.id) - c.value(a.id));
  const others = withSig.filter(p => c.rostered.has(p.id) && c.owner.get(p.id) !== c.me.rid && c.value(p.id) >= 3 && p.sig.some(s => ['late', 'ros', 'mkt', 'snap', 'split'].includes(s.k)))
    .sort((a, b) => c.value(b.id) - c.value(a.id)).slice(0, 25);
  const item = (p, extra = '') => `<button class="row" data-p="${esc(p.id)}"><div class="slot">${posTag(p)}</div><div class="who"><div class="nm"><span class="tx">${esc(p.n)}</span>${injTag(p)}</div>${extra ? `<div class="meta">${esc(extra)}</div>` : ''}
      ${p.sig.map(s => `<div class="meta"><span class="sg ${s.d > 0 ? 'up' : s.d < 0 ? 'dn' : ''}">${s.d > 0 ? '▲ ' : s.d < 0 ? '▼ ' : ''}${esc(SIG_LABEL[s.k] || s.k)}</span> ${esc(s.t)}</div>`).join('')}</div>
      <div class="fig"><div class="v">${f1(c.value(p.id))}</div><div class="u">value</div></div></button>`;
  const owner = p => { const r = c.rosterOf(c.owner.get(p.id)); return r ? c.teamName(r) : ''; };
  return `<section class="sec"><h2>Your players<span class="aside">${esc(c.L.name)}</span></h2><div class="list">${mine.map(item).join('') || '<div class="empty">Nothing new on your roster.</div>'}</div></section>
  <section class="sec"><h2>Free agents moving</h2><div class="list">${fa.slice(0, 25).map(item).join('') || '<div class="empty">No free agents with signals.</div>'}</div></section>
  <section class="sec"><h2>On other rosters<span class="aside">trade timing</span></h2><div class="list">${others.map(p => item(p, owner(p))).join('') || '<div class="empty">Quiet.</div>'}</div></section>
  <p class="note">Signals flag change before the consensus catches up: late FantasyPros moves (they tend to continue into Sunday), 7-day rest-of-season moves, Rotowire and FantasyPros disagreeing, FantasyCalc market swings, Sleeper-wide adds and drops, snap-share jumps, fresh injury news, and Footballers vs consensus. They never change values on their own.</p>`;
}

// ---------------------------------------------------------------- sheets
function openSheet(html) {
  closeSheet();
  const scrim = document.createElement('div'); scrim.className = 'scrim'; scrim.addEventListener('click', closeSheet);
  const sh = document.createElement('div'); sh.className = 'sheet'; sh.setAttribute('role', 'dialog'); sh.setAttribute('aria-modal', 'true');
  sh.innerHTML = `<div class="grab"></div><button class="close" data-close="1">Close</button>${html}`;
  document.body.append(scrim, sh);
  sh.querySelector('[data-close]').focus();
}
function closeSheet() { document.querySelectorAll('.scrim,.sheet').forEach(n => n.remove()); }
function playerSheet(id) {
  const p = pl(id);
  const own = S.D.leagues.map(L => { const c = ctx(L.key); const rid = c.owner.get(id); const r = rid != null ? c.rosterOf(rid) : null;
    return `<div><div class="k" style="color:var(--${L.key})">${esc(L.name)}</div><div class="v">${f1(c.value(id))}</div><div class="s">${r ? (r.rid === c.me.rid ? 'Yours' : esc(c.teamName(r))) : 'Free agent'}</div></div>`; }).join('');
  const w = p.wk || {};
  openSheet(`<h3>${esc(p.n)}</h3><div class="sub">${posTag(p)} · ${esc(p.tm || 'FA')}${p.age ? ' · age ' + p.age : ''}${p.inj ? ' · ' + esc(p.inj) : ''}</div>
    <h4>Week ${S.D.meta.week} · ${esc(oppText(p))}</h4>
    <div class="kv"><div><div class="k">Projection</div><div class="v">${f1(w.mu)}</div><div class="s">likely ${f1(Math.max(0, (w.mu ?? 0) - 1.28 * (w.sd ?? 0)))}–${f1((w.mu ?? 0) + 1.28 * (w.sd ?? 0))}</div></div>
      <div><div class="k">FantasyPros</div><div class="v">${f1(w.fp)}</div><div class="s">${w.ecr ? `${p.pos}${Math.round(w.ecr)} (${w.best}–${w.worst})` : 'unranked'}</div></div>
      <div><div class="k">Rotowire</div><div class="v">${f1(w.rw)}</div><div class="s">${w.it ? `team total ${f1(w.it)}` : '&nbsp;'}</div></div></div>
    <h4>Rest of season</h4>
    <div class="kv"><div><div class="k">Points / week</div><div class="v">${f1(p.ros?.ppw)}</div><div class="s">${p.ros?.ecr ? `FantasyPros ${p.pos}${f1(p.ros.ecr)}` : 'from Rotowire'}</div></div>
      <div><div class="k">Sleeper season</div><div class="v">${p.lens?.rk ? p.pos + p.lens.rk : '–'}</div><div class="s">${f1(p.lens?.pts)} pts in ${p.lens?.gp ?? 0} games</div></div>
      <div><div class="k">Market</div><div class="v">${kfmt(p.mkt?.v)}</div><div class="s">${p.mkt?.trend ? `30-day ${p.mkt.trend > 0 ? '+' : ''}${kfmt(p.mkt.trend)}` : 'FantasyCalc'}</div></div></div>
    <h4>By league</h4><div class="kv">${own}</div>
    ${p.snap ? `<h4>Snap share</h4><div class="sub">${p.snap.map(x => x + '%').join(' → ')}</div>` : ''}
    ${p.sig?.length ? `<h4>Signals</h4><ul>${p.sig.map(s => `<li>${esc(s.t)}</li>`).join('')}</ul>` : ''}
    ${p.ffb ? `<h4>Fantasy Footballers</h4><div class="sub">${p.ffb.wk ? `Weekly ${p.pos}${p.ffb.wk}` : ''}${p.ffb.wv ? ` Waiver list #${p.ffb.wv}` : ''}</div>` : ''}`);
}
function infoSheet() {
  const m = S.D.meta, repo = m.repo || 'luke-benham/FantasyTools', wk = m.week;
  openSheet(`<h3>Data &amp; inputs</h3><div class="sub">Engine run ${esc(clock(m.generated))} (${esc(ago(m.generated))}) · rosters ${S.liveAt ? 'live from Sleeper' : 'from that run'}</div>
    <h4>Sources</h4><ul>
      <li>FantasyPros consensus (weekly + rest of season), scraped ${esc(m.fp_scrape || '–')}; late moves measured from ${esc(clock(m.late_move_base))}</li>
      <li>Rotowire projections and season stats via Sleeper</li><li>FantasyCalc trade market · nflverse schedule, Vegas lines, snap counts</li>
      <li>Fantasy Footballers: ${m.footballers?.length ? esc(m.footballers.join(', ')) : 'nothing pasted for week ' + wk}</li></ul>
    <h4>Paste Fantasy Footballers</h4>
    <p class="note">Paste the waiver list (as copied off their page) or weekly ranks (lines like "WR12 Name"). Save opens GitHub with the file filled in; commit it and the next refresh picks it up.</p>
    <p><select id="fbk" class="search" style="max-width:none"><option value="waivers">Waiver list</option><option value="ranks">Weekly ranks</option></select></p>
    <textarea id="fbt" class="paste" placeholder="Paste here"></textarea>
    <p style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn" id="fbsave" href="https://github.com/${esc(repo)}/tree/main/inputs/footballers" target="_blank" rel="noopener">Save to GitHub</a>
      <a class="btn ghost" href="https://github.com/${esc(repo)}/actions/workflows/refresh.yml" target="_blank" rel="noopener">Run a refresh</a></p>
    <h4>How the numbers work</h4><ul>
      <li>Weekly projection: 50/50 blend of FantasyPros and Rotowire, nudged toward late-week FantasyPros moves. In 2024–25 tests the blend was never worse than either source and best at RB and QB.</li>
      <li>Rest of season: points per week at the FantasyPros ROS rank, from what players at that rank actually scored in 2024–25 (injuries included).</li>
      <li>League value: points above each league's starter and waiver lines; bench-level points count by the chance a lineup spot opens (15% a week per slot).</li></ul>`);
  const upd = () => {
    const kind = $('#fbk').value, txt = $('#fbt').value.trim();
    $('#fbsave').href = txt ? `https://github.com/${repo}/new/main/inputs/footballers?filename=${encodeURIComponent(`wk${wk}_${kind}.txt`)}&value=${encodeURIComponent(txt)}`
      : `https://github.com/${repo}/tree/main/inputs/footballers`;
  };
  $('#fbt').addEventListener('input', upd); $('#fbk').addEventListener('change', upd);
}

// ---------------------------------------------------------------- shell
function renderHeader() {
  const m = S.D.meta;
  const age = (Date.now() - new Date(m.generated).getTime()) / 3.6e6;
  $('#stamp').innerHTML = `<span class="dot ${age > 36 ? 'old' : age > 14 ? 'stale' : ''}"></span>Wk ${m.week} · ${esc(ago(m.generated))}${S.liveAt ? ' · live' : ''}`;
  $('#leagues').innerHTML = S.D.leagues.map(L => { const c = ctx(L.key), r = c.me;
    return `<button class="lg-btn" data-lg="${L.key}" style="--c:var(--${L.key})" aria-pressed="${S.league === L.key}"><span class="ln">${esc(L.name)}</span><span class="lr">${r.w}–${r.l} · ${esc(c.teamName(r))}</span></button>`; }).join('');
  document.documentElement.dataset.league = S.league;
  document.querySelectorAll('.tab').forEach(t => t.setAttribute('aria-selected', String(t.dataset.tab === S.tab)));
}
const VIEWS = { lineup: renderLineup, waivers: renderWaivers, trades: renderTrades, values: renderValues, signals: renderSignals };
function render() {
  renderHeader();
  const main = $('#main');
  const y = window.scrollY;
  main.innerHTML = VIEWS[S.tab]();
  if (S._keepScroll) window.scrollTo(0, y); S._keepScroll = false;
  const q = $('#vq'); if (q && S._focusQ) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); S._focusQ = false; }
}

function wire() {
  document.addEventListener('click', ev => {
    const t = ev.target.closest('button, [data-p], tr[data-p]');
    if (!t) return;
    const d = t.dataset;
    if (d.lg) { S.league = d.lg; store.set('league', S.league); S.trade.give.clear(); S.trade.get.clear(); S.trade.opp = null; render(); return; }
    if (d.tab) { S.tab = d.tab; store.set('tab', S.tab); history.replaceState(null, '', '#' + S.tab); render(); window.scrollTo(0, 0); return; }
    if (d.close) { closeSheet(); return; }
    if (d.info) { infoSheet(); return; }
    if (d.wvall) { S.wv.all = !S.wv.all; S._keepScroll = true; render(); return; }
    if (d.wv) { S.wv.pos = d.wv; S._keepScroll = true; render(); return; }
    if (d.vpos) { S.vals.pos = d.vpos; S._keepScroll = true; render(); return; }
    if (d.vf) { S.vals.filter = S.vals.filter === d.vf ? 'all' : d.vf; S._keepScroll = true; render(); return; }
    if (d.opp) { S.trade.opp = +d.opp; S.trade.give.clear(); S.trade.get.clear(); S._keepScroll = true; render(); return; }
    if (d.t) { const set = d.t === 'give' ? S.trade.give : S.trade.get; set.has(d.id) ? set.delete(d.id) : set.add(d.id); S._keepScroll = true; render(); return; }
    if (d.clear) { S.trade.give.clear(); S.trade.get.clear(); S._keepScroll = true; render(); return; }
    if (d.kd) { S.trade.showKD = !S.trade.showKD; S._keepScroll = true; render(); return; }
    if (d.idea != null) { const x = S._ideas[+d.idea]; S.trade.give = new Set(x.give); S.trade.get = new Set(x.get); S._keepScroll = true; render(); return; }
    if (d.p) { playerSheet(d.p); return; }
  });
  document.addEventListener('input', ev => { if (ev.target.id === 'vq') { S.vals.q = ev.target.value.trim().toLowerCase(); S._keepScroll = true; S._focusQ = true; render(); } });
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') closeSheet(); });
  document.addEventListener('visibilitychange', async () => { if (document.visibilityState === 'visible' && S.D && (!S.liveAt || Date.now() - new Date(S.liveAt) > 120000)) { if (await refreshLive()) render(); } });
}

async function boot() {
  wire();
  try { S.D = await loadData(); } catch (e) {
    $('#main').innerHTML = `<div class="empty">Couldn't load data files. Check that the latest refresh finished, then reload.</div>`; return;
  }
  index();
  const saved = store.get('league', null); if (saved && S.D.leagues.some(l => l.key === saved)) S.league = saved;
  const hash = location.hash.replace('#', ''); S.tab = VIEWS[hash] ? hash : store.get('tab', 'lineup'); if (!VIEWS[S.tab]) S.tab = 'lineup';
  render();
  if (await refreshLive()) render();
  if ('serviceWorker' in navigator && location.protocol === 'https:' && !document.getElementById('fo-data')) navigator.serviceWorker.register('sw.js').catch(() => {});
}
boot();
})();
