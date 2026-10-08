"""Front Office engine: gathers every source, computes player-level facts, writes site/data/*.json.

Run from the repo root:  python -m engine.build
League logic (lineups, league values, trades, waivers) runs in the web app on live Sleeper rosters.
This engine supplies what the app can't compute on a phone: blended projections, ROS points,
market values, the Sleeper view, and signals.
"""
import argparse, bisect, datetime as dt, glob, json, math, os, re, sys

from . import config as C
from .net import json_get, csv_get, num
from .names import Index

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "site", "data")
SNAPDIR = os.path.join(ROOT, "snapshots", "fp")
INPUTS = os.path.join(ROOT, "inputs")
CAL = json.load(open(os.path.join(ROOT, "engine", "calibration.json")))
SL = "https://api.sleeper.app"
UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)
OUT_STATUS = {"Out", "IR", "PUP", "Sus", "NA", "DNR"}


def log(*a):
    print(*a, file=sys.stderr)


def fix_team(t):
    return C.TEAMFIX.get(t, t) if t else t


# ---------------------------------------------------------------- time helpers (US Eastern for nflverse kickoffs)
def eastern_offset(d):
    y = d.year
    mar = dt.date(y, 3, 8 + (6 - dt.date(y, 3, 8).weekday()) % 7)       # second Sunday of March
    nov = dt.date(y, 11, 1 + (6 - dt.date(y, 11, 1).weekday()) % 7)     # first Sunday of November
    return -4 if mar <= d < nov else -5


def kickoff_utc(gameday, gametime):
    d = dt.date.fromisoformat(gameday)
    h, m = (int(x) for x in (gametime or "13:00").split(":"))
    local = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=UTC)
    return local - dt.timedelta(hours=eastern_offset(d))


# ---------------------------------------------------------------- sources
def sleeper_week_proj(week):
    q = "&".join(f"position[]={p}" for p in C.ALL_POS)
    rows = json_get(f"{SL}/projections/nfl/{C.SEASON}/{week}?season_type=regular&{q}")
    return {r["player_id"]: r for r in rows}


def load_games():
    games = [g for g in csv_get(C.NFLVERSE_GAMES, max_age_h=6, name="games.csv")
             if g["season"] == str(C.SEASON) and g["game_type"] == "REG"]
    by_week = {}
    for g in games:
        w = int(g["week"])
        ko = kickoff_utc(g["gameday"], g["gametime"])
        total, spread = num(g["total_line"]), num(g["spread_line"])
        for side, team, opp in (("home", g["home_team"], g["away_team"]), ("away", g["away_team"], g["home_team"])):
            it = None
            if total is not None and spread is not None:
                it = (total + spread) / 2 if side == "home" else (total - spread) / 2
            by_week.setdefault(w, {})[fix_team(team)] = {"day": g["gameday"],
                "opp": fix_team(opp), "home": side == "home", "ko": ko.isoformat(), "implied": it,
                "total": total, "spread": spread if side == "home" else (-spread if spread is not None else None)}
    return by_week


def fp_snapshot_files():
    out = []
    for f in glob.glob(os.path.join(SNAPDIR, "*.json")):
        try:
            t = dt.datetime.strptime(os.path.basename(f)[:13], "%Y-%m-%dT%H").replace(tzinfo=UTC)
            out.append((t, f))
        except ValueError:
            pass
    return sorted(out)


def nearest_snapshot(target, max_time):
    best = None
    for t, f in fp_snapshot_files():
        if t > max_time:
            continue
        if best is None or abs((t - target).total_seconds()) < abs((best[0] - target).total_seconds()):
            best = (t, f)
    if not best:
        return None, None
    return best[0], json.load(open(best[1]))


# ---------------------------------------------------------------- math helpers
def interp(xs, ys, x):
    """Linear interpolation on sorted xs; clamps at the ends."""
    if not xs:
        return None
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect.bisect_left(xs, x)
    x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0) if x1 != x0 else y0


def ros_curve(pos, rank):
    c = CAL["ros_curve"].get(pos)
    return interp(c["rank"], c["ppw"], rank) if c else None


def weekly_error(pos, mu):
    e = CAL["weekly_error"].get("DST" if pos == "DEF" else pos)
    if not e:
        return mu, 5.5
    cal = e["mean_y"] + e["slope"] * (mu - e["mean_x"]) if mu > 0 else 0.0
    sd = max(2.0, e["sd_a"] + e["sd_b"] * max(cal, 0))
    return max(cal, 0.0), sd


def r1(x, n=1):
    return None if x is None else round(x, n)


# ---------------------------------------------------------------- footballers inputs
TEAM_LINE = re.compile(r"^([A-Z]{2,3})\s*\(([^)]*)\)$")


def load_footballers(week, idx):
    """inputs/footballers/wk{W}_waivers.txt (raw paste of the waiver list) and wk{W}_ranks.txt
    (lines like 'WR12 Name' or '12. Name (TEAM)'). Returns {sleeper_id: {...}}."""
    out = {}
    wf = os.path.join(INPUTS, "footballers", f"wk{week}_waivers.txt")
    if os.path.exists(wf):
        name = team = None
        for line in open(wf, encoding="utf-8"):
            s = line.strip()
            if not s or re.match(r"^player\b", s, re.I):
                continue
            m = TEAM_LINE.match(s)
            if m:
                team = fix_team(m.group(1)); continue
            if s.isdigit():
                if name:
                    pid = idx.match(name, team)
                    if pid:
                        out.setdefault(pid, {})["wv"] = int(s)
                name = team = None; continue
            name = s
    rf = os.path.join(INPUTS, "footballers", f"wk{week}_ranks.txt")
    if os.path.exists(rf):
        for line in open(rf, encoding="utf-8"):
            s = line.strip()
            m = re.match(r"^(QB|RB|WR|TE|K|DST|DEF)\s*(\d+)[\s.:\-]+(.+?)(?:\s*\(([A-Z]{2,3})\))?$", s)
            if not m:
                continue
            pos, rk, name, team = m.group(1), int(m.group(2)), m.group(3), fix_team(m.group(4))
            pid = idx.match(name, team, "DEF" if pos in ("DST", "DEF") else pos)
            if pid:
                out.setdefault(pid, {})["wk"] = rk
    return out


# ---------------------------------------------------------------- main build
def build(write_snapshot=True):
    state = json_get(f"{SL}/v1/state/nfl")
    week = int(state.get("week") or 1)
    season_type = state.get("season_type")
    log("state", state)

    PL = json_get(f"{SL}/v1/players/nfl", max_age_h=20, name="players_nfl.json")
    idx = Index(PL)
    games = load_games()
    gw = games.get(week, {})
    first_ko = min((dt.datetime.fromisoformat(g["ko"]) for g in gw.values()), default=NOW)
    ros_from = week if NOW < first_ko else week + 1
    weeks_left = max(C.LAST_FANTASY_WEEK - ros_from + 1, 1)

    # ---- FantasyPros mirror
    ids = {r["fantasypros_id"]: r["sleeper_id"] for r in csv_get(C.FP_MIRROR + "db_playerids.csv", max_age_h=20, name="db_playerids.csv")
           if r["fantasypros_id"] not in ("", "NA") and r["sleeper_id"] not in ("", "NA")}
    pfr2sl = {r["pfr_id"]: r["sleeper_id"] for r in csv_get(C.FP_MIRROR + "db_playerids.csv", max_age_h=20, name="db_playerids.csv")
              if r["pfr_id"] not in ("", "NA") and r["sleeper_id"] not in ("", "NA")}
    weekly = csv_get(C.FP_MIRROR + "fp_latest_weekly.csv")
    ecrdb = csv_get(C.FP_MIRROR + "db_fpecr_latest.csv")
    fp_scrape = max((r["scrape_date"] for r in weekly), default=None)

    def fp_sid(fpid, pos, team):
        if pos in ("DST", "DEF"):
            return fix_team(team)
        return ids.get(fpid)

    WK = {}          # sid -> weekly FP row
    wk_pages = {}    # pos -> sorted [(ecr, r2p)] for interpolation
    for r in weekly:
        page = r["page"].replace("ppr-", "").upper()
        pos = {"DST": "DEF"}.get(page, page)
        if pos not in C.ALL_POS:
            continue
        sid = fp_sid(r["fantasypros_id"], page, r["team"])
        e, r2p = num(r["ecr"]), num(r["r2p_pts"])
        if sid and e is not None:
            WK[sid] = {"pos": pos, "fpid": r["fantasypros_id"], "ecr": e, "sd": num(r["sd"]), "best": num(r["best"]),
                       "worst": num(r["worst"]), "r2p": r2p, "opp": r["player_opponent"], "grade": r.get("start_sit_grade"),
                       "page": page}
        if e is not None and r2p is not None:
            wk_pages.setdefault(pos, []).append((e, r2p))
    for pos in wk_pages:
        wk_pages[pos].sort()

    ROS, ROS_OVR = {}, {}
    for r in ecrdb:
        pt = r["page_type"]
        if not pt.startswith("redraft-") or "ros-" not in r["fp_page"]:
            continue
        kind = pt.split("-", 1)[1].upper()
        sid = fp_sid(r["id"], kind, r["team"]) if kind in ("QB", "RB", "WR", "TE", "K", "DST") else ids.get(r["id"])
        if not sid:
            continue
        rec = {"ecr": num(r["ecr"]), "sd": num(r["sd"]), "best": num(r["best"]), "worst": num(r["worst"]), "fpid": r["id"]}
        if kind == "OVERALL":
            ROS_OVR[sid] = dict(rec, pos=re.sub(r"\d+$", "", r["pos"]))
        elif kind in ("QB", "RB", "WR", "TE", "K", "DST"):
            ROS[sid] = dict(rec, pos="DEF" if kind == "DST" else kind)

    # snapshots for movement signals
    snap = {"weekly": {s: w["ecr"] for s, w in WK.items()}, "ros": {s: r["ecr"] for s, r in ROS.items()},
            "ovr": {s: r["ecr"] for s, r in ROS_OVR.items()}, "fp_scrape": fp_scrape, "week": week}
    first_day = min((g["day"] for g in gw.values()), default=NOW.date().isoformat())
    thursday = dt.datetime.fromisoformat(first_day).replace(hour=13, tzinfo=UTC)   # opening game day, ~9am ET
    tuesday = thursday - dt.timedelta(days=2) + dt.timedelta(hours=5)
    target = thursday if NOW > thursday + dt.timedelta(hours=12) else tuesday
    base_t, base = nearest_snapshot(target, NOW - dt.timedelta(hours=6))
    if base and base.get("week") != week:
        base_t, base = None, None
    ros_t, ros_base = nearest_snapshot(NOW - dt.timedelta(days=7), NOW - dt.timedelta(days=4))

    # ---- Sleeper projections, stats, trending
    projW = sleeper_week_proj(week)
    fut, byweek = {}, {}
    for w in range(ros_from, C.LAST_FANTASY_WEEK + 1):
        for sid, r in sleeper_week_proj(w).items():
            v = (r.get("stats") or {}).get("pts_ppr") or 0.0
            fut[sid] = fut.get(sid, 0.0) + v
            byweek.setdefault(sid, {})[w] = v
    next_weeks = list(range(ros_from, min(ros_from + 3, C.LAST_FANTASY_WEEK + 1)))
    q = "&".join(f"position[]={p}" for p in C.ALL_POS)
    season = {r["player_id"]: r.get("stats") or {} for r in json_get(f"{SL}/stats/nfl/{C.SEASON}?season_type=regular&{q}")}
    trend_add = {t["player_id"]: t["count"] for t in json_get(f"{SL}/v1/players/nfl/trending/add?lookback_hours=24&limit=60")}
    trend_drop = {t["player_id"]: t["count"] for t in json_get(f"{SL}/v1/players/nfl/trending/drop?lookback_hours=24&limit=60")}

    # ---- FantasyCalc (market)
    FC = {}
    for teams in (10, 8):
        try:
            for x in json_get(C.FANTASYCALC.format(teams=teams)):
                sid = str(x["player"].get("sleeperId") or "")
                if sid:
                    FC.setdefault(sid, {})[f"v{teams}"] = x.get("value")
                    FC[sid].update(trend=x.get("trend30Day"), rank=x.get("overallRank"), prank=x.get("positionRank"),
                                   tier=x.get("maybeTier"))
        except Exception as e:  # market is context; never fail the build on it
            log("fantasycalc failed", e)

    # ---- usage (snap share) from nflverse
    SNAPS = {}
    try:
        for r in csv_get(C.NFLVERSE_SNAPS.format(season=C.SEASON), max_age_h=6, name=f"snaps_{C.SEASON}.csv"):
            if r["game_type"] != "REG" or r["position"] not in ("RB", "WR", "TE", "QB"):
                continue
            sid = pfr2sl.get(r["pfr_player_id"])
            if sid:
                SNAPS.setdefault(sid, {})[int(r["week"])] = num(r["offense_pct"], 0.0)
    except Exception as e:
        log("snap counts failed", e)

    FB = load_footballers(week, idx)
    top_add = set(sorted(trend_add, key=lambda k: -trend_add[k])[:15])
    top_drop = set(sorted(trend_drop, key=lambda k: -trend_drop[k])[:10])

    # ---- leagues (snapshot; the app re-fetches live)
    leagues, rostered = [], set()
    for L in C.LEAGUES:
        lg = json_get(f"{SL}/v1/league/{L['id']}")
        rosters = json_get(f"{SL}/v1/league/{L['id']}/rosters")
        users = json_get(f"{SL}/v1/league/{L['id']}/users")
        comps = []
        for w in range(1, week + 1):
            try:
                for t in json_get(f"{SL}/v1/league/{L['id']}/transactions/{w}"):
                    if t.get("type") == "waiver" and t.get("status") == "complete":
                        for pid in (t.get("adds") or {}):
                            comps.append({"w": w, "p": pid, "bid": (t.get("settings") or {}).get("waiver_bid", 0)})
            except Exception:
                pass
        for r in rosters:
            rostered |= set((r.get("players") or []) + (r.get("reserve") or []))
        try:
            mus = json_get(f"{SL}/v1/league/{L['id']}/matchups/{week}")
        except Exception:
            mus = []
        s = lg["settings"]
        leagues.append({
            **L, "teams": s["num_teams"], "slots": lg["roster_positions"], "ir": s.get("reserve_slots", 0),
            "ir_ok": ["IR", "PUP"] + [k for k, f in (("Out", "reserve_allow_out"), ("Doubtful", "reserve_allow_doubtful"),
                                                   ("Sus", "reserve_allow_sus"), ("NA", "reserve_allow_na")) if s.get(f)],
            "budget": s.get("waiver_budget", 100), "deadline": s.get("trade_deadline"), "playoffs": s.get("playoff_week_start"),
            "waiver_day": s.get("waiver_day_of_week"), "scoring_rec": lg["scoring_settings"].get("rec"),
            "users": [{"id": u["user_id"], "name": (u.get("metadata") or {}).get("team_name") or u.get("display_name"),
                       "handle": u.get("display_name")} for u in users],
            "rosters": [{"rid": r["roster_id"], "owner": r.get("owner_id"), "players": r.get("players") or [],
                         "starters": r.get("starters") or [], "reserve": r.get("reserve") or [],
                         "w": (r.get("settings") or {}).get("wins", 0), "l": (r.get("settings") or {}).get("losses", 0),
                         "t": (r.get("settings") or {}).get("ties", 0),
                         "pf": (r.get("settings") or {}).get("fpts", 0) + (r.get("settings") or {}).get("fpts_decimal", 0) / 100,
                         "fab": (r.get("settings") or {}).get("waiver_budget_used", 0)} for r in rosters],
            "fab_wins": comps,
            "matchups": [{"rid": m["roster_id"], "mid": m.get("matchup_id"), "pts": m.get("points"), "pp": m.get("players_points") or {}, "st": m.get("starters") or []} for m in mus]})

    # ---- universe
    uni = set(WK) | set(ROS) | set(ROS_OVR) | set(FC) | rostered | set(trend_add) | set(FB)
    uni |= {s for s, r in projW.items() if ((r.get("stats") or {}).get("pts_ppr") or 0) >= 1.0}
    uni |= {s for s, v in fut.items() if v / weeks_left >= 2.0}

    # positional order from the overall ROS list, for players missing from the positional pages
    ovr_order = {}
    for sid, r in sorted(ROS_OVR.items(), key=lambda kv: kv[1]["ecr"] or 999):
        ovr_order.setdefault(r["pos"], []).append(sid)

    players, sig_count = [], 0
    for sid in uni:
        p = PL.get(sid)
        if not p:
            continue
        pos = p.get("position")
        if pos not in C.ALL_POS:
            continue
        team = p.get("team")
        g = gw.get(team) if team else None
        inj = p.get("injury_status")
        out_now = inj in OUT_STATUS

        # ---- weekly blend
        w = WK.get(sid)
        pr = projW.get(sid)
        rw = ((pr or {}).get("stats") or {}).get("pts_ppr") if pr else None
        r2p = w["r2p"] if w else None
        move = None
        if w and base and sid in base["weekly"] and base["weekly"][sid]:
            m = math.log(base["weekly"][sid]) - math.log(w["ecr"])
            move = {"from": base["weekly"][sid], "to": w["ecr"], "m": m}
            if wk_pages.get(pos) and r2p is not None:
                e_adj = math.exp(math.log(w["ecr"]) - C.LATE_MOVE_K * m)
                pts = wk_pages[pos]
                r2p = interp([x for x, _ in pts], [y for _, y in pts], e_adj)
        parts = [x for x in (r2p, rw) if x is not None]
        mu_raw = sum(parts) / len(parts) if parts else 0.0
        if g is None or out_now:
            mu_raw = 0.0
        mu, sd = weekly_error(pos, mu_raw)

        # ---- ROS points per week
        rr = ROS.get(sid); ro = ROS_OVR.get(sid)
        pos_ecr, ros_src = None, None
        if rr and rr["ecr"]:
            pos_ecr, ros_src = rr["ecr"], "fp"
        elif ro and pos in ovr_order and sid in ovr_order[pos]:
            pos_ecr, ros_src = ovr_order[pos].index(sid) + 1.0, "fp-ovr"
        rw_ppw = fut.get(sid, 0.0) / weeks_left
        # next three fantasy weeks: this week's blend (if not started yet), then Rotowire; byes count as 0
        nx = []
        for nw in next_weeks:
            if nw == week:
                nx.append(mu)
            else:
                v = byweek.get(sid, {}).get(nw, 0.0)
                nx.append(0.0 if (out_now and inj in ("IR", "PUP", "Sus")) else v)
        if pos in C.SKILL and pos_ecr:
            ppw = ros_curve(pos, pos_ecr)
        elif pos in C.SKILL:
            last = CAL["ros_curve"][pos]["rank"][-1]
            ppw = min(rw_ppw * 0.75, ros_curve(pos, last)) if rw_ppw else 0.0
            ros_src = "rw"
        else:
            ppw = rw_ppw
            ros_src = "rw"

        # ---- Sleeper lens and market
        ss = season.get(sid, {})
        fc = FC.get(sid)
        snaps = SNAPS.get(sid, {})

        # ---- signals
        sig = []
        if move and pos in C.SKILL and w["ecr"] <= 60 and abs(move["m"]) >= math.log(1.25) and abs(move["from"] - move["to"]) >= 3:
            up = move["m"] > 0
            sig.append({"k": "late", "d": 1 if up else -1,
                        "t": f"{'Rising' if up else 'Falling'} this week: {pos}{round(move['from'])} → {pos}{round(move['to'])}"})
        if rr and ros_base and sid in ros_base.get("ros", {}):
            a, b = ros_base["ros"][sid], rr["ecr"]
            if a and b and b <= 80 and abs(a - b) >= max(3, 0.2 * min(a, b)):
                sig.append({"k": "ros", "d": 1 if b < a else -1, "t": f"ROS {pos}{round(a)} → {pos}{round(b)} in 7 days"})
        if w and w["r2p"] is not None and rw is not None:
            mean = (w["r2p"] + rw) / 2
            if mean >= 6 and abs(w["r2p"] - rw) >= max(4, 0.35 * mean):
                sig.append({"k": "split", "d": 1 if rw > w["r2p"] else -1,
                            "t": f"Rotowire {rw:.1f} vs FantasyPros {w['r2p']:.1f} this week"})
        if fc and fc.get("v10") and fc.get("trend") and fc["v10"] >= 1200:
            share = fc["trend"] / max(fc["v10"] - fc["trend"], 1)
            if abs(share) >= 0.2:
                sig.append({"k": "mkt", "d": 1 if share > 0 else -1, "t": f"Trade market {share:+.0%} in 30 days"})
        if sid in top_add:
            sig.append({"k": "hot", "d": 1, "t": f"Added in {trend_add[sid]:,} Sleeper leagues (24h)"})
        if sid in top_drop:
            sig.append({"k": "hot", "d": -1, "t": f"Dropped in {trend_drop[sid]:,} Sleeper leagues (24h)"})
        news = p.get("news_updated")
        if inj and news and (NOW.timestamp() * 1000 - news) < 72 * 3600 * 1000:
            part = p.get("injury_body_part")
            sig.append({"k": "inj", "d": -1, "t": f"{inj}{' · ' + part if part else ''}"})
        if pos in ("RB", "WR", "TE") and snaps:
            ws = sorted(snaps)
            if len(ws) >= 3:
                last, prev = snaps[ws[-1]], (snaps[ws[-2]] + snaps[ws[-3]]) / 2
                if abs(last - prev) >= 0.15 and max(last, prev) >= 0.35:
                    sig.append({"k": "snap", "d": 1 if last > prev else -1,
                                "t": f"Snaps {prev:.0%} → {last:.0%} (week {ws[-1]})"})
        if w and pos in C.SKILL and w["sd"] and w["ecr"] <= 36 and w["sd"] / w["ecr"] >= 0.45 and w["best"] and w["worst"]:
            sig.append({"k": "experts", "d": 0, "t": f"Experts split: {pos}{int(w['best'])} to {pos}{int(w['worst'])}"})
        fb = FB.get(sid)
        if fb and fb.get("wk") and w:
            gap = w["ecr"] - fb["wk"]
            if abs(gap) >= max(5, 0.3 * w["ecr"]):
                sig.append({"k": "ffb", "d": 1 if gap > 0 else -1,
                            "t": f"Footballers {pos}{fb['wk']} vs consensus {pos}{round(w['ecr'])}"})
        sig_count += len(sig)

        players.append({
            "id": sid, "n": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() if pos != "DEF" else f"{team} D/ST",
            "pos": pos, "tm": team, "age": p.get("age"), "inj": inj, "bye": g is None and bool(team),
            "wk": {"opp": (g or {}).get("opp"), "home": (g or {}).get("home"), "ko": (g or {}).get("ko"),
                   "it": r1((g or {}).get("implied")), "ecr": r1(w["ecr"]) if w else None,
                   "best": w["best"] if w else None, "worst": w["worst"] if w else None, "esd": r1(w["sd"]) if w else None,
                   "fp": r1(w["r2p"]) if w and w["r2p"] is not None else None, "rw": r1(rw),
                   "mu": r1(mu), "sd": r1(sd), "grade": w["grade"] if w and w["grade"] not in ("NA", "") else None},
            "ros": {"ecr": r1(pos_ecr), "ovr": r1(ro["ecr"]) if ro else None, "sd": r1(rr["sd"]) if rr else None,
                    "ppw": r1(ppw, 2), "src": ros_src},
            "lens": {"pts": r1(ss.get("pts_ppr")), "gp": int(ss.get("gp") or 0), "rk": ss.get("pos_rank_ppr"),
                     "rw_ppw": r1(rw_ppw, 2)},
            "nx": [r1(x) for x in nx], "n3": r1(sum(nx) / len(nx), 2) if nx else None,
            "mkt": {"v": fc.get("v10"), "v8": fc.get("v8"), "trend": fc.get("trend"), "rank": fc.get("rank"),
                    "tier": fc.get("tier")} if fc else None,
            "snap": [r1(snaps[k] * 100, 0) for k in sorted(snaps)[-4:]] if snaps else None,
            "ffb": fb or None,
            "sig": sig,
        })

    players.sort(key=lambda x: (x["ros"]["ovr"] or 999, -(x["ros"]["ppw"] or 0)))
    meta = {
        "generated": NOW.isoformat(timespec="minutes"), "season": C.SEASON, "week": week, "season_type": season_type,
        "ros_from": ros_from, "next_weeks": next_weeks, "weeks_left": weeks_left, "fp_scrape": fp_scrape,
        "late_move_base": base_t.isoformat(timespec="minutes") if base_t else None,
        "ros_move_base": ros_t.isoformat(timespec="minutes") if ros_t else None,
        "footballers": sorted(os.path.basename(f) for f in glob.glob(os.path.join(INPUTS, "footballers", f"wk{week}_*.txt"))),
        "counts": {"players": len(players), "signals": sig_count, "fantasycalc": len(FC)},
        "user": C.SLEEPER_USER_ID, "repo": C.REPO,
    }
    model = {"ros_curve": {p: {"rank": c["rank"], "ppw": c["ppw"]} for p, c in CAL["ros_curve"].items()},
             "weekly_error": CAL["weekly_error"], "qb_stream_bonus": CAL.get("qb_stream_bonus", 0)}
    os.makedirs(OUT, exist_ok=True)
    for name, obj in (("players", players), ("leagues", leagues), ("meta", meta), ("model", model)):
        with open(os.path.join(OUT, f"{name}.json"), "w") as f:
            json.dump(obj, f, separators=(",", ":"))
    if write_snapshot:
        os.makedirs(SNAPDIR, exist_ok=True)
        with open(os.path.join(SNAPDIR, NOW.strftime("%Y-%m-%dT%H") + ".json"), "w") as f:
            json.dump(snap, f, separators=(",", ":"))
    log(f"week {week} (ROS from {ros_from}); {len(players)} players, {sig_count} signals; FP scrape {fp_scrape}; "
        f"late-move base {base_t}; ROS base {ros_t}")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-snapshot", action="store_true")
    a = ap.parse_args()
    build(write_snapshot=not a.no_snapshot)
