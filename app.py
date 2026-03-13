from flask import Flask, request, jsonify, render_template_string
import json
import os
import random

app = Flask(__name__)

# --------------------------------------------------
# Load fighter database
# --------------------------------------------------
DB_FILE = "fighters.json"

if os.path.exists(DB_FILE):
    with open(DB_FILE, "r", encoding="utf-8") as f:
        fighter_list = json.load(f)
else:
    fighter_list = []

fighters = {}
for fighter in fighter_list:
    name = fighter.get("name")
    if name:
        fighters[name] = fighter

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def clamp(value, low, high):
    return max(low, min(high, value))


def get_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def normalize_fighter_stats(f):
    """
    Convert scraped stats into model-friendly values.
    """
    slpm = get_float(f.get("slpm"), 2.5)
    sapm = get_float(f.get("sapm"), 2.5)
    str_acc = get_float(f.get("str_acc"), 45.0)
    str_def = get_float(f.get("str_def"), 50.0)
    td_avg = get_float(f.get("td_avg"), 0.5)
    td_acc = get_float(f.get("td_acc"), 35.0)
    td_def = get_float(f.get("td_def"), 55.0)
    sub_avg = get_float(f.get("sub_avg"), 0.2)

    total_fights = int(get_float(f.get("total_fights"), 1))
    wins = int(get_float(f.get("wins"), 0))

    ko_rate = get_float(f.get("ko_rate"), 0.20)
    sub_rate = get_float(f.get("sub_rate"), 0.10)
    decision_rate = get_float(f.get("decision_rate"), 0.70)
    finish_rate = get_float(f.get("finish_rate"), ko_rate + sub_rate)

    # Basic quality / experience factor
    win_rate = wins / total_fights if total_fights > 0 else 0.5
    experience_factor = clamp(total_fights / 20.0, 0.4, 1.2)

    return {
        "name": f.get("name", "Unknown"),
        "slpm": slpm,
        "sapm": sapm,
        "str_acc": str_acc,
        "str_def": str_def,
        "td_avg": td_avg,
        "td_acc": td_acc,
        "td_def": td_def,
        "sub_avg": sub_avg,
        "ko_rate": ko_rate,
        "sub_rate": sub_rate,
        "decision_rate": decision_rate,
        "finish_rate": finish_rate,
        "win_rate": win_rate,
        "experience_factor": experience_factor,
        "total_fights": total_fights,
        "wins": wins,
        "losses": int(get_float(f.get("losses"), 0)),
        "draws": int(get_float(f.get("draws"), 0)),
    }


def build_matchup_probabilities(a_raw, b_raw, rounds):
    """
    Derive win/method probabilities from real stats.
    This is still a simplified model, but much better than hardcoded values.
    """
    a = normalize_fighter_stats(a_raw)
    b = normalize_fighter_stats(b_raw)

    # Striking advantage
    a_strike_score = (
        (a["slpm"] * (a["str_acc"] / 100.0))
        - (b["sapm"] * (b["str_def"] / 100.0))
    )
    b_strike_score = (
        (b["slpm"] * (b["str_acc"] / 100.0))
        - (a["sapm"] * (a["str_def"] / 100.0))
    )

    # Grappling advantage
    a_grapple_score = (a["td_avg"] * (a["td_acc"] / 100.0)) - (b["td_def"] / 100.0)
    b_grapple_score = (b["td_avg"] * (b["td_acc"] / 100.0)) - (a["td_def"] / 100.0)

    # Base total strength
    a_total = (
        a_strike_score * 1.2
        + a_grapple_score * 0.9
        + a["win_rate"] * 1.0
        + a["experience_factor"] * 0.5
    )

    b_total = (
        b_strike_score * 1.2
        + b_grapple_score * 0.9
        + b["win_rate"] * 1.0
        + b["experience_factor"] * 0.5
    )

    # Convert to relative win probabilities
    raw_a = max(0.05, a_total + 2.5)
    raw_b = max(0.05, b_total + 2.5)
    total = raw_a + raw_b

    a_win_prob = raw_a / total
    b_win_prob = raw_b / total

    # 5 rounds = slightly more finish opportunities and also more decision exposure for better fighters
    if rounds == 5:
        a_finish_bias = 1.08
        b_finish_bias = 1.08
        a_decision_bias = 1.05
        b_decision_bias = 1.05
    else:
        a_finish_bias = 1.00
        b_finish_bias = 1.00
        a_decision_bias = 1.00
        b_decision_bias = 1.00

    # Method mix inside each fighter's win condition
    a_ko_weight = max(0.01, a["ko_rate"] * (1 + max(0, a_strike_score) * 0.10)) * a_finish_bias
    a_sub_weight = max(0.01, a["sub_rate"] * (1 + max(0, a_grapple_score) * 0.15)) * a_finish_bias
    a_dec_weight = max(0.01, a["decision_rate"]) * a_decision_bias

    b_ko_weight = max(0.01, b["ko_rate"] * (1 + max(0, b_strike_score) * 0.10)) * b_finish_bias
    b_sub_weight = max(0.01, b["sub_rate"] * (1 + max(0, b_grapple_score) * 0.15)) * b_finish_bias
    b_dec_weight = max(0.01, b["decision_rate"]) * b_decision_bias

    a_method_total = a_ko_weight + a_sub_weight + a_dec_weight
    b_method_total = b_ko_weight + b_sub_weight + b_dec_weight

    probs = {
        f'{a["name"]} KO/TKO': a_win_prob * (a_ko_weight / a_method_total),
        f'{a["name"]} Submission': a_win_prob * (a_sub_weight / a_method_total),
        f'{a["name"]} Decision': a_win_prob * (a_dec_weight / a_method_total),
        f'{b["name"]} KO/TKO': b_win_prob * (b_ko_weight / b_method_total),
        f'{b["name"]} Submission': b_win_prob * (b_sub_weight / b_method_total),
        f'{b["name"]} Decision': b_win_prob * (b_dec_weight / b_method_total),
    }

    return probs


def simulate_fight(fighter_a, fighter_b, rounds):
    probs = build_matchup_probabilities(fighters[fighter_a], fighters[fighter_b], rounds)
    outcomes = list(probs.keys())
    weights = list(probs.values())
    return random.choices(outcomes, weights=weights, k=1)[0]


def monte_carlo(fighter_a, fighter_b, rounds, runs):
    method_counts = {
        f"{fighter_a} KO/TKO": 0,
        f"{fighter_a} Submission": 0,
        f"{fighter_a} Decision": 0,
        f"{fighter_b} KO/TKO": 0,
        f"{fighter_b} Submission": 0,
        f"{fighter_b} Decision": 0,
    }

    for _ in range(runs):
        outcome = simulate_fight(fighter_a, fighter_b, rounds)
        method_counts[outcome] += 1

    method_percentages = {
        outcome: round((count / runs) * 100, 2)
        for outcome, count in method_counts.items()
    }

    fighter_a_win_pct = round(
        method_percentages[f"{fighter_a} KO/TKO"]
        + method_percentages[f"{fighter_a} Submission"]
        + method_percentages[f"{fighter_a} Decision"],
        2
    )

    fighter_b_win_pct = round(
        method_percentages[f"{fighter_b} KO/TKO"]
        + method_percentages[f"{fighter_b} Submission"]
        + method_percentages[f"{fighter_b} Decision"],
        2
    )

    ranked_methods = dict(
        sorted(method_percentages.items(), key=lambda x: x[1], reverse=True)
    )

    return {
        "fight": f"{fighter_a} vs {fighter_b}",
        "rounds": rounds,
        "simulations": runs,
        "win_percentages": {
            fighter_a: fighter_a_win_pct,
            fighter_b: fighter_b_win_pct
        },
        "method_breakdown": ranked_methods
    }


# --------------------------------------------------
# UI
# --------------------------------------------------
HOME_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>UFC Sim</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body {
            font-family: Arial, sans-serif;
            background: #0b0d12;
            color: white;
            margin: 0;
            padding: 40px 20px;
        }
        .wrap {
            max-width: 900px;
            margin: 0 auto;
        }
        h1 {
            margin-top: 0;
            font-size: 48px;
        }
        p {
            color: #b9c0cc;
        }
        form {
            background: #161a22;
            padding: 24px;
            border-radius: 16px;
            margin-top: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: bold;
        }
        select, input, button {
            width: 100%;
            padding: 14px;
            margin-bottom: 18px;
            border-radius: 10px;
            border: none;
            font-size: 16px;
        }
        button {
            background: #ff9800;
            color: black;
            font-weight: bold;
            cursor: pointer;
        }
        .links {
            margin-top: 30px;
        }
        a {
            color: #7db7ff;
        }
    </style>
</head>
<body>
    <div class="wrap">
        <h1>UFC Fight Simulator</h1>
        <p>Real fighter database loaded from fighters.json</p>
        <p>Fighters in database: <strong>{{ fighter_count }}</strong></p>

        <form action="/simulate" method="get">
            <label for="fighter_a">Fighter A</label>
            <select name="fighter_a" id="fighter_a">
                {% for fighter in fighter_names %}
                <option value="{{ fighter }}">{{ fighter }}</option>
                {% endfor %}
            </select>

            <label for="fighter_b">Fighter B</label>
            <select name="fighter_b" id="fighter_b">
                {% for fighter in fighter_names %}
                <option value="{{ fighter }}">{{ fighter }}</option>
                {% endfor %}
            </select>

            <label for="rounds">Rounds</label>
            <select name="rounds" id="rounds">
                <option value="3">3 Rounds</option>
                <option value="5">5 Rounds</option>
            </select>

            <label for="runs">Simulations</label>
            <input type="number" name="runs" id="runs" value="100000" min="1000" step="1000">

            <button type="submit">Run Simulation</button>
        </form>

        <div class="links">
            <p>Quick test:</p>
            <a href="/simulate?fighter_a=Max Holloway&fighter_b=Charles Oliveira&rounds=5&runs=100000">Max Holloway vs Charles Oliveira</a>
        </div>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    fighter_names = sorted(fighters.keys())
    return render_template_string(
        HOME_HTML,
        fighter_names=fighter_names,
        fighter_count=len(fighter_names),
    )


@app.route("/simulate")
def simulate():
    fighter_a = request.args.get("fighter_a")
    fighter_b = request.args.get("fighter_b")
    rounds = int(request.args.get("rounds", 3))
    runs = int(request.args.get("runs", 100000))

    if fighter_a not in fighters or fighter_b not in fighters:
        return jsonify({
            "error": "fighter not found",
            "available_fighters_sample": sorted(list(fighters.keys()))[:25]
        }), 400

    if fighter_a == fighter_b:
        return jsonify({
            "error": "fighter_a and fighter_b must be different"
        }), 400

    if rounds not in [3, 5]:
        return jsonify({
            "error": "rounds must be 3 or 5"
        }), 400

    if runs <= 0:
        return jsonify({
            "error": "runs must be greater than 0"
        }), 400

    results = monte_carlo(fighter_a, fighter_b, rounds, runs)
    return jsonify(results)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
