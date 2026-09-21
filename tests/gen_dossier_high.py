#!/usr/bin/env python3
"""Genera un dossier HTML revisable de la muestra HIGH: por cada cluster, sus
cuentas reales, dominios, fechas y los textos completos, para etiquetarlo a mano
(coordinado / no_coordinado / dudoso) sin sugerencias del asistente."""
import csv
import datetime
import html
import sqlite3
import urllib.parse
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "data" / "validacion" / "muestra_high_20260921_1351.csv"
DB = ROOT / "data" / "radar.db"
OUT = Path("/tmp/dossier_high.html")


def esc(s):
    return html.escape(str(s or ""), quote=True)


def fmt_ts(ts):
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).strftime("%d %b %Y %H:%M")
    except Exception:
        return str(ts)


def dom(u):
    try:
        d = urllib.parse.urlparse(u or "").netloc.replace("www.", "")
        return d
    except Exception:
        return ""


CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
     background:#f6f7f9;color:#0f172a}
header.top{position:sticky;top:0;z-index:50;background:#0f172a;color:#fff;
     padding:10px 18px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
header.top b{font-size:15px}
header.top .bar{flex:1;min-width:140px;height:8px;background:#334155;border-radius:4px;overflow:hidden}
header.top .bar i{display:block;height:100%;background:#22c55e;width:0}
header.top button{background:#22c55e;color:#052e16;border:0;border-radius:6px;
     padding:8px 14px;font-weight:700;cursor:pointer}
.wrap{max-width:1080px;margin:0 auto;padding:18px}
.intro{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;margin-bottom:18px}
.intro h1{margin:0 0 8px;font-size:19px}
.intro p{margin:6px 0;color:#334155}
.intro .k{background:#fef3c7;border-left:4px solid #f59e0b;padding:8px 12px;border-radius:6px;margin-top:10px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;margin-bottom:16px}
.card h2{margin:0 0 4px;font-size:16px}
.card h2 .score{color:#c2410c}
.meta{color:#64748b;font-size:13px;margin-bottom:8px}
.meta span{margin-right:12px;white-space:nowrap}
.chips{margin:8px 0}
.chip{display:inline-block;background:#f1f5f9;border:1px solid #e2e8f0;border-radius:14px;
     padding:2px 10px;margin:2px 4px 2px 0;font-size:12.5px}
.chip.m{background:#fff7ed;border-color:#fdba74;color:#9a3412}
.chip.c{background:#eef2ff;border-color:#c7d2fe;color:#3730a3}
.lbl{font-weight:700;font-size:13px;color:#475569;margin:10px 0 2px}
.ev{border-top:1px solid #eef2f6;padding:7px 0}
.ev .h{font-size:12.5px;color:#64748b}
.ev .h b{color:#0f172a}
.ev .t{font-weight:600;margin:2px 0}
.ev .x{color:#334155;font-size:14px;white-space:pre-wrap}
.ev .u a{font-size:12.5px;color:#0369a1;word-break:break-all}
details{margin-top:10px}
details summary{cursor:pointer;color:#0369a1;font-weight:600;font-size:14px}
.verdict{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
.verdict button{border:2px solid #e2e8f0;background:#fff;border-radius:8px;padding:8px 14px;
     font-weight:700;cursor:pointer;font-size:14px}
.verdict button.on[data-v=coordinado]{background:#fee2e2;border-color:#ef4444;color:#991b1b}
.verdict button.on[data-v=no_coordinado]{background:#dcfce7;border-color:#22c55e;color:#166534}
.verdict button.on[data-v=dudoso]{background:#fef3c7;border-color:#f59e0b;color:#92400e}
.nota{width:100%;margin-top:8px;border:1px solid #e2e8f0;border-radius:6px;padding:7px 9px;font:14px inherit}
footer{color:#94a3b8;text-align:center;padding:24px;font-size:13px}
"""

JS = """
var V = JSON.parse(localStorage.getItem('dossier_high_v1') || '{}');
function paint(){
  var n=0;
  document.querySelectorAll('.card').forEach(function(c){
    var k=c.dataset.k, v=V[k];
    if(v) n++;
    c.querySelectorAll('.verdict button').forEach(function(b){
      b.classList.toggle('on', b.dataset.v===v);
    });
  });
  document.getElementById('prog').textContent = n + ' / ' + document.querySelectorAll('.card').length;
  document.getElementById('bar').style.width = (100*n/document.querySelectorAll('.card').length) + '%';
}
function setv(k,v){
  if(V[k]===v) delete V[k]; else V[k]=v;
  localStorage.setItem('dossier_high_v1', JSON.stringify(V));
  paint();
}
function nota(k,t){ V['_n_'+k]=t; localStorage.setItem('dossier_high_v1', JSON.stringify(V)); }
function dl(){
  var rows=[['cluster_label','label','nota']];
  document.querySelectorAll('.card').forEach(function(c){
    var k=c.dataset.k;
    if(V[k]) rows.push([k, V[k], V['_n_'+k]||'']);
  });
  var csv=rows.map(function(r){return r.map(function(x){return '"'+String(x).replace(/"/g,'""')+'"';}).join(',');}).join('\\n');
  var a=document.createElement('a');
  a.href='data:text/csv;charset=utf-8,'+encodeURIComponent(csv);
  a.download='muestra_high_etiquetada.csv'; a.click();
}
document.addEventListener('click',function(e){
  var b=e.target.closest('.verdict button');
  if(b){ setv(b.closest('.card').dataset.k, b.dataset.v); }
});
document.addEventListener('input',function(e){
  if(e.target.classList.contains('nota')) nota(e.target.closest('.card').dataset.k, e.target.value);
});
paint();
"""


def main():
    rows = list(csv.DictReader(open(CSV, encoding="utf-8")))
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cards = []
    for r in rows:
        label = r["cluster_label"]
        evs = con.execute(
            "SELECT ce.ts, ce.source, ce.author, ce.title, ce.text, ce.url "
            "FROM cluster_events ce JOIN clusters cl ON cl.id=ce.cluster_id "
            "WHERE cl.cluster_label=? ORDER BY ce.ts", (label,)).fetchall()
        accs, doms = {}, {}
        for e in evs:
            a = (e["author"] or "").split(":", 1)[-1]
            if a:
                accs[a] = accs.get(a, 0) + 1
            d = dom(e["url"])
            if d:
                doms[d] = doms.get(d, 0) + 1
        accs_s = "".join(
            '<span class="chip c">%s · %d</span>' % (esc(a), n)
            for a, n in sorted(accs.items(), key=lambda x: -x[1]))
        doms_s = "".join(
            '<span class="chip m">%s · %d</span>' % (esc(d), n)
            for d, n in sorted(doms.items(), key=lambda x: -x[1])[:12])
        ev_html = []
        for e in evs:
            a = (e["author"] or "").split(":", 1)[-1]
            u = e["url"] or ""
            link = ('<div class="u"><a href="%s" target="_blank" rel="noopener">%s</a></div>'
                    % (esc(u), esc(u[:80]))) if u else ""
            ev_html.append(
                '<div class="ev"><div class="h">%s · <b>%s</b> · %s</div>'
                '<div class="t">%s</div><div class="x">%s</div>%s</div>'
                % (esc(fmt_ts(e["ts"])), esc(a), esc(e["source"] or ""),
                   esc((e["title"] or "")[:180]), esc((e["text"] or "")[:600]), link))
        ev_block = "".join(ev_html)
        cards.append(
            '<div class="card" data-k="%s">'
            '<h2>%s <span class="score">%s/100 %s</span></h2>'
            '<div class="meta"><span>tema: <b>%s</b></span><span>%s eventos</span>'
            '<span>%s cuentas</span><span>%s URLs</span><span>ventana: %s h</span>'
            '<span>coord %s · anom %s · infra %s</span></div>'
            '<div class="lbl">CUENTAS (%d)</div><div class="chips">%s</div>'
            '<div class="lbl">DOMINIOS ENLAZADOS (%d)</div><div class="chips">%s</div>'
            '<details><summary>Ver los %d eventos (texto completo)</summary>%s</details>'
            '<div class="verdict">'
            '<button data-v="coordinado">✅ coordinado</button>'
            '<button data-v="no_coordinado">❌ no coordinado</button>'
            '<button data-v="dudoso">❓ dudoso</button></div>'
            '<input class="nota" placeholder="nota (opcional)"></div>'
            % (esc(label), esc(label), esc(r.get("score")), esc(r.get("banda")),
               esc(r.get("tema")), esc(r.get("n_eventos")), esc(r.get("n_cuentas")),
               esc(r.get("n_urls")), esc(r.get("span_h")), esc(r.get("coord")),
               esc(r.get("anom")), esc(r.get("infra")),
               len(accs), accs_s, len(doms), doms_s, len(evs), ev_block))
    out = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>Dossier muestra HIGH — etiquetado</title><style>%s</style></head><body>'
        '<header class="top"><b>Dossier HIGH — etiquetado ciego</b>'
        '<span id="prog">0 / %d</span><span class="bar"><i id="bar"></i></span>'
        '<button onclick="dl()">⬇ Descargar CSV etiquetado</button></header>'
        '<div class="wrap"><div class="intro">'
        '<h1>Cómo etiquetar</h1>'
        '<p>Por cada grupo, lee las <b>cuentas</b>, los <b>dominios</b> y los <b>textos</b> '
        '(pulsa "Ver los N eventos") y decide:</p>'
        '<p><b>✅ coordinado</b> = las cuentas actúan juntas a propósito (campaña): muchas '
        'cuentas, muchas anónimas, mismo mensaje repetido, durante días, enlazando a sitios '
        'pequeños.<br>'
        '<b>❌ no coordinado</b> = casualidad: medios normales reportando la misma noticia, '
        'o gente compartiendo un titular porque es noticia.<br>'
        '<b>❓ dudoso</b> = no se puede saber.</p>'
        '<div class="k">Tu veredicto se guarda en el navegador. Al terminar, pulsa '
        '<b>"Descargar CSV etiquetado"</b> y me lo pasas. Con eso se calcula la precisión '
        'real de la banda HIGH. <b>Sin sugerencias mías</b>: es tu lectura.</div>'
        '</div>%s<footer>Radar FIMI · muestra HIGH 2026-09-21 · %d clusters</footer>'
        '</div><script>%s</script></body></html>'
        % (CSS, len(cards), "".join(cards), len(cards), JS))
    OUT.write_text(out, encoding="utf-8")
    print("OK: %s (%d clusters, %d KB)" % (OUT, len(cards), OUT.stat().st_size // 1024))


if __name__ == "__main__":
    main()
