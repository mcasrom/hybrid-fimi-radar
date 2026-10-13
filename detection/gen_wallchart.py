#!/usr/bin/env python3
"""gen_wallchart.py — Wallchart A4 «mapa del sistema» con DATOS VIVOS.

Fuente editable: genera un HTML autocontenido (docs/wallchart.html) que se puede
imprimir, y lo renderiza a PNG (A4 300 dpi), PDF (A4) y thumbnail WebP con
Playwright/Chromium. Sustituye a la infografía raster de origen externo (sin
fuente), para que las cifras (commits, líneas, tests, corpus, temas) no se
desfasen.

Uso:
  .venv/bin/python detection/gen_wallchart.py [--out-dir docs] [--web /var/www/fimi]
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "radar.db"
CFG = ROOT / "config.yaml"
CHROME = "/home/deploy/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"
W, H, SCALE = 1122, 794, 3.125  # A4 apaisado @96dpi -> ~3506x2481

TEMA_NOMBRE = {
    "frontera_sur": "Frontera Sur", "eeuu_politica": "EEUU", "oriente_medio": "Oriente Medio",
    "sahel": "Sahel", "energia": "Energía", "inteligencia_artificial": "Inteligencia artificial",
    "espana_elecciones": "España elecciones", "elecciones": "Elecciones",
    "defensa_espana": "Defensa España", "geopolitica_ue_marruecos": "UE-Marruecos",
    "espana_amenazas_hibridas": "Amenazas híbridas", "politica_nacional": "Política nacional",
}


def mil(n):
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)


def _run(cmd):
    try:
        return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120).stdout.strip()
    except Exception:
        return ""


def gather():
    d = {}
    d["commits"] = _run(["git", "rev-list", "--count", "HEAD"]) or "—"
    ini = _run(["git", "log", "--reverse", "--format=%cs"])
    ini = ini.splitlines()[0] if ini else ""
    try:
        d["dias"] = (datetime.date.today() - datetime.date.fromisoformat(ini)).days
    except Exception:
        d["dias"] = "—"
    pys = [p for p in ROOT.rglob("*.py")
           if ".venv" not in p.parts and ".git" not in p.parts and ".bak" not in p.name]
    d["py_ficheros"] = len(pys)
    lineas = 0
    for p in pys:
        try:
            lineas += sum(1 for _ in open(p, encoding="utf-8", errors="ignore"))
        except Exception as e:
            print(f"wallchart: fichero no leible {p}: {e}", file=sys.stderr)
    d["py_lineas"] = lineas
    t = _run([".venv/bin/python", "-m", "pytest", "--collect-only", "-q"])
    m = None
    for ln in reversed(t.splitlines()):
        m = __import__("re").search(r"(\d+)\s+tests? collected", ln)
        if m:
            break
    d["tests"] = m.group(1) if m else "—"
    # BD
    try:
        c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        d["eventos"] = c.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        d["clusters"] = c.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        d["fuentes_ev"] = c.execute("SELECT COUNT(DISTINCT source) FROM events").fetchone()[0]
        c.close()
    except Exception:
        d["eventos"] = d["clusters"] = d["fuentes_ev"] = "—"
    # config
    prod, pil, cer = [], [], []
    feeds = kws = 0
    try:
        cfg = yaml.safe_load(open(CFG, encoding="utf-8"))
        feeds = len(cfg.get("feeds", []))
        kws = len(cfg.get("keywords", []))
        for k, v in (cfg.get("temas") or {}).items():
            e = (v or {}).get("estado", "produccion")
            (prod if e == "produccion" else pil if e == "piloto" else cer if e == "cerrado" else pil).append(k)
    except Exception as e:
        print(f"wallchart: config no leible: {e}", file=sys.stderr)
    d["feeds"], d["kws"] = feeds, kws
    d["temas_prod"], d["temas_pil"], d["temas_cer"] = prod, pil, cer
    d["head"] = _run(["git", "rev-parse", "--short", "HEAD"]) or "—"
    d["fecha"] = datetime.date.today().isoformat()
    return d


def chips(temas, cls):
    return "".join(f'<span class="chip {cls}">{TEMA_NOMBRE.get(t, t)}</span>' for t in temas)


def build_html(d):
    tpl = _TEMPLATE
    rep = {
        "@@COMMITS@@": str(d["commits"]), "@@DIAS@@": str(d["dias"]),
        "@@LINEAS@@": mil(d["py_lineas"]), "@@PYF@@": str(d["py_ficheros"]),
        "@@TESTS@@": str(d["tests"]),
        "@@NPROD@@": str(len(d["temas_prod"])), "@@NPIL@@": str(len(d["temas_pil"])),
        "@@NCER@@": str(len(d["temas_cer"])),
        "@@EVENTOS@@": mil(d["eventos"]), "@@CLUSTERS@@": mil(d["clusters"]),
        "@@FUENTES@@": str(d["fuentes_ev"]), "@@FEEDS@@": str(d["feeds"]), "@@KWS@@": str(d["kws"]),
        "@@CHIP_PROD@@": chips(d["temas_prod"], "prod"),
        "@@CHIP_PIL@@": chips(d["temas_pil"], "pil"),
        "@@CHIP_CER@@": chips(d["temas_cer"], "cer"),
        "@@HEAD@@": str(d["head"]), "@@FECHA@@": str(d["fecha"]),
    }
    for k, v in rep.items():
        tpl = tpl.replace(k, v)
    return tpl


def render(html, out_png, out_pdf, out_webp):
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": W, "height": H}, device_scale_factor=SCALE)
        pg.set_content(html, wait_until="load")
        pg.screenshot(path=out_png, clip={"x": 0, "y": 0, "width": W, "height": H})
        pg.pdf(path=out_pdf, width=f"{W}px", height=f"{H}px", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    try:
        from PIL import Image
        im = Image.open(out_png)
        nh = round(im.height * 720 / im.width)
        im.resize((720, nh), Image.LANCZOS).save(out_webp, "WEBP", quality=82)
    except Exception as e:
        print(f"webp: {e}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(ROOT / "docs"))
    ap.add_argument("--web", default="/var/www/fimi")
    ap.add_argument("--html-only", action="store_true")
    a = ap.parse_args()
    d = gather()
    html = build_html(d)
    hp = Path(a.out_dir) / "wallchart.html"
    hp.write_text(html, encoding="utf-8")
    print(f"HTML -> {hp}")
    if a.html_only:
        return
    od = Path(a.out_dir)
    render(html, od / "fimi-wallchart-A4.png", od / "fimi-wallchart-A4.pdf",
           Path(a.web) / "fimi-wallchart-web.webp")
    # copiar a /var/www/fimi
    shutil.copy(od / "fimi-wallchart-A4.png", Path(a.web) / "fimi-wallchart-A4.png")
    shutil.copy(od / "fimi-wallchart-A4.pdf", Path(a.web) / "fimi-wallchart-A4.pdf")
    print(f"OK wallchart: commits={d['commits']} ev={d['eventos']} clusters={d['clusters']}")


_TEMPLATE = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<style>
:root{--navy:#0c2340;--ink:#0f172a;--mut:#64748b;--line:#e2e8f0;--teal:#0e7490;--blue:#1d4ed8;--amber:#d97706;--green:#16a34a}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1122px;height:794px;overflow:hidden;background:#fff;color:var(--ink);
 font-family:"DejaVu Sans",-apple-system,Segoe UI,Roboto,Arial,sans-serif;font-size:11px;line-height:1.32}
.page{width:1122px;height:794px;padding:14px 16px 10px;display:flex;flex-direction:column;gap:10px}
.hd{display:flex;align-items:center;gap:16px;background:linear-gradient(90deg,var(--navy),#10315c);
 color:#fff;border-radius:10px;padding:12px 18px}
.hd .logo{width:46px;height:46px;flex:0 0 46px}
.hd h1{font-size:23px;font-weight:800;letter-spacing:.2px}
.hd .sub{color:#c7d6ea;font-size:11.5px}
.hd .meta{color:#8aa2c0;font-size:9.5px;margin-top:2px}
.kpis{margin-left:auto;display:flex;gap:8px}
.kpi{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);border-radius:8px;
 padding:7px 12px;text-align:center;min-width:96px}
.kpi b{display:block;font-size:18px;font-weight:800}
.kpi span{font-size:9px;color:#c7d6ea}
.row{display:flex;gap:10px;flex:1 1 0;min-height:0}
.box{background:#fff;border:1px solid var(--line);border-radius:9px;padding:9px 12px;overflow:hidden;display:flex;flex-direction:column;min-height:0}
.box.t1{flex:0 0 auto}
.box>h2{font-size:12.5px;font-weight:800;display:flex;align-items:center;gap:7px;margin-bottom:6px}
.num{display:inline-flex;width:18px;height:18px;border-radius:50%;background:var(--teal);color:#fff;
 align-items:center;justify-content:center;font-size:11px;font-weight:800}
.box.t2 .num{background:#0ea5e9}.box.t3 .num{background:var(--blue)}.box.t4 .num{background:#7c3aed}
.box.t5 .num{background:var(--green)}.box.t6 .num{background:var(--amber)}.box.t7 .num{background:#dc2626}
.box.t8 .num{background:#334155}
.k{color:var(--teal);font-weight:800}
ul{list-style:none}li{position:relative;padding-left:11px;margin:2.5px 0;color:#334155}
li:before{content:"•";position:absolute;left:0;color:var(--teal);font-weight:800}
.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin:2px 3px 0 0;font-size:9.5px}
.chip.prod{border-color:#a7f3d0;background:#ecfdf5;color:#065f46}
.chip.pil{border-color:#fde68a;background:#fffbeb;color:#92400e}
.chip.cer{border-color:#e2e8f0;background:#f8fafc;color:#64748b;text-decoration:line-through}
/* pipeline */
.pipe{display:flex;gap:6px}
.stage{flex:1;text-align:center}
.stage .bar{background:linear-gradient(180deg,#1e40af,#0e7490);color:#fff;border-radius:6px;padding:7px 4px;font-weight:800;font-size:11px}
.stage .bar small{display:block;font-size:8.5px;font-weight:400;color:#c7d6ea}
.stage .desc{font-size:8.6px;color:#64748b;margin-top:4px}
.stage .desc b{color:var(--teal)}
/* bands */
.bands{display:flex;gap:3px;margin:5px 0;font-size:8px;text-align:center}
.bands div{flex:1;color:#fff;border-radius:4px;padding:3px 0;font-weight:800}
.sc{display:flex;gap:5px;align-items:center;margin:2.5px 0;font-size:9.5px}
.sc .lbl{width:98px;color:#475569}
.sc .track{flex:1;height:9px;background:#eef2f7;border-radius:5px;overflow:hidden}
.sc .track i{display:block;height:100%}
.hyp{display:flex;gap:6px;margin:2px 0;font-size:8.8px;color:#475569}
.hyp b{color:var(--blue)}
.two{display:flex;gap:14px}.two>div{flex:1}
.foot{display:flex;justify-content:space-between;color:#94a3b8;font-size:9px;padding:0 4px}
.wm{color:#94a3b8;font-weight:800}
.p{color:var(--teal);font-weight:700}
.callout{background:#f8fafc;border:1px solid var(--line);border-radius:6px;padding:5px 8px;font-size:9px;color:#475569;margin-top:5px}
</style></head><body><div class="page">

<div class="hd">
  <svg class="logo" viewBox="0 0 44 44"><circle cx="22" cy="22" r="20" fill="none" stroke="#38bdf8" stroke-width="2.5"/><circle cx="22" cy="22" r="3.4" fill="#38bdf8"/><path d="M22 2v6M22 36v6M2 22h6M36 22h6" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round"/></svg>
  <div>
    <h1>FIMI RADAR</h1>
    <div class="sub">Observatorio de amplificación · mapa del sistema</div>
    <div class="meta">github.com/mcasrom/hybrid-fimi-radar · AGPL-3.0 · v0.2 · <b>@@FECHA@@</b></div>
  </div>
  <div class="kpis">
    <div class="kpi"><b>@@COMMITS@@</b><span>commits · @@DIAS@@ días</span></div>
    <div class="kpi"><b>@@LINEAS@@</b><span>líneas · @@PYF@@ .py</span></div>
    <div class="kpi"><b>@@TESTS@@</b><span>tests</span></div>
    <div class="kpi"><b>@@NPROD@@ + @@NPIL@@</b><span>activos + piloto</span></div>
    <div class="kpi"><b>6 h</b><span>ciclo de captura</span></div>
  </div>
</div>

<!-- 1 PIPELINE -->
<div class="box t1">
  <h2><span class="num">1</span>PIPELINE · se ejecuta cada 6 h <span style="color:#94a3b8;font-weight:400">scripts/cron_every_6h.sh</span></h2>
  <div class="pipe">
    <div class="stage"><div class="bar">1<small>CAPTURA</small></div><div class="desc">collectors/capture.py<br>RSS (@@FEEDS@@ feeds), Bluesky, Telegram, Google News</div></div>
    <div class="stage"><div class="bar">2<small>NORMALIZA</small></div><div class="desc">normalizer/ ingesta, etiquetado por tema y esquema SQLite</div></div>
    <div class="stage"><div class="bar">3<small>FEATURES</small></div><div class="desc">features/ tiempos, contenido y señales de bot</div></div>
    <div class="stage"><div class="bar">4<small>DETECCIÓN</small></div><div class="desc">detection/run_fimi.py <b>ventana 45 d</b> (90 d en temas de historia)</div></div>
    <div class="stage"><div class="bar">5<small>CLUSTERS</small></div><div class="desc">clustering/ grafo k-core (scipy sparse)</div></div>
    <div class="stage"><div class="bar">6<small>SCORING</small></div><div class="desc">scoring.py 0-100, bandas y topes anti-eco</div></div>
    <div class="stage"><div class="bar">7<small>ATRIBUCIÓN</small></div><div class="desc">attribution/ UNKNOWN por defecto; hipótesis H1-H6</div></div>
    <div class="stage"><div class="bar">8<small>PUBLICA</small></div><div class="desc">gen_fimi_html.py dashboard, API v1, avisos</div></div>
  </div>
  <div class="callout"><b>Regla de oro:</b> observación → anomalía → coordinación → cluster → hipótesis → atribución con confianza. <b>Nunca al revés: no se parte de un actor sospechoso.</b></div>
</div>

<div class="row">
  <!-- 2 FUENTES Y TEMAS -->
  <div class="box t2" style="flex:1.15">
    <h2><span class="num">2</span>FUENTES Y TEMAS</h2>
    <li><span class="k">Corpus ≈ @@EVENTOS@@ eventos · @@CLUSTERS@@ clusters</span></li>
    <li>@@FEEDS@@ feeds RSS + 2 búsquedas de plataforma</li>
    <li>Bluesky + Google News ≈ 95 % del corpus</li>
    <li>Telegram: 6 canales públicos; Reddit aparcado (429)</li>
    <li>Sin X, TikTok, Meta, YouTube ni WhatsApp</li>
    <li style="margin-top:5px"><b>Temas definidos en config.yaml (@@NPROD@@+@@NPIL@@+@@NCER@@)</b></li>
    <div style="margin-top:3px"><span style="color:#065f46;font-weight:700;font-size:9.5px">PRODUCCIÓN · @@NPROD@@</span><br>@@CHIP_PROD@@</div>
    <div style="margin-top:3px"><span style="color:#92400e;font-weight:700;font-size:9.5px">PILOTO · @@NPIL@@</span><br>@@CHIP_PIL@@</div>
    <div style="margin-top:3px"><span style="color:#64748b;font-weight:700;font-size:9.5px">CERRADOS · @@NCER@@</span><br>@@CHIP_CER@@</div>
  </div>

  <!-- 3 SCORING -->
  <div class="box t3" style="flex:1">
    <h2><span class="num">3</span>SCORING · 0-100 POR CLUSTER</h2>
    <div style="font-size:9.5px;color:#64748b">Peso de cada componente (suman 100 %)</div>
    <div class="sc"><span class="lbl">Anomalía</span><div class="track"><i style="width:50%;background:#0e7490"></i></div><b>50,0 %</b></div>
    <div class="sc"><span class="lbl">Sincronización</span><div class="track"><i style="width:16.7%;background:#1d4ed8"></i></div><b>16,7 %</b></div>
    <div class="sc"><span class="lbl">Similitud contenido</span><div class="track"><i style="width:16.7%;background:#7c3aed"></i></div><b>16,7 %</b></div>
    <div class="sc"><span class="lbl">Infraestructura</span><div class="track"><i style="width:11.1%;background:#16a34a"></i></div><b>11,1 %</b></div>
    <div class="sc"><span class="lbl">Amplificación</span><div class="track"><i style="width:5.6%;background:#d97706"></i></div><b>5,6 %</b></div>
    <div style="font-weight:800;margin-top:7px;font-size:9.5px">Bandas de score</div>
    <div class="bands">
      <div style="background:#16a34a">NORMAL<br>0-19</div><div style="background:#0891b2">WATCH<br>20-39</div>
      <div style="background:#eab308">ANOMALOUS<br>40-59</div><div style="background:#f97316">HIGH<br>60-79</div>
      <div style="background:#dc2626">CRITICAL<br>80-100</div>
    </div>
    <li>HIGH exige ≥3 cuentas y anomalía ≥20; CRITICAL ≥10 cuentas y ≥40</li>
    <li>Topes anti-eco: 1 URL, ≥80 % prensa o ≥90 % un dominio → máx. ANOMALOUS</li>
    <li>La densidad de red se publica, pero no pondera.</li>
  </div>

  <!-- 4 ATRIBUCIÓN -->
  <div class="box t4" style="flex:1.05">
    <h2><span class="num">4</span>ATRIBUCIÓN Y HIPÓTESIS</h2>
    <div style="font-size:9.5px;color:#64748b">Taxonomía neutra (módulo separado del detector)</div>
    <div style="margin:3px 0"><span class="chip" style="background:#0c2340;color:#fff;border:none">UNKNOWN (por defecto)</span> <span class="chip">DOMESTIC</span> <span class="chip">FOREIGN_STATE</span> <span class="chip">FOREIGN_NON_STATE</span> <span class="chip">TRANSNATIONAL</span> <span class="chip">PROXY</span> <span class="chip">MIXED</span> <span class="chip">UNDETERMINED</span></div>
    <div style="font-size:9.5px;color:#64748b;margin-top:4px">Confianza <span class="chip">NO</span><span class="chip">LOW</span><span class="chip">MEDIUM</span><span class="chip">HIGH</span></div>
    <div style="font-weight:800;margin-top:6px;font-size:9.5px">Hipótesis evaluadas (no alimentan el score)</div>
    <div class="hyp"><b>H1</b> Viralidad orgánica</div>
    <div class="hyp"><b>H2</b> Coordinación doméstica con estructura</div>
    <div class="hyp"><b>H2b</b> Sincronización sin atribución de operador</div>
    <div class="hyp"><b>H3</b> Posible operación de influencia extranjera</div>
    <div class="hyp"><b>H4</b> Amplificación mediática</div>
    <div class="hyp"><b>H5</b> Sincronía sostenida, sin estructura · <b>H6</b> sin evidencia</div>
    <div class="callout">«Sin evidencia para atribuir» es una conclusión válida. La ideología nunca es un indicador de amenaza.</div>
  </div>
</div>

<div class="row">
  <!-- 5 SALIDAS -->
  <div class="box t5">
    <h2><span class="num">5</span>SALIDAS</h2>
    <li>Dashboard estático con pestañas, diales por tema y tarjetas de cluster</li>
    <li>API v1 de solo lectura con OpenAPI: /temas, /tema/&lt;slug&gt;, /cluster/&lt;label&gt;, /buscar y serie diaria</li>
    <li>Datasets abiertos CC BY 4.0 (CSV/JSON) y export de evidencia por cluster</li>
    <li>Contraste con verificadores (Maldita, Newtral): feed RSS y JSON</li>
    <li>Telegram @RadarFIMI_bot y digest semanal por email</li>
  </ul></div>

  <!-- 6 AUTO-AUDITORÍA -->
  <div class="box t6">
    <h2><span class="num">6</span>AUTO-AUDITORÍA Y GOBERNANZA</h2>
    <li>check_sistema: frescura de captura, integridad de la BD y coherencia de la config</li>
    <li>salud_keywords: ¿cada tema capta su ruido real?</li>
    <li>health_fuentes + notify_fuentes: avisa cuando una fuente se cae</li>
    <li>check_promocion (72 h) y check_cierre solo sugieren; decide una persona</li>
    <li>Solo datos públicos, sin perfilado, retención de 90 días</li>
  </ul></div>

  <!-- 7 VALIDACIÓN -->
  <div class="box t7">
    <h2><span class="num">7</span>VALIDACIÓN Y LÍMITES</h2>
    <div style="font-weight:800;color:#b91c1c">Validación ciega del 29-sep: 40 clusters HIGH</div>
    <div class="bands" style="margin:4px 0">
      <div style="background:#16a34a">3<br><span style="font-weight:400">sí coord.</span></div>
      <div style="background:#eab308">33<br><span style="font-weight:400">sin coord.</span></div>
      <div style="background:#f97316">4<br><span style="font-weight:400">dudosos</span></div>
    </div>
    <li>3 de 33 evaluables (8,3 %) con coordinación; un solo revisor</li>
    <li>Sintética: ARI 1,000 en 6 escenarios; sin falsos positivos A/D</li>
    <li>Validación externa (EUvsDisinfo) mecánica, no concluyente</li>
    <div class="callout">Deuda conocida: cobertura sesgada a Bluesky y Google News; un solo mantenedor.</div>
  </div>

  <!-- 8 STACK -->
  <div class="box t8">
    <h2><span class="num">8</span>STACK Y CALIDAD</h2>
    <div style="font-weight:800;font-size:9.5px">Pila</div>
    <div><span class="chip">Python 3.12</span><span class="chip">pandas</span><span class="chip">numpy</span><span class="chip">scikit-learn</span><span class="chip">networkx</span><span class="chip">SQLite · 17 tablas</span></div>
    <li>Corpus: <b>@@EVENTOS@@</b> eventos · <b>@@CLUSTERS@@</b> clusters · @@FUENTES@@ fuentes</li>
    <li>Despliegue: cron cada 6 h, nginx tras Cloudflare, RAM 3,8 GB</li>
    <li>CI local (pre-push): compileall, contrato, ruff, pip-audit, pytest</li>
    <li>Licencia AGPL-3.0 · SECURITY.md · código de conducta</li>
  </ul></div>
</div>

<div class="foot">
  <span>Fuente: análisis del repositorio github.com/mcasrom/hybrid-fimi-radar (HEAD <b>@@HEAD@@</b>, @@FECHA@@) y config.yaml. Cifras vivas: se regeneran con <code>gen_wallchart.py</code>.</span>
  <span class="wm">Mide comportamiento, no autoría</span>
</div>
</div></body></html>"""


if __name__ == "__main__":
    main()
