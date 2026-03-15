import os
import re
import math
import json
import html
import hashlib
import statistics
import concurrent.futures as cf
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import trafilatura
import yfinance as yf
from dateutil import parser as dtparser
from nltk.tokenize import sent_tokenize
from streamlit_autorefresh import st_autorefresh

# Optional helpers
try:
    from word2number import w2n
except Exception:
    w2n = None

# --- NLTK bootstrap ---
import nltk
nltk.download("punkt", quiet=True)
nltk.download("punkt_tab", quiet=True)

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

# =========================
# PAGE CONFIG
# =========================
st.set_page_config(
    page_title="War Pulse Live | Iran • Israel • U.S.",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)
st_autorefresh(interval=5 * 60 * 1000, key="auto_refresh")

# =========================
# STYLE
# =========================
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {font-family:'Inter',sans-serif;}
.stApp {
    background:
        radial-gradient(circle at top left, rgba(56,189,248,0.12), transparent 32%),
        radial-gradient(circle at top right, rgba(248,113,113,0.10), transparent 28%),
        linear-gradient(180deg, #07111d 0%, #0b1220 45%, #0f172a 100%);
    color: #e5edf8;
}
.block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
.hero {
    padding: 1.25rem 1.4rem;
    border: 1px solid rgba(148,163,184,0.18);
    background: linear-gradient(135deg, rgba(15,23,42,0.92), rgba(2,6,23,0.76));
    border-radius: 22px;
    box-shadow: 0 18px 60px rgba(0,0,0,0.28);
    margin-bottom: 1rem;
}
.kpi-card, .glass-card {
    background: linear-gradient(180deg, rgba(15,23,42,0.88), rgba(15,23,42,0.74));
    border: 1px solid rgba(148,163,184,0.16);
    border-radius: 20px;
    padding: 1rem 1rem;
    box-shadow: 0 12px 36px rgba(0,0,0,0.20);
}
.kpi-title {font-size: 0.76rem; text-transform: uppercase; letter-spacing: 0.08em; color: #94a3b8; font-weight: 700;}
.kpi-value {font-size: 2rem; font-weight: 800; color: #f8fafc; line-height: 1.1; margin-top: 0.35rem;}
.kpi-sub {font-size: 0.80rem; color: #cbd5e1; margin-top: 0.35rem;}
.live-pill {
    display:inline-flex; align-items:center; gap:8px; padding:6px 12px;
    border-radius:999px; background:rgba(239,68,68,0.14); color:#fecaca; font-weight:700; font-size:0.82rem;
    border:1px solid rgba(239,68,68,0.26);
}
.live-dot {width:9px; height:9px; border-radius:50%; background:#ef4444; box-shadow:0 0 0 0 rgba(239,68,68,0.8); animation:pulse 1.7s infinite;}
@keyframes pulse {0%{box-shadow:0 0 0 0 rgba(239,68,68,0.85);} 70%{box-shadow:0 0 0 12px rgba(239,68,68,0);} 100%{box-shadow:0 0 0 0 rgba(239,68,68,0);}}
.story-card {
    padding: 0.85rem 0.95rem; border-radius: 16px; margin-bottom: 0.75rem;
    background: linear-gradient(180deg, rgba(15,23,42,0.86), rgba(2,6,23,0.72));
    border:1px solid rgba(148,163,184,0.15);
}
.story-card a {color:#f8fafc !important; text-decoration:none;}
.small-muted {color:#94a3b8; font-size:0.82rem;}
.badge {display:inline-block; padding:3px 8px; border-radius:999px; font-size:0.73rem; font-weight:700; margin-right:6px; margin-top:6px;}
.badge-red {background:rgba(248,113,113,0.16); color:#fecaca; border:1px solid rgba(248,113,113,0.18);}
.badge-blue {background:rgba(96,165,250,0.16); color:#bfdbfe; border:1px solid rgba(96,165,250,0.18);}
.badge-amber {background:rgba(251,191,36,0.16); color:#fde68a; border:1px solid rgba(251,191,36,0.18);}
.badge-slate {background:rgba(148,163,184,0.16); color:#e2e8f0; border:1px solid rgba(148,163,184,0.18);}
.section-title {font-size:1.06rem; font-weight:800; color:#f8fafc; margin-bottom:0.6rem;}
.metric-split {display:flex; justify-content:space-between; gap:10px; padding:10px 0; border-bottom:1px solid rgba(148,163,184,0.10);} 
.metric-split:last-child {border-bottom:none;}
</style>
""",
    unsafe_allow_html=True,
)

# =========================
# HELPERS
# =========================
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")

ACTOR_LABELS = ["US", "Israel", "Iran", "Global"]

SOURCE_PRIORITY = {
    "reuters": 100,
    "associated press": 95,
    "ap": 95,
    "bbc": 90,
    "financial times": 88,
    "wall street journal": 88,
    "washington post": 86,
    "the guardian": 84,
    "al jazeera": 84,
    "cnn": 80,
    "cbs": 78,
    "abc": 78,
    "nbc": 78,
    "fox": 70,
}

TARGET_DICT = {
    "US": [
        "united states", " u.s.", " us ", "american", "americans", "pentagon",
        "u.s. base", "us base", "u.s. troops", "us troops", "u.s. forces", "us forces",
        "u.s. military", "us military", "washington",
    ],
    "Israel": [
        "israel", "israeli", "idf", "tel aviv", "jerusalem", "haifa",
        "israeli military", "israeli forces",
    ],
    "Iran": [
        "iran", "iranian", "tehran", "isfahan", "irgc", "revolutionary guards",
        "iran-backed", "hezbollah", "houthi", "proxy forces", "proxies",
    ],
    "Global": [
        "global", "world", "shipping", "oil markets", "energy markets", "world economy",
        "gulf", "uae", "saudi", "bahrain", "kuwait", "qatar", "iraq", "oman",
        "strait of hormuz", "red sea",
    ],
}

ATTACKER_VERBS = [
    "fired", "launched", "sent", "unleashed", "deployed", "shot", "struck with",
]

MISSILE_WORDS = [
    "missile", "missiles", "ballistic missile", "ballistic missiles", "rocket", "rockets",
    "projectile", "projectiles", "cruise missile", "cruise missiles", "barrage",
]
DRONE_WORDS = ["drone", "drones", "uav", "uavs", "shahed", "shaheds", "kamikaze drone", "kamikaze drones"]
CASUALTY_WORDS = [
    "killed", "dead", "deaths", "death toll", "fatalities", "casualties", "wounded",
    "injured", "injuries", "hurt",
]
LOSS_WORDS = [
    "damage", "damages", "loss", "losses", "cost", "costs", "economic toll", "property damage",
    "insured loss", "war cost", "repair bill", "compensation", "reconstruction",
]
PRICE_EXCLUSION_WORDS = [
    "per barrel", "a barrel", "brent", "wti", "stock", "shares rose", "shares fell",
    "market cap", "forecast", "price target", "oil price", "gold price", "trading at",
    "index", "closed at", "yield",
]

# Handles: 300, 300+, over 300, at least 300, about 300, more than 300, hundreds, dozens, one hundred and twenty
NUMERIC_TOKEN = r"(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
QUANT_RE = re.compile(
    rf"(?P<prefix>over|more than|at least|around|about|roughly|nearly|almost|up to|as many as)?\s*"
    rf"(?P<num>{NUMERIC_TOKEN}|[a-z\-\s]+?)\s*(?P<plus>\+)?\s*"
    rf"(?P<unit>missiles?|rockets?|projectiles?|drones?|uavs?|shaheds?|people|troops|soldiers|civilians|deaths?|fatalities|casualties|injuries|wounded|killed)\b",
    re.I,
)
USD_RE = re.compile(
    r"(?P<cur>\$|USD|US\$|U\.S\.\$)\s*(?P<val>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<scale>trillion|billion|million|tn|bn|mn|t|b|m)?\b",
    re.I,
)
LOCAL_MONEY_RE = re.compile(
    r"(?P<val>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<scale>trillion|billion|million|tn|bn|mn|t|b|m)?\s*"
    r"(?P<cur>shekels?|nis|rials?|tomans?|euros?|pounds?)\b",
    re.I,
)


def normalize_source_name(name: str) -> str:
    if not name:
        return "Unknown"
    return re.sub(r"\s+", " ", name).strip()


def domain_source_weight(source_name: str, url: str) -> int:
    text = f"{source_name} {urlparse(url).netloc}".lower()
    for key, val in SOURCE_PRIORITY.items():
        if key in text:
            return val
    return 50


def safe_parse_date(value):
    try:
        return dtparser.parse(value)
    except Exception:
        return datetime.now(UTC)


def clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_textual_number(token: str) -> float | None:
    if not token:
        return None
    token = token.strip().lower()
    token = token.replace("-", " ")
    if re.fullmatch(NUMERIC_TOKEN, token):
        return float(token.replace(",", ""))
    # quick commons
    commons = {
        "dozens": 24,
        "scores": 40,
        "hundreds": 200,
        "thousands": 2000,
        "a dozen": 12,
        "several": 3,
    }
    if token in commons:
        return float(commons[token])
    if w2n:
        try:
            return float(w2n.word_to_num(token))
        except Exception:
            pass
    return None


def money_to_usd_m(val: float, scale: str | None, currency: str) -> float | None:
    # Conservative conversion. Only native USD becomes a true number.
    # Local currency stays unresolved unless we can estimate reliably via live FX.
    if not currency:
        return None
    currency = currency.lower()
    scale = (scale or "").lower()
    mult = 1.0
    if scale in {"million", "m", "mn"}:
        mult = 1e6
    elif scale in {"billion", "b", "bn"}:
        mult = 1e9
    elif scale in {"trillion", "t", "tn"}:
        mult = 1e12

    if currency in {"$", "usd", "us$", "u.s.$"}:
        return (val * mult) / 1e6
    return None


def money_to_display_usd_m(val: float | None) -> float:
    return float(val or 0.0)


def format_money_m(val_m: float) -> str:
    if not val_m or val_m <= 0:
        return "$0"
    if val_m >= 1_000_000:
        return f"${val_m/1_000_000:,.2f}T"
    if val_m >= 1_000:
        return f"${val_m/1_000:,.2f}B"
    return f"${val_m:,.0f}M"


def actor_hits(text: str) -> list[str]:
    hits = []
    lower = f" {text.lower()} "
    for actor, terms in TARGET_DICT.items():
        if any(term in lower for term in terms):
            hits.append(actor)
    return hits or ["Global"]


def choose_actor(text: str, fallback: str = "Global") -> str:
    hits = actor_hits(text)
    priority = ["US", "Israel", "Iran", "Global"]
    for p in priority:
        if p in hits:
            return p
    return fallback


def looks_like_damage_sentence(text: str) -> bool:
    lower = text.lower()
    return any(k in lower for k in LOSS_WORDS) and not any(k in lower for k in PRICE_EXCLUSION_WORDS)


def split_sentences_with_context(text: str):
    sents = [clean_text(s) for s in sent_tokenize(text) if clean_text(s)]
    rows = []
    for i, sent in enumerate(sents):
        prev_sent = sents[i - 1] if i > 0 else ""
        next_sent = sents[i + 1] if i + 1 < len(sents) else ""
        window = f"{prev_sent} {sent} {next_sent}".strip()
        rows.append((sent, window))
    return rows


class WarFactExtractor:
    def extract_facts(self, article: dict) -> list[dict]:
        text = clean_text(article.get("text", ""))
        if not text:
            return []

        facts: list[dict] = []
        source_weight = domain_source_weight(article.get("source", ""), article.get("url", ""))
        for sent, window in split_sentences_with_context(text):
            lower = sent.lower()
            ctx = window.lower()

            # 1) missiles / drones / casualties
            for m in QUANT_RE.finditer(sent):
                raw_num = m.group("num")
                unit = m.group("unit").lower()
                prefix = (m.group("prefix") or "").lower()
                plus = bool(m.group("plus"))
                num = parse_textual_number(raw_num)
                if num is None:
                    continue
                # make lower-bound approximations explicit
                if prefix in {"over", "more than", "at least"} or plus:
                    num = math.floor(num)
                if num <= 0:
                    continue
                if num > 1_000_000:
                    continue

                metric = None
                subtype = None
                actor = "Global"
                target = "Global"
                confidence = 0.45

                if any(word in unit for word in ["missile", "rocket", "projectile"]):
                    metric = "missiles_fired"
                    subtype = unit
                    confidence = 0.72
                elif any(word in unit for word in ["drone", "uav", "shahed"]):
                    metric = "drones_fired"
                    subtype = unit
                    confidence = 0.72
                elif any(word in unit for word in ["death", "fatalit", "killed", "casualt"]):
                    metric = "casualties"
                    subtype = "killed"
                    confidence = 0.74
                elif any(word in unit for word in ["injur", "wound"]):
                    metric = "injuries"
                    subtype = "injured"
                    confidence = 0.68

                if metric is None:
                    continue

                if metric in {"missiles_fired", "drones_fired"}:
                    actor = self._infer_attacker_actor(ctx)
                    target = self._infer_target_actor(ctx, default="Global")
                    if metric == "missiles_fired" and ("interceptor" in ctx or "intercepted" in ctx):
                        confidence -= 0.12
                else:
                    target = self._infer_target_actor(ctx, default="Global")
                    actor = self._infer_attacker_actor(ctx, default="Global")

                facts.append({
                    "article_hash": article["hash"],
                    "article_title": article["title"],
                    "article_url": article["url"],
                    "source": article["source"],
                    "source_weight": source_weight,
                    "published_at": article["datetime"],
                    "sentence": sent,
                    "context": window,
                    "metric": metric,
                    "subtype": subtype,
                    "actor": actor,
                    "target": target,
                    "value": float(num),
                    "unit": "count",
                    "confidence": max(0.1, min(0.99, confidence)),
                })

            # 2) money / economic loss
            if looks_like_damage_sentence(ctx):
                for m in USD_RE.finditer(sent):
                    val = float(m.group("val").replace(",", ""))
                    usd_m = money_to_usd_m(val, m.group("scale"), m.group("cur"))
                    if usd_m is None or usd_m <= 0:
                        continue
                    target = self._infer_target_actor(ctx, default="Global")
                    actor = self._infer_attacker_actor(ctx, default="Global")
                    conf = 0.78 if any(x in ctx for x in ["damage", "loss", "cost", "insured", "compensation"]) else 0.55
                    facts.append({
                        "article_hash": article["hash"],
                        "article_title": article["title"],
                        "article_url": article["url"],
                        "source": article["source"],
                        "source_weight": source_weight,
                        "published_at": article["datetime"],
                        "sentence": sent,
                        "context": window,
                        "metric": "economic_loss_usd_m",
                        "subtype": "usd",
                        "actor": actor,
                        "target": target,
                        "value": float(usd_m),
                        "unit": "usd_m",
                        "confidence": conf,
                    })

                # local currency facts captured separately so the dashboard can surface evidence even if not converted
                for m in LOCAL_MONEY_RE.finditer(sent):
                    val = float(m.group("val").replace(",", ""))
                    scale = (m.group("scale") or "").lower()
                    cur = m.group("cur").lower()
                    target = self._infer_target_actor(ctx, default="Global")
                    actor = self._infer_attacker_actor(ctx, default="Global")
                    mult = 1.0
                    if scale in {"million", "m", "mn"}:
                        mult = 1e6
                    elif scale in {"billion", "b", "bn"}:
                        mult = 1e9
                    elif scale in {"trillion", "t", "tn"}:
                        mult = 1e12
                    facts.append({
                        "article_hash": article["hash"],
                        "article_title": article["title"],
                        "article_url": article["url"],
                        "source": article["source"],
                        "source_weight": source_weight,
                        "published_at": article["datetime"],
                        "sentence": sent,
                        "context": window,
                        "metric": "economic_loss_local",
                        "subtype": cur,
                        "actor": actor,
                        "target": target,
                        "value": float(val * mult),
                        "unit": cur,
                        "confidence": 0.55,
                    })

        return facts

    def _infer_attacker_actor(self, ctx: str, default: str = "Global") -> str:
        # sentence patterns tuned for current conflict framing
        patterns = [
            ("US", ["u.s. fired", "us fired", "u.s. launched", "us launched", "american strike", "american strikes", "pentagon said", "u.s. strike", "us strike"]),
            ("Israel", ["israel fired", "israel launched", "israeli strike", "israeli strikes", "idf fired", "idf launched", "idf struck"]),
            ("Iran", ["iran fired", "iran launched", "iranian strike", "iranian strikes", "irgc fired", "irgc launched", "hezbollah fired", "houthi fired", "proxies fired", "shahed drones", "tehran launched"]),
        ]
        for actor, pats in patterns:
            if any(p in ctx for p in pats):
                return actor
        # fallback by entity prominence
        if ctx.count("iran") + ctx.count("iranian") > ctx.count("israel") + ctx.count("israeli") and ctx.count("iran") + ctx.count("iranian") > ctx.count("u.s.") + ctx.count(" us ") + ctx.count("american"):
            return "Iran"
        if ctx.count("israel") + ctx.count("israeli") >= max(ctx.count("iran") + ctx.count("iranian"), ctx.count("u.s.") + ctx.count(" us ") + ctx.count("american")):
            return "Israel"
        if any(x in ctx for x in ["u.s.", " us ", "american", "pentagon"]):
            return "US"
        return default

    def _infer_target_actor(self, ctx: str, default: str = "Global") -> str:
        if any(x in ctx for x in ["in israel", "on israel", "israeli city", "tel aviv", "jerusalem", "haifa", "israeli civilians", "israelis"]):
            return "Israel"
        if any(x in ctx for x in ["in iran", "on iran", "tehran", "isfahan", "iranian city", "iranians"]):
            return "Iran"
        if any(x in ctx for x in ["u.s. base", "us base", "american troops", "u.s. troops", "us troops", "u.s. forces", "us forces"]):
            return "US"
        if any(x in ctx for x in ["gulf", "uae", "saudi", "bahrain", "kuwait", "qatar", "strait of hormuz", "world economy", "global markets", "shipping"]):
            return "Global"
        return choose_actor(ctx, fallback=default)


# =========================
# FETCHING
# =========================
def gdelt_query_url(query: str, mode: str = "ArtList", max_records: int = 80) -> str:
    q = quote_plus(query)
    return (
        "https://api.gdeltproject.org/api/v2/doc/doc?"
        f"query={q}&mode={mode}&maxrecords={max_records}&format=json&sort=datedesc"
    )


def fetch_gdelt_articles(max_records: int = 120) -> list[dict]:
    queries = [
        '((Iran OR Iranian OR Tehran) AND (Israel OR Israeli OR IDF) AND (US OR "United States" OR American) AND (missile OR drone OR casualty OR damage OR cost OR economic OR oil))',
        '((Iran OR Iranian OR Tehran) AND (missile OR drones OR projectiles OR barrage) AND (Israel OR Israeli))',
        '((war OR conflict) AND (Iran OR Israel OR US) AND (damage OR losses OR compensation OR insured OR cost))',
    ]
    out = []
    seen = set()
    for q in queries:
        try:
            r = requests.get(gdelt_query_url(q, max_records=max_records), timeout=20)
            r.raise_for_status()
            data = r.json().get("articles", [])
        except Exception:
            data = []
        for art in data:
            url = art.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({
                "title": clean_text(art.get("title", "")),
                "url": url,
                "source": normalize_source_name(art.get("sourceCountry", "") or urlparse(url).netloc),
                "datetime": safe_parse_date(art.get("seendate") or art.get("socialimage") or datetime.now(UTC).isoformat()),
                "summary": clean_text(art.get("snippet", "")),
                "source_hint": art.get("domain", urlparse(url).netloc),
            })
    return out


def fetch_rss_articles(limit_per_feed: int = 50) -> list[dict]:
    feeds = [
        ("Reuters World", "https://www.reutersagency.com/feed/?best-topics=world&post_type=best"),
        ("Reuters Business", "https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best"),
        ("AP Top News", "https://apnews.com/hub/apf-topnews?output=rss"),
        ("BBC Middle East", "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml"),
        ("Al Jazeera", "https://www.aljazeera.com/xml/rss/all.xml"),
        ("Google News", "https://news.google.com/rss/search?q=Iran+Israel+US+war+missiles+casualties+damage+cost&hl=en-US&gl=US&ceid=US:en"),
        ("Google News 2", "https://news.google.com/rss/search?q=Iran+Israel+war+drones+missiles+economic+loss&hl=en-US&gl=US&ceid=US:en"),
    ]
    out = []
    seen = set()
    for label, url in feeds:
        try:
            parsed = feedparser.parse(url)
        except Exception:
            parsed = None
        if not parsed:
            continue
        for e in parsed.entries[:limit_per_feed]:
            link = (e.get("link") or "").split("?")[0]
            if not link or link in seen:
                continue
            seen.add(link)
            out.append({
                "title": clean_text(e.get("title", "")),
                "url": link,
                "source": normalize_source_name(e.get("source", {}).get("title") or label),
                "datetime": safe_parse_date(e.get("published") or e.get("updated") or datetime.now(UTC).isoformat()),
                "summary": clean_text(e.get("summary", "")),
                "source_hint": label,
            })
    return out


def fetch_newsapi_articles(page_size: int = 80) -> list[dict]:
    if not NEWSAPI_KEY:
        return []
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": '(Iran OR Iranian OR Tehran) AND (Israel OR Israeli OR IDF) AND (US OR American) AND (missile OR drone OR casualty OR damage OR cost OR economy)',
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "domains": "reuters.com,apnews.com,bbc.com,aljazeera.com,theguardian.com,wsj.com,washingtonpost.com,ft.com,cnn.com,cbsnews.com,abcnews.go.com,nbcnews.com",
        "apiKey": NEWSAPI_KEY,
    }
    try:
        r = requests.get(url, params=params, timeout=20)
        r.raise_for_status()
        payload = r.json()
        data = payload.get("articles", [])
    except Exception:
        data = []
    out = []
    for a in data:
        link = a.get("url")
        if not link:
            continue
        out.append({
            "title": clean_text(a.get("title", "")),
            "url": link,
            "source": normalize_source_name((a.get("source") or {}).get("name", "NewsAPI")),
            "datetime": safe_parse_date(a.get("publishedAt") or datetime.now(UTC).isoformat()),
            "summary": clean_text(a.get("description", "")),
            "source_hint": "NewsAPI",
        })
    return out


def fetch_full_article_text(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url, timeout=12)
        if not downloaded:
            return ""
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=False) or ""
        return clean_text(text)[:25000]
    except Exception:
        return ""


def hydrate_article(article: dict, fetch_full: bool = True) -> dict:
    text = f"{article.get('title','')}. {article.get('summary','')}"
    full = fetch_full_article_text(article["url"]) if fetch_full else ""
    if full:
        text = f"{text} {full}"
    content = clean_text(text)
    h = hashlib.md5((article["url"] + "|" + content[:1200]).encode()).hexdigest()[:16]
    item = dict(article)
    item["text"] = content
    item["hash"] = h
    item["date"] = item["datetime"].astimezone(IST).date()
    return item


@st.cache_data(ttl=300, show_spinner=False)
def build_live_dataset(max_articles: int, fetch_full: bool) -> tuple[pd.DataFrame, pd.DataFrame]:
    seed = []
    seed.extend(fetch_gdelt_articles(max_records=max_articles))
    seed.extend(fetch_rss_articles(limit_per_feed=max(20, max_articles // 3)))
    seed.extend(fetch_newsapi_articles(page_size=min(100, max_articles)))

    # dedupe by URL and keep best source title
    dedup = {}
    for item in seed:
        url = item["url"]
        prev = dedup.get(url)
        if not prev or domain_source_weight(item.get("source", ""), url) > domain_source_weight(prev.get("source", ""), url):
            dedup[url] = item
    articles = list(dedup.values())
    articles = sorted(articles, key=lambda x: x["datetime"], reverse=True)[:max_articles]

    hydrated = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(hydrate_article, item, fetch_full) for item in articles]
        for fut in cf.as_completed(futs):
            try:
                hydrated.append(fut.result())
            except Exception:
                pass

    art_df = pd.DataFrame(hydrated)
    if art_df.empty:
        return art_df, pd.DataFrame()
    art_df = art_df.drop_duplicates(subset=["hash"]).sort_values("datetime", ascending=False).reset_index(drop=True)

    extractor = WarFactExtractor()
    all_facts = []
    for _, row in art_df.iterrows():
        all_facts.extend(extractor.extract_facts(row.to_dict()))

    facts_df = pd.DataFrame(all_facts)
    if facts_df.empty:
        return art_df, facts_df

    facts_df["day"] = pd.to_datetime(facts_df["published_at"]).dt.date
    return art_df, facts_df


# =========================
# FACT RESOLUTION
# =========================
def resolve_fact_rollup(facts_df: pd.DataFrame) -> dict:
    empty = {
        "missiles": {a: 0 for a in ACTOR_LABELS},
        "drones": {a: 0 for a in ACTOR_LABELS},
        "casualties": {a: 0 for a in ACTOR_LABELS},
        "injuries": {a: 0 for a in ACTOR_LABELS},
        "loss_usd_m": {a: 0.0 for a in ACTOR_LABELS},
    }
    if facts_df.empty:
        return empty

    rollup = json.loads(json.dumps(empty))

    def aggregate(metric_name: str, bucket: str, actor_field: str = "target"):
        subset = facts_df[facts_df["metric"] == metric_name].copy()
        if subset.empty:
            return
        # Prefer higher confidence and source weight, then latest, then max value
        subset = subset.sort_values(["confidence", "source_weight", "published_at", "value"], ascending=[False, False, False, False])
        for actor in ACTOR_LABELS:
            if actor == "Global":
                actor_df = subset
            else:
                actor_df = subset[subset[actor_field] == actor]
            if actor_df.empty:
                rollup[bucket][actor] = 0 if bucket != "loss_usd_m" else 0.0
                continue

            # Robust estimator: weighted 80th percentile-ish by taking top consensus cluster.
            vals = actor_df["value"].tolist()
            top = sorted(vals, reverse=True)[: min(7, len(vals))]
            if not top:
                value = 0
            elif len(top) == 1:
                value = top[0]
            else:
                median_top = statistics.median(top)
                # cap outliers that are >3x the median of top sample
                filtered = [v for v in top if v <= max(median_top * 3, median_top + 50)]
                value = max(filtered) if filtered else median_top
            rollup[bucket][actor] = float(value)

    aggregate("missiles_fired", "missiles", actor_field="actor")
    aggregate("drones_fired", "drones", actor_field="actor")
    aggregate("casualties", "casualties", actor_field="target")
    aggregate("injuries", "injuries", actor_field="target")
    aggregate("economic_loss_usd_m", "loss_usd_m", actor_field="target")

    # keep global as overall max/sum depending on metric
    rollup["missiles"]["Global"] = max(rollup["missiles"].values())
    rollup["drones"]["Global"] = max(rollup["drones"].values())
    rollup["casualties"]["Global"] = max(rollup["casualties"].values())
    rollup["injuries"]["Global"] = max(rollup["injuries"].values())
    rollup["loss_usd_m"]["Global"] = sum(v for k, v in rollup["loss_usd_m"].items() if k != "Global")
    return rollup



def make_timeline(facts_df: pd.DataFrame) -> pd.DataFrame:
    if facts_df.empty:
        return pd.DataFrame()
    pivot = (
        facts_df.groupby(["day", "metric", "actor", "target"], as_index=False)["value"]
        .max()
        .sort_values("day")
    )
    return pivot



def evidence_table(facts_df: pd.DataFrame, metric: str, actor: str | None = None, target: str | None = None, top_n: int = 8) -> pd.DataFrame:
    if facts_df.empty:
        return pd.DataFrame()
    df = facts_df[facts_df["metric"] == metric].copy()
    if actor:
        df = df[df["actor"] == actor]
    if target:
        df = df[df["target"] == target]
    if df.empty:
        return df
    df = df.sort_values(["confidence", "source_weight", "published_at", "value"], ascending=[False, False, False, False])
    return df[["published_at", "source", "value", "unit", "actor", "target", "sentence", "article_title", "article_url"]].head(top_n)


# =========================
# MARKET DATA
# =========================
@st.cache_data(ttl=600, show_spinner=False)
def fetch_market_snapshot():
    tickers = {
        "Brent": "BZ=F",
        "WTI": "CL=F",
        "Gold": "GC=F",
        "S&P 500": "^GSPC",
        "Dollar Index": "DX-Y.NYB",
    }
    rows = []
    for name, ticker in tickers.items():
        try:
            hist = yf.Ticker(ticker).history(period="1mo", interval="1d")
            if len(hist) < 2:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2])
            delta = (last - prev) / prev * 100 if prev else 0
            rows.append({"name": name, "ticker": ticker, "last": last, "delta_pct": delta, "series": hist.reset_index()})
        except Exception:
            pass
    return rows


# =========================
# SIDEBAR
# =========================
with st.sidebar:
    st.markdown("### Control Tower")
    max_articles = st.slider("Live article cap", 60, 400, 180, step=20)
    fetch_full = st.toggle("Fetch full article text", value=True)
    show_evidence = st.toggle("Show extraction evidence tables", value=True)
    st.caption("Tip: add NEWSAPI_KEY in Streamlit secrets or environment for wider coverage.")
    if st.button("Force live rebuild", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# =========================
# DATA BUILD
# =========================
with st.spinner("Scanning live coverage, parsing facts, resolving counts…"):
    articles_df, facts_df = build_live_dataset(max_articles=max_articles, fetch_full=fetch_full)

if articles_df.empty:
    st.error("No live coverage could be fetched right now.")
    st.stop()

rollup = resolve_fact_rollup(facts_df)
timeline_df = make_timeline(facts_df)

# Narrative momentum: lightweight article sentiment by actor presence
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    analyzer = SentimentIntensityAnalyzer()
except Exception:
    analyzer = None

if analyzer:
    momentum_rows = []
    for _, row in articles_df.iterrows():
        text = row.get("text", "")[:3000]
        score = analyzer.polarity_scores(text).get("compound", 0.0)
        low = text.lower()
        for actor in ["US", "Israel", "Iran"]:
            if actor.lower() in low or (actor == "US" and any(x in low for x in ["u.s.", "american", "united states"])):
                momentum_rows.append({"date": row["date"], "actor": actor, "score": score})
    momentum_df = pd.DataFrame(momentum_rows)
    if not momentum_df.empty:
        momentum_df = momentum_df.groupby(["date", "actor"], as_index=False)["score"].mean()
else:
    momentum_df = pd.DataFrame()

# =========================
# HERO
# =========================
last_refresh = datetime.now(IST).strftime("%d %b %Y • %H:%M IST")
st.markdown(
    f"""
<div class="hero">
  <div style="display:flex; justify-content:space-between; gap:16px; align-items:flex-start; flex-wrap:wrap;">
    <div>
      <div class="small-muted" style="font-weight:800; letter-spacing:0.08em; text-transform:uppercase;">Live Conflict Intelligence Dashboard</div>
      <div style="font-size:2.0rem; font-weight:800; line-height:1.08; margin-top:6px;">War Pulse Live: Iran • Israel • U.S.</div>
      <div class="small-muted" style="margin-top:8px; max-width:920px;">Structured extraction from live news coverage. The dashboard resolves missiles, drones, casualties, and economic losses into fact tables, then surfaces best-supported counts with source evidence.</div>
    </div>
    <div style="display:flex; flex-direction:column; align-items:flex-end; gap:10px;">
      <div class="live-pill"><span class="live-dot"></span>LIVE INTEL</div>
      <div class="small-muted">Last refresh: {last_refresh}</div>
      <div class="small-muted">Signals processed: {len(articles_df):,} articles • {len(facts_df):,} extracted facts</div>
    </div>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# =========================
# KPI ROW
# =========================
k1, k2, k3, k4, k5 = st.columns(5)

kpis = [
    (k1, "Missiles fired", f"{int(rollup['missiles']['US'] + rollup['missiles']['Israel'] + rollup['missiles']['Iran']):,}", "Resolved from actor-attributed reports"),
    (k2, "Drones fired", f"{int(rollup['drones']['US'] + rollup['drones']['Israel'] + rollup['drones']['Iran']):,}", "Actor-attributed drone salvos"),
    (k3, "Economic loss", format_money_m(rollup['loss_usd_m']['Global']), "USD-only direct loss evidence"),
    (k4, "Global casualties", f"{int(rollup['casualties']['Global']):,}", "Best-supported reported toll"),
    (k5, "Global injuries", f"{int(rollup['injuries']['Global']):,}", "Best-supported reported injuries"),
]
for col, title, val, sub in kpis:
    col.markdown(f"<div class='kpi-card'><div class='kpi-title'>{title}</div><div class='kpi-value'>{val}</div><div class='kpi-sub'>{sub}</div></div>", unsafe_allow_html=True)

st.write("")

# =========================
# MAIN GRID
# =========================
left, right = st.columns([1.7, 1.05], gap="large")

with left:
    st.markdown("<div class='section-title'>Kinetic trendline</div>", unsafe_allow_html=True)
    if not timeline_df.empty:
        time_rows = []
        for day, sub in timeline_df.groupby("day"):
            row = {"day": day}
            row["Iran missiles"] = sub[(sub.metric == "missiles_fired") & (sub.actor == "Iran")]["value"].max() if not sub.empty else 0
            row["Israel missiles"] = sub[(sub.metric == "missiles_fired") & (sub.actor == "Israel")]["value"].max() if not sub.empty else 0
            row["US missiles"] = sub[(sub.metric == "missiles_fired") & (sub.actor == "US")]["value"].max() if not sub.empty else 0
            row["Iran drones"] = sub[(sub.metric == "drones_fired") & (sub.actor == "Iran")]["value"].max() if not sub.empty else 0
            row["Casualties"] = sub[sub.metric == "casualties"]["value"].max() if not sub.empty else 0
            row["Loss USD M"] = sub[sub.metric == "economic_loss_usd_m"]["value"].max() if not sub.empty else 0
            time_rows.append(row)
        trend = pd.DataFrame(time_rows).sort_values("day")
        for c in [c for c in trend.columns if c != "day"]:
            trend[c] = trend[c].cummax()

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=trend["day"], y=trend["Iran missiles"], mode="lines+markers", name="Iran missiles", line=dict(width=3, color="#ef4444")))
        fig.add_trace(go.Scatter(x=trend["day"], y=trend["Israel missiles"], mode="lines+markers", name="Israel missiles", line=dict(width=2, color="#60a5fa")))
        fig.add_trace(go.Scatter(x=trend["day"], y=trend["US missiles"], mode="lines+markers", name="US missiles", line=dict(width=2, color="#22c55e")))
        fig.add_trace(go.Scatter(x=trend["day"], y=trend["Iran drones"], mode="lines", name="Iran drones", line=dict(width=2, dash="dot", color="#f59e0b"), yaxis="y2"))
        fig.add_trace(go.Scatter(x=trend["day"], y=trend["Casualties"], mode="lines", name="Casualties", line=dict(width=2, dash="dash", color="#cbd5e1"), yaxis="y2"))
        fig.update_layout(
            template="plotly_dark",
            height=420,
            margin=dict(l=8, r=8, t=8, b=8),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,23,42,0.30)",
            legend=dict(orientation="h", y=1.12),
            yaxis=dict(title="Projectile counts"),
            yaxis2=dict(title="Drones / casualties", overlaying="y", side="right"),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No structured time series extracted yet.")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<div class='section-title'>Attributed projectile mix</div>", unsafe_allow_html=True)
        proj_df = pd.DataFrame({
            "Actor": ["US", "Israel", "Iran"],
            "Missiles": [rollup["missiles"]["US"], rollup["missiles"]["Israel"], rollup["missiles"]["Iran"]],
            "Drones": [rollup["drones"]["US"], rollup["drones"]["Israel"], rollup["drones"]["Iran"]],
        })
        proj_long = proj_df.melt(id_vars="Actor", var_name="Type", value_name="Count")
        fig2 = px.bar(proj_long, x="Actor", y="Count", color="Type", barmode="group", template="plotly_dark", height=320)
        fig2.update_layout(margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.30)")
        st.plotly_chart(fig2, use_container_width=True)

    with c2:
        st.markdown("<div class='section-title'>Economic loss by impacted side</div>", unsafe_allow_html=True)
        loss_df = pd.DataFrame({
            "Target": ["US", "Israel", "Iran", "Global spillover"],
            "USD_M": [rollup["loss_usd_m"]["US"], rollup["loss_usd_m"]["Israel"], rollup["loss_usd_m"]["Iran"], max(0.0, rollup["loss_usd_m"]["Global"] - rollup["loss_usd_m"]["US"] - rollup["loss_usd_m"]["Israel"] - rollup["loss_usd_m"]["Iran"])]
        })
        fig3 = px.pie(loss_df, names="Target", values="USD_M", hole=0.58, template="plotly_dark", height=320)
        fig3.update_layout(margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig3, use_container_width=True)

    st.markdown("<div class='section-title'>Narrative momentum</div>", unsafe_allow_html=True)
    if not momentum_df.empty:
        figm = px.line(momentum_df, x="date", y="score", color="actor", markers=True, template="plotly_dark", height=300)
        figm.update_layout(margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.30)", yaxis_title="Tone score")
        st.plotly_chart(figm, use_container_width=True)
    else:
        st.info("Momentum tracker unavailable because VADER sentiment is not installed.")

    if show_evidence:
        with st.expander("Evidence table: economic loss extraction", expanded=False):
            ev = pd.concat([
                evidence_table(facts_df, "economic_loss_usd_m", target="US"),
                evidence_table(facts_df, "economic_loss_usd_m", target="Israel"),
                evidence_table(facts_df, "economic_loss_usd_m", target="Iran"),
                evidence_table(facts_df, "economic_loss_usd_m", target="Global"),
            ], ignore_index=True)
            if ev.empty:
                st.info("No direct USD loss evidence resolved from current coverage.")
            else:
                st.dataframe(ev, use_container_width=True, hide_index=True)

with right:
    st.markdown("<div class='section-title'>Resolved live scoreboard</div>", unsafe_allow_html=True)
    st.markdown("<div class='glass-card'>", unsafe_allow_html=True)
    scoreboard = [
        ("US", int(rollup["missiles"]["US"] + rollup["drones"]["US"]), int(rollup["casualties"]["US"]), format_money_m(rollup["loss_usd_m"]["US"])),
        ("Israel", int(rollup["missiles"]["Israel"] + rollup["drones"]["Israel"]), int(rollup["casualties"]["Israel"]), format_money_m(rollup["loss_usd_m"]["Israel"])),
        ("Iran", int(rollup["missiles"]["Iran"] + rollup["drones"]["Iran"]), int(rollup["casualties"]["Iran"]), format_money_m(rollup["loss_usd_m"]["Iran"])),
        ("Global", int(rollup["missiles"]["Global"] + rollup["drones"]["Global"]), int(rollup["casualties"]["Global"]), format_money_m(rollup["loss_usd_m"]["Global"])),
    ]
    for name, proj, cas, loss in scoreboard:
        st.markdown(
            f"<div class='metric-split'><div><div style='font-weight:800; font-size:1rem'>{name}</div><div class='small-muted'>Projectiles / casualties / losses</div></div><div style='text-align:right'><div style='font-weight:800'>{proj:,} proj.</div><div class='small-muted'>{cas:,} casualties • {loss}</div></div></div>",
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='section-title' style='margin-top:1rem;'>Macro market shock</div>", unsafe_allow_html=True)
    market = fetch_market_snapshot()
    for row in market:
        st.metric(row["name"], f"{row['last']:,.2f}", f"{row['delta_pct']:+.2f}%")

    st.markdown("<div class='section-title' style='margin-top:1rem;'>Top source-backed reports</div>", unsafe_allow_html=True)
    if not facts_df.empty:
        severity = (
            facts_df.groupby(["article_hash", "article_title", "article_url", "source"], as_index=False)
            .agg(score=("value", "sum"), avg_conf=("confidence", "mean"), source_weight=("source_weight", "max"))
        )
        severity["rank"] = severity["score"] * severity["avg_conf"] * (severity["source_weight"] / 50)
        top = severity.sort_values("rank", ascending=False).head(8)
        for _, r in top.iterrows():
            tags_df = facts_df[facts_df["article_hash"] == r["article_hash"]]
            badge_html = []
            if (tags_df["metric"] == "missiles_fired").any():
                badge_html.append("<span class='badge badge-red'>Missiles</span>")
            if (tags_df["metric"] == "drones_fired").any():
                badge_html.append("<span class='badge badge-amber'>Drones</span>")
            if (tags_df["metric"] == "economic_loss_usd_m").any():
                badge_html.append("<span class='badge badge-blue'>Losses</span>")
            if (tags_df["metric"] == "casualties").any():
                badge_html.append("<span class='badge badge-slate'>Casualties</span>")
            st.markdown(
                f"""
<div class='story-card'>
  <a href='{r['article_url']}' target='_blank'>{r['article_title']}</a>
  <div class='small-muted' style='margin-top:4px;'>{r['source']}</div>
  <div>{''.join(badge_html)}</div>
</div>
""",
                unsafe_allow_html=True,
            )
    else:
        for _, r in articles_df.head(8).iterrows():
            st.markdown(
                f"""
<div class='story-card'>
  <a href='{r['url']}' target='_blank'>{r['title']}</a>
  <div class='small-muted' style='margin-top:4px;'>{r['source']}</div>
</div>
""",
                unsafe_allow_html=True,
            )

# =========================
# ARTICLE TABLE
# =========================
with st.expander("Article inventory", expanded=False):
    table = articles_df[["datetime", "source", "title", "url"]].copy().sort_values("datetime", ascending=False)
    st.dataframe(table, use_container_width=True, hide_index=True)

# =========================
# FOOTER NOTES
# =========================
st.caption(
    "Method note: the dashboard surfaces best-supported counts from recent reporting, not official battlefield truth. It favors direct numeric statements tied to attack, casualty, or damage language and shows evidence rows so you can inspect the extraction quality."
)
