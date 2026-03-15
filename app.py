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

# --- NLTK CLOUD FIX ---
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Global Threat Matrix: Kinetic", page_icon="🌍", layout="wide")
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

# --- HIGH-END CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }
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

# --- 1. KINETIC EXTRACTION ENGINE (PURE PYTHON) ---
class KineticExtractor:
    def __init__(self):
        # Look for digits up to 4 length (1 to 9999) near specific kinetic words
        self.projectile_regex = re.compile(r'\b(\d{1,4})\s+(?:ballistic\s+|cruise\s+)?(missiles?|rockets?|drones?|projectiles?)\b', re.IGNORECASE)
        self.casualty_regex = re.compile(r'\b(\d{1,5})\s+(?:people\s+|civilians\s+|soldiers\s+)?(killed|dead|fatalities|casualties)\b', re.IGNORECASE)

    def extract_metrics(self, text):
        missiles_fired = 0
        drones_launched = 0
        casualties = 0
        
        # Projectiles
        for match in self.projectile_regex.findall(text):
            num = int(match[0])
            if 'drone' in match[1].lower(): drones_launched += num
            else: missiles_fired += num
                
        # Casualties
        for match in self.casualty_regex.findall(text):
            casualties += int(match[0])
            
        return {"missiles": missiles_fired, "drones": drones_launched, "casualties": casualties}

# --- 2. MULTITHREADED TIER-1 SCRAPER ---
def fetch_single_article(entry, fetch_full):
    link = entry.link.split("?")[0]
    pub = parser.parse(entry.published) if 'published' in entry else datetime.now(IST)
    text = f"{entry.title}. {entry.get('summary', '')}"
    
    if fetch_full:
        try:
            dl = trafilatura.fetch_url(link, timeout=4)
            if dl: text += " " + (trafilatura.extract(dl) or "")[:2500]
        except: pass
        
    return {
        "title": entry.title, "url": link, "source": entry.get('source', {}).get('title', 'Verified News'),
        "date": pub.date(), "datetime": pub, "text": text[:3500],
        "hash": hashlib.md5(text.encode()).hexdigest()[:12]
    }

@st.cache_data(ttl=300)
def fetch_tier1_news(max_articles, fetch_full):
    # Upgraded to Tier-1 Verified Sources
    feeds = [
        "https://news.google.com/rss/search?q=Israel+Iran+US+conflict+when:1d&hl=en-US&gl=US&ceid=US:en",
        "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml"
    ]

    raw_entries = []
    seen = set()
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_articles]:
                link = entry.link.split("?")[0]
                # Filter BBC/Al Jazeera for relevant Middle East keywords to avoid generic news
                if any(k in entry.title.lower() for k in ['iran', 'israel', 'us', 'tehran', 'strike', 'gaza', 'lebanon']):
                    if link not in seen:
                        seen.add(link)
                        raw_entries.append(entry)
        except: continue

    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = [executor.submit(fetch_single_article, entry, fetch_full) for entry in raw_entries[:max_articles]]
        for future in concurrent.futures.as_completed(futures):
            try: articles.append(future.result())
            except: pass

    df = pd.DataFrame(articles)
    if df.empty: return df

    df = df.drop_duplicates(subset="hash").sort_values("datetime", ascending=False)
    
    # Analyze Sentiment & Kinetic Data
    analyzer = SentimentIntensityAnalyzer()
    kinetic = KineticExtractor()
    
    sent_list, m_list, d_list, c_list = [], [], [], []
    for text in df["text"]:
        sent_list.append(analyzer.polarity_scores(text)["compound"])
        k_data = kinetic.extract_metrics(text)
        m_list.append(k_data["missiles"])
        d_list.append(k_data["drones"])
        c_list.append(k_data["casualties"])
        
    df["sentiment"] = sent_list
    df["reported_missiles"] = m_list
    df["reported_drones"] = d_list
    df["reported_casualties"] = c_list

    return df

# --- DASHBOARD RENDER ---
st.markdown("<h2 style='text-align: center;'>🌍 TACTICAL THREAT MATRIX & KINETIC TRACKER</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #8b949e;'>Real-Time Geopolitical & Market Sensing Engine</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Intel Constraints")
    max_articles = st.slider("Signal Volume (Max Links)", 50, 250, 150, step=50)
    if st.button("🔄 Force Data Sync", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Parsing Tier-1 News Feeds & Extracting Kinetic Data..."):
    df = fetch_tier1_news(max_articles, True)
    has_data = not df.empty

if not has_data:
    st.warning("⚠️ Telemetry Offline: Awaiting network sync.")
    st.stop()

# Consensus Algorithm: Prevent double counting by taking the daily MAX reported numbers
daily_kinetic = df.groupby("date").agg({
    "reported_missiles": "max", 
    "reported_drones": "max", 
    "reported_casualties": "max",
    "sentiment": "mean"
}).reset_index()

total_missiles = daily_kinetic["reported_missiles"].sum()
total_drones = daily_kinetic["reported_drones"].sum()
total_casualties = daily_kinetic["reported_casualties"].sum()

# --- MACRO KPIs ---
k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(f'<div class="metric-card"><div class="metric-title">Intel Signals</div><div class="metric-value">{len(df)}</div></div>', unsafe_allow_html=True)
k2.markdown(f'<div class="metric-card"><div class="metric-title">Missiles Fired (Est.)</div><div class="metric-value" style="color: #ff7b72;">{int(total_missiles):,}</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="metric-card"><div class="metric-title">Drones Deployed (Est.)</div><div class="metric-value" style="color: #d29922;">{int(total_drones):,}</div></div>', unsafe_allow_html=True)
k4.markdown(f'<div class="metric-card"><div class="metric-title">Reported Casualties</div><div class="metric-value" style="color: #8b949e;">{int(total_casualties):,}</div></div>', unsafe_allow_html=True)
k5.markdown(f'<div class="metric-card"><div class="metric-title">System Status</div><div class="metric-value" style="font-size: 1.2rem;"><span class="live-dot"></span>LIVE<br><span style="font-size: 0.8rem; color: #8b949e;">{datetime.now(IST).strftime("%H:%M IST")}</span></div></div>', unsafe_allow_html=True)

st.write("---")

# --- ANALYTICS DASHBOARD ---
left, right = st.columns([2, 1], gap="large")

with left:
    st.subheader("🔥 Kinetic Escalation Volume (Projectiles vs Time)")
    # Stacked Bar Chart for Missiles and Drones
    fig1 = px.bar(daily_kinetic, x="date", y=["reported_missiles", "reported_drones"], 
                  title="Daily Max Consensus of Projectiles Reported",
                  color_discrete_map={"reported_missiles": "#ff7b72", "reported_drones": "#d29922"})
    fig1.update_layout(template="plotly_dark", barmode='stack', hovermode="x unified", legend_title_text="Weapon Type", yaxis_title="Estimated Volume")
    st.plotly_chart(fig1, use_container_width=True)

    st.subheader("📊 Macro Economic Shock Tracker")
    mc1, mc2, mc3 = st.columns(3)
    for name, tick, col in [("Brent Crude (Energy)", "BZ=F", mc1), ("S&P 500 (Equity)", "^GSPC", mc2), ("Gold (Safe Haven)", "GC=F", mc3)]:
        with col:
            try:
                hist = yf.Ticker(tick).history(period="7d")
                if len(hist) >= 2:
                    last, prev = hist["Close"].iloc[-1], hist["Close"].iloc[-2]
                    delta_pct = ((last - prev) / prev) * 100
                    val = f"${last:,.2f}" if "S&P" not in name else f"{int(last):,}"
                    spark_color = "#ff7b72" if delta_pct < 0 else "#3fb950"
                    
                    st.metric(name, val, f"{delta_pct:+.2f}%")
                    spark = px.line(hist, x=hist.index, y='Close', template='plotly_dark', height=80)
                    spark.update_traces(line_color=spark_color)
                    spark.update_xaxes(visible=False, fixedrange=True)
                    spark.update_yaxes(visible=False, fixedrange=True)
                    spark.update_layout(margin=dict(t=0, b=0, l=0, r=0), hovermode=False)
                    st.plotly_chart(spark, use_container_width=True, config={'displayModeBar': False})
            except: st.caption(f"{name} Data Offline")

with right:
    st.subheader("🕸️ Secondary Actors & Contagion")
    text = " ".join(df["text"]).lower()
    
    entities = {"Russia": r"\brussia", "China": r"\bchina", "Turkey": r"\bturkey", 
                "Saudi": r"\bsaudi", "Lebanon": r"\blebanon", "Syria": r"\bsyria", 
                "Yemen (Houthis)": r"\b(yemen|houthi)", "Hezbollah": r"\bhezbollah", "Iraq": r"\biraq"}
    
    counts = {k: len(re.findall(v, text)) for k, v in entities.items()}
    ent_df = pd.Series(counts).sort_values(ascending=True).tail(7).to_frame("Mentions").reset_index()
    
    fig2 = px.bar(ent_df, x="Mentions", y="index", orientation='h', template="plotly_dark", color="Mentions", color_continuous_scale="Reds")
    fig2.update_layout(height=280, yaxis_title=None, coloraxis_showscale=False, margin=dict(l=0, r=0, t=0, b=10))
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("📡 Raw Signal Feed")
    # Show headlines that have kinetic data prominently
    kinetic_df = df[(df['reported_missiles'] > 0) | (df['reported_casualties'] > 0)].head(6)
    if kinetic_df.empty: kinetic_df = df.head(6) # Fallback to latest
    
    for _, r in kinetic_df.iterrows():
        tags = []
        if r['reported_missiles'] > 0: tags.append(f"🚀 {r['reported_missiles']} Missiles")
        if r['reported_casualties'] > 0: tags.append(f"⚠️ {r['reported_casualties']} Casualties")
        tag_str = " | ".join(tags)
        
        st.markdown(f"""
        <div class='metric-card' style='padding: 10px; margin-bottom: 8px; text-align: left;'>
            <a href='{r['url']}' target='_blank' style='color: #58a6ff; text-decoration: none; font-weight: 600; font-size: 0.9rem;'>{r['title']}</a><br>
            <span style='color: #8b949e; font-size: 0.75rem;'>{r['source']} • {r['datetime'].strftime('%H:%M GMT')}</span><br>
            <span style='color: #ff7b72; font-size: 0.8rem; font-weight: bold;'>{tag_str}</span>
        </div>
        """, unsafe_allow_html=True)
