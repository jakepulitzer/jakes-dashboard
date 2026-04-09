import streamlit as st
import streamlit.components.v1 as components
import requests
import xml.etree.ElementTree as ET
import os
import pytz
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

SCHWAB_APP_KEY = os.getenv("SCHWAB_APP_KEY")
SCHWAB_APP_SECRET = os.getenv("SCHWAB_APP_SECRET")
SCHWAB_TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.json")

# ── Config ────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

HEADLINES_PER_SOURCE = 6

FEEDS = {
    "🌴 LA Local": [
        ("KTLA 5", "https://ktla.com/feed"),
        ("NBC Los Angeles", "https://www.nbclosangeles.com/?rss=y"),
        ("ABC7 LA", "https://abc7.com/feed"),
        ("LA Times", "https://latimes.com/news/rss2.0.xml"),
    ],
    "🏔️ Boulder": [
        ("Daily Camera", "https://www.dailycamera.com/feed"),
        ("Boulder Weekly", "https://www.boulderweekly.com/feed"),
    ],
    "🦬 Denver": [
        ("Denver Post", "https://www.denverpost.com/feed"),
        ("Denver7", "https://www.denver7.com/news/local-news.rss"),
    ],
    "🗞️ National": [
        ("CNN", "http://rss.cnn.com/rss/cnn_topstories.rss"),
        ("New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml"),
        ("NPR News", "https://feeds.npr.org/1001/rss.xml"),
    ],
    "🏈 Sports": [
        ("ESPN", "https://www.espn.com/espn/rss/news"),
    ],
    "💼 Business": [
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
        ("Bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
    ],
}

WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

CITIES = [
    ("Los Angeles", "Los Angeles,US"),
    ("Santa Monica", "Santa Monica,US"),
    ("Calabasas", "Calabasas,US"),
    ("San Francisco", "San Francisco,US"),
    ("Boulder", "Boulder,US"),
    ("Denver", "Denver,US"),
    ("Silverthorne", "Silverthorne,US"),
]

# ── Schwab Positions ──────────────────────────────────────────
@st.cache_data(ttl=300)
def get_schwab_positions():
    try:
        import schwab
        if not SCHWAB_APP_KEY or not SCHWAB_APP_SECRET:
            return None, "Schwab credentials not set in .env"
        if not os.path.exists(SCHWAB_TOKEN_PATH):
            return None, "Run setup_schwab_auth.py first to authenticate"

        client = schwab.auth.client_from_token_file(
            token_path=SCHWAB_TOKEN_PATH,
            api_key=SCHWAB_APP_KEY,
            app_secret=SCHWAB_APP_SECRET,
        )
        resp = client.get_accounts(fields=[schwab.client.Client.Account.Fields.POSITIONS])
        resp.raise_for_status()
        accounts = resp.json()

        positions = []
        for account in accounts:
            acct = account.get("securitiesAccount", {})
            for pos in acct.get("positions", []):
                instrument = pos.get("instrument", {})
                symbol = instrument.get("symbol", "")
                if not symbol or instrument.get("assetType") == "CASH_EQUIVALENT":
                    continue
                qty = pos.get("longQuantity", 0)
                avg_price = pos.get("averageLongPrice") or pos.get("averagePrice", 0)
                market_value = pos.get("marketValue", 0)
                day_pl = pos.get("currentDayProfitLoss", 0)
                day_pl_pct = pos.get("currentDayProfitLossPercentage", 0)
                total_pl = pos.get("longOpenProfitLoss", 0)
                current_price = market_value / qty if qty else 0
                total_pl_pct = ((market_value - (avg_price * qty)) / (avg_price * qty) * 100) if avg_price and qty else 0
                positions.append({
                    "symbol": symbol,
                    "description": instrument.get("description", ""),
                    "qty": qty,
                    "avg_price": avg_price,
                    "current_price": current_price,
                    "market_value": market_value,
                    "day_pl": day_pl,
                    "day_pl_pct": day_pl_pct,
                    "total_pl": total_pl,
                    "total_pl_pct": total_pl_pct,
                })

        positions.sort(key=lambda x: x["market_value"], reverse=True)
        return positions, None
    except ImportError:
        return None, "schwab-py not installed — run: pip install schwab-py"
    except Exception as e:
        return None, str(e)


def build_schwab_section(positions, error):
    if error:
        content = f'<div class="no-feed">{error}</div>'
    elif not positions:
        content = '<div class="no-feed">No positions found</div>'
    else:
        cards = ""
        for p in positions:
            day_color = "#4caf80" if p["day_pl"] >= 0 else "#e05c5c"
            total_color = "#4caf80" if p["total_pl"] >= 0 else "#e05c5c"
            day_sign = "+" if p["day_pl"] >= 0 else ""
            total_sign = "+" if p["total_pl"] >= 0 else ""
            desc = p["description"][:28] + "…" if len(p["description"]) > 28 else p["description"]
            cards += f"""
            <div class="schwab-card">
                <div class="schwab-symbol">{p["symbol"]}</div>
                <div class="schwab-desc">{desc}</div>
                <div class="schwab-price">${p["current_price"]:,.2f}</div>
                <div class="schwab-value">${p["market_value"]:,.0f} &nbsp;<span class="schwab-qty">{p["qty"]:g} shares</span></div>
                <div class="schwab-pl-row">
                    <span style="color:{day_color}">{day_sign}${p["day_pl"]:,.2f} today</span>
                    <span style="color:{total_color}">{total_sign}{p["total_pl_pct"]:.1f}% total</span>
                </div>
            </div>"""

        content = f'<div class="schwab-grid">{cards}</div>'

    return f"""
<div class="section" id="section-Portfolio" data-section="Portfolio">
    <div class="section-header" onclick="toggleSection('Portfolio')">
        <span class="section-label">📈 Portfolio</span>
        <span class="section-toggle" id="toggle-Portfolio">&#9662;</span>
    </div>
    <div class="section-content" id="content-Portfolio">
        {content}
    </div>
</div>"""


# ── Fetch Headlines ───────────────────────────────────────────
@st.cache_data(ttl=900)
def get_headlines(url, num=HEADLINES_PER_SOURCE):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        root = ET.fromstring(r.content)
        items = root.findall(".//item")[:num]
        headlines = []
        for item in items:
            title = item.findtext("title", "No title").strip()
            link = item.findtext("link", "#").strip()
            headlines.append((title, link))
        return headlines
    except Exception:
        return []

@st.cache_data(ttl=900)
def get_weather(city_query):
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city_query}&appid={WEATHER_API_KEY}&units=imperial"
        r = requests.get(url, timeout=10)
        data = r.json()
        return {
            "temp": round(data["main"]["temp"]),
            "feels_like": round(data["main"]["feels_like"]),
            "high": round(data["main"]["temp_max"]),
            "low": round(data["main"]["temp_min"]),
            "humidity": data["main"]["humidity"],
            "wind": round(data["wind"]["speed"]),
            "condition": data["weather"][0]["description"].title(),
            "icon": data["weather"][0]["icon"],
        }
    except Exception:
        return None

# ── Page Config ───────────────────────────────────────────────
st.set_page_config(
    page_title="Jake's Daily Dashboard",
    page_icon="📰",
    layout="wide"
)

st.markdown("""
<style>
    #MainMenu, footer, header { visibility: hidden; }
    .block-container { padding: 0 !important; }
    iframe { border: none !important; }
</style>
""", unsafe_allow_html=True)

# ── Password Gate ─────────────────────────────────────────────
DASHBOARD_PASSWORD = st.secrets.get("DASHBOARD_PASSWORD") or os.getenv("DASHBOARD_PASSWORD")

if DASHBOARD_PASSWORD:
    if not st.session_state.get("authenticated"):
        wrong = st.session_state.get("wrong_password", False)
        st.markdown("""
        <style>
        .stApp, section[data-testid="stMain"], .stMainBlockContainer {
            background: #ffffff !important;
        }
        .block-container {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 90vh !important;
            padding-top: 0 !important;
        }
        div[data-testid="stTextInput"] input {
            text-align: center;
            font-size: 1.2rem;
            border: 3px solid #000 !important;
            border-radius: 0 !important;
            background: #fff !important;
            color: #000 !important;
            padding: 0.6rem 1rem !important;
        }
        div[data-testid="stTextInput"] { max-width: 260px; margin: 0 auto; }
        </style>
        """, unsafe_allow_html=True)

        if wrong:
            st.markdown("""
            <div style="text-align:center; margin-bottom:1.5rem;">
                <div style="font-size:8rem; line-height:1;">🦕</div>
                <div style="font-family:'Arial Black',sans-serif; font-size:4rem; font-weight:900; color:#000; letter-spacing:-2px; margin-top:0.5rem;">STUPID</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style="text-align:center; margin-bottom:1.5rem;">
                <div style="font-family:'Arial Black',sans-serif; font-size:2.8rem; font-weight:900; color:#000; letter-spacing:-1px; line-height:1.1;">ENTER FUCKIN<br>PASSWORD</div>
            </div>
            """, unsafe_allow_html=True)

        pwd = st.text_input("", type="password", label_visibility="collapsed", placeholder="••••••••")
        if pwd:
            if pwd == DASHBOARD_PASSWORD:
                st.session_state["authenticated"] = True
                st.session_state["wrong_password"] = False
                st.rerun()
            else:
                st.session_state["wrong_password"] = True
                st.rerun()
        st.stop()

# ── Helpers ───────────────────────────────────────────────────
from datetime import datetime
import pytz

pacific = pytz.timezone("America/Los_Angeles")
now = datetime.now(pacific)

def section_id(category):
    replacements = {
        "🌴": "LA", "🏔️": "Boulder", "🦬": "Denver",
        "🗞️": "National", "🏈": "Sports", "💼": "Business",
        " ": "-", "/": ""
    }
    result = category
    for k, v in replacements.items():
        result = result.replace(k, v)
    return result.strip("-")

def build_section(category, sources):
    sid = section_id(category)
    cards = ""
    for source_name, url in sources:
        headlines = headline_results.get(url, [])
        items = ""
        if headlines:
            for i, (title, link) in enumerate(headlines, 1):
                safe_title = title.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
                items += f"""
                <div class="headline-item">
                    <span class="num">{i:02d}</span>
                    <a href="{link}" target="_blank">{safe_title}</a>
                </div>"""
        else:
            items = '<div class="no-feed">Feed unavailable</div>'

        cards += f"""
        <div class="card">
            <div class="card-source">{source_name}</div>
            {items}
        </div>"""

    cols = len(sources)
    return f"""
    <div class="section" id="section-{sid}" data-section="{sid}">
        <div class="section-header" onclick="toggleSection('{sid}')">
            <span class="section-label">{category}</span>
            <span class="section-toggle" id="toggle-{sid}">&#9662;</span>
        </div>
        <div class="section-content" id="content-{sid}">
            <div class="grid cols-{cols}">{cards}</div>
        </div>
    </div>"""

# ── Build Pills ───────────────────────────────────────────────
pills_html = '<div class="pills-bar"><span class="pill active" onclick="filterSection(\'all\', this)">✦ All</span><span class="pill" onclick="filterSection(\'Portfolio\', this)">📈 Portfolio</span><span class="pill" onclick="filterSection(\'Weather\', this)">⛅ Weather</span>'
for category in FEEDS.keys():
    sid = section_id(category)
    pills_html += f'<span class="pill" onclick="filterSection(\'{sid}\', this)">{category}</span>'
pills_html += '</div>'

# ── Fetch everything in parallel ──────────────────────────────
def fetch_source(args):
    source_name, url = args
    return source_name, url, get_headlines(url)

def fetch_weather_city(args):
    city_name, city_query = args
    return city_name, get_weather(city_query)

with ThreadPoolExecutor(max_workers=20) as executor:
    all_sources = [(name, url) for sources in FEEDS.values() for name, url in sources]
    headline_futures = {executor.submit(fetch_source, s): s for s in all_sources}
    weather_futures = {executor.submit(fetch_weather_city, c): c for c in CITIES}
    schwab_future = executor.submit(get_schwab_positions)

    headline_results = {}
    for future in as_completed(headline_futures):
        source_name, url, headlines = future.result()
        headline_results[url] = headlines

    weather_collected = {}
    for future in as_completed(weather_futures):
        city_name, w = future.result()
        weather_collected[city_name] = w
    weather_data = [(city_name, weather_collected.get(city_name)) for city_name, _ in CITIES]

    schwab_positions, schwab_error = schwab_future.result()

# ── Build Portfolio Section ───────────────────────────────────
portfolio_section = build_schwab_section(schwab_positions, schwab_error)

# ── Build Sections ────────────────────────────────────────────
sections_html = ""
for category, sources in FEEDS.items():
    sections_html += build_section(category, sources)

# ── Build Weather HTML ────────────────────────────────────────
weather_cards = ""
for city_name, w in weather_data:
    if w:
        icon_url = f"https://openweathermap.org/img/wn/{w['icon']}@2x.png"
        weather_cards += f"""
        <div class="weather-card">
            <div class="weather-city">{city_name}</div>
            <div class="weather-main">
                <img src="{icon_url}" class="weather-icon" />
                <span class="weather-temp">{w['temp']}°</span>
            </div>
            <div class="weather-condition">{w['condition']}</div>
            <div class="weather-details">
                <span>↑ {w['high']}° ↓ {w['low']}°</span>
                <span>💨 {w['wind']} mph</span>
            </div>
        </div>"""
    else:
        weather_cards += f"""
        <div class="weather-card">
            <div class="weather-city">{city_name}</div>
            <div class="no-feed">Unavailable</div>
        </div>"""

weather_section = f"""
<div class="section" id="section-Weather" data-section="Weather">
    <div class="section-header" onclick="toggleSection('Weather')">
        <span class="section-label">⛅ Weather</span>
        <span class="section-toggle" id="toggle-Weather">&#9662;</span>
    </div>
    <div class="section-content" id="content-Weather">
        <div class="weather-grid">{weather_cards}</div>
    </div>
</div>"""

# ── Full HTML Page ────────────────────────────────────────────
html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@400&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}

body {{
    background: #0a0a0a;
    color: #e8e6e1;
    font-family: 'DM Sans', sans-serif;
    padding: 2rem 3rem;
}}

/* Masthead */
.masthead {{
    border-top: 3px solid #e8e6e1;
    border-bottom: 1px solid #2a2a2a;
    padding: 1.5rem 0 1.2rem;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: baseline;
    justify-content: space-between;
}}
.masthead-title {{
    font-family: 'Playfair Display', serif;
    font-size: 3rem;
    font-weight: 900;
    color: #f5f3ee;
    letter-spacing: -1px;
}}
.masthead-title span {{ color: #c9a84c; }}
.masthead-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: #555;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    text-align: right;
    line-height: 2;
}}

/* Pills */
.pills-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid #1a1a1a;
}}
.pill {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #c9a84c;
    background: rgba(201, 168, 76, 0.08);
    border: 1px solid rgba(201, 168, 76, 0.2);
    border-radius: 20px;
    padding: 0.35rem 0.9rem;
    cursor: pointer;
    transition: all 0.2s ease;
    user-select: none;
}}
.pill:hover {{
    background: rgba(201, 168, 76, 0.15);
    border-color: rgba(201, 168, 76, 0.4);
}}
.pill.active {{
    background: rgba(201, 168, 76, 0.2);
    border-color: #c9a84c;
    color: #e8c96a;
}}

/* Sections */
.section {{ margin-bottom: 2rem; }}
.section.hidden {{ display: none; }}

.section-header {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
    border-bottom: 1px solid #1e1e1e;
    user-select: none;
    transition: opacity 0.15s;
}}
.section-header:hover {{ opacity: 0.75; }}

.section-label {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #c9a84c;
}}
.section-toggle {{
    font-size: 0.75rem;
    color: #555;
    transition: transform 0.25s ease;
    display: inline-block;
}}
.section-toggle.collapsed {{ transform: rotate(-90deg); }}

/* Section content */
.section-content {{
    overflow: hidden;
    transition: max-height 0.35s ease, opacity 0.3s ease;
    max-height: 3000px;
    opacity: 1;
}}
.section-content.collapsed {{
    max-height: 0;
    opacity: 0;
}}

/* Grid */
.grid {{ display: grid; gap: 1rem; }}
.cols-1 {{ grid-template-columns: 1fr; }}
.cols-2 {{ grid-template-columns: repeat(2, 1fr); }}
.cols-3 {{ grid-template-columns: repeat(3, 1fr); }}
.cols-4 {{ grid-template-columns: repeat(4, 1fr); }}

/* Cards */
.card {{
    background: #111;
    border: 1px solid #1e1e1e;
    border-radius: 2px;
    padding: 1.2rem;
    transition: border-color 0.2s, background 0.2s;
    position: relative;
    overflow: hidden;
}}
.card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #c9a84c, transparent);
    opacity: 0;
    transition: opacity 0.2s;
}}
.card:hover {{ background: #161616; border-color: #333; }}
.card:hover::before {{ opacity: 1; }}

.card-source {{
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #444;
    padding-bottom: 0.7rem;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid #1a1a1a;
}}

/* Headlines */
.headline-item {{
    padding: 0.45rem 0;
    border-bottom: 1px solid #161616;
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
}}
.headline-item:last-child {{ border-bottom: none; }}
.num {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    color: #2e2e2e;
    flex-shrink: 0;
}}
.headline-item a {{
    font-size: 0.85rem;
    font-weight: 400;
    line-height: 1.4;
    color: #aaa8a0;
    text-decoration: none;
    transition: color 0.15s;
}}
.headline-item a:hover {{ color: #f5f3ee; }}

.no-feed {{
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: #2e2e2e;
    padding: 0.5rem 0;
}}
/* Weather */
.weather-grid {{
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 1rem;
    margin-bottom: 1rem;
}}

.weather-card {{
    background: #111;
    border: 1px solid #1e1e1e;
    border-radius: 2px;
    padding: 1.2rem 1rem;
    text-align: center;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, background 0.2s;
}}

.weather-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #c9a84c, transparent);
    opacity: 0;
    transition: opacity 0.2s;
}}

.weather-card:hover {{ background: #161616; border-color: #333; }}
.weather-card:hover::before {{ opacity: 1; }}

.weather-city {{
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #444;
    margin-bottom: 0.5rem;
}}

.weather-main {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.2rem;
}}

.weather-icon {{
    width: 48px;
    height: 48px;
}}

.weather-temp {{
    font-family: 'Playfair Display', serif;
    font-size: 2rem;
    font-weight: 700;
    color: #f5f3ee;
}}

.weather-condition {{
    font-size: 0.75rem;
    color: #666;
    margin-bottom: 0.6rem;
    margin-top: 0.1rem;
}}

.weather-details {{
    display: flex;
    justify-content: space-between;
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    color: #555;
    border-top: 1px solid #1a1a1a;
    padding-top: 0.5rem;
    margin-top: 0.3rem;
}}

/* Portfolio */
.schwab-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 1rem;
    margin-bottom: 1rem;
}}

.schwab-card {{
    background: #111;
    border: 1px solid #1e1e1e;
    border-radius: 2px;
    padding: 1.1rem 1rem;
    position: relative;
    overflow: hidden;
    transition: border-color 0.2s, background 0.2s;
}}

.schwab-card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #c9a84c, transparent);
    opacity: 0;
    transition: opacity 0.2s;
}}

.schwab-card:hover {{ background: #161616; border-color: #333; }}
.schwab-card:hover::before {{ opacity: 1; }}

.schwab-symbol {{
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
    font-weight: 600;
    color: #c9a84c;
    letter-spacing: 0.05em;
    margin-bottom: 0.15rem;
}}

.schwab-desc {{
    font-size: 0.65rem;
    color: #444;
    margin-bottom: 0.6rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}

.schwab-price {{
    font-family: 'Playfair Display', serif;
    font-size: 1.4rem;
    font-weight: 700;
    color: #f5f3ee;
    margin-bottom: 0.15rem;
}}

.schwab-value {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: #666;
    margin-bottom: 0.5rem;
}}

.schwab-qty {{
    color: #444;
}}

.schwab-pl-row {{
    display: flex;
    justify-content: space-between;
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    border-top: 1px solid #1a1a1a;
    padding-top: 0.5rem;
    margin-top: 0.2rem;
}}
</style>
</head>
<body>

<div class="masthead">
    <div class="masthead-title">Jake's <span>Daily</span> Dashboard</div>
    <div class="masthead-meta">
        {now.strftime("%A, %B %d, %Y")}<br>
        Updated {now.strftime("%I:%M %p")}<br>
        {sum(len(v) for v in FEEDS.values())} sources
    </div>
</div>

{pills_html}

{portfolio_section}

{weather_section}

{sections_html}

<script>
function filterSection(target, el) {{
    document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.section').forEach(section => {{
        if (target === 'all') {{
            section.classList.remove('hidden');
        }} else {{
            section.classList.toggle('hidden', section.dataset.section !== target);
        }}
    }});
}}

function toggleSection(sid) {{
    document.getElementById('content-' + sid).classList.toggle('collapsed');
    document.getElementById('toggle-' + sid).classList.toggle('collapsed');
}}
</script>
</body>
</html>
"""

components.html(html, height=9000, scrolling=True)
