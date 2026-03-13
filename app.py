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
        "max_odds": 260,
        "chalk_penalty": 0.045,
        "dog_penalty": 0.070,
        "volatility_weight": 0.060,
        "score_hit": 0.68,
        "score_ev": 0.16,
        "score_line": 0.08,
        "score_price": 0.08,
    },
    "balanced": {
        "label": "Balanced",
        "min_odds": 160,
        "max_odds": 420,
        "chalk_penalty": 0.040,
        "dog_penalty": 0.060,
        "volatility_weight": 0.080,
        "score_hit": 0.55,
        "score_ev": 0.20,
        "score_line": 0.12,
        "score_price": 0.13,
    },
    "aggressive": {
        "label": "Aggressive",
        "min_odds": 220,
        "max_odds": 800,
        "chalk_penalty": 0.032,
        "dog_penalty": 0.050,
        "volatility_weight": 0.100,
        "score_hit": 0.42,
        "score_ev": 0.20,
        "score_line": 0.15,
        "score_price": 0.23,
    },
}

WINDOW_HOURS = 48
TOP_N = 5
MAX_SINGLE_LEG_FAVORITE = -600
SAFE_SINGLE_MIN_HIT = 0.70

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
    if game["sport"] == "American Football" and abs(leg["price"]) < 130:
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
    if game["sport"] == "American Football":
        return 0.010
    if game["sport"] == "Baseball":
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


def simulate_single(prob, n):
    wins = 0
    for _ in range(n):
        if random.random() < prob:
            wins += 1
    return wins / n


def simulate_parlay(prob_a, prob_b, n):
    wins = 0
    for _ in range(n):
        if random.random() < prob_a and random.random() < prob_b:
            wins += 1
    return wins / n


def price_fit_score(odds, mode_key):
    mode = MODE_CONFIG[mode_key]
    min_odds = mode["min_odds"]
    max_odds = mode["max_odds"]
    midpoint = (min_odds + max_odds) / 2
    span = max(1, (max_odds - min_odds) / 2)
    return max(0.0, 1 - abs(odds - midpoint) / span)


def parlay_rating_label(ev, edge):
    if ev >= 0.03 and edge >= 0.02:
        return "Playable"
    if ev >= 0.0:
        return "Thin Edge"
    if ev >= -0.04:
        return "Best Available"
    if ev >= -0.10:
        return "Risky"
    return "Bad Price"


def single_rating_label(hit, ev):
    if hit >= 0.80 and ev >= 0:
        return "Hammer Safe"
    if hit >= 0.75:
        return "Very Safe"
    if hit >= 0.70:
        return "Safe"
    return "Not Safe"


def find_safe_singles(mode_key):
    singles = []
    market_counts = []

    for book in BOOKMAKERS:
        games = fetch_games(book)
        local_count = 0

        for game in games:
            for leg in game["legs"]:
                if leg["price"] < MAX_SINGLE_LEG_FAVORITE:
                    continue

                adj_prob = adjust_probability(game, leg, mode_key)
                sim_hit = simulate_single(adj_prob, SIMULATION_COUNT)

                if sim_hit < SAFE_SINGLE_MIN_HIT:
                    continue

                break_even = break_even_prob(leg["price"])
                edge = sim_hit - break_even
                ev = ev_per_dollar(sim_hit, leg["price"])

                score = (sim_hit * 0.72) + (ev * 0.20) + (edge * 0.08)

                local_count += 1
                singles.append(
                    {
                        "book": game["book"],
                        "team": leg["team"],
                        "price": leg["price"],
                        "price_display": format_american(leg["price"]),
                        "hit": sim_hit,
                        "ev": ev,
                        "edge": edge,
                        "score": score,
                        "rating": single_rating_label(sim_hit, ev),
                        "sport": game["sport"],
                        "game": game["game"],
                        "time": game["display_time"],
                        "raw_prob": leg["prob"],
                        "adj_prob": adj_prob,
                    }
                )

        market_counts.append(
            {
                "book": BOOKMAKERS[book],
                "games": len(games),
                "candidates": local_count,
            }
        )

    singles.sort(key=lambda x: (x["score"], x["hit"], x["ev"], x["edge"]), reverse=True)
    return singles[:TOP_N], market_counts


def find_parlays(mode_key):
    mode = MODE_CONFIG[mode_key]
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
                    sim_hit = simulate_parlay(p1, p2, SIMULATION_COUNT)
                    baseline_hit = p1 * p2
                    break_even = break_even_prob(odds)
                    edge = sim_hit - break_even
                    ev = ev_per_dollar(sim_hit, odds)
                    line_value = ((l1["prob"] - p1) + (l2["prob"] - p2)) * -1
                    price_score = price_fit_score(odds, mode_key)

                    score = (
                        sim_hit * mode["score_hit"]
                        + ev * mode["score_ev"]
                        + line_value * mode["score_line"]
                        + price_score * mode["score_price"]
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
                            "rating": parlay_rating_label(ev, edge),
                        }
                    )

        market_counts.append(
            {
                "book": BOOKMAKERS[book],
                "games": len(games),
                "candidates": local_count,
            }
        )

    candidates.sort(key=lambda x: (x["score"], x["hit"], x["ev"], x["edge"]), reverse=True)
    return candidates[:TOP_N], market_counts


HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Parlay Forge V8</title>
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
      max-width: 920px;
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
    .rating {
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
      <div class="eyebrow">Forge Mode // V8</div>
      <h1>Parlay Forge</h1>
      <p class="sub">Safe Singles only returns bets with at least 70% simulated hit rate. Parlay Scanner keeps the ranked 2-leg parlay view. This is much closer to what you meant by safe.</p>
      <form method="post" class="controls">
        <select name="bet_type">
          <option value="singles" {% if bet_type == 'singles' %}selected{% endif %}>Safe Singles</option>
          <option value="parlays" {% if bet_type == 'parlays' %}selected{% endif %}>Parlay Scanner</option>
        </select>
        <select name="mode">
          <option value="safe" {% if mode == 'safe' %}selected{% endif %}>Safe</option>
          <option value="balanced" {% if mode == 'balanced' %}selected{% endif %}>Balanced</option>
          <option value="aggressive" {% if mode == 'aggressive' %}selected{% endif %}>Aggressive</option>
        </select>
        <button type="submit">Forge V8</button>
      </form>
      {% if results is not none %}
        <div class="meta">Bet type: {{ bet_type_label }} · Mode: {{ mode_label }} · Window: {{ window_hours }} hours · Simulations: {{ sim_count }} · Top shown: {{ top_n }}</div>
      {% endif %}
    </div>

    {% if results %}
      <div class="grid">
        {% for item in results %}
          <div class="card">
            <div class="rankrow">
              <div class="rank">Rank {{ loop.index }}</div>
              <div class="rating">{{ item.rating }}</div>
            </div>

            {% if bet_type == 'singles' %}
              <div class="odds">{{ item.price_display }}</div>
              <div>
                <span class="metric">Book: {{ item.book }}</span>
                <span class="metric">Sim hit: {{ '%.2f'|format(item.hit*100) }}%</span>
                <span class="metric">EV: {{ '%.2f'|format(item.ev*100) }}%</span>
                <span class="metric">Edge: {{ '%.2f'|format(item.edge*100) }}%</span>
              </div>

              <div class="leg">
                <div class="team">{{ item.team }} ({{ item.price_display }})</div>
                <div class="small">{{ item.game }}</div>
                <div class="small">{{ item.sport }} · {{ item.time }}</div>
                <div class="small">Adj win rate: {{ '%.2f'|format(item.adj_prob*100) }}% · Raw: {{ '%.2f'|format(item.raw_prob*100) }}%</div>
              </div>
            {% else %}
              <div class="odds">{{ item.odds_display }}</div>
              <div>
                <span class="metric">Book: {{ item.book }}</span>
                <span class="metric">Sim hit: {{ '%.2f'|format(item.hit*100) }}%</span>
                <span class="metric">EV: {{ '%.2f'|format(item.ev*100) }}%</span>
                <span class="metric">Edge: {{ '%.2f'|format(item.edge*100) }}%</span>
              </div>

              <div class="leg">
                <div class="team">{{ item.leg1.team }} ({{ item.leg1.price_display }})</div>
                <div class="small">{{ item.leg1.game }}</div>
                <div class="small">{{ item.leg1.sport }} · {{ item.leg1.time }}</div>
                <div class="small">Adj win rate: {{ '%.2f'|format(item.leg1.prob*100) }}% · Raw: {{ '%.2f'|format(item.leg1.raw_prob*100) }}%</div>
              </div>

              <div class="leg">
                <div class="team">{{ item.leg2.team }} ({{ item.leg2.price_display }})</div>
                <div class="small">{{ item.leg2.game }}</div>
                <div class="small">{{ item.leg2.sport }} · {{ item.leg2.time }}</div>
                <div class="small">Adj win rate: {{ '%.2f'|format(item.leg2.prob*100) }}% · Raw: {{ '%.2f'|format(item.leg2.raw_prob*100) }}%</div>
              </div>
            {% endif %}
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
              <div class="small">Candidates built: {{ item.candidates }}</div>
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
    mode = request.form.get("mode", "safe") if request.method == "POST" else "safe"
    bet_type = request.form.get("bet_type", "singles") if request.method == "POST" else "singles"

    if mode not in MODE_CONFIG:
        mode = "safe"
    if bet_type not in {"singles", "parlays"}:
        bet_type = "singles"

    if request.method == "POST":
        if bet_type == "singles":
            results, market_counts = find_safe_singles(mode)
        else:
            results, market_counts = find_parlays(mode)

    return render_template_string(
        HTML,
        results=results,
        market_counts=market_counts,
        mode=mode,
        bet_type=bet_type,
        mode_label=MODE_CONFIG[mode]["label"],
        bet_type_label="Safe Singles" if bet_type == "singles" else "Parlay Scanner",
        sim_count=f"{SIMULATION_COUNT:,}",
        top_n=TOP_N,
        window_hours=WINDOW_HOURS,
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
