"""Calibrate from 2024-25:
1) ROS: points per remaining week by FantasyPros positional ROS ECR (continuous avg rank) -> smoothed monotone table.
2) Weekly: error SD of the 50/50 blend (FP r2p points + Rotowire) by position and projection level, plus calibration slope."""
import csv, glob, os, json, math, collections, statistics as st
from bt_common import load_season, ids

POS = ["QB", "RB", "WR", "TE"]
pts_rows = collections.defaultdict(list)   # pos -> [(pos_ecr, ppw)]

for Y in (2024, 2025):
    gameday, stats, proj = load_season(Y)
    pts = lambda w, s: (stats[w].get(s) or {}).get("pts_ppr") or 0.0
    snaps = []
    if Y == 2024:
        wk = {"2024-09-27": 4, "2024-10-04": 5, "2024-10-11": 6, "2024-10-18": 7, "2024-10-25": 8, "2024-11-01": 9,
              "2024-11-08": 10, "2024-11-15": 11, "2024-11-22": 12, "2024-11-27": 13, "2024-12-06": 14}
        by = collections.defaultdict(list)
        for r in csv.DictReader(open("ecr2024.csv")):
            if r["date"] in wk and r["page_type"] in ("redraft-qb", "redraft-rb", "redraft-wr", "redraft-te"):
                by[r["date"]].append((r["page_type"][-2:].upper(), r["id"], float(r["ecr"])))
        snaps = [(wk[d], rows) for d, rows in by.items()]
    else:
        for f in sorted(glob.glob("ros2025/*.csv")):
            d = os.path.basename(f)[:10]
            w = next((k for k in range(1, 18) if min(gameday[k].values()) <= d <= max(gameday[k].values())), None)
            if not w or w > 14:
                continue
            rows = [(x["page_type"][-2:].upper(), x["id"], float(x["ecr"])) for x in csv.DictReader(open(f))
                    if x["page_type"] in ("redraft-qb", "redraft-rb", "redraft-wr", "redraft-te") and "ros-" in x["fp_page"]]
            if rows:
                snaps.append((w, rows))
    for w, rows in snaps:
        n = 17 - w
        for pos, fid, e in rows:
            sid = ids.get(fid)
            if not sid:
                continue
            ppw = sum(pts(k, sid) for k in range(w + 1, 18)) / n
            pts_rows[pos].append((e, ppw))


def pav_decreasing(y, wts):
    # pool-adjacent-violators for a non-increasing fit
    blocks = [[v, w, 1] for v, w in zip(y, wts)]
    out = []
    for b in blocks:
        out.append(b)
        while len(out) > 1 and out[-2][0] < out[-1][0]:
            v2, w2, n2 = out.pop(); v1, w1, n1 = out.pop()
            out.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2])
    res = []
    for v, w, n in out:
        res += [v] * n
    return res


curve = {}
for pos in POS:
    data = pts_rows[pos]
    maxr = {"QB": 40, "RB": 90, "WR": 120, "TE": 45}[pos]
    grid = [1 + i * 0.5 for i in range(int((maxr - 1) / 0.5) + 1)]
    sm, wt = [], []
    for g in grid:
        lg = math.log(g); num = den = 0.0
        for e, v in data:
            k = math.exp(-0.5 * ((math.log(e) - lg) / 0.18) ** 2)
            num += k * v; den += k
        sm.append(num / den if den else 0.0); wt.append(den)
    fit = pav_decreasing(sm, wt)
    curve[pos] = {"rank": grid, "ppw": [round(v, 2) for v in fit], "n": len(data)}
    show = [1, 3, 6, 12, 18, 24, 36, 48, 60, 80]
    print(pos, len(data), " ".join(f"{pos}{r}:{fit[grid.index(r)]:.1f}" for r in show if r in grid))

# ---- weekly error model (2025 Sunday snapshots, blend of r2p and Rotowire)
gameday, stats, proj = load_season(2025)
res = collections.defaultdict(list)
for w in range(1, 18):
    rows = list(csv.DictReader(open(f"fp2025/wk{w}.csv")))
    d = rows[0]["scrape_date"]
    for r in rows:
        pos = r["page"].replace("ppr-", "").upper()
        if pos not in ("QB", "RB", "WR", "TE", "K", "DST") or r["r2p_pts"] in ("NA", ""):
            continue
        sid = ids.get(r["fantasypros_id"]) if pos != "DST" else None
        if pos == "DST":
            continue  # handled below via team ids
        if not sid or sid not in proj[w]:
            continue
        s = stats[w].get(sid)
        if not s or not ((s.get("off_snp") or 0) > 0 or (s.get("gp") or 0) > 0 or pos == "K"):
            continue
        gd = gameday[w].get(proj[w][sid][2])
        if gd is None or gd < d:
            continue
        b = 0.5 * float(r["r2p_pts"]) + 0.5 * proj[w][sid][0]
        res[pos].append((b, s.get("pts_ppr") or 0.0))

err = {}
for pos, xs in res.items():
    xs = [x for x in xs if x[0] >= 2]
    mx = st.mean(x for x, _ in xs); my = st.mean(y for _, y in xs)
    slope = sum((x - mx) * (y - my) for x, y in xs) / sum((x - mx) ** 2 for x, _ in xs)
    # sd by projection bins, then linear fit sd = a + b*proj
    bins = collections.defaultdict(list)
    for x, y in xs:
        bins[min(int(x // 3), 8)].append(y - (my + slope * (x - mx)))
    pts_ = [(st.mean([x for x, _ in xs if min(int(x // 3), 8) == k]), st.pstdev(v)) for k, v in bins.items() if len(v) > 30]
    ax = st.mean(p for p, _ in pts_); ay = st.mean(s for _, s in pts_)
    b = sum((p - ax) * (s - ay) for p, s in pts_) / sum((p - ax) ** 2 for p, _ in pts_)
    a = ay - b * ax
    err[pos] = {"slope": round(slope, 3), "mean_x": round(mx, 2), "mean_y": round(my, 2), "sd_a": round(a, 2), "sd_b": round(b, 3), "n": len(xs)}
    print(pos, err[pos], sorted((round(p, 1), round(s, 1)) for p, s in pts_))

json.dump({"ros_curve": curve, "weekly_error": err, "note": "fit on 2024-25; see calibrate.py"}, open("calibration.json", "w"), indent=1)
