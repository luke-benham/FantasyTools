"""One-off: rebuild snapshots/fp/*.json from the DynastyProcess repo's git history so movement signals
work from the first run.  Usage: python -m engine.seed_snapshots /path/to/dynastyprocess-data-clone [since]"""
import csv, datetime as dt, io, json, os, subprocess, sys

from . import config as C
from .net import csv_get
from .build import SNAPDIR, fix_team, load_games, num

repo = sys.argv[1]
since = sys.argv[2] if len(sys.argv) > 2 else "2026-09-15"


def versions(path):
    out = subprocess.run(["git", "-C", repo, "log", "origin/master", "--format=%H %cI", f"--since={since}", "--", path],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return sorted((dt.datetime.fromisoformat(l.split()[1]), l.split()[0]) for l in out if l.strip())


def show(sha, path):
    txt = subprocess.run(["git", "-C", repo, "show", f"{sha}:{path}"], capture_output=True, text=True, check=True).stdout
    return list(csv.DictReader(io.StringIO(txt)))


ids = {r["fantasypros_id"]: r["sleeper_id"] for r in csv_get(C.FP_MIRROR + "db_playerids.csv", max_age_h=20, name="db_playerids.csv")
       if r["fantasypros_id"] not in ("", "NA") and r["sleeper_id"] not in ("", "NA")}
games = load_games()
windows = []
for w, g in sorted(games.items()):
    first = dt.date.fromisoformat(min(x["day"] for x in g.values()))
    windows.append((w, first - dt.timedelta(days=2)))


def week_of(t):
    wk = None
    for w, start in windows:
        if t.date() >= start:
            wk = w
    return wk


ros_versions = versions("files/db_fpecr_latest.csv")
ros_cache = {}
os.makedirs(SNAPDIR, exist_ok=True)
for t, sha in versions("files/fp_latest_weekly.csv"):
    weekly = {}
    for r in show(sha, "files/fp_latest_weekly.csv"):
        page = r["page"].replace("ppr-", "").upper()
        if page not in ("QB", "RB", "WR", "TE", "K", "DST"):
            continue
        sid = fix_team(r["team"]) if page == "DST" else ids.get(r["fantasypros_id"])
        if sid and num(r["ecr"]):
            weekly[sid] = num(r["ecr"])
    rv = [v for v in ros_versions if v[0] <= t]
    ros, ovr = {}, {}
    if rv:
        rsha = rv[-1][1]
        if rsha not in ros_cache:
            ros_cache[rsha] = show(rsha, "files/db_fpecr_latest.csv")
        for r in ros_cache[rsha]:
            pt = r["page_type"]
            if not pt.startswith("redraft-") or "ros-" not in r["fp_page"]:
                continue
            kind = pt.split("-", 1)[1].upper()
            sid = fix_team(r["team"]) if kind == "DST" else ids.get(r["id"])
            if not sid or not num(r["ecr"]):
                continue
            (ovr if kind == "OVERALL" else ros)[sid] = num(r["ecr"])
    snap = {"weekly": weekly, "ros": ros, "ovr": ovr, "fp_scrape": t.date().isoformat(), "week": week_of(t), "seeded": True}
    fn = os.path.join(SNAPDIR, t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H") + ".json")
    json.dump(snap, open(fn, "w"), separators=(",", ":"))
    print(fn, snap["week"], len(weekly), len(ros))
