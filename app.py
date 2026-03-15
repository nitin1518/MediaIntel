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
import os
import re
from nltk.tokenize import sent_tokenize
import concurrent.futures
from streamlit_autorefresh import st_autorefresh

# --- NLTK CLOUD FIX ---
import nltk
nltk.download('punkt', quiet=True)
nltk.download('punkt_tab', quiet=True)
nltk_data_dir = os.path.join(os.getcwd(), "nltk_data")
os.makedirs(nltk_data_dir, exist_ok=True)
nltk.data.path.append(nltk_data_dir)

IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="Global Threat Matrix: Quant", page_icon="🌍", layout="wide")
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

# --- 1. AGGRESSIVE GRAMMAR & LOCATION BINDING ENGINE ---
class DeepGrammarExtractor:
    def __init__(self):
        # The number/metric regex
        self.cas_regex = re.compile(r'(?:death toll|killed|dead|casualties|fatalities|claimed lives of)[^\d]{0,40}?([\d,]{1,6})|([\d,]{1,6})\s+(?:people|civilians|soldiers|israelis|palestinians|iranians|lebanese|troops)?\s*(?:killed|dead|fatalities|casualties)', re.IGNORECASE)
        self.proj_regex = re.compile(r'([\d,]{1,5})\s+(?:ballistic\s+|cruise\s+|kamikaze\s+)?(missiles?|rockets?|drones?|projectiles?|uavs?)\b', re.IGNORECASE)
        
        # Geographic & Target Dictionaries (Object level)
        self.victims_iran = ['iran', 'tehran', 'isfahan', 'iranians', 'gaza', 'palestinians', 'lebanon', 'beirut', 'hezbollah', 'houthi']
        self.victims_israel = ['israel', 'israelis', 'tel aviv', 'jerusalem', 'idf']
        self.victims_us = ['us ', 'usa ', 'american', 'soldiers', 'troops', 'us base']
        self.victims_gulf = ['gulf', 'uae', 'saudi', 'iraq', 'syria', 'kuwait', 'oman']

    def _clean_number(self, num_str):
        if not num_str: return 0
        try: return int(num_str.replace(',', ''))
        except: return 0

    def extract(self, text):
        data = {
            "US_Israel": {"casualties": 0, "missiles": 0, "drones": 0},
            "Iran_Proxies": {"casualties": 0, "missiles": 0, "drones": 0},
            "Gulf_Others": {"casualties": 0, "missiles": 0, "drones": 0},
            "Global_Max": {"casualties": 0, "missiles": 0, "drones": 0}
        }

        for sent in sent_tokenize(text):
            sent_lower = sent.lower()
            
            # 1. COLLISION DETECTION: If it's summarizing the whole war, ignore specific attribution.
            is_macro_summary = bool(re.search(r'(israel[ -]iran|us[ -]israel[ -]iran|middle east war)', sent_lower))

            # 2. EXTRACT CASUALTIES
            for match in self.cas_regex.findall(sent_lower):
                num = max(self._clean_number(match[0]), self._clean_number(match[1]))
                if num == 0 or num > 100000: continue
                
                data["Global_Max"]["casualties"] = max(data["Global_Max"]["casualties"], num)

                if is_macro_summary: continue # Skip specific faction attribution if it's a macro summary (e.g., 2000 total)

                # Location-Binding: Check immediate 60-character radius for victim/location keywords
                idx = sent_lower.find(str(num))
                context = sent_lower[max(0, idx-60):min(len(sent_lower), idx+60)]
                
                # Resolving Faction based on Victim Location/Adjective, NOT the Attacker
                if any(v in context for v in self.victims_iran):
                    data["Iran_Proxies"]["casualties"] = max(data["Iran_Proxies"]["casualties"], num)
                elif any(v in context for v in self.victims_israel) or any(v in context for v in self.victims_us):
                    data["US_Israel"]["casualties"] = max(data["US_Israel"]["casualties"], num)
                elif any(v in context for v in self.victims_gulf):
                    data["Gulf_Others"]["casualties"] = max(data["Gulf_Others"]["casualties"], num)

            # 3. EXTRACT PROJECTILES (Slightly broader binding since attackers are often named with the weapon)
            for match in self.proj_regex.findall(sent_lower):
                num = self._clean_number(match[0])
                is_drone = 'drone' in match[1].lower() or 'uav' in match[1].lower()
                
                target_dict = "drones" if is_drone else "missiles"
                data["Global_Max"][target_dict] = max(data["Global_Max"][target_dict], num)
                
                if is_macro_summary: continue
                
                # For projectiles, if Iran/Proxies are the subject of firing, attribute to them
                if any(w in sent_lower for w in ['iran fired', 'tehran launched', 'hezbollah fired', 'houthi launched']):
                    data["Iran_Proxies"][target_dict] = max(data["Iran_Proxies"][target_dict], num)
                elif any(w in sent_lower for w in ['israel fired', 'idf launched', 'us struck']):
                    data["US_Israel"][target_dict] = max(data["US_Israel"][target_dict], num)

        return data

# --- 2. MULTITHREADED TIER-1 SCRAPER ---
def fetch_single_article(entry, fetch_full):
    link = entry.link.split("?")[0]
    pub = parser.parse(entry.published) if 'published' in entry else datetime.now(IST)
    text = f"{entry.title}. {entry.get('summary', '')}"
    
    if fetch_full:
        try:
            dl = trafilatura.fetch_url(link, timeout=4)
            if dl: text += " " + (trafilatura.extract(dl) or "")[:5000]
        except: pass
        
    return {
        "title": entry.title, "url": link, "source": entry.get('source', {}).get('title', 'Verified News'),
        "date": pub.date(), "datetime": pub, "text": text[:6000],
        "hash": hashlib.md5(text.encode()).hexdigest()[:12]
    }

@st.cache_data(ttl=300)
def fetch_tier1_news(max_articles, fetch_full):
    feeds = [
        "https://news.google.com/rss/search?q=Israel+Iran+US+conflict+when:1d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Israel+Iran+war+death+toll+OR+casualties&hl=en-US&gl=US&ceid=US:en",
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
                if link not in seen:
                    seen.add(link)
                    raw_entries.append(entry)
        except: continue

    articles = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(fetch_single_article, entry, fetch_full) for entry in raw_entries[:max_articles]]
        for future in concurrent.futures.as_completed(futures):
            try: articles.append(future.result())
            except: pass

    df = pd.DataFrame(articles)
    if df.empty: return df

    df = df.drop_duplicates(subset="hash").sort_values("datetime", ascending=False)
    
    kinetic = DeepGrammarExtractor()
    parsed_data = [kinetic.extract(text) for text in df["text"]]
        
    df["tot_cas"] = [d["Global_Max"]["casualties"] for d in parsed_data]
    df["tot_mis"] = [d["Global_Max"]["missiles"] for d in parsed_data]
    df["tot_dro"] = [d["Global_Max"]["drones"] for d in parsed_data]
    
    df["us_cas"] = [d["US_Israel"]["casualties"] for d in parsed_data]
    df["ir_cas"] = [d["Iran_Proxies"]["casualties"] for d in parsed_data]
    df["gulf_cas"] = [d["Gulf_Others"]["casualties"] for d in parsed_data]
    
    df["us_mis"] = [d["US_Israel"]["missiles"] for d in parsed_data]
    df["ir_mis"] = [d["Iran_Proxies"]["missiles"] for d in parsed_data]

    return df

# --- DASHBOARD RENDER ---
st.markdown("<h2 style='text-align: center;'>🌍 TACTICAL THREAT MATRIX & KINETIC TRACKER</h2>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚙️ Intel Constraints")
    max_articles = st.slider("Signal Volume (Max Links)", 50, 300, 200, step=50)
    if st.button("🔄 Force Deep Extraction", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Executing Directional Grammar Parsing on Live Trackers..."):
    df = fetch_tier1_news(max_articles, True)
    has_data = not df.empty

if not has_data:
    st.warning("⚠️ Telemetry Offline: Awaiting network sync.")
    st.stop()

# --- MACRO KPIs ---
total_missiles = df["tot_mis"].max()
total_drones = df["tot_dro"].max()
total_casualties = df["tot_cas"].max()

k1, k2, k3, k4, k5 = st.columns(5)
k1.markdown(f'<div class="metric-card"><div class="metric-title">Intel Signals</div><div class="metric-value">{len(df)}</div></div>', unsafe_allow_html=True)
k2.markdown(f'<div class="metric-card"><div class="metric-title">Missiles Fired</div><div class="metric-value" style="color: #ff7b72;">{int(total_missiles):,}</div></div>', unsafe_allow_html=True)
k3.markdown(f'<div class="metric-card"><div class="metric-title">Drones Launched</div><div class="metric-value" style="color: #d29922;">{int(total_drones):,}</div></div>', unsafe_allow_html=True)
k4.markdown(f'<div class="metric-card"><div class="metric-title">Global Casualties</div><div class="metric-value" style="color: #8b949e;">{int(total_casualties):,}</div></div>', unsafe_allow_html=True)
k5.markdown(f'<div class="metric-card"><div class="metric-title">System Status</div><div class="metric-value" style="font-size: 1.2rem;"><span class="live-dot"></span>LIVE<br><span style="font-size: 0.8rem; color: #8b949e;">{datetime.now(IST).strftime("%H:%M IST")}</span></div></div>', unsafe_allow_html=True)

st.write("---")

# --- ANALYTICS DASHBOARD ---
left, right = st.columns([2, 1], gap="large")

with left:
    tab1, tab2 = st.tabs(["📉 Segregated Kinetic Trends", "🔥 Cumulative Faction Breakdown"])
    
    with tab1:
        st.subheader("Reported Deployments Over Time")
        daily_trends = df.groupby("date").agg({
            "tot_cas": "max", "us_mis": "max", "ir_mis": "max"
        }).reset_index().sort_values("date")
        
        for col in ["tot_cas", "us_mis", "ir_mis"]:
            daily_trends[col] = daily_trends[col].cummax()

        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=daily_trends["date"], y=daily_trends["tot_cas"], name="Global Casualties", line=dict(color="#8b949e", width=4)))
        fig1.add_trace(go.Scatter(x=daily_trends["date"], y=daily_trends["us_mis"], name="US/Israel Missiles", line=dict(color="#58a6ff", width=2, dash="dash")))
        fig1.add_trace(go.Scatter(x=daily_trends["date"], y=daily_trends["ir_mis"], name="Iran Missiles", line=dict(color="#ff7b72", width=2, dash="dash")))
        
        fig1.update_layout(template="plotly_dark", hovermode="x unified", xaxis_title="")
        st.plotly_chart(fig1, use_container_width=True)

    with tab2:
        st.subheader("Attributed Warfare Volume (By Actor)")
        us_proj = df["us_mis"].max()
        ir_proj = df["ir_mis"].max()
        
        faction_data = pd.DataFrame({
            "Faction": ["US/Israel Posture", "Iran/Proxies Posture"],
            "Missiles Fired": [us_proj, ir_proj]
        })
        
        fig2 = px.bar(faction_data, x="Faction", y="Missiles Fired", color="Faction", 
                      color_discrete_map={"US/Israel Posture": "#58a6ff", "Iran/Proxies Posture": "#ff7b72"})
        fig2.update_layout(template="plotly_dark", showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

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
                    st.metric(name, val, f"{delta_pct:+.2f}%")
            except: st.caption(f"{name} Data Offline")

with right:
    st.subheader("⚖️ Segregated Casualty Impact")
    
    us_cas = df["us_cas"].max()
    ir_cas = df["ir_cas"].max()
    gulf_cas = df["gulf_cas"].max()
    
    if any(v > 0 for v in [us_cas, ir_cas, gulf_cas]):
        pie_df = pd.DataFrame({
            "Faction": ["US/Israel", "Iran/Proxies", "Gulf/Others"], 
            "Casualties": [us_cas, ir_cas, gulf_cas]
        })
        fig_pie = px.pie(pie_df, values='Casualties', names='Faction', hole=0.6, 
                         color='Faction', color_discrete_map={"US/Israel": "#58a6ff", "Iran/Proxies": "#ff7b72", "Gulf/Others": "#d29922"})
        fig_pie.update_layout(template="plotly_dark", margin=dict(t=0, b=0, l=0, r=0), height=250)
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("Awaiting explicit faction-attributed casualty data.")

    st.subheader("📡 High-Yield Tracker Reports")
    kinetic_df = df[(df['tot_mis'] > 0) | (df['tot_cas'] > 0)].sort_values(by='tot_cas', ascending=False).head(5)
    
    for _, r in kinetic_df.iterrows():
        tags = []
        if r['tot_cas'] > 0: tags.append(f"⚠️ {int(r['tot_cas']):,} Total Cas.")
        if r['tot_mis'] > 0: tags.append(f"🚀 {int(r['tot_mis']):,} Mis.")
        
        st.markdown(f"""
        <div class='metric-card' style='padding: 10px; margin-bottom: 8px; text-align: left;'>
            <a href='{r['url']}' target='_blank' style='color: #c9d1d9; text-decoration: none; font-weight: 600; font-size: 0.85rem;'>{r['title']}</a><br>
            <span style='color: #8b949e; font-size: 0.75rem;'>{r['source']}</span><br>
            <span style='color: #ff7b72; font-size: 0.8rem; font-weight: bold;'>{" | ".join(tags)}</span>
        </div>
        """, unsafe_allow_html=True)
