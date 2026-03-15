import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
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

st.set_page_config(page_title="Iran-US-Israel Conflict Monitor", page_icon="🌍", layout="wide")

# --- AUTO-REFRESH (Reliable Kiosk Mode) ---
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

# --- HIGH-END CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }
    .main { background: #0d1117; color: #c9d1d9; }
    .stApp > header { background: #0d1117 !important; }
    h1, h2, h3 { color: #ffffff; font-weight: 700; letter-spacing: -0.5px; }
    .metric-card {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 10px;
        padding: 1.5rem;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .metric-title { font-size: 0.85rem; color: #8b949e; text-transform: uppercase; font-weight: 600; margin-bottom: 5px;}
    .metric-value { font-size: 2rem; font-weight: bold; color: #ffffff; }
    .live-dot {
        height: 10px; width: 10px; background-color: #3fb950;
        border-radius: 50%; display: inline-block;
        animation: pulse 2s infinite; margin-right: 8px;
    }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
    hr { border-color: #30363d; margin: 2rem 0; }
    </style>
""", unsafe_allow_html=True)

# --- ENGINE: MULTITHREADED SCRAPER ---
def fetch_single_article(entry, fetch_full):
    """Worker function for parallel downloading"""
    link = entry.link.split("?")[0]
    pub = parser.parse(entry.published) if 'published' in entry else datetime.now()
    text = f"{entry.title}. {entry.get('summary', '')}"
    
    if fetch_full:
        try:
            dl = trafilatura.fetch_url(link, timeout=5) # Reduced timeout to prevent hanging
            if dl:
                ft = trafilatura.extract(dl) or ""
                text += " " + ft[:2000]
        except: pass
        
    return {
        "title": entry.title,
        "url": link,
        "source": entry.get('source', {}).get('title', 'Google News'),
        "date": pub.date(),
        "datetime": pub,
        "text": text[:3000],
        "hash": hashlib.md5(text.encode()).hexdigest()[:12]
    }

@st.cache_data(ttl=300)
def fetch_news(max_articles, fetch_full):
    queries = [
        '(Iran OR Tehran OR Khamenei) (Israel OR Netanyahu OR "Tel Aviv") (US OR USA OR America)',
        '(Iran OR Israel) (missile OR drone OR strike OR escalation OR conflict)',
        '(Iran) (oil OR nuclear OR sanctions)'
    ]

    raw_entries = []
    seen_links = set()

    # 1. Gather all RSS links instantly
    for q in queries:
        url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_articles]:
                link = entry.link.split("?")[0]
                if link not in seen_links:
                    seen_links.add(link)
                    raw_entries.append(entry)
        except: continue

    # 2. Multithreaded Full-Text Extraction (10x Faster)
    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(fetch_single_article, entry, fetch_full) for entry in raw_entries[:max_articles]]
        for future in concurrent.futures.as_completed(futures):
            try:
                articles.append(future.result())
            except: pass

    df = pd.DataFrame(articles)
    if df.empty: return df

    # 3. Deduplicate & Sentiment Engine
    df = df.drop_duplicates(subset="hash").sort_values("datetime", ascending=False)
    analyzer = SentimentIntensityAnalyzer()
    
    def compute_sent(text):
        if not text.strip(): return 0.0, 0.0, 0.0
        overall = analyzer.polarity_scores(text)["compound"]
        israel_s, iran_s, ic, rc = 0.0, 0.0, 0, 0
        
        for sent in sent_tokenize(text):
            low = sent.lower()
            sc = analyzer.polarity_scores(sent)["compound"]
            if re.search(r'\b(israel|netanyahu|tel aviv|us|usa|america|biden)\b', low):
                israel_s += sc; ic += 1
            if re.search(r'\b(iran|tehran|khamenei|irgc)\b', low):
                iran_s += sc; rc += 1
                
        return overall, israel_s/ic if ic else 0.0, iran_s/rc if rc else 0.0

    results = df["text"].apply(compute_sent)
    df["sent_overall"] = [r[0] for r in results]
    df["sent_israel_us"] = [r[1] for r in results]
    df["sent_iran"] = [r[2] for r in results]

    return df

# --- UI RENDER ---
st.markdown("<h2 style='text-align: center;'>🌍 IRAN-US-ISRAEL CONFLICT MONITOR</h2>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #8b949e;'>Real-time Narrative & Market Impact Engine</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Engine Controls")
    max_articles = st.slider("Signal Volume (Max Articles)", 50, 300, 150, step=50)
    fetch_full_text = st.checkbox("Deep Extraction (Full Text)", True)
    if st.button("🔄 Force Network Sync", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# Load Data
with st.spinner("Aggregating global signals..."):
    df = fetch_news(max_articles, fetch_full_text)
    has_data = not df.empty

# --- MACRO KPIs ---
k1, k2, k3, k4 = st.columns(4)

with k1:
    count_str = f"{len(df):,}" if has_data else "0"
    st.markdown(f'<div class="metric-card"><div class="metric-title">Signals Processed</div><div class="metric-value">{count_str}</div></div>', unsafe_allow_html=True)

with k2:
    tone_str = f"{df['sent_overall'].mean():.2f}" if has_data else "0.00"
    t_color = "#3fb950" if has_data and float(tone_str) > 0 else "#ff7b72" if has_data and float(tone_str) < 0 else "#c9d1d9"
    st.markdown(f'<div class="metric-card"><div class="metric-title">Global Media Tone</div><div class="metric-value" style="color:{t_color};">{tone_str}</div></div>', unsafe_allow_html=True)

with k3:
    if has_data:
        winner = "🇺🇸🇮🇱 US/Israel" if df["sent_israel_us"].mean() > df["sent_iran"].mean() else "🇮🇷 Iran/Proxies"
    else: winner = "N/A"
    st.markdown(f'<div class="metric-card"><div class="metric-title">Narrative Dominance</div><div class="metric-value" style="font-size: 1.5rem; padding-top: 5px;">{winner}</div></div>', unsafe_allow_html=True)

with k4:
    st.markdown(f'<div class="metric-card"><div class="metric-title">System Status</div><div class="metric-value" style="font-size: 1.2rem; padding-top: 8px;"><span class="live-dot"></span>LIVE<br><span style="font-size: 0.8rem; color: #8b949e; font-weight: normal;">{datetime.now(IST).strftime("%H:%M IST")}</span></div></div>', unsafe_allow_html=True)

st.write("---")

if not has_data:
    st.warning("⚠️ Telemetry Offline: No articles fetched. Waiting for next network sync.")
    st.stop()

# --- ANALYTICS DASHBOARD ---
left, right = st.columns([2, 1], gap="large")

with left:
    st.subheader("📈 Faction Sentiment Trajectory")
    daily = df.groupby("date").agg({"sent_israel_us": "mean", "sent_iran": "mean"}).reset_index()
    
    fig = go.Figure()
    # Added markers and line smoothing for a more professional "CXO" look
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_israel_us"], name="US/Israel Posture", line=dict(color="#58a6ff", width=3, shape='spline'), mode='lines+markers'))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_iran"], name="Iran Posture", line=dict(color="#ff7b72", width=3, shape='spline'), mode='lines+markers'))
    
    fig.update_layout(template="plotly_dark", height=350, hovermode="x unified", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    fig.add_hline(y=0, line_dash="dash", line_color="#8b949e", opacity=0.5)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("📊 Macro Market Signals")
    mc1, mc2, mc3 = st.columns(3)
    for name, tick, col in [("Brent Crude (Energy)", "BZ=F", mc1), ("S&P 500 (Equity)", "^GSPC", mc2), ("Gold (Safe Haven)", "GC=F", mc3)]:
        with col:
            try:
                hist = yf.Ticker(tick).history(period="7d")
                if len(hist) >= 2:
                    last, prev = hist["Close"].iloc[-1], hist["Close"].iloc[-2]
                    delta_pct = ((last - prev) / prev) * 100
                    val = f"${last:,.2f}" if "S&P" not in name else f"{int(last):,}"
                    
                    st.metric(name, val, f"{delta_pct:+.2f}%")
                    # Simplified sparkline using Plotly for cleaner aesthetics
                    spark = px.line(hist, x=hist.index, y='Close', template='plotly_dark', height=100)
                    spark.update_xaxes(visible=False, fixedrange=True)
                    spark.update_yaxes(visible=False, fixedrange=True)
                    spark.update_layout(margin=dict(t=0, b=0, l=0, r=0), hovermode=False)
                    st.plotly_chart(spark, use_container_width=True, config={'displayModeBar': False})
            except: st.caption(f"{name} Data Offline")

with right:
    st.subheader("🕸️ Global Contagion Radar")
    text = " ".join(df["text"]).lower()
    
    # NLP Fix: Using Regex \b to ensure exact word matches (e.g., stops "china" matching "indochina")
    entities = {"Russia": r"\brussia", "China": r"\bchina", "Turkey": r"\bturkey", 
                "Saudi Arabia": r"\bsaudi", "Lebanon": r"\blebanon", "Syria": r"\bsyria", 
                "Yemen/Houthis": r"\b(yemen|houthi)", "Hezbollah": r"\bhezbollah", "Hamas": r"\bhamas"}
    
    counts = {k: len(re.findall(v, text)) for k, v in entities.items()}
    ent_df = pd.Series(counts).sort_values(ascending=True).tail(8).to_frame("Mentions").reset_index()
    
    fig2 = px.bar(ent_df, x="Mentions", y="index", orientation='h', template="plotly_dark", color="Mentions", color_continuous_scale="Reds")
    fig2.update_layout(height=300, yaxis_title=None, coloraxis_showscale=False, margin=dict(l=0, r=0, t=0, b=0))
    st.plotly_chart(fig2, use_container_width=True)

    st.subheader("📡 Live Signal Feed")
    for _, r in df.head(5).iterrows():
        with st.container():
            st.markdown(f"**<a href='{r['url']}' target='_blank' style='color: #c9d1d9; text-decoration: none;'>{r['title']}</a>**", unsafe_allow_html=True)
            st.markdown(f"<span style='color: #8b949e; font-size: 0.8rem;'>{r['source']} • Score: {r['sent_overall']:.2f}</span>", unsafe_allow_html=True)
            st.write("")
