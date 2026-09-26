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


