# Fantasy Footballers inputs

One file per week and kind. The engine reads the files for the current Sleeper week.

- `wk{W}_waivers.txt` — the waiver list pasted as copied off their page: a name line, a team line like `CAR (@ ATL)`, then the list number. Repeated name lines are fine.
- `wk{W}_ranks.txt` — weekly ranks, one per line: `WR12 Name`, `RB3: Name (TEAM)` or `QB1 - Name`.

The quickest way to add one is the **Data** sheet in the app: paste, tap **Save to GitHub**, then **Commit**. The commit triggers a refresh.
