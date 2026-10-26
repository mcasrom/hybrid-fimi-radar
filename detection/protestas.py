#!/usr/bin/env python3
"""protestas.py — ficha curada + señal del radar para el piloto `protestas_juveniles`.

Qué hace:
  - Lee `data/protestas.yaml` (episodios, demandas y llamadas documentadas).
  - Lee `data/radar.db` (eventos/clusters del tema) SIN tocar scoring.
  - Escribe `data/protestas.json` y `/var/www/fimi/casos/protestas/index.html`.

Límites:
  - No atribuye autoría ni intención.
  - Las demandas/llamadas son citas curadas, no extracción automática.
  - La señal del radar mide eventos y amplificación, no hechos verificados.

Uso:
  .venv/bin/python detection/protestas.py
  .venv/bin/python detection/protestas.py --json-only
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
YAML_PATH = ROOT / "data" / "protestas.yaml"
JSON_OUT = Path("/var/www/fimi/datos/protestas.json")
HTML_OUT = Path("/var/www/fimi/casos/protestas/index.html")
TEMA = "protestas_juveniles"

sys.path.insert(0, str(ROOT))
from detection.bandas import BAND_ES, banda  # noqa: E402


def n(x) -> str:
    return f"{int(round(float(x or 0))):,}".replace(",", ".")


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


def fecha(x) -> str:
    if hasattr(x, "isoformat"):
        return x.isoformat()
    return str(x or "")


def cargar_episodios() -> list:
    return yaml.safe_load(YAML_PATH.read_text(encoding="utf-8")) or []


def señal(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT e.author), MIN(e.timestamp), MAX(e.timestamp) "
        "FROM events e JOIN event_temas et ON et.event_id=e.id WHERE et.tema_id=?",
        (TEMA,),
    ).fetchone()
    n_ev, n_aut, t0, t1 = row
    cl = conn.execute(
        "SELECT cluster_label, overall_score, created_at FROM clusters "
        "WHERE tema_id=? ORDER BY overall_score DESC", (TEMA,)
    ).fetchall()
    bandas = {}
    for r in cl:
        b = banda(r["overall_score"] or 0)
        bandas[b] = bandas.get(b, 0) + 1
    # dominios con más presencia (sin exponer cuentas)
    doms = {}
    for r in conn.execute(
        "SELECT e.url FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.url IS NOT NULL AND e.url<>''", (TEMA,)
    ):
        try:
            host = urllib.parse.urlparse(r[0]).netloc.lower().replace("www.", "")
        except Exception:
            host = ""
        if host:
            doms[host] = doms.get(host, 0) + 1
    top_doms = sorted(doms.items(), key=lambda x: -x[1])[:8]
    return {
        "eventos": n_ev or 0,
        "cuentas": n_aut or 0,
        "desde": int(t0) if t0 else None,
        "hasta": int(t1) if t1 else None,
        "clusters": len(cl),
        "bandas": bandas,
        "max_score": round(max((r["overall_score"] or 0 for r in cl), default=0), 1),
        "top_clusters": [
            {
                "label": r["cluster_label"],
                "score": round(r["overall_score"] or 0, 1),
                "banda": banda(r["overall_score"] or 0),
                "banda_es": BAND_ES.get(banda(r["overall_score"] or 0), banda(r["overall_score"] or 0)),
            } for r in cl[:8]
        ],
        "top_dominios": [{"dominio": d, "eventos": c} for d, c in top_doms],
    }


def dt(ts):
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m/%Y")


CSS = """
:root{--navy:#0f172a;--ink:#1e293b;--muted:#64748b;--line:#e2e8f0;--orange:#f97316;--blue:#38bdf8;--bg:#f8fafc}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:#c2410c}
header{background:var(--navy);color:#fff;padding:18px 0;border-top:4px solid var(--orange)}
.wrap{max-width:1060px;margin:0 auto;padding:0 22px}
.brand{font-weight:800;letter-spacing:.02em;text-decoration:none;color:#fff}
.brand span{color:var(--blue)}
.kicker{color:#fdba74;font-size:.78rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase}
h1{font-size:clamp(2rem,5vw,3.5rem);line-height:1.08;margin:.25em 0 .2em;letter-spacing:-.03em}
h2{font-size:1.45rem;margin:2.2rem 0 .6rem;letter-spacing:-.01em}
h3{font-size:1.08rem;margin:0 0 .35rem}
.lead{font-size:1.12rem;color:#334155;max-width:820px}
.badge{display:inline-block;background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;border-radius:999px;padding:4px 10px;font-size:.78rem;font-weight:800;margin:0 6px 6px 0}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:20px 0}
.kpi{background:#fff;border:1px solid var(--line);border-radius:14px;padding:15px}
.kpi b{display:block;font-size:1.55rem;line-height:1.1;color:var(--navy)}
.kpi span{font-size:.78rem;color:var(--muted)}
.note{background:#fff7ed;border-left:4px solid var(--orange);padding:14px 16px;border-radius:0 10px 10px 0;margin:18px 0}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px;margin:14px 0}
.meta{font-size:.82rem;color:var(--muted)}
.tag{display:inline-block;background:#f1f5f9;border:1px solid var(--line);border-radius:6px;padding:2px 7px;font-size:.75rem;margin:2px 4px 2px 0}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:.9rem}
th{background:#f1f5f9;color:#334155;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
tr:last-child td{border-bottom:0}
ul{margin:.4rem 0 .4rem 1.15rem;padding:0}
footer{border-top:1px solid var(--line);margin-top:30px;padding:20px 0 40px;color:var(--muted);font-size:.85rem}
@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}table{display:block;overflow-x:auto}}
"""


def render(epis: list, s: dict, ahora: str) -> str:
    eps = []
    for e in epis:
        dem = e.get("demandas") or []
        dem_html = "<ul>" + "".join(f"<li>{esc(x)}</li>" for x in dem) + "</ul>" if dem else "<p class='meta'>Sin pliego público localizado.</p>"
        fuentes = "".join(
            f"<a href='{esc(u)}' target='_blank' rel='noopener noreferrer'>fuente</a> "
            for u in (e.get("fuentes") or [])
        )
        eps.append(f"""
        <article class="card">
          <div class="meta">{esc(fecha(e.get('fecha')))} · {esc(e.get('pais'))} · {esc(e.get('ciudad'))}</div>
          <h3>{esc(e.get('nombre'))}</h3>
          <p class="meta"><b>Estado:</b> {esc(e.get('estado'))}</p>
          <p><b>Detonante documentado:</b> {esc(e.get('detonante'))}</p>
          <p><b>Quién convoca:</b> {esc(e.get('convocantes'))}</p>
          <p><b>Demandas declaradas:</b></p>{dem_html}
          <p><b>Llamada / acción:</b> {esc(e.get('llamada'))}</p>
          <p class="meta"><b>Alcance:</b> {esc(e.get('alcance'))}</p>
          <p class="meta"><b>Límite:</b> {esc(e.get('nota'))}</p>
          <p class="meta">Fuentes: {fuentes or '—'}</p>
        </article>""")

    banda_rows = "".join(
        f"<tr><td>{esc(BAND_ES.get(b, b))}</td><td>{n(c)}</td></tr>"
        for b, c in sorted(s["bandas"].items(), key=lambda x: -x[1])
    ) or "<tr><td colspan='2'>Sin clusters todavía.</td></tr>"
    top = "".join(
        f"<tr><td>{esc(c['label'])}</td><td>{c['score']:.1f}</td><td>{esc(c['banda_es'])}</td></tr>"
        for c in s["top_clusters"]
    ) or "<tr><td colspan='3'>Sin clusters todavía.</td></tr>"
    doms = "".join(
        f"<tr><td>{esc(d['dominio'])}</td><td>{n(d['eventos'])}</td></tr>"
        for d in s["top_dominios"]
    ) or "<tr><td colspan='2'>Sin dominios todavía.</td></tr>"

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Protestas juveniles · piloto FIMI</title>
<meta name="robots" content="noindex,follow">
<style>{CSS}</style></head><body>
<header><div class="wrap"><a class="brand" href="/">📡 Observatorio <span>/ protestas juveniles</span></a></div></header>
<main class="wrap">
<p class="kicker">Piloto · señal de amplificación</p>
<h1>Protestas juveniles: qué se documenta y qué se amplifica</h1>
<p class="lead">Una ficha para seguir la ola de protestas de 2025–26 sin confundir <b>demandas citadas</b>, <b>difusión observada</b> y <b>atribución</b>. El radar mide repetición y extensión; no identifica autores ni intención.</p>
<p><span class="badge">Piloto</span><span class="badge">Sin atribución</span><span class="badge">Fuentes enlazadas</span></p>
<div class="note"><b>Cómo leer esta página.</b> Los KPIs y clústeres salen de <code>event_temas</code> del tema <code>{TEMA}</code>. Las demandas y llamadas son una selección curada de fuentes públicas, no una extracción automática. Una banda alta significa <b>amplificación anómala</b>, no coordinación confirmada.</div>
<div class="grid">
  <div class="kpi"><b>{n(s['eventos'])}</b><span>eventos etiquetados</span></div>
  <div class="kpi"><b>{n(s['cuentas'])}</b><span>cuentas distintas</span></div>
  <div class="kpi"><b>{n(s['clusters'])}</b><span>clústeres</span></div>
  <div class="kpi"><b>{n(s['bandas'].get('HIGH', 0) + s['bandas'].get('CRITICAL', 0))}</b><span>en banda alta</span></div>
</div>
<p class="meta">Última observación: {dt(s['hasta'])} · ventana del piloto: 14 días · actualizado: {esc(ahora)} UTC.</p>

<h2>Episodios curados</h2>
<p class="meta">Cinco fichas para separar el hecho, la demanda y la llamada. No todas tienen un pliego público: cuando no lo hay, se dice.</p>
{''.join(eps)}

<h2>Señal del radar</h2>
<div class="grid">
  <div class="kpi"><b>{n(s['eventos'])}</b><span>eventos</span></div>
  <div class="kpi"><b>{n(s['cuentas'])}</b><span>cuentas</span></div>
  <div class="kpi"><b>{n(s['clusters'])}</b><span>clústeres</span></div>
  <div class="kpi"><b>{s['max_score']:.1f}</b><span>score máximo</span></div>
</div>
<p class="meta">Periodo: {dt(s['desde'])} → {dt(s['hasta'])}. Cifras calculadas desde <code>radar.db</code>; no son hechos verificados.</p>
<h3>Reparto por banda</h3>
<table><thead><tr><th>Banda</th><th>Clústeres</th></tr></thead><tbody>{banda_rows}</tbody></table>
<h3>Clústeres con más señal</h3>
<table><thead><tr><th>Clúster</th><th>Score</th><th>Banda</th></tr></thead><tbody>{top}</tbody></table>
<h3>Dominios con más presencia</h3>
<table><thead><tr><th>Dominio</th><th>Eventos</th></tr></thead><tbody>{doms}</tbody></table>

<h2>Qué vigilar</h2>
<ul>
  <li><b>Extensión:</b> si las mismas consignas saltan de país sin un detonante local.</li>
  <li><b>Amplificación:</b> si crecen las cuentas y dominios que repiten el mismo contenido en una ventana corta.</li>
  <li><b>Objetivos:</b> si aparece un pliego, comunicado o fuente primaria que permita citar demandas, no inferirlas.</li>
  <li><b>Atribución:</b> solo con evidencia independiente; el radar no la proporciona.</li>
</ul>
<p><a href="/datos/protestas.json">Datos abiertos (JSON)</a> · <a href="/">Volver al radar</a> · <a href="/casos/electoral/">Panorama electoral</a></p>
<footer>Elaborado con asistencia de IA y revisión humana. Fuentes enlazadas en el texto. — @pruebapublica<br>
Piloto <code>{TEMA}</code> · no indexado hasta revisión · {esc(ahora)} UTC</footer>
</main></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    a = ap.parse_args()
    epis = cargar_episodios()
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    s = señal(conn)
    conn.close()
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    data = {"tema": TEMA, "actualizado": ahora, "episodios": epis, "senal": s}
    JSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[protestas] JSON -> {JSON_OUT} ({len(epis)} episodios, {s['eventos']} eventos)")
    if not a.json_only:
        HTML_OUT.parent.mkdir(parents=True, exist_ok=True)
        HTML_OUT.write_text(render(epis, s, ahora), encoding="utf-8")
        print(f"[protestas] HTML -> {HTML_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
