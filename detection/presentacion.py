"""presentacion.py — Sprint A «Precisión visible» (12-oct-2026).

UNA sola definición de "cluster publicado" para dashboard e informe visual:
un cluster con señal tiene un MÍNIMO de cuentas (parejas y solitarios van
agregados en nota, no en titulares). Solo presentación: no toca score,
bandas, BD ni captura. La distribución de scores se muestra (muro 39/59
incluido), no se esconde.
"""

MIN_CUENTAS_PUBLICADO = 3

BANDAS_ORDEN = ("CRITICAL", "HIGH", "ANOMALOUS", "WATCH", "NORMAL")


def es_publicado(n_cuentas, minimo=MIN_CUENTAS_PUBLICADO):
    """¿El cluster tiene señal suficiente para titulares? (puro, testeable)."""
    try:
        return int(n_cuentas or 0) >= int(minimo)
    except (TypeError, ValueError):
        return False


def partir_publicados(clusters, ncuentas_por_id, minimo=MIN_CUENTAS_PUBLICADO):
    """Parte clusters en (publicados, agregados) por nº de cuentas.

    clusters: iterable de mappings con clave "id".
    ncuentas_por_id: {cluster_id: nº de cuentas distintas} (o None).
    Devuelve (publicados, agregados). Puro, testeable, sin BD.
    Fail-open: sin mapa no se filtra nada (nunca ocultar por error técnico).
    """
    clusters = list(clusters or [])
    if not ncuentas_por_id:
        return clusters, []
    pub, par = [], []
    for c in clusters:
        try:
            cid = c["id"]
        except (TypeError, KeyError, IndexError):
            par.append(c)
            continue
        n = ncuentas_por_id.get(cid, 0) or 0
        (pub if es_publicado(n, minimo) else par).append(c)
    return pub, par


def resumen_distribucion(scores):
    """Cuenta por banda + valores topados 39,0/59,0 (muro de escala). Puro."""
    bandas = {b: 0 for b in BANDAS_ORDEN}
    pin39 = pin59 = 0
    scores = list(scores or [])
    for s in scores:
        try:
            v = float(s or 0)
        except (TypeError, ValueError):
            v = 0.0
        if v >= 80:
            bandas["CRITICAL"] += 1
        elif v >= 60:
            bandas["HIGH"] += 1
        elif v >= 40:
            bandas["ANOMALOUS"] += 1
        elif v >= 20:
            bandas["WATCH"] += 1
        else:
            bandas["NORMAL"] += 1
        r = round(v, 1)
        if r == 39.0:
            pin39 += 1
        elif r == 59.0:
            pin59 += 1
    return {"bandas": bandas, "pin39": pin39, "pin59": pin59, "total": len(scores)}


def chequeo_coherencia(n_raw_inf, publicados, agregados,
                       minimo=MIN_CUENTAS_PUBLICADO):
    """El universo declarado cuadra: cargados = publicados + agregados y todo
    lo publicado alcanza el mínimo de cuentas. Falla en voz alta en vez de
    publicar cifras incoherentes (revisión externa 12-oct). Puro, testeable."""
    publicadas = list(publicados or [])
    agregadas = list(agregados or [])
    assert len(publicadas) + len(agregadas) == n_raw_inf, (
        f"universo incoherente: {len(publicadas)}+{len(agregadas)}!={n_raw_inf}")
    bajos = [c for c in publicadas if (c.get("n_au", 0) or 0) < minimo]
    assert not bajos, (
        "publicado bajo mínimo: %s" % [c.get("label") for c in bajos])
    return True


def mil(n):
    """Miles con punto (formato español): 241885 -> '241.885'."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def bloque_distribucion_html(dist, n_par=0, colores=None, compacto=False):
    """Bloque «Distribución de scores» con la nota honesta del muro 39/59."""
    colores = colores or {}
    b = dist["bandas"]
    total = dist["total"] or 1
    filas = []
    for banda in BANDAS_ORDEN:
        n = b.get(banda, 0)
        if compacto and not n:
            continue
        col = colores.get(banda, "#94a3b8")
        pct = 100.0 * n / total
        filas.append(
            f"<div style='display:flex;align-items:center;gap:8px;margin:2px 0'>"
            f"<span style='width:86px;font-size:.7rem;color:#475569'>{banda}</span>"
            f"<div style='flex:1;background:#f1f5f9;border-radius:4px;height:9px;min-width:30px;overflow:hidden'>"
            f"<div style='width:{pct:.1f}%;height:100%;background:{col}'></div></div>"
            f"<span style='width:30px;text-align:right;font-size:.7rem;font-weight:700;color:#334155'>{n}</span>"
            f"</div>"
        )
    muro = ""
    if dist["pin39"] or dist["pin59"]:
        muro = (
            f"<div style='font-size:.7rem;color:#64748b;margin-top:4px'>Muro de escala "
            f"(<b>{dist['pin39'] + dist['pin59']}</b> clusters topados de {dist['total']} con señal): "
            f"<b>{dist['pin39']}</b> en 39,0 y <b>{dist['pin59']}</b> en 59,0 — reglas "
            f"deliberadas (<i>scale_floor</i>/<i>scale_cap</i>) que limitan la puntuación "
            f"para no sobre-valorar grupos minúsculos. Ver «Cómo se puntúa».</div>"
        )
    pares = (
        f"<div style='font-size:.7rem;color:#64748b'>+{n_par} grupos pequeños "
        f"agregados (menos de {MIN_CUENTAS_PUBLICADO} cuentas), contados aparte.</div>"
        if n_par
        else ""
    )
    return (
        f"<div style='margin-top:10px;padding:10px 12px;background:#f8fafc;"
        f"border:1px solid #e2e8f0;border-radius:10px'>"
        f"<div style='font-size:.72rem;color:#475569;font-weight:700;margin-bottom:4px'>"
        f"Distribución de scores (clusters con señal)</div>"
        f"{''.join(filas)}{muro}{pares}</div>"
    )
