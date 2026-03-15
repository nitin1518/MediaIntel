# app.py — Professional dashboard with empty-data protection

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
from nltk.tokenize import sent_tokenize

# NLTK fix
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

st.set_page_config(page_title="Iran–US–Israel Conflict Monitor", page_icon="🌍", layout="wide")

# ──── CSS (same as before) ────
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }
    .main { background: #0f172a; color: #e2e8f0; padding: 1.5rem 2rem; }
    .stApp > header { background: #0f172a !important; }
    h1 { color: #f1f5f9; font-weight: 700; letter-spacing: -0.5px; margin-bottom: 0.5rem !important; }
    .metric-card {
        background: linear-gradient(145deg, #1e293b, #334155);
        border: 1px solid #475569;
        border-radius: 12px;
        padding: 1.25rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2);
        text-align: center;
        transition: transform 0.2s;
    }
    .metric-card:hover { transform: translateY(-3px); }
    .live-dot {
        height: 10px; width: 10px; background-color: #22c55e;
        border-radius: 50%; display: inline-block;
        animation: pulse 2s infinite; margin-right: 6px;
    }
    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.4; } 100% { opacity: 1; } }
    .stExpander { background: #1e293b !important; border: 1px solid #475569 !important; border-radius: 8px; }
    hr { border-color: #475569; margin: 1.8rem 0; }
    </style>
""", unsafe_allow_html=True)

st.title("🌍 Iran – US – Israel Conflict Monitor")
st.markdown("Real-time media sentiment & economic impact • RSS + local NLP + markets")

# ──── Sidebar ────
with st.sidebar:
    st.header("Controls")
    max_articles = st.slider("Max articles to keep", 80, 400, 180, step=20)
    fetch_full_text = st.checkbox("Extract full article text", True)
    auto_refresh = st.checkbox("Auto-refresh every 5 min", True)

    if st.button("🔄 Refresh Now", type="primary", use_container_width=True):
        if "df" in st.session_state: del st.session_state.df
        st.rerun()

    st.markdown("---")
    st.caption("Debug: If no articles appear → check network / try later")

# ──── Fetch function with better fallback queries ────
@st.cache_data(ttl=300)
def fetch_news(max_articles, fetch_full):
    queries = [
        '(Iran OR Tehran OR Khamenei) (Israel OR Netanyahu OR "Tel Aviv") (US OR USA OR America OR Trump OR Biden)',
        '(Iran OR Israel OR Gaza) (missile OR drone OR strike OR attack OR war OR escalation OR conflict)',
        '(Iran OR Israel) (US OR United States) (tension OR "Hormuz" OR oil OR nuclear)'
    ]

    articles = []
    seen = set()

    for q in queries:
        url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        for entry in feed.entries[:max_articles]:
            link = entry.link.split("?")[0]
            if link in seen: continue
            seen.add(link)
            pub = parser.parse(entry.published) if 'published' in entry else datetime.now()
            text = f"{entry.title}. {entry.get('summary', '')}"
            if fetch_full:
                try:
                    dl = trafilatura.fetch_url(link, timeout=8)
                    ft = trafilatura.extract(dl) or ""
                    text += " " + ft[:1500]
                except:
                    pass
            articles.append({
                "title": entry.title,
                "url": link,
                "source": "Google News",
                "date": pub.date(),
                "datetime": pub,
                "text": text[:3000],
                "hash": hashlib.md5(text.encode()).hexdigest()[:12]
            })

    # Dedup & limit
    df = pd.DataFrame(articles)
    if not df.empty:
        df = df.drop_duplicates(subset="hash").sort_values("datetime", ascending=False).head(max_articles)

    # Sentiment (only if data exists)
    if not df.empty:
        analyzer = SentimentIntensityAnalyzer()
        def compute_sent(text):
            if not text.strip(): return 0.0, 0.0, 0.0
            overall = analyzer.polarity_scores(text)["compound"]
            israel_s = iran_s = 0.0
            ic = rc = 0
            for sent in sent_tokenize(text):
                low = sent.lower()
                sc = analyzer.polarity_scores(sent)["compound"]
                if any(w in low for w in ["israel","netanyahu","tel aviv","us","usa","america","trump","biden"]):
                    israel_s += sc; ic += 1
                if any(w in low for w in ["iran","tehran","khamenei","irgc"]):
                    iran_s += sc; rc += 1
            return overall, israel_s/ic if ic else 0.0, iran_s/rc if rc else 0.0

        results = df["text"].apply(compute_sent)
        df["sent_overall"] = [r[0] for r in results]
        df["sent_israel_us"] = [r[1] for r in results]
        df["sent_iran"] = [r[2] for r in results]

    return df

# ──── Load data ────
if "df" not in st.session_state:
    with st.spinner("Fetching latest news..."):
        st.session_state.df = fetch_news(max_articles, fetch_full_text)
        st.session_state.last_update = datetime.now()

df = st.session_state.df
last_update = st.session_state.last_update

has_data = not df.empty

# ──── KPI Cards ────
k1, k2, k3, k4 = st.columns([1,1,1.3,1])

with k1:
    count_str = f"{len(df):,}" if has_data else "0"
    st.markdown(f'<div class="metric-card"><strong>Articles</strong><br><h2>{count_str}</h2><small>from RSS sources</small></div>', unsafe_allow_html=True)

with k2:
    tone_str = f"{float(df['sent_overall'].mean()):.2f}" if has_data else "0.00"
    tone_color = "#22c55e" if has_data and float(tone_str) > 0.05 else "#ef4444" if has_data and float(tone_str) < -0.05 else "#94a3b8"
    st.markdown(f'<div class="metric-card"><strong>Media Tone</strong><br><h2 style="color:{tone_color};">{tone_str}</h2><small>(+ = pro US/Israel)</small></div>', unsafe_allow_html=True)

with k3:
    if has_data:
        winner = "🇺🇸🇮🇱 US/Israel" if df["sent_israel_us"].mean() > df["sent_iran"].mean() else "🇮🇷 Iran"
    else:
        winner = "No data"
    st.markdown(f'<div class="metric-card"><strong>Media Favor</strong><br><h2>{winner}</h2><small>tone-based</small></div>', unsafe_allow_html=True)

with k4:
    st.markdown(f'<div class="metric-card"><strong>Last Update</strong><br><span class="live-dot"></span>{last_update.strftime("%H:%M %d %b")}</div>', unsafe_allow_html=True)

st.markdown("---")

if not has_data:
    st.warning("No articles fetched in the last run. This can happen due to temporary RSS issues, network problems, or quiet news periods. Try forcing a refresh or wait a few minutes.")
    st.info("Tip: Broader queries sometimes help during low-activity times.")

# ──── Layout (only show charts if data exists) ────
if has_data:
    left, right = st.columns([7, 3], gap="large")

    with left:
        st.subheader("Sentiment Trend")
        daily = df.groupby("date").agg({"sent_israel_us": "mean", "sent_iran": "mean"}).reset_index()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_israel_us"], name="US/Israel", line=dict(color="#22c55e", width=3)))
        fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_iran"], name="Iran", line=dict(color="#ef4444", width=3)))
        fig.update_layout(template="plotly_dark", height=420, hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # Markets...
        st.subheader("Market Signals")
        mc1, mc2, mc3 = st.columns(3)
        for name, tick in [("Oil (WTI)", "CL=F"), ("S&P 500", "^GSPC"), ("Gold", "GC=F")]:
            col = mc1 if name == "Oil (WTI)" else mc2 if name == "S&P 500" else mc3
            with col:
                try:
                    hist = yf.Ticker(tick).history(period="14d")
                    if not hist.empty and len(hist) >= 2:
                        last = float(hist["Close"].iloc[-1])
                        delta = last - float(hist["Close"].iloc[-2])
                        val = f"${last:,.2f}" if "Oil" in name or "Gold" in name else f"{int(last):,}"
                        st.metric(name, val, f"{delta:+,.2f}")
                        st.line_chart(hist["Close"], height=120)
                except:
                    st.caption(f"{name} – no data")

    with right:
        st.subheader("Key Mentions")
        text = " ".join(df["text"]).lower()
        counts = {k: text.count(v.lower()) for k,v in {
            "Russia": "russia", "China": "china", "Turkey": "turkey", "Saudi": "saudi",
            "Lebanon": "lebanon", "Syria": "syria", "Yemen/Houthis": "yemen|houthi",
            "Hezbollah": "hezbollah", "Hamas": "hamas", "Qatar": "qatar"
        }.items()}
        ent_df = pd.Series(counts).sort_values(ascending=False).head(10).to_frame("Mentions")
        fig = px.bar(ent_df, y="Mentions", color="Mentions", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Recent Articles")
        for _, r in df.head(6).iterrows():
            with st.expander(r["title"][:65] + "…"):
                st.caption(f"{r['source']} • {r['date']} • {r['sent_overall']:.2f}")
                st.markdown(f"[Read]({r['url']})")
                st.write(r["text"][:250] + "…")

else:
    st.info("Dashboard waiting for data... Refresh to try again.")

# ──── Footer ────
st.markdown("---")
st.caption(f"Last: {last_update.strftime('%Y-%m-%d %H:%M')} • Free/local • Approximate analysis")

if auto_refresh and (datetime.now() - last_update).total_seconds() > 300:
    st.rerun()
