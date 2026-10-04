#!/usr/bin/env python3
"""Scoring configurable 0-100 con componentes y bandas.

Bandas (configurables en config.yaml):
  0-19 NORMAL · 20-39 WATCH · 40-59 ANOMALOUS · 60-79 HIGH · 80-100 CRITICAL

Cada score muestra sus componentes (coordination, synchronization, content
similarity, amplification, infrastructure, network density).
"""


def load_bands(config):
    """Carga las bandas de severidad desde config.yaml."""
    bands = (config or {}).get("scoring", {}).get("bands", {})
    return {
        "NORMAL": (0, 19),
        "WATCH": (20, 39),
        "ANOMALOUS": (40, 59),
        "HIGH": (60, 79),
        "CRITICAL": (80, 100),
    }


def band_for(score, bands):
    """Devuelve la etiqueta de banda para un score 0-100.

    Los cortes de banda son enteros (0-19, 20-39, ...) pero los scores son
    decimales, así que un score como 39.14 o 59.96 no cae en ninguna banda.
    Con la comparación anterior esos valores caían en el `return "NORMAL"`
    final y quedaban degradados en silencio (un 59.96 marcado NORMAL).

    Aquí se toma la última banda cuyo `lo` es <= score, de modo que los
    tramos decimales se asignan a la banda que los contiene y no existen
    huecos. Un score por encima del último `hi` se recorta en la última banda.
    """
    if not bands:
        return "NORMAL"
    elegido = None
    for label, (lo, _hi) in sorted(bands.items(), key=lambda kv: kv[1][0]):
        if lo <= score:
            elegido = label
        else:
            break
    return elegido or "NORMAL"


def _tema_weights(config, tema):
    """Pesos específicos del tema (config->temas-><tema>->scoring->weights).

    Permite calibrar por tema: p.ej. politica_nacional (piloto) da mucho más
    peso a la anomalía para no marcar como ANOMALOUS la coordinación humana
    partidista legítima (sync+contenido altos pero anomalía ~0).
    """
    if not tema:
        return {}
    return (config or {}).get("temas", {}).get(tema, {}).get("scoring", {}).get("weights", {}) or {}


def compute_scores(components, config, tema=None, weights_override=None):
    """Combina componentes en overall_score ponderado.

    components: dict con synchronization, content_similarity, amplification,
    infrastructure, network_density (0-100) y anomaly (0-100).
    weights: configurables en config.yaml->scoring->weights, con override por
    tema en config.yaml->temas-><tema>->scoring->weights (merge sobre global).
    weights_override: dict opcional que se aplica DESPUÉS del override por tema
    (p. ej. pesos por fase electoral EEAS en run_fimi). Si es None, no aplica.

    NOTA (cambio D, 24/Sep): este `default_w` define ADEMÁS las claves que suma
    `overall`. `network_density` se calcula y persiste (lo usa H3 de attribution)
    pero NO está aquí -> no pondera. Si tuviera que ponderar, habría que añadir su
    peso al config (y el config lo sobreescribiría); el diseño evita el doble
    conteo del mismo `coordination_score` que alimenta `synchronization`.
    """
    w = (config or {}).get("scoring", {}).get("weights", {})
    default_w = {
        "synchronization": 0.1667, "content_similarity": 0.1667,
        "amplification": 0.0556, "infrastructure": 0.1111,
        "anomaly": 0.50,
    }
    for k, v in default_w.items():
        w.setdefault(k, v)
    w.update(_tema_weights(config, tema))
    if weights_override:
        w.update(weights_override)

    overall = sum(components.get(k, 0) * w.get(k, 0) for k in default_w)
    overall = round(min(100.0, max(0.0, overall)), 1)
    return overall, w


def _scale_min_accounts(config, tema=None):
    """Mínimo de cuentas exigido por banda (config->scoring->scale_min_accounts).

    Merge sobre los globales con el override por tema
    (config->temas-><tema>->scoring->scale_min_accounts), igual que los pesos.
    """
    sma = (config or {}).get("scoring", {}).get("scale_min_accounts", {}) or {}
    if tema:
        t = (config or {}).get("temas", {}).get(tema, {}).get("scoring", {})
        sma = {**sma, **((t or {}).get("scale_min_accounts", {}) or {})}
    return sma


def scale_cap(overall, n_accounts, config, tema=None):
    """Límite de banda según la masa del cluster (nº de cuentas).

    La señal de coordinación a gran escala debe alarmar más que 2-3 cuentas
    sincronizadas (p.ej. una pareja de activistas no debe leerse como red
    orquestada). Si el cluster no llega al mínimo de cuentas de su banda, el
    overall se recorta al tope de la banda inmediatamente inferior permitida.

    Config: scoring.scale_min_accounts = {HIGH: n, CRITICAL: n} (nº mínimo de
    cuentas para poder estar en esa banda). Sin config no aplica límite.
    """
    sma = _scale_min_accounts(config, tema)
    if not sma:
        sma = {"CRITICAL": 10}  # defensivo: por defecto CRITICAL exige masa
    bands = load_bands(config)
    order = ["NORMAL", "WATCH", "ANOMALOUS", "HIGH", "CRITICAL"]
    cur = band_for(overall, bands)
    # banda máxima alcanzable con las cuentas actuales
    allowed = "NORMAL"
    for b in order:
        need = sma.get(b)
        if need is None or n_accounts >= need:
            allowed = b
        else:
            break
    if order.index(cur) > order.index(allowed):
        return float(bands[allowed][1])  # tope de la banda permitida
    return overall


def _tema_scale(config, tema, section, default):
    """Parámetros de escala: globales config->scoring-><section>, con override
    por tema (config->temas-><tema>->scoring-><section>). Igual que los pesos."""
    merged = dict(default)
    if config:
        merged.update((config.get("scoring", {}) or {}).get(section, {}) or {})
    if tema and config:
        t = (config.get("temas", {}) or {}).get(tema, {}).get("scoring", {})
        merged.update((t or {}).get(section, {}) or {})
    return merged


def scale_bonus(overall, accounts, config=None, tema=None):
    """Bonus por escala (Tarea 1 del análisis 05/Sep): a igualdad de
    componentes, más cuentas puntúan más. Corrige el orden invertido en la
    vista activa (un cluster de 2 cuentas puntuaba igual o más que uno de 49).
    bonus = min(cap, cuentas * per_account); acotado para no desbordar el
    score natural. Config: scoring.scale_bonus = {cap, per_account}."""
    p = _tema_scale(config, tema, "scale_bonus", {"cap": 3.5, "per_account": 0.08})
    bonus = min(float(p.get("cap", 3.5)), accounts * float(p.get("per_account", 0.08)))
    return min(100.0, float(overall) + bonus)


def scale_floor(overall, accounts, events, infra, config=None, tema=None):
    """Piso híbrido de masa (05/Sep): un cluster con pocas cuentas solo puede
    llegar a WATCH salvo evidencia adicional.

    Regla: cuentas < min_accounts (3) => banda máx WATCH y se etiqueta
    "posible ruido de bajo volumen", EXCEPTO si tiene >= except_events eventos
    sostenidos o infraestructura compartida >= except_infra: en ese caso puede
    alcanzar HIGH (79), pero NUNCA CRITICAL (eso lo fija scale_cap con
    scale_min_accounts.CRITICAL=10).

    Conserva como señal las parejas de 2 cuentas con volumen (cluster_012=22
    eventos, cluster_006=31) y tumba a WATCH las parejas efímeras (2-3
    eventos) que saturaban el top con banda alta.
    Config: scoring.scale_floor = {min_accounts, except_events, except_infra}."""
    p = _tema_scale(config, tema, "scale_floor",
                    {"min_accounts": 3, "except_events": 10, "except_infra": 80})
    bands = load_bands(config)
    if accounts < p["min_accounts"]:
        excepcion = (events >= p["except_events"]) or (infra >= p["except_infra"])
        if not excepcion:
            return float(bands["WATCH"][1])  # 39 — posible ruido de bajo volumen
        return min(float(overall), float(bands["HIGH"][1]))  # 79 máx, nunca CRITICAL
    return overall


def origen_unico_cap(overall, n_urls, n_events, config=None, tema=None):
    """Tope por "origen único" (análisis externo 11/Sep): un cluster cuyos
    eventos provienen de UNA SOLA URL es un "eco de 1 pieza" (varias cuentas
    repitiendo el mismo artículo/fuente), no una campaña con producción propia,
    y no debe entrar en bandas altas a menos que la masa lo respalde: se topa a
    cap_band (por defecto ANOMALOUS) para evitar el "eco de agencia" leído como
    coordinación sostenida.

    Config: scoring.origen_unico = {max_urls, min_events, cap_band}, con
    override por tema en temas.<tema>.scoring.origen_unico (igual que pesos).

    Devuelve (overall, es_eco): es_eco=True etiqueta el cluster como eco de una
    sola pieza aunque el tope no haya cambiado el score (ya estaba dentro)."""
    p = _tema_scale(config, tema, "origen_unico",
                    {"max_urls": 1, "min_events": 2, "cap_band": "ANOMALOUS"})
    es_eco = (n_urls <= p["max_urls"]) and (n_events >= p["min_events"])
    if es_eco:
        bands = load_bands(config)
        overall = min(float(overall), float(bands[p["cap_band"]][1]))
    return overall, es_eco


def mainstream_cap(overall, mainstream_frac, config=None, tema=None):
    """Tope por "eco de prensa": si >= frac_min de los dominios amplificados del
    cluster son de medios establecidos, se topa a cap_band (ANOMALOUS). La
    coordinacion observada es compatible con cobertura periodistica normal, no
    con una campana inautentica.

    Config: scoring.mainstream_cap = {frac_min, cap_band}.
    Devuelve (overall, es_eco_prensa)."""
    p = _tema_scale(config, tema, "mainstream_cap",
                    {"frac_min": 0.8, "cap_band": "ANOMALOUS"})
    try:
        frac = float(mainstream_frac)
    except Exception:
        frac = 0.0
    es_eco = frac >= float(p["frac_min"])
    if es_eco:
        bands = load_bands(config)
        overall = min(float(overall), float(bands[p["cap_band"]][1]))
    return overall, es_eco


def single_source_feed_cap(overall, accounts, dominant_account_frac, dominant_domain_frac,
                           config=None, tema=None):
    """Tope por "feed de una sola fuente" (2-Oct, auditoría externa): si el
    cluster es PEQUEÑO y UNA cuenta o UNA red de dominio concentra casi todo el
    contenido, lo observado es un feed/agregador individual (radio, periódico,
    blog propio), no coordinación entre actores distintos: se topa a cap_band
    (ANOMALOUS) igual que mainstream_cap/origen_unico.

    Usa los MISMOS umbrales que `detection/explicaciones.py` marca la explicación
    `single_source_feed` como supported, para no divergir del propio detector
    (regla: el cap y la explicación deben hablar el mismo idioma):
      - dominant_account_frac >= min_account_frac  (0.55 por defecto)
      - O dominant_domain_frac >= min_domain_frac   (0.8 por defecto)
    Solo aplica con pocas cuentas (<= max_accounts): con masa, la concentración
    de una fuente puede ser una campaña multicuenta que SÍ merece banda alta.

    Config: scoring.single_source_feed_cap = {max_accounts, min_account_frac,
    min_domain_frac, cap_band}, con override por tema en temas.<tema>.scoring.
    Devuelve (overall, es_feed)."""
    p = _tema_scale(config, tema, "single_source_feed_cap",
                    {"max_accounts": 5, "min_account_frac": 0.55,
                     "min_domain_frac": 0.8, "cap_band": "ANOMALOUS"})
    try:
        daf = float(dominant_account_frac)
    except Exception:
        daf = 0.0
    try:
        ddf = float(dominant_domain_frac)
    except Exception:
        ddf = 0.0
    es_feed = (accounts <= int(p["max_accounts"])
               and (daf >= float(p["min_account_frac"])
                    or ddf >= float(p["min_domain_frac"])))
    if es_feed:
        bands = load_bands(config)
        overall = min(float(overall), float(bands[p["cap_band"]][1]))
    return overall, es_feed


def meta_coverage_cap(overall, subtype, config=None, tema=None):
    """Tope por "cobertura SOBRE desinformación" (auditoría externa 4-Oct): un
    cluster cuyo rol narrativo dominante es `meta_analysis` (analiza/explica la
    desinformación, no la produce) es COBERTURA sobre el fenómeno, no una
    narrativa FIMI: se topa a cap_band (ANOMALOUS). Coherente con subtipo.py.

    Config: scoring.meta_coverage_cap = {subtypes: ["meta_analysis"], cap_band}.
    Devuelve (overall, es_meta)."""
    p = _tema_scale(config, tema, "meta_coverage_cap",
                    {"subtypes": ["meta_analysis"], "cap_band": "ANOMALOUS"})
    st = str(subtype or "")
    es = st in (p.get("subtypes") or ["meta_analysis"])
    if es:
        bands = load_bands(config)
        overall = min(float(overall), float(bands[p["cap_band"]][1]))
    return overall, es


def single_domain_cap(overall, dominant_domain_frac, config=None, tema=None):
    """Tope por "eco de un solo dominio" (auditoría externa 4-Oct): si ~todos los
    enlaces del cluster apuntan a UN mismo dominio (>= min_domain_frac), lo
    observado es amplificación de una fuente/agregador, no coordinación entre
    actores distintos: se topa a cap_band (ANOMALOUS) aunque haya masa.

    NOTA de diseño: a diferencia de `single_source_feed_cap`, aquí NO se exige un
    nº pequeño de cuentas; es un cambio de política deliberado (una campaña
    multicuenta suele diversificar dominios; un único dominio dominante es más
    compatible con un feed/agregador). Revertible en scoring.single_domain_cap.

    Config: scoring.single_domain_cap = {min_domain_frac, cap_band}.
    Devuelve (overall, es_1dom)."""
    p = _tema_scale(config, tema, "single_domain_cap",
                    {"min_domain_frac": 0.9, "cap_band": "ANOMALOUS"})
    try:
        ddf = float(dominant_domain_frac)
    except Exception:
        ddf = 0.0
    es = ddf >= float(p["min_domain_frac"])
    if es:
        bands = load_bands(config)
        overall = min(float(overall), float(bands[p["cap_band"]][1]))
    return overall, es


def solve_scale(overall, accounts, events, infra, config=None, tema=None, n_urls=0):
    """Aplica la escala completa del cluster (orden correcto):
    1) bonus por masa; 2) piso híbrido; 3) cap CRITICAL/HIGH por masa mínima;
    4) tope por "origen único" (1 sola URL => eco de 1 pieza).

    Devuelve (overall_final, floored, es_eco):
      floored=True => cae en "posible ruido de bajo volumen" (para marcarlo
      en el assessment, la tarjeta y el informe).
      es_eco=True => etiquetado "eco de 1 pieza" (tope aplicado o ya dentro)."""
    overall = scale_bonus(overall, accounts, config, tema)
    floored = False
    p = _tema_scale(config, tema, "scale_floor",
                    {"min_accounts": 3, "except_events": 10, "except_infra": 80})
    bands = load_bands(config)
    if accounts < p["min_accounts"]:
        excepcion = (events >= p["except_events"]) or (infra >= p["except_infra"])
        if not excepcion:
            overall = float(bands["WATCH"][1])
            floored = True
        else:
            overall = min(float(overall), float(bands["HIGH"][1]))
    overall = scale_cap(overall, accounts, config, tema)
    overall, es_eco = origen_unico_cap(overall, n_urls, events, config, tema)
    return overall, floored, es_eco

def band_gate(overall, accounts, anomaly, config=None, tema=None, kcore=0):
    """Gate de banda (S3, 'alerta quirúrgica'): una banda alta exige, además
    del score, un mínimo de ANOMALÍA, de CUENTAS y —desde 29/Sep— un NÚCLEO
    MUTUO en el grafo (k-core >= 2). Evita que el eco de medios (masa sin
    anomalía) o las parejas (2 cuentas) griten HIGH/CRITICAL.

    `min_kcore` (29/Sep): el k-core es el mayor subgrafo en el que TODOS los
    nodos tienen grado >= k (graph_metrics.kcore_subset). kcore>=2 exige que
    las cuentas estén conectadas MUTUAMENTE (un ciclo), no solo encadenadas.
    Sin él, una cadena de enlaces (mediana de 1 arista por cluster) llegaba a
    HIGH por percolación: el gate midió 8 % de WATCH, 47 % de ANOMALOUS y 86 %
    de HIGH con núcleo, o sea que discrimina de forma monótona en lugar de
    recortar por gusto. Las cadenas (kcore=1) caen a ANOMALOUS.
    Desactivable con min_kcore: 0 (o no definiendo la clave).

    Config: scoring.band_gate = {
      'HIGH': {'min_accounts': 3, 'min_anomaly': 20, 'min_kcore': 2},
      'CRITICAL': {'min_accounts': 10, 'min_anomaly': 40, 'min_kcore': 2}}
    Sin config usa esos valores por defecto."""
    gate = {"HIGH": {"min_accounts": 3, "min_anomaly": 20, "min_kcore": 2},
            "CRITICAL": {"min_accounts": 10, "min_anomaly": 40, "min_kcore": 2}}
    if config:
        gate.update((config.get("scoring", {}) or {}).get("band_gate", {}) or {})
    bands = load_bands(config)
    order = ["NORMAL", "WATCH", "ANOMALOUS", "HIGH", "CRITICAL"]
    cur = band_for(overall, bands)
    allowed = "ANOMALOUS"
    for b in ("HIGH", "CRITICAL"):
        req = gate.get(b, {}) or {}
        if (accounts >= req.get("min_accounts", 0)
                and anomaly >= req.get("min_anomaly", 0)
                and (kcore or 0) >= req.get("min_kcore", 0)):
            allowed = b
        else:
            break
    if order.index(cur) > order.index(allowed):
        return float(bands[allowed][1])
    return overall
