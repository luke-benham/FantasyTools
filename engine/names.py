"""Name matching for sources without ids (Fantasy Footballers pastes)."""
import re, unicodedata

SKILL_K = ["QB", "RB", "WR", "TE", "K"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`’]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    while True:
        t = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", s)
        if t == s:
            return s
        s = t


class Index:
    def __init__(self, players):
        self.PL = players
        self.by_full, self.by_init, self.defs = {}, {}, {}
        for pid, p in players.items():
            if p.get("position") == "DEF":
                self.defs[p.get("team") or pid] = pid
                continue
            pos = [x for x in (p.get("fantasy_positions") or [p.get("position")]) if x in SKILL_K]
            f, l = norm(p.get("first_name")), norm(p.get("last_name"))
            if not pos or not f or not l:
                continue
            self.by_full.setdefault(f"{f} {l}", []).append(pid)
            for x in pos:
                self.by_init.setdefault((f[0], l, x), []).append(pid)

    def choose(self, cands, team=None):
        c = list(dict.fromkeys(cands))
        if team:
            c = [x for x in c if (self.PL[x].get("team") or "FA") == team] or c
        c = [x for x in c if self.PL[x].get("active")] or c
        c.sort(key=lambda x: self.PL[x].get("search_rank") or 10 ** 7)
        return c[0] if c else None

    def match(self, name, team=None, pos=None):
        n = norm(name)
        if not n:
            return None
        if pos in ("DEF", "DST"):
            return self.defs.get(team)
        pid = self.choose(self.by_full.get(n, []), team)
        if pid:
            return pid
        if " " in n:
            f, l = n.split(" ", 1)
            ps = [pos] if pos else SKILL_K
            return self.choose(sum((self.by_init.get((f[0], l, x), []) for x in ps), []), team)
        return None
