# source_backtest.py — FantasyPros ECR vs Rotowire (Sleeper) vs blend, 2024–2025. Run 2026-09-25.
# DATA SETUP (all reachable from the workspace):
#   ids.csv      <- https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv
#   games.csv    <- https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
#   ecr2024.csv  <- rows of files/db_fpecr.csv.gz (same repo) with scrape_date 2024-09-20..12-31, weekly-* and redraft-* pages
#   fp2025/wk{W}.csv  <- `git show <sha>:files/fp_latest_weekly.csv` for the last commit before Sunday 16:30 UTC of week W
#                        (git clone --filter=blob:none https://github.com/dynastyprocess/data; git log -- files/fp_latest_weekly.csv)
#   ros2025/{date}.csv <- every 2025 in-season version of files/db_fpecr_latest.csv
#   stats_{Y}_{W}.json / proj_{Y}_{W}.json <- https://api.sleeper.app/{stats|projections}/nfl/{Y}/{W}?season_type=regular&position[]=QB&...
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


def weekly_snapshots(Y):
    """yield week, scrape_date, {pos: [(fp_id, ecr, r2p)]}"""
    if Y == 2024:
        ecr = collections.defaultdict(list)
        for r in csv.DictReader(open("ecr2024.csv")):
            if r["page_type"].startswith("weekly"):
                ecr[r["date"]].append(r)
        wk = {4: "2024-09-27", 5: "2024-10-04", 6: "2024-10-11", 7: "2024-10-18", 8: "2024-10-25", 9: "2024-11-01",
              10: "2024-11-08", 11: "2024-11-15", 12: "2024-11-22", 13: "2024-11-27", 14: "2024-12-06",
              15: "2024-12-13", 16: "2024-12-20", 17: "2024-12-27"}
        for w, d in wk.items():
            out = collections.defaultdict(list)
            for r in ecr[d]:
                out[r["page_type"].split("-")[1].upper()].append((r["id"], float(r["ecr"]), None))
            yield w, d, out
    else:
        for w in range(1, 18):
            rows = list(csv.DictReader(open(f"fp2025/wk{w}.csv")))
            d = rows[0]["scrape_date"]
            out = collections.defaultdict(list)
            for r in rows:
                pos = r["page"].replace("ppr-", "").upper()
                r2p = float(r["r2p_pts"]) if r["r2p_pts"] not in ("NA", "") else None
                out[pos].append((r["fantasypros_id"], float(r["ecr"]), r2p))
            yield w, d, out


RES = {}
for Y in (2024, 2025):
    gameday, stats, proj = load_season(Y)
    pts = lambda w, s: (stats[w].get(s) or {}).get("pts_ppr") or 0.0
    played = lambda w, s: bool(stats[w].get(s)) and ((stats[w][s].get("off_snp") or 0) > 0 or (stats[w][s].get("gp") or 0) > 0)
    W = collections.defaultdict(lambda: [0, 0]); SP = collections.defaultdict(list); FLEX = collections.defaultdict(lambda: [0, 0])
    nweeks = 0
    for w, d, snap in weekly_snapshots(Y):
        nweeks += 1
        flexpool = []
        for pos in POOL:
            cand = []
            for fid, e, r2p in snap.get(pos, []):
                sid = ids.get(fid)
                if not sid or sid not in proj[w]:
                    continue
                gd = gameday[w].get(proj[w][sid][2])
                if gd is None or gd < d or (Y == 2024 and gd <= d):
                    continue
                if not played(w, sid):
                    continue
                cand.append((e, proj[w][sid][0], pts(w, sid), sid, r2p))
            cand.sort(); cand = cand[:POOL[pos]]
            if len(cand) < 8:
                continue
            er = rankdata([c[0] for c in cand]); pr = rankdata([-c[1] for c in cand]); a = [c[2] for c in cand]
            for name, sc in (("FP ECR", [-x for x in er]), ("Rotowire", [c[1] for c in cand]),
                             ("Blend", [-(x + y) for x, y in zip(er, pr)])):
                for wn, win in (("all", None), ("close", 6)):
                    g, t = pairwise(sc, a, er, win); W[(pos, wn, name)][0] += g; W[(pos, wn, name)][1] += t
                SP[(pos, name)].append(spearman(sc, a))
            if pos != "QB":
                flexpool += [(c, pos) for c in cand if c[4] is not None]
        # cross-position flex test: pairs of different positions whose r2p and Rotowire both fall in flex-relevant range
        if flexpool:
            fp = [x for x in flexpool if 7 <= x[0][4] <= 16]
            a = [x[0][2] for x in fp]; grp = [x[1] for x in fp]
            e = [x[0][4] for x in fp]; p = [x[0][1] for x in fp]; b = [(x + y) / 2 for x, y in zip(e, p)]
            for name, sc in (("FP ECR (r2p pts)", e), ("Rotowire", p), ("Blend", b)):
                g, t = pairwise(sc, a, groups=grp, cross_only=True); FLEX[name][0] += g; FLEX[name][1] += t
    RES[Y] = {"weeks": nweeks, "W": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in W.items()},
              "SP": {f"{k[0]}|{k[1]}": v for k, v in SP.items()}, "FLEX": dict(FLEX)}

    # ---- ROS
    R = collections.defaultdict(list)
    if Y == 2024:
        rows_by = collections.defaultdict(list)
        for r in csv.DictReader(open("ecr2024.csv")):
            if r["page_type"] == "redraft-overall":
                rows_by[r["date"]].append((r["id"], r["pos"], float(r["ecr"])))
        snaps = [(w, d, rows_by[d]) for w, d in {4: "2024-09-27", 5: "2024-10-04", 6: "2024-10-11", 7: "2024-10-18", 8: "2024-10-25", 9: "2024-11-01", 10: "2024-11-08", 11: "2024-11-15", 12: "2024-11-22", 13: "2024-11-27", 14: "2024-12-06"}.items()]
        start = lambda w: w  # Friday snapshot of week w (TNF excluded is minor) -> score weeks w+1..17
    else:
        snaps = []
        for f in sorted(glob.glob("ros2025/*.csv")):
            d = os.path.basename(f)[:10]
            rows = [(x["id"], x["pos"], float(x["ecr"])) for x in csv.DictReader(open(f))
                    if x["page_type"] == "redraft-overall" and "ros-" in x["fp_page"]]
            if not rows:
                continue
            # week whose Thursday..Wednesday contains d-1 (scrape is Thu night ET)
            w = next((k for k in range(1, 18) if min(gameday[k].values()) <= d <= max(gameday[k].values())), None)
            if w and 3 <= w <= 14:
                snaps.append((w, d, rows))
    for w, d, rows in snaps:
        for pos in RP:
            cand = []
            for fid, p, e in rows:
                if not p.startswith(pos):
                    continue
                sid = ids.get(fid)
                if not sid:
                    continue
                gp = sum(1 for k in range(1, w) if played(k, sid))
                ppg = sum(pts(k, sid) for k in range(1, w)) / gp if gp else 0.0
                fut = sum(pts(k, sid) for k in range(w + 1, 18))
                cand.append((e, ppg, fut))
            cand.sort(); cand = cand[:RP[pos]]
            er = rankdata([c[0] for c in cand]); pg = rankdata([-c[1] for c in cand]); a = [c[2] for c in cand]
            R[(pos, "FP ROS ECR")].append(spearman([-x for x in er], a))
            R[(pos, "PPG to date")].append(spearman([-x for x in pg], a))
            R[(pos, "ECR 2/3 + PPG 1/3")].append(spearman([-(2 * x + y) for x, y in zip(er, pg)], a))
            R[(pos, "ECR 1/2 + PPG 1/2")].append(spearman([-(x + y) for x, y in zip(er, pg)], a))
    RES[Y]["ROS"] = {f"{k[0]}|{k[1]}": v for k, v in R.items()}
    RES[Y]["ros_weeks"] = [w for w, _, _ in snaps]

json.dump(RES, open("results2.json", "w"))

# ---------- report
for Y in RES:
    print(f"\n===== {Y}: weekly weeks={RES[Y]['weeks']}  ROS weeks={RES[Y]['ros_weeks']}")
    for pos in POOL:
        s = []
        for name in ("FP ECR", "Rotowire", "Blend"):
            ga, ta = RES[Y]["W"][f"{pos}|all|{name}"]; gc, tc = RES[Y]["W"][f"{pos}|close|{name}"]
            s.append(f"{name} {100*ga/ta:.1f}/{100*gc/tc:.1f}/rho {st.mean(RES[Y]['SP'][f'{pos}|{name}']):.3f}")
        print(pos, " ; ".join(s))
    print("FLEX cross-position pairs:", {k: f"{100*v[0]/v[1]:.1f}% of {v[1]}" for k, v in RES[Y]["FLEX"].items() if v[1]})
    for pos in RP:
        print("ROS", pos, " ; ".join(f"{k.split('|')[1]} {st.mean(v):.3f}" for k, v in RES[Y]["ROS"].items() if k.startswith(pos + "|")))

print("\n===== POOLED (both seasons)")
for pos in POOL:
    s = []
    for name in ("FP ECR", "Rotowire", "Blend"):
        ga = sum(RES[Y]["W"][f"{pos}|all|{name}"][0] for Y in RES); ta = sum(RES[Y]["W"][f"{pos}|all|{name}"][1] for Y in RES)
        gc = sum(RES[Y]["W"][f"{pos}|close|{name}"][0] for Y in RES); tc = sum(RES[Y]["W"][f"{pos}|close|{name}"][1] for Y in RES)
        rh = st.mean(sum((RES[Y]["SP"][f"{pos}|{name}"] for Y in RES), []))
        s.append(f"{name} {100*ga/ta:.1f}/{100*gc/tc:.1f}/rho {rh:.3f}")
    a = sum((RES[Y]["SP"][f"{pos}|Blend"] for Y in RES), []); e = sum((RES[Y]["SP"][f"{pos}|FP ECR"] for Y in RES), []); r = sum((RES[Y]["SP"][f"{pos}|Rotowire"] for Y in RES), [])
    print(pos, " ; ".join(s), f"| blend>ECR {sum(x>y for x,y in zip(a,e))}/{len(a)} wks, blend>RW {sum(x>y for x,y in zip(a,r))}/{len(a)}, RW>ECR {sum(x>y for x,y in zip(r,e))}/{len(a)}")
for pos in RP:
    keys = sorted({k.split("|")[1] for Y in RES for k in RES[Y]["ROS"] if k.startswith(pos + "|")})
    print("ROS", pos, " ; ".join(f"{k} {st.mean(sum((RES[Y]['ROS'][pos+'|'+k] for Y in RES), [])):.3f}" for k in keys))
