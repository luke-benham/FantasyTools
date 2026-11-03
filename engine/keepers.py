"""Keeper value for leagues with an inputs/keepers/<league>.json history (Maywood).

For every player who could be kept next season this computes:
  cost      the round his keeper pick would cost, from the league's escalation rule and his draft history
  price     where he is expected to be drafted next August (median and range), from FantasyPros + FantasyCalc
            dynasty ranks, FantasyPros rest-of-season rank, an age shift and Maywood's own position pricing
  surplus   the player's value minus the value of the cost pick, on the realized pick value curve
            (100 = pick 1, 0 = pick 170, the waiver line). Player value = curve at his projected rank ×
            his position's realized share (QBs 0.47 once streaming is counted). 96 draws, so the app can
            value any set of keeper options ("best of my candidates") on live rosters
  runway    later seasons he stays worth keeping as the cost escalates and his price drifts with age

Every number is fitted in research/keeper_backtest.py (engine/keeper_model.json). Standard library only.
"""
import datetime as dt, json, math, os, random, statistics as st

from . import config as C
from .net import json_get, num

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = json.load(open(os.path.join(ROOT, "engine", "keeper_model.json")))
SL = "https://api.sleeper.app"
FC_DYN = "https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=1&numTeams={teams}&ppr=1"
SKILL = ("QB", "RB", "WR", "TE")
N_DRAWS = 96
MISS = 300                       # rank for a player missing from a list
DISCOUNT = 0.65                  # later seasons: injury/role risk and a keeper slot that may go to someone better
MAX_YEARS = 5


# ---------------------------------------------------------------- model pieces
PV = MODEL["pick_value"]
PICKS = MODEL["picks"]


def pick_value(n):
    """Value of overall pick n: 100 at pick 1, 0 at the waiver line (pick 170). Realized 2021-25 points above replacement."""
    n = min(max(n, 1.0), PICKS)
    for i in range(1, len(PV)):
        if n <= PV[i][0]:
            x0, y0 = PV[i - 1]; x1, y1 = PV[i]
            return y0 + (y1 - y0) * (n - x0) / (x1 - x0)
    return 0.0


def bucket(age):
    for lo, hi, lab in MODEL["age_buckets"]:
        if lo <= age <= hi:
            return lab
    return MODEL["age_buckets"][-1][2]


def age_shift(pos, age):
    return MODEL["age_shift"][f"{pos}|{bucket(int(age))}"]


def drift(pos, age):
    return MODEL["drift_yoy"][f"{pos}|{bucket(int(age))}"]


def round_pick(rnd, teams):
    """Overall pick of a keeper cost round: middle of the round (the owner's 2027 slot isn't known yet)."""
    return teams * (rnd - 1) + (teams + 1) / 2


# 32-point normal quadrature for expectations; seeded draws for the app
_Q = [st.NormalDist().inv_cdf((i + 0.5) / 32) for i in range(32)]


def e_pos(price, sd, cost_val, pv=1.0):
    """E[max(0, pv·V(price·e^(sd·z)) − cost_val)]."""
    return sum(max(0.0, pv * pick_value(price * math.exp(sd * z)) - cost_val) for z in _Q) / len(_Q)


# ---------------------------------------------------------------- inputs
def load_history(key):
    path = os.path.join(ROOT, "inputs", "keepers", f"{key}.json")
    return json.load(open(path)) if os.path.exists(path) else None


def skill_rank(pairs):
    """[(sid, ecr)] -> {sid: rank among skill players}."""
    return {sid: i + 1 for i, (sid, _) in enumerate(sorted(pairs, key=lambda x: x[1]))}


def fc_dynasty(teams):
    out = {}
    try:
        rows = json_get(FC_DYN.format(teams=teams))
    except Exception as e:  # never fail the build on a context source
        return out, str(e)
    pairs = []
    for x in rows:
        p = x.get("player") or {}
        sid = str(p.get("sleeperId") or "")
        if sid and p.get("position") in SKILL and x.get("value"):
            pairs.append((sid, -x["value"]))
    return skill_rank(pairs), None


# ---------------------------------------------------------------- main
def build_keepers(L, PL, ecrdb, ids, ros_ovr, now):
    """L: the league dict written to leagues.json (rosters, users). ids: FantasyPros id -> Sleeper id.
    ros_ovr: {sid: {"ecr", "pos"}} FantasyPros ROS overall. Returns the keepers.json object or None."""
    H = load_history(L["key"])
    if not H:
        return None
    R = H["rule"]
    season, nxt = C.SEASON, C.SEASON + 1
    teams = L["teams"]
    last_round = len(L["slots"])                       # Maywood: 17 rounds = 17 roster spots
    seasons = H["seasons"]

    # ---- keeper streaks and this season's draft
    kept = {y: {k["id"] for k in s.get("keepers", [])} for y, s in seasons.items()}

    def streak(sid):
        n, y = 0, season
        while str(y) in kept and sid in kept[str(y)]:
            n += 1; y -= 1
        return n

    draft_id = seasons.get(str(season), {}).get("draft_id")
    picks = json_get(f"{SL}/v1/draft/{draft_id}/picks", max_age_h=24, name=f"picks_{draft_id}.json") if draft_id else []
    drafted = {p["player_id"]: p for p in picks}

    def cost_rounds(sid):
        """Cost round for nxt, nxt+1, ... while keepable. Cost follows the player through trades and drops."""
        k = streak(sid)
        p = drafted.get(sid)
        base = p["round"] if p else R.get("undrafted_base_round", last_round + 1)
        out, c = [], base
        for t in range(MAX_YEARS):
            c = c - (k + 1 + t)
            if c < 1:
                if R.get("floor_at_round_1"):
                    c = 1
                else:
                    break
            out.append(c)
        return out, k, ("kept" if k else "drafted" if p else "undrafted"), (p["round"] if p else None)

    # ---- price inputs
    fp_dyn_pairs, pre_pairs, pre_date = [], [], None
    for r in ecrdb:
        if r["page_type"] == "dynasty-overall":
            sid = ids.get(r["id"]); pos = (r["pos"] or "").rstrip("0123456789")
            e = num(r["ecr"])
            if sid and pos in SKILL and e is not None:
                fp_dyn_pairs.append((sid, e))
        elif r["page_type"] == "redraft-overall" and "cheatsheets" in r["fp_page"] and r["scrape_date"][:4] == str(nxt):
            sid = ids.get(r["id"]); pos = (r["pos"] or "").rstrip("0123456789")
            e = num(r["ecr"])
            if sid and pos in SKILL and e is not None:
                pre_pairs.append((sid, e)); pre_date = r["scrape_date"]
    fp_dyn = skill_rank(fp_dyn_pairs)
    fc_dyn, fc_err = fc_dynasty(teams)
    ros = skill_rank([(s, r["ecr"]) for s, r in ros_ovr.items() if r.get("pos") in SKILL and r.get("ecr")])
    pre = skill_rank(pre_pairs) if len(pre_pairs) >= 150 else {}
    mode = "preseason" if pre else "dynasty"
    w = MODEL["blend_weight_dynasty"]
    posf = MODEL["maywood_pos_price"]
    posv = MODEL["pos_value"]
    aug = dt.date(nxt, 8, 15)

    rostered = {}
    for r in L["rosters"]:
        for sid in (r.get("players") or []) + (r.get("reserve") or []):
            rostered[sid] = r["rid"]
    cands = set(rostered) | set(drafted) | {s for s, rk in fp_dyn.items() if rk <= 220} | {s for s, rk in fc_dyn.items() if rk <= 220}

    out = []
    for sid in cands:
        p = PL.get(sid)
        if not p or p.get("position") not in SKILL:
            continue
        pos = p["position"]
        bd = p.get("birth_date")
        try:
            age = (aug - dt.date.fromisoformat(bd)).days / 365.25
        except (TypeError, ValueError):
            age = (p.get("age") or 25) + 0.75
        a, b, rr = fp_dyn.get(sid), fc_dyn.get(sid), ros.get(sid)

        if mode == "preseason":
            if sid not in pre:
                continue
            logp, sd = math.log(pre[sid]), MODEL["sigma_preseason"]
        else:
            dyn = [x for x in (a, b) if x]
            if not dyn:
                continue
            ld = sum(math.log(x) for x in dyn) / len(dyn) + age_shift(pos, age)
            # a player missing from the ROS list is usually injured or not playing this year: dynasty only
            logp = w * ld + (1 - w) * math.log(rr) if rr else ld
            sd = MODEL["sigma_nov_aug"][pos]
        rank = math.exp(logp)                  # projected FantasyPros-scale rank: sets the player's value
        price = rank * posf.get(pos, 1.0)      # where Maywood would actually draft him
        pv = posv.get(pos, 1.0)

        costs, k, origin, r_now = cost_rounds(sid)
        if not costs:
            continue
        c_pick = round_pick(costs[0], teams)
        c_val = pick_value(c_pick)

        # this season's draws (seeded per player so refreshes only move when inputs move)
        rng = random.Random(int(sid) if sid.isdigit() else hash(sid))
        draws = [round((pv * pick_value(rank * math.exp(sd * rng.gauss(0, 1))) - c_val) * 10) for _ in range(N_DRAWS)]
        e1 = sum(max(0, d) for d in draws) / N_DRAWS / 10
        if e1 < 0.3 and sid not in rostered and sid not in drafted:
            continue

        # later seasons
        yrs, K, pr, s2 = [], 0.0, rank, sd ** 2
        for t, cr in enumerate(costs):
            if t:
                pr *= math.exp(drift(pos, age + t))
                s2 += MODEL["sigma_yoy"][pos] ** 2
            ev = e_pos(pr, math.sqrt(s2), pick_value(round_pick(cr, teams)), pv)
            yrs.append({"y": nxt + t, "c": cr, "p": round(pr * posf.get(pos, 1.0), 1), "e": round(ev, 1)})
            K += DISCOUNT ** t * ev
        runway = 0
        for y in yrs:
            if y["e"] < 1.0:
                break
            runway += 1

        lo, hi = price * math.exp(-1.2816 * sd), price * math.exp(1.2816 * sd)
        out.append({
            "id": sid, "pos": pos, "age": round(age, 1), "origin": origin, "keeps": k, "r_now": r_now,
            "cost": costs[0], "cpick": round(c_pick, 1), "cval": round(c_val, 1),
            "price": round(price, 1), "lo": round(lo), "hi": round(hi), "rank": round(rank, 1),
            "val": round(pv * pick_value(rank), 1),
            "e": round(e1, 1), "p_pos": round(sum(d > 0 for d in draws) / N_DRAWS, 2),
            "K": round(K, 1), "runway": runway, "years": yrs,
            "src": {"fp": a, "fc": b, "ros": rr, "pre": pre.get(sid)}, "d": draws,
        })
    out.sort(key=lambda x: -x["e"])
    return {
        "league": L["key"], "season": nxt, "generated": now.isoformat(timespec="minutes"), "mode": mode,
        "preseason_date": pre_date, "fc_error": fc_err, "draws": N_DRAWS, "teams": teams,
        "per_team": H.get("keepers_per_team", 1), "rule": R,
        "kept": {y: sorted(v) for y, v in kept.items()},
        "model": {"pick_value": PV, "blend_weight_dynasty": w, "pos_price": posf, "pos_value": posv, "discount": DISCOUNT,
                  "sigma": MODEL["sigma_nov_aug"] if mode == "dynasty" else MODEL["sigma_preseason"],
                  "backtest": MODEL["summary"], "years": MODEL["years"]},
        "players": out,
    }
