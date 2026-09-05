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
            rec = post.get("record", {})
            try:
                ts = int(datetime.fromisoformat(rec["createdAt"].replace("Z", "+00:00")).timestamp())
            except Exception:
                ts = int(time.time())
            text = rec.get("text", "")
            import re as _re
            tags = " ".join(_re.findall(r"#\w+", text))
            mentions = " ".join(_re.findall(r"@\w+", text))
            # extraer URL: embed external + facets link
            url_found = ""
            embed = rec.get("embed")
            if isinstance(embed, dict):
                ext = embed.get("external") or {}
                if ext.get("uri"):
                    url_found = ext["uri"]
                elif embed.get("$type", "").endswith("embed.recordWithMedia"):
                    media = embed.get("media") or {}
                    mext = media.get("external") or {}
                    if mext.get("uri"):
                        url_found = mext["uri"]
            if not url_found:
                for f in rec.get("facets", []) or []:
                    for feat in f.get("features", []) or []:
                        if isinstance(feat, dict) and feat.get("uri") and feat["uri"].startswith("http"):
                            url_found = feat["uri"]
                            break
                    if url_found:
                        break
            out.append({"timestamp": ts, "author": f"bsky:{author}", "text": text[:500],
                        "url": url_found, "hashtags": tags, "mentions": mentions,
                        "action": "post", "source": "bluesky"})
        out = out[:n]
    except Exception as e:
        print(f"  bsky:{query} error: {e}")
    return out


def store_sqlite(events):
    """Inserta eventos en SQLite (tabla events, esquema centralizado).

    Cada evento lleva _temas (set de tema_ids). events.tema_id conserva el
    tema primario (legacy); event_temas guarda la relacion many-to-many para
    que un evento pueda pertenecer a varios temas sin duplicar la fila."""
    from normalizer.schema import get_conn
    con = get_conn(DB)
    con.executemany(
        "INSERT OR IGNORE INTO events (timestamp, source, author, title, url, text, tema_id)"
        " VALUES (?,?,?,?,?,?,?)",
        [(e["timestamp"], e["source"], e.get("author", ""), e["text"][:120], e["url"], e["text"],
          e.get("tema_id", "frontera_sur")) for e in events])
    con.commit()
    # relacion many-to-many: a cada evento (por url o texto) sus temas
    for e in events:
        temas = e.get("_temas") or {"frontera_sur"}
        if not temas:
            temas = {"frontera_sur"}
        row = con.execute(
            "SELECT id FROM events WHERE source=? AND author=? AND timestamp=? AND text=?",
            (e["source"], e.get("author", ""), e["timestamp"], e["text"])).fetchone()
        if not row:
            continue
        eid = row[0]
        for t in temas:
            con.execute("INSERT OR IGNORE INTO event_temas (event_id, tema_id) VALUES (?,?)",
                        (eid, t))
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

    # ---- Nueva estructura (config reorganizado) ----
    feeds = cfg.get("feeds", []) or []
    keywords = cfg.get("keywords", []) or []
    channels = cfg.get("telegram_canales", TELEGRAM_CHANNELS)
    subreddits = cfg.get("subreddits", ["spain", "es"])

    # compatibilidad con estructura antigua si existe
    if not feeds:
        feeds = []
        for kind, items in (cfg.get("sources", {}) or {}).items():
            for it in items:
                feeds.append({"nombre": it.get("name", kind), "url": it.get("url", ""), "tipo": kind})
    if not keywords and cfg.get("capture"):
        cap = cfg["capture"]
        keywords = ([{"palabra": q, "plataformas": ["bluesky"]} for q in cap.get("bluesky_queries", [])] +
                    [{"palabra": q, "plataformas": ["google-news"]} for q in cap.get("news_queries", [])] +
                    [{"palabra": q, "plataformas": ["mastodon"]} for q in cap.get("mastodon_queries", [])])
        channels = channels or cap.get("telegram_channels", [])
        subreddits = subreddits or cap.get("subreddits", ["spain", "es"])

    # derivar queries por plataforma desde keywords, arrastrando su tema
    bsky_q = [(k["palabra"], k.get("tema", "frontera_sur")) for k in keywords if "bluesky" in k.get("plataformas", [])]
    news_q = [(k["palabra"], k.get("tema", "frontera_sur")) for k in keywords if "google-news" in k.get("plataformas", [])]
    masto_q = [(k["palabra"], k.get("tema", "frontera_sur")) for k in keywords if "mastodon" in k.get("plataformas", [])]

    print(f"[captura] {datetime.utcnow().isoformat()} UTC")
    events = []
    for ch in channels:
        print(f"  telegram/{ch} ...")
        for e in grab_telegram(ch):
            e["_temas"] = {"frontera_sur"}
            events.append(e)
    for q, tema in bsky_q:
        print(f"  bluesky/{q} (tema={tema}) ...")
        for e in grab_bluesky(q):
            e["_temas"] = {tema}
            events.append(e)
    for q, tema in news_q:
        print(f"  google-news/{q} (tema={tema}) ...")
        for e in grab_google_news(q):
            e["_temas"] = {tema}
            events.append(e)
    for s in subreddits:
        print(f"  reddit/{s} ...")
        for e in grab_reddit_rss(s):
            e["_temas"] = {"frontera_sur"}
            events.append(e)
    for q, tema in masto_q:
        print(f"  mastodon/{q} (tema={tema}) ...")
        for e in grab_mastodon(q):
            e["_temas"] = {tema}
            events.append(e)
    # RSS feeds (todos los tipos)
    for s in feeds:
        name = s.get("nombre") or s.get("name") or "feed"
        url = s.get("url", "")
        tema = s.get("tema", "frontera_sur")
        if url:
            print(f"  rss/{name} (tema={tema}) ...")
            for e in grab_rss_feed(name, url):
                e["_temas"] = {tema}
                events.append(e)

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
        else:
            # mismo evento capturado por keyword de otro tema: acumular temas
            for existing in uniq:
                if (existing["author"], existing["text"][:80], existing["timestamp"]) == k:
                    existing.setdefault("_temas", set()).update(e.get("_temas", set()))
                    break

    # Clasificación por CONTENIDO multi-tema: aunque un evento se haya capturado
    # por la keyword de un tema (o un feed sin tema -> frontera_sur), si su texto
    # menciona keywords de otros temas se acumulan TODOS los que matcheen. Esto
    # corrige el sesgo de captura (los feeds RSS caen en frontera_sur por defecto
    # y geopolitica/politica quedaban pobres de datos).
    try:
        from normalizer.clasificar import temas_por_contenido
        for e in uniq:
            extra = temas_por_contenido((e.get("text") or "") + " " + (e.get("title") or ""), keywords)
            if extra:
                cur = set(e.get("_temas") or {"frontera_sur"})
                cur.update(extra)
                e["_temas"] = sorted(cur)
    except Exception as _exc:
        print(f"  clasificacion por contenido error: {_exc}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # _temas es un set (no serializable a JSON): convertir a lista para el dump
    for e in uniq:
        if isinstance(e.get("_temas"), set):
            e["_temas"] = sorted(e["_temas"])
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
