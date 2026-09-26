# Front Office

Start/sit, waivers, trades and values for three Sleeper leagues (Maywood, Gridiron, Poker), as a web app you can add to an iPhone home screen.

- **App:** `site/` — static page served by GitHub Pages. It reads `site/data/*.json` and pulls rosters, free agents and matchups live from Sleeper each time it opens.
- **Engine:** `engine/` — Python (standard library only). Gathers every source, computes player-level numbers, writes `site/data/`.
- **Schedule:** `.github/workflows/refresh.yml` runs the engine daily at ~7 am CT, Tuesday night after MNF, Thursday afternoon and Sunday after inactives, then redeploys the site. Run it any time from the Actions tab ("Run workflow").

## Sources

| Source | Used for | How |
|---|---|---|
| FantasyPros consensus (weekly, rest of season, K/DST) | Rankings, weekly points, ROS order, expert spread | DynastyProcess mirror on GitHub, scraped twice daily |
| Rotowire via Sleeper | Weekly and future-week projections, season stats | Sleeper API |
| Sleeper | Leagues, rosters, matchups, trending adds/drops, injuries, FAB history | Sleeper API (also live in the app) |
| FantasyCalc | Trade market values and 30-day trend | FantasyCalc API |
| nflverse | Schedule, byes, Vegas lines, snap counts | GitHub |
| Fantasy Footballers | Weekly ranks and waiver list | Pasted into `inputs/footballers/` (the app's Data sheet prefills a GitHub commit) |

How the numbers are built, and the 2024–25 backtests behind them, are in `docs/ARCHITECTURE.md`.

## One-time setup

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Settings → Actions → General → Workflow permissions: Read and write.**
3. Run the workflow once (Actions → refresh → Run workflow). The site appears at `https://luke-benham.github.io/FantasyTools/`.
4. On the iPhone, open that address in Safari → Share → **Add to Home Screen**.

## Local run

```sh
python -m engine.build            # writes site/data and a snapshot
cd site && python -m http.server  # open http://localhost:8000
```

`python -m engine.seed_snapshots <dynastyprocess-data-clone>` rebuilds the FantasyPros history used for movement signals.
