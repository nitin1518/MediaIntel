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
from nltk.tokenize import sent_tokenize
import concurrent.futures
from streamlit_autorefresh import st_autorefresh

# ================== NLTK + TIME SETUP ==================
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

IST = pytz.timezone('Asia/Kolkata')
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

st.set_page_config(page_title="Global Threat Matrix: Kinetic", page_icon="🌍", layout="wide")

# ================== HIGH-END CSS ==================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.main { background: #0d1117; color: #c9d1d9; }
.stApp > header { background: #0d1117 !important; }
h1, h2, h3 { color: #ffffff; font-weight: 700; letter-spacing: -0.5px; }
.metric-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; text-align: center; }
.metric-title { font-size: 0.80rem; color: #8b949e; text-transform: uppercase; font-weight: 600; margin-bottom: 5px;}
.metric-value { font-size: 1.8rem; font-weight: bold; color: #ffffff; }
.live-dot { height: 10px; width: 10px; background-color: #ff7b72; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; margin-right: 8px; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
</style>
""", unsafe_allow_html=True)

# ================== ENHANCED KINETIC EXTRACTOR ==================
class KineticExtractor:
    def __init__(self):
        self.patterns = {
            "missiles": re.compile(r'(?:fired|launched|struck with|at least|over)\s+(\d{1,4})\s+(?:ballistic\s+)?missiles?', re.IGNORECASE),
            "drones": re.compile(r'(?:launched|deployed|sent)\s+(\d{1,4})\s+(?:attack\s+)?drones?', re.IGNORECASE),
            "casualties": re.compile(r'(?:killed|dead|fatalities|casualties|at least|over)\s+(\d{1,5})\s+(?:people|civilians|soldiers)?', re.IGNORECASE),
            "intercepted": re.compile(r'(?:intercepted|shot down|destroyed)\s+(\d{1,4})\s+(?:missiles?|drones?)', re.IGNORECASE)
        }

    def extract_metrics(self, text):
        data = {"missiles": 0, "drones": 0, "casualties": 0, "intercepted": 0}
        for key, regex in self.patterns.items():
            matches = regex.findall(text)
            data[key] = sum(int(m) for m in matches) if matches else 0
        return data

# ================== MULTI-SOURCE SCRAPER (MORE RELIABLE FEEDS) ==================
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
        "title": entry.title, "url": link, "source": entry.get('source', {}).get('title', 'Verified'),
        "date": pub.date(), "datetime": pub, "text": text[:3800],
        "hash": hashlib.md5(text.encode()).hexdigest()[:12]
    }

@st.cache_data(ttl=300)
def fetch_tier1_news(max_articles, fetch_full):
    feeds = [
        "https://feeds.reuters.com/reuters/topNews",
        "https://feeds.reuters.com/reuters/worldNews",
        "http://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.apnews.com/rss/apf-topnews",
        "https://www.timesofisrael.com/feed/",
        "https://www.cnn.com/services/rss/cnn_world.rss",
        "https://www.haaretz.com/israel-news/rss",          # Middle East focused
        "https://feeds.bloomberg.com/markets/news.rss",
        # Targeted Google News for maximum coverage
        "https://news.google.com/rss/search?q=Israel+Iran+US+missile+strike+when:2d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Iran+attack+casualties+missiles+drones&hl=en-US&gl=US&ceid=US:en"
    ]

    raw_entries = []
    seen = set()
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_articles]:
                link = entry.link.split("?")[0]
                if link not in seen and any(k in (entry.title + entry.get('summary', '')).lower() for k in ['iran','israel','missile','drone','strike','casualty','hezbollah','gaza']):
                    seen.add(link)
                    raw_entries.append(entry)
        except: continue

    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(fetch_single_article, e, fetch_full) for e in raw_entries[:max_articles]]
        for f in concurrent.futures.as_completed(futures):
            try: articles.append(f.result())
            except: pass

    df = pd.DataFrame(articles)
    if df.empty: return df
    df = df.drop_duplicates(subset="hash").sort_values("datetime", ascending=False).head(max_articles)

    # ================== ANALYZE ==================
    analyzer = SentimentIntensityAnalyzer()
    kinetic = KineticExtractor()

    results = []
    for text in df["text"]:
        sent = analyzer.polarity_scores(text)["compound"]
        k = kinetic.extract_metrics(text)
        results.append((sent, k["missiles"], k["drones"], k["casualties"], k["intercepted"]))

    df["sentiment"] = [r[0] for r in results]
    df["reported_missiles"] = [r[1] for r in results]
    df["reported_drones"] = [r[2] for r in results]
    df["reported_casualties"] = [r[3] for r in results]
    df["reported_intercepted"] = [r[4] for r in results]
    return df

# ================== DASHBOARD ==================
st.markdown("<h2 style='text-align: center;'>🌍 TACTICAL THREAT MATRIX & KINETIC TRACKER</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #8b949e;'>Real-Time Geopolitical & Market Sensing Engine • Enhanced Sources 2026</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Intel Controls")
    max_articles = st.slider("Signal Volume", 50, 300, 180, step=10)
    if st.button("🔄 Force Full Sync", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Fetching from Reuters • AP • Times of Israel • Haaretz • BBC • Al Jazeera + more..."):
    df = fetch_tier1_news(max_articles, True)
    has_data = not df.empty

if not has_data:
    st.error("No signals received. Try Force Sync or wait 5 minutes.")
    st.stop()

# ================== DAILY + CUMULATIVE AGGREGATION ==================
daily = df.groupby("date").agg({
    "reported_missiles": "max",
    "reported_drones": "max",
    "reported_casualties": "max",
    "reported_intercepted": "max",
    "sentiment": "mean"
}).reset_index()

daily["cum_missiles"] = daily["reported_missiles"].cumsum()
daily["cum_drones"] = daily["reported_drones"].cumsum()
daily["cum_casualties"] = daily["reported_casualties"].cumsum()
daily["cum_intercepted"] = daily["reported_intercepted"].cumsum()

total_m = daily["reported_missiles"].sum()
total_d = daily["reported_drones"].sum()
total_c = daily["reported_casualties"].sum()
total_i = daily["reported_intercepted"].sum()

# ================== MACRO KPIs ==================
cols = st.columns(6)
cols[0].markdown(f'<div class="metric-card"><div class="metric-title">Signals</div><div class="metric-value">{len(df)}</div></div>', unsafe_allow_html=True)
cols[1].markdown(f'<div class="metric-card"><div class="metric-title">Missiles (Est.)</div><div class="metric-value" style="color:#ff7b72;">{int(total_m):,}</div></div>', unsafe_allow_html=True)
cols[2].markdown(f'<div class="metric-card"><div class="metric-title">Drones (Est.)</div><div class="metric-value" style="color:#d29922;">{int(total_d):,}</div></div>', unsafe_allow_html=True)
cols[3].markdown(f'<div class="metric-card"><div class="metric-title">Intercepted</div><div class="metric-value" style="color:#3fb950;">{int(total_i):,}</div></div>', unsafe_allow_html=True)
cols[4].markdown(f'<div class="metric-card"><div class="metric-title">Casualties (Est.)</div><div class="metric-value" style="color:#8b949e;">{int(total_c):,}</div></div>', unsafe_allow_html=True)
cols[5].markdown(f'<div class="metric-card"><div class="metric-title">Status</div><div class="metric-value" style="font-size:1.2rem;"><span class="live-dot"></span>LIVE<br><small>{datetime.now(IST).strftime("%H:%M IST")}</small></div></div>', unsafe_allow_html=True)

st.write("---")

# ================== CHARTS (PROFESSIONAL) ==================
left, right = st.columns([2, 1], gap="large")

with left:
    st.subheader("🔥 Cumulative Kinetic Escalation Trend")
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_missiles"], name="Missiles", line=dict(color="#ff7b72", width=3)))
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_drones"], name="Drones", line=dict(color="#d29922", width=3)))
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_intercepted"], name="Intercepted", line=dict(color="#3fb950", width=3)))
    fig_cum.add_trace(go.Scatter(x=daily["date"], y=daily["cum_casualties"], name="Casualties", line=dict(color="#8b949e", width=3), yaxis="y2"))
    fig_cum.update_layout(
        template="plotly_dark", height=420,
        yaxis=dict(title="Projectiles"),
        yaxis2=dict(title="Casualties", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.02)
    )
    st.plotly_chart(fig_cum, use_container_width=True)

    st.subheader("Daily Escalation Volume")
    fig_daily = px.bar(daily, x="date", y=["reported_missiles", "reported_drones", "reported_intercepted"],
                       title="Daily Maximum Reported", barmode="group",
                       color_discrete_map={"reported_missiles":"#ff7b72", "reported_drones":"#d29922", "reported_intercepted":"#3fb950"})
    st.plotly_chart(fig_daily, use_container_width=True)

with right:
    st.subheader("Secondary Actors")
    text = " ".join(df["text"]).lower()
    entities = {"Russia": "russia", "China": "china", "Turkey": "turkey", "Saudi": "saudi",
                "Lebanon": "lebanon", "Syria": "syria", "Hezbollah": "hezbollah", "Houthis": "houthi"}
    counts = {k: len(re.findall(v, text)) for k, v in entities.items()}
    ent_df = pd.Series(counts).sort_values(ascending=False).head(8).to_frame("Mentions")
    fig_ent = px.bar(ent_df, x="Mentions", y=ent_df.index, orientation='h', template="plotly_dark", color="Mentions")
    st.plotly_chart(fig_ent, use_container_width=True)

    st.subheader("Market Shock")
    for name, tick in [("Brent Crude", "BZ=F"), ("S&P 500", "^GSPC"), ("Gold", "GC=F")]:
        try:
            h = yf.Ticker(tick).history(period="7d")
            if len(h) >= 2:
                last = h["Close"].iloc[-1]
                delta = ((last - h["Close"].iloc[-2]) / h["Close"].iloc[-2]) * 100
                st.metric(name, f"${last:,.2f}" if "Gold" in name or "Crude" in name else f"{int(last):,}", f"{delta:+.1f}%")
        except: st.caption(f"{name} offline")

# ================== RAW FEED ==================
st.subheader("📡 Kinetic Signals Feed")
for _, r in df[df["reported_missiles"] + df["reported_casualties"] > 0].head(8).iterrows():
    tags = []
    if r["reported_missiles"] > 0: tags.append(f"🚀 {r['reported_missiles']} Missiles")
    if r["reported_drones"] > 0: tags.append(f"🛸 {r['reported_drones']} Drones")
    if r["reported_intercepted"] > 0: tags.append(f"🛡️ {r['reported_intercepted']} Intercepted")
    if r["reported_casualties"] > 0: tags.append(f"⚠️ {r['reported_casualties']} Casualties")
    st.markdown(f"""
    <div style='background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px;margin-bottom:10px;'>
        <a href='{r['url']}' target='_blank' style='color:#58a6ff;font-weight:600;'>{r['title']}</a><br>
        <small>{r['source']} • {r['datetime'].strftime('%H:%M IST')}</small><br>
        <span style='color:#ff7b72;font-size:0.9rem;'><b>{' | '.join(tags)}</b></span>
    </div>
    """, unsafe_allow_html=True)

st.caption("Enhanced with Reuters, AP, Times of Israel, Haaretz + 7 more Tier-1 sources • All estimations based on media consensus • Not official counts")
