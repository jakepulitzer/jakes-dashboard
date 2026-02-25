import streamlit as st
import streamlit.components.v1 as components
import requests
import xml.etree.ElementTree as ET
from datetime import datetime

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

# ── Fetch Headlines ───────────────────────────────────────────
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

# ── Helpers ───────────────────────────────────────────────────
now = datetime.now()

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
        headlines = get_headlines(url)
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
pills_html = '<div class="pills-bar"><span class="pill active" onclick="filterSection(\'all\', this)">✦ All</span>'
for category in FEEDS.keys():
    sid = section_id(category)
    pills_html += f'<span class="pill" onclick="filterSection(\'{sid}\', this)">{category}</span>'
pills_html += '</div>'

# ── Build Sections ────────────────────────────────────────────
sections_html = ""
for category, sources in FEEDS.items():
    sections_html += build_section(category, sources)

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
