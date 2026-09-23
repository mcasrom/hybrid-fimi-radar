#!/usr/bin/env python3
"""tema_reglas.py — Fuente única de verdad de las REGLAS DE TEMA.

Consolida la lógica que hoy estaba duplicada (y derivando) en `collectors/capture.py`,
`detection/salud_keywords.py`, `detection/recompute_temas.py`, `detection/backfill_*`,
`detection/transversal.py`, etc.:

  - qué temas están ACTIVOS (produccion/piloto) y cuáles CERRADOS;
  - las keywords por tema y los gates `filtro`/`contexto` de config.yaml;
  - el matcher compartido (normalizar/tokens/matches/temas_por_contenido);
  - bootstrap de `ROOT` en `sys.path` (evita el fallo clásico
    `ModuleNotFoundError: No module named 'detection'/'normalizer'` al correr como script).

Regla: los módulos nuevos deben importar de aquí, NO reimplementar el matcher ni el gate.
"""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config.yaml"

# Bootstrap: que `normalizer`/`detection` sean importables aunque se ejecute como script.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Matcher compartido (re-export; una sola implementación en todo el proyecto).
from normalizer.clasificar import (  # noqa: E402
    STOP, normalizar, _tokens, _matches, temas_por_contenido,
)

ACTIVOS = ("produccion", "piloto")


def cargar_config():
    """config.yaml como dict (o {} si falla)."""
    try:
        return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def temas_cfg():
    return (cargar_config().get("temas") or {})


def estado(tema, _cfg=None):
    cfg = _cfg if _cfg is not None else cargar_config()
    return ((cfg.get("temas") or {}).get(tema) or {}).get("estado")


def temas_activos(_cfg=None):
    """Temas monitorizados: estado en {produccion, piloto} (ausente = produccion)."""
    cfg = _cfg if _cfg is not None else cargar_config()
    return sorted(
        t for t, m in (cfg.get("temas") or {}).items()
        if (m or {}).get("estado", "produccion") in ACTIVOS)


def temas_cerrados(_cfg=None):
    """Temas NO activos (cerrado/candidato/…): fuera de captura y de salud de keywords."""
    cfg = _cfg if _cfg is not None else cargar_config()
    return sorted(
        t for t, m in (cfg.get("temas") or {}).items()
        if (m or {}).get("estado", "produccion") not in ACTIVOS)


def reglas_por_tema(_cfg=None):
    """Devuelve (por_tema, filtros, contextos, cerrados) tal como lo consume el pipeline.

    - `por_tema`: {tema: [keywords...]} (de la lista global `keywords`).
    - `filtros` / `contextos`: {tema: [términos_gate...]} (de `temas.<tema>`).
    - `cerrados`: set de temas NO activos.
    """
    cfg = _cfg if _cfg is not None else cargar_config()
    por_tema = {}
    for k in (cfg.get("keywords") or []):
        if not isinstance(k, dict):
            continue
        t = k.get("tema") or "frontera_sur"
        por_tema.setdefault(t, []).append((k.get("palabra") or "").strip())
    filtros = {t: ((m or {}).get("filtro") or []) for t, m in (cfg.get("temas") or {}).items()}
    contextos = {t: ((m or {}).get("contexto") or []) for t, m in (cfg.get("temas") or {}).items()}
    cerrados = set(temas_cerrados(cfg))
    return por_tema, filtros, contextos, cerrados


def prep_gates(filtros, contextos):
    """Pre-normaliza los gates `filtro`/`contexto` una sola vez (consistente con capture.py)."""
    filtros_pre, contextos_pre = {}, {}
    for t, terms in filtros.items():
        prep = [(normalizar(str(x)), _tokens(str(x))) for x in (terms or []) if normalizar(str(x))]
        if prep:
            filtros_pre[t] = prep
    for t, terms in contextos.items():
        prep = [(normalizar(str(x)), _tokens(str(x))) for x in (terms or []) if normalizar(str(x))]
        if prep:
            contextos_pre[t] = prep
    return filtros_pre, contextos_pre


if __name__ == "__main__":  # diagnóstico rápido
    print("ROOT:", ROOT)
    print("activos:", temas_activos())
    print("cerrados:", temas_cerrados())
