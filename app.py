# app.py — Professional single-screen dashboard (corrected formatting issues)

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

# Force NLTK data download at startup (fixes punkt_tab LookupError)
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

# ──── Professional Dark Theme CSS ────
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

# ──── Title ────
st.title("🌍 Iran – US – Israel Conflict Monitor")
st.markdown("**Real-time media sentiment & economic impact dashboard** • RSS aggregation + local NLP + live markets")

# ──── Sidebar ────
with st.sidebar:
    st.header("Controls")
    max_articles = st.slider("Max articles to keep", 80, 400, 180, step=20)
    fetch_full_text = st.checkbox("Extract full article text (better NLP)", True)
    auto_refresh = st.checkbox("Auto-refresh every 5 minutes", True)

    if st.button("🔄 Refresh Now", type="primary", use_container_width=True):
        if "df" in st.session_state:
            del st.session_state.df
        st.rerun()

# ─────────────────────────────────────────────────────────────
#                  DATA FETCHING & PROCESSING
# ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300, show_spinner="Fetching latest news...")
def fetch_news(max_articles, fetch_full):
    # ------------------- Your existing fetch logic -------------------
    # For this example I'm putting placeholder – replace with your real implementation
    # (Google News RSS + direct feeds + deduplication + VADER sentiment)

    # Placeholder – in real code replace this whole function body
    # with your previous working fetch + sentiment code

    # Example minimal structure:
    articles = []  # ← fill with real data
    df = pd.DataFrame(articles)

    # Add sentiment columns (you already have this logic)
    analyzer = SentimentIntensityAnalyzer()
    # ... your compute_sentiment function here ...

    return df  # must have: title, url, source, date, datetime, text, sent_overall, sent_israel_us, sent_iran

# Load or fetch data
if "df" not in st.session_state:
    with st.spinner("Loading latest intelligence…"):
        st.session_state.df = fetch_news(max_articles, fetch_full_text)
        st.session_state.last_update = datetime.now()

df = st.session_state.df
last_update = st.session_state.last_update

# ──── KPI CARDS (fixed formatting) ────
kpi1, kpi2, kpi3, kpi4 = st.columns([1, 1, 1.3, 1])

with kpi1:
    count_formatted = f"{len(df):,}"
    st.markdown(
        f'<div class="metric-card"><strong>Articles</strong><br><h2>{count_formatted}</h2><small>from multiple sources</small></div>',
        unsafe_allow_html=True
    )

with kpi2:
    avg_tone = float(df["sent_overall"].mean()) if not df.empty else 0.0
    tone_str = f"{avg_tone:.2f}"
    tone_color = "#22c55e" if avg_tone > 0.05 else "#ef4444" if avg_tone < -0.05 else "#94a3b8"
    st.markdown(
        f'<div class="metric-card"><strong>Media Tone</strong><br><h2 style="color:{tone_color};">{tone_str}</h2><small>(+ = pro US/Israel)</small></div>',
        unsafe_allow_html=True
    )

with kpi3:
    winner = "🇺🇸🇮🇱 US/Israel" if df["sent_israel_us"].mean() > df["sent_iran"].mean() else "🇮🇷 Iran"
    st.markdown(
        f'<div class="metric-card"><strong>Current Media Favor</strong><br><h2>{winner}</h2><small>tone-based</small></div>',
        unsafe_allow_html=True
    )

with kpi4:
    st.markdown(
        f'<div class="metric-card"><strong>Last Update</strong><br><span class="live-dot"></span>{last_update.strftime("%H:%M  %d %b")}</div>',
        unsafe_allow_html=True
    )

st.markdown("---")

# ──── MAIN LAYOUT ────
left, right = st.columns([7, 3], gap="large")

# LEFT ──────────────────────────────────────────────────────────
with left:
    st.subheader("Sentiment Trend – Media Perception Over Time")

    if not df.empty:
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

    # Markets ────────────────────────────────
    st.subheader("Market Impact Signals")
    mcol1, mcol2, mcol3 = st.columns(3)

    assets = {"Oil (WTI)": "CL=F", "S&P 500": "^GSPC", "Gold": "GC=F"}

    for name, ticker in assets.items():
        col = mcol1 if name == "Oil (WTI)" else mcol2 if name == "S&P 500" else mcol3
        with col:
            try:
                tkr = yf.Ticker(ticker)
                hist = tkr.history(period="14d")
                if hist.empty or len(hist) < 2:
                    st.caption(f"No recent data – {name}")
                    continue

                last = float(hist["Close"].iloc[-1])
                delta = last - float(hist["Close"].iloc[-2])

                val = f"${last:,.2f}" if "Oil" in name or "Gold" in name else f"{int(last):,}"
                deltastr = f"{delta:+,.2f}"

                st.metric(name, val, deltastr)
                st.line_chart(hist["Close"], height=120, use_container_width=True)
            except Exception as e:
                st.caption(f"Error – {name}")

# RIGHT ─────────────────────────────────────────────────────────
with right:
    st.subheader("Key Entities Mentioned")

    if not df.empty:
        text_all = " ".join(df["text"]).lower()
        entities = {
            "Russia": text_all.count("russia"),
            "China": text_all.count("china"),
            "Turkey": text_all.count("turkey"),
            "Saudi": text_all.count("saudi"),
            "Lebanon": text_all.count("lebanon"),
            "Syria": text_all.count("syria"),
            "Yemen/Houthis": text_all.count("yemen") + text_all.count("houthi"),
            "Hezbollah": text_all.count("hezbollah"),
            "Hamas": text_all.count("hamas"),
            "Qatar": text_all.count("qatar")
        }
        ent_df = pd.DataFrame.from_dict(entities, orient="index", columns=["Mentions"])\
                             .sort_values("Mentions", ascending=False).head(10)

        fig_bar = px.bar(ent_df, y="Mentions", color="Mentions",
                         color_continuous_scale="reds", template="plotly_dark")
        fig_bar.update_layout(height=340, margin=dict(l=10,r=10,t=10,b=50))
        st.plotly_chart(fig_bar, use_container_width=True)

    st.subheader("Recent Articles")
    if not df.empty:
        for _, row in df.head(7).iterrows():
            with st.expander(f"{row['title'][:70]}…"):
                st.caption(f"{row['source']} • {row['date']} • Tone: {row['sent_overall']:.2f}")
                st.markdown(f"[→ Read]({row['url']})")
                st.write(row["text"][:280] + "…")

# ──── Footer ────
st.markdown("---")
st.caption(
    f"Last refresh: {last_update.strftime('%Y-%m-%d %H:%M:%S')}  •  "
    "Fully local & free  •  RSS + VADER + yfinance  •  Approximate media tone analysis  •  Not financial advice"
)

# Auto-refresh
if auto_refresh and (datetime.now() - last_update).total_seconds() > 300:
    st.rerun()
