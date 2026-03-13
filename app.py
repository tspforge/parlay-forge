from flask import Flask, render_template_string, request
import os
import random
from datetime import datetime, timedelta, timezone
import requests
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
PORT = int(os.getenv("PORT", 10000))
SIMULATION_COUNT = int(os.getenv("SIMULATION_COUNT", "100000"))

BOOKMAKERS = ["fanduel","draftkings","betmgm","caesars"]

SPORTS = [
"basketball_nba",
"americanfootball_nfl",
"baseball_mlb",
"mma_mixed_martial_arts"
]

WINDOW_HOURS = 48
TOP_N = 5

SINGLE_THRESHOLDS = {
"safe":0.70,
"balanced":0.50,
"aggressive":0.30
}

AGGRESSIVE_MIN_PRICE = 120

app = Flask(__name__)


def american_to_decimal(a):
    if a>0:
        return 1+(a/100)
    return 1+(100/abs(a))

def decimal_to_american(d):
    if d>=2:
        return round((d-1)*100)
    return round(-100/(d-1))

def implied_prob(a):
    if a>0:
        return 100/(a+100)
    return abs(a)/(abs(a)+100)

def remove_vig(a,b):
    p1=implied_prob(a)
    p2=implied_prob(b)
    s=p1+p2
    return p1/s,p2/s

def ev(win_prob,american):
    dec=american_to_decimal(american)
    profit=dec-1
    return (win_prob*profit)-(1-win_prob)

def now():
    return datetime.now(timezone.utc)

def parse(t):
    return datetime.fromisoformat(t.replace("Z","+00:00"))

def in_window(t):
    try:
        g=parse(t)
    except:
        return False
    return now()<=g<=now()+timedelta(hours=WINDOW_HOURS)

def fetch_games(book):
    games=[]
    for sport in SPORTS:

        url=f"https://api.the-odds-api.com/v4/sports/{sport}/odds"

        params={
        "apiKey":ODDS_API_KEY,
        "regions":"us",
        "markets":"h2h",
        "oddsFormat":"american",
        "bookmakers":book
        }

        r=requests.get(url,params=params,timeout=20)
        events=r.json()

        for e in events:

            if not in_window(e.get("commence_time","")):
                continue

            if not e.get("bookmakers"):
                continue

            m=None

            for b in e["bookmakers"]:
                for x in b["markets"]:
                    if x["key"]=="h2h":
                        m=x
                        break
                if m:
                    break

            if not m:
                continue

            if len(m["outcomes"])!=2:
                continue

            a=m["outcomes"][0]
            b=m["outcomes"][1]

            p1,p2=remove_vig(a["price"],b["price"])

            games.append({
            "sport":e.get("sport_title"),
            "game":f"{e.get('away_team')} @ {e.get('home_team')}",
            "time":e.get("commence_time"),
            "book":book,
            "legs":[
            {"team":a["name"],"price":a["price"],"prob":p1},
            {"team":b["name"],"price":b["price"],"prob":p2}
            ]
            })

    return games


def simulate(p,n):
    w=0
    for _ in range(n):
        if random.random()<p:
            w+=1
    return w/n


def single_score(hit,ev_val,price,mode):

    if mode=="safe":
        return (hit*0.75)+(ev_val*0.25)

    if mode=="balanced":
        return (hit*0.50)+(ev_val*0.50)

    bonus=0
    if price>0:
        bonus=min(price/1000,0.25)

    return (ev_val*0.60)+(hit*0.20)+bonus


def find_singles(mode):

    singles=[]

    for book in BOOKMAKERS:

        games=fetch_games(book)

        for g in games:

            for leg in g["legs"]:

                prob=leg["prob"]

                hit=simulate(prob,SIMULATION_COUNT)

                if hit<SINGLE_THRESHOLDS[mode]:
                    continue

                if mode=="aggressive" and leg["price"]<AGGRESSIVE_MIN_PRICE:
                    continue

                e=ev(hit,leg["price"])

                score=single_score(hit,e,leg["price"],mode)

                singles.append({
                "team":leg["team"],
                "price":leg["price"],
                "hit":hit,
                "ev":e,
                "score":score,
                "game":g["game"],
                "sport":g["sport"],
                "book":book
                })

    singles.sort(key=lambda x:x["score"],reverse=True)

    return singles[:TOP_N]


HTML="""
<html>
<head>
<title>Parlay Forge</title>
<style>
body{background:#0b0b0e;color:white;font-family:Arial;padding:40px}
.card{background:#1a1a20;padding:20px;border-radius:14px;margin-bottom:14px}
.big{font-size:28px;font-weight:bold}
.small{color:#aaa}
button{padding:12px 20px;border-radius:10px;border:none;background:#ff7b00;color:black;font-weight:bold}
select{padding:10px}
</style>
</head>
<body>

<h1>Parlay Forge</h1>

<form method="post">

<select name="mode">
<option value="safe">Safe</option>
<option value="balanced">Balanced</option>
<option value="aggressive">Aggressive</option>
</select>

<button>Forge</button>

</form>

{% if results %}

{% for r in results %}

<div class="card">

<div class="big">{{r.team}} ({{r.price}})</div>

<div>Sim hit: {{'%0.2f'%(r.hit*100)}}%</div>
<div>EV: {{'%0.2f'%(r.ev*100)}}%</div>

<div class="small">{{r.game}}</div>
<div class="small">{{r.sport}}</div>
<div class="small">{{r.book}}</div>

</div>

{% endfor %}

{% endif %}

</body>
</html>
"""

@app.route("/",methods=["GET","POST"])
def home():

    results=None

    mode="safe"

    if request.method=="POST":
        mode=request.form.get("mode","safe")
        results=find_singles(mode)

    return render_template_string(HTML,results=results)


if __name__=="__main__":
    app.run(host="0.0.0.0",port=PORT,debug=False)
