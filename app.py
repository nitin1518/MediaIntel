# app.py — Enhanced fully-free version (no API keys ever)

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import feedparser
from dateutil import parser
import trafilatura
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import yfinance as yf
import re
import hashlib
from nltk.tokenize import sent_tokenize
import nltk
nltk.download('punkt', quiet=True)
import time
import pickle
from pathlib import Path

st.set_page_config(page_title="Iran-US-Israel Conflict Live", layout="wide", page_icon="🌍")

# --------------------- CUSTOM CSS (dark + modern) ---------------------
st.markdown("""
<style>
    .main { background: #0f172a; color: #e2e8f0; }
    h1, h2, h3 { color: #f1f5f9; }
    .metric-card { background: linear-gradient(145deg, #1e2937, #334155); padding: 1.4rem; border-radius: 12px; border: 1px solid #475569; text-align:center; }
    .live { color:#22c55e; font-weight:bold; animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
    .stExpander { background: #1e2937 !important; border: 1px solid #475569; }
</style>
""", unsafe_allow_html=True)

st.title("🌍 Iran • US • Israel Conflict — Live Dashboard")
st.caption("100% free • Google News RSS + direct feeds • No API keys • NLP local analysis • Markets via yfinance • Auto-refresh")

# --------------------- SIDEBAR ---------------------
with st.sidebar:
    st.header("Controls")
    max_articles = st.slider("Max articles to keep", 80, 400, 180)
    fetch_full = st.checkbox("Extract full article text (slower but better NLP)", True)
    auto_refresh = st.checkbox("Auto-refresh every 5 min", True)
    if st.button("🔄 FORCE REFRESH", type="primary"):
        if "df" in st.session_state: del st.session_state.df
        st.rerun()

# --------------------- CACHE & STORAGE ---------------------
CACHE_FILE = Path("article_cache.pkl")
def load_cache():
    if CACHE_FILE.exists():
        with open(CACHE_FILE, "rb") as f:
            return pickle.load(f)
    return {"articles": [], "seen": set()}

def save_cache(data):
    with open(CACHE_FILE, "wb") as f:
        pickle.dump(data, f)

# --------------------- FETCH FUNCTION ---------------------
@st.cache_data(ttl=300, show_spinner="Collecting latest news...")
def fetch_news(max_articles, fetch_full):
    cache = load_cache()
    articles = cache["articles"]
    seen = cache["seen"]

    # Multiple focused queries + direct RSS for diversity & resilience
    queries = [
        '(Iran OR Tehran OR Khamenei) (Israel OR "Tel Aviv" OR Netanyahu) (US OR USA OR America OR Trump OR Biden)',
        '(Iran OR Israel) (missile OR drone OR strike OR attack OR war OR escalation)',
        '(Iran OR Israel) (US OR United States) (conflict OR tension OR Strait of Hormuz OR oil)'
    ]

    direct_rss = [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.reuters.com/arc/outboundfeeds/newsroom/?outputType=xml",
        "https://www.timesofisrael.com/feed/",
        "https://www.bbc.co.uk/news/world/middle_east/rss.xml",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.cnn.com/services/rss/cnn_world.rss"
    ]

    new_entries = []
    for q in queries:
        url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.link.split("?")[0]
            if link in seen: continue
            seen.add(link)

            try:
                pub = parser.parse(entry.published)
            except:
                pub = datetime.now()

            text = f"{entry.title}. {entry.get('summary', '')}"
            full_text = ""

            if fetch_full:
                try:
                    dl = trafilatura.fetch_url(link, timeout=7)
                    ft = trafilatura.extract(dl) or ""
                    full_text = ft
                    text += " " + ft[:1800]
                except:
                    pass

            art = {
                "title": entry.title,
                "url": link,
                "source": entry.get("source", {}).get("title", "Google News"),
                "date": pub.date(),
                "datetime": pub,
                "text": text[:3200],
                "hash": hashlib.md5(text.encode()).hexdigest()[:12]  # for dedup
            }
            new_entries.append(art)

    # Add from direct RSS
    for rss in direct_rss:
        feed = feedparser.parse(rss)
        for entry in feed.entries[:30]:
            link = entry.link
            if any(s in link for s in ["iran", "israel", "tehran", "tel-aviv"]):  # loose filter
                if link in seen: continue
                seen.add(link)
                try: pub = parser.parse(entry.published)
                except: pub = datetime.now()
                text = f"{entry.title}. {entry.get('summary', '')}"
                art = {
                    "title": entry.title,
                    "url": link,
                    "source": feed.feed.get("title", "Direct RSS"),
                    "date": pub.date(),
                    "datetime": pub,
                    "text": text[:3200],
                    "hash": hashlib.md5(text.encode()).hexdigest()[:12]
                }
                new_entries.append(art)

    # Merge new + old, dedup by hash, sort by date
    all_arts = articles + new_entries
    unique = {a["hash"]: a for a in all_arts}.values()
    df = pd.DataFrame(sorted(unique, key=lambda x: x["datetime"], reverse=True)[:max_articles])

    # Update cache
    cache["articles"] = df.to_dict("records")
    cache["seen"] = seen
    save_cache(cache)

    return df

# Load / fetch data
if "df" not in st.session_state or st.button("Refresh (force)", key="force"):
    with st.spinner("Fetching from Google News + major RSS feeds..."):
        df = fetch_news(max_articles, fetch_full)
        st.session_state.df = df
        st.session_state.last = datetime.now()

df = st.session_state.df
last_update = st.session_state.last

# --------------------- NLP (local VADER) ---------------------
analyzer = SentimentIntensityAnalyzer()

@st.cache_data
def compute_sentiment(text):
    score = analyzer.polarity_scores(text)["compound"]

    israel_s = 0; iran_s = 0; ic = 0; rc = 0
    for sent in sent_tokenize(text):
        low = sent.lower()
        if any(w in low for w in ["israel","tel aviv","netanyahu","us","usa","america","trump"]):
            israel_s += analyzer.polarity_scores(sent)["compound"]
            ic += 1
        if any(w in low for w in ["iran","tehran","khamenei","irgc","axis of resistance"]):
            iran_s += analyzer.polarity_scores(sent)["compound"]
            rc += 1

    return score, israel_s/ic if ic else 0, iran_s/rc if rc else 0

if "sent_overall" not in df.columns:
    with st.spinner("Running local sentiment analysis..."):
        results = df["text"].apply(compute_sentiment)
        df["sent_overall"] = [r[0] for r in results]
        df["sent_israel_us"] = [r[1] for r in results]
        df["sent_iran"] = [r[2] for r in results]
        st.session_state.df = df

# --------------------- METRICS ROW ---------------------
c1, c2, c3, c4 = st.columns(4)
with c1: st.markdown(f'<div class="metric-card"><h4>Articles</h4><h2>{len(df)}</h2><small>from 100+ sources</small></div>', unsafe_allow_html=True)
with c2:
    avg = df["sent_overall"].mean()
    col = "#22c55e" if avg > 0.05 else "#ef4444" if avg < -0.05 else "#94a3b8"
    st.markdown(f'<div class="metric-card"><h4>Media Tone</h4><h2 style="color:{col};">{avg:.2f}</h2><small>(+ = more positive for US/Israel)</small></div>', unsafe_allow_html=True)
with c3:
    winner = "🇺🇸🇮🇱 US/Israel" if df["sent_israel_us"].mean() > df["sent_iran"].mean() else "🇮🇷 Iran"
    st.markdown(f'<div class="metric-card"><h4>Media Favor</h4><h2>{winner}</h2><small>(based on tone)</small></div>', unsafe_allow_html=True)
with c4:
    st.markdown(f'<div class="metric-card"><h4>Last Update</h4><h2 class="live">● {last_update.strftime("%H:%M")}</h2></div>', unsafe_allow_html=True)

# --------------------- TABS ---------------------
tab1, tab2, tab3, tab4 = st.tabs(["Trend", "Articles", "Countries", "Markets"])

with tab1:
    st.subheader("Media Sentiment Trend (who looks stronger in coverage)")
    daily = df.groupby("date").agg({
        "sent_israel_us": "mean",
        "sent_iran": "mean"
    }).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_israel_us"], name="US/Israel tone", line=dict(color="#22c55e", width=3)))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_iran"], name="Iran tone", line=dict(color="#ef4444", width=3)))
    fig.update_layout(template="plotly_dark", height=480, hovermode="x unified", legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Latest Articles")
    for _, row in df.head(30).iterrows():
        with st.expander(f"{row['title']}  •  {row['source']}  •  {row['date']}  •  {row['sent_overall']:.2f}"):
            st.markdown(f"**Sentiment:** {row['sent_overall']:.2f} | US/Israel: {row['sent_israel_us']:.2f} | Iran: {row['sent_iran']:.2f}")
            st.markdown(f"[Read →]({row['url']})")
            st.write(row["text"][:600] + "...")

with tab3:
    st.subheader("Mentions of Involved / Impacted Countries & Groups")
    text_all = " ".join(df["text"]).lower()
    entities = {
        "Russia": text_all.count("russia"),
        "China": text_all.count("china"),
        "Turkey": text_all.count("turkey"),
        "Saudi": text_all.count("saudi"),
        "Lebanon": text_all.count("lebanon"),
        "Syria": text_all.count("syria"),
        "Yemen": text_all.count("yemen"),
        "Hezbollah": text_all.count("hezbollah"),
        "Houthi": text_all.count("houthi"),
        "Hamas": text_all.count("hamas"),
        "Gulf": text_all.count("gulf"),
        "Qatar": text_all.count("qatar")
    }
    ent_df = pd.DataFrame.from_dict(entities, orient="index", columns=["Mentions"]).sort_values("Mentions", ascending=False)
    fig = px.bar(ent_df.head(12), y="Mentions", color="Mentions", color_continuous_scale="reds", template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.subheader("Economic & Market Impact (live)")
    cA, cB, cC = st.columns(3)
    tickers = {"Oil (WTI)": "CL=F", "S&P 500": "^GSPC", "Gold": "GC=F"}
    for name, sym in tickers.items():
        with (cA if name=="Oil (WTI)" else cB if name=="S&P 500" else cC):
            data = yf.download(sym, period="14d", progress=False)
            if not data.empty:
                last = data["Close"].iloc[-1]
                delta = last - data["Close"].iloc[-2] if len(data)>1 else 0
                st.metric(name, f"{last:.2f}" if "Oil" in name or "Gold" in name else f"{int(last)}", f"{delta:+.2f}")
                st.line_chart(data["Close"], use_container_width=True, height=140)

# --------------------- AUTO REFRESH ---------------------
if auto_refresh and (datetime.now() - last_update).total_seconds() > 300:
    st.rerun()

st.caption("Fully free & local • RSS + trafilatura + VADER + yfinance • Respect source terms • Not financial advice • War coverage approximate")
