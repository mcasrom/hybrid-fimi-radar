#!/usr/bin/env python3
"""hybrid-fimi-radar — explicaciones alternativas por cluster (opción 2, 24/Sep).

Convierte en DATO PERSISTIDO lo que antes solo era texto de UI: para cada cluster
evaluado se listan las explicaciones alternativas plausibles (eco de prensa, eco de
una sola pieza, viralidad orgánica, sincronización sin operador, automatización no
maliciosa, movilización legítima, artefacto del grafo) con un estado y la EVIDENCIA
que lo motiva.

Reglas de diseño (acordadas):
  - NO toca el algoritmo, `overall_score`, las bandas ni la atribución. Solo LEE
    métricas que el pipeline ya calcula.
  - No es una clasificación de "la verdad": usa tres estados
    (`supported` | `plausible` | `ruled_out`) y conserva siempre la evidencia.
  - Es una función PURA (sin I/O) para poder testearla con casos sintéticos.

Se persiste como JSON en `clusters.alternative_explanations` y se expone en la API,
el dashboard y las exportaciones.
"""
from __future__ import annotations

# Orden de prioridad: el primer `supported` (o si no, el primer `plausible`) es la
# explicación principal del cluster.
CODES = [
    ("mainstream_echo", "Eco de prensa"),
    ("single_piece_echo", "Eco de una sola pieza"),
    ("organic_viral", "Viralidad orgánica"),
    ("synchronized_without_operator", "Sincronización sin operador identificable"),
    ("automated_non_malicious", "Automatización no maliciosa"),
    ("legitimate_mobilization", "Movilización legítima"),
    ("graph_artifact", "Artefacto del grafo"),
    ("unresolved", "Sin explicación concluyente"),
]
_LABEL = dict(CODES)
_ORDER = [c for c, _ in CODES]


def _item(code, status, evidence):
    return {"code": code, "label": _LABEL[code], "status": status, "evidence": evidence}


def para_cluster(
    *,
    accounts=0,
    n_events=0,
    n_urls=0,
    synchronization=0.0,
    content_similarity=0.0,
    amplification=0.0,
    infrastructure=0.0,
    anomaly=0.0,
    kcore=0,
    kcore_size=0,
    mainstream_frac=0.0,
    mainstream_cap_applied=False,
    single_piece_cap=False,
    boilerplate_frac=0.0,
    top_hypothesis="",
    hypotheses=None,
    narrative_role="",
):
    """Devuelve la lista de explicaciones alternativas (todas, con estado + evidencia).

    Métricas 0-100 salvo `mainstream_frac`/`boilerplate_frac` (0-1) y `accounts`/`n_*`.
    Los umbrales son heurísticos y conservadores: ante la duda -> `plausible`, y si
    nada encaja -> `unresolved` (que pasa a `supported`, "sin explicación concluyente").
    """
    items = []

    # 1. Eco de prensa: la mayoría de dominios son medios establecidos.
    if mainstream_cap_applied or mainstream_frac >= 0.8:
        st = "supported"
    elif mainstream_frac >= 0.5:
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("mainstream_echo", st, {
        "mainstream_domain_fraction": round(float(mainstream_frac), 2),
        "mainstream_cap_applied": bool(mainstream_cap_applied),
    }))

    # 2. Eco de una sola pieza: una misma URL repetida por varias cuentas.
    if single_piece_cap or (n_urls <= 1 and n_events >= 2):
        st = "supported"
    elif n_urls == 2:
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("single_piece_echo", st, {
        "distinct_urls": int(n_urls), "n_events": int(n_events),
    }))

    # 3. Viralidad orgánica: mucha sincronía, anomalía e infraestructura bajas.
    if synchronization >= 60 and anomaly < 20 and infrastructure < 30:
        st = "supported"
    elif synchronization >= 50 and anomaly < 30:
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("organic_viral", st, {
        "synchronization": round(float(synchronization), 1),
        "anomaly": round(float(anomaly), 1),
        "infrastructure": round(float(infrastructure), 1),
    }))

    # 4. Sincronización sin operador: H2b (sync alta sin estructura organizada).
    if top_hypothesis == "H2b":
        st = "supported"
    elif synchronization >= 60 and int(kcore_size) < 3 and infrastructure < 40:
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("synchronized_without_operator", st, {
        "top_hypothesis": top_hypothesis, "kcore_size": int(kcore_size),
        "infrastructure": round(float(infrastructure), 1),
    }))

    # 5. Automatización no maliciosa: plantilla común o contenido idéntico masivo.
    if boilerplate_frac >= 0.5 and accounts >= 5:
        st = "supported"
    elif boilerplate_frac >= 0.5 or (content_similarity >= 80 and accounts >= 5):
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("automated_non_malicious", st, {
        "boilerplate_fraction": round(float(boilerplate_frac), 2),
        "content_similarity": round(float(content_similarity), 1),
        "accounts": int(accounts),
    }))

    # 6. Movilización legítima: mensaje compartido, anomalía baja, sin infra densa.
    if synchronization >= 70 and anomaly < 15 and content_similarity >= 60 and infrastructure < 50:
        st = "supported"
    elif synchronization >= 60 and anomaly < 30 and content_similarity >= 50:
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("legitimate_mobilization", st, {
        "synchronization": round(float(synchronization), 1),
        "content_similarity": round(float(content_similarity), 1),
        "anomaly": round(float(anomaly), 1),
    }))

    # 7. Artefacto del grafo: macro-cluster por transitividad (mucha masa, poco núcleo).
    if accounts >= 30 and int(kcore_size) < 2 and infrastructure < 30:
        st = "supported"
    elif accounts >= 15 and int(kcore_size) < 3:
        st = "plausible"
    else:
        st = "ruled_out"
    items.append(_item("graph_artifact", st, {
        "accounts": int(accounts), "kcore_size": int(kcore_size),
        "infrastructure": round(float(infrastructure), 1),
    }))

    # 8. Sin explicación concluyente: supported si ninguna otra encaja.
    resolved = any(it["status"] == "supported" for it in items)
    items.append(_item("unresolved", "ruled_out" if resolved else "supported", {
        "resolved_by": next((it["code"] for it in items if it["status"] == "supported"), None),
        "narrative_role": narrative_role or "",
    }))
    return items


def principal(items):
    """Código de la explicación principal (primer supported; si no, primer plausible)."""
    if not items:
        return "unresolved"
    for it in items:
        if it["status"] == "supported":
            return it["code"]
    for it in items:
        if it["status"] == "plausible":
            return it["code"]
    return "unresolved"


def resumen(items):
    """Resumen corto {principal, supported, plausible} para la API/dashboard."""
    return {
        "principal": principal(items),
        "supported": [it["code"] for it in items if it["status"] == "supported"],
        "plausible": [it["code"] for it in items if it["status"] == "plausible"],
    }
