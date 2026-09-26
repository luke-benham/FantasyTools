# lag_test.py — does FantasyPros ECR lag news? Same data setup as source_backtest.py.txt, plus fp2025thu/wk{W}.csv (last mirror commit before Thursday 20:00 UTC of week W).
"""Two-season backtest (2024 Friday ECR snapshots wk4-17; 2025 Sunday-morning ECR snapshots wk1-17).
Weekly: FantasyPros ECR vs Rotowire (Sleeper) vs 50/50 rank blend, by position, plus cross-position flex test (2025, r2p points).
ROS: FantasyPros ROS ECR vs points-per-game-to-date vs blends."""
import csv, json, collections, statistics as st, glob, os

POOL = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}
RP = {"QB": 20, "RB": 48, "WR": 60, "TE": 20}
FIX = {"LA": "LAR"}

ids = {r["fantasypros_id"]: r["sleeper_id"] for r in csv.DictReader(open("ids.csv"))
       if r["fantasypros_id"] not in ("", "NA") and r["sleeper_id"] not in ("", "NA")}


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


def pairwise(scores, actual, keyrank=None, window=None, groups=None, cross_only=False):
    good = tot = 0; n = len(scores)
    for i in range(n):
        for j in range(i + 1, n):
            if window is not None and abs(keyrank[i] - keyrank[j]) > window:
                continue
            if cross_only and groups[i] == groups[j]:
                continue
            if actual[i] == actual[j] or scores[i] == scores[j]:
                continue
            tot += 1; good += (scores[i] > scores[j]) == (actual[i] > actual[j])
    return good, tot


def load_season(Y):
    games = [r for r in csv.DictReader(open("games.csv")) if r["season"] == str(Y) and r["game_type"] == "REG"]
    gameday = collections.defaultdict(dict)
    for g in games:
        for t in (g["home_team"], g["away_team"]):
            gameday[int(g["week"])][FIX.get(t, t)] = g["gameday"]
    stats, proj = {}, {}
    for w in range(1, 18):
        stats[w] = {r["player_id"]: r["stats"] for r in json.load(open(f"stats_{Y}_{w}.json"))}
        proj[w] = {r["player_id"]: (r["stats"].get("pts_ppr") or 0.0, r["player"].get("position"), r.get("team"))
                   for r in json.load(open(f"proj_{Y}_{w}.json"))}
    return gameday, stats, proj


_st = st
"""Does FantasyPros ECR under-react to news?
A) ROS: does last week's ECR move (momentum) predict rest-of-season results beyond the current ECR?
B) Weekly 2025: Thursday vs Sunday-morning ECR — does the late-week move keep going?
C) Does expert disagreement (sd) predict bigger misses?"""
import csv, json, glob, os, math, collections, statistics as st
def spearman(a, b):
    try:
        return _st.correlation(rankdata(a), rankdata(b))
    except Exception:
        return 0.0

RP = {"QB": 20, "RB": 48, "WR": 60, "TE": 20}
POOL = {"QB": 24, "RB": 48, "WR": 60, "TE": 24}


def ros_snaps(Y, gameday):
    if Y == 2024:
        by = collections.defaultdict(dict)
        for r in csv.DictReader(open("ecr2024.csv")):
            if r["page_type"] == "redraft-overall" and r["date"] >= "2024-09-27":
                by[r["date"]][r["id"]] = (r["pos"], float(r["ecr"]), float(r["sd"] or 0))
        wk = {"2024-09-27": 4, "2024-10-04": 5, "2024-10-11": 6, "2024-10-18": 7, "2024-10-25": 8, "2024-11-01": 9,
              "2024-11-08": 10, "2024-11-15": 11, "2024-11-22": 12, "2024-11-27": 13, "2024-12-06": 14}
        return [(wk[d], by[d]) for d in sorted(by) if d in wk]
    out = []
    for f in sorted(glob.glob("ros2025/*.csv")):
        d = os.path.basename(f)[:10]
        rows = {x["id"]: (x["pos"], float(x["ecr"]), float(x["sd"] or 0)) for x in csv.DictReader(open(f))
                if x["page_type"] == "redraft-overall" and "ros-" in x["fp_page"]}
        w = next((k for k in range(1, 18) if min(gameday[k].values()) <= d <= max(gameday[k].values())), None)
        if rows and w and w <= 14:
            out.append((w, rows))
    return out


KS = (-0.5, 0.5, 1.0, 2.0)
A = collections.defaultdict(list); C = collections.defaultdict(list); MOM = collections.defaultdict(list)
for Y in (2024, 2025):
    gameday, stats, proj = load_season(Y)
    pts = lambda w, s: (stats[w].get(s) or {}).get("pts_ppr") or 0.0
    snaps = ros_snaps(Y, gameday)
    for (wp, prev), (w, cur) in zip(snaps, snaps[1:]):
        for pos in RP:
            cand = []
            for fid, (p, e, sd) in cur.items():
                if not p.startswith(pos) or fid not in prev or fid not in ids:
                    continue
                m = math.log(prev[fid][1]) - math.log(e)          # + = rising
                fut = sum(pts(k, ids[fid]) for k in range(w + 1, 18))
                cand.append((e, m, sd / e, fut))
            cand.sort(); cand = cand[:RP[pos]]
            if len(cand) < 10:
                continue
            base = [-math.log(c[0]) for c in cand]; a = [c[3] for c in cand]
            A[(pos, "ECR now")].append(spearman(base, a))
            for k in KS:
                A[(pos, f"ECR + {k}×last move")].append(spearman([b + k * c[1] for b, c in zip(base, cand)], a))
            # residual: actual rank minus ECR rank (negative = beat ECR)
            resid = [x - y for x, y in zip(rankdata([-v for v in a]), rankdata([c[0] for c in cand]))]
            MOM[pos].append(spearman([c[1] for c in cand], [-r for r in resid]))
            C[pos].append(spearman([c[2] for c in cand], [abs(r) for r in resid]))

print("A) ROS momentum — mean Spearman vs rest-of-season points (2024 wk5-14 + 2025 wk4-14)")
for pos in RP:
    print(" ", pos, " | ".join(f"{k.split('|')[-1]} {st.mean(v):.3f}" for (p, k), v in A.items() if p == pos),
          f"| corr(move, beat-ECR) {st.mean(MOM[pos]):+.3f} over {len(MOM[pos])} wks")
print("C) ROS: corr(relative sd, size of miss):", {p: round(st.mean(v), 3) for p, v in C.items()})

# ---- B) weekly Thursday -> Sunday, 2025
gameday, stats, proj = load_season(2025)
pts = lambda w, s: (stats[w].get(s) or {}).get("pts_ppr") or 0.0
played = lambda w, s: bool(stats[w].get(s)) and ((stats[w][s].get("off_snp") or 0) > 0 or (stats[w][s].get("gp") or 0) > 0)
B = collections.defaultdict(list); BM = collections.defaultdict(list); BC = collections.defaultdict(list); moved = collections.Counter()
for w in range(1, 18):
    def load(f):
        o = {}
        for r in csv.DictReader(open(f)):
            pos = r["page"].replace("ppr-", "").upper()
            if pos in POOL:
                o[(pos, r["fantasypros_id"])] = (float(r["ecr"]), float(r["sd"]) if r["sd"] not in ("NA", "") else 0.0)
        return o
    thu, sun = load(f"fp2025thu/wk{w}.csv"), load(f"fp2025/wk{w}.csv")
    d = open(f"fp2025/wk{w}.csv").readlines()[1].split(",")[2]
    for pos in POOL:
        cand = []
        for (p, fid), (e, sd) in sun.items():
            if p != pos or (p, fid) not in thu or fid not in ids:
                continue
            sid = ids[fid]
            if sid not in proj[w] or not played(w, sid):
                continue
            gd = gameday[w].get(proj[w][sid][2])
            if gd is None or gd < d:
                continue
            m = math.log(thu[(p, fid)][0]) - math.log(e)
            cand.append((e, m, sd / e, pts(w, sid), thu[(p, fid)][0]))
        cand.sort(); cand = cand[:POOL[pos]]
        if len(cand) < 10:
            continue
        moved[pos] += sum(1 for c in cand if abs(c[1]) > math.log(1.25))
        a = [c[3] for c in cand]; base = [-math.log(c[0]) for c in cand]
        B[(pos, "Thu ECR")].append(spearman([-math.log(c[4]) for c in cand], a))
        B[(pos, "Sun ECR")].append(spearman(base, a))
        for k in KS:
            B[(pos, f"Sun + {k}×Thu→Sun move")].append(spearman([b + k * c[1] for b, c in zip(base, cand)], a))
        resid = [x - y for x, y in zip(rankdata([-v for v in a]), rankdata([c[0] for c in cand]))]
        BM[pos].append(spearman([c[1] for c in cand], [-r for r in resid]))
        BC[pos].append(spearman([c[2] for c in cand], [abs(r) for r in resid]))
print("\nB) Weekly 2025 — Thursday vs Sunday ECR, and Sunday + extrapolated late-week move")
for pos in POOL:
    print(" ", pos, " | ".join(f"{k} {st.mean(v):.3f}" for (p, k), v in B.items() if p == pos),
          f"| corr(move, beat-ECR) {st.mean(BM[pos]):+.3f}; players moving >25%: {moved[pos]}")
print("C) Weekly: corr(relative sd, size of miss):", {p: round(st.mean(v), 3) for p, v in BC.items()})
