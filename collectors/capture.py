#!/usr/bin/env python3
"""Capturador ECR: recopila actividad pública (Telegram público + Bluesky)
hacia SQLite con timestamp, y ejecuta el análisis.

Uso:
    python scripts/capture.py                    # captura y analiza
    python scripts/capture.py --no-analyze       # solo captura

Cron sugerido (cada 6 horas):
    0 */6 * * * cd /home/miguelc/electoral-radar && .venv/bin/python scripts/capture.py >> logs/capture.log 2>&1

Sin APIs de pago. Telegram vía t.me/s/ (canales públicos). Bluesky API pública.
"""
import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "data" / "radar.db"
OUT = ROOT / "data" / "raw" / f"events_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ECR-capture/0.1"

# Canales Telegram públicos (ejemplos genéricos; configúralos en config.yaml)
TELEGRAM_CHANNELS = []  # p.ej. ["elfarodeceuta", "maldita_es"]
BLUESKY_QUERIES = []    # p.ej. ["elecciones", "voto"]
MAX_PER_SOURCE = 100


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "ignore")


def grab_telegram(channel):
    """Recopila mensajes de un canal público vía t.me/s/ (HTML)."""
    out = []
    try:
        html = http_get(f"https://t.me/s/{channel}")
        import re
        dates = re.findall(r'datetime="([^"]+)"', html)
        texts = re.findall(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.S)
        # limpiar HTML
        texts = [re.sub(r"<[^>]+>", " ", t).strip()[:500] for t in texts]
        for d, t in zip(dates, texts):
            ts = int(datetime.fromisoformat(d.replace("+00:00", "")).timestamp())
            out.append({"timestamp": ts, "author": f"tg:{channel}", "text": t,
                        "url": "", "hashtags": "", "mentions": "", "action": "post",
                        "source": f"telegram:{channel}"})
        out = out[:MAX_PER_SOURCE]
    except Exception as e:
        print(f"  telegram:{channel} error: {e}")
    return out


def _bsky_login(env_path=None):
    """Login a Bluesky con credenciales del .env del social-poster.

    El endpoint público de búsqueda (public.api.bsky.app) da 403; la API
    autenticada (api.bsky.app) funciona con la cuenta del operador.
    """
    env_path = env_path or "/home/deploy/hybrid-fimi-radar/.bsky_creds.env"
    env = {}
    if Path(env_path).exists():
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    ident = env.get("BSKY_USER", "")
    password = env.get("BSKY_APP_PASS", "")
    if not ident or not password:
        return None
    try:
        data = json.dumps({"identifier": ident, "password": password}).encode()
        req = urllib.request.Request("https://bsky.social/xrpc/com.atproto.server.createSession",
                                     data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        sess = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        return sess.get("accessJwt")
    except Exception as e:
        print(f"  bsky login error: {e}")
        return None


def grab_bluesky(query, n=50):
    """Posts reales de Bluesky (API autenticada, sin clave comercial)."""
    out = []
    jwt = _bsky_login()
    if not jwt:
        print("  bsky: sin credenciales disponibles (social-poster/.env)")
        return out
    try:
        import urllib.parse, re
        url = ("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q="
               + urllib.parse.quote(query) + f"&limit={n}")
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Bearer " + jwt)
        req.add_header("User-Agent", UA)
        data = json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
        for post in data.get("posts", []):
            author = (post.get("author") or {}).get("handle", "?")
            ts = int(datetime.fromisoformat(post["record"]["createdAt"].replace("Z", "+00:00")).timestamp())
            text = post["record"].get("text", "")
            import re as _re
            tags = " ".join(_re.findall(r"#\w+", text))
            mentions = " ".join(_re.findall(r"@\w+", text))
            out.append({"timestamp": ts, "author": f"bsky:{author}", "text": text[:500],
                        "url": "", "hashtags": tags, "mentions": mentions,
                        "action": "post", "source": "bluesky"})
        out = out[:n]
    except Exception as e:
        print(f"  bsky:{query} error: {e}")
    return out


def store_sqlite(events):
    """Inserta eventos en SQLite (tabla events, esquema centralizado)."""
    from normalizer.schema import get_conn
    con = get_conn(DB)
    con.executemany(
        "INSERT OR IGNORE INTO events (timestamp, source, title, url, text)"
        " VALUES (?,?,?,?,?)",
        [(e["timestamp"], e["source"], e["text"][:120], e["url"], e["text"]) for e in events])
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()
    return n


def grab_google_news(query, n=50):
    """Titulares reales de Google News RSS (sin clave)."""
    out = []
    try:
        import urllib.parse, re
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
               + "&hl=es&gl=ES&ceid=ES:es")
        html = http_get(url)
        items = re.findall(r"<item>(.*?)</item>", html, re.S)
        for it in items[:n]:
            title = re.search(r"<title>(.*?)</title>", it, re.S)
            pub = re.search(r"<pubDate>(.*?)</pubDate>", it, re.S)
            link = re.search(r"<link>(.*?)</link>", it, re.S)
            if not title:
                continue
            ts = int(datetime.strptime(pub.group(1), "%a, %d %b %Y %H:%M:%S %Z").timestamp()) if pub else int(time.time())
            out.append({"timestamp": ts, "author": "news:google",
                        "text": title.group(1).strip(), "url": link.group(1).strip() if link else "",
                        "hashtags": "", "mentions": "", "action": "post", "source": "google-news"})
    except Exception as e:
        print(f"  google-news:{query} error: {e}")
    return out


def grab_reddit_rss(subreddit, n=50):
    """Posts reales de un subreddit vía RSS."""
    out = []
    try:
        import re
        html = http_get(f"https://www.reddit.com/r/{subreddit}/.rss")
        items = re.findall(r"<entry>(.*?)</entry>", html, re.S)
        for it in items[:n]:
            title = re.search(r"<title>(.*?)</title>", it, re.S)
            pub = re.search(r"<published>(.*?)</published>", it, re.S)
            author = re.search(r"<name>(.*?)</name>", it, re.S)
            if not title:
                continue
            ts = int(datetime.fromisoformat(pub.group(1).replace("Z", "+00:00")).timestamp()) if pub else int(time.time())
            out.append({"timestamp": ts, "author": f"reddit:{author.group(1) if author else subreddit}",
                        "text": title.group(1).strip(), "url": "", "hashtags": "", "mentions": "",
                        "action": "post", "source": f"reddit:{subreddit}"})
    except Exception as e:
        print(f"  reddit:{subreddit} error: {e}")
    return out


def grab_mastodon(query, instance="mastodon.social", n=50):
    """Posts reales de Mastodon (API pública, sin clave)."""
    out = []
    try:
        import urllib.parse, json, re
        url = f"https://{instance}/api/v2/search?q=" + urllib.parse.quote(query) + f"&limit={n}"
        data = json.loads(http_get(url))
        for s in data.get("statuses", [])[:n]:
            ts = int(datetime.fromisoformat(s["created_at"].replace("Z", "+00:00")).timestamp())
            author = (s.get("account") or {}).get("acct", "?")
            text = re.sub(r"<[^>]+>", "", s.get("content", ""))[:500]
            tags = " ".join("#" + t["name"] for t in s.get("tags", []))
            out.append({"timestamp": ts, "author": f"masto:{author}", "text": text,
                        "url": s.get("url", ""), "hashtags": tags, "mentions": "",
                        "action": "post", "source": f"mastodon:{instance}"})
    except Exception as e:
        print(f"  mastodon:{query} error: {e}")
    return out


def grab_rss_feed(name, url, n=40):
    """RSS oficial/mediático vía feedparser (fuente prioritaria del prompt)."""
    out = []
    try:
        import feedparser
        feed = feedparser.parse(url)
        for e in feed.entries[:n]:
            ts = int(time.mktime(e.get("published_parsed") or e.get("updated_parsed") or time.gmtime()))
            title = e.get("title", "")
            link = e.get("link", "")
            summary = (e.get("summary") or "")[:200]
            out.append({"timestamp": ts, "author": f"rss:{name}", "text": title,
                        "url": link, "hashtags": "", "mentions": "",
                        "action": "post", "source": f"rss:{name}", "summary": summary})
    except Exception as e:
        print(f"  rss:{name} error: {e}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-analyze", action="store_true")
    ap.add_argument("--config", default=ROOT / "config.yaml")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(args.config))
    channels = cfg.get("capture", {}).get("telegram_channels", TELEGRAM_CHANNELS)
    queries = cfg.get("capture", {}).get("bluesky_queries", BLUESKY_QUERIES)
    news_queries = cfg.get("capture", {}).get("news_queries", ["elecciones espana", "voto espana", "Ceuta"])
    subreddits = cfg.get("capture", {}).get("subreddits", ["spain", "es"])
    masto_queries = cfg.get("capture", {}).get("mastodon_queries", ["elecciones espana", "politica espana"])

    print(f"[captura] {datetime.utcnow().isoformat()} UTC")
    events = []
    for ch in channels:
        print(f"  telegram/{ch} ...")
        events += grab_telegram(ch)
    for q in queries:
        print(f"  bluesky/{q} ...")
        events += grab_bluesky(q)
    for q in news_queries:
        print(f"  google-news/{q} ...")
        events += grab_google_news(q)
    for s in subreddits:
        print(f"  reddit/{s} ...")
        events += grab_reddit_rss(s)
    for q in masto_queries:
        print(f"  mastodon/{q} ...")
        events += grab_mastodon(q)
    # RSS oficiales/mediáticos (fuente prioritaria: FUENTE OFICIAL > RSS > WEB)
    for kind in ("official", "media"):
        for s in cfg.get("sources", {}).get(kind, []):
            name = s.get("name", kind)
            url = s.get("url", "")
            if url:
                print(f"  rss/{name} ...")
                events += grab_rss_feed(name, url)

    if not events:
        print("  No hay fuentes configuradas (config.yaml -> capture) o no se capturó nada.")
        return

    # dedupe
    seen = set()
    uniq = []
    for e in events:
        k = (e["author"], e["text"][:80], e["timestamp"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    json.dump(uniq, open(OUT, "w"), ensure_ascii=False, indent=1)
    total = store_sqlite(uniq)
    print(f"  capturados {len(uniq)} eventos nuevos; total en SQLite: {total}")
    print(f"  guardado: {OUT}")

    if not args.no_analyze:
        print("[analisis] ejecutando run_analysis sobre SQLite ...")
        from scripts.run_analysis import main as analyze
        # reutilizar el pipeline con la BD
        import subprocess
        subprocess.run([sys.executable, str(ROOT / "scripts" / "run_analysis.py"),
                        "--input", str(DB), "--report"], cwd=str(ROOT))


if __name__ == "__main__":
    main()
