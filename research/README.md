# Research

Backtests behind the engine (2024–25). Data setup is described at the top of `source_backtest.py`; results are summarized in `docs/ARCHITECTURE.md`.

- `source_backtest.py` — FantasyPros vs Rotowire vs blend, weekly and ROS
- `lag_test.py` — does FantasyPros lag news (Thursday vs Sunday, ROS momentum, expert spread)
- `calibrate.py` — ROS points curve and weekly error model (writes `engine/calibration.json`)
- `keeper_backtest.py` — Maywood keeper model: November dynasty/ROS ranks vs next August's price (2020–24), age shifts, year-over-year drift, the pick value curve from realized 2021–25 points above replacement, Maywood's position pricing, and option value of a second keeper candidate (writes `engine/keeper_model.json`)
