# app.py — Professional single-screen dashboard version

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

# Force NLTK data download (fixes previous error)
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)

nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

st.set_page_config(
    page_title="Iran–US–Israel Conflict Monitor",
    page_icon="🌍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ──── Professional Dark Theme + Layout CSS ────
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"]  {
        font-family: 'Inter', sans-serif;
    }
    .main {
        background: #0f172a;
        color: #e2e8f0;
        padding: 1.5rem 2rem;
    }
    .stApp > header {
        background: #0f172a !important;
    }
    h1 {
        color: #f1f5f9;
        font-weight: 700;
        letter-spacing: -0.5px;
        margin-bottom: 0.5rem !important;
    }
    .metric-card {
        background: linear-gradient(145deg, #1e293b, #334155);
        border: 1px solid #475569;
        border-radius: 12px;
        padding: 1.25rem;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.2), 0 2px 4px -1px rgba(0,0,0,0.1);
        text-align: center;
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-3px);
    }
    .live-dot {
        height: 10px;
        width: 10px;
        background-color: #22c55e;
        border-radius: 50%;
        display: inline-block;
        animation: pulse 2s infinite;
        margin-right: 6px;
    }
    @keyframes pulse {
        0% { opacity: 1; }
        50% { opacity: 0.4; }
        100% { opacity: 1; }
    }
    .stExpander {
        background: #1e293b !important;
        border: 1px solid #475569 !important;
        border-radius: 8px;
    }
    hr {
        border-color: #475569;
        margin: 1.8rem 0;
    }
    </style>
""", unsafe_allow_html=True)

# ──── Title & Subtitle ────
st.title("🌍 Iran – US – Israel Conflict Monitor")
st.markdown("**Real-time media sentiment & economic impact dashboard** • Powered by RSS aggregation, local NLP & live market data • Updated automatically")

# ──── Sidebar Controls ────
with st.sidebar:
    st.header("Dashboard Controls")
    max_articles = st.slider("Max articles", 80, 400, 180, step=20)
    fetch_full_text = st.checkbox("Extract full article text (better accuracy)", True)
    auto_refresh = st.checkbox("Auto-refresh every 5 min", True)

    if st.button("🔄 Refresh Now", type="primary", use_container_width=True):
        if "df" in st.session_state:
            del st.session_state.df
        st.rerun()

# ──── Data Fetch & Cache (same as before, abbreviated) ────
@st.cache_data(ttl=300)
def fetch_and_process(max_art, full_text):
    # ... (keep your existing fetch_news logic here – Google RSS + direct feeds + dedup + sentiment)
    # For brevity: assume it returns df with columns: title, url, source, date, datetime, text, sent_overall, sent_israel_us, sent_iran, hash
    # Return processed df
    pass  # ← Replace with your full fetch + compute_sentiment logic from previous versions

if "df" not in st.session_state:
    with st.spinner("Loading latest intelligence…"):
        st.session_state.df = fetch_and_process(max_articles, fetch_full_text)
        st.session_state.last_update = datetime.now()

df = st.session_state.df
last = st.session_state.last_update

# ──── KPI Cards (Top Row) ────
cols = st.columns([1,1,1.2,1])
with cols[0]:
    st.markdown(f'<div class="metric-card"><strong>Articles</strong><br><h2>{len(df):,}</h2><small>from 100+ sources</small></div>', unsafe_allow_html=True)

with cols[1]:
    avg_tone = df["sent_overall"].mean()
    tone_color = "#22c55e" if avg_tone > 0.05 else "#ef4444" if avg_tone < -0.05 else "#94a3b8"
    st.markdown(f'<div class="metric-card"><strong>Media Tone</strong><br><h2 style="color:{tone_color};">{avg_tone:.2f}</h2><small>(+ = more favorable to US/Israel)</small></div>', unsafe_allow_html=True)

with cols[2]:
    winner = "🇺🇸🇮🇱 US/Israel" if df["sent_israel_us"].mean() > df["sent_iran"].mean() else "🇮🇷 Iran"
    st.markdown(f'<div class="metric-card"><strong>Current Media Favor</strong><br><h2>{winner}</h2><small>based on sentence-level sentiment</small></div>', unsafe_allow_html=True)

with cols[3]:
    st.markdown(f'<div class="metric-card"><strong>Last Update</strong><br><span class="live-dot"></span>{last.strftime("%H:%M %d %b")}</div>', unsafe_allow_html=True)

st.markdown("---")

# ──── Main Layout: 2 Big Columns ────
left_col, right_col = st.columns([7, 3], gap="large")

# ──── LEFT COLUMN ──── (Charts & Trend – takes most space)
with left_col:
    st.subheader("Sentiment Trend – Who Appears Stronger in Coverage")

    daily = df.groupby("date").agg({
        "sent_israel_us": "mean",
        "sent_iran": "mean"
    }).reset_index()

    fig_trend = go.Figure()
    fig_trend.add_trace(go.Scatter(x=daily["date"], y=daily["sent_israel_us"],
                                   name="US/Israel Tone", line=dict(color="#22c55e", width=3)))
    fig_trend.add_trace(go.Scatter(x=daily["date"], y=daily["sent_iran"],
                                   name="Iran Tone", line=dict(color="#ef4444", width=3)))

    fig_trend.update_layout(
        template="plotly_dark",
        height=420,
        margin=dict(l=20, r=20, t=30, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified"
    )
    st.plotly_chart(fig_trend, use_container_width=True)

    # Market Charts – 3 small charts in row
    st.subheader("Economic & Market Signals")
    m1, m2, m3 = st.columns(3)

    assets = {"Oil (WTI)": "CL=F", "S&P 500": "^GSPC", "Gold": "GC=F"}

    for name, ticker in assets.items():
        with (m1 if name == "Oil (WTI)" else m2 if name == "S&P 500" else m3):
            try:
                tkr = yf.Ticker(ticker)
                hist = tkr.history(period="14d")
                if hist.empty or len(hist) < 2:
                    st.caption(f"No data – {name}")
                    continue

                last = float(hist["Close"].iloc[-1])
                delta = float(hist["Close"].iloc[-1] - hist["Close"].iloc[-2])

                val_fmt = f"${last:,.2f}" if "Oil" in name or "Gold" in name else f"{last:,.0f}"
                delta_fmt = f"{delta:+,.2f}"

                st.metric(name, val_fmt, delta_fmt)
                st.line_chart(hist["Close"], height=120, use_container_width=True)
            except:
                st.caption(f"Error – {name}")

# ──── RIGHT COLUMN ──── (Quick info, mentions, recent articles)
with right_col:
    st.subheader("Key Entities Mentioned")
    all_text = " ".join(df["text"]).lower()
    entities = {
        "Russia": all_text.count("russia"), "China": all_text.count("china"),
        "Turkey": all_text.count("turkey"), "Saudi": all_text.count("saudi"),
        "Lebanon": all_text.count("lebanon"), "Syria": all_text.count("syria"),
        "Yemen/Houthis": all_text.count("yemen") + all_text.count("houthi"),
        "Hezbollah": all_text.count("hezbollah"), "Hamas": all_text.count("hamas"),
        "Qatar": all_text.count("qatar")
    }
    ent_df = pd.DataFrame.from_dict(entities, orient="index", columns=["Mentions"]).sort_values("Mentions", ascending=False).head(10)
    fig_ent = px.bar(ent_df, y="Mentions", color="Mentions", color_continuous_scale="reds", template="plotly_dark")
    fig_ent.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=40))
    st.plotly_chart(fig_ent, use_container_width=True)

    st.subheader("Most Recent Articles")
    for _, row in df.head(8).iterrows():
        with st.expander(f"{row['title'][:80]}…"):
            st.caption(f"{row['source']} • {row['date']} • Tone: {row['sent_overall']:.2f}")
            st.markdown(f"[Read →]({row['url']})")
            st.write(row["text"][:300] + "…")

# ──── Footer & Auto-refresh ────
st.markdown("---")
st.caption(f"Last refresh: {last.strftime('%Y-%m-%d %H:%M:%S')} • 100% local/free • RSS + VADER + yfinance • Approximate media analysis • Not financial advice")

if auto_refresh and (datetime.now() - last).total_seconds() > 300:
    st.rerun()
