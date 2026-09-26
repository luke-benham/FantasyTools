# Research

Backtests behind the engine (2024–25). Data setup is described at the top of `source_backtest.py`; results are summarized in `docs/ARCHITECTURE.md`.

- `source_backtest.py` — FantasyPros vs Rotowire vs blend, weekly and ROS
- `lag_test.py` — does FantasyPros lag news (Thursday vs Sunday, ROS momentum, expert spread)
- `calibrate.py` — ROS points curve and weekly error model (writes `engine/calibration.json`)
