#!/usr/bin/env python3
"""caso_goldset.py — Gold set (validacion humana) del caso Frontera Sur.

Modos:
  --muestra N [--seed S] [--out DIR]   genera la muestra + el HTML de anotacion
  --evaluar anotado.json               precision/recall/kappa por categoria

La muestra es reproducible (seed fija). La anotacion se hace en el HTML
(se guarda en localStorage del navegador) y se exporta a un JSON que se
pasa a --evaluar. No toca score/bandas ni la BD (solo lectura).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "radar.db")
TEMA = "frontera_sur"
TS_CASE = int(datetime(2026, 7, 30, tzinfo=timezone.utc).timestamp())
MESES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
         7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}

# Categorias anotables (las del generador + contexto/nada)
CATS = [
    ("drones", "Drones"),
    ("buques", "Buques de guerra / aguas"),
    ("hostigamiento", "Hostigamiento / presion migratoria"),
    ("bloqueo", "Bloqueo aereo / maritimo"),
    ("valla", "Salto a la valla / incidente"),
    ("postura", "Postura oficial de Marruecos"),
    ("critica", "Critica internacional a Marruecos"),
    ("soberania", "Soberania / aguas / reivindicacion"),
    ("contexto_otro", "Contexto relevante (otra cosa)"),
    ("nada", "No relevante al caso"),
]
CATKEYS = [k for k, _ in CATS]
TONE = ["hostil", "cooperación", "neutro"]

# Prediccion automatica (replica simplificada de las CATS del generador)
KW = {
    "drones": ["drone", "dron"],
    "buques": ["fragata", "buque de guerra", "barco de guerra", "patrullera", "buque militar"],
    "hostigamiento": ["hostigamiento", "presion migratoria", "presión migratoria", "desestabiliz", "asedio"],
    "bloqueo": ["bloqueo aereo", "bloqueo maritimo", "bloqueo naval", "cierre del espacio aereo"],
    "valla": ["valla", "salto a la valla", "incursion", "incursión", "asalto"],
    "postura": ["gobierno marroqui", "gobierno marroquí", "mohamed vi", "rey de marruecos",
                "marruecos rechaza", "marruecos niega", "marruecos advierte"],
    "critica": ["acusa a marruecos", "acusa a rabat", "irredentismo", "ataque marroqui", "ofensiva marroquí"],
    "soberania": ["soberan", "aguas territoriales", "aguas internacionales", "tratado de ceuta"],
}
ANCLAS = ["ceuta", "melilla", "marruecos", "marroqu", "estrecho", "rabat", "gibraltar",
          "albor", "frontera", "valla", "canarias", "magreb", "sahara", "tarajal", "penon", "peñon"]
POL_COOP = ["ejercicio conjunto", "maniobras conjuntas", "cooperaci", "navantia", "entrega de",
            "normalidad", "reabre", "colaboraci", "acuerdo bilateral", "visita oficial", "patrullera"]
POL_HOST = ["violaci", "incursi", "amenaz", "hostigamiento", "bloqueo", "injerencia", "espionaje",
            "sabotaje", "ataque", "provocaci", "invas", "coerci", "presión migratoria", "presion migratoria",
            "dron marroqu", "fragata marroqu", "basta ya"]


def _fecha(ts):
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return f"{d.day}-{MESES[d.month]}-{d.year}"


def _auto(text, title):
    """Categoria automatica + tono (aprox. del generador)."""
    t = ((text or "") + " " + (title or "")).lower()
    cat = "nada"
    for k, words in KW.items():
        if any(w in t for w in words):
            cat = k
            break
    if cat != "nada" and not any(a in t for a in ANCLAS):
        cat = "nada"  # sin ancla geografica
    if any(w in t for w in POL_COOP):
        tone = "cooperación"
    elif any(w in t for w in POL_HOST):
        tone = "hostil"
    else:
        tone = "neutro"
    return cat, tone


def _muestra(n, seed, out_dir):
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT e.id, e.timestamp, e.source, e.title, e.text "
        "FROM events e JOIN event_temas et ON et.event_id=e.id "
        "WHERE et.tema_id=? AND e.timestamp>=?", (TEMA, TS_CASE)).fetchall()
    con.close()
    if not rows:
        print("[goldset] sin eventos del caso", file=sys.stderr)
        return 1

    # estratifica: la mitad de los que la heuristica etiqueta (positivos) y la
    # mitad del resto (para poder medir falsos negativos).
    pos, neg = [], []
    for r in rows:
        cat, tone = _auto(r[4], r[3])
        (pos if cat != "nada" else neg).append((r, cat, tone))
    rnd = random.Random(seed)
    rnd.shuffle(pos)
    rnd.shuffle(neg)
    half = n // 2
    sel = pos[:half] + neg[:n - half]
    rnd.shuffle(sel)

    items = []
    for (eid, ts, src, tit, txt), cat, tone in sel:
        items.append({
            "id": eid, "fecha": _fecha(ts), "fuente": (src or "")[:40],
            "titular": (tit or "").replace("\n", " ")[:300],
            "texto": (txt or "").replace("\n", " ")[:600],
            "auto_cat": cat, "auto_tone": tone,
        })
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "goldset_muestra.json")
    html_path = os.path.join(out_dir, "goldset.html")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"cat": CATS, "tone": TONE, "items": items}, f, ensure_ascii=False, indent=1)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_html(items))
    csv_path = os.path.join(out_dir, "goldset.csv")
    _write_csv(items, csv_path)
    print(f"[goldset] muestra: {len(items)} eventos ({half} auto-positivos / {n-half} resto)")
    print(f"[goldset] CSV  -> {csv_path}  (rellena 'categoria' y 'tono')")
    print(f"[goldset] HTML -> {html_path}")
    print(f"[goldset] JSON -> {json_path}")
    return 0


def _write_csv(items, path):
    """CSV para anotar a mano (separador ';', UTF-8 con BOM -> abre en columnas)."""
    import csv
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
        w.writerow(["id", "fecha", "fuente", "categoria", "tono", "titular", "texto"])
        for it in items:
            w.writerow([it["id"], it["fecha"], it["fuente"], "", "",
                        it["titular"], it["texto"]])


def _html(items):
    data = json.dumps({"cat": CATS, "tone": TONE, "items": items}, ensure_ascii=False)
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Gold set · Frontera Sur</title>
<style>
:root{--navy:#0d1b2a;--acc:#c1440e;--line:#dde3ea;--mut:#5b6b7c}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,Segoe UI,Roboto,sans-serif;color:var(--navy);background:#f6f8fa}
.wrap{max-width:820px;margin:0 auto;padding:18px}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--line);padding:10px 0;z-index:5}
.bar{height:8px;background:#e5eaf0;border-radius:6px;overflow:hidden}.bar>i{display:block;height:100%;background:var(--acc);width:0}
.card{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px;margin:14px 0}
.q{font-weight:700;margin:2px 0 8px}.sub{color:var(--mut);font-size:.88rem}
.txt{white-space:pre-wrap;background:#f9fafc;border:1px solid var(--line);border-radius:8px;padding:10px;margin:8px 0}
.btns{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0}
button{border:1px solid var(--line);background:#fff;border-radius:20px;padding:6px 12px;cursor:pointer;font-size:.86rem}
button.on{background:var(--navy);color:#fff;border-color:var(--navy)}
button.t.on{background:var(--acc);border-color:var(--acc)}
.nav{display:flex;gap:8px;justify-content:space-between;margin-top:8px}
.primary{background:var(--navy);color:#fff;border:none;padding:9px 16px;border-radius:8px;font-weight:600}
.hide{display:none}
</style></head><body>
<header><div class="wrap"><b>Gold set · Caso Frontera Sur</b>
<div class="bar" style="margin-top:8px"><i id="prog"></i></div>
<div class="sub" id="cnt">0 / 0 anotados · <a href="#" onclick="exportar();return false">exportar JSON</a></div></div></header>
<div class="wrap"><div id="app"></div></div>
<script>
var DATA = __DATA__;
var L = JSON.parse(localStorage.getItem("goldset_fs") || "{}");
var i = 0;
function guardar(){ localStorage.setItem("goldset_fs", JSON.stringify(L)); }
function pinta(){
  var it = DATA.items[i];
  if(!it){ document.getElementById("app").innerHTML = "<div class='card'><h2>Hecho</h2><p>Todos anotados. Pulsa <b>exportar JSON</b>.</p></div>"; return; }
  var done = L[it.id] || {cat:"", tone:""};
  var h = "<div class='card'><div class='sub'>"+it.fecha+" · "+it.fuente+" · id "+it.id+"</div>";
  h += "<div class='q'>1. ¿A qué categoría pertenece?</div><div class='btns'>";
  DATA.cat.forEach(function(c){ h += "<button class='"+(done.cat===c[0]?"on":"")+"' onclick='setcat(\""+c[0]+"\")'>"+c[1]+"</button>"; });
  h += "</div><div class='q'>2. ¿Tono del mensaje?</div><div class='btns'>";
  DATA.tone.forEach(function(t){ h += "<button class='t "+(done.tone===t?"on":"")+"' onclick='settone(\""+t+"\")'>"+t+"</button>"; });
  h += "</div><div class='txt'>"+(it.titular||"(sin titular)")+"\\n\\n"+(it.texto||"")+"</div>";
  h += "<div class='sub'>predicción automática: categoría <b>"+it.auto_cat+"</b> · tono <b>"+it.auto_tone+"</b> (no mires esto hasta decidir)</div>";
  h += "<div class='nav'><button onclick='mueve(-1)'>← anterior</button><button class='primary' onclick='mueve(1)'>siguiente →</button></div></div>";
  document.getElementById("app").innerHTML = h;
  actualiza();
}
function setcat(v){ var it=DATA.items[i]; L[it.id]=L[it.id]||{cat:"",tone:""}; L[it.id].cat=v; guardar(); pinta(); }
function settone(v){ var it=DATA.items[i]; L[it.id]=L[it.id]||{cat:"",tone:""}; L[it.id].tone=v; guardar(); pinta(); }
function mueve(d){ i=Math.max(0,Math.min(DATA.items.length-1,i+d)); pinta(); }
function actualiza(){ var n=0; DATA.items.forEach(function(it){ if(L[it.id]&&L[it.id].cat) n++; });
  document.getElementById("cnt").innerHTML = n+" / "+DATA.items.length+" anotados · <a href='#' onclick='exportar();return false'>exportar JSON</a>";
  document.getElementById("prog").style.width = (100*n/DATA.items.length)+"%"; }
function exportar(){
  var out={}; DATA.items.forEach(function(it){ var v=L[it.id]; if(v) out[it.id]={cat:v.cat,tone:v.tone}; });
  var blob=new Blob([JSON.stringify({gold:out},null,1)],{type:"application/json"});
  var a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download="goldset_anotado.json"; a.click();
}
pinta();
</script></body></html>""".replace("__DATA__", data)


def _kappa(a, b):
    """Cohen's kappa entre dos listas de etiquetas."""
    n = len(a)
    if n == 0:
        return 0.0
    pa = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    return (pa - pe) / (1 - pe) if pe != 1 else 0.0


def _leer_csv(path):
    """Lee el CSV anotado -> {id(str): {cat, tone}}. Acepta ';' o ','."""
    import csv
    gold = {}
    with open(path, encoding="utf-8-sig") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except csv.Error:
            dialect = csv.excel
            dialect.delimiter = ";"
        for row in csv.DictReader(f, dialect=dialect):
            eid = (row.get("id") or "").strip()
            cat = (row.get("categoria") or "").strip().lower()
            tone = (row.get("tono") or "").strip().lower()
            if eid and cat:
                gold[eid] = {"cat": cat, "tone": tone}
    return gold


def _evaluar(path):
    if path.lower().endswith(".csv"):
        gold = _leer_csv(path)
    else:
        d = json.load(open(path, encoding="utf-8"))
        gold = d.get("gold", d)
    # recuperar la muestra (para el auto_) desde el JSON hermano
    base = os.path.dirname(os.path.abspath(path)) or "."
    mpath = os.path.join(base, "goldset_muestra.json")
    if not os.path.exists(mpath):
        print("[goldset] falta goldset_muestra.json junto al anotado", file=sys.stderr)
        return 1
    muestra = {str(it["id"]): it for it in json.load(open(mpath, encoding="utf-8"))["items"]}
    gold = {str(k): v for k, v in gold.items()}
    pairs = [(mid, muestra[mid], gold[mid]) for mid in gold if mid in muestra]
    if not pairs:
        print("[goldset] el anotado no cruza con la muestra", file=sys.stderr)
        return 1

    print(f"\n=== GOLD SET · caso Frontera Sur · n={len(pairs)} ===\n")
    print("Por CATEGORÍA (la automática vs tu anotación):")
    print(f"  {'categoría':<22}{'n_gold':>7}{'prec':>7}{'recall':>8}{'F1':>7}")
    gcat = [g["cat"] for _m, _it, g in pairs]
    for k, lbl in CATS:
        tp = sum(1 for _m, it, g in pairs if it["auto_cat"] == k and g["cat"] == k)
        fp = sum(1 for _m, it, g in pairs if it["auto_cat"] == k and g["cat"] != k)
        fn = sum(1 for _m, it, g in pairs if it["auto_cat"] != k and g["cat"] == k)
        prec = tp / (tp + fp) if (tp + fp) else 0
        rec = tp / (tp + fn) if (tp + fn) else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
        print(f"  {lbl[:21]:<22}{gcat.count(k):>7}{prec:>7.2f}{rec:>8.2f}{f1:>7.2f}")
    ka = _kappa([it["auto_cat"] for _m, it, _g in pairs], gcat)
    print(f"\n  kappa (categoría): {ka:.3f}")

    gtone = [g["tone"] for _m, _it, g in pairs]
    kt = _kappa([it["auto_tone"] for _m, it, _g in pairs], gtone)
    acc = sum(1 for _m, it, g in pairs if it["auto_tone"] == g["tone"]) / len(pairs)
    print(f"  tono: accuracy {acc:.2f} · kappa {kt:.3f}")

    rel = [1 if g["cat"] != "nada" else 0 for _m, _it, g in pairs]
    autorel = [0 if it["auto_cat"] == "nada" else 1 for _m, it, _g in pairs]
    tp = sum(1 for a, g in zip(autorel, rel) if a and g)
    fp = sum(1 for a, g in zip(autorel, rel) if a and not g)
    fn = sum(1 for a, g in zip(autorel, rel) if not a and g)
    prec = tp / (tp + fp) if (tp + fp) else 0
    rec = tp / (tp + fn) if (tp + fn) else 0
    print(f"\n  RELEVANCIA (¿es del caso?): precision {prec:.2f} · recall {rec:.2f} "
          f"(gold: {sum(rel)}/{len(rel)} relevantes)")
    print("\nInterpretación: precision = de lo que el sistema dice que es X, cuánto es X;")
    print("recall = de lo que ES X, cuánto detecta. kappa <0,2 pobre · 0,2-0,4 aceptable · >0,6 bueno.\n")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--muestra", type=int, default=0)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="/tmp/goldset")
    ap.add_argument("--evaluar")
    args = ap.parse_args()
    if args.evaluar:
        return _evaluar(args.evaluar)
    if args.muestra:
        return _muestra(args.muestra, args.seed, args.out)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
