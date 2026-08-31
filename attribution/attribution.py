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
    ("H2", "Domestic coordinated campaign", "Coordinación temporal/contenido dentro del país, sin infraestructura externa."),
    ("H3", "Foreign influence operation", "Coordinación + infraestructura compartida + narrativa transversal a países."),
    ("H4", "Media amplification", "Amplificación por medios establecidos, no por cuentas anónimas coordinadas."),
    ("H5", "Political campaign", "Coordinación en el marco electoral/partidista doméstico."),
    ("H6", "Unknown", "Sin evidencia suficiente para discriminar entre las anteriores."),
]


def classify_hypotheses(cluster):
    """Ranking de hipótesis H1-H6 según señales del cluster.

    cluster: dict con coordination_score, amplification_score, anomaly_score,
    infrastructure_score, network_density, accounts, diversity.
    Devuelve lista ordenada [(Hx, label, score0-1, razon)].
    """
    c = cluster or {}
    coord = c.get("coordination_score", 0) / 100
    amp = c.get("amplification_score", 0) / 100
    anom = c.get("anomaly_score", 0) / 100
    infra = c.get("infrastructure_score", 0) / 100
    net = c.get("network_density", 0)
    accounts = c.get("accounts", 0)
    diversity = c.get("content_diversity", 0.5)  # 0=mismo contenido, 1=muy variado

    scores = {}
    # H1 orgánico: alta diversidad, bajo net, pocas aristas fuertes
    scores["H1"] = diversity * 0.6 + (1 - net) * 0.2 + (1 - coord) * 0.2
    # H2 doméstica: coordinación alta pero infra baja
    scores["H2"] = coord * 0.4 + amp * 0.3 + (1 - infra) * 0.3
    # H3 extranjera: coordinación + infra + transversalidad
    scores["H3"] = coord * 0.35 + infra * 0.4 + net * 0.25
    # H4 mediática: amplificación alta, diversidad media, pocas cuentas anónimas
    scores["H4"] = amp * 0.4 + (1 - anom) * 0.3 + diversity * 0.3
    # H5 política: coordinación + contexto temporal electoral (proxy: coord+amp)
    scores["H5"] = coord * 0.4 + amp * 0.3 + net * 0.3
    # H6 desconocido: todas bajas (no hay señal fuerte)
    scores["H6"] = (1 - max(coord, amp, infra)) * 0.8 + 0.2

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    out = []
    for h, s in ranked:
        label = next(x[1] for x in HYPOTHESES if x[0] == h)
        razon = next(x[2] for x in HYPOTHESES if x[0] == h)
        out.append({"hypothesis": h, "label": label, "score": round(s, 3), "reason": razon})
    return out


def attribution(hypotheses, infra_shared=False, cross_country=False):
    """Hipótesis de actor con nivel de confianza, SOLO si hay señal.

    Devuelve dict: actor, confidence, evidence, missing_evidence.
    La ausencia de atribución es resultado válido.
    """
    top = hypotheses[0] if hypotheses else {"label": "Unknown"}
    # Si la señal más fuerte no pasa de un umbral, NO hay atribución.
    if not hypotheses or hypotheses[0]["score"] < 0.5:
        return {
            "actor": "UNKNOWN",
            "confidence": "NO_ATTRIBUTION",
            "evidence": "No hay señales suficientes para formular hipótesis de actor.",
            "missing_evidence": "coordinación confirmada; infraestructura compartida; enlace organizativo",
        }

    if top["hypothesis"] == "H3" and infra_shared:
        conf = "HIGH" if cross_country else "MEDIUM"
        actor = "FOREIGN_STATE_OR_PROXY" if cross_country else "PROXY"
    elif top["hypothesis"] == "H3":
        conf, actor = "LOW", "FOREIGN_NON_STATE"
    elif top["hypothesis"] in ("H2", "H5"):
        conf, actor = "MEDIUM" if top["score"] > 0.6 else "LOW", "DOMESTIC"
    elif top["hypothesis"] == "H4":
        conf, actor = "MEDIUM", "DOMESTIC_INSTITUTIONAL"  # medios
    else:
        conf, actor = "NO_ATTRIBUTION", "UNKNOWN"

    return {
        "actor": actor,
        "confidence": conf,
        "evidence": f"Hipótesis principal {top['label']} (score {top['score']}). "
                    f"Infraestructura compartida: {'sí' if infra_shared else 'no'}.",
        "missing_evidence": "vínculo organizativo verificado; vínculo financiero; atribución directa",
    }
