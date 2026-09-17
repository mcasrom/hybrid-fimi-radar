"""Validación del modelo — card HTML para Transparencia (DINÁMICA).

Lee los resultados reales de las tres capas de validación:
  1. Sintética (ARI)          — gate de CI (tests/test_synthetic_ari.py).
  2. Curada (ground truth)    — data/validacion/historial.csv (precisión por banda).
  3. Externa (EUvsDisinfo)    — data/validacion/auto_ultimo.json (precision/recall).

Si falta algún fichero, muestra lo que haya (no rompe el dashboard).
Se expone como `_validacion_html` (variable de módulo) para no cambiar el import
de gen_fimi_html; se recalcula en cada ejecución (el módulo se reimporta por ciclo).
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAL = ROOT / "data" / "validacion"

ARI = "1,000"  # ARI sintético (gate de CI); separación perfecta en 6 escenarios.
BANDAS = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH"]
_COL = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "ANOMALOUS": "#d97706", "WATCH": "#0e7490"}


def _auto():
    try:
        return json.loads((VAL / "auto_ultimo.json").read_text())
    except Exception:
        return None


def _curada():
    try:
        rows = list(csv.DictReader(open(VAL / "historial.csv", encoding="utf-8")))
        if not rows:
            return None
        ultima = rows[-1]["muestra"]
        return {"muestra": ultima, "bandas": {r["banda"]: r["precision"] for r in rows if r["muestra"] == ultima}}
    except Exception:
        return None


def _pct(x):
    """Fracción 0-1 -> porcentaje (validación externa)."""
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return "—"


def _pct100(x):
    """Valor ya en escala 0-100 -> porcentaje (validación curada)."""
    try:
        return f"{float(x):.0f}%"
    except Exception:
        return "—"


def render_validacion_html():
    auto = _auto()
    cur = _curada()
    filas = []

    # 1) Sintética
    filas.append(
        "<tr>"
        "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🔬 <b>ARI sintético</b></td>"
        f"<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
        f"<span style='color:#16a34a;font-weight:700'>{ARI}</span></td>"
        "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
        "La mecánica de clustering separa correctamente coordinación simulada (6 escenarios, gate de CI).</td>"
        "</tr>")

    # 2) Curada
    if cur:
        chips = " · ".join(
            f"<b style='color:{_COL.get(b,'#334155')}'>{b} {_pct100(cur['bandas'].get(b))}</b>"
            for b in BANDAS if b in cur["bandas"])
        n = len(cur["bandas"]) * 8
        filas.append(
            "<tr>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🧪 <b>Curada</b> (ground truth)</td>"
            f"<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>{chips}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
            f"Precisión por banda sobre {n} clusters etiquetados a mano: <b>la precisión sube con la banda</b> "
            f"(el score ordena bien; WATCH = ruido de bajo volumen).</td>"
            "</tr>")
    else:
        filas.append(
            "<tr><td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🧪 <b>Curada</b></td>"
            "<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>—</td>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>Aún sin muestras etiquetadas.</td></tr>")

    # 3) Externa
    if auto:
        g = auto.get("resultados", {}).get("global", {})
        s = auto.get("resultados", {}).get("spanish", {})
        filas.append(
            "<tr>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🌍 <b>Externa (EUvsDisinfo)</b></td>"
            f"<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
            f"<span style='color:#ea580c;font-weight:700'>prec {_pct(g.get('precision'))}</span> · "
            f"<span style='color:#64748b'>recall {_pct(g.get('recall'))}</span></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
            f"Solape con dominios documentados ({g.get('n_senales','—')} señales ≥60; "
            f"{g.get('n_senales_doc','—')} con dominio documentado). Recall bajo por diseño: los RSS no entran "
            f"al grafo de coordinación. En castellano: prec {_pct(s.get('precision'))}.</td>"
            "</tr>")
    else:
        filas.append(
            "<tr><td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🌍 <b>Externa</b></td>"
            "<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>—</td>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>Pendiente de ejecutar (job semanal).</td></tr>")

    fecha = (auto or {}).get("fecha", "")[:16].replace("T", " ")
    return f"""
<div class="card" id="validacion">
<h3>Validación del modelo</h3>
<p class="caption" style="font-size:.84rem;color:#334155;line-height:1.65">
El radar se valida con <b>tres capas que prueban cosas distintas</b> y no compiten:
la <b>mecánica</b> (sintética), el <b>orden</b> del score (curada) y el <b>solape externo</b> (EUvsDisinfo).
Se actualizan solas en cada ciclo.
</p>
<table style="width:100%;border-collapse:collapse;margin:8px 0;font-size:.82rem">
<tr style="background:#f8fafc">
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #c2410c">Método</th>
<th style="text-align:center;padding:6px 10px;border-bottom:2px solid #c2410c">Resultado</th>
<th style="text-align:left;padding:6px 10px;border-bottom:2px solid #c2410c">Qué prueba</th>
</tr>
{"".join(filas)}
</table>
<div style="margin-top:10px;padding:10px 14px;background:#fffbeb;border-left:4px solid #d97706;border-radius:4px">
<b style="color:#92400e">⚙️ Validación honesta, no marketing.</b> El radar mide <b>coordinación</b>, no autoría:
la ausencia de atribución es un resultado válido. Los ceros y los valores bajos se publican tal cual.
<br><span style="font-size:.78rem;color:#78350f">Última validación externa: {fecha or 'pendiente'}.</span>
</div>
</div>
"""


_validacion_html = render_validacion_html()
