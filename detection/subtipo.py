#!/usr/bin/env python3
"""hybrid-fimi-radar — rol narrativo del cluster (capa semántica ligera, 24/Sep).

Distingue QUÉ TIPO de pieza es, no si es cierta: separa "hablar DE FIMI" (meta,
respuesta oficial, reporte de incidente) de "posible NARRATIVA FIMI" (narrativa
potencial, señal de coordinación). Responde a la crítica de que "una noticia
contiene la palabra desinformación porque la combate o la analiza".

  - official_response  : respuesta institucional (Gobierno/Ministerio/autoridades,
                         informe/estrategia/condena/alerta...).
  - incident_report    : reporte de un incidente concreto (ataque/intrusión/
                         sabotaje/filtración/ransomware/DDoS/drones...).
  - meta_analysis      : análisis/explicación (expertos/académico/estudio/"qué es").
  - coordination_signal: lenguaje de coordinación/amplificación (bots, red,
                         amplificado, orquestado, inauténtico).
  - potential_narrative: propaganda/desinformación/injerencia sin lenguaje claro
                         de informe, respuesta o análisis -> posible narrativa.

REGLAS: es una función PURA (sin I/O) que reutiliza el matcher compartido del
pipeline (`normalizer.clasificar`) para ser consistente con el gate de temas.
NO toca `overall_score`, bandas ni atribución. El rol es cluster-level: se toma
el dominante sobre los textos del cluster (con recuento para auditar mezcla).
"""
from __future__ import annotations

import re
from collections import Counter

from normalizer.clasificar import normalizar

CODES = [
    ("official_response", "Respuesta oficial"),
    ("incident_report", "Reporte de incidente"),
    ("meta_analysis", "Análisis / meta"),
    ("coordination_signal", "Señal de coordinación"),
    ("potential_narrative", "Posible narrativa"),
]
_LABEL = dict(CODES)

# Prioridad de desambiguación: primero lo que MÁS aleja de "narrativa FIMI".
PRIORITY = ["meta_analysis", "official_response", "incident_report",
            "coordination_signal", "potential_narrative"]

MARKERS = {
    "official_response": [
        "gobierno", "ministerio", "ministerio del interior", "ministerio de defensa",
        "autoridades", "autoridad", "moncloa", "consejo de ministros", "policia",
        "guardia civil", "cni", "cnti", "europol", "comision europea",
        "informe", "estrategia", "condena", "investigacion", "investiga",
        "alerta", "alertado", "advertencia", "respuesta", "combate", "combatir",
        "defensa", "desmentir", "desmentido", "verificacion", "verificado",
    ],
    "incident_report": [
        "ataque", "ciberataque", "ciberataques", "intrusion", "sabotaje",
        "filtracion", "ransomware", "ddos", "denegacion de servicio", "drones",
        "interferencia", "brecha", "hackeo", "incidente", "afectado",
        "vulnerabilidad", "secuestro de datos", "apagado",
    ],
    "meta_analysis": [
        "experto", "expertos", "academico", "academicos", "estudio", "universidad",
        "investigador", "investigadores", "analisis", "analiza", "analizan",
        "analizar", "que es", "como funciona", "informe anual", "simposio",
        "conferencia", "debate", "ensayo", "libro", "manual", "guia",
    ],
    "coordination_signal": [
        "coordinado", "coordinada", "coordinacion", "amplificacion", "amplificado",
        "amplificada", "red de bots", "cuentas automatizadas", "granja de trolls",
        "astroturfing", "inautentico", "inautentica", "orquestado", "orquestada",
        "sincronizado", "sincronizada",
    ],
    "potential_narrative": [
        "desinformacion", "desinformaciones", "propaganda", "propagandas",
        "injerencia", "injerencias", "operacion de influencia",
        "operaciones de influencia", "campana", "narrativa", "bulos", "bulo",
        "fake news", "manipulacion informativa",
    ],
}

_PREP = {c: [re.compile(r"\b" + re.escape(normalizar(t)) + r"\b") for t in terms]
         for c, terms in MARKERS.items()}


def clasificar_texto(text):
    """Devuelve el código de rol narrativo del texto, o None si no encaja."""
    nt = normalizar(str(text or ""))
    if not nt:
        return None
    for code in PRIORITY:
        for rx in _PREP[code]:
            if rx.search(nt):
                return code
    return None


def dominante(texts):
    """Rol dominante de un cluster a partir de sus textos.

    Devuelve {"dominant": code|"", "counts": {code: n}, "label": str}.
    """
    cnt = Counter()
    for t in texts or []:
        c = clasificar_texto(t)
        if c:
            cnt[c] += 1
    if not cnt:
        return {"dominant": "", "counts": {}, "label": ""}
    dom = max(PRIORITY, key=lambda c: (cnt.get(c, 0), -PRIORITY.index(c)))
    return {"dominant": dom, "counts": dict(cnt), "label": _LABEL.get(dom, dom)}
