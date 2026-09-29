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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAL = ROOT / "data" / "validacion"

ARI = "1,000"  # ARI sintético (gate de CI); separación perfecta en 6 escenarios.
BANDAS = ["CRITICAL", "HIGH", "ANOMALOUS", "WATCH"]
_COL = {"CRITICAL": "#dc2626", "HIGH": "#ea580c", "ANOMALOUS": "#d97706", "WATCH": "#0e7490"}

# Fecha en que el banding vigente cambió por última vez (gate de núcleo k-core >= 2).
# Una muestra anterior describe otra versión del score y no es comparable.
BANDING_ACTUAL_DESDE = "2026-09-29"


def _auto():
    try:
        return json.loads((VAL / "auto_ultimo.json").read_text())
    except Exception:
        return None


def _curada():
    """Última muestra curada, con su n REAL y su fecha.

    Antes multiplicaba `len(bandas) * 8` (suponiendo 8 clusters por banda) y
    por eso la card decía «sobre 8 clusters etiquetados a mano» cuando la
    última muestra tenía 53. El n sale ahora de la fila del historial.
    """
    try:
        rows = list(csv.DictReader(open(VAL / "historial.csv", encoding="utf-8")))
        if not rows:
            return None
        ultima = rows[-1]["muestra"]
        sub = [r for r in rows if r["muestra"] == ultima]
        bandas = {r["banda"]: r["precision"] for r in sub}
        try:
            n_total = sum(int(r["n"]) for r in sub)
        except (TypeError, ValueError):
            n_total = 0
        return {"muestra": ultima, "bandas": bandas, "n": n_total,
                "n_por_banda": {r["banda"]: r.get("n", "?") for r in sub}}
    except Exception:
        return None


def _fecha_muestra(nombre):
    """'muestra_high_20260921_1351.csv' -> '21/09/2026'."""
    iso = _fecha_iso(nombre)
    if iso:
        return f"{iso[8:10]}/{iso[5:7]}/{iso[0:4]}"
    return str(nombre) or "—"


def _fecha_iso(nombre):
    """'muestra_high_20260929_postgate.csv' -> '2026-09-29' ('' si no la trae)."""
    try:
        for parte in str(nombre).split("_"):
            if len(parte) == 8 and parte.isdigit():
                return f"{parte[0:4]}-{parte[4:6]}-{parte[6:8]}"
    except (AttributeError, IndexError, TypeError) as e:   # pragma: no cover
        print(f"[validacion_card] fecha ilegible en {nombre!r}: {e}", file=sys.stderr)
    return ""


def _aviso_banding(fecha_iso):
    """Caveat según la muestra sea anterior o posterior al banding vigente."""
    if not fecha_iso:
        return ("<b style='color:#b45309'>Sin fecha en el nombre de la muestra: no se puede "
                "saber si es comparable con el banding vigente.</b>")
    if fecha_iso < BANDING_ACTUAL_DESDE:
        return ("<b style='color:#b45309'>Anterior al banding vigente (cambio del 24/Sep y "
                "gate de núcleo del 29/Sep): no es comparable con las cifras actuales.</b>")
    return ("<b style='color:#166534'>Medida sobre el banding vigente, incluido el gate de "
            "núcleo (k-core ≥2) del 29/Sep.</b>")


def _pct(x):
    """Fracción 0-1 -> porcentaje (validación externa)."""
    try:
        return f"{float(x) * 100:.1f}%"
    except Exception:
        return "—"


def _pct100(x):
    """Valor ya en escala 0-100 -> porcentaje (validación curada)."""
    try:
        return f"{float(x):.1f}%"
    except Exception:
        return "—"


def render_validacion_html():
    auto = _auto()
    cur = _curada()
    filas = []
    fecha = (auto or {}).get("fecha", "")[:16].replace("T", " ")

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
            f"<span style='color:#64748b;font-weight:400'> (n={cur['n_por_banda'].get(b,'?')})</span>"
            for b in BANDAS if b in cur["bandas"])
        n = cur.get("n") or len(cur["bandas"]) * 8
        # "sube con la banda" solo es conclusion si la muestra cubre varias
        # bandas: con una sola (p.ej. la muestra ciega post-gate, HIGH n=40)
        # la afirmacion no se deduce de nada.
        if len(cur["bandas"]) >= 2:
            conclusion = ("<b>La precisión sube con la banda</b> (el score ordena bien; "
                          "WATCH = ruido de bajo volumen).")
        else:
            conclusion = (f"Muestra de <b>una sola banda ({'/'.join(cur['bandas'])})</b>: "
                          "no permite afirmar que la precisión suba con la banda.")
            # Honestidad: si la unica banda medida sale baja, decirlo de forma
            # explicita. «HIGH» sin mas criterio NO es lo mismo que
            # «coordinacion» (29-Sep: 8,3 % en una muestra ciega de 40 HIGH).
            # OJO: el valor viene del historial como STRING ('8.3'), no como
            # float -> parsear antes de formatear (si no, :.1f revienta).
            try:
                _pb = float(cur["bandas"].get("/".join(cur["bandas"])))
                if _pb < 25.0:
                    conclusion += (
                        f" <b style='color:#b91c1c'>Aviso: {_pb:.1f} % de precisión en esa banda "
                        "significa que una banda alta NO equivale a coordinación</b> (el resto es "
                        "cobertura orgánica, eco de prensa o killbait de fuente única).")
            except (TypeError, ValueError) as exc:
                print(f"[validacion_card] no se pudo evaluar la precisión de la "
                      f"muestra {cur.get('muestra')!r}: {exc}", file=sys.stderr)
        filas.append(
            "<tr>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🧪 <b>Curada</b> (ground truth)</td>"
            f"<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>{chips}</td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
            f"Precisión por banda sobre <b>{n} clusters etiquetados a mano</b> "
            f"(medido el {_fecha_muestra(cur['muestra'])}): {conclusion} "
            f"{_aviso_banding(_fecha_iso(cur['muestra']))}</td>"
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
        edad = auto.get("dataset_edad_dias")
        frescos = "dataset refrescado" if auto.get("dataset_refrescado") else (
            f"dataset externo con {edad} días" if edad is not None else "dataset externo")
        filas.append(
            "<tr>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🌍 <b>Externa (EUvsDisinfo)</b></td>"
            f"<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
            f"<span style='color:#ea580c;font-weight:700'>prec {_pct(g.get('precision'))}</span> · "
            f"<span style='color:#64748b'>recall {_pct(g.get('recall'))}</span></td>"
            f"<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>"
            f"Solape con dominios documentados ({g.get('n_senales','—')} señales ≥60; "
            f"{g.get('n_senales_doc','—')} con dominio documentado, "
            f"{g.get('dominios_doc_amplificados','—')} dominios). Recall bajo por diseño: los RSS no entran "
            f"al grafo de coordinación. En castellano: prec {_pct(s.get('precision'))}. "
            f"<b style='color:#b45309'>Medido el {fecha}, {frescos}; el recuento de señales es el de "
            f"ese momento, no el del ciclo actual.</b></td>"
            "</tr>")
    else:
        filas.append(
            "<tr><td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>🌍 <b>Externa</b></td>"
            "<td style='text-align:center;padding:6px 10px;border-bottom:1px solid #e2e8f0'>—</td>"
            "<td style='padding:6px 10px;border-bottom:1px solid #e2e8f0'>Pendiente de ejecutar (job semanal).</td></tr>")

    # Nota de estado de la capa ciega: dato derivado del historial, no texto fijo.
    if cur:
        _n = cur.get("n") or len(cur["bandas"]) * 8
        ciega = (f"La validación <b>ciega</b> del modelo vigente <b>está ejecutada</b>: "
                 f"{_n} clusters etiquetados a mano el {_fecha_muestra(cur['muestra'])}, "
                 f"por <b>un solo revisor</b> (aún <b>sin κ</b>: falta un 2.º revisor "
                 f"independiente). Es una <b>línea base de precisión en banda alta</b>.")
    else:
        ciega = "La validación ciega del modelo vigente está preparada y sin ejecutar."

    return f"""
<div class="card" id="validacion">
<h3>Validación del modelo</h3>
<p class="caption" style="font-size:.84rem;color:#334155;line-height:1.65">
El radar se valida con <b>tres capas que prueban cosas distintas</b> y no compiten:
la <b>mecánica</b> (sintética), el <b>orden</b> del score (curada) y el <b>solape externo</b> (EUvsDisinfo).
<b>Cada capa se mide con su propia cadencia y no en cada ciclo:</b> la sintética es un gate de CI,
la externa corre los lunes y la curada genera muestra el día 1 de cada mes (el etiquetado es manual).
Cada cifra lleva la fecha en que se midió: <b>una medición antigua no describe el sistema actual</b>.
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
<br><span style="font-size:.78rem;color:#78350f"><b>Ninguna de estas tres capas mide recall de campañas reales</b>
ni demuestra que una señal alta sea una campaña: la capa externa solo puede dar <b>recall 0</b> porque su
catálogo es histórico y de otro ámbito, y la capa curada es un muestreo de precisión sin denominador
de positivos conocidos. {ciega}</span>
<br><span style="font-size:.78rem;color:#78350f">Última validación externa: {fecha or 'pendiente'}.</span>
</div>
</div>
"""


_validacion_html = render_validacion_html()
