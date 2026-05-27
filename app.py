import streamlit as st
import feedparser
import anthropic
import smtplib
import urllib.request
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone
from collections import defaultdict
from secrets_loader import load_config
from config import FEEDS, USER_PROFILE
_cfg = load_config()
ANTHROPIC_API_KEY = _cfg["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS = _cfg["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = _cfg["GMAIL_APP_PASSWORD"]
KINDLE_EMAIL = _cfg["KINDLE_EMAIL"]

st.set_page_config(page_title="Pulse AI", page_icon="⚡", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@300;400;500&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; background-color: #080808; color: #d4d4d4; }
.stApp { background-color: #080808; }
.pulse-header { font-family: 'Space Mono', monospace; font-size: 32px; font-weight: 700; color: #fff; letter-spacing: -1px; margin-bottom: 2px; }
.pulse-sub { font-family: 'Space Mono', monospace; font-size: 11px; color: #444; letter-spacing: 2px; text-transform: uppercase; margin-bottom: 24px; }
.stButton > button { background-color: #111; color: #d4d4d4; border: 1px solid #2a2a2a; border-radius: 3px; font-family: 'Space Mono', monospace; font-size: 11px; padding: 8px 16px; transition: all 0.15s; width: 100%; }
.stButton > button:hover { background-color: #1a1a1a; border-color: #555; color: #fff; }
.card { background: #0f0f0f; border: 1px solid #1e1e1e; border-radius: 6px; padding: 14px 16px; margin-bottom: 10px; }
.card-source { font-family: 'Space Mono', monospace; font-size: 9px; color: #555; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px; }
.card-title { font-size: 13px; font-weight: 500; color: #e8e8e8; margin-bottom: 6px; line-height: 1.4; }
.card-summary { font-size: 12px; color: #777; line-height: 1.5; margin-bottom: 8px; }
.section-header { font-family: 'Space Mono', monospace; font-size: 10px; color: #444; text-transform: uppercase; letter-spacing: 2px; border-bottom: 1px solid #1a1a1a; padding-bottom: 6px; margin: 20px 0 12px 0; }
.detail-title { font-size: 18px; font-weight: 600; color: #fff; line-height: 1.4; margin-bottom: 12px; }
.detail-source { font-family: 'Space Mono', monospace; font-size: 10px; color: #555; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 16px; }
.detail-content { font-size: 14px; color: #aaa; line-height: 1.8; white-space: pre-wrap; }
.analysis-box { background: #0a0a0a; border: 1px solid #1e1e1e; border-left: 2px solid #4a9eff; border-radius: 4px; padding: 20px 24px; font-size: 14px; line-height: 1.8; color: #aaa; white-space: pre-wrap; }
.linkedin-box { background: #0a0f1a; border: 1px solid #1a2a3a; border-left: 2px solid #0077b5; border-radius: 4px; padding: 20px 24px; font-size: 14px; line-height: 1.8; color: #aaa; white-space: pre-wrap; }
.meta { font-family: 'Space Mono', monospace; font-size: 11px; color: #333; }
.empty-panel { text-align: center; padding: 60px 20px; color: #333; font-family: 'Space Mono', monospace; font-size: 12px; }
</style>
""", unsafe_allow_html=True)


def fetch_items(feeds, max_per_feed=10):
    result, errors = [], []
    for feed_info in feeds:
        try:
            parsed = feedparser.parse(feed_info["url"], request_headers={"User-Agent": "Mozilla/5.0"})
            for entry in parsed.entries[:max_per_feed]:
                result.append({
                    "source": feed_info["name"],
                    "category": feed_info.get("category", "🔗 Otros"),
                    "title": entry.get("title", "Sin título"),
                    "summary": entry.get("summary", entry.get("description", ""))[:600],
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            errors.append(f"{feed_info['name']}: {e}")
    return result, errors


def fetch_full_content(item):
    link = item.get("link", "")
    summary = item.get("summary", "")
    arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', link)
    if arxiv_match:
        try:
            url = f"https://export.arxiv.org/abs/{arxiv_match.group(1)}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
            m = re.search(r'<blockquote class="abstract mathjax">(.*?)</blockquote>', html, re.DOTALL)
            if m:
                abstract = re.sub(r'<[^>]+>', '', m.group(1)).strip().replace("Abstract:", "").strip()
                return f"Abstract complete\n\n{abstract}\n\nLink: {link}"
        except Exception:
            pass
    if link:
        try:
            req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
            html = re.sub(r'<(script|style|nav|header|footer)[^>]*>.*?</\1>', '', html, flags=re.DOTALL)
            text = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html)).strip()[:4000]
            return f"{text}\n\nLink: {link}"
        except Exception:
            pass
    return f"{summary}\n\nLink: {link}"


def call_claude(prompt, max_tokens=2000):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    msg = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text


def generate_analysis(feed_items):
    feed_text = "\n".join([f"[{i}] [{it['category']}] {it['source']} — {it['title']}\n{it['summary'][:300]}" for i, it in enumerate(feed_items[:40], 1)])
    return call_claude(f"Sos un analista de IA. Perfil: {USER_PROFILE}\nItems: {feed_text}\nSelecciona 6-8 mas relevantes. Titulo negrita, fuente, 2-3 oraciones cada uno. Cerra con Tendencias. Español tecnico directo.", max_tokens=2000)


def analyze_single_item(item, content):
    return call_claude(f"Analiza para el perfil: {USER_PROFILE}\nTitulo: {item['title']}\nFuente: {item['source']}\nContenido: {content[:3000]}\nExplica que es, por que importa, conexion con perfil. Cerra con Relevancia: alta/media/baja.", max_tokens=1000)


def generate_linkedin_post(feed_items, analysis):
    titles = "\n".join([f"- {i['title']} ({i['source']})" for i in feed_items[:15]])
    return call_claude(f"Sos Tomas, analista supply chain que construye IA aplicada en Buenos Aires. Primera persona, tono directo. Sin buzzwords.\nAvances: {titles}\nAnalisis: {analysis[:800]}\nPost LinkedIn: observacion propia, 3-4 items, reflexion final, hashtags. Max 250 palabras.", max_tokens=800)


def send_to_kindle(content, date_str):
    subject = f"Pulse AI — {date_str}"
    html = f"<html><body style='font-family:Georgia;font-size:16px;line-height:1.8;max-width:680px;margin:0 auto;padding:20px'><h2>{subject}</h2><div style='white-space:pre-wrap'>{content}</div></body></html>"
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = KINDLE_EMAIL
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            s.sendmail(GMAIL_ADDRESS, KINDLE_EMAIL, msg.as_string())
        return True, ""
    except Exception as e:
        return False, str(e)


# ── Init ──────────────────────────────────────────────────────────────────────
for k in ["feed_data", "analysis", "linkedin_post", "errors", "selected_item", "selected_content", "item_analysis"]:
    if k not in st.session_state:
        st.session_state[k] = None

# ── Header ────────────────────────────────────────────────────────────────────
st.markdown('<div class="pulse-header">⚡ Pulse AI</div>', unsafe_allow_html=True)
date_str = datetime.now(timezone.utc).strftime("%d %b %Y")
st.markdown(f'<div class="pulse-sub">AI Intelligence Radar · {date_str}</div>', unsafe_allow_html=True)

# ── PASO 1: Cargar fuentes ────────────────────────────────────────────────────
if st.button("⚡ Load sources"):
    with st.spinner("Loading sources..."):
        items, errors = fetch_items(FEEDS)
    st.session_state.feed_data = items
    st.session_state.errors = errors
    st.session_state.analysis = None
    st.session_state.linkedin_post = None
    st.session_state.selected_item = None
    st.session_state.selected_content = None
    st.session_state.item_analysis = None

# ── PASO 2: Analizar (solo si hay fuentes) ────────────────────────────────────
if st.session_state.feed_data is not None:
    if st.button("🧠 Analyze with AI"):
        with st.spinner("Analyzing with AI..."):
            result = generate_analysis(st.session_state.feed_data)
        st.session_state.analysis = result
        st.session_state.selected_item = None
        st.session_state.item_analysis = None

# ── PASO 3: LinkedIn y Kindle (solo si hay análisis) ─────────────────────────
if st.session_state.analysis is not None:
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💼 Post LinkedIn"):
            with st.spinner("Generando post..."):
                post = generate_linkedin_post(st.session_state.feed_data, st.session_state.analysis)
            st.session_state.linkedin_post = post
    with c2:
        if st.button("📖 Send to Kindle"):
            with st.spinner("Sending..."):
                ok, err = send_to_kindle(st.session_state.analysis, date_str)
            if ok:
                st.success("✓ Enviado al Kindle.")
            else:
                st.error(f"Error: {err}")

# ── Errors ────────────────────────────────────────────────────────────────────
if st.session_state.errors:
    with st.expander(f"⚠ {len(st.session_state.errors)} fuente(s) con error"):
        for e in st.session_state.errors:
            st.caption(e)

# ── Grid + Panel ──────────────────────────────────────────────────────────────
if st.session_state.feed_data:
    feed_items = st.session_state.feed_data
    grouped = defaultdict(list)
    for idx, item in enumerate(feed_items):
        item["_idx"] = idx
        grouped[item["category"]].append(item)

    left_col, right_col = st.columns([6, 4])

    with left_col:
        search = st.text_input("Buscar", placeholder="agents, RAG, memory, supply chain......", label_visibility="collapsed")
        query = search.strip().lower()
        if query:
            dg = defaultdict(list)
            for cat, ci in grouped.items():
                for item in ci:
                    if query in item["title"].lower() or query in item["summary"].lower():
                        dg[cat].append(item)
            st.caption(f"{sum(len(v) for v in dg.values())} results for '{query}'")
        else:
            dg = grouped
            st.caption(f"{len(feed_items)} items loaded")

        for category, cat_items in sorted(dg.items()):
            st.markdown(f'<div class="section-header">{category} — {len(cat_items)}</div>', unsafe_allow_html=True)
            cols = st.columns(2)
            for i, item in enumerate(cat_items):
                with cols[i % 2]:
                    pub = item["published"][:16] if item["published"] else ""
                    st.markdown(f"""<div class="card">
<div class="card-source">{item['source']}{f' · {pub}' if pub else ''}</div>
<div class="card-title">{item['title']}</div>
<div class="card-summary">{item['summary'][:200]}{'...' if len(item['summary']) > 200 else ''}</div>
</div>""", unsafe_allow_html=True)
                    if st.button("→ View", key=f"btn_{item['_idx']}"):
                        with st.spinner("Loading..."):
                            content = fetch_full_content(item)
                        st.session_state.selected_item = item
                        st.session_state.selected_content = content
                        st.session_state.item_analysis = None

    with right_col:
        if st.session_state.selected_item:
            sel = st.session_state.selected_item
            st.markdown(f'<div class="detail-source">{sel["source"]} · {sel["category"]}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="detail-title">{sel["title"]}</div>', unsafe_allow_html=True)
            if sel.get("link"):
                st.markdown(f'[🔗 Open original]({sel["link"]})')
            st.markdown("---")
            content = st.session_state.selected_content or sel["summary"]
            st.markdown(f'<div class="detail-content">{content[:2000]}</div>', unsafe_allow_html=True)
            st.markdown("---")
            if st.button("🧠 Analizar este item", key="analyze_item"):
                with st.spinner("Analyzing..."):
                    st.session_state.item_analysis = analyze_single_item(sel, content)
            if st.session_state.item_analysis:
                st.markdown(f'<div class="analysis-box">{st.session_state.item_analysis}</div>', unsafe_allow_html=True)
        elif st.session_state.analysis:
            st.markdown('<div class="section-header">🧠 Global analysis</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="analysis-box">{st.session_state.analysis}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="empty-panel">← load sources to get started</div>', unsafe_allow_html=True)

# ── LinkedIn post ─────────────────────────────────────────────────────────────
if st.session_state.linkedin_post:
    st.markdown('<div class="section-header">💼 Post LinkedIn</div>', unsafe_allow_html=True)
    st.code(st.session_state.linkedin_post, language=None)
