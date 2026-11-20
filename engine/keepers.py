"""Keeper value for leagues with an inputs/keepers/<league>.json history (Maywood).

For every player who could be kept next season this computes:
  cost      the round his keeper pick would cost, from the league's escalation rule and his draft history
  price     where he is expected to be drafted next August (median and range), from FantasyPros + FantasyCalc
            dynasty ranks, FantasyPros rest-of-season rank, an age shift and Maywood's own position pricing
  surplus   the player's value minus the value of the cost pick, on the realized pick value curve
            (100 = an average first-round pick, 0 = pick 170, the waiver line). Player value = curve at his
            projected rank × his position's realized share (QBs about half). Cost pick = the owner's projected
            slot in a snake draft run in reverse standings. 96 value draws, so the app can
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
_CUR = {"pv": PV, "picks": PICKS}        # the league being built: its own curve (size, lineup, draft length)


def skill_norm(pv):
    """Position value relative to RB/WR/TE. The raw curve averages every player taken at a pick, QBs included, so
    a flex player drafted exactly where he belongs realizes 8–35% more than the curve (more in 8-team, 3-FLEX
    leagues). A pick is spent on whoever is best there, so the cost of a pick is a flex player's value at it:
    RB/WR/TE are scaled to 1.0 and QB keeps its relative discount."""
    m = (pv["RB"] + pv["WR"] + pv["TE"]) / 3
    return {k: round(v / m, 3) for k, v in pv.items()}


def use_curve(key):
    """Pick the league's curve: Maywood's main fit, or the per-league fit from research section 7."""
    lc = (MODEL.get("leagues") or {}).get(key)
    if key == "maywood" or not lc:
        _CUR.update(pv=PV, picks=PICKS)
        return {"pick_value": PV, "picks": PICKS, "pos_value": skill_norm(MODEL["pos_value"]), "pos_price": MODEL["maywood_pos_price"]}
    _CUR.update(pv=lc["pick_value"], picks=lc["picks"])
    return {"pick_value": lc["pick_value"], "picks": lc["picks"], "pos_value": skill_norm(lc["pos_value"]),
            "pos_price": lc.get("pos_price") or MODEL["maywood_pos_price"]}


def pick_value(n):
    """Value of overall pick n: 100 = an average first-round pick, 0 at the waiver line (the league's last pick).
    Realized 2021-25 points above replacement for the league's lineup."""
    pv, picks = _CUR["pv"], _CUR["picks"]
    n = min(max(n, 1.0), picks)
    for i in range(1, len(pv)):
        if n <= pv[i][0]:
            x0, y0 = pv[i - 1]; x1, y1 = pv[i]
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


def forward(rnd, rev=0):
    """Does round rnd run slot 1 -> N? Snake; with a third-round reversal (Sleeper reversal_round = 3) round 3
    repeats round 2's direction and the alternation flips from there."""
    return (rnd % 2 == 1) if (not rev or rnd < rev) else (rnd % 2 == 0)


def round_pick(rnd, teams, slot=None, rev=0):
    """Overall pick of a keeper cost round. slot = the owner's draft slot (1 = first pick); None = middle of the round."""
    if slot is None:
        return teams * (rnd - 1) + (teams + 1) / 2
    return teams * (rnd - 1) + (slot if forward(rnd, rev) else teams + 1 - slot)


def project_slots(rosters):
    """Next draft runs in reverse regular-season standings: worst record picks first (points for breaks ties)."""
    order = sorted(rosters, key=lambda r: (r.get("w", 0) - r.get("l", 0), r.get("pf", 0)))
    return {r["rid"]: i + 1 for i, r in enumerate(order)}


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
    seasons = H["seasons"]
    curve = use_curve(L["key"])

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
    dinfo = json_get(f"{SL}/v1/draft/{draft_id}", max_age_h=24, name=f"draft_{draft_id}.json") if draft_id else {}
    dset = (dinfo or {}).get("settings") or {}
    last_round = int(H.get("rounds") or dset.get("rounds") or len(L["slots"]))
    rev = int(H.get("reversal_round", dset.get("reversal_round") or 0) or 0)

    def cost_rounds(sid):
        """Cost round for nxt, nxt+1, ... while keepable. Cost follows the player through trades and drops."""
        k = streak(sid)
        p = drafted.get(sid)
        base = p["round"] if p else last_round + 1        # undrafted: first keep costs the last round
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
    posf = curve["pos_price"]
    posv = curve["pos_value"]
    aug = dt.date(nxt, 8, 15)

    slots = project_slots(L["rosters"])
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
        own_slot = slots.get(rostered.get(sid))               # None for free agents: middle of the round
        c_pick = round_pick(costs[0], teams, own_slot, rev)
        c_val = pick_value(c_pick)

        # this season's value draws (seeded per player so refreshes only move when inputs move); the app
        # subtracts each team's own cost pick, so a trade moves the cost to the new owner's slot
        rng = random.Random(int(sid) if sid.isdigit() else hash(sid))
        vdraws = [round(pv * pick_value(rank * math.exp(sd * rng.gauss(0, 1))) * 10) for _ in range(N_DRAWS)]
        e1 = sum(max(0.0, v / 10 - c_val) for v in vdraws) / N_DRAWS
        es = [round(sum(max(0.0, v / 10 - pick_value(round_pick(costs[0], teams, sl, rev))) for v in vdraws) / N_DRAWS, 1)
              for sl in range(1, teams + 1)]
        if max(es) < 0.3 and sid not in rostered and sid not in drafted:
            continue

        # later seasons, at every draft slot (next year's slot is projected; later ones are unknown, so they
        # assume the same slot)
        def seasons(slot):
            yrs, K, pr, s2 = [], 0.0, rank, sd ** 2
            for t, cr in enumerate(costs):
                if t:
                    pr *= math.exp(drift(pos, age + t))
                    s2 += MODEL["sigma_yoy"][pos] ** 2
                ev = e_pos(pr, math.sqrt(s2), pick_value(round_pick(cr, teams, slot, rev)), pv)
                yrs.append({"y": nxt + t, "c": cr, "p": round(pr * posf.get(pos, 1.0), 1), "e": round(ev, 1)})
                K += DISCOUNT ** t * ev
            run = 0
            for y in yrs:
                if y["e"] < 1.0:
                    break
                run += 1
            return yrs, K, run
        yrs, K, runway = seasons(own_slot)
        Ks, runs = [], []
        for sl in range(1, teams + 1):
            _, k_s, r_s = seasons(sl)
            Ks.append(round(k_s, 1)); runs.append(r_s)

        lo, hi = price * math.exp(-1.2816 * sd), price * math.exp(1.2816 * sd)
        out.append({
            "id": sid, "pos": pos, "age": round(age, 1), "origin": origin, "keeps": k, "r_now": r_now,
            "cost": costs[0], "costs": costs, "cpick": round(c_pick, 1), "cval": round(c_val, 1),
            "price": round(price, 1), "lo": round(lo), "hi": round(hi), "rank": round(rank, 1),
            "val": round(pv * pick_value(rank), 1),
            "e": round(e1, 1), "p_pos": round(sum(v / 10 > c_val for v in vdraws) / N_DRAWS, 2),
            "K": round(K, 1), "runway": runway, "years": yrs, "es": es, "Ks": Ks, "runs": runs,
            "src": {"fp": a, "fc": b, "ros": rr, "pre": pre.get(sid)}, "v": vdraws,
        })
    out.sort(key=lambda x: -x["e"])
    return {
        "league": L["key"], "season": nxt, "generated": now.isoformat(timespec="minutes"), "mode": mode,
        "preseason_date": pre_date, "fc_error": fc_err, "draws": N_DRAWS, "teams": teams,
        "per_team": H.get("keepers_per_team", 1), "rule": R, "slots": slots,
        "rounds": last_round, "reversal": rev, "picks": curve["picks"], "history_known": bool(H.get("history_known", True)),
        "kept": {y: sorted(v) for y, v in kept.items()},
        "model": {"pick_value": curve["pick_value"], "blend_weight_dynasty": w, "pos_price": posf, "pos_value": posv, "discount": DISCOUNT,
                  "sigma": MODEL["sigma_nov_aug"] if mode == "dynasty" else MODEL["sigma_preseason"],
                  "backtest": MODEL["summary"], "years": MODEL["years"]},
        "players": out,
    }
