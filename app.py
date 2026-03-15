import os
import re
import math
import json
import html
import hashlib
import concurrent.futures as cf
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import trafilatura
import yfinance as yf
from dateutil import parser as dtparser
from nltk.tokenize import sent_tokenize
from streamlit_autorefresh import st_autorefresh

# --- NLTK bootstrap ---
import nltk
nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

# =========================
# PAGE CONFIG & STYLE
# =========================
st.set_page_config(
    page_title="War Pulse Live | Iran • Israel • U.S.",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {font-family:'Inter',sans-serif;}
.stApp {
    background:
        radial-gradient(circle at top left, rgba(56,189,248,0.12), transparent 32%),
        radial-gradient(circle at top right, rgba(248,113,113,0.10), transparent 28%),
        linear-gradient(180deg, #07111d 0%, #0b1220 45%, #0f172a 100%);
    color: #e5edf8;
}
.block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
.hero {
    padding: 1.25rem 1.4rem;
    border: 1px solid rgba(148,163,184,0.18);
    background: linear-gradient(135deg, rgba(15,23,42,0.92), rgba(2,6,23,0.76));
    border-radius: 22px;
    box-shadow: 0 18px 60px rgba(0,0,0,0.28);
    margin-bottom: 1rem;
}
.kpi-card, .glass-card {
    background: linear-gradient(180deg, rgba(15,23,42,0.88), rgba(15,23,42,0.74));
    border: 1px solid rgba(148,163,184,0.16);
    border-radius: 20px;
    padding: 1rem 1rem;
    box-shadow: 0 12px 36px rgba(0,0,0,0.20);
}
.kpi-title {font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;}
.kpi-value {font-size: 2rem; font-weight: 800; color: #f8fafc; line-height: 1.1; margin-top: 0.35rem;}
.kpi-sub {font-size: 0.80rem; color: #cbd5e1; margin-top: 0.35rem;}
.live-pill {
    display:inline-flex; align-items:center; gap:8px; padding:6px 12px;
    border-radius:999px; background:rgba(239,68,68,0.14); color:#fecaca; font-weight:700; font-size:0.82rem;
    border:1px solid rgba(239,68,68,0.26);
}
.live-dot {width:9px; height:9px; border-radius:50%; background:#ef4444; box-shadow:0 0 0 0 rgba(239,68,68,0.8); animation:pulse 1.7s infinite;}
@keyframes pulse {0%{box-shadow:0 0 0 0 rgba(239,68,68,0.85);} 70%{box-shadow:0 0 0 12px rgba(239,68,68,0);} 100%{box-shadow:0 0 0 0 rgba(239,68,68,0);}}
.story-card {
    padding: 0.85rem 0.95rem; border-radius: 16px; margin-bottom: 0.75rem;
    background: linear-gradient(180deg, rgba(15,23,42,0.86), rgba(2,6,23,0.72));
    border:1px solid rgba(148,163,184,0.15);
}
.story-card a {color:#f8fafc !important; text-decoration:none;}
.small-muted {color:#94a3b8; font-size:0.82rem;}
.section-title {font-size:1.06rem; font-weight:800; color:#f8fafc; margin-bottom:0.6rem;}
.metric-split {display:flex; justify-content:space-between; gap:10px; padding:10px 0; border-bottom:1px solid rgba(148,163,184,0.10);} 
.metric-split:last-child {border-bottom:none;}
</style>
""", unsafe_allow_html=True)

# =========================
# GEOMETRIC COORDINATE PARSER
# =========================
class GeometricExtractor:
    def __init__(self):
        self.num_pattern = re.compile(r'(?:\$)?\s*([\d\,\.]+)\s*(million|billion|trillion|m|b|t)?(?:\s*dollars|\s*usd)?\b', re.IGNORECASE)
        
    def _clean_num(self, val_str, multiplier):
        try:
            val = float(val_str.replace(',', ''))
            mult = (multiplier or '').lower()
            if mult in ['billion', 'b']: return val * 1000
            if mult in ['trillion', 't']: return val * 1000000
            if mult in ['million', 'm']: return val
            if val > 1000000: return val / 1000000 # Assume raw dollars > 1M
            return val
        except: return 0

    def extract(self, text):
        data = {
            "US": {"casualties": 0, "missiles": 0, "drones": 0, "loss_m": 0},
            "Israel": {"casualties": 0, "missiles": 0, "drones": 0, "loss_m": 0},
            "Iran": {"casualties": 0, "missiles": 0, "drones": 0, "loss_m": 0},
            "Global": {"casualties": 0, "missiles": 0, "drones": 0, "loss_m": 0}
        }

        for sent in sent_tokenize(text.lower()):
            nums = [(m.group(0), m.start(), m.group(1), m.group(2)) for m in self.num_pattern.finditer(sent)]
            if not nums: continue

            # Metric Coordinates
            cas_spans = [m.start() for m in re.finditer(r'\b(dead|killed|casualt|fatalit|lives|soldiers|troops)\b', sent)]
            mis_spans = [m.start() for m in re.finditer(r'\b(missile|rocket|projectile)\b', sent)]
            dro_spans = [m.start() for m in re.finditer(r'\b(drone|uav|kamikaze)\b', sent)]
            loss_spans = [m.start() for m in re.finditer(r'\b(damage|loss|cost|destroy|economic|worth)\b', sent)]

            # Faction Coordinates
            iran_spans = [m.start() for m in re.finditer(r'\b(iran|tehran|isfahan|hezbollah|houthi|gaza|palestin)\b', sent)]
            isr_spans = [m.start() for m in re.finditer(r'\b(israel|tel aviv|idf|jerusalem)\b', sent)]
            us_spans = [m.start() for m in re.finditer(r'\b(us|usa|american|us base)\b', sent)]

            for raw_str, num_pos, val_str, mult in nums:
                val = self._clean_num(val_str, mult)
                if val == 0 or (val > 100000 and '$' not in raw_str and not mult): continue

                metric = None
                if '$' in raw_str or 'usd' in raw_str or 'dollar' in raw_str:
                    metric = "loss_m"
                else:
                    min_dist = 100 
                    for m_type, spans in [("casualties", cas_spans), ("missiles", mis_spans), ("drones", dro_spans), ("loss_m", loss_spans)]:
                        for s in spans:
                            dist = abs(num_pos - s)
                            if dist < min_dist:
                                min_dist, metric = dist, m_type

                if not metric: continue 

                faction = "Global"
                f_min_dist = 120
                for f_type, spans in [("Iran", iran_spans), ("Israel", isr_spans), ("US", us_spans)]:
                    for s in spans:
                        dist = abs(num_pos - s)
                        if dist < f_min_dist:
                            f_min_dist, faction = dist, f_type

                # Use Max to prevent double counting within the same article
                data["Global"][metric] = max(data["Global"][metric], val)
                if faction != "Global":
                    data[faction][metric] = max(data[faction][metric], val)

        return data

# =========================
# SCRAPERS & AGGREGATORS
# =========================
def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    return re.sub(r"\s+", " ", text).strip()

def safe_parse_date(value):
    try: return dtparser.parse(value)
    except: return datetime.now(UTC)

def fetch_rss_articles(limit=50) -> list[dict]:
    feeds = [
        "https://news.google.com/rss/search?q=Israel+Iran+US+conflict+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Israel+Iran+war+death+toll+OR+casualties&hl=en-US&gl=US&ceid=US:en",
        "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml"
    ]
    out, seen = [], set()
    for url in feeds:
        try:
            parsed = feedparser.parse(url)
            for e in parsed.entries[:limit]:
                link = (e.get("link") or "").split("?")[0]
                if link and link not in seen:
                    seen.add(link)
                    out.append({
                        "title": clean_text(e.get("title", "")),
                        "url": link,
                        "source": e.get("source", {}).get("title", "News Feed"),
                        "datetime": safe_parse_date(e.get("published") or e.get("updated")),
                        "summary": clean_text(e.get("summary", ""))
                    })
        except: pass
    return out

def hydrate_article(article: dict, fetch_full: bool) -> dict:
    text = f"{article.get('title','')}. {article.get('summary','')}"
    if fetch_full:
        try:
            dl = trafilatura.fetch_url(article["url"], timeout=5)
            if dl: text += " " + (trafilatura.extract(dl) or "")[:6000]
        except: pass
    
    content = clean_text(text)
    article["text"] = content
    article["hash"] = hashlib.md5(content.encode()).hexdigest()[:12]
    article["day"] = article["datetime"].astimezone(IST).date()
    return article

@st.cache_data(ttl=300, show_spinner=False)
def build_live_dataset(max_articles: int, fetch_full: bool):
    raw_articles = fetch_rss_articles(max_articles)[:max_articles]
    
    hydrated = []
    with cf.ThreadPoolExecutor(max_workers=15) as ex:
        futs = [ex.submit(hydrate_article, item, fetch_full) for item in raw_articles]
        for fut in cf.as_completed(futs):
            try: hydrated.append(fut.result())
            except: pass

    df = pd.DataFrame(hydrated)
    if df.empty: return df

    df = df.drop_duplicates(subset=["hash"]).sort_values("datetime", ascending=False)
    
    # Apply Geometric Parser
    extractor = GeometricExtractor()
    parsed = [extractor.extract(text) for text in df["text"]]
    
    # Flatten Data
    for metric in ["casualties", "missiles", "drones", "loss_m"]:
        for faction in ["US", "Israel", "Iran", "Global"]:
            df[f"{faction}_{metric}"] = [d[faction][metric] for d in parsed]

    return df

@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_snapshot():
    tickers = {"Brent": "BZ=F", "Gold": "GC=F", "S&P 500": "^GSPC", "VIX (Fear)": "^VIX"}
    rows = []
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d", interval="1d")
            if len(hist) >= 2:
                last, prev = float(hist["Close"].iloc[-1]), float(hist["Close"].iloc[-2])
                delta = (last - prev) / prev * 100
                rows.append({"name": name, "last": last, "delta_pct": delta})
        except: pass
    return rows

def format_money_m(val_m: float) -> str:
    if val_m == 0: return "$0"
    if val_m >= 1000: return f"${val_m/1000:,.1f}B"
    if val_m < 1: return f"${val_m*1000:,.0f}K"
    return f"${val_m:,.0f}M"

# =========================
# DASHBOARD RENDERING
# =========================
with st.sidebar:
    st.markdown("### Control Tower")
    max_articles = st.slider("Live article cap", 60, 400, 200, step=20)
    fetch_full = st.toggle("Fetch full article text", value=True)
    if st.button("Force live rebuild", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Executing Geometric Coordinate Parsing on Live Data..."):
    df = build_live_dataset(max_articles, fetch_full)

if df.empty:
    st.error("No live coverage could be fetched right now.")
    st.stop()

# --- AGGREGATIONS (Global Maxima Consensus) ---
k_cas = df["Global_casualties"].max()
k_mis = df["Global_missiles"].max()
k_dro = df["Global_drones"].max()
k_loss = df["Global_loss_m"].max()

last_refresh = datetime.now(IST).strftime("%d %b %Y • %H:%M IST")

st.markdown(f"""
<div class="hero">
  <div style="display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap;">
    <div>
      <div class="small-muted" style="font-weight:800; letter-spacing:0.08em; text-transform:uppercase;">Live Conflict Intelligence Dashboard</div>
      <div style="font-size:2.0rem; font-weight:800; line-height:1.08; margin-top:6px;">War Pulse Live: Iran • Israel • U.S.</div>
      <div class="small-muted" style="margin-top:8px; max-width:920px;">Powered by Geometric Coordinate Parsing. Extracts precise attribution by mapping numerical proximity to faction and metric keywords.</div>
    </div>
    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:10px;">
      <div class="live-pill"><span class="live-dot"></span>LIVE INTEL</div>
      <div class="small-muted">Last refresh: {last_refresh}</div>
      <div class="small-muted">Signals Processed: {len(df):,}</div>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# --- KPI ROW ---
k1, k2, k3, k4, k5 = st.columns(5)
kpis = [
    (k1, "Projectiles Fired", f"{int(k_mis + k_dro):,}", "Missiles + Drones"),
    (k2, "Global Casualties", f"{int(k_cas):,}", "Max Reported Toll"),
    (k3, "Economic Loss ($)", format_money_m(k_loss), "Infrastructure Damage"),
    (k4, "Intel Signals", f"{len(df):,}", "Processed Links"),
    (k5, "System Status", "LIVE", f"Auto-Sync Active")
]
for col, title, val, sub in kpis:
    col.markdown(f"<div class='kpi-card'><div class='kpi-title'>{title}</div><div class='kpi-value'>{val}</div><div class='kpi-sub'>{sub}</div></div>", unsafe_allow_html=True)

st.write("")

# --- MAIN GRID ---
left, right = st.columns([1.7, 1.05], gap="large")

with left:
    st.markdown("<div class='section-title'>Kinetic trendline (Cumulative Media Consensus)</div>", unsafe_allow_html=True)
    
    # Calculate daily cumulative maximums to build the timeline
    daily = df.groupby("day").agg({
        "Global_casualties": "max", "US_missiles": "max", "Israel_missiles": "max", "Iran_missiles": "max"
    }).reset_index().sort_values("day")
    
    for c in ["Global_casualties", "US_missiles", "Israel_missiles", "Iran_missiles"]:
        daily[c] = daily[c].cummax()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily["day"], y=daily["Iran_missiles"], mode="lines+markers", name="Iran Missiles", line=dict(width=3, color="#ef4444")))
    fig.add_trace(go.Scatter(x=daily["day"], y=daily["Israel_missiles"], mode="lines+markers", name="Israel Missiles", line=dict(width=2, color="#60a5fa")))
    fig.add_trace(go.Scatter(x=daily["day"], y=daily["US_missiles"], mode="lines+markers", name="US Missiles", line=dict(width=2, color="#22c55e")))
    fig.add_trace(go.Scatter(x=daily["day"], y=daily["Global_casualties"], mode="lines", name="Casualties", line=dict(width=2, dash="dot", color="#cbd5e1"), yaxis="y2"))
    
    fig.update_layout(
        template="plotly_dark", height=420, margin=dict(l=8, r=8, t=8, b=8),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.30)",
        legend=dict(orientation="h", y=1.12), hovermode="x unified",
        yaxis=dict(title="Projectiles Fired"), yaxis2=dict(title="Casualties", overlaying="y", side="right")
    )
    st.plotly_chart(fig, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='section-title'>Attributed Projectile Mix</div>", unsafe_allow_html=True)
        proj_df = pd.DataFrame({
            "Actor": ["US", "Israel", "Iran"],
            "Missiles": [df["US_missiles"].max(), df["Israel_missiles"].max(), df["Iran_missiles"].max()],
            "Drones": [df["US_drones"].max(), df["Israel_drones"].max(), df["Iran_drones"].max()],
        }).melt(id_vars="Actor", var_name="Type", value_name="Count")
        
        fig2 = px.bar(proj_df, x="Actor", y="Count", color="Type", barmode="group", template="plotly_dark", height=320, color_discrete_sequence=["#ef4444", "#f59e0b"])
        fig2.update_layout(margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.30)")
        st.plotly_chart(fig2, use_container_width=True)

    with c2:
        st.markdown("<div class='section-title'>Attributed Casualties</div>", unsafe_allow_html=True)
        cas_df = pd.DataFrame({
            "Target": ["US", "Israel", "Iran"],
            "Casualties": [df["US_casualties"].max(), df["Israel_casualties"].max(), df["Iran_casualties"].max()]
        })
        fig3 = px.pie(cas_df, names="Target", values="Casualties", hole=0.58, template="plotly_dark", height=320, color="Target", color_discrete_map={"US":"#22c55e", "Israel":"#60a5fa", "Iran":"#ef4444"})
        fig3.update_layout(margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
        st.plotly_chart(fig3, use_container_width=True)

with right:
    st.markdown("<div class='section-title'>Resolved Scoreboard (Maxima)</div>", unsafe_allow_html=True)
    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
    
    scoreboard = [
        ("US", int(df["US_missiles"].max() + df["US_drones"].max()), int(df["US_casualties"].max()), format_money_m(df["US_loss_m"].max())),
        ("Israel", int(df["Israel_missiles"].max() + df["Israel_drones"].max()), int(df["Israel_casualties"].max()), format_money_m(df["Israel_loss_m"].max())),
        ("Iran", int(df["Iran_missiles"].max() + df["Iran_drones"].max()), int(df["Iran_casualties"].max()), format_money_m(df["Iran_loss_m"].max())),
        ("Global", int(k_mis + k_dro), int(k_cas), format_money_m(k_loss)),
    ]
    for name, proj, cas, loss in scoreboard:
        st.markdown(f"<div class='metric-split'><div><div style='font-weight:800; font-size:1rem'>{name}</div><div class='small-muted'>Projectiles / Casualties / Losses</div></div><div style='text-align:right'><div style='font-weight:800'>{proj:,} proj.</div><div class='small-muted'>{cas:,} casualties • {loss}</div></div></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='section-title' style='margin-top:1rem;'>Macro market shock</div>", unsafe_allow_html=True)
    for row in fetch_market_snapshot():
        st.metric(row["name"], f"{row['last']:,.2f}", f"{row['delta_pct']:+.2f}%")

    st.markdown("<div class='section-title' style='margin-top:1rem;'>Top Extracted Reports</div>", unsafe_allow_html=True)
    # Sort by the most catastrophic articles
    df['severity'] = df['Global_casualties'] + df['Global_missiles'] + (df['Global_loss_m'] / 5)
    for _, r in df[df['severity'] > 0].sort_values(by='severity', ascending=False).head(5).iterrows():
        tags = []
        if r['Global_casualties'] > 0: tags.append(f"⚠️ {int(r['Global_casualties']):,} Cas.")
        if r['Global_missiles'] > 0: tags.append(f"🚀 {int(r['Global_missiles']):,} Mis.")
        if r['Global_loss_m'] > 0: tags.append(f"💰 {format_money_m(r['Global_loss_m'])}")
        
        st.markdown(f"""
        <div class='story-card'>
          <a href='{r['url']}' target='_blank'>{r['title']}</a>
          <div class='small-muted' style='margin-top:4px;'>{r['source']} • {' | '.join(tags)}</div>
        </div>
        """, unsafe_allow_html=True)
