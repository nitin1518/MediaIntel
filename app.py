import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz
import feedparser
from dateutil import parser
import trafilatura
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import yfinance as yf
import hashlib
import nltk
import os
import re
import concurrent.futures
from streamlit_autorefresh import st_autorefresh

# ────────────────────────────────────────────────
# NLTK + Time Setup
# ────────────────────────────────────────────────
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Global Threat Matrix: Kinetic", page_icon="🌍", layout="wide")
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

# ────────────────────────────────────────────────
# Professional Dark Theme
# ────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.main { background: #0d1117; color: #c9d1d9; }
.stApp > header { background: #0d1117 !important; }
h1, h2, h3 { color: #ffffff; font-weight: 700; letter-spacing: -0.5px; }
.metric-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; text-align: center; margin-bottom: 12px; }
.metric-title { font-size: 0.82rem; color: #8b949e; text-transform: uppercase; font-weight: 600; margin-bottom: 6px; }
.metric-value { font-size: 1.9rem; font-weight: bold; color: #ffffff; }
.live-dot { height: 10px; width: 10px; background-color: #ff7b72; border-radius: 50%; display: inline-block; animation: pulse 1.6s infinite; margin-right: 8px; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.35; } 100% { opacity: 1; } }
hr { border-color: #30363d; margin: 1.6rem 0; }
</style>
""", unsafe_allow_html=True)

# ────────────────────────────────────────────────
# BROADENED Kinetic Extractor (catches real 2026 phrasing)
# ────────────────────────────────────────────────
class KineticExtractor:
    def __init__(self):
        self.patterns = {
            # Missiles - catches "fired 285 ballistic missiles", "barrage of 400 missiles", "over 300 missiles launched", etc.
            "missiles": re.compile(
                r'(?:fired|launched|detonated|barrage of|sent|targeted|reported|estimated|at least|more than|over|hundreds?|dozens?)\s*(\d{1,6})\s*(?:ballistic|cruise|hypersonic)?\s*missiles?',
                re.IGNORECASE | re.DOTALL),

            # Drones - catches "1,567 drones", "swarm of Shahed drones", "hundreds of attack drones", etc.
            "drones": re.compile(
                r'(?:launched|sent|fired|deployed|swarm of|hundreds?|dozens?)\s*(\d{1,6})\s*(?:attack|kamikaze|suicide|shahed|one-way)?\s*drones?',
                re.IGNORECASE | re.DOTALL),

            # Casualties - very broad (death toll, killed, dead, fatalities, etc.)
            "casualties": re.compile(
                r'(?i)(?:death toll|killed|dead|fatalit(?:ies|y)|died|perished|slain|casualt(?:ies|y)|bodies|victims?)\s*(?:has|stands at|rises to|climbs to|now|at|reaches|exceeds|surpasses|of)?\s*'
                r'(?:at least|more than|over|nearly|around|about|approximately)?\s*(\d{1,6})(?:\s*(?:people|civilians|soldiers|militants|personnel|troops|women|children|individuals)?)?'
                r'(?:\s*(?:and|plus|including)?\s*(?:at least|more than|over)?\s*(\d{1,6})\s*(?:wounded|injured|hurt))?)',
                re.IGNORECASE | re.DOTALL),

            # Intercepted - catches "intercepted 233 missiles", "shot down 1,359 drones", "air defenses downed 250 projectiles", etc.
            "intercepted": re.compile(
                r'(?:intercepted|shot down|destroyed|neutralized|downed|engaged|taken out|air defenses downed)\s*(\d{1,6})\s*(?:incoming\s*)?(?:ballistic|cruise|missiles?|drones?|projectiles?)',
                re.IGNORECASE | re.DOTALL)
        }

    def extract_metrics(self, text):
        data = {"missiles": 0, "drones": 0, "casualties": 0, "intercepted": 0}
        for key, regex in self.patterns.items():
            matches = regex.finditer(text)
            total = 0
            for m in matches:
                for group in m.groups():
                    if group:
                        total += int(group)
            data[key] = total
        return data

# ────────────────────────────────────────────────
# Rest of the code (unchanged except minor cleanups)
# ────────────────────────────────────────────────
def fetch_single_article(entry, fetch_full):
    link = entry.link.split("?")[0]
    pub = parser.parse(entry.published) if 'published' in entry else datetime.now(IST)
    text = f"{entry.title}. {entry.get('summary', '')}"
    if fetch_full:
        try:
            dl = trafilatura.fetch_url(link, timeout=5)
            if dl: text += " " + (trafilatura.extract(dl) or "")[:2800]
        except: pass
    return {
        "title": entry.title, "url": link, "source": entry.get('source', {}).get('title', 'News'),
        "date": pub.date(), "datetime": pub, "text": text[:3800],
        "hash": hashlib.md5(text.encode()).hexdigest()[:12]
    }

@st.cache_data(ttl=300)
def fetch_tier1_news(max_articles, fetch_full):
    feeds = [
        "https://feeds.reuters.com/reuters/topNews", "https://feeds.reuters.com/reuters/worldNews",
        "http://feeds.bbci.co.uk/news/world/rss.xml", "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.apnews.com/rss/apf-topnews", "https://www.timesofisrael.com/feed/",
        "https://www.cnn.com/services/rss/cnn_world.rss", "https://www.haaretz.com/israel-news/rss",
        "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
        "https://news.google.com/rss/search?q=Israel+Iran+US+missile+strike+OR+drone+OR+attack+when:7d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Iran+OR+Israel+casualties+OR+killed+OR+dead+OR+wounded+when:7d&hl=en-US&gl=US&ceid=US:en"
    ]

    raw_entries = []
    seen = set()
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_articles*2]:
                link = entry.link.split("?")[0]
                combined = (entry.title + entry.get('summary', '')).lower()
                if link not in seen and any(k in combined for k in ['iran','israel','missile','drone','strike','hezbollah','gaza','casualty','killed','dead']):
                    seen.add(link)
                    raw_entries.append(entry)
        except: continue

    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(fetch_single_article, e, fetch_full) for e in raw_entries]
        for future in concurrent.futures.as_completed(futures):
            try: articles.append(future.result())
            except: pass

    if not articles: return pd.DataFrame()

    df = pd.DataFrame(articles)
    df = df.drop_duplicates(subset="hash").sort_values("datetime", ascending=False).head(max_articles)

    analyzer = SentimentIntensityAnalyzer()
    extractor = KineticExtractor()

    results = []
    for text in df["text"]:
        sent = analyzer.polarity_scores(text)["compound"]
        k = extractor.extract_metrics(text)
        results.append((sent, k["missiles"], k["drones"], k["casualties"], k["intercepted"]))

    df["sentiment"] = [r[0] for r in results]
    df["reported_missiles"] = [r[1] for r in results]
    df["reported_drones"] = [r[2] for r in results]
    df["reported_casualties"] = [r[3] for r in results]
    df["reported_intercepted"] = [r[4] for r in results]
    return df

# ────────────────────────────────────────────────
# UI
# ────────────────────────────────────────────────
st.markdown("<h2 style='text-align: center;'>🌍 TACTICAL THREAT MATRIX & KINETIC TRACKER</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #8b949e;'>Real-Time Geopolitical & Market Sensing • Multi-Source 2026</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Controls")
    max_articles = st.slider("Max articles", 50, 300, 180, step=10)
    fetch_full = st.checkbox("Extract full article text", value=True)
    if st.button("🔄 Force Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Collecting from Reuters • AP • BBC • Al Jazeera • Times of Israel • Haaretz • Jerusalem Post + Google News…"):
    df = fetch_tier1_news(max_articles, fetch_full)

if df.empty:
    st.error("No recent relevant articles found. Try Force Refresh.")
    st.stop()

# Daily aggregation
daily = df.groupby("date").agg({
    "reported_missiles": "max", "reported_drones": "max",
    "reported_casualties": "max", "reported_intercepted": "max"
}).reset_index()

daily["cum_missiles"] = daily["reported_missiles"].cumsum()
daily["cum_drones"] = daily["reported_drones"].cumsum()
daily["cum_casualties"] = daily["reported_casualties"].cumsum()
daily["cum_intercepted"] = daily["reported_intercepted"].cumsum()

tot_m = daily["reported_missiles"].sum()
tot_d = daily["reported_drones"].sum()
tot_c = daily["reported_casualties"].sum()
tot_i = daily["reported_intercepted"].sum()

# KPIs
cols = st.columns(6)
cols[0].markdown(f'<div class="metric-card"><div class="metric-title">Signals</div><div class="metric-value">{len(df)}</div></div>', unsafe_allow_html=True)
cols[1].markdown(f'<div class="metric-card"><div class="metric-title">Missiles (Est.)</div><div class="metric-value" style="color:#ff7b72;">{int(tot_m):,}</div></div>', unsafe_allow_html=True)
cols[2].markdown(f'<div class="metric-card"><div class="metric-title">Drones (Est.)</div><div class="metric-value" style="color:#d29922;">{int(tot_d):,}</div></div>', unsafe_allow_html=True)
cols[3].markdown(f'<div class="metric-card"><div class="metric-title">Intercepted</div><div class="metric-value" style="color:#3fb950;">{int(tot_i):,}</div></div>', unsafe_allow_html=True)
cols[4].markdown(f'<div class="metric-card"><div class="metric-title">Casualties (Est.)</div><div class="metric-value" style="color:#8b949e;">{int(tot_c):,}</div></div>', unsafe_allow_html=True)
cols[5].markdown(f'<div class="metric-card"><div class="metric-title">Status</div><div class="metric-value" style="font-size:1.25rem;"><span class="live-dot"></span>LIVE<br><small>{datetime.now(IST).strftime("%H:%M IST")}</small></div></div>', unsafe_allow_html=True)

st.markdown("---")

left_col, right_col = st.columns([2, 1], gap="large")

with left_col:
    st.subheader("Cumulative Kinetic Trend")
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_missiles"], name="Missiles", line=dict(color="#ff7b72", width=3)))
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_drones"], name="Drones", line=dict(color="#d29922", width=3)))
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_intercepted"], name="Intercepted", line=dict(color="#3fb950", width=3)))
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_casualties"], name="Casualties", line=dict(color="#8b949e", width=3), yaxis="y2"))
    fig_cum.update_layout(template="plotly_dark", height=460, yaxis=dict(title="Projectiles"), yaxis2=dict(title="Casualties", overlaying="y", side="right"), legend=dict(orientation="h", y=1.02))
    st.plotly_chart(fig_cum, use_container_width=True)

    st.subheader("Daily Reported Maxima")
    fig_daily = px.bar(daily, x="date", y=["reported_missiles", "reported_drones", "reported_intercepted"], barmode="group", title="Daily Peak Numbers", template="plotly_dark")
    st.plotly_chart(fig_daily, use_container_width=True)

with right_col:
    st.subheader("Secondary Actors")
    text_all = " ".join(df["text"]).lower()
    actors = {"Russia":"russia","China":"china","Turkey":"turkey","Saudi":"saudi","Lebanon":"lebanon","Syria":"syria","Hezbollah":"hezbollah","Houthis":"houthi"}
    counts = {k: len(re.findall(v, text_all)) for k,v in actors.items()}
    actor_df = pd.Series(counts).sort_values(ascending=False).head(8).to_frame("Mentions")
    st.plotly_chart(px.bar(actor_df, x="Mentions", y=actor_df.index, orientation='h', template="plotly_dark"), use_container_width=True)

    st.subheader("Market Impact")
    for name, tick in [("Brent Crude","BZ=F"), ("S&P 500","^GSPC"), ("Gold","GC=F")]:
        try:
            h = yf.Ticker(tick).history(period="7d")
            if len(h) >= 2:
                last = h["Close"].iloc[-1]
                delta = ((last - h["Close"].iloc[-2]) / h["Close"].iloc[-2]) * 100
                val = f"${last:,.2f}" if "Crude" in name or "Gold" in name else f"{int(last):,}"
                st.metric(name, val, f"{delta:+.1f}%")
        except: st.caption(f"{name} offline")

st.markdown("---")
st.subheader("📡 Most Relevant Kinetic Reports")
for _, row in df.sort_values("datetime", ascending=False).head(12).iterrows():
    tags = []
    if row["reported_missiles"] > 0: tags.append(f"🚀 {row['reported_missiles']:,} Missiles")
    if row["reported_drones"] > 0: tags.append(f"🛸 {row['reported_drones']:,} Drones")
    if row["reported_intercepted"] > 0: tags.append(f"🛡️ {row['reported_intercepted']:,} Intercepted")
    if row["reported_casualties"] > 0: tags.append(f"⚠️ {row['reported_casualties']:,} Casualties")
    st.markdown(f"""
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:12px;">
        <a href="{row['url']}" target="_blank" style="color:#58a6ff;font-weight:600;">{row['title']}</a><br>
        <small style="color:#8b949e;">{row['source']} • {row['datetime'].strftime('%Y-%m-%d %H:%M IST')}</small><br>
        <span style="color:#ff7b72;font-size:0.92rem;font-weight:600;">{' • '.join(tags) if tags else 'No kinetic data extracted'}</span>
    </div>
    """, unsafe_allow_html=True)

st.caption("📌 All figures are highest reported values per day (media consensus) • Subject to revision • Sources include Reuters, AP, BBC, Al Jazeera, Times of Israel, Haaretz, Jerusalem Post, CNN, Google News")
