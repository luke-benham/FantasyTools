"""Tiny HTTP helpers (standard library only) with retries and an on-disk cache."""
import csv, io, json, os, time, urllib.error, urllib.request

UA = {"User-Agent": "front-office-ff/1.0 (+github.com/juikmnjui/FantasyTools)"}
CACHE = os.environ.get("FO_CACHE", ".cache")


def fetch(url, max_age_h=0, name=None, tries=3):
    """Return bytes. With max_age_h>0 reuse a cached copy younger than that."""
    path = os.path.join(CACHE, name) if name else None
    if path and max_age_h and os.path.exists(path) and (time.time() - os.path.getmtime(path)) / 3600 < max_age_h:
        return open(path, "rb").read()
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                data = r.read()
            if path:
                os.makedirs(CACHE, exist_ok=True)
                open(path, "wb").write(data)
            return data
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def json_get(url, **kw):
    return json.loads(fetch(url, **kw))


def csv_get(url, **kw):
    return list(csv.DictReader(io.StringIO(fetch(url, **kw).decode("utf-8"))))


def num(x, default=None):
    try:
        if x in (None, "", "NA"):
            return default
        return float(x)
    except (TypeError, ValueError):
        return default
