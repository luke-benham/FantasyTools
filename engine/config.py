"""Static settings for the Front Office engine."""

SEASON = 2026
SLEEPER_USERNAME = "juikmn"
SLEEPER_USER_ID = "867908795513364480"
REPO = "luke-benham/FantasyTools"

# key, Sleeper league id, display name, color (colorblind-safe trio used everywhere)
LEAGUES = [
    {"key": "maywood", "id": "1388924725622747136", "name": "Maywood", "color": "#0B6BAE"},
    {"key": "gridiron", "id": "1395271982236332032", "name": "Gridiron", "color": "#C8650A"},
    {"key": "poker", "id": "1403194738567303169", "name": "Poker", "color": "#8E3D8A"},
]

LAST_FANTASY_WEEK = 17          # playoffs weeks 15-17 in all three leagues
SKILL = ["QB", "RB", "WR", "TE"]
ALL_POS = SKILL + ["K", "DEF"]

# FantasyPros / nflverse team codes -> Sleeper
TEAMFIX = {"JAC": "JAX", "LVR": "LV", "LA": "LAR", "WSH": "WAS", "STL": "LAR", "SD": "LAC", "OAK": "LV"}

FP_MIRROR = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/"
NFLVERSE_GAMES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
NFLVERSE_SNAPS = "https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv"
FANTASYCALC = "https://api.fantasycalc.com/values/current?isDynasty=false&numQbs=1&numTeams={teams}&ppr=1"

# Weekly late-move nudge: extrapolate this share of the Thursday->now ECR move (tested 2025: helps QB/WR/TE, neutral RB)
LATE_MOVE_K = 0.5
