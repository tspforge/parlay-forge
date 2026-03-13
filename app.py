from flask import Flask, request, render_template_string
from typing import List, Dict, Any
from datetime import datetime, timedelta

app = Flask(__name__)

# -------------------------------------------------------------------
# SAMPLE DATA
# Replace this later with your real odds/model feed.
# IMPORTANT: game_time must be in ISO format: YYYY-MM-DDTHH:MM:SS
# -------------------------------------------------------------------
BETS: List[Dict[str, Any]] = [
    {
        "team": "Detroit Pistons",
        "odds": -1350,
        "sim_hit": 89.50,
        "ev": -3.87,
        "matchup": "Memphis Grizzlies @ Detroit Pistons",
        "sport": "NBA",
        "book": "FanDuel",
        "game_time": "2026-03-13T19:00:00",
    },
    {
        "team": "Detroit Pistons",
        "odds": -1200,
        "sim_hit": 88.70,
        "ev": -3.91,
        "matchup": "Memphis Grizzlies @ Detroit Pistons",
        "sport": "NBA",
        "book": "DraftKings",
        "game_time": "2026-03-13T19:00:00",
    },
    {
        "team": "New York Knicks",
        "odds": -800,
        "sim_hit": 85.45,
        "ev": -3.87,
        "matchup": "New York Knicks @ Indiana Pacers",
        "sport": "NBA",
        "book": "FanDuel",
        "game_time": "2026-03-13T20:00:00",
    },
    {
        "team": "Boston Celtics",
        "odds": -220,
        "sim_hit": 72.10,
        "ev": 3.25,
        "matchup": "Boston Celtics @ Miami Heat",
        "sport": "NBA",
        "book": "DraftKings",
        "game_time": "2026-03-20T19:30:00",  # outside next 24h on purpose
    },
    {
        "team": "Denver Nuggets",
        "odds": -145,
        "sim_hit": 63.40,
        "ev": 4.10,
        "matchup": "Denver Nuggets @ Lakers",
        "sport": "NBA",
        "book": "FanDuel",
        "game_time": "2026-03-13T22:00:00",
    },
    {
        "team": "Sacramento Kings",
        "odds": +120,
        "sim_hit": 49.80,
        "ev": 4.90,
        "matchup": "Kings @ Suns",
        "sport": "NBA",
        "book": "DraftKings",
        "game_time": "2026-03-13T21:30:00",
    },
    {
        "team": "Minnesota Timberwolves",
        "odds": +165,
        "sim_hit": 43.00,
        "ev": 6.75,
        "matchup": "Timberwolves @ Thunder",
        "sport": "NBA",
        "book": "FanDuel",
        "game_time": "2026-03-13T20:30:00",
    },
    {
        "team": "Cleveland Cavaliers",
        "odds": +210,
        "sim_hit": 38.10,
        "ev": 8.30,
        "matchup": "Cavaliers @ Bucks",
        "sport": "NBA",
        "book": "DraftKings",
        "game_time": "2026-03-13T19:30:00",
    },
    {
        "team": "Seattle Kraken",
        "odds": +145,
        "sim_hit": 45.20,
        "ev": 7.10,
        "matchup": "Kraken @ Canucks",
        "sport": "NHL",
        "book": "FanDuel",
        "game_time": "2026-03-13T22:30:00",
    },
    {
        "team": "Texas Rangers",
        "odds": -115,
        "sim_hit": 57.60,
        "ev": 3.40,
        "matchup": "Rangers @ Astros",
        "sport": "MLB",
        "book": "DraftKings",
        "game_time": "2026-03-13T18:45:00",
    },
]

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Parlay Forge</title>
    <style>
        * { box-sizing: border-box; }
        body {
            margin: 0;
            background: #06080d;
            color: #f3f6fb;
            font-family: Arial, sans-serif;
        }
        .wrap {
            max-width: 1480px;
            margin: 0 auto;
            padding: 34px 36px 80px;
        }
        h1 {
            margin: 0 0 18px;
            font-size: 54px;
            line-height: 1;
        }
        .sub {
            margin: 0 0 24px;
            color: #9fb0c5;
            font-size: 15px;
        }
        form {
            display: flex;
            gap: 12px;
            align-items: center;
            margin-bottom: 24px;
            flex-wrap: wrap;
        }
        select, button {
            height: 50px;
            border-radius: 10px;
            border: none;
            font-size: 18px;
        }
        select {
            min-width: 180px;
            padding: 0 14px;
        }
        button {
            background: #ff9800;
            color: #000;
            font-weight: 800;
            padding: 0 24px;
            cursor: pointer;
        }
        .checkbox-wrap {
            display: flex;
            align-items: center;
            gap: 10px;
            color: #dbe4f0;
            font-size: 15px;
            padding: 0 8px;
        }
        .checkbox-wrap input {
            transform: scale(1.15);
        }
        .status-bar {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
            margin: 0 0 26px;
        }
        .pill {
            background: #171c27;
            color: #a9bbd1;
            border: 1px solid #242c3c;
            padding: 9px 14px;
            border-radius: 999px;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: .03em;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
            gap: 18px;
        }
        .card {
            background: #151922;
            border: 1px solid #232a38;
            border-radius: 20px;
            padding: 22px 22px 20px;
            box-shadow: 0 10px 28px rgba(0,0,0,.18);
        }
        .topline {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 14px;
        }
        .mode-tag {
            display: inline-block;
            background: #232a38;
            color: #9fb0c5;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .edge-tag {
            display: inline-block;
            border-radius: 999px;
            padding: 6px 10px;
            font-size: 11px;
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
        }
        .edge-elite { background: rgba(0, 200, 120, .18); color: #72f0aa; }
        .edge-strong { background: rgba(100, 180, 255, .18); color: #85c7ff; }
        .edge-ok { background: rgba(255, 180, 0, .18); color: #ffc861; }

        .team {
            font-size: 34px;
            font-weight: 900;
            line-height: 1.05;
            margin: 0 0 8px;
        }
        .matchup {
            color: #b8c5d6;
            font-size: 16px;
            margin-bottom: 6px;
        }
        .gametime {
            color: #8fa0b5;
            font-size: 14px;
            margin-bottom: 12px;
        }
        .meta {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            margin: 14px 0 18px;
        }
        .stat {
            background: #0f131b;
            border: 1px solid #222938;
            border-radius: 14px;
            padding: 12px 14px;
        }
        .label {
            color: #8fa0b5;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .08em;
            margin-bottom: 6px;
        }
        .value {
            font-size: 22px;
            font-weight: 800;
        }
        .ev-pos { color: #6bea9f; }
        .ev-neg { color: #ff7e7e; }

        .why {
            background: #0f131b;
            border: 1px solid #222938;
            border-radius: 14px;
            padding: 14px;
        }
        .why h3 {
            margin: 0 0 10px;
            font-size: 14px;
            color: #9fb0c5;
            text-transform: uppercase;
            letter-spacing: .08em;
        }
        .why ul {
            margin: 0;
            padding-left: 18px;
            color: #dbe4f0;
            line-height: 1.6;
            font-size: 15px;
        }
        .empty {
            color: #a9bbd1;
            font-size: 18px;
            margin-top: 20px;
        }
        .hint {
            margin-top: 18px;
            color: #8898ae;
            font-size: 14px;
        }
    </style>
</head>
<body>
    <div class="wrap">
        <h1>Parlay Forge</h1>
        <p class="sub">Mode-aware picks with EV filtering, market edge, and a quick reason why each bet made the board.</p>

        <form method="GET" action="/">
            <select name="mode">
                <option value="safe" {% if mode == "safe" %}selected{% endif %}>Safe</option>
                <option value="balanced" {% if mode == "balanced" %}selected{% endif %}>Balanced</option>
                <option value="aggressive" {% if mode == "aggressive" %}selected{% endif %}>Aggressive</option>
            </select>

            <label class="checkbox-wrap">
                <input type="checkbox" name="edge_only" value="1" {% if edge_only %}checked{% endif %}>
                Edge only (EV > 0)
            </label>

            <button type="submit">Forge</button>
        </form>

        <div class="status-bar">
            <div class="pill">Mode: {{ mode|capitalize }}</div>
            <div class="pill">Edge Filter: {{ "On" if edge_only else "Off" }}</div>
            <div class="pill">Results: {{ bets|length }}</div>
        </div>

        {% if bets %}
            <div class="grid">
                {% for bet in bets %}
                    <div class="card">
                        <div class="topline">
                            <span class="mode-tag">{{ mode|capitalize }}</span>
                            <span class="edge-tag {{ bet.edge_class }}">{{ bet.edge_label }}</span>
                        </div>

                        <div class="team">{{ bet.team }}</div>
                        <div class="matchup">{{ bet.matchup }} • {{ bet.sport }} • {{ bet.book }}</div>
                        <div class="gametime">Starts: {{ bet.game_time_display }}</div>

                        <div class="meta">
                            <div class="stat">
                                <div class="label">Odds</div>
                                <div class="value">{{ bet.odds_display }}</div>
                            </div>
                            <div class="stat">
                                <div class="label">Model Hit Rate</div>
                                <div class="value">{{ "%.2f"|format(bet.sim_hit) }}%</div>
                            </div>
                            <div class="stat">
                                <div class="label">Market Implied</div>
                                <div class="value">{{ "%.2f"|format(bet.implied_prob) }}%</div>
                            </div>
                            <div class="stat">
                                <div class="label">Model Edge</div>
                                <div class="value {% if bet.edge >= 0 %}ev-pos{% else %}ev-neg{% endif %}">
                                    {{ "%+.2f"|format(bet.edge) }}%
                                </div>
                            </div>
                            <div class="stat">
                                <div class="label">EV</div>
                                <div class="value {% if bet.ev >= 0 %}ev-pos{% else %}ev-neg{% endif %}">
                                    {{ "%+.2f"|format(bet.ev) }}%
                                </div>
                            </div>
                            <div class="stat">
                                <div class="label">Confidence</div>
                                <div class="value">{{ bet.confidence }}</div>
                            </div>
                        </div>

                        <div class="why">
                            <h3>Why this bet made the board</h3>
                            <ul>
                                {% for line in bet.reasons %}
                                    <li>{{ line }}</li>
                                {% endfor %}
                            </ul>
                        </div>
                    </div>
                {% endfor %}
            </div>
        {% else %}
            <div class="empty">
                No bets matched this mode/filter combo in the next 24 hours.
            </div>
        {% endif %}

        <div class="hint">
            Safe = heavy favorites. Balanced = tighter prices. Aggressive = plus-money / bigger swings.
        </div>
    </div>
</body>
</html>
"""


def american_to_implied_prob(odds: int) -> float:
    """Convert American odds to implied probability percentage."""
    if odds < 0:
        return (abs(odds) / (abs(odds) + 100)) * 100
    return (100 / (odds + 100)) * 100


def format_american_odds(odds: int) -> str:
    return f"+{odds}" if odds > 0 else str(odds)


def confidence_label(sim_hit: float) -> str:
    if sim_hit >= 75:
        return "Very High"
    if sim_hit >= 62:
        return "High"
    if sim_hit >= 50:
        return "Moderate"
    return "Volatile"


def edge_label(edge: float) -> tuple[str, str]:
    if edge >= 7:
        return "Elite Edge", "edge-elite"
    if edge >= 4:
        return "Strong Edge", "edge-strong"
    return "Playable", "edge-ok"


def mode_filter(mode: str, odds: int) -> bool:
    """
    Safe: mostly favorites
    Balanced: modest favorites through slight dogs
    Aggressive: plus money / larger upside
    """
    if mode == "safe":
        return odds <= -180
    if mode == "balanced":
        return -179 <= odds <= 140
    if mode == "aggressive":
        return odds >= 100
    return True


def is_within_next_24h(game_time_str: str) -> bool:
    """Return True if game starts within the next 24 hours."""
    try:
        game_time = datetime.fromisoformat(game_time_str)
        now = datetime.now()
        cutoff = now + timedelta(hours=24)
        return now <= game_time <= cutoff
    except Exception:
        return False


def format_game_time(game_time_str: str) -> str:
    try:
        dt = datetime.fromisoformat(game_time_str)
        return dt.strftime("%b %d, %I:%M %p")
    except Exception:
        return game_time_str


def build_reasons(bet: Dict[str, Any]) -> List[str]:
    reasons: List[str] = []

    if bet["edge"] >= 7:
        reasons.append("Model is significantly higher than the market price.")
    elif bet["edge"] >= 4:
        reasons.append("Model shows a meaningful edge over the market.")
    else:
        reasons.append("Model has this side slightly above market.")

    if bet["ev"] > 0:
        reasons.append("Expected value is positive, so it passes the edge filter.")
    else:
        reasons.append("Expected value is negative, so this is more of a confidence play than a value play.")

    if bet["odds"] <= -180:
        reasons.append("Price profile fits a safer parlay leg or anchor.")
    elif -179 <= bet["odds"] <= 140:
        reasons.append("Price profile fits a balanced single or mid-risk parlay piece.")
    else:
        reasons.append("Price profile fits an aggressive play with higher upside.")

    return reasons


def enrich_bet(bet: Dict[str, Any]) -> Dict[str, Any]:
    implied_prob = american_to_implied_prob(bet["odds"])
    edge = bet["sim_hit"] - implied_prob
    label, css = edge_label(edge)

    enriched = dict(bet)
    enriched["implied_prob"] = implied_prob
    enriched["edge"] = edge
    enriched["edge_label"] = label
    enriched["edge_class"] = css
    enriched["odds_display"] = format_american_odds(bet["odds"])
    enriched["confidence"] = confidence_label(bet["sim_hit"])
    enriched["game_time_display"] = format_game_time(bet["game_time"])
    enriched["reasons"] = build_reasons(
        {
            **bet,
            "implied_prob": implied_prob,
            "edge": edge,
        }
    )
    return enriched


@app.route("/", methods=["GET"])
def home():
    mode = request.args.get("mode", "safe").strip().lower()
    edge_only = request.args.get("edge_only") == "1"

    valid_modes = {"safe", "balanced", "aggressive"}
    if mode not in valid_modes:
        mode = "safe"

    filtered: List[Dict[str, Any]] = []

    for bet in BETS:
        # Only games in next 24 hours
        if not is_within_next_24h(bet["game_time"]):
            continue

        # Mode filter
        if not mode_filter(mode, bet["odds"]):
            continue

        enriched = enrich_bet(bet)

        # Positive EV only if requested
        if edge_only and enriched["ev"] <= 0:
            continue

        filtered.append(enriched)

    # Best bets first
    filtered.sort(key=lambda x: (x["ev"], x["edge"]), reverse=True)

    return render_template_string(
        HTML,
        bets=filtered,
        mode=mode,
        edge_only=edge_only,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
