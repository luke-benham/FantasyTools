"""keeper_backtest.py — evidence for the Maywood keeper value model (run 2026-11-02).

Question: in November, how well can we predict where a player will be drafted next August, and what is a
draft pick worth?  Five seasons of FantasyPros history (Nov 2020 -> Aug 2021 ... Nov 2024 -> Aug 2025).

DATA SETUP (run from a folder holding these files):
  ecr_sub.csv   <- rows of dynastyprocess/data files/db_fpecr.csv.gz with page_type dynasty-overall or
                   redraft-overall (fp_page ppr-cheatsheets = preseason, ros-ppr-overall = rest of season)
                   columns: date,page_type,fp_page,id,player,pos,team,ecr
  ids.csv       <- dynastyprocess/data files/db_playerids.csv
  stats_{Y}.json<- https://api.sleeper.app/stats/nfl/{Y}?season_type=regular&position[]=QB&...TE  (Y = 2021..2025)
  picks_{Y}.json<- https://api.sleeper.app/v1/draft/{maywood draft id}/picks  (Y = 2024, 2025)

Usage: python keeper_backtest.py <path to engine/calibration.json>
Writes keeper_model.json (the fitted numbers the engine uses) next to the data and prints the tables.
"""
import csv, json, math, collections, statistics as st, sys, datetime as dt

SKILL = ("QB", "RB", "WR", "TE")
YEARS = [2020, 2021, 2022, 2023, 2024]          # November of Y -> August of Y+1
POOL = 200                                       # players in the November top-200 (skill only)
MISS = 300                                       # rank given to players who fall out of a list
AGE_BUCKETS = [(0, 23, "≤23"), (24, 25, "24–25"), (26, 27, "26–27"), (28, 29, "28–29"), (30, 99, "30+")]
TEAMS, STARTERS = 10, {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2}
QB_STREAM = json.load(open(sys.argv[1]))["qb_stream_bonus"] * 17 if len(sys.argv) > 1 else 0.0   # engine/calibration.json
PICKS = TEAMS * 17                               # 170: end of a Maywood draft = waiver line


def bucket(age):
    for lo, hi, lab in AGE_BUCKETS:
        if lo <= age <= hi:
            return lab
    return AGE_BUCKETS[-1][2]


def rankdata(v):
    order = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            r[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return r


def spearman(a, b):
    return st.correlation(rankdata(a), rankdata(b))


# ---------------------------------------------------------------- load
ids, born, idpos = {}, {}, {}
for r in csv.DictReader(open("ids.csv")):
    f = r["fantasypros_id"]
    if f in ("", "NA"):
        continue
    if r["sleeper_id"] not in ("", "NA"):
        ids[f] = r["sleeper_id"]
    if r["birthdate"] not in ("", "NA"):
        born[f] = dt.date.fromisoformat(r["birthdate"][:10])
    idpos[f] = r["position"]

pages = collections.defaultdict(dict)       # (kind, date) -> {fpid: (ecr, pos)}
for r in csv.DictReader(open("ecr_sub.csv")):
    kind = {"dynasty-overall": "dyn"}.get(r["page_type"]) or ("pre" if "cheatsheets" in r["fp_page"] else
                                                               "ros" if "ros-ppr" in r["fp_page"] else None)
    pos = r["pos"].rstrip("0123456789")
    if kind and pos in SKILL and r["ecr"] not in ("", "NA"):
        pages[(kind, r["date"])][r["id"]] = (float(r["ecr"]), pos)


def snap(kind, year, month, last=False):
    ds = sorted(d for k, d in pages if k == kind and d.startswith(f"{year}-{month:02d}"))
    if month == 8:
        ds = [d for d in ds if d <= f"{year}-08-31"]
    return (ds[-1] if last else ds[0]) if ds else None


def skill_rank(page):
    """Re-rank one list among skill players only (K/DST removed), ties by ECR order."""
    order = sorted(page, key=lambda f: page[f][0])
    return {f: i + 1 for i, f in enumerate(order)}


points = {}
for Y in range(2021, 2026):
    pts = {}
    for row in json.load(open(f"stats_{Y}.json")):
        pts[row["player_id"]] = (row.get("stats") or {}).get("pts_ppr") or 0.0
    points[Y] = pts


def age_on(f, d):
    b = born.get(f)
    return None if not b else (d - b).days / 365.25


# ---------------------------------------------------------------- 1. Nov -> Aug price prediction
print("=" * 78)
print("1. Predicting next August's draft price from November rankings")
print("=" * 78)
rows = []   # one per player-year
for Y in YEARS:
    dn, rn, an = snap("dyn", Y, 11), snap("ros", Y, 11), snap("pre", Y + 1, 8, last=True)
    if not (dn and an):
        print("skip", Y, dn, rn, an); continue
    D, A = skill_rank(pages[("dyn", dn)]), skill_rank(pages[("pre", an)])
    R = skill_rank(pages[("ros", rn)]) if rn else {}
    ref = dt.date(Y + 1, 8, 15)
    print(f"  {Y}: dynasty {dn}, ROS {rn or '—'}, preseason {an}")
    for f, d in D.items():
        if d > POOL:
            continue
        a = age_on(f, ref)
        if a is None:
            continue
        pos = pages[("dyn", dn)][f][1]
        rows.append({"Y": Y, "f": f, "pos": pos, "age": a, "b": bucket(int(a)), "D": d, "R": R.get(f, MISS) if R else None,
                     "A": A.get(f, MISS), "pts": points[Y + 1].get(ids.get(f), 0.0)})
print(f"  {len(rows)} player-seasons")

L = math.log


def fit_age(train):
    """Mean log(August rank / November dynasty rank) by position and age bucket, shrunk to the position mean."""
    by = collections.defaultdict(list); bp = collections.defaultdict(list)
    for r in train:
        x = L(r["A"]) - L(r["D"]); by[(r["pos"], r["b"])].append(x); bp[r["pos"]].append(x)
    out = {}
    for pos in SKILL:
        pm = st.mean(bp[pos]) if bp[pos] else 0.0
        for _, _, lab in AGE_BUCKETS:
            v = by.get((pos, lab), [])
            n = len(v)
            out[(pos, lab)] = (sum(v) + 10 * pm) / (n + 10)        # shrink small cells toward the position mean
    return out


def predictors(r, adj):
    out = {"Dynasty": r["D"]}
    if r["R"] is not None:
        out["ROS"] = r["R"]
        out["Blend 50/50"] = math.exp((L(r["D"]) + L(r["R"])) / 2)
    out["Dynasty + age"] = math.exp(L(r["D"]) + adj[(r["pos"], r["b"])])
    if r["R"] is not None:
        out["Blend + age"] = math.exp((L(r["D"]) + adj[(r["pos"], r["b"])] + L(r["R"])) / 2)
    return out


res = collections.defaultdict(lambda: collections.defaultdict(list))
for Y in YEARS:
    test = [r for r in rows if r["Y"] == Y]
    adj = fit_age([r for r in rows if r["Y"] != Y])           # leave one season out
    for r in test:
        for k, v in predictors(r, adj).items():
            res[k]["pred"].append(v); res[k]["A"].append(r["A"]); res[k]["pts"].append(r["pts"])
            res[k]["Y"].append(Y)

print("\n  Out-of-sample (each season predicted from the other four). Pool: November top-200 skill players.")
print(f"  {'predictor':16} {'n':>5} {'ρ vs Aug price':>15} {'ρ vs next-yr pts':>17} {'median |log err|':>17} {'within 1 round*':>16}")
summary = {}
for k in ["Dynasty", "Dynasty + age", "ROS", "Blend 50/50", "Blend + age"]:
    d = res[k]
    if not d["pred"]:
        continue
    rho = spearman(d["pred"], d["A"]); rp = spearman([-x for x in d["pred"]], d["pts"])
    err = [abs(L(p) - L(a)) for p, a in zip(d["pred"], d["A"])]
    inr = [abs(p - a) <= 10 for p, a in zip(d["pred"], d["A"]) if a <= PICKS]
    summary[k] = {"n": len(err), "rho_price": round(rho, 3), "rho_pts": round(rp, 3), "mae_log": round(st.median(err), 3),
                  "within_round": round(sum(inr) / len(inr), 3)}
    print(f"  {k:16} {len(err):5d} {rho:15.3f} {rp:17.3f} {st.median(err):17.3f} {sum(inr) / len(inr):16.1%}")
print("  * share of players drafted inside 170 whose predicted price was within 10 picks (one round)")

# ROS exists only some Novembers: compare on the common subset too
common = [i for i, r in enumerate(res["ROS"]["pred"])]

# ---------------------------------------------------------------- 2. final age shifts + uncertainty
adj_all = fit_age(rows)
print("\n2. Age shift: median move from November dynasty rank to next August price (× rank; <1 = earlier pick)")
print(f"  {'':6}" + "".join(f"{lab:>9}" for _, _, lab in AGE_BUCKETS))
for pos in SKILL:
    print(f"  {pos:6}" + "".join(f"{math.exp(adj_all[(pos, lab)]):9.2f}" for _, _, lab in AGE_BUCKETS))
# residual spread in log rank by position after the age shift, players with Nov rank <= 170
sig = {}
for pos in SKILL:
    e = [L(r["A"]) - L(r["D"]) - adj_all[(r["pos"], r["b"])] for r in rows if r["pos"] == pos and r["D"] <= PICKS]
    sig[pos] = st.pstdev(e)
print("  Spread of the remaining error (sd of log rank):", {p: round(s, 2) for p, s in sig.items()},
      "→ a player projected at pick 40 lands between", ", ".join(f"{p} {40 * math.exp(-sig[p]):.0f}–{40 * math.exp(sig[p]):.0f}" for p in SKILL))

# blend weights: should the age-shifted dynasty or ROS carry more?
best_w, best_e = None, 9
both = [r for r in rows if r["R"] is not None]
for w in [i / 10 for i in range(11)]:
    e = st.median([abs(w * (L(r["D"]) + adj_all[(r["pos"], r["b"])]) + (1 - w) * L(r["R"]) - L(r["A"])) for r in both])
    if e < best_e:
        best_w, best_e = w, e
print(f"  Best in-sample weight on age-shifted dynasty vs ROS: {best_w:.1f} (median |log err| {best_e:.3f}); "
      f"ROS available for {len(both)} of {len(rows)} player-seasons")

# ---------------------------------------------------------------- 3. year 2+: August -> August drift by age
print("\n3. Year-over-year drift of August price by age (multi-year keepers)")
yy = collections.defaultdict(list)
for Y in range(2021, 2025):
    a0, a1 = snap("pre", Y, 8, last=True), snap("pre", Y + 1, 8, last=True)
    if not (a0 and a1):
        continue
    A0, A1 = skill_rank(pages[("pre", a0)]), skill_rank(pages[("pre", a1)])
    for f, r0 in A0.items():
        if r0 > PICKS:
            continue
        a = age_on(f, dt.date(Y, 8, 15))
        if a is None:
            continue
        pos = pages[("pre", a0)][f][1]
        yy[(pos, bucket(int(a)))].append(L(A1.get(f, MISS)) - L(r0))
drift = {}
print(f"  {'':6}" + "".join(f"{lab:>9}" for _, _, lab in AGE_BUCKETS))
for pos in SKILL:
    pm = st.mean([x for (p, _), v in yy.items() if p == pos for x in v])
    line = []
    for _, _, lab in AGE_BUCKETS:
        v = yy.get((pos, lab), [])
        m = (sum(v) + 10 * pm) / (len(v) + 10)
        drift[(pos, lab)] = m; line.append(math.exp(m))
    print(f"  {pos:6}" + "".join(f"{x:9.2f}" for x in line))
sig_yy = {pos: st.pstdev([x - drift[k] for k, v in yy.items() if k[0] == pos for x in v]) for pos in SKILL}
print("  sd of log rank, one season ahead:", {p: round(s, 2) for p, s in sig_yy.items()})

# ---------------------------------------------------------------- 4. pick value curve from realized points
print("\n4. What a pick is worth: next-season points above replacement by preseason rank (10 teams, Maywood lineup)")


def vorp_season(pts):
    """Replacement = best player not needed to fill 10 Maywood lineups (1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX)."""
    by = {p: sorted(v, reverse=True) for p, v in pts.items()}
    need = {p: TEAMS * STARTERS[p] for p in SKILL}
    flex = sorted(by["RB"][need["RB"]:] + by["WR"][need["WR"]:] + by["TE"][need["TE"]:], reverse=True)[:TEAMS * STARTERS["FLEX"]]
    cut = flex[-1]
    return {"QB": by["QB"][need["QB"]], "TE": by["TE"][need["TE"]], "RB": cut, "WR": cut}


curve_pts = collections.defaultdict(list)
for Y in range(2021, 2026):
    an = snap("pre", Y, 8, last=True)
    if not an:
        continue
    A = skill_rank(pages[("pre", an)])
    season = collections.defaultdict(list)
    sp = {}
    for f, (e, pos) in pages[("pre", an)].items():
        sid = ids.get(f)
        p = points[Y].get(sid, 0.0) if sid else 0.0
        sp[f] = (p, pos); season[pos].append(p)
    for pos in SKILL:                               # include unranked players who scored (waiver hits)
        season[pos] += [0.0] * 5
    repl = vorp_season(season)
    for f, r in A.items():
        if r > 220:
            continue
        p, pos = sp[f]
        curve_pts[r].append(max(0.0, p - repl[pos]))
    print(f"  {Y}: replacement QB {repl['QB']:.0f}, RB/WR/flex {repl['RB']:.0f}, TE {repl['TE']:.0f} season PPR points")

# smooth: mean in bands of 10 picks
bands = []
for lo in range(1, 211, 10):
    v = [x for r in range(lo, lo + 10) for x in curve_pts.get(r, [])]
    bands.append((lo + 4.5, st.mean(v), len(v)))
# fit V(n) = a*exp(-b n) + c on bands by grid search on b (least squares for a, c)
best = None
for bi in range(1, 400):
    b = bi / 4000
    xs = [math.exp(-b * n) for n, _, _ in bands]; ys = [m for _, m, _ in bands]
    mx, my = st.mean(xs), st.mean(ys)
    a = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    c = my - a * mx
    sse = sum((a * x + c - y) ** 2 for x, y in zip(xs, ys))
    if best is None or sse < best[0]:
        best = (sse, a, b, c)
_, a, b, c = best


def V(n):
    """Value of overall pick n, 100 at pick 1, 0 at pick 170 (the waiver line)."""
    n = min(max(n, 1), PICKS)
    top, bot = a * math.exp(-b) + c, a * math.exp(-b * PICKS) + c
    return 100 * (a * math.exp(-b * n) + c - bot) / (top - bot)


print(f"  Exponential fit: points above replacement ≈ {a:.0f}·e^(−{b:.4f}·pick) {c:+.0f}; half-life {math.log(2) / b:.0f} picks")


def isotonic_dec(ys, ws):
    """Pool-adjacent-violators for a non-increasing fit."""
    blocks = [[y, w, 1] for y, w in zip(ys, ws)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] < blocks[i + 1][0]:
            y0, w0, n0 = blocks[i]; y1, w1, n1 = blocks.pop(i + 1)
            blocks[i] = [(y0 * w0 + y1 * w1) / (w0 + w1), w0 + w1, n0 + n1]
            i = max(i - 1, 0)
        else:
            i += 1
    out = []
    for y, _, n in blocks:
        out += [y] * n
    return out


iso = isotonic_dec([m for _, m, _ in bands], [k for _, _, k in bands])
xs = [n for n, _, _ in bands]
# knots at the centre of each pooled block, so the curve falls steadily instead of in steps
knots, i = [], 0
while i < len(iso):
    j = i
    while j + 1 < len(iso) and abs(iso[j + 1] - iso[i]) < 1e-9:
        j += 1
    w = [bands[k][2] for k in range(i, j + 1)]
    knots.append((sum(xs[k] * bands[k][2] for k in range(i, j + 1)) / sum(w), iso[i]))
    i = j + 1
knots = [(x, y) for x, y in knots if x < PICKS]
top_v = knots[0][1]
end = 0.0                                          # pick 170 = waiver line = 0
pick_value = [[1, 100.0]] + [[round(x, 1), round(100 * y / top_v, 2)] for x, y in knots[1:]] + [[PICKS, 0.0]]
pv_x, pv_y = [p for p, _ in pick_value], [v for _, v in pick_value]


def Viso(n):
    n = min(max(n, 1), PICKS)
    for i in range(1, len(pv_x)):
        if n <= pv_x[i]:
            t = (n - pv_x[i - 1]) / (pv_x[i] - pv_x[i - 1])
            return pv_y[i - 1] + t * (pv_y[i] - pv_y[i - 1])
    return 0.0


print("  pick  realized-VORP  exponential  isotonic (used)")
for (n, m, k), y in zip(bands[:17], iso):
    print(f"  {n:5.0f} {m:14.0f} {V(n):12.1f} {Viso(n):15.1f}")
print("  Round values, isotonic (pick 5 of each round):", {r: round(Viso(10 * (r - 1) + 5), 1) for r in range(1, 18)})
# position factor: realized value of a position relative to the curve at the same preseason rank
pos_val = {}
for pos in SKILL:
    got = exp = 0.0
    for Y in range(2021, 2026):
        an = snap("pre", Y, 8, last=True)
        A = skill_rank(pages[("pre", an)])
        season = collections.defaultdict(list); sp = {}
        for f, (e, ps) in pages[("pre", an)].items():
            sid = ids.get(f); p = points[Y].get(sid, 0.0) if sid else 0.0
            sp[f] = (p, ps); season[ps].append(p)
        repl = vorp_season(season)
        repl = dict(repl, QB=repl["QB"] + QB_STREAM)    # a team can stream free-agent QBs (engine calibration)
        for f, r in A.items():
            p, ps = sp[f]
            if ps == pos and r <= 150:
                got += max(0.0, p - repl[ps]) * 100 / top_v; exp += Viso(r)
    pos_val[pos] = round(got / exp, 3) if exp else 1.0
print(f"  Realized value ÷ curve at the same preseason rank, ranks 1–150 (QB line +{QB_STREAM:.0f} pts for streaming):", pos_val)
sse_e = sum((V(n) - 100 * (m - end) / (top_v - end)) ** 2 * k for n, m, k in bands if n <= PICKS)
sse_i = sum((Viso(n) - 100 * (m - end) / (top_v - end)) ** 2 * k for n, m, k in bands if n <= PICKS)
print(f"  weighted squared error vs realized bands: exponential {sse_e:,.0f}, isotonic {sse_i:,.0f}")

# ---------------------------------------------------------------- 5. is FantasyPros' August list Maywood's price?
print("\n5. Is the FantasyPros preseason list the Maywood price? (non-keeper picks, 2024 and 2025)")
mp = {}
for Y in (2024, 2025):
    an = snap("pre", Y, 8, last=True)
    A = skill_rank(pages[("pre", an)])
    sl2fp = {v: k for k, v in ids.items()}
    picks = json.load(open(f"picks_{Y}.json"))
    xs, ys, bypos = [], [], collections.defaultdict(list)
    for p in picks:
        if p.get("is_keeper"):
            continue
        f = sl2fp.get(p["player_id"])
        if not f or f not in A or p["metadata"].get("position") not in SKILL:
            continue
        xs.append(A[f]); ys.append(p["pick_no"])
        bypos[p["metadata"]["position"]].append(L(p["pick_no"]) - L(A[f]))
    rho = spearman(xs, ys)
    print(f"  {Y}: ρ = {rho:.3f} over {len(xs)} picks; median pick ÷ FP rank by position:",
          {k: round(math.exp(st.median(v)), 2) for k, v in sorted(bypos.items())})
    for k, v in bypos.items():
        mp.setdefault(k, []).extend(v)
pos_price = {k: round(math.exp(st.median(v)), 3) for k, v in mp.items()}
print("  Pooled Maywood position factor (applied to price):", pos_price)
sig_pre = st.pstdev([x - math.log(pos_price[k]) for k, v in mp.items() for x in v])
print(f"  Spread of Maywood pick around the adjusted August rank: sd {sig_pre:.2f} log rank (used once August lists exist)")

# ---------------------------------------------------------------- 6. value of holding two keeper options
print("\n6. Option value: keeper declared just before the draft, so a second candidate is a free call option")
import random
random.seed(7)
ex = []
for s1, s2 in [(30, 30), (30, 20), (30, 10), (20, 20)]:
    # two players whose expected surplus is s1, s2 value points; price error from section 2 (WR spread)
    sd = sig["WR"]
    draws = []
    for _ in range(20000):
        # surplus moves with value at the realized price; approximate with a multiplicative shock on the player's pick
        e1, e2 = random.gauss(0, sd), random.gauss(0, sd)
        draws.append((s1 * math.exp(-e1 * 0.8), s2 * math.exp(-e2 * 0.8)))
    best1 = st.mean(max(d[0], 0) for d in draws)
    both2 = st.mean(max(d[0], d[1], 0) for d in draws)
    ex.append((s1, s2, best1, both2))
    print(f"  candidates worth {s1} and {s2}: keeping only the first {best1:.1f}, choosing in August {both2:.1f} "
          f"(+{both2 - best1:.1f}, {100 * (both2 - best1) / best1:.0f}%)")

json.dump({
    "generated": "2026-11-02", "years": [f"Nov {y} → Aug {y + 1}" for y in YEARS], "summary": summary,
    "age_shift": {f"{p}|{lab}": round(adj_all[(p, lab)], 4) for p in SKILL for _, _, lab in AGE_BUCKETS},
    "age_buckets": [[lo, hi, lab] for lo, hi, lab in AGE_BUCKETS],
    "sigma_nov_aug": {p: round(s, 4) for p, s in sig.items()},
    "drift_yoy": {f"{p}|{lab}": round(drift[(p, lab)], 4) for p in SKILL for _, _, lab in AGE_BUCKETS},
    "sigma_yoy": {p: round(s, 4) for p, s in sig_yy.items()},
    "blend_weight_dynasty": best_w,
    "pick_curve_exp": {"a": round(a, 3), "b": round(b, 6), "c": round(c, 3)},
    "pick_value": pick_value, "picks": PICKS,
    "realized_bands": [[round(n, 1), round(m, 1), k] for n, m, k in bands],
    "maywood_pos_price": pos_price, "sigma_preseason": round(sig_pre, 4), "pos_value": pos_val,
}, open("keeper_model.json", "w"), indent=1)
print("\nwrote keeper_model.json")
