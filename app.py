import os, re, hashlib, concurrent.futures
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytz
import feedparser
from dateutil import parser
import trafilatura
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

import nltk
from nltk.tokenize import sent_tokenize
nltk.download('punkt', quiet=True)

IST = pytz.timezone('Asia/Kolkata')
st.set_page_config(page_title="War Pulse Live — Verified", page_icon="🌍", layout="wide")
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"]  { font-family: 'Inter', sans-serif; }
.stApp { background: linear-gradient(180deg,#0b1020 0%, #0e1427 100%); color:#e6edf3; }
.metric-card { background: rgba(22,27,34,.85); border:1px solid #30363d; border-radius:16px; padding:18px; text-align:center; box-shadow: 0 12px 40px rgba(0,0,0,.18); }
.metric-title { font-size:.78rem; color:#8b949e; text-transform:uppercase; font-weight:700; letter-spacing:.06em; margin-bottom:8px; }
.metric-value { font-size:2rem; font-weight:800; color:#fff; }
.live-dot { height: 10px; width: 10px; background-color: #ff6b6b; border-radius: 50%; display: inline-block; animation: pulse 1.5s infinite; margin-right: 8px; }
@keyframes pulse { 0% { opacity: 1; } 50% { opacity: .25; } 100% { opacity: 1; } }
.block { background: rgba(22,27,34,.75); border:1px solid #2f3743; border-radius:18px; padding:14px 16px; }
.small { color:#9da7b3; font-size:.86rem; }
</style>
""", unsafe_allow_html=True)

TRUSTED_DOMAINS = {
    "reuters.com": 1.00,
    "apnews.com": 0.98,
    "bloomberg.com": 0.96,
    "bbc.com": 0.94,
    "bbci.co.uk": 0.94,
    "wsj.com": 0.93,
    "ft.com": 0.93,
}
DISPLAY_ONLY_BLOCKLIST = {
    "middleeastmonitor.com", "newarab.com", "palestinechronicle.com",
    "middleeasteye.net", "mondoweiss.net"
}

MISSILE_WORDS = r"(?:ballistic\s+)?missiles?|rockets?|projectiles?"
DRONE_WORDS = r"drones?|uavs?|shaheds?"
NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
APPROX = r"(?:about|around|nearly|some|more than|over|at least|roughly|up to)?"

MISSILE_RE = re.compile(rf"\b{APPROX}\s*({NUM}|hundreds?|thousands?)\s+{MISSILE_WORDS}\b", re.I)
DRONE_RE = re.compile(rf"\b{APPROX}\s*({NUM}|hundreds?|thousands?)\s+{DRONE_WORDS}\b", re.I)
COMBINED_RE = re.compile(rf"\b{APPROX}\s*({NUM}|hundreds?|thousands?)\s+{MISSILE_WORDS}\s+(?:and|,)\s+{APPROX}\s*({NUM}|hundreds?|thousands?)\s+{DRONE_WORDS}\b|\b{APPROX}\s*({NUM}|hundreds?|thousands?)\s+{DRONE_WORDS}\s+(?:and|,)\s+{APPROX}\s*({NUM}|hundreds?|thousands?)\s+{MISSILE_WORDS}\b", re.I)
DEATH_RE = re.compile(rf"\b({APPROX}\s*{NUM}|hundreds?|thousands?)\s+(?:people|troops|soldiers|civilians|service members|americans|iranians|israelis|lebanese)?\s*(?:have been|were|was)?\s*(?:killed|dead|slain|deaths?)\b|\bdeath toll\b[^\d]{{0,20}}({NUM})", re.I)
INJURY_RE = re.compile(rf"\b({APPROX}\s*{NUM}|hundreds?|thousands?)\s+(?:people|troops|soldiers|civilians|service members|americans|iranians|israelis|lebanese)?\s*(?:have been|were|was)?\s*(?:injured|wounded)\b", re.I)
USD_LOSS_RE = re.compile(rf"\$\s*({NUM})\s*(billion|million|trillion|bn|mn|m|b|t)?\b", re.I)
SHEKEL_DOLLAR_HINT_RE = re.compile(r"\((?:about\s+)?\$\s*(\d+(?:\.\d+)?)\s*(billion|million|bn|mn|b|m)\)", re.I)

LOSS_CONTEXT = re.compile(r"\b(cost|damage|loss|losses|spending|defense spending|economic damage|war cost|budget boost|revised budget)\b", re.I)
PRICE_CONTEXT = re.compile(r"\b(barrel|brent|wti|gold|sp\s*500|shares?|stock|price|priced|trading|yield|market cap)\b", re.I)
INVENTORY_CONTEXT = re.compile(r"\bworth|range|payload|can carry|priced at|costs to make|each drone costs|per drone|interceptor\b", re.I)

IRAN_ACTOR = re.compile(r"\b(iran|iranian|tehran|irgc|hezbollah|houthi)\b", re.I)
US_ISRAEL_ACTOR = re.compile(r"\b(israel|israeli|idf|u\.s\.|united states|american|us military|pentagon)\b", re.I)
ISRAEL_TARGET = re.compile(r"\b(israel|israeli|tel aviv|jerusalem)\b", re.I)
IRAN_TARGET = re.compile(r"\b(iran|iranian|tehran|isfahan)\b", re.I)
US_TARGET = re.compile(r"\b(u\.s\.|american|us troops|u\.s. troops|service members|pentagon)\b", re.I)
GLOBAL_HINT = re.compile(r"\b(conflict|war|region|global|middle east|since late february|so far)\b", re.I)


def canonical_url(link: str) -> str:
    try:
        p = urlparse(link)
        host = p.netloc.lower().replace('www.', '')
        path = p.path
        if 'news.google.com' in host:
            qs = parse_qs(p.query)
            if 'url' in qs:
                return qs['url'][0]
        return f"{p.scheme}://{host}{path}"
    except Exception:
        return link


def source_domain(link: str) -> str:
    try:
        return urlparse(link).netloc.lower().replace('www.', '')
    except Exception:
        return ''


def source_weight(domain: str) -> float:
    for d, w in TRUSTED_DOMAINS.items():
        if domain.endswith(d):
            return w
    return 0.25


def parse_num(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return int(float(raw))

    s = str(raw).strip().lower()
    if not s:
        return None

    s = s.replace('+', '')
    s = re.sub(r'^(about|around|nearly|some|more than|over|at least|roughly|up to)\s+', '', s)

    if 'hundred' in s:
        return 200
    if 'thousand' in s:
        return 2000

    try:
        return int(float(s.replace(',', '')))
    except Exception:
        return None


def parse_money_m(raw_num: str, unit: str | None) -> float:
    x = float(raw_num.replace(',', ''))
    u = (unit or '').lower()
    if u in ('billion', 'bn', 'b'):
        return x * 1000
    if u in ('trillion', 't'):
        return x * 1_000_000
    if u in ('million', 'mn', 'm'):
        return x
    return x / 1_000_000


def format_money(m: float) -> str:
    if m <= 0:
        return '$0'
    if m >= 1000:
        return f"${m/1000:,.2f}B"
    return f"${m:,.0f}M"


def actor_from_text(t: str) -> str:
    if IRAN_ACTOR.search(t):
        return 'Iran'
    if US_ISRAEL_ACTOR.search(t):
        return 'US/Israel'
    return 'Unknown'


def impacted_side_from_text(t: str) -> str:
    if ISRAEL_TARGET.search(t):
        return 'Israel'
    if IRAN_TARGET.search(t):
        return 'Iran'
    if US_TARGET.search(t):
        return 'US'
    return 'Global'


def is_trusted_metric_source(domain: str) -> bool:
    return source_weight(domain) >= 0.93


def fetch_single_article(entry, fetch_full: bool):
    link = canonical_url(entry.link)
    try:
        pub = parser.parse(entry.get('published', '') or entry.get('updated', ''))
    except Exception:
        pub = datetime.now(IST)
    title = entry.get('title', '').strip()
    summary = entry.get('summary', '') or ''
    text = f"{title}. {summary}"
    if fetch_full:
        try:
            dl = trafilatura.fetch_url(link, timeout=6)
            if dl:
                ext = trafilatura.extract(dl, include_comments=False, include_tables=False) or ''
                text += ' ' + ext[:8000]
        except Exception:
            pass
    dom = source_domain(link)
    return {
        'title': title,
        'url': link,
        'domain': dom,
        'source': dom or entry.get('source', {}).get('title', 'unknown'),
        'datetime': pub,
        'date': pub.date(),
        'text': text[:9000],
        'hash': hashlib.md5((title + '|' + link).encode()).hexdigest()[:16],
        'trusted': is_trusted_metric_source(dom),
        'display_only': any(dom.endswith(x) for x in DISPLAY_ONLY_BLOCKLIST),
    }


@st.cache_data(ttl=300)
def fetch_news(max_articles: int, fetch_full: bool) -> pd.DataFrame:
    feeds = [
        "https://news.google.com/rss/search?q=Iran+Israel+US+war+missiles+drones+casualties+when:7d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Iran+Israel+US+war+cost+damage+losses+when:7d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=site:reuters.com+Iran+Israel+war+when:30d&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=site:apnews.com+Iran+Israel+war+when:30d&hl=en-US&gl=US&ceid=US:en",
        "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    ]
    raw_entries, seen = [], set()
    for url in feeds:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_articles]:
                link = canonical_url(entry.link)
                key = (entry.get('title', '').strip().lower(), link)
                if key not in seen:
                    seen.add(key)
                    raw_entries.append(entry)
        except Exception:
            pass

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(fetch_single_article, e, fetch_full) for e in raw_entries[:max_articles]]
        for f in concurrent.futures.as_completed(futs):
            try:
                rows.append(f.result())
            except Exception:
                pass
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.drop_duplicates(subset=['hash']).sort_values('datetime', ascending=False).reset_index(drop=True)
    return df


def extract_facts(df: pd.DataFrame) -> pd.DataFrame:
    facts = []
    for _, row in df.iterrows():
        text = row['text'] or ''
        sents = sent_tokenize(text)
        for i, sent in enumerate(sents):
            ctx = ' '.join(sents[max(0, i-1):min(len(sents), i+2)])
            lctx = ctx.lower()
            actor = actor_from_text(lctx)
            impacted = impacted_side_from_text(lctx)
            dom = row['domain']
            weight = source_weight(dom)

            # missiles+drones combined
            for m in COMBINED_RE.finditer(ctx):
                vals = [g for g in m.groups() if g]
                if len(vals) == 2:
                    first, second = vals[0], vals[1]
                    if 'drone' in m.group(0).lower().split('and')[0]:
                        drone_val, missile_val = parse_num(first), parse_num(second)
                    else:
                        missile_val, drone_val = parse_num(first), parse_num(second)
                    if missile_val is not None and missile_val <= 2000:
                        facts.append({'metric':'missiles','value':missile_val,'actor':actor,'impacted':'Global','source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})
                    if drone_val is not None and drone_val <= 5000:
                        facts.append({'metric':'drones','value':drone_val,'actor':actor,'impacted':'Global','source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})

            if not INVENTORY_CONTEXT.search(lctx):
                for m in MISSILE_RE.finditer(ctx):
                    v = parse_num(m.group(1))
                    if v is not None and v <= 2000:
                        facts.append({'metric':'missiles','value':v,'actor':actor,'impacted':'Global','source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})
                for m in DRONE_RE.finditer(ctx):
                    v = parse_num(m.group(1))
                    if v is not None and v <= 5000:
                        facts.append({'metric':'drones','value':v,'actor':actor,'impacted':'Global','source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})

            for m in DEATH_RE.finditer(ctx):
                raw = m.group(1) or m.group(2)
                if raw:
                    v = parse_num(raw)
                    if v <= 50000:
                        facts.append({'metric':'casualties','value':v,'actor':'N/A','impacted':impacted if impacted != 'Global' else 'Global','source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})
            for m in INJURY_RE.finditer(ctx):
                raw = m.group(1)
                if raw:
                    v = parse_num(raw)
                    if v <= 100000:
                        facts.append({'metric':'injuries','value':v,'actor':'N/A','impacted':impacted if impacted != 'Global' else 'Global','source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})

            if LOSS_CONTEXT.search(lctx) and not PRICE_CONTEXT.search(lctx) and not INVENTORY_CONTEXT.search(lctx):
                # prefer explicit USD hints in parentheses for shekel articles
                for hm in SHEKEL_DOLLAR_HINT_RE.finditer(ctx):
                    v = parse_money_m(hm.group(1), hm.group(2))
                    facts.append({'metric':'loss_usd_m','value':v,'actor':'N/A','impacted':impacted_side_from_text(lctx),'source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})
                for m in USD_LOSS_RE.finditer(ctx):
                    v = parse_money_m(m.group(1), m.group(2))
                    if 50 <= v <= 200000:
                        facts.append({'metric':'loss_usd_m','value':v,'actor':'N/A','impacted':impacted_side_from_text(lctx),'source':row['source'],'domain':dom,'url':row['url'],'date':row['date'],'sentence':ctx,'weight':weight})

    facts_df = pd.DataFrame(facts)
    if facts_df.empty:
        return facts_df
    facts_df = facts_df.drop_duplicates(subset=['metric','value','actor','impacted','url']).reset_index(drop=True)
    return facts_df


def resolve_metric(facts_df: pd.DataFrame, metric: str, actor: str | None = None, impacted: str | None = None) -> int | float:
    q = facts_df[facts_df['metric'] == metric].copy()
    if actor:
        q = q[q['actor'] == actor]
    if impacted:
        q = q[q['impacted'] == impacted]
    if q.empty:
        return 0
    # headline KPIs only from trusted sources
    tq = q[q['weight'] >= 0.93].copy()
    if not tq.empty:
        q = tq
    # recent, trusted, high value
    q = q.sort_values(['weight','date','value'], ascending=[False, False, False])
    return q.iloc[0]['value']


def top_evidence(facts_df: pd.DataFrame, metric: str, limit: int = 8) -> pd.DataFrame:
    q = facts_df[facts_df['metric'] == metric].copy()
    if q.empty:
        return q
    q = q.sort_values(['weight','date','value'], ascending=[False, False, False])
    return q.head(limit)


st.markdown("<h1 style='text-align:center;margin-bottom:0;'>War Pulse Live: Iran • Israel • U.S.</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:#9da7b3;margin-top:6px;'>Headline KPIs use only high-trust publishers. Lower-trust outlets can appear in the article list, but they do not drive the scoreboard.</p>", unsafe_allow_html=True)

with st.sidebar:
    st.header("Control Tower")
    max_articles = st.slider("Live article cap", 60, 400, 180, 20)
    fetch_full = st.toggle("Full-text extraction", value=True)
    st.caption("Tip: add NEWSAPI_KEY later only for broader discovery. Keep KPI resolution trusted-source-first.")
    if st.button("Force refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

with st.spinner("Scanning trusted coverage and resolving structured facts..."):
    articles_df = fetch_news(max_articles=max_articles, fetch_full=fetch_full)
    facts_df = extract_facts(articles_df)

if articles_df.empty:
    st.warning("No articles fetched.")
    st.stop()

missiles_iran = resolve_metric(facts_df, 'missiles', actor='Iran')
drones_iran = resolve_metric(facts_df, 'drones', actor='Iran')
cas_global = resolve_metric(facts_df, 'casualties', impacted='Global') or resolve_metric(facts_df, 'casualties')
inj_global = resolve_metric(facts_df, 'injuries')
loss_israel = resolve_metric(facts_df, 'loss_usd_m', impacted='Israel')
loss_us = resolve_metric(facts_df, 'loss_usd_m', impacted='US')
loss_iran = resolve_metric(facts_df, 'loss_usd_m', impacted='Iran')
total_loss = sum(v for v in [loss_israel, loss_us, loss_iran] if v)

c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.markdown(f"<div class='metric-card'><div class='metric-title'>Signals processed</div><div class='metric-value'>{len(articles_df)}</div></div>", unsafe_allow_html=True)
c2.markdown(f"<div class='metric-card'><div class='metric-title'>Iran missiles fired</div><div class='metric-value'>{int(missiles_iran):,}</div></div>", unsafe_allow_html=True)
c3.markdown(f"<div class='metric-card'><div class='metric-title'>Iran drones fired</div><div class='metric-value'>{int(drones_iran):,}</div></div>", unsafe_allow_html=True)
c4.markdown(f"<div class='metric-card'><div class='metric-title'>Resolved loss</div><div class='metric-value'>{format_money(total_loss)}</div></div>", unsafe_allow_html=True)
c5.markdown(f"<div class='metric-card'><div class='metric-title'>Global casualties</div><div class='metric-value'>{int(cas_global):,}</div></div>", unsafe_allow_html=True)
c6.markdown(f"<div class='metric-card'><div class='metric-title'>Global injuries</div><div class='metric-value'><span class='live-dot'></span>{int(inj_global):,}</div></div>", unsafe_allow_html=True)

left,right = st.columns([1.8,1], gap='large')
with left:
    st.markdown("### Kinetic timeline")
    if not facts_df.empty:
        daily = facts_df[facts_df['metric'].isin(['missiles','drones','casualties'])].copy()
        g = daily.groupby(['date','metric'], as_index=False)['value'].max()
        fig = go.Figure()
        colors = {'missiles':'#ff6b6b','drones':'#f6c453','casualties':'#a0aec0'}
        names = {'missiles':'Missiles','drones':'Drones','casualties':'Casualties'}
        for m in ['missiles','drones','casualties']:
            s = g[g.metric==m].sort_values('date')
            if not s.empty:
                s['value'] = s['value'].cummax()
                fig.add_trace(go.Scatter(x=s['date'], y=s['value'], mode='lines+markers', name=names[m], line=dict(width=3, color=colors[m])))
        fig.update_layout(template='plotly_dark', height=420, margin=dict(l=10,r=10,t=20,b=10), hovermode='x unified')
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("### Trusted evidence table")
    ev = top_evidence(facts_df, 'loss_usd_m', 6)
    if ev.empty:
        ev = top_evidence(facts_df, 'missiles', 6)
    if ev.empty:
        st.info('No structured facts extracted yet.')
    else:
        show = ev[['date','source','metric','value','impacted','sentence','url']].copy()
        st.dataframe(show, use_container_width=True, hide_index=True)

with right:
    st.markdown("### Resolved live scoreboard")
    board = pd.DataFrame([
        ['US', 0, 0, loss_us],
        ['Israel', 0, 0, loss_israel],
        ['Iran', int((missiles_iran or 0) + (drones_iran or 0)), 0, loss_iran],
        ['Global', int((missiles_iran or 0) + (drones_iran or 0)), int(cas_global or 0), total_loss],
    ], columns=['Side','Projectiles','Casualties','LossUSDm'])
    for _, r in board.iterrows():
        st.markdown(f"<div class='block'><div style='font-weight:800;font-size:1.02rem'>{r['Side']}</div><div class='small'>{int(r['Projectiles']):,} proj. • {int(r['Casualties']):,} casualties • {format_money(r['LossUSDm'])}</div></div>", unsafe_allow_html=True)
        st.write('')

    st.markdown("### Macro market shock")
    for name, tick in [('Brent','BZ=F'),('WTI','CL=F'),('Gold','GC=F'),('S&P 500','^GSPC')]:
        try:
            hist = yf.Ticker(tick).history(period='7d')
            if len(hist) >= 2:
                last, prev = hist['Close'].iloc[-1], hist['Close'].iloc[-2]
                st.metric(name, f"{last:,.2f}" if 'S&P' not in name else f"{last:,.2f}", f"{((last-prev)/prev)*100:+.2f}%")
        except Exception:
            st.caption(f"{name} offline")

st.markdown("### Article inventory")
disp = articles_df[['datetime','source','title','url','trusted']].copy()
disp['tier'] = disp['trusted'].map({True:'trusted', False:'other'})
st.dataframe(disp[['datetime','source','tier','title','url']], use_container_width=True, hide_index=True)

st.caption("Method note: KPIs are intentionally conservative. They resolve only from high-trust publishers and ignore weak-source headlines, market prices, and per-unit hardware cost phrases.")
