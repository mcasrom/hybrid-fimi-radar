#!/usr/bin/env python3
"""Prepara una muestra ciega de narrativas y publica el código de marcos.

No asigna narrativas. Las columnas se rellenan a mano; el script solo valida
códigos, cuenta lo codificado y avisa de lo que queda pendiente.
"""
import argparse
import csv
import os
import html
import json
import random
import re
import sqlite3
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
OBS = HERE.parent
ROOT = OBS.parent
DB = Path(os.environ.get("OBS_DATA_DB", ROOT.parent / "observatorio/data/observatorio.db"))
CODIGO = HERE / "codigo.json"
SAMPLE = HERE / "muestra.csv"
OUT = HERE / "index.html"
JSON_OUT = HERE / "narrativas.json"
TOPIC_KEYS = ("frontera_sur", "protestas_juveniles", "infraestructuras_espana", "elecciones_generales")


def e(x):
    return html.escape(str(x or ""))


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm_title(value):
    value = html.unescape(str(value or "")).casefold()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def domain(url):
    host = (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    return host or "sin dominio"


def rows_for(con, topic, today, days=45):
    start = today - timedelta(days=days - 1)
    rows = con.execute(
        """SELECT id, title, url, source, published FROM items
           WHERE topic = ? AND published IS NOT NULL AND published >= ? AND published < ?
             AND source_lang = 'es' AND url NOT LIKE '%news.google.com%'
           ORDER BY published DESC""",
        (topic, start.isoformat(), (today + timedelta(days=1)).isoformat()),
    ).fetchall()
    seen, out = set(), []
    for r in rows:
        title = norm_title(r["title"])
        if not title:
            continue
        key = ((r["published"] or "")[:10], title, (r["source"] or "").strip())
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": r["id"], "topic": topic, "title": r["title"], "url": r["url"], "source": r["source"], "published": r["published"]})
    return out


def build_sample(per_topic, today, reset):
    if SAMPLE.exists() and not reset:
        return
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    selected = []
    try:
        for topic in TOPIC_KEYS:
            rows = rows_for(con, topic, today)
            rnd = random.Random(f"20261102-{topic}")
            take = min(per_topic, len(rows))
            selected.extend(rnd.sample(rows, take))
    finally:
        con.close()
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    with SAMPLE.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["id", "topic", "fecha", "fuente", "dominio", "titular", "narrativa", "nota"])
        for r in selected:
            w.writerow([
                r["id"], r["topic"], (r["published"] or "")[:10], r["source"],
                domain(r["url"]), r["title"], "", "",
            ])


def read_sample(codebook):
    if not SAMPLE.exists():
        return [], Counter(), [], 0
    rows = list(csv.DictReader(SAMPLE.open(encoding="utf-8")))
    valid_codes = {topic: {f["code"] for f in meta["frames"]} for topic, meta in codebook["topics"].items()}
    counts = Counter()
    errors = []
    coded = 0
    for i, row in enumerate(rows, start=2):
        code = (row.get("narrativa") or "").strip()
        if not code:
            continue
        coded += 1
        topic = (row.get("topic") or "").strip()
        if topic not in valid_codes:
            errors.append(f"fila {i}: tema desconocido {topic!r}")
        elif code not in valid_codes[topic]:
            errors.append(f"fila {i}: código {code!r} no válido para {topic}")
        else:
            counts[(topic, code)] += 1
    return rows, counts, errors, coded


def page(codebook, rows, counts, errors, coded):
    total = len(rows)
    status = "sin codificar" if not coded else f"{coded}/{total} codificadas"
    if errors:
        status += f" · {len(errors)} errores"
    blocks = []
    for topic, meta in codebook["topics"].items():
        frame_rows = "".join(
            f'<tr><td><code>{e(f["code"])}</code></td><td><b>{e(f["label"])}</b></td><td>{e(f["definition"])}</td><td>{e(f["include"])}</td><td>{e(f["exclude"])}</td></tr>'
            for f in meta["frames"]
        )
        topic_counts = "".join(
            f'<li><code>{e(code)}</code>: {n}</li>'
            for (t, code), n in counts.most_common()
            if t == topic
        ) or '<li class="muted">Sin codificar.</li>'
        blocks.append(f'''<h2>{e(meta["label"])}</h2><div style="overflow-x:auto"><table><thead><tr><th>Código</th><th>Marco</th><th>Definición</th><th>Incluye</th><th>Excluye</th></tr></thead><tbody>{frame_rows}</tbody></table></div><p class="muted">Recuento actual: <ul>{topic_counts}</ul></p>''')
    error_block = ""
    if errors:
        error_block = '<div class="box warn"><b>Errores de codificación.</b><ul>' + "".join(f"<li>{e(x)}</li>" for x in errors[:30]) + "</ul></div>"
    return f'''<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Narrativas · Observatorio de lo publicado</title>
<meta name="description" content="Código de marcos y muestra ciega para codificación manual de narrativas. Sin clasificación automática.">
<link rel="canonical" href="https://fimi.viajeinteligencia.com/observatorio/narrativas/">
<meta property="og:type" content="article"><meta property="og:title" content="Narrativas · Observatorio de lo publicado">
<meta property="og:description" content="Código de marcos y muestra para codificación manual. Sin IA.">
<meta property="og:url" content="https://fimi.viajeinteligencia.com/observatorio/narrativas/">
<meta property="og:image" content="https://fimi.viajeinteligencia.com/observatorio/og.png">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="https://fimi.viajeinteligencia.com/observatorio/og.png">
<style>
:root{{--a:#b45309;--i:#1e293b;--m:#64748b;--l:#fde68a;--bg:#fffaf5}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:linear-gradient(180deg,#fff,var(--bg));color:var(--i);line-height:1.6}}.wrap{{max-width:1100px;margin:0 auto;padding:28px 18px 60px}}a{{color:var(--a)}}h1{{font-size:1.8rem;line-height:1.2;margin:0 0 6px}}h2{{font-size:1.15rem;border-bottom:2px solid var(--l);padding-bottom:5px;margin:30px 0 10px}}.muted{{color:var(--m);font-size:.84rem}}.box{{background:#fff7ed;border-left:4px solid var(--a);padding:10px 14px;border-radius:7px;margin:12px 0}}.box.warn{{background:#fef2f2;border-left-color:#dc2626}}table{{width:100%;border-collapse:collapse;font-size:.86rem}}th,td{{border-bottom:1px solid #e2e8f0;padding:7px;text-align:left;vertical-align:top}}th{{background:#f8fafc;font-size:.75rem;text-transform:uppercase;letter-spacing:.04em;color:#475569}}code{{background:#f1f5f9;padding:2px 5px;border-radius:4px}}ul{{padding-left:20px}}li{{margin:4px 0}}.foot{{display:grid;grid-template-columns:1.4fr 1fr 1.2fr;gap:20px;margin-top:40px;border-top:2px solid var(--l);padding-top:22px;color:#334155;font-size:.86rem}}.foot b{{display:block;color:var(--i);margin-bottom:6px}}.foot a{{display:block;text-decoration:none;margin:4px 0}}.foot p{{margin:0 0 8px;color:var(--m)}}@media(max-width:760px){{h1{{font-size:1.45rem}}table{{font-size:.78rem}}th,td{{padding:6px}}.foot{{grid-template-columns:1fr}}}}
</style></head><body><div class="wrap">
<div class="sitehead"><a class="brand" href="/observatorio/">Observatorio de lo publicado</a><nav><a href="/observatorio/">Inicio</a><a href="/observatorio/ceuta/">Frontera Sur</a><a href="/observatorio/juventud/">Protestas juveniles</a><a href="/observatorio/campana/">Elecciones generales</a><a href="/observatorio/infraestructuras/">Infraestructuras</a><a href="/observatorio/evidencia/">Evidencia</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a></nav></div>
<p class="muted">Observatorio · Narrativas</p><h1>Narrativas: código y muestra</h1>
<p class="lead">Una publicación puede tener más de un marco, pero aquí se codifica un <b>marco dominante</b> por pieza. La asignación es manual y revisable; el script no usa IA ni reglas de palabras clave para etiquetar.</p>
<div class="box"><b>Estado:</b> {e(status)}. Muestra: {total} publicaciones. Descarga: <a href="/observatorio/narrativas/muestra.csv">muestra.csv</a>.</div>
{error_block}
<h2>Cómo codificar</h2><ol><li>Descarga <code>muestra.csv</code>.</li><li>Rellena <code>narrativa</code> con un código del tema o déjalo vacío si no encaja.</li><li>No cambies <code>id</code>, <code>topic</code> ni <code>titular</code>.</li><li>Devuelve el CSV corregido; se valida y se cuentan los códigos.</li></ol>
<p class="muted">Una publicación sin marco no es un error. Un mismo titular en medios distintos sigue siendo una publicación distinta.</p>
<h2>Marcos por tema</h2>{''.join(blocks)}
<div class="box"><b>Qué no es esto.</b> No es una clasificación automática, no mide coordinación y no atribuye intención. Los recuentos solo se publican cuando hay codificación manual suficiente.</div>
<footer class="foot"><div><b>Observatorio de lo publicado</b><p>Código y muestra para análisis manual.</p><p>Actualizado: {date.today().isoformat()}.</p></div><div><b>Secciones</b><a href="/observatorio/">Inicio</a><a href="/observatorio/evidencia/">Evidencia</a><a href="/observatorio/metodo/">Método</a><a href="/observatorio/fuentes/">Fuentes</a></div><div><b>Contacto</b><a href="mailto:info-fimi@viajeinteligencia.com">info-fimi@viajeinteligencia.com</a><p>Correcciones: indica la fila y el código.</p></div></footer>
</div></body></html>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-topic", type=int, default=15)
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--json", type=Path, default=JSON_OUT)
    args = ap.parse_args()
    today = args.today or datetime.now(timezone.utc).date()
    codebook = load(CODIGO)
    build_sample(args.per_topic, today, args.reset)
    rows, counts, errors, coded = read_sample(codebook)
    data = {
        "version": codebook["version"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sample": len(rows),
        "coded": coded,
        "pending": len(rows) - coded,
        "errors": errors,
        "counts": [{"topic": t, "code": c, "n": n} for (t, c), n in sorted(counts.items())],
        "codes": codebook["topics"],
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    args.out.write_text(page(codebook, rows, counts, errors, coded), encoding="utf-8")
    print(f"{args.out} · {coded}/{len(rows)} codificadas · {len(errors)} errores")


if __name__ == "__main__":
    main()
