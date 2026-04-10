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

# On Streamlit Cloud, token.json doesn't exist as a file — decode it from secrets
def _ensure_token():
    if not os.path.exists(SCHWAB_TOKEN_PATH):
        try:
            import base64
            token_b64 = st.secrets.get("SCHWAB_TOKEN_JSON") or os.getenv("SCHWAB_TOKEN_JSON", "")
            if token_b64:
                with open(SCHWAB_TOKEN_PATH, "wb") as f:
                    f.write(base64.b64decode(token_b64))
        except Exception:
            pass

_ensure_token()

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

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
DRIVE_ROUTES = [
    ("Calabasas → Brentwood", "4500 Park Granada, Calabasas, CA", "11836 Gorham Ave, Brentwood, CA"),
    ("Brentwood → Malibu Pier", "11836 Gorham Ave, Brentwood, CA", "Malibu Pier, Malibu, CA"),
    ("Brentwood → Venice Beach", "11836 Gorham Ave, Brentwood, CA", "Venice Beach, Venice, CA"),
]

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

ACCOUNT_LABELS = {
    "9632": "Roth IRA",
    "2902": "Individual Brokerage",
}

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
def pct_to_tile_colors(pct):
    """Map daily % change to (bg, fg) — red-to-green gradient, muted palette."""
    if pct >= 3:    return "#0a2e1c", "#5abf88"
    if pct >= 2:    return "#0a2818", "#4caf7a"
    if pct >= 1:    return "#0a2414", "#3d9e6a"
    if pct >= 0.5:  return "#0c1f10", "#2e8f5a"
    if pct >= 0:    return "#111f12", "#1f7a42"
    if pct >= -0.5: return "#1f1111", "#7a3030"
    if pct >= -1:   return "#241212", "#9f3838"
    if pct >= -2:   return "#2d1212", "#b54545"
    if pct >= -3:   return "#361414", "#cc5050"
    return "#3d1414", "#e06060"

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

        accounts_data = []
        for account in accounts:
            acct = account.get("securitiesAccount", {})
            acct_number = acct.get("accountNumber", "")
            last4 = acct_number[-4:] if acct_number else "??"
            label = ACCOUNT_LABELS.get(last4, f"Account (···{last4})")  # add unknown accounts to ACCOUNT_LABELS if needed

            positions = []
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

            if positions:
                positions.sort(key=lambda x: x["market_value"], reverse=True)
                accounts_data.append({"label": label, "positions": positions})

        return accounts_data, None
    except ImportError:
        return None, "schwab-py not installed — run: pip install schwab-py"
    except Exception as e:
        return None, str(e)


def build_rollup(accounts_data):
    """Aggregate positions across all accounts by symbol."""
    merged = {}
    for acct in accounts_data:
        for p in acct["positions"]:
            sym = p["symbol"]
            if sym not in merged:
                merged[sym] = {
                    "symbol": sym,
                    "qty": 0,
                    "market_value": 0,
                    "day_pl": 0,
                    "total_pl": 0,
                    "cost_basis": 0,
                    "day_pl_pct": 0,
                    "total_pl_pct": 0,
                    "current_price": p["current_price"],
                }
            merged[sym]["qty"] += p["qty"]
            merged[sym]["market_value"] += p["market_value"]
            merged[sym]["day_pl"] += p["day_pl"]
            merged[sym]["total_pl"] += p["total_pl"]
            merged[sym]["cost_basis"] += p["avg_price"] * p["qty"]

    rollup = []
    for sym, d in merged.items():
        prev_mv = d["market_value"] - d["day_pl"]
        d["day_pl_pct"] = (d["day_pl"] / prev_mv * 100) if prev_mv else 0
        d["total_pl_pct"] = (d["total_pl"] / d["cost_basis"] * 100) if d["cost_basis"] else 0
        rollup.append(d)

    rollup.sort(key=lambda x: x["market_value"], reverse=True)
    return rollup


def build_treemap(positions):
    """Build a single treemap HTML block for a list of positions."""
    sorted_pos = sorted(positions, key=lambda x: abs(x["day_pl"]), reverse=True)
    max_abs = max(abs(p["day_pl"]) for p in sorted_pos) or 1
    tiles = ""
    for p in sorted_pos:
        bg, fg = pct_to_tile_colors(p["day_pl_pct"])
        flex_val = max(2, round(abs(p["day_pl"]) / max_abs * 20))
        day_sign = "+" if p["day_pl"] >= 0 else ""
        total_sign = "+" if p["total_pl"] >= 0 else ""
        tiles += f"""
        <div class="ptile" style="background:{bg}; color:{fg}; flex:{flex_val} 1 {max(100, flex_val * 11)}px;">
            <div class="ptile-symbol">{p["symbol"]}</div>
            <div class="ptile-price">${p["current_price"]:,.2f}</div>
            <div class="ptile-mv">${p["market_value"]:,.0f}</div>
            <div class="ptile-day-row">{day_sign}{p["day_pl_pct"]:.2f}% &nbsp; {day_sign}${p["day_pl"]:,.2f}</div>
            <div class="ptile-divider"></div>
            <div class="ptile-total">{total_sign}{p["total_pl_pct"]:.1f}% &nbsp; {total_sign}${p["total_pl"]:,.0f} total</div>
            <div class="ptile-shares">{p["qty"]:g} shares</div>
        </div>"""
    return f'<div class="portfolio-treemap">{tiles}</div>'


def build_acct_summary(positions, label=None):
    """Build a summary line showing day % and $ for a set of positions."""
    day_pl = sum(p["day_pl"] for p in positions)
    mv = sum(p["market_value"] for p in positions)
    prev_mv = mv - day_pl
    day_pct = (day_pl / prev_mv * 100) if prev_mv else 0
    color = "#4caf80" if day_pl >= 0 else "#e05c5c"
    sign = "+" if day_pl >= 0 else ""
    label_html = f'<span class="acct-summary-label">{label}</span> &nbsp; ' if label else ""
    return f"""<div class="acct-summary">
        {label_html}<span style="color:{color};">{sign}{day_pct:.2f}%</span>
        <span style="color:{color}; opacity:0.7;"> &nbsp; {sign}${day_pl:,.2f} today</span>
    </div>"""


def build_schwab_section(accounts_data, error):
    if error:
        summary = ""
        content = f'<div class="no-feed">{error}</div>'
    elif not accounts_data:
        summary = ""
        content = '<div class="no-feed">No positions found</div>'
    else:
        all_positions = [p for acct in accounts_data for p in acct["positions"]]

        # Overall summary across all accounts
        summary = build_acct_summary(all_positions)

        # Rollup treemap
        rollup = build_rollup(accounts_data)
        content = '<div class="acct-label">All Accounts</div>'
        content += build_treemap(rollup)

        # One treemap per account with its own summary
        for acct in accounts_data:
            content += build_acct_summary(acct["positions"], label=acct["label"])
            content += build_treemap(acct["positions"])

    return f"""
<div class="section" id="section-Portfolio" data-section="Portfolio">
    <div class="section-header" onclick="toggleSection('Portfolio')">
        <span class="section-label">📈 Portfolio</span>
        <span class="section-toggle" id="toggle-Portfolio">&#9662;</span>
    </div>
    <div class="section-content" id="content-Portfolio">
        {summary}
        {content}
    </div>
</div>"""


# ── Drive Time ────────────────────────────────────────────────
@st.cache_data(ttl=600)
def get_drive_time():
    if not GOOGLE_MAPS_API_KEY:
        return None, "Set GOOGLE_MAPS_API_KEY in .env"
    try:
        routes = []
        for label, origin, destination in DRIVE_ROUTES:
            params = {
                "origins": origin,
                "destinations": destination,
                "departure_time": "now",
                "traffic_model": "best_guess",
                "units": "imperial",
                "key": GOOGLE_MAPS_API_KEY,
            }
            r = requests.get("https://maps.googleapis.com/maps/api/distancematrix/json", params=params, timeout=10)
            data = r.json()
            if data.get("status") != "OK":
                routes.append({"label": label, "error": True})
                continue
            element = data["rows"][0]["elements"][0]
            if element["status"] != "OK":
                routes.append({"label": label, "error": True})
                continue
            duration_traffic = element.get("duration_in_traffic", element.get("duration", {})).get("value", 0)
            duration_normal = element.get("duration", {}).get("value", 0)
            routes.append({
                "label": label,
                "minutes": round(duration_traffic / 60),
                "normal_minutes": round(duration_normal / 60),
                "distance": element.get("distance", {}).get("text", ""),
                "ratio": duration_traffic / duration_normal if duration_normal else 1,
                "error": False,
            })
        return routes, None
    except Exception as e:
        return None, str(e)


def build_drive_section(drive_data, error):
    if error:
        content = f'<div class="no-feed">{error}</div>'
    elif not drive_data:
        content = '<div class="no-feed">No drive data</div>'
    else:
        tiles = ""
        for route in drive_data:
            if route.get("error"):
                tiles += f'<div class="drive-tile"><div class="no-feed">{route["label"]}: unavailable</div></div>'
                continue
            m = route["minutes"]
            delay = m - route["normal_minutes"]
            ratio = route["ratio"]
            if ratio < 1.15:
                traffic_label, traffic_color = "Light", "#4caf80"
            elif ratio < 1.5:
                traffic_label, traffic_color = "Moderate", "#c9a84c"
            else:
                traffic_label, traffic_color = "Heavy", "#e05c5c"
            delay_str = f"+{delay} min" if delay > 2 else "On time"
            tiles += f"""
            <div class="drive-tile">
                <div class="drive-dest">{route['label']}</div>
                <div class="drive-time">{m}<span class="drive-unit">min</span></div>
                <div class="drive-route">{route['distance']}</div>
                <div class="drive-traffic" style="color:{traffic_color}">{traffic_label} traffic &nbsp;·&nbsp; {delay_str}</div>
            </div>"""
        content = f'<div class="drive-grid">{tiles}</div>'
    return f"""
<div class="section" id="section-Drive" data-section="Drive">
    <div class="section-header" onclick="toggleSection('Drive')">
        <span class="section-label">🚗 Fuckin Traffic</span>
        <span class="section-toggle" id="toggle-Drive">&#9662;</span>
    </div>
    <div class="section-content" id="content-Drive">
        {content}
    </div>
</div>"""


# ── Gmail ──────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_gmail_summary():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return None, "Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env"
    try:
        import imaplib
        import email as email_lib
        from email.header import decode_header as decode_hdr

        def decode_str(raw):
            parts = decode_hdr(raw or "")
            result = ""
            for part, enc in parts:
                if isinstance(part, bytes):
                    result += part.decode(enc or "utf-8", errors="replace")
                else:
                    result += str(part)
            return result.strip()

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("INBOX")

        _, unread_data = mail.search(None, "UNSEEN")
        unread_ids = set(unread_data[0].split())
        unread_count = len(unread_ids)

        _, all_data = mail.search(None, "ALL")
        all_ids = all_data[0].split()
        recent_ids = all_ids[-8:][::-1]

        emails = []
        for eid in recent_ids:
            _, msg_data = mail.fetch(eid, "(RFC822)")
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subject = decode_str(msg.get("Subject", "(no subject)"))[:80]
            sender_raw = decode_str(msg.get("From", ""))
            # Extract just the name if present: "Name <email>" → "Name"
            sender = sender_raw.split("<")[0].strip().strip('"') or sender_raw.split("@")[0]
            sender = sender[:40]
            date_str = msg.get("Date", "")
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(date_str)
                dt_pacific = dt.astimezone(pytz.timezone("America/Los_Angeles"))
                today = datetime.now(pytz.timezone("America/Los_Angeles")).date()
                if dt_pacific.date() == today:
                    time_label = dt_pacific.strftime("%-I:%M %p")
                else:
                    time_label = dt_pacific.strftime("%b %-d")
            except Exception:
                time_label = ""
            emails.append({
                "subject": subject,
                "sender": sender,
                "time": time_label,
                "unread": eid in unread_ids,
            })

        mail.logout()
        return {"unread_count": unread_count, "emails": emails}, None
    except Exception as e:
        return None, str(e)


def build_gmail_section(gmail_data, error):
    if error:
        content = f'<div class="no-feed">{error}</div>'
    elif not gmail_data:
        content = '<div class="no-feed">No email data</div>'
    else:
        unread = gmail_data["unread_count"]
        badge = f'<span class="gmail-badge">{unread} unread</span>' if unread else '<span class="gmail-badge zero">inbox zero</span>'
        rows = ""
        for em in gmail_data["emails"]:
            weight = "600" if em["unread"] else "400"
            dot = '<span class="gmail-dot"></span>' if em["unread"] else '<span class="gmail-dot" style="opacity:0"></span>'
            rows += f"""
            <div class="gmail-row">
                {dot}
                <div class="gmail-sender" style="font-weight:{weight}">{em['sender']}</div>
                <div class="gmail-subject">{em['subject']}</div>
                <div class="gmail-time">{em['time']}</div>
            </div>"""
        content = f"""
        <div class="gmail-toprow">{badge}</div>
        <div class="gmail-list">{rows}</div>"""
    return f"""
<div class="section" id="section-Gmail" data-section="Gmail">
    <div class="section-header" onclick="toggleSection('Gmail')">
        <span class="section-label">✉️ Gmail</span>
        <span class="section-toggle" id="toggle-Gmail">&#9662;</span>
    </div>
    <div class="section-content" id="content-Gmail">
        {content}
    </div>
</div>"""


# ── Color Helpers ─────────────────────────────────────────────
def temp_to_colors(temp):
    """Return (bg_color, text_color) based on temperature in °F — muted palette."""
    if temp >= 100: return "#3d1a1a", "#c9a09a"
    if temp >= 90:  return "#3d2218", "#c9a48a"
    if temp >= 80:  return "#3a2a14", "#c9b080"
    if temp >= 70:  return "#2a3018", "#a0b87a"
    if temp >= 60:  return "#1a2e20", "#7aaa88"
    if temp >= 50:  return "#162535", "#7aA0c0"
    if temp >= 40:  return "#121e30", "#6e90b8"
    if temp >= 30:  return "#101828", "#7080b0"
    return "#0d1420", "#6878a8"

# ── Summary Section ───────────────────────────────────────────
CA_CITIES_SUMMARY = {"Los Angeles", "Santa Monica", "Calabasas", "San Francisco"}
SUMMARY_LA_COUNT = 3
SUMMARY_SPORTS_COUNT = 2

def _swing_bar(pct, max_swing=3.0):
    """Return HTML for a centered swing bar showing day % change."""
    clamped = max(-max_swing, min(max_swing, pct))
    bar_pct = abs(clamped) / max_swing * 50
    bar_color = "#4caf80" if pct >= 0 else "#e05c5c"
    bar_left = 50 - bar_pct if pct < 0 else 50
    return f"""
    <div class="sum-swing-track">
        <div class="sum-swing-center"></div>
        <div class="sum-swing-fill" style="left:{bar_left:.1f}%; width:{bar_pct:.1f}%; background:{bar_color};"></div>
    </div>
    <div class="sum-swing-labels"><span>-3%</span><span>0</span><span>+3%</span></div>"""


def _summary_portfolio(accounts_data):
    if not accounts_data:
        return '<div class="sum-empty">Portfolio unavailable</div>'
    all_pos = [p for acct in accounts_data for p in acct["positions"]]
    total_mv = sum(p["market_value"] for p in all_pos)
    total_day_pl = sum(p["day_pl"] for p in all_pos)
    prev_mv = total_mv - total_day_pl
    total_pct = (total_day_pl / prev_mv * 100) if prev_mv else 0
    color = "#4caf80" if total_day_pl >= 0 else "#e05c5c"
    sign = "+" if total_day_pl >= 0 else ""

    # Themed swatches: gold + muted blue-gray matching the dark newspaper palette
    swatch_colors = ["#c9a84c", "#7a9ab8", "#8a7acc", "#7aaa88"]

    # Stacked bar segments + per-account legend rows with swing bars
    stack_segs = ""
    legend_rows = ""
    for i, acct in enumerate(accounts_data):
        acct_mv = sum(p["market_value"] for p in acct["positions"])
        acct_day_pl = sum(p["day_pl"] for p in acct["positions"])
        prev = acct_mv - acct_day_pl
        acct_pct = (acct_day_pl / prev * 100) if prev else 0
        flex_val = (acct_mv / total_mv * 100) if total_mv else 0
        bc = "#4caf80" if acct_day_pl >= 0 else "#e05c5c"
        bs = "+" if acct_day_pl >= 0 else ""
        swatch = swatch_colors[i % len(swatch_colors)]
        stack_segs += f'<div class="sum-stack-seg" style="flex:{flex_val:.1f}; background:{swatch};" title="{acct["label"]}"></div>'
        legend_rows += f"""
        <div class="sum-legend-row">
            <span class="sum-legend-dot" style="background:{swatch};"></span>
            <span class="sum-legend-label">{acct["label"]}</span>
            <span class="sum-legend-val">${acct_mv:,.0f}</span>
            <span class="sum-legend-chg" style="color:{bc};">{bs}{acct_pct:.2f}% &nbsp; {bs}${acct_day_pl:,.0f}</span>
        </div>
        <div class="sum-acct-swing">{_swing_bar(acct_pct)}</div>"""

    return f"""
    <div class="sum-panel-title">Portfolio</div>
    <div class="sum-port-total">${total_mv:,.0f}</div>
    <div class="sum-port-day" style="color:{color};">{sign}{total_pct:.2f}% &nbsp; {sign}${total_day_pl:,.2f} today</div>
    <div class="sum-stack-bar">{stack_segs}</div>
    <div class="sum-legend">{legend_rows}</div>"""


def _summary_weather(weather_data):
    rows = ""
    for city_name, w in weather_data:
        if city_name not in CA_CITIES_SUMMARY:
            continue
        if not w:
            rows += f'<div class="sum-w-row"><span class="sum-w-city">{city_name}</span><span class="sum-w-temp">—</span></div>'
            continue
        bg, fg = temp_to_colors(w["temp"])
        rows += f"""
        <div class="sum-w-row" style="background:{bg}; color:{fg};">
            <span class="sum-w-city">{city_name}</span>
            <span class="sum-w-temp">{w["temp"]}°</span>
            <span class="sum-w-cond">{w["condition"]}</span>
        </div>"""
    return f'<div class="sum-panel-title">Weather</div><div class="sum-w-list">{rows}</div>'


def _summary_drives(drive_data):
    if not drive_data:
        return '<div class="sum-panel-title">Traffic</div><div class="sum-empty">Unavailable</div>'
    rows = ""
    for route in drive_data:
        if route.get("error"):
            rows += f'<div class="sum-d-row"><span class="sum-d-label">{route["label"]}</span><span class="sum-d-time">—</span></div>'
            continue
        ratio = route["ratio"]
        tc = "#4caf80" if ratio < 1.15 else ("#c9a84c" if ratio < 1.5 else "#e05c5c")
        rows += f"""
        <div class="sum-d-row">
            <span class="sum-d-label">{route["label"]}</span>
            <span class="sum-d-time" style="color:{tc};">{route["minutes"]}<span class="sum-d-unit">min</span></span>
            <span class="sum-d-dist">{route.get("distance", "")}</span>
        </div>"""
    return f'<div class="sum-panel-title">Traffic</div><div class="sum-d-list">{rows}</div>'


def _summary_stories(headline_results):
    la_sources = FEEDS.get("🌴 LA Local", [])
    sports_sources = FEEDS.get("🏈 Sports", [])
    stories = []
    for name, url in la_sources:
        for title, link in headline_results.get(url, []):
            stories.append((title, link, name))
            break
        if len(stories) >= SUMMARY_LA_COUNT:
            break
    for name, url in sports_sources:
        for title, link in headline_results.get(url, []):
            stories.append((title, link, name))
            break
        if len([s for s in stories if s[2] in [n for n, _ in sports_sources]]) >= SUMMARY_SPORTS_COUNT:
            break
    rows = ""
    for title, link, source in stories:
        safe = title.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        rows += f"""
        <div class="sum-story">
            <span class="sum-story-src">{source}</span>
            <a href="{link}" target="_blank" class="sum-story-link">{safe}</a>
        </div>"""
    return f'<div class="sum-panel-title">Top Stories</div><div class="sum-stories">{rows}</div>'


def _summary_email(gmail_data, error):
    if error or not gmail_data:
        return '<div class="sum-panel-title">Email</div><div class="sum-empty">Unavailable</div>'
    unread = gmail_data["unread_count"]
    badge_color = "#c9a84c" if unread > 0 else "#4caf80"
    badge_text = f"{unread} unread" if unread > 0 else "inbox zero"
    rows = ""
    for em in gmail_data["emails"][:5]:
        weight = "600" if em["unread"] else "400"
        dot = f'<span class="sum-em-dot" style="opacity:{1 if em["unread"] else 0};"></span>'
        rows += f"""
        <div class="sum-em-row" style="font-weight:{weight};">
            {dot}
            <span class="sum-em-sender">{em['sender']}</span>
            <span class="sum-em-subject">{em['subject']}</span>
            <span class="sum-em-time">{em['time']}</span>
        </div>"""
    return f"""
    <div class="sum-panel-title">Email &nbsp;<span style="color:{badge_color}; font-size:0.65rem; letter-spacing:0.05em; text-transform:none;">{badge_text}</span></div>
    <div class="sum-em-list">{rows}</div>"""


def build_summary_section(accounts_data, weather_data, drive_data, headline_results, gmail_data=None, gmail_error=None):
    port  = _summary_portfolio(accounts_data)
    wx    = _summary_weather(weather_data)
    drv   = _summary_drives(drive_data)
    mail  = _summary_email(gmail_data, gmail_error)
    news  = _summary_stories(headline_results)
    return f"""
<div class="section" id="section-Summary" data-section="Summary">
    <div class="section-header" onclick="toggleSection('Summary')">
        <span class="section-label">⚡ Summary</span>
        <span class="section-toggle" id="toggle-Summary">&#9662;</span>
    </div>
    <div class="section-content" id="content-Summary">
        <div class="summary-grid">
            <div class="sum-panel">{port}</div>
            <div class="sum-panel">{wx}</div>
            <div class="sum-panel">{drv}</div>
            <div class="sum-panel">{mail}</div>
            <div class="sum-panel">{news}</div>
        </div>
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
        status_msg = '// ACCESS DENIED — TRY AGAIN' if wrong else '// AUTHENTICATION REQUIRED'
        status_color = '#e05c5c' if wrong else '#555'
        st.markdown(f"""
        <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700;900&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
        <style>
        .stApp, section[data-testid="stMain"], .stMainBlockContainer {{
            background: #0a0a0a !important;
        }}
        .block-container {{
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
            justify-content: center !important;
            min-height: 100vh !important;
            padding: 0 !important;
        }}
        div[data-testid="stTextInput"] {{
            max-width: 340px;
            margin: 0 auto;
        }}
        div[data-testid="stTextInput"] input {{
            background: #0f0f0f !important;
            border: 1px solid #2a2a2a !important;
            border-left: 3px solid #c9a84c !important;
            border-radius: 0 !important;
            color: #c9a84c !important;
            font-family: 'DM Mono', monospace !important;
            font-size: 1rem !important;
            letter-spacing: 0.2em !important;
            padding: 0.7rem 1rem 0.7rem 1.2rem !important;
        }}
        div[data-testid="stTextInput"] input:focus {{
            border-color: #c9a84c !important;
            box-shadow: 0 0 0 1px rgba(201,168,76,0.3) !important;
        }}
        div[data-testid="stTextInput"] input::placeholder {{
            color: #333 !important;
            letter-spacing: 0.1em !important;
        }}
        @keyframes blink {{ 0%,100%{{opacity:1}} 50%{{opacity:0}} }}
        .cursor {{ display:inline-block; animation: blink 1.1s infinite; color:#c9a84c; }}
        @keyframes scanline {{
            0% {{ transform: translateY(-100%); }}
            100% {{ transform: translateY(100vh); }}
        }}
        </style>
        <div style="width:100%; max-width:420px; margin:0 auto;">
            <!-- Mac-style window chrome -->
            <div style="background:#111; border:1px solid #1e1e1e; border-bottom:none; border-radius:6px 6px 0 0; padding:0.6rem 1rem; display:flex; align-items:center; gap:0.5rem;">
                <span style="width:12px;height:12px;border-radius:50%;background:#ff5f57;display:inline-block;"></span>
                <span style="width:12px;height:12px;border-radius:50%;background:#febc2e;display:inline-block;"></span>
                <span style="width:12px;height:12px;border-radius:50%;background:#28c840;display:inline-block;"></span>
                <span style="font-family:'DM Mono',monospace; font-size:0.58rem; color:#333; letter-spacing:0.15em; margin-left:0.5rem; text-transform:uppercase;">dashboard.py — python3</span>
            </div>
            <!-- Main card -->
            <div style="background:#0d0d0d; border:1px solid #1e1e1e; border-top:none; border-radius:0 0 6px 6px; padding:2.5rem 2rem 2rem;">
                <!-- Header rule -->
                <div style="border-top:2px solid #c9a84c; margin-bottom:1.5rem;"></div>
                <!-- Title -->
                <div style="font-family:'DM Mono',monospace; font-size:0.6rem; letter-spacing:0.3em; text-transform:uppercase; color:#555; margin-bottom:0.4rem;">Jake's</div>
                <div style="font-family:'Playfair Display',serif; font-size:2.4rem; font-weight:900; color:#f5f3ee; letter-spacing:-1px; line-height:1; margin-bottom:1.5rem;">Daily <span style="color:#c9a84c;">Dashboard</span></div>
                <!-- Status line -->
                <div style="font-family:'DM Mono',monospace; font-size:0.62rem; letter-spacing:0.12em; color:{status_color}; margin-bottom:1.5rem; border-left:2px solid {status_color}; padding-left:0.7rem;">{status_msg}</div>
                <!-- Prompt label -->
                <div style="font-family:'DM Mono',monospace; font-size:0.6rem; color:#444; letter-spacing:0.1em; margin-bottom:0.4rem;">ENTER PASSWORD <span class="cursor">_</span></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        pwd = st.text_input("", type="password", label_visibility="collapsed", placeholder="············")
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
pills_html = '<div class="pills-bar"><span class="pill active" onclick="filterSection(\'all\', this)">✦ All</span><span class="pill" onclick="filterSection(\'Summary\', this)">⚡ Summary</span><span class="pill" onclick="filterSection(\'Drive\', this)">🚗 Traffic</span><span class="pill" onclick="filterSection(\'Gmail\', this)">✉️ Gmail</span><span class="pill" onclick="filterSection(\'Portfolio\', this)">📈 Portfolio</span><span class="pill" onclick="filterSection(\'Weather\', this)">⛅ Weather</span>'
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
    drive_future = executor.submit(get_drive_time)
    gmail_future = executor.submit(get_gmail_summary)

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
    drive_data, drive_error = drive_future.result()
    gmail_data, gmail_error = gmail_future.result()

# ── Build All Sections ────────────────────────────────────────
summary_section = build_summary_section(schwab_positions, weather_data, drive_data, headline_results, gmail_data, gmail_error)
portfolio_section = build_schwab_section(schwab_positions, schwab_error)
drive_section = build_drive_section(drive_data, drive_error)
gmail_section = build_gmail_section(gmail_data, gmail_error)

# ── Build Sections ────────────────────────────────────────────
sections_html = ""
for category, sources in FEEDS.items():
    sections_html += build_section(category, sources)

# ── Build Weather Treemap ─────────────────────────────────────

weather_tiles = ""
for city_name, w in weather_data:
    if not w:
        weather_tiles += f'<div class="wtile"><div class="wtile-city">{city_name}</div><div class="wtile-na">—</div></div>'
        continue
    bg, fg = temp_to_colors(w["temp"])
    weather_tiles += f"""
    <div class="wtile" style="background:{bg}; color:{fg};">
        <div class="wtile-city">{city_name}</div>
        <div class="wtile-temp">{w['temp']}°</div>
        <div class="wtile-cond">{w['condition']}</div>
        <div class="wtile-detail">↑{w['high']}° ↓{w['low']}° · {w['wind']}mph</div>
    </div>"""

weather_section = f"""
<div class="section" id="section-Weather" data-section="Weather">
    <div class="section-header" onclick="toggleSection('Weather')">
        <span class="section-label">⛅ Weather</span>
        <span class="section-toggle" id="toggle-Weather">&#9662;</span>
    </div>
    <div class="section-content" id="content-Weather">
        <div class="weather-treemap">{weather_tiles}</div>
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
/* Weather Treemap */
.weather-treemap {{
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 0.5rem;
    margin-bottom: 1rem;
}}

.wtile {{
    border-radius: 3px;
    padding: 1rem;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    transition: filter 0.2s, transform 0.15s;
    cursor: default;
    min-height: 100px;
    overflow: hidden;
}}
.wtile:hover {{ filter: brightness(1.2); transform: scale(1.02); }}

.wtile-city {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    opacity: 0.6;
    margin-bottom: 0.3rem;
}}
.wtile-temp {{
    font-family: 'Playfair Display', serif;
    font-weight: 700;
    font-size: 2.2rem;
    line-height: 1;
    margin-bottom: 0.2rem;
}}
.wtile-cond {{
    font-size: 0.65rem;
    opacity: 0.7;
    margin-bottom: 0.3rem;
}}
.wtile-detail {{
    font-family: 'DM Mono', monospace;
    font-size: 0.52rem;
    opacity: 0.5;
    border-top: 1px solid rgba(255,255,255,0.08);
    padding-top: 0.4rem;
    margin-top: auto;
}}
.wtile-na {{
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    opacity: 0.4;
}}

/* Portfolio Treemap */
.portfolio-treemap {{
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 1rem;
}}

.ptile {{
    border-radius: 3px;
    padding: 1.1rem 1rem;
    display: flex;
    flex-direction: column;
    min-height: 150px;
    overflow: hidden;
    transition: filter 0.2s, transform 0.15s;
    cursor: default;
}}
.ptile:hover {{ filter: brightness(1.15); transform: scale(1.02); }}

.ptile-symbol {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    opacity: 0.6;
    margin-bottom: 0.5rem;
}}

.ptile-price {{
    font-family: 'Playfair Display', serif;
    font-size: 1.7rem;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 0.4rem;
}}

.ptile-mv {{
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    opacity: 0.6;
    margin-bottom: 0.4rem;
    margin-top: -0.1rem;
}}

.ptile-day-row {{
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    opacity: 0.8;
    margin-bottom: 0.5rem;
}}

.ptile-divider {{
    border-top: 1px solid rgba(255,255,255,0.08);
    margin: 0.4rem 0;
}}

.ptile-total {{
    font-family: 'DM Mono', monospace;
    font-size: 0.55rem;
    opacity: 0.55;
    margin-bottom: 0.3rem;
}}

.ptile-shares {{
    font-family: 'DM Mono', monospace;
    font-size: 0.52rem;
    opacity: 0.35;
    margin-top: auto;
}}

.acct-label {{
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #444;
    margin: 1.8rem 0 0.5rem;
}}
.acct-label:first-of-type {{ margin-top: 0; }}

.acct-summary {{
    font-family: 'Playfair Display', serif;
    font-size: 1.5rem;
    font-weight: 700;
    margin-bottom: 0.8rem;
    line-height: 1;
}}
.acct-summary-label {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #444;
    vertical-align: middle;
    font-weight: 400;
}}

/* Summary Section */
.summary-grid {{
    display: grid;
    grid-template-columns: 2fr 1fr 1.2fr 1.5fr 1.8fr;
    gap: 1.5rem;
    align-items: start;
}}
.sum-panel {{
    display: flex;
    flex-direction: column;
    gap: 0;
}}
.sum-panel-title {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #444;
    margin-bottom: 0.7rem;
}}
.sum-empty {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: #333;
}}
/* Portfolio panel */
.sum-port-total {{
    font-family: 'Playfair Display', serif;
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
    color: #f5f3ee;
    margin-bottom: 0.2rem;
}}
.sum-port-day {{
    font-family: 'DM Mono', monospace;
    font-size: 0.63rem;
    margin-bottom: 0.9rem;
}}
.sum-stack-bar {{
    display: flex;
    height: 10px;
    border-radius: 3px;
    overflow: hidden;
    gap: 2px;
    margin-bottom: 0.6rem;
}}
.sum-stack-seg {{ height: 100%; border-radius: 2px; }}
.sum-legend {{ display: flex; flex-direction: column; gap: 0.35rem; }}
.sum-legend-row {{
    display: grid;
    grid-template-columns: 8px 1fr auto auto;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.2rem;
}}
.sum-legend-dot {{
    width: 8px; height: 8px;
    border-radius: 2px;
    flex-shrink: 0;
}}
.sum-legend-label {{
    font-family: 'DM Mono', monospace;
    font-size: 0.56rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #666;
}}
.sum-legend-val {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    color: #555;
}}
.sum-legend-chg {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    text-align: right;
}}
.sum-swing-wrap {{ margin-top: 0.4rem; }}
.sum-swing-track {{
    position: relative;
    height: 8px;
    background: #1a1a1a;
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 0.25rem;
}}
.sum-swing-center {{
    position: absolute;
    left: 50%; top: 0;
    width: 1px; height: 100%;
    background: #333;
}}
.sum-swing-fill {{
    position: absolute;
    top: 0; height: 100%;
    border-radius: 3px;
    transition: width 0.5s ease;
}}
.sum-swing-labels {{
    display: flex;
    justify-content: space-between;
    font-family: 'DM Mono', monospace;
    font-size: 0.5rem;
    color: #444;
}}
.sum-acct-swing {{
    margin: 0.25rem 0 0.7rem 1.1rem;
}}
/* Weather panel */
.sum-w-list {{ display: flex; flex-direction: column; gap: 0.35rem; }}
.sum-w-row {{
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.45rem 0.7rem;
    border-radius: 3px;
    background: #111;
}}
.sum-w-city {{
    font-family: 'DM Mono', monospace;
    font-size: 0.56rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    opacity: 0.6;
    flex: 1;
}}
.sum-w-temp {{
    font-family: 'Playfair Display', serif;
    font-size: 1.1rem;
    font-weight: 700;
    line-height: 1;
}}
.sum-w-cond {{
    font-size: 0.55rem;
    opacity: 0.6;
    text-align: right;
    flex: 1;
}}
/* Drive panel */
.sum-d-list {{ display: flex; flex-direction: column; gap: 0.5rem; }}
.sum-d-row {{
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid #161616;
}}
.sum-d-row:last-child {{ border-bottom: none; }}
.sum-d-label {{
    font-family: 'DM Mono', monospace;
    font-size: 0.56rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #555;
    flex: 1;
}}
.sum-d-time {{
    font-family: 'Playfair Display', serif;
    font-size: 1.4rem;
    font-weight: 700;
    line-height: 1;
}}
.sum-d-unit {{
    font-family: 'DM Mono', monospace;
    font-size: 0.55rem;
    color: #555;
    margin-left: 0.15rem;
}}
.sum-d-dist {{
    font-family: 'DM Mono', monospace;
    font-size: 0.55rem;
    color: #444;
}}
/* Stories panel */
.sum-stories {{ display: flex; flex-direction: column; gap: 0; }}
.sum-story {{
    padding: 0.55rem 0;
    border-bottom: 1px solid #161616;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
}}
.sum-story:last-child {{ border-bottom: none; }}
.sum-story-src {{
    font-family: 'DM Mono', monospace;
    font-size: 0.52rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #444;
}}
.sum-story-link {{
    font-size: 0.8rem;
    line-height: 1.4;
    color: #aaa8a0;
    text-decoration: none;
    transition: color 0.15s;
}}
.sum-story-link:hover {{ color: #f5f3ee; }}

/* Summary Email */
.sum-em-list {{ display: flex; flex-direction: column; gap: 0; }}
.sum-em-row {{
    display: grid;
    grid-template-columns: 8px 1fr auto;
    grid-template-rows: auto auto;
    column-gap: 0.5rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid #161616;
    align-items: center;
}}
.sum-em-row:last-child {{ border-bottom: none; }}
.sum-em-dot {{
    width: 6px; height: 6px;
    border-radius: 50%;
    background: #c9a84c;
    grid-row: 1 / 3;
    align-self: center;
}}
.sum-em-sender {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    color: #777;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.sum-em-subject {{
    font-size: 0.72rem;
    color: #aaa8a0;
    grid-column: 2;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.sum-em-time {{
    font-family: 'DM Mono', monospace;
    font-size: 0.52rem;
    color: #444;
    grid-row: 1;
    grid-column: 3;
    white-space: nowrap;
}}

/* Drive Home */
.drive-grid {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
    margin-bottom: 1rem;
}}
.drive-tile {{
    background: #111;
    border: 1px solid #1e1e1e;
    border-radius: 2px;
    padding: 1.2rem 1.4rem;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
}}
.drive-dest {{
    font-family: 'DM Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    color: #555;
    margin-bottom: 0.2rem;
}}
.drive-time {{
    font-family: 'Playfair Display', serif;
    font-size: 2.8rem;
    font-weight: 700;
    color: #f5f3ee;
    line-height: 1;
}}
.drive-unit {{
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: #555;
    margin-left: 0.3rem;
    vertical-align: super;
}}
.drive-route {{
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    color: #555;
    letter-spacing: 0.04em;
}}
.drive-traffic {{
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 0.04em;
}}

/* Gmail */
.gmail-toprow {{
    margin-bottom: 0.8rem;
}}
.gmail-badge {{
    font-family: 'DM Mono', monospace;
    font-size: 0.62rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    background: rgba(201, 168, 76, 0.12);
    border: 1px solid rgba(201, 168, 76, 0.25);
    color: #c9a84c;
    padding: 0.2rem 0.7rem;
    border-radius: 20px;
}}
.gmail-badge.zero {{
    color: #4caf80;
    background: rgba(76, 175, 128, 0.1);
    border-color: rgba(76, 175, 128, 0.2);
}}
.gmail-list {{
    display: flex;
    flex-direction: column;
    gap: 0;
    border: 1px solid #1e1e1e;
    border-radius: 2px;
    overflow: hidden;
}}
.gmail-row {{
    display: grid;
    grid-template-columns: 12px 160px 1fr auto;
    align-items: center;
    gap: 0.8rem;
    padding: 0.65rem 1rem;
    border-bottom: 1px solid #161616;
    background: #111;
    transition: background 0.15s;
}}
.gmail-row:last-child {{ border-bottom: none; }}
.gmail-row:hover {{ background: #161616; }}
.gmail-dot {{
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: #c9a84c;
    flex-shrink: 0;
}}
.gmail-sender {{
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    color: #888;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.gmail-subject {{
    font-size: 0.8rem;
    color: #aaa8a0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.gmail-time {{
    font-family: 'DM Mono', monospace;
    font-size: 0.58rem;
    color: #444;
    white-space: nowrap;
    text-align: right;
}}

/* ── Mobile ───────────────────────────────────────────────── */
@media (max-width: 768px) {{
    body {{
        padding: 1rem 1rem;
    }}
    .masthead {{
        flex-direction: column;
        gap: 0.4rem;
        padding: 1rem 0 0.8rem;
    }}
    .masthead-title {{
        font-size: 2rem;
    }}
    .masthead-meta {{
        text-align: left;
        font-size: 0.62rem;
        line-height: 1.6;
    }}
    .drive-grid {{ grid-template-columns: 1fr; }}
    .drive-time {{ font-size: 2.2rem; }}
    .gmail-row {{ grid-template-columns: 12px 1fr auto; }}
    .gmail-sender {{ display: none; }}
    .weather-treemap {{ grid-template-columns: repeat(2, 1fr); }}
    .cols-2, .cols-3, .cols-4 {{
        grid-template-columns: 1fr;
    }}
    .summary-grid {{ grid-template-columns: 1fr 1fr; gap: 1rem; row-gap: 1.2rem; }}
    .portfolio-treemap {{ gap: 0.3rem; }}
    .ptile {{ min-height: 120px; padding: 0.8rem; }}
    .ptile-price {{ font-size: 1.3rem; }}
    .pills-bar {{
        gap: 0.4rem;
        margin-bottom: 1.2rem;
        padding-bottom: 1rem;
    }}
    .pill {{
        font-size: 0.6rem;
        padding: 0.3rem 0.7rem;
    }}
    .section-label {{
        font-size: 0.6rem;
    }}
    .headline-item a {{
        font-size: 0.82rem;
    }}
}}

@media (max-width: 480px) {{
    body {{
        padding: 0.75rem;
    }}
    .masthead-title {{
        font-size: 1.7rem;
    }}
    .summary-grid {{ grid-template-columns: 1fr; row-gap: 1.2rem; }}
    .weather-treemap {{ grid-template-columns: repeat(2, 1fr); }}
    .ptile-price {{ font-size: 1.1rem; }}
    .wtile-temp {{ font-size: 1.6rem; }}
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

{summary_section}

{drive_section}

{gmail_section}

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

components.html(html, height=18000, scrolling=True)
