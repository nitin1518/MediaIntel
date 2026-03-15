import os
import re
import math
import hashlib
import concurrent.futures
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qs, unquote

import feedparser
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytz
import requests
import streamlit as st
import trafilatura
import yfinance as yf
from dateutil import parser as dtparser
from nltk.tokenize import sent_tokenize
from streamlit_autorefresh import st_autorefresh

# ---------------------------
# NLTK bootstrap
# ---------------------------
import nltk
nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)

IST = pytz.timezone("Asia/Kolkata")
UTC = timezone.utc

st.set_page_config(page_title="War Pulse Live — Verified", page_icon="🌍", layout="wide")
st_autorefresh(interval=5 * 60 * 1000, key="autorefresh")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: linear-gradient(180deg, #08111f 0%, #0d1117 55%, #0d1117 100%); color: #d7dee9; }
    .main .block-container { padding-top: 1.2rem; }
    .hero {
        background: radial-gradient(circle at top left, rgba(88,166,255,0.18), transparent 30%),
                    radial-gradient(circle at top right, rgba(255,123,114,0.16), transparent 28%),
                    linear-gradient(135deg, #0f1725 0%, #121a28 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 22px;
        padding: 24px 26px;
        margin-bottom: 18px;
        box-shadow: 0 18px 40px rgba(0,0,0,0.25);
    }
    .pill { display:inline-block; padding:6px 10px; border-radius:999px; font-size:12px; font-weight:700; letter-spacing:.04em; }
    .live { background:#1f3a2a; color:#7ee787; border:1px solid rgba(126,231,135,.25); }
    .muted { color:#93a0b4; }
    .metric-card {
        background: linear-gradient(180deg, rgba(22,27,34,0.95), rgba(17,22,29,0.95));
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 18px;
        padding: 16px 18px;
        min-height: 112px;
        box-shadow: 0 10px 22px rgba(0,0,0,0.16);
    }
    .metric-label { font-size: 12px; color:#8ea0b8; font-weight:700; text-transform:uppercase; letter-spacing:.06em; }
    .metric-value { font-size: 34px; font-weight:800; color:white; margin-top:8px; line-height:1; }
    .metric-sub { font-size: 12px; color:#90a1b8; margin-top:8px; }
    .panel {
        background: rgba(17,22,29,0.86);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 18px;
        padding: 14px 16px 6px;
        box-shadow: 0 10px 22px rgba(0,0,0,0.12);
        margin-bottom: 14px;
    }
    .article-card {
        background: rgba(17,22,29,0.88);
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 16px;
        padding: 12px 14px;
        margin-bottom: 10px;
    }
    a.clean-link { color: #d7dee9; text-decoration: none; font-weight: 700; }
    a.clean-link:hover { color: #8cc5ff; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------
# Source quality controls
# ---------------------------
TRUSTED_KPI_DOMAINS = {
    "reuters.com": 1.00,
    "apnews.com": 0.98,
    "bloomberg.com": 0.97,
    "bbc.com": 0.95,
    "wsj.com": 0.95,
    "ft.com": 0.95,
}
DISPLAY_ONLY_DOMAINS = {
    "aljazeera.com", "theguardian.com", "washingtonpost.com", "nytimes.com"
}
BLOCK_KPI_DOMAINS = {
    "newarab.com", "middleeastmonitor.com", "palestinechronicle.com",
    "middleeasteye.net", "timesofindia.indiatimes.com", "nypost.com"
}

RSS_FEEDS = [
    "http://feeds.reuters.com/reuters/worldNews",
    "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "https://apnews.com/hub/apf-topnews?output=rss",
    "https://news.google.com/rss/search?q=(Iran+Israel+US+war)+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(Iran+missiles+drones+Israel)+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(Iran+war+casualties+injuries)+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=(Iran+war+cost+damage+Israel+US)+when:7d&hl=en-US&gl=US&ceid=US:en",
]

ACTOR_SYNONYMS = {
    "Iran": ["iran", "iranian", "tehran", "irgc"],
    "Israel": ["israel", "israeli", "idf", "tel aviv", "jerusalem"],
    "US": ["u.s.", "us ", "usa", "american", "pentagon", "u.s. troops", "us troops"],
    "Lebanon": ["lebanon", "lebanese", "beirut", "hezbollah"],
    "Gulf": ["gulf", "bahrain", "uae", "saudi", "kuwait", "oman", "iraq", "syria"],
}

GLOBAL_SCOPE_TERMS = [
    "so far", "since the war began", "since late february", "overall", "in the conflict",
    "death toll", "toll has reached", "have been killed", "have died", "have been injured",
    "since the onset of the conflict", "since the start of the war"
]
SUBGROUP_TERMS = [
    "troops", "service members", "health workers", "children", "journalists", "medics",
    "hospital", "healthcare", "aid workers", "officers", "soldiers", "civilians"
]
LOSS_TERMS = [
    "damage", "damages", "loss", "losses", "cost", "costs", "war cost", "defense spending",
    "budget", "economic damage", "economic toll", "fiscal burden", "property damage"
]
LOSS_EXCLUDE_TERMS = [
    "barrel", "per barrel", "stock", "stocks", "market cap", "share price", "priced at",
    "each drone costs", "cost-effective", "range", "payload", "yield", "per day"  # per-day excluded from headline KPI
]

COMBINED_PROJECTILE_RE = re.compile(
    r"(?P<n1>over\s+\d[\d,]*|more than\s+\d[\d,]*|nearly\s+\d[\d,]*|at least\s+\d[\d,]*|\d[\d,]*|hundreds|dozens|scores)\s+"
    r"(?P<t1>ballistic\s+missiles?|cruise\s+missiles?|missiles?|rockets?)"
    r"(?:[^.]{0,80}?)\b(?:and|plus|as well as)\b(?:[^.]{0,30}?)"
    r"(?P<n2>over\s+\d[\d,]*|more than\s+\d[\d,]*|nearly\s+\d[\d,]*|at least\s+\d[\d,]*|\d[\d,]*|hundreds|dozens|scores)\s+"
    r"(?P<t2>drones?|uavs?)",
    re.I,
)
SINGLE_PROJECTILE_RE = re.compile(
    r"(?P<n>over\s+\d[\d,]*|more than\s+\d[\d,]*|nearly\s+\d[\d,]*|at least\s+\d[\d,]*|\d[\d,]*|hundreds|dozens|scores)\s+"
    r"(?P<t>ballistic\s+missiles?|cruise\s+missiles?|missiles?|rockets?|drones?|uavs?)\b",
    re.I,
)
CASUALTY_RE = re.compile(
    r"(?:(?:at least|more than|over|nearly|about|around)\s+)?(?P<n>[\d,]+)\s+(?P<kind>killed|dead|deaths|fatalities|injured|wounded|injuries)\b",
    re.I,
)
CASUALTY_TOLL_RE = re.compile(
    r"(?:death toll|toll|casualties?)(?:\s+(?:has\s+)?(?:reached|rose to|stands at|of))?[^\d]{0,20}(?P<n>[\d,]+)",
    re.I,
)
MONEY_RE = re.compile(
    r"(?:\$|usd\s*)(?P<n>[\d,.]+)\s*(?P<unit>million|billion|trillion|m|b|t)?\b",
    re.I,
)
ILS_MONEY_RE = re.compile(
    r"(?P<n>[\d,.]+)\s*(?P<unit>billion|million|m|b)?\s+shekels?\b(?:\s*\((?:about\s*)?\$(?P<usd>[\d,.]+)\s*(?P<usd_unit>billion|million|m|b)?\))?",
    re.I,
)


# ---------------------------
# Utility helpers
# ---------------------------
def parse_num(raw):
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().lower()
    if not s:
        return None
    for prefix in ["about ", "around ", "approximately ", "approx. ", "at least ", "more than ", "over ", "nearly ", "some "]:
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = s.replace(",", "").replace("+", "")
    word_map = {"dozens": 24.0, "scores": 40.0, "hundreds": 300.0, "thousands": 3000.0}
    if s in word_map:
        return word_map[s]
    mult = 1.0
    if s.endswith("k"):
        mult, s = 1_000.0, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000.0, s[:-1]
    elif s.endswith("b"):
        mult, s = 1_000_000_000.0, s[:-1]
    elif s.endswith("t"):
        mult, s = 1_000_000_000_000.0, s[:-1]
    try:
        return float(s) * mult
    except Exception:
        return None


def money_to_usd_m(value, unit):
    base = parse_num(value)
    if base is None:
        return None
    unit = (unit or "").lower()
    if unit in {"billion", "b"}:
        return base * 1000.0
    if unit in {"million", "m"}:
        return base
    if unit in {"trillion", "t"}:
        return base * 1_000_000.0
    return base / 1_000_000.0


def fmt_money_m(v):
    if not v or pd.isna(v):
        return "$0"
    if v >= 1000:
        return f"${v/1000:,.2f}B"
    return f"${v:,.0f}M"


def parse_dt(value):
    if not value:
        return datetime.now(UTC)
    try:
        dt = dtparser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return datetime.now(UTC)


def canonical_url(url):
    if not url:
        return ""
    try:
        p = urlparse(url)
        if "news.google.com" in p.netloc and "/rss/articles/" in p.path:
            qs = parse_qs(p.query)
            if "url" in qs:
                return qs["url"][0]
        cleaned = f"{p.scheme}://{p.netloc}{p.path}"
        return cleaned.rstrip("/")
    except Exception:
        return url


def root_domain(url):
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def source_weight(domain):
    if domain in TRUSTED_KPI_DOMAINS:
        return TRUSTED_KPI_DOMAINS[domain]
    if domain in BLOCK_KPI_DOMAINS:
        return 0.10
    if domain in DISPLAY_ONLY_DOMAINS:
        return 0.55
    return 0.35


def is_kpi_eligible(domain):
    return domain in TRUSTED_KPI_DOMAINS


def detect_regions(text):
    text_l = text.lower()
    hits = []
    for region, words in ACTOR_SYNONYMS.items():
        if any(w in text_l for w in words):
            hits.append(region)
    return hits


def classify_scope(metric, sent_l, regions):
    if any(term in sent_l for term in GLOBAL_SCOPE_TERMS):
        return "global_total"
    if len(regions) == 1 and metric in {"casualties", "injuries"}:
        if any(term in sent_l for term in SUBGROUP_TERMS):
            return "subgroup_total"
        return "country_total"
    if any(term in sent_l for term in SUBGROUP_TERMS):
        return "subgroup_total"
    return "incident_count"


def dedupe_key(title, url):
    s = (title or "") + "|" + (canonical_url(url) or "")
    return hashlib.md5(s.encode()).hexdigest()[:16]


# ---------------------------
# Ingestion
# ---------------------------
def fetch_single_entry(entry, fetch_full=True):
    url = canonical_url(entry.get("link", ""))
    title = entry.get("title", "")
    published = parse_dt(entry.get("published") or entry.get("updated") or entry.get("pubDate"))
    summary = entry.get("summary", "")

    text = f"{title}. {summary}"
    if fetch_full and url:
        try:
            downloaded = trafilatura.fetch_url(url, timeout=8)
            if downloaded:
                extracted = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
                if extracted:
                    text += " " + extracted[:12000]
        except Exception:
            pass

    domain = root_domain(url)
    source = entry.get("source", {}).get("title") or domain or "unknown"
    return {
        "title": title,
        "url": url,
        "domain": domain,
        "source": source,
        "published": published,
        "date": published.date(),
        "text": text[:14000],
        "dedupe": dedupe_key(title, url),
        "kpi_eligible": is_kpi_eligible(domain),
        "source_weight": source_weight(domain),
    }


@st.cache_data(ttl=300)
def build_articles(max_articles=180, fetch_full=True):
    entries = []
    seen = set()
    for feed_url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:max_articles]:
                key = dedupe_key(entry.get("title", ""), entry.get("link", ""))
                if key not in seen:
                    seen.add(key)
                    entries.append(entry)
        except Exception:
            continue

    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(fetch_single_entry, e, fetch_full) for e in entries[:max_articles]]
        for fut in concurrent.futures.as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception:
                pass

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset=["dedupe"]).sort_values("published", ascending=False).reset_index(drop=True)
    return df


# ---------------------------
# Fact extraction
# ---------------------------
def extract_facts(articles_df: pd.DataFrame) -> pd.DataFrame:
    facts = []
    if articles_df.empty:
        return pd.DataFrame()

    for _, row in articles_df.iterrows():
        text = row["text"] or ""
        try:
            sents = sent_tokenize(text)
        except Exception:
            sents = [text]

        for i, sent in enumerate(sents):
            sent_l = sent.lower()
            ctx = " ".join(sents[max(0, i-1):min(len(sents), i+2)]).lower()
            regions = detect_regions(ctx)

            # Combined projectile pattern first
            for m in COMBINED_PROJECTILE_RE.finditer(sent):
                values = [
                    (m.group("n1"), m.group("t1")),
                    (m.group("n2"), m.group("t2")),
                ]
                actor = None
                if any(x in ctx for x in ACTOR_SYNONYMS["Iran"]):
                    actor = "Iran"
                elif any(x in ctx for x in ACTOR_SYNONYMS["Israel"]):
                    actor = "Israel"
                elif any(x in ctx for x in ACTOR_SYNONYMS["US"]):
                    actor = "US"
                for raw_n, weapon in values:
                    v = parse_num(raw_n)
                    if v is None or v <= 0 or v > 10000:
                        continue
                    metric = "drones_fired" if re.search(r"drone|uav", weapon, re.I) else "missiles_fired"
                    facts.append({
                        "article_title": row["title"], "url": row["url"], "domain": row["domain"],
                        "published": row["published"], "metric": metric, "value": float(v),
                        "scope_type": "global_total" if "so far" in ctx or "since" in ctx else "country_total",
                        "scope_region": actor or "Unknown", "actor": actor or "Unknown", "target": None,
                        "confidence": 0.93 * row["source_weight"], "evidence": sent.strip(),
                        "kpi_eligible": row["kpi_eligible"],
                    })

            # Single projectile pattern
            for m in SINGLE_PROJECTILE_RE.finditer(sent):
                v = parse_num(m.group("n"))
                if v is None or v <= 0 or v > 10000:
                    continue
                weapon = m.group("t")
                if any(ex in ctx for ex in ["range", "payload", "can carry", "capable of"]):
                    continue
                metric = "drones_fired" if re.search(r"drone|uav", weapon, re.I) else "missiles_fired"
                actor = None
                if any(x in ctx for x in ACTOR_SYNONYMS["Iran"]):
                    actor = "Iran"
                elif any(x in ctx for x in ACTOR_SYNONYMS["Israel"]):
                    actor = "Israel"
                elif any(x in ctx for x in ACTOR_SYNONYMS["US"]):
                    actor = "US"
                facts.append({
                    "article_title": row["title"], "url": row["url"], "domain": row["domain"],
                    "published": row["published"], "metric": metric, "value": float(v),
                    "scope_type": "global_total" if "so far" in ctx or "since" in ctx else "country_total",
                    "scope_region": actor or "Unknown", "actor": actor or "Unknown", "target": None,
                    "confidence": 0.78 * row["source_weight"], "evidence": sent.strip(),
                    "kpi_eligible": row["kpi_eligible"],
                })

            # Casualties / injuries
            for m in CASUALTY_RE.finditer(sent):
                v = parse_num(m.group("n"))
                if v is None or v <= 0 or v > 500000:
                    continue
                kind = m.group("kind").lower()
                metric = "injuries" if kind in {"injured", "wounded", "injuries"} else "casualties"
                scope_type = classify_scope(metric, ctx, regions)
                region = regions[0] if len(regions) == 1 else ("Global" if scope_type == "global_total" else "Unknown")
                subgroup = next((term for term in SUBGROUP_TERMS if term in ctx), None)
                facts.append({
                    "article_title": row["title"], "url": row["url"], "domain": row["domain"],
                    "published": row["published"], "metric": metric, "value": float(v),
                    "scope_type": scope_type, "scope_region": region, "actor": None, "target": region,
                    "subgroup": subgroup, "confidence": 0.82 * row["source_weight"],
                    "evidence": sent.strip(), "kpi_eligible": row["kpi_eligible"],
                })

            for m in CASUALTY_TOLL_RE.finditer(sent):
                v = parse_num(m.group("n"))
                if v is None or v <= 0 or v > 500000:
                    continue
                scope_type = "global_total" if any(t in ctx for t in GLOBAL_SCOPE_TERMS) else "country_total"
                region = regions[0] if len(regions) == 1 and scope_type == "country_total" else "Global"
                facts.append({
                    "article_title": row["title"], "url": row["url"], "domain": row["domain"],
                    "published": row["published"], "metric": "casualties", "value": float(v),
                    "scope_type": scope_type, "scope_region": region, "actor": None, "target": region,
                    "subgroup": None, "confidence": 0.8 * row["source_weight"],
                    "evidence": sent.strip(), "kpi_eligible": row["kpi_eligible"],
                })

            # Losses in shekels with usd in parentheses
            for m in ILS_MONEY_RE.finditer(sent):
                if not any(term in ctx for term in LOSS_TERMS):
                    continue
                if any(term in ctx for term in LOSS_EXCLUDE_TERMS):
                    continue
                usd_val = money_to_usd_m(m.group("usd"), m.group("usd_unit")) if m.group("usd") else None
                if usd_val is None:
                    continue
                region = regions[0] if regions else "Unknown"
                facts.append({
                    "article_title": row["title"], "url": row["url"], "domain": row["domain"],
                    "published": row["published"], "metric": "economic_loss_usd_m", "value": float(usd_val),
                    "scope_type": "country_total", "scope_region": region, "actor": None, "target": region,
                    "subgroup": None, "confidence": 0.92 * row["source_weight"],
                    "evidence": sent.strip(), "kpi_eligible": row["kpi_eligible"],
                })

            # Dollar losses
            for m in MONEY_RE.finditer(sent):
                if not any(term in ctx for term in LOSS_TERMS):
                    continue
                if any(term in ctx for term in LOSS_EXCLUDE_TERMS):
                    continue
                if any(term in ctx for term in ["price of oil", "crude", "gold", "s&p", "stocks", "shares"]):
                    continue
                usd_m = money_to_usd_m(m.group("n"), m.group("unit"))
                if usd_m is None or usd_m <= 0 or usd_m > 500000:
                    continue
                region = regions[0] if regions else "Unknown"
                facts.append({
                    "article_title": row["title"], "url": row["url"], "domain": row["domain"],
                    "published": row["published"], "metric": "economic_loss_usd_m", "value": float(usd_m),
                    "scope_type": "country_total", "scope_region": region, "actor": None, "target": region,
                    "subgroup": None, "confidence": 0.75 * row["source_weight"],
                    "evidence": sent.strip(), "kpi_eligible": row["kpi_eligible"],
                })

    if not facts:
        return pd.DataFrame()
    facts_df = pd.DataFrame(facts)
    facts_df["date"] = pd.to_datetime(facts_df["published"]).dt.date
    return facts_df


# ---------------------------
# Resolution
# ---------------------------
def resolve_metric(facts_df, metric, scope_type=None, region=None, actor=None, require_kpi=True):
    if facts_df.empty:
        return None
    q = facts_df[facts_df["metric"] == metric].copy()
    if scope_type is not None:
        q = q[q["scope_type"] == scope_type]
    if region is not None:
        q = q[q["scope_region"] == region]
    if actor is not None:
        q = q[q["actor"] == actor]
    if require_kpi:
        q = q[q["kpi_eligible"] == True]
    if q.empty:
        return None

    q["age_hours"] = (pd.Timestamp.utcnow().tz_localize(None) - pd.to_datetime(q["published"]).dt.tz_convert(None)).dt.total_seconds() / 3600.0
    q["age_penalty"] = q["age_hours"].clip(lower=0).apply(lambda x: math.exp(-x / 72.0))
    q["score"] = q["confidence"] * q["age_penalty"]

    # For global casualty/injury, avoid subgroup counts completely.
    if metric in {"casualties", "injuries"} and scope_type == "global_total":
        q = q[q["subgroup"].isna()]
        if q.empty:
            return None

    # Choose high-score cluster by value frequency/quality
    top = q.sort_values(["score", "value"], ascending=[False, False]).head(20)
    top["bucket"] = top["value"].round(-1 if metric in {"casualties", "injuries", "missiles_fired", "drones_fired"} else 0)
    bucket_scores = top.groupby("bucket")["score"].sum().sort_values(ascending=False)
    chosen_bucket = bucket_scores.index[0]
    chosen = top[top["bucket"] == chosen_bucket].sort_values(["score", "published"], ascending=[False, False])
    best = chosen.iloc[0].to_dict()
    best["support_count"] = int(len(chosen))
    return best


def build_scoreboard(facts_df):
    resolved = {
        "missiles": resolve_metric(facts_df, "missiles_fired", scope_type="global_total"),
        "drones": resolve_metric(facts_df, "drones_fired", scope_type="global_total"),
        "global_casualties": resolve_metric(facts_df, "casualties", scope_type="global_total"),
        "global_injuries": resolve_metric(facts_df, "injuries", scope_type="global_total"),
        "us_injuries": resolve_metric(facts_df, "injuries", scope_type="country_total", region="US"),
        "lebanon_casualties": resolve_metric(facts_df, "casualties", scope_type="country_total", region="Lebanon"),
        "israel_loss": resolve_metric(facts_df, "economic_loss_usd_m", scope_type="country_total", region="Israel"),
        "us_loss": resolve_metric(facts_df, "economic_loss_usd_m", scope_type="country_total", region="US"),
        "iran_loss": resolve_metric(facts_df, "economic_loss_usd_m", scope_type="country_total", region="Iran"),
    }
    return resolved


# ---------------------------
# UI helpers
# ---------------------------
def metric_card(label, value, sub):
    st.markdown(
        f"""
        <div class='metric-card'>
            <div class='metric-label'>{label}</div>
            <div class='metric-value'>{value}</div>
            <div class='metric-sub'>{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def safe_value(resolved, default="—", money=False):
    if not resolved:
        return default
    v = resolved.get("value")
    if money:
        return fmt_money_m(v)
    try:
        return f"{int(v):,}"
    except Exception:
        return default


# ---------------------------
# Build app
# ---------------------------
with st.sidebar:
    st.header("Control Tower")
    max_articles = st.slider("Live article cap", 60, 400, 180, step=20)
    fetch_full = st.toggle("Deep article fetch", value=True)
    if st.button("Force refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("KPI cards only use a trusted publisher allowlist. Wider media remains visible in the article inventory.")

with st.spinner("Parsing live conflict coverage and resolving evidence..."):
    articles_df = build_articles(max_articles=max_articles, fetch_full=fetch_full)
    facts_df = extract_facts(articles_df)
    resolved = build_scoreboard(facts_df)

if articles_df.empty:
    st.warning("No articles were loaded.")
    st.stop()

st.markdown(
    f"""
    <div class='hero'>
        <div class='pill live'>LIVE INTEL</div>
        <h1 style='margin:10px 0 8px 0;'>War Pulse Live: Iran • Israel • U.S.</h1>
        <div class='muted' style='font-size:15px;'>Headline metrics are resolved only from trusted publishers, and casualty scope is separated into global totals, country totals, and subgroup counts so small subset numbers do not overwrite the main conflict toll.</div>
        <div class='muted' style='margin-top:12px;'>Last refresh: {datetime.now(IST).strftime('%d %b %Y • %H:%M IST')} • Signals processed: {len(articles_df):,} articles • {len(facts_df):,} extracted facts</div>
    </div>
    """,
    unsafe_allow_html=True,
)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    metric_card("Missiles fired", safe_value(resolved["missiles"]), "Trusted global salvo estimate")
with c2:
    metric_card("Drones fired", safe_value(resolved["drones"]), "Trusted global drone estimate")
with c3:
    metric_card("Global casualties", safe_value(resolved["global_casualties"]), "Only explicit conflict-wide totals")
with c4:
    metric_card("Global injuries", safe_value(resolved["global_injuries"]), "Only explicit conflict-wide totals")
with c5:
    total_loss = sum((resolved[k]["value"] if resolved[k] else 0) for k in ["us_loss", "israel_loss", "iran_loss"])
    metric_card("Resolved loss", fmt_money_m(total_loss), "US + Israel + Iran loss rows with trusted evidence")

left, right = st.columns([1.6, 1], gap="large")

with left:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    st.subheader("Kinetic trendline")
    if not facts_df.empty:
        trends = facts_df[facts_df["kpi_eligible"] == True].copy()
        trends = trends[trends["scope_type"].isin(["global_total", "country_total"])]
        daily = trends.groupby(["date", "metric"], as_index=False)["value"].max()
        fig = go.Figure()
        for metric, color, name in [
            ("missiles_fired", "#ff7b72", "Missiles"),
            ("drones_fired", "#d29922", "Drones"),
            ("casualties", "#8b949e", "Casualties"),
            ("injuries", "#58a6ff", "Injuries"),
        ]:
            subset = daily[daily["metric"] == metric].sort_values("date")
            if not subset.empty:
                subset["value"] = subset["value"].cummax()
                fig.add_trace(go.Scatter(x=subset["date"], y=subset["value"], mode="lines+markers", name=name, line=dict(width=3, color=color)))
        fig.update_layout(template="plotly_dark", height=360, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    st.subheader("Trusted evidence table")
    trusted_facts = facts_df[facts_df["kpi_eligible"] == True].copy() if not facts_df.empty else pd.DataFrame()
    if not trusted_facts.empty:
        show = trusted_facts.sort_values(["published", "confidence"], ascending=[False, False])[ ["published", "domain", "metric", "value", "scope_type", "scope_region", "subgroup", "evidence"] ].head(30)
        st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("No trusted fact rows extracted yet.")
    st.markdown("</div>", unsafe_allow_html=True)

with right:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    st.subheader("Resolved live scoreboard")
    rows = []
    for name, proj_key, cas_key, inj_key, loss_key in [
        ("US", None, None, "us_injuries", "us_loss"),
        ("Israel", None, None, None, "israel_loss"),
        ("Iran", None, None, None, "iran_loss"),
        ("Global", "missiles", "global_casualties", "global_injuries", None),
    ]:
        rows.append({
            "Entity": name,
            "Projectiles": safe_value(resolved.get(proj_key)) if proj_key else "—",
            "Casualties": safe_value(resolved.get(cas_key)) if cas_key else "—",
            "Injuries": safe_value(resolved.get(inj_key)) if inj_key else "—",
            "Loss": fmt_money_m(resolved[loss_key]["value"]) if loss_key and resolved.get(loss_key) else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    st.subheader("Macro market shock")
    cols = st.columns(2)
    tickers = [("Brent", "BZ=F"), ("WTI", "CL=F"), ("Gold", "GC=F"), ("S&P 500", "^GSPC")]
    for idx, (name, tick) in enumerate(tickers):
        with cols[idx % 2]:
            try:
                hist = yf.Ticker(tick).history(period="7d")
                if len(hist) >= 2:
                    last = hist["Close"].iloc[-1]
                    prev = hist["Close"].iloc[-2]
                    delta = ((last - prev) / prev) * 100
                    val = f"{last:,.2f}" if name == "S&P 500" else f"${last:,.2f}"
                    st.metric(name, val, f"{delta:+.2f}%")
            except Exception:
                st.caption(f"{name} offline")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    st.subheader("Top source-backed reports")
    top_articles = articles_df.sort_values(["kpi_eligible", "source_weight", "published"], ascending=[False, False, False]).head(10)
    for _, r in top_articles.iterrows():
        st.markdown(
            f"<div class='article-card'><a class='clean-link' href='{r['url']}' target='_blank'>{r['title']}</a><br><span class='muted'>{r['domain']}</span></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("<div class='panel'>", unsafe_allow_html=True)
st.subheader("Article inventory")
show_articles = articles_df[["published", "domain", "title", "url", "kpi_eligible"]].copy().head(60)
st.dataframe(show_articles, use_container_width=True, hide_index=True)
st.markdown("</div>", unsafe_allow_html=True)
