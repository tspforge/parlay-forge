from flask import Flask, render_template_string, request
import os
import random
from datetime import datetime, timedelta, timezone
from itertools import combinations
import requests
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
PORT = int(os.getenv("PORT", 5000))
SIMULATION_COUNT = int(os.getenv("SIMULATION_COUNT", "100000"))
REQUEST_TIMEOUT = 20

BOOKMAKERS = {
    "fanduel": "FanDuel",
    "draftkings": "DraftKings",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
}

SPORT_KEYS = [
    "basketball_nba",
    "americanfootball_nfl",
    "baseball_mlb",
    "mma_mixed_martial_arts",
]

MODE_CONFIG = {
    "safe": {
        "label": "Safe",
        "min_odds": 120,
        "max_odds": 220,
        "chalk_penalty": 0.05,
        "dog_penalty": 0.07,
        "volatility_weight": 0.06,
        "score_hit": 0.70,
        "score_ev": 0.22,
        "score_line": 0.08,
    },
    "balanced": {
        "label": "Balanced",
        "min_odds": 180,
        "max_odds": 350,
        "chalk_penalty": 0.04,
        "dog_penalty": 0.06,
        "volatility_weight": 0.08,
        "score_hit": 0.58,
        "score_ev": 0.28,
        "score_line": 0.14,
    },
    "aggressive": {
        "label": "Aggressive",
        "min_odds": 300,
        "max_odds": 650,
        "chalk_penalty": 0.03,
        "dog_penalty": 0.05,
        "volatility_weight": 0.10,
        "score_hit": 0.48,
        "score_ev": 0.32,
        "score_line": 0.20,
    },
}

ENGINE_CONFIG = {
    "strict": {
        "label": "Strict",
        "min_ev": 0.0,
        "description": "Only positive-EV parlays. No forcing action.",
    },
    "action": {
        "label": "Action",
        "min_ev": -0.05,
        "description": "Best available parlays, even if slightly negative EV.",
    },
}

WINDOW_HOURS = 24
TOP_N = 5
MAX_SINGLE_LEG_FAVORITE = -350
app = Flask(__name__)


def american_to_decimal(american):
    if american > 0:
        return 1 + (american / 100)
    return 1 + (100 / abs(american))


def decimal_to_american(decimal_odds):
    if decimal_odds >= 2:
        return round((decimal_odds - 1) * 100)
    return round(-100 / (decimal_odds - 1))


def american_to_implied_prob(american):
    if american > 0:
        return 100 / (american + 100)
    return abs(american) / (abs(american) + 100)


def remove_vig(price_a, price_b):
    p1 = american_to_implied_prob(price_a)
    p2 = american_to_implied_prob(price_b)
    total = p1 + p2
    if total == 0:
        return 0.5, 0.5
    return p1 / total, p2 / total


def parlay_price(a, b):
    return decimal_to_american(american_to_decimal(a) * american_to_decimal(b))


def break_even_prob(american):
    return 1 / american_to_decimal(american)


def ev_per_dollar(win_prob, american):
    decimal = american_to_decimal(american)
    profit_if_win = decimal - 1
    return (win_prob * profit_if_win) - (1 - win_prob)


def format_american(american):
    return f"+{american}" if american > 0 else str(american)


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_time(value):
    try:
        return parse_time(value).strftime("%b %d, %Y %I:%M %p UTC")
    except Exception:
        return value


def within_window(commence):
    try:
        t = parse_time(commence)
    except Exception:
        return False
    now = utc_now()
    return now <= t <= now + timedelta(hours=WINDOW_HOURS)


def odds_api_get(url, params):
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json(), r.headers


def fetch_games(book):
    games = []

    for sport in SPORT_KEYS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "us",
            "markets": "h2h",
            "oddsFormat": "american",
            "bookmakers": book,
        }

        events, _headers = odds_api_get(url, params)

        for event in events:
            commence = event.get("commence_time", "")
            if not within_window(commence):
                continue

            bookmakers = event.get("bookmakers", [])
            if not bookmakers:
                continue

            market = None
            for bookmaker in bookmakers:
                for m in bookmaker.get("markets", []):
                    if m.get("key") == "h2h":
                        market = m
                        break
                if market:
                    break

            if not market:
                continue

            outcomes = market.get("outcomes", [])
            if len(outcomes) != 2:
                continue

            a = outcomes[0]
            b = outcomes[1]
            p1, p2 = remove_vig(a["price"], b["price"])

            games.append(
                {
                    "event_id": event["id"],
                    "sport": event.get("sport_title", sport),
                    "game": f"{event.get('away_team')} @ {event.get('home_team')}",
                    "time": commence,
                    "display_time": format_time(commence),
                    "home_team": event.get("home_team"),
                    "away_team": event.get("away_team"),
                    "book": BOOKMAKERS[book],
                    "legs": [
                        {"team": a["name"], "price": a["price"], "prob": p1},
                        {"team": b["name"], "price": b["price"], "prob": p2},
                    ],
                }
            )

    return games


def sport_volatility(sport):
    if sport == "Mixed Martial Arts":
        return 0.11
    if sport == "Baseball":
        return 0.08
    if sport == "American Football":
        return 0.06
    if sport == "Basketball":
        return 0.05
    return 0.07


def infer_injury_risk(game, leg):
    risk = 0.0
    if game["sport"] == "American Football":
        if abs(leg["price"]) < 130:
            risk += 0.006
    elif game["sport"] == "Baseball":
        risk += 0.008
    elif game["sport"] == "Mixed Martial Arts":
        risk += 0.010
    return risk


def infer_public_side_penalty(leg):
    price = leg["price"]
    if price <= -220:
        return 0.018
    if price <= -160:
        return 0.010
    return 0.0


def infer_qb_or_pitcher_penalty(game):
    sport = game["sport"]
    if sport == "American Football":
        return 0.010
    if sport == "Baseball":
        return 0.015
    return 0.0


def adjust_probability(game, leg, mode_key):
    mode = MODE_CONFIG[mode_key]
    prob = leg["prob"]
    price = leg["price"]

    if price < -300:
        prob -= mode["chalk_penalty"]
    elif price < -220:
        prob -= mode["chalk_penalty"] * 0.6

    if price > 200:
        prob -= mode["dog_penalty"]
    elif price > 140:
        prob -= mode["dog_penalty"] * 0.55

    prob -= sport_volatility(game["sport"]) * mode["volatility_weight"]
    prob -= infer_injury_risk(game, leg)
    prob -= infer_public_side_penalty(leg)
    prob -= infer_qb_or_pitcher_penalty(game)

    return max(0.01, min(0.99, prob))


def simulate(prob_a, prob_b, n):
    wins = 0
    for _ in range(n):
        if random.random() < prob_a and random.random() < prob_b:
            wins += 1
    return wins / n


def parlay_confidence(rank_idx, mode_key):
    names = {
        "safe": ["Iron Lock", "Strong", "Steady", "Measured", "Thin Edge"],
        "balanced": ["Prime", "Strong", "Balanced", "Press", "Thin Edge"],
        "aggressive": ["Heat Check", "Live Dog", "Swing", "Spicy", "Longshot"],
    }
    return names[mode_key][rank_idx]


def find_parlays(mode_key, engine_key):
    mode = MODE_CONFIG[mode_key]
    engine = ENGINE_CONFIG[engine_key]
    candidates = []
    market_counts = []

    for book in BOOKMAKERS:
        games = fetch_games(book)
        local_count = 0

        for g1, g2 in combinations(games, 2):
            for l1 in g1["legs"]:
                for l2 in g2["legs"]:
                    odds = parlay_price(l1["price"], l2["price"])

                    if not (mode["min_odds"] <= odds <= mode["max_odds"]):
                        continue

                    if l1["price"] < MAX_SINGLE_LEG_FAVORITE or l2["price"] < MAX_SINGLE_LEG_FAVORITE:
                        continue

                    p1 = adjust_probability(g1, l1, mode_key)
                    p2 = adjust_probability(g2, l2, mode_key)
                    sim_hit = simulate(p1, p2, SIMULATION_COUNT)
                    baseline_hit = p1 * p2
                    break_even = break_even_prob(odds)
                    edge = sim_hit - break_even
                    ev = ev_per_dollar(sim_hit, odds)
                    line_value = ((l1["prob"] - p1) + (l2["prob"] - p2)) * -1

                    if ev < engine["min_ev"]:
                        continue

                    score = (
                        sim_hit * mode["score_hit"]
                        + ev * mode["score_ev"]
                        + line_value * mode["score_line"]
                    )

                    local_count += 1
                    candidates.append(
                        {
                            "book": BOOKMAKERS[book],
                            "leg1": {
                                "team": l1["team"],
                                "price": l1["price"],
                                "price_display": format_american(l1["price"]),
                                "prob": p1,
                                "raw_prob": l1["prob"],
                                "sport": g1["sport"],
                                "game": g1["game"],
                                "time": g1["display_time"],
                            },
                            "leg2": {
                                "team": l2["team"],
                                "price": l2["price"],
                                "price_display": format_american(l2["price"]),
                                "prob": p2,
                                "raw_prob": l2["prob"],
                                "sport": g2["sport"],
                                "game": g2["game"],
                                "time": g2["display_time"],
                            },
                            "odds": odds,
                            "odds_display": format_american(odds),
                            "hit": sim_hit,
                            "baseline_hit": baseline_hit,
                            "break_even": break_even,
                            "edge": edge,
                            "ev": ev,
                            "line_value": line_value,
                            "score": score,
                        }
                    )

        market_counts.append(
            {
                "book": BOOKMAKERS[book],
                "games": len(games),
                "candidates": local_count,
            }
        )

    candidates.sort(key=lambda x: (x["score"], x["ev"], x["hit"], x["edge"]), reverse=True)

    top = candidates[:TOP_N]
    for idx, item in enumerate(top):
        item["confidence"] = parlay_confidence(idx, mode_key)

    return top, market_counts


HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Parlay Forge V6</title>
  <style>
    :root {
      --bg: #08080b;
      --panel: rgba(18,18,24,.94);
      --panel2: rgba(25,25,33,.96);
      --line: rgba(255,255,255,.08);
      --text: #f4f4f6;
      --muted: #a6a6b0;
      --orange: #ff6a00;
      --gold: #ffbc6b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: Arial, Helvetica, sans-serif;
      background:
        radial-gradient(circle at top, rgba(255,106,0,.14), transparent 28%),
        linear-gradient(180deg, #0a0a0d, #07070a 55%, #040406);
    }
    .wrap { max-width: 1220px; margin: 0 auto; padding: 28px 18px 56px; }
    .hero {
      position: relative;
      overflow: hidden;
      border-radius: 28px;
      border: 1px solid var(--line);
      padding: 28px;
      background:
        linear-gradient(180deg, rgba(255,106,0,.10), rgba(255,106,0,.025)),
        linear-gradient(180deg, rgba(255,255,255,.02), rgba(255,255,255,.01));
      box-shadow: 0 0 0 1px rgba(255,106,0,.05), 0 24px 80px rgba(0,0,0,.36);
    }
    .eyebrow {
      color: var(--gold);
      letter-spacing: .18em;
      text-transform: uppercase;
      font-size: 12px;
      font-weight: 700;
      margin-bottom: 10px;
    }
    h1 { margin: 0; font-size: 46px; line-height: 1; }
    .sub {
      margin: 12px 0 22px;
      max-width: 900px;
      color: var(--muted);
      line-height: 1.45;
    }
    .controls { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
    select, button {
      border-radius: 16px;
      padding: 14px 16px;
      font-size: 15px;
      border: 1px solid var(--line);
    }
    select {
      background: #0f0f15;
      color: var(--text);
      min-width: 170px;
    }
    button {
      border: 0;
      font-weight: 800;
      color: #170900;
      cursor: pointer;
      background: linear-gradient(180deg, var(--gold), var(--orange));
      box-shadow: 0 14px 30px rgba(255,106,0,.18);
    }
    .meta {
      margin-top: 16px;
      color: var(--muted);
      font-size: 14px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
      gap: 18px;
      margin-top: 22px;
    }
    .card {
      position: relative;
      overflow: hidden;
      border-radius: 24px;
      border: 1px solid var(--line);
      padding: 20px;
      background: linear-gradient(180deg, var(--panel), var(--panel2));
    }
    .rankrow {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }
    .rank {
      color: var(--gold);
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: .16em;
      font-weight: 700;
    }
    .confidence {
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: rgba(255,106,0,.12);
      border: 1px solid rgba(255,106,0,.22);
      color: #ffd7b6;
      font-weight: 700;
    }
    .odds {
      font-size: 32px;
      font-weight: 900;
      margin: 6px 0 12px;
    }
    .metric {
      display: inline-block;
      margin: 0 8px 8px 0;
      padding: 7px 10px;
      border-radius: 999px;
      font-size: 12px;
      background: rgba(255,255,255,.03);
      border: 1px solid var(--line);
      color: #e0e0e4;
    }
    .leg {
      border-top: 1px solid var(--line);
      padding-top: 14px;
      margin-top: 14px;
    }
    .team { font-size: 20px; font-weight: 800; margin-bottom: 4px; }
    .small { color: var(--muted); font-size: 14px; line-height: 1.45; }
    .error {
      margin-top: 20px;
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(255,90,90,.25);
      background: rgba(160,30,30,.12);
      color: #ffb9b9;
    }
    .summary {
      margin-top: 24px;
      border-radius: 20px;
      border: 1px solid var(--line);
      background: rgba(255,255,255,.02);
      padding: 18px;
    }
    .summarygrid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .summaryitem {
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 12px;
      background: rgba(255,255,255,.02);
    }
    .summaryitem strong { display: block; margin-bottom: 4px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="eyebrow">Forge Mode // V6</div>
      <h1>Parlay Forge</h1>
      <p class="sub">Scans NBA, NFL, MLB, and UFC/MMA games in the next 24 hours. Checks FanDuel, DraftKings, BetMGM, and Caesars. Strict mode only shows positive-EV parlays. Action mode shows the best available top 5 even if they are slightly negative EV.</p>
      <form method="post" class="controls">
        <select name="mode">
          <option value="safe" {% if mode == 'safe' %}selected{% endif %}>Safe</option>
          <option value="balanced" {% if mode == 'balanced' %}selected{% endif %}>Balanced</option>
          <option value="aggressive" {% if mode == 'aggressive' %}selected{% endif %}>Aggressive</option>
        </select>
        <select name="engine">
          <option value="strict" {% if engine == 'strict' %}selected{% endif %}>Strict</option>
          <option value="action" {% if engine == 'action' %}selected{% endif %}>Action</option>
        </select>
        <button type="submit">Forge V6 Parlays</button>
      </form>
      {% if results is not none %}
        <div class="meta">Mode: {{ mode_label }} · Engine: {{ engine_label }} · {{ engine_description }} · Simulations per candidate: {{ sim_count }} · Top results shown: {{ top_n }}</div>
      {% endif %}
    </div>

    {% if error %}
      <div class="error">{{ error }}</div>
    {% endif %}

    {% if results %}
      <div class="grid">
        {% for p in results %}
          <div class="card">
            <div class="rankrow">
              <div class="rank">Rank {{ loop.index }}</div>
              <div class="confidence">{{ p.confidence }}</div>
            </div>
            <div class="odds">{{ p.odds_display }}</div>
            <div>
              <span class="metric">Book: {{ p.book }}</span>
              <span class="metric">Sim hit: {{ '%.2f'|format(p.hit*100) }}%</span>
              <span class="metric">EV: {{ '%.2f'|format(p.ev*100) }}%</span>
              <span class="metric">Edge: {{ '%.2f'|format(p.edge*100) }}%</span>
            </div>

            <div class="leg">
              <div class="team">{{ p.leg1.team }} ({{ p.leg1.price_display }})</div>
              <div class="small">{{ p.leg1.game }}</div>
              <div class="small">{{ p.leg1.sport }} · {{ p.leg1.time }}</div>
              <div class="small">Adj win rate: {{ '%.2f'|format(p.leg1.prob*100) }}% · Raw: {{ '%.2f'|format(p.leg1.raw_prob*100) }}%</div>
            </div>

            <div class="leg">
              <div class="team">{{ p.leg2.team }} ({{ p.leg2.price_display }})</div>
              <div class="small">{{ p.leg2.game }}</div>
              <div class="small">{{ p.leg2.sport }} · {{ p.leg2.time }}</div>
              <div class="small">Adj win rate: {{ '%.2f'|format(p.leg2.prob*100) }}% · Raw: {{ '%.2f'|format(p.leg2.raw_prob*100) }}%</div>
            </div>
          </div>
        {% endfor %}
      </div>
    {% endif %}

    {% if market_counts %}
      <div class="summary">
        <strong>Sportsbook scan summary</strong>
        <div class="summarygrid">
          {% for item in market_counts %}
            <div class="summaryitem">
              <strong>{{ item.book }}</strong>
              <div class="small">Games found: {{ item.games }}</div>
              <div class="small">Candidates shown: {{ item.candidates }}</div>
            </div>
          {% endfor %}
        </div>
      </div>
    {% endif %}
  </div>
</body>
</html>
"""


@app.route("/", methods=["GET", "POST"])
def home():
    results = None
    market_counts = None
    error = None
    mode = request.form.get("mode", "balanced") if request.method == "POST" else "balanced"
    engine = request.form.get("engine", "strict") if request.method == "POST" else "strict"

    if mode not in MODE_CONFIG:
        mode = "balanced"
    if engine not in ENGINE_CONFIG:
        engine = "strict"

    if request.method == "POST":
        try:
            results, market_counts = find_parlays(mode, engine)
            if not results:
                if engine == "strict":
                    error = "No positive EV parlays found in the next 24 hours. No bet today."
                else:
                    error = "No parlays found in the next 24 hours for this mode."
        except Exception as e:
            error = str(e)
            results = []
            market_counts = []

    return render_template_string(
        HTML,
        results=results,
        market_counts=market_counts,
        error=error,
        mode=mode,
        engine=engine,
        mode_label=MODE_CONFIG[mode]["label"],
        engine_label=ENGINE_CONFIG[engine]["label"],
        engine_description=ENGINE_CONFIG[engine]["description"],
        sim_count=f"{SIMULATION_COUNT:,}",
        top_n=TOP_N,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
