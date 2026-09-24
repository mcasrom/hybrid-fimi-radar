#!/usr/bin/env python3
"""Atribución agnóstica al actor + hipótesis alternativas.

PRINCIPIO: la atribución es un módulo SEPARADO del detector y solo se activa
DESPUÉS de confirmar anomalía + coordinación + infraestructura común.

Taxonomía neutra de actores (nunca ideología como indicador de amenaza):
  UNKNOWN / DOMESTIC / FOREIGN_STATE / FOREIGN_NON_STATE / TRANSNATIONAL_NETWORK
  / PROXY / MIXED / UNDETERMINED

Hipótesis alternativas por cluster (anti sesgo de confirmación):
  H1 Orgánico viral · H2 Campaña doméstica · H3 Operación extranjera ·
  H4 Amplificación mediática · H5 Campaña política · H6 Desconocido

La ausencia de atribución es un RESULTADO VÁLIDO.
"""

# Taxonomía de actores (neutra, no ideológica)
ACTORS = [
    "UNKNOWN", "DOMESTIC", "FOREIGN_STATE", "FOREIGN_NON_STATE",
    "TRANSNATIONAL_NETWORK", "PROXY", "MIXED", "UNDETERMINED",
]

HYPOTHESES = [
    ("H1", "Organic viral event", "Muchas cuentas, diversidad alta, contenido modificado, difusión progresiva."),
    ("H2", "Domestic coordinated campaign", "Coordinación temporal/contenido DENTRO del país CON evidencia de estructura compartida (URLs/dominios)."),
    ("H2b", "Synchronized activity without operator attribution", "Alta sincronía temporal SIN evidencia de estructura organizada (cuentas/dominios/administradores): no atribuye operador."),
    ("H3", "Foreign influence operation", "Coordinación + infraestructura compartida + narrativa transversal a países."),
    ("H4", "Media amplification", "Amplificación por medios establecidos, no por cuentas anónimas coordinadas."),
    ("H5", "Sustained synchronization with diverse content", "Alta sincronía + contenido diverso SIN evidencia de estructura; NO implica campaña política ni electoral."),
    ("H6", "Unknown", "Sin evidencia suficiente para discriminar entre las anteriores."),
]


def classify_hypotheses(cluster):
    """Ranking de hipótesis H1-H6 a partir de los COMPONENTES (0-100) del cluster.

    cluster: dict con synchronization, content_similarity, amplification,
    anomaly, infrastructure, network_density (escala 0-100) + accounts, n_urls.

    FIX (17/09/2026): antes se le pasaba el dict de `cluster_summary` (con
    coordination_score/anomaly_score en otra escala y SIN amplification,
    infrastructure, network_density ni content_diversity) -> los pesos caían a
    sus valores por defecto y las hipótesis salían casi constantes (H4=0,45
    fijo, H6≈0,94). Ahora se le pasan los componentes reales del run.
    Devuelve lista ordenada [(Hx, label, score0-1, razon)].
    """
    c = cluster or {}
    sync = c.get("synchronization", 0) / 100
    content = c.get("content_similarity", 0) / 100
    amp = c.get("amplification", 0) / 100
    anom = c.get("anomaly", 0) / 100
    infra = c.get("infrastructure", 0) / 100
    net = c.get("network_density", 0) / 100
    accounts = c.get("accounts", 0)
    n_urls = c.get("n_urls", 0)
    masa = min(1.0, accounts / 20)   # masa de red (satura a 20 cuentas)
    div = min(1.0, n_urls / 10)      # diversidad de contenido (satura a 10 urls)
    # EVIDENCIA DE ESTRUCTURA: exige un núcleo MUTUO (kcore>=2) de al menos 3
    # cuentas (kcore_size>=3). El gate anterior (solo kcore_size>=3) admitía
    # 1-cores (cadenas/estrellas, kcore=1) como "estructura"; ahora se exige
    # además que el núcleo sea mutuo (k>=2), alineado con el badge _kcore_chip.
    kc_size = c.get("kcore_size", 0) or 0
    kc = c.get("kcore", 0) or 0
    struct = min(1.0, infra) if (kc >= 2 and kc_size >= 3) else 0.0

    scores = {}
    # H1 orgánico viral: contenido diverso, anomalía e infraestructura bajas
    scores["H1"] = div * 0.30 + (1 - anom) * 0.25 + (1 - infra) * 0.25 + masa * 0.20
    # H2 campaña doméstica: EXIGE estructura (URLs/dominios compartidos). Sin
    # estructura compartida NO es "campaña coordinada" (ese material va a H2b).
    scores["H2"] = struct * (sync * 0.55 + (1 - anom) * 0.45)
    # H2b sincronización sin atribución de operador: sync alta y SIN estructura.
    scores["H2b"] = (1 - struct) * (sync * 0.65 + (1 - anom) * 0.35)
    # H3 operación extranjera: requiere infraestructura + red + anomalía altas
    # a la vez (sin eso no hay base para atribuir actor externo).
    scores["H3"] = min(infra, net, anom) * 0.9 + sync * 0.1
    # H4 amplificación mediática: amplificación global alta, anomalía/infra bajas
    scores["H4"] = amp * 0.45 + (1 - anom) * 0.30 + (1 - infra) * 0.25
    # H5 (renombrada): sincronía + diversidad, sin estructura. NO es "campaña
    # política": midió siempre la FORMA (sync+diversidad), no un contexto político.
    scores["H5"] = sync * 0.40 + div * 0.35 + (1 - infra) * 0.25
    # H6 desconocido: ninguna señal fuerte
    scores["H6"] = (1 - max(sync, content, amp, anom, infra, net)) * 0.8 + 0.2

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out = []
    for h, s in ranked:
        label = next(x[1] for x in HYPOTHESES if x[0] == h)
        razon = next(x[2] for x in HYPOTHESES if x[0] == h)
        out.append({"hypothesis": h, "label": label, "score": round(s, 3), "reason": razon})
    return out


def attribution(hypotheses, infra_shared=False, cross_country=False):
    """Hipótesis de actor con nivel de confianza, SOLO si hay señal + evidencia.

    POLÍTICA CONSERVADORA (17/09/2026): el radar NO tiene dato de país/idioma por
    cuenta, así que NO atribuye actor doméstico (H2/H5 son mecanismos, no actor).
    Solo se atribuye actor EXTERNO cuando H3 (operación extranjera) gana Y hay
    infraestructura compartida. En el resto, UNKNOWN — la ausencia de atribución
    es un resultado válido.
    """
    top = hypotheses[0] if hypotheses else {"label": "Unknown", "score": 0.0}
    h = top.get("hypothesis")
    if h == "H3" and infra_shared and top["score"] >= 0.6:
        conf = "HIGH" if cross_country else "MEDIUM"
        actor = "FOREIGN_STATE_OR_PROXY" if cross_country else "PROXY"
        return {
            "actor": actor,
            "confidence": conf,
            "evidence": f"Hipótesis principal {top['label']} (score {top['score']}) "
                        f"con infraestructura compartida.",
            "missing_evidence": "vínculo organizativo verificado; vínculo financiero; atribución directa",
        }
    return {
        "actor": "UNKNOWN",
        "confidence": "NO_ATTRIBUTION",
        "evidence": "Sin evidencia de actor: el radar mide coordinación, no autoría "
                    "(y no tiene dato de país/idioma por cuenta).",
        "missing_evidence": "coordinación confirmada; infraestructura compartida; enlace organizativo",
    }
