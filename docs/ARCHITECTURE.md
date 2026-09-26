# Front Office — architecture and evidence

Written 2026-09-25 (NFL week 3), updated same day with the lag test, signals, Sleeper lens, decisions and architecture. Covers the three tools being built: **start/sit**, **waiver recommender**, **trade analyzer**. Read with `trade-system-handoff.md` (leagues, value model, conventions) and `source_backtest.py.txt` / `lag_test.py.txt` (the tests below). **Roles:** the architect chat designs and builds; other chats use the app and do fantasy investigations.

## 1. What published research says

- **Aggregation wins, and no single source stays on top.** Fantasy Football Analytics scored 11 sources over 2014–2025 (seasonal) and 2015–2025 (weekly). The two aggregators (FFA average, FantasyPros consensus) were the most reliable across positions; individual sources (CBS, ESPN, NumberFire, FFToday) took turns leading and then collapsed. Weighting sources by past accuracy was no better than a simple average, because source accuracy does not persist year to year.
- **Projections exaggerate spread.** Top-projected players underperform, lower ones slightly overperform. Calibration slope seasonal QB 0.67, RB 0.79, WR 0.85, TE 0.72; weekly RB 0.91, WR 0.75, TE 0.72. Weekly projections explain only ~3–23% of within-position variance.
- **FantasyPros 2025 in-season accuracy:** Justin Boone (Yahoo) 1st, Pat Thorman (Establish the Run) 2nd — Thorman's fourth straight top-4, one of few persistent experts.
- **Fantasy Footballers:** top-25 in-season finishes 2017–2020 (Holloway #5 in 2018, #7 in 2020; Moore #6 in 2019), then stopped submitting to FantasyPros. No independent accuracy data since 2020.
- **Draft Sharks:** strong FantasyPros *draft* (preseason) accuracy (Jody Smith #1 multi-year; Kevin English 2024; Smola 2023). Nothing independent on their in-season, ROS or trade values.
- **Trade value charts have no accuracy studies.** They measure price, not outcomes. FantasyCalc solves values from millions of real trades — the best "what will people accept" signal.
- **K/DST:** Subvertadown reports its D/ST model #1 for 2025 (its own measurement; paid).

## 2. Our own backtest (2024 + 2025)

Data: FantasyPros ECR history from the DynastyProcess GitHub mirror (2024 Friday snapshots weeks 4–17; 2025 **Sunday ~9:15 am ET** snapshots weeks 1–17, from the repo's git history), Rotowire weekly projections and Sportradar actuals from Sleeper. Pools: top 24 QB, 48 RB, 60 WR, 24 TE by ECR, players who played. Metric: share of player pairs the source ordered correctly (all pairs / close calls within 6 ECR spots), full PPR.

| Pooled 2024–25 | FP ECR | Rotowire | 50/50 blend |
|---|---|---|---|
| QB | 59.8 / 53.9 | 59.9 / 54.2 | **60.2 / 54.4** |
| RB | 70.7 / 54.6 | 71.4 / 56.8 | **71.5 / 57.0** (beat ECR 22 of 31 weeks) |
| WR | 65.3 / 52.9 | 64.8 / 52.4 | **65.5 / 53.4** |
| TE | **61.8 / 55.7** | 61.2 / 54.3 | 61.5 / 54.8 |
| Flex, RB vs WR vs TE (2025) | 61.4 | 61.6 | 61.6 |

ROS (Spearman vs actual points for the rest of the season, pooled): FP ROS ECR — RB .63, WR .40, TE .33, QB .25. Points-per-game-to-date — RB .56, WR .35, TE .20, QB .30. Mixing PPG into ECR helped in 2024 and hurt in 2025: no reliable gain.

**Conclusions**
1. FantasyPros ECR and Rotowire are statistically tied for weekly decisions; the 50/50 blend is never the worst and is best at RB and QB. Use the blend.
2. Close start/sit calls are right only 53–57% of the time with any source. The start/sit tool must show confidence, not a bare verdict.
3. FantasyPros ROS ECR is the best-tested ROS input; performance-to-date adds nothing reliable on top.
4. Footballers and Draft Sharks can't be backtested (no history); they get tracked going forward.

## 3. Does FantasyPros lag the news? (tested)

Concern: ECR averages many experts, some update rarely, so it may react slowly.

- **Within the week, yes (a little).** 2025, Thursday ~9 am ET vs Sunday ~9 am ET weekly ECR. Sunday beat Thursday at every position (Spearman QB .251→.268, RB .557→.584, WR .409→.433, TE .306→.325). Players who rose late kept beating their Sunday rank (corr +0.02 to +0.11, largest at WR). Extrapolating half to one times the Thursday→Sunday move added a little more at QB (.283), WR (.437) and TE (.345); nothing at RB. → Use the freshest scrape, blend with Rotowire (updates continuously), apply a small late-move nudge (k≈0.5) in start/sit, and flag big late movers.
- **Across weeks, no.** Last week's ROS ECR move does not predict rest-of-season results beyond current ROS ECR (corr −0.01 to +0.05; extrapolating it helps WR/QB by <0.01 and hurts RB/TE). Experts catch up within about a week. → The risk window is the days between news and the next ECR update: waiver bids and mid-week trades. Fast signals are for *timing*, not for re-valuing.
- **Expert disagreement is not a risk meter.** ECR standard deviation barely predicts the size of a miss (corr −0.09 to +0.06). Show it as "experts split" (possible trade leverage), and use outcome-based ranges for risk: position-level projection error from the backtest plus the player's own weekly volatility.

## 4. Signals layer ("something changed")

Flags on players; they never silently change values.

| Signal | Source | Speed | Meaning |
|---|---|---|---|
| ECR move (Thu→Sun weekly; 7-day ROS) | FP mirror git history | twice daily | Consensus moving; late weekly moves tend to continue |
| Rotowire vs ECR gap (>1 tier) | Sleeper projections | continuous | One source knows something; blend handles, flag shows |
| FantasyCalc value change (1–7 day, trend30Day) | FantasyCalc | ~3 h | Market reacting to news before ECR |
| Sleeper trending adds/drops (24 h counts) | Sleeper | live | News detector; what leaguemates are reacting to |
| Usage shift (snap share ±15 pts, target/route share) | nflverse weekly | weekly | Role change ahead of rankings |
| Injury status / fresh news | Sleeper players (`injury_status`, `news_updated`) | live | Check before acting |
| Experts split (high sd, wide best–worst) | FP mirror | daily | Info / leverage only |
| Footballers vs ECR divergence | Footballers paste | weekly | Different read from the consensus |

FantasyCalc, trending and Footballers have no public history, so the pipeline snapshots them from now on and scores them later.

## 5. The Sleeper lens (how opponents see value)

Opponents on Sleeper see the Rotowire projections (weekly and future weeks), season points with positional finish, and trending adds; many also sync FantasyCalc (it logs in by Sleeper username). The trade tool shows three views side by side:
- **Our value** — league-adjusted ROS value (decision basis).
- **Sleeper lens** — Rotowire remaining-season projection + season-to-date points/positional rank, run through the same league value curve.
- **Market** — FantasyCalc redraft value (league size barely changes it: 8 vs 10 teams differ <1%), plus Draft Sharks when uploaded.

Buy targets: our value > Sleeper lens and market (they undervalue). Sell: season-to-date rank or Sleeper projection flatters the player versus our value. Trade pitches lean on the numbers the opponent sees.

## 6. Source stack per tool

| Tool | Core (drives the number) | Context (shown, not scored) | Tracked |
|---|---|---|---|
| Start/sit | 50/50 blend of FP weekly ECR (rank→points) and Rotowire stat projection scored to league settings; small late-move nudge | Signals, win % vs next option with "coin flip" band, Vegas implied total, injury, opponent | Footballers weekly ranks |
| Waivers | League value from FP ROS ECR (full list) + next-week blend for immediate need | Signals (trending, FantasyCalc move, usage), Footballers pickups, FAB left per team | Hit rate per source |
| Trades | League-adjusted ROS value (FP ROS ECR points blended with Rotowire remaining weeks); lineup change for both teams | Sleeper lens, FantasyCalc market, Draft Sharks, signals | — |

## 7. Decisions (2026-09-25/26)

1. **Runs:** GitHub Actions on a schedule plus manual "Run workflow" for mid-week trade checks.
2. **FantasyCalc:** in use (`api.fantasycalc.com/values/current?isDynasty=false&numQbs=1&numTeams={8|10}&ppr=1`; ~200 players with `sleeperId`, value, 30-day trend, tier).
3. **One cohesive app**, hosted on GitHub Pages (public repo `luke-benham/FantasyTools`), installable on iPhone.
4. **Footballers kept** as an independent read; scored weekly against the other sources.
5. **Chat roles:** architect chat designs/builds; other chats use it.

## 8. Architecture

```
GitHub Actions (cron + Run workflow)
  └─ python -m engine.build
       ├─ Sleeper API ........ state, players, projections (this week + future weeks), season stats,
       │                       trending, league settings/rosters/users/matchups/transactions (snapshot)
       ├─ FantasyPros mirror . weekly ECR (sd/best/worst, rank→points), ROS ECR (overall + positional)
       ├─ FantasyCalc ........ market values (8- and 10-team)
       ├─ nflverse ........... schedule, byes, Vegas lines → implied team totals, snap counts
       ├─ inputs/footballers . pasted weekly ranks / waiver list
       └─ snapshots/fp ....... our own FantasyPros history (late-week and 7-day moves)
     → site/data/{players,leagues,meta,model}.json  → commit → deploy Pages
Phone (Front Office web app)
  ├─ loads site/data/*.json
  ├─ fetches Sleeper live: rosters, users, matchups (CORS-enabled) → current rosters every open
  └─ runs league logic in the browser: value model, weekly lineups, waiver plan, trade evaluation, trade ideas
```

**Engine outputs per player:** weekly `mu` (calibrated blend, late-move nudge) and `sd` (position error model), FantasyPros and Rotowire parts, expert best/worst, opponent, kickoff, implied team total; ROS points per week (`ppw`) from the calibrated curve at the FantasyPros positional ROS rank; Sleeper lens (season points/rank, Rotowire points per remaining week); FantasyCalc market; snap shares; Footballers ranks; signals.

**Calibration (`engine/calibration.json`, from 2024–25):**
- ROS curve: points per remaining week by FantasyPros positional ROS rank (QB log-linear; RB/WR/TE log-quadratic), e.g. RB12 13.1, WR24 10.4, TE6 9.9, QB12 13.1.
- Weekly error: calibration slope ≈1 for QB/RB/TE, 0.93 WR, 0.64 K; SD ≈ a + b·projection (RB 2.9+0.32p, WR 3.2+0.33p, TE 2.2+0.46p, QB 4.5+0.17p).

**App logic (site/app.js):**
- *League value:* per league, starter lines from the curve (ideal fill of QB/RB/WR/TE + flex), waiver lines = 50/50 of a ranked fill of every roster spot and the live free agents (top-3 average); RB/WR/TE share one flex line; TE also has a TE-slot line; bench-level points count by 1−0.85^slots. Scaled to 100 = best player.
- *Lineup:* greedy fill (fixed slots first, then flex) on weekly `mu`; locked players stay; win % vs next option = Φ(Δμ/√(σ₁²+σ₂²)); matchup win % from both teams' totals.
- *Waivers:* top free agents by value, drop = lowest-value player that keeps starting requirements (QB/TE: one backup max); bid range by value gain × remaining FAB; K/DST streams by weekly projection; league winning-bid history.
- *Trades:* value delta after forced drops, both teams' ROS lineup change, FantasyCalc market delta, what Sleeper's projections show the other manager; one-for-one ideas where both lineups improve or the market sees it as fair.

**Schedule (UTC cron; Central shifts by an hour after Nov 1):** daily 12:00 (~7 am CT); Wed 02:30 (Tue ~9:30 pm CT); Thu 20:00 (~3 pm CT); Sun 15:45 and 16:45 (after inactives in either DST state). Pushes to `inputs/`, `engine/`, `site/` also trigger a run.

## 9. Next

- Design pass on the app with Luke; FAB bid calibration once more league bid history exists.
- Tracker: score FantasyPros, Rotowire, blend and Footballers weekly (pairwise accuracy, waiver hit rate) and show it in the Data sheet.
- Two-for-one trade ideas; playoff-week (15–17) weighting and bye-aware ROS lineups.
