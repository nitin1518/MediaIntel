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
import nltk
import os
from nltk.tokenize import sent_tokenize

# ───────────────────────────────────────────────
# Force download of required NLTK data at startup
# This fixes LookupError: Resource punkt_tab not found
# ───────────────────────────────────────────────
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)

# Optional: set custom NLTK data path (helps in some cloud environments)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

st.set_page_config(page_title="Iran-US-Israel Conflict Live", layout="wide", page_icon="🌍")

# ──────────────────────────────
# Modern dark theme styling
# ──────────────────────────────
st.markdown("""
<style>
    .main { background: #0f172a; color: #e2e8f0; }
    h1, h2, h3 { color: #f1f5f9; }
    .metric-card {
        background: linear-gradient(145deg, #1e2937, #334155);
        padding: 1.4rem;
        border-radius: 12px;
        border: 1px solid #475569;
        text-align: center;
    }
    .live {
        color: #22c55e;
        font-weight: bold;
        animation: pulse 2s infinite;
    }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.5} }
    .stExpander {
        background: #1e2937 !important;
        border: 1px solid #475569;
    }
</style>
""", unsafe_allow_html=True)

st.title("🌍 Iran • US • Israel Conflict — Live Dashboard")
st.caption("Fully free • Google News RSS + major outlet feeds • No API keys • Local VADER sentiment • yfinance markets • Auto-refresh")

# ────────────────
# Sidebar controls
# ────────────────
with st.sidebar:
    st.header("Controls")
    max_articles = st.slider("Max articles to keep", 80, 400, 180)
    fetch_full = st.checkbox("Extract full article text (better NLP, slower)", True)
    auto_refresh = st.checkbox("Auto-refresh every 5 min", True)
    if st.button("🔄 FORCE REFRESH", type="primary"):
        if "df" in st.session_state:
            del st.session_state.df
        st.rerun()

# ───────────────────────────────
# Simple persistent cache on disk
# ───────────────────────────────
CACHE_FILE = "article_cache.pkl"

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "rb") as f:
                return pd.read_pickle(f)
        except:
            return None
    return None

def save_cache(df):
    df.to_pickle(CACHE_FILE)

# ────────────────────────────────
# Main data collection function
# ────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Collecting latest news from multiple sources…")
def fetch_news(max_articles, fetch_full_text):
    cached_df = load_cache()
    if cached_df is not None and len(cached_df) >= max_articles // 2:
        return cached_df

    queries = [
        '(Iran OR Tehran OR Khamenei) (Israel OR "Tel Aviv" OR Netanyahu) (US OR USA OR America OR Trump OR Biden)',
        '(Iran OR Israel) (missile OR drone OR strike OR attack OR war OR escalation)',
        '(Iran OR Israel) (US OR United States) (conflict OR tension OR "Strait of Hormuz" OR oil)'
    ]

    direct_rss_feeds = [
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://www.reuters.com/arc/outboundfeeds/newsroom/?outputType=xml",
        "https://www.timesofisrael.com/feed/",
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://www.cnn.com/services/rss/cnn_world.rss"
    ]

    all_entries = []
    seen_urls = set()

    # Google News queries
    for q in queries:
        url = f"https://news.google.com/rss/search?q={q.replace(' ', '+')}&hl=en-US&gl=US&ceid=US:en"
        feed = feedparser.parse(url)
        for entry in feed.entries:
            link = entry.link.split("?")[0]
            if link in seen_urls:
                continue
            seen_urls.add(link)

            pub = parser.parse(entry.published) if 'published' in entry else datetime.now()
            text = f"{entry.title}. {entry.get('summary', '')}"
            full_text = ""

            if fetch_full_text:
                try:
                    downloaded = trafilatura.fetch_url(link, timeout=7)
                    ft = trafilatura.extract(downloaded) or ""
                    full_text = ft
                    text += " " + ft[:1800]
                except:
                    pass

            all_entries.append({
                "title": entry.title,
                "url": link,
                "source": entry.get("source", {}).get("title", "Google News"),
                "date": pub.date(),
                "datetime": pub,
                "text": text[:3200],
                "hash": hashlib.md5(text.encode()).hexdigest()[:12]
            })

    # Direct RSS feeds
    for rss_url in direct_rss_feeds:
        feed = feedparser.parse(rss_url)
        feed_title = feed.feed.get("title", "Direct RSS")
        for entry in feed.entries[:40]:
            link = entry.link
            if any(kw in link.lower() for kw in ["iran", "israel", "tehran", "tel-aviv", "gaza", "hezbollah"]):
                if link in seen_urls:
                    continue
                seen_urls.add(link)
                pub = parser.parse(entry.published) if 'published' in entry else datetime.now()
                text = f"{entry.title}. {entry.get('summary', '')}"
                all_entries.append({
                    "title": entry.title,
                    "url": link,
                    "source": feed_title,
                    "date": pub.date(),
                    "datetime": pub,
                    "text": text[:3200],
                    "hash": hashlib.md5(text.encode()).hexdigest()[:12]
                })

    # Deduplicate & sort
    unique = {e["hash"]: e for e in all_entries}.values()
    df_new = pd.DataFrame(sorted(unique, key=lambda x: x["datetime"], reverse=True))[:max_articles]

    # Merge with cache if exists
    if cached_df is not None:
        combined = pd.concat([cached_df, df_new]).drop_duplicates(subset="hash", keep="first")
        df = combined.sort_values("datetime", ascending=False).head(max_articles)
    else:
        df = df_new

    save_cache(df)
    return df

# ───────────────────────────────
# Load or fetch data
# ───────────────────────────────
if "df" not in st.session_state:
    with st.spinner("Initial data load from RSS sources…"):
        st.session_state.df = fetch_news(max_articles, fetch_full)
        st.session_state.last_update = datetime.now()

df = st.session_state.df
last_update = st.session_state.last_update

# ───────────────────────────────
# Local VADER sentiment analysis
# ───────────────────────────────
analyzer = SentimentIntensityAnalyzer()

@st.cache_data
def compute_sentiment(text: str) -> tuple:
    if not text.strip():
        return 0.0, 0.0, 0.0

    overall = analyzer.polarity_scores(text)["compound"]

    israel_score = iran_score = 0.0
    israel_count = iran_count = 0

    sentences = sent_tokenize(text)
    for sent in sentences:
        low = sent.lower()
        sent_score = analyzer.polarity_scores(sent)["compound"]
        if any(k in low for k in ["israel", "tel aviv", "netanyahu", "us", "usa", "america", "trump", "biden"]):
            israel_score += sent_score
            israel_count += 1
        if any(k in low for k in ["iran", "tehran", "khamenei", "irgc", "axis of resistance"]):
            iran_score += sent_score
            iran_count += 1

    avg_israel = israel_score / israel_count if israel_count > 0 else 0.0
    avg_iran   = iran_score   / iran_count   if iran_count   > 0 else 0.0

    return overall, avg_israel, avg_iran

if "sent_overall" not in df.columns:
    with st.spinner("Running local sentiment analysis on articles…"):
        results = df["text"].apply(compute_sentiment)
        df["sent_overall"]   = [r[0] for r in results]
        df["sent_israel_us"] = [r[1] for r in results]
        df["sent_iran"]      = [r[2] for r in results]
        st.session_state.df = df

# ───────────────────────────────
# Dashboard metrics row
# ───────────────────────────────
cols = st.columns(4)
with cols[0]:
    st.markdown(f'<div class="metric-card"><h4>Articles</h4><h2>{len(df)}</h2><small>from multiple sources</small></div>', unsafe_allow_html=True)

with cols[1]:
    avg_sent = df["sent_overall"].mean()
    color = "#22c55e" if avg_sent > 0.05 else "#ef4444" if avg_sent < -0.05 else "#94a3b8"
    st.markdown(f'<div class="metric-card"><h4>Overall Media Tone</h4><h2 style="color:{color};">{avg_sent:.2f}</h2><small>(+ = more favorable to US/Israel)</small></div>', unsafe_allow_html=True)

with cols[2]:
    winner = "🇺🇸🇮🇱 US/Israel" if df["sent_israel_us"].mean() > df["sent_iran"].mean() else "🇮🇷 Iran"
    st.markdown(f'<div class="metric-card"><h4>Current Media Favor</h4><h2>{winner}</h2><small>(tone-based)</small></div>', unsafe_allow_html=True)

with cols[3]:
    st.markdown(f'<div class="metric-card"><h4>Last Update</h4><h2 class="live">● {last_update.strftime("%H:%M")}</h2></div>', unsafe_allow_html=True)

# ───────────────────────────────
# Tabs
# ───────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["Trend", "Articles", "Countries/Groups", "Markets"])

with tab1:
    st.subheader("Media Sentiment Trend")
    daily = df.groupby("date").agg({
        "sent_israel_us": "mean",
        "sent_iran": "mean"
    }).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_israel_us"], name="US/Israel tone", line=dict(color="#22c55e", width=3)))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["sent_iran"], name="Iran tone", line=dict(color="#ef4444", width=3)))
    fig.update_layout(
        template="plotly_dark",
        height=480,
        hovermode="x unified",
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
    )
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.subheader("Latest Articles")
    for _, row in df.head(30).iterrows():
        with st.expander(f"{row['title']} • {row['source']} • {row['date']} • {row['sent_overall']:.2f}"):
            st.markdown(f"**Tone breakdown** — Overall: {row['sent_overall']:.2f} | US/Israel: {row['sent_israel_us']:.2f} | Iran: {row['sent_iran']:.2f}")
            st.markdown(f"[Read full article]({row['url']})")
            st.write(row["text"][:700] + "…")

with tab3:
    st.subheader("Mentions — Involved / Impacted Entities")
    all_text = " ".join(df["text"]).lower()
    entities = {
        "Russia": all_text.count("russia"),
        "China": all_text.count("china"),
        "Turkey": all_text.count("turkey"),
        "Saudi": all_text.count("saudi"),
        "Lebanon": all_text.count("lebanon"),
        "Syria": all_text.count("syria"),
        "Yemen": all_text.count("yemen"),
        "Hezbollah": all_text.count("hezbollah"),
        "Houthi": all_text.count("houthi"),
        "Hamas": all_text.count("hamas"),
        "Gulf": all_text.count("gulf"),
        "Qatar": all_text.count("qatar")
    }
    ent_df = pd.DataFrame.from_dict(entities, orient="index", columns=["Mentions"]).sort_values("Mentions", ascending=False)
    fig = px.bar(ent_df.head(12), y="Mentions", color="Mentions", color_continuous_scale="reds", template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

with tab4:
    st.subheader("Live Market Impact (Oil, S&P 500, Gold)")

    c1, c2, c3 = st.columns(3)
    assets = {
        "Oil (WTI)": "CL=F",
        "S&P 500": "^GSPC",
        "Gold": "GC=F"
    }

    for name, ticker in assets.items():
        with (c1 if name == "Oil (WTI)" else c2 if name == "S&P 500" else c3):
            try:
                # Use Ticker.history for more stable single-ticker fetch
                ticker_obj = yf.Ticker(ticker)
                data = ticker_obj.history(period="14d", timeout=10)

                if data.empty or len(data) < 2:
                    st.warning(f"No recent data available for {name} ({ticker})")
                    st.caption("Possible weekend/holiday, market closed, or temporary Yahoo Finance delay")
                    continue

                # Explicitly extract scalar values (prevents Series formatting issues)
                last_close = float(data["Close"].iloc[-1])   # force float scalar
                prev_close = float(data["Close"].iloc[-2])

                delta = last_close - prev_close

                # Format safely (no direct Series formatting)
                if "Oil" in name or "Gold" in name:
                    value_str = f"${last_close:,.2f}"
                else:
                    value_str = f"{last_close:,.0f}"

                delta_str = f"{delta:+,.2f}"

                st.metric(
                    label=name,
                    value=value_str,
                    delta=delta_str
                )

                # Simple line chart (only if enough points)
                if len(data) >= 5:
                    st.line_chart(data["Close"], use_container_width=True, height=140)
                else:
                    st.caption("Not enough data points for chart")

            except Exception as e:
                error_msg = str(e)
                if "unsupported format" in error_msg.lower():
                    st.warning(f"Formatting issue for {name} – showing raw value")
                    # Fallback raw display if formatting fails
                    try:
                        raw_last = data["Close"].iloc[-1]
                        st.metric(name, f"Raw: {raw_last}", "N/A")
                    except:
                        st.metric(name, "Error", "N/A")
                else:
                    st.error(f"Error fetching {name}: {error_msg}")
                st.caption("Try refreshing or check later – yfinance is unofficial")

# ───────────────────────────────
# Auto-refresh logic
# ───────────────────────────────
if auto_refresh and (datetime.now() - last_update).total_seconds() > 300:
    st.rerun()

st.caption("100% free & local • RSS aggregation + trafilatura + VADER + yfinance • Respect source terms • Approximate analysis • Not financial advice")
