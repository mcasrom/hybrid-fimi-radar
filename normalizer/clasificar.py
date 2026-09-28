#!/usr/bin/env python3
"""Asignación de temas por CONTENIDO, no solo por la query de captura.

El tema de un evento no debe depender únicamente de la keyword que lo
capturó: un titular de un feed de prensa general puede hablar de política
nacional Y de frontera a la vez. Este módulo matchea las keywords de TODOS
los temas contra el texto real del evento y acumula todos los temas que
cuadran (multi-tema), sin atribución de actor (visible, no interpretativo).

El match es por PRESENCIA DE TÉRMINOS, no por subcadena contigua: los titulares
reales no contienen la frase completa de la keyword ("Marruecos Unión Europea
relaciones"), sino sus términos separados ("las relaciones y la diplomacia de
España y Marruecos"). Se exige que esté presente una fracción de los términos
significativos de la keyword.
"""
import math
import re
import unicodedata
from functools import lru_cache

STOP = set("de la el en y a los las un una con por para se su sus al del que es no lo"
           " e o u entre como más ya fue han ha sobre desde hasta".split())


def normalizar(s):
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


@lru_cache(maxsize=None)
def _tokens(kw):
    """Términos significativos de una keyword (sin stopwords).

    Caché: se llama millones de veces con el MISMO puñado de keywords en cada
    generación del dashboard (el matcher recorre el corpus por keyword). Recalcular
    normalizar+split+stopwords cada vez era parte del cuello (~30 M llamadas).
    """
    return [t for t in normalizar(kw).split() if len(t) > 2 and t not in STOP]


@lru_cache(maxsize=None)
def _plurales(palabra):
    """Variantes plurales de una palabra (tolerancia -s / -es).

    El castellano forma el plural con `-s` (vocal final: propaganda -> propagandas)
    o `-es` (consonante final: desinformación -> desinformaciones). Se generan
    ambas; la forma que no aplica no aparecerá en el texto y no molesta.

    NO se genera el SINGULAR de una palabra ya plural: hacerlo producía falsos
    positivos graves (p. ej. "elecciones" -> "eleccion", y "su elección" en un
    post de moda entraba en el tema `elecciones`; "partidos" -> "partido"). La
    tolerancia es solo en la dirección singular->plural. Tampoco se generan
    variantes para palabras de <3 letras.

    Caché: el conjunto depende solo de la palabra (vocabulario acotado) y se
    pedía ~30 M veces por generación. El set devuelto NO debe mutarse.
    """
    v = {palabra}
    if len(palabra) >= 3:
        v.add(palabra + "s")
        v.add(palabra + "es")
    return v


# --- Stemming ligero para ruso/ucraniano (cirílico) -------------------------
# `_plurales` genera el plural ESPAÑOL (-s/-es); en ruso/ucraniano la morfología
# (casos: Россия/России/России…) es rica y las formas flexionadas no casan con la
# raíz. Para tokens cirílicos se recorta un sufijo frecuente (raíz >= 4 letras) y
# se compara por RAÍZ. Solo afecta a tokens con cirílico: ES/EN no cambian.
_CYR = re.compile(r"[\u0400-\u04FF]")
_CYR_SUF = ("иями", "ями", "ами", "ией", "ей", "ой", "ий", "ый", "ия", "ии",
            "ию", "ием", "ов", "ев", "ах", "ях", "ам", "ям", "ом", "ем",
            "ую", "юю", "ая", "яя", "ы", "и", "а", "я", "у", "ю", "е", "о", "ь")


def _is_cyr(s):
    return bool(_CYR.search(s or ""))


@lru_cache(maxsize=None)
def _stem_cyr(w):
    if not _is_cyr(w):
        return w
    for suf in _CYR_SUF:
        if len(w) - len(suf) >= 4 and w.endswith(suf):
            return w[:-len(suf)]
    return w


@lru_cache(maxsize=None)
def _word_pat(kw_norm):
    """Regex \\b(?:variantes)\\b precompilada por keyword de 1 término.

    Antes se hacía `re.escape` + `re.search` (compila) en CADA llamada (~13 M
    compilaciones por generación). La keyword normalizada es vocabulario acotado.
    Para keywords cirílicas (ru/uk) se compara la RAÍZ + cualquier terminación
    (inflexión), porque el plural `-s/-es` no aplica a esas lenguas.
    """
    if _is_cyr(kw_norm):
        return re.compile(r"(?<!\w)" + re.escape(_stem_cyr(kw_norm)) + r"\w*")
    vars_ = sorted(_plurales(kw_norm), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(v) for v in vars_) + r")\b")


def _tok_present(t, texto_toks):
    """¿El token `t` (o su variante) está presente en el texto?"""
    if _is_cyr(t):
        stem = _stem_cyr(t)
        return any(x.startswith(stem) for x in texto_toks)
    return any(v in texto_toks for v in _plurales(t))


def _matches(kw_norm, kw_toks, texto_norm, texto_toks):
    """Una keyword matchea un texto si:
    - 1 término: aparece como PALABRA COMPLETA (con límites \\b), tolerando el
      plural en -s/-es. Evita falsos positivos por subcadena (p. ej. "mali"
      dentro de "normalizing"/"normalidad").
    - 2 términos: ambos presentes (como tokens), tolerando plural por token.
    - 3+ términos: al menos el 60% (redondeado arriba) presentes.
    """
    n = len(kw_toks)
    if n == 0:
        return False
    if n == 1:
        return _word_pat(kw_norm).search(texto_norm) is not None
    present = sum(1 for t in kw_toks if _tok_present(t, texto_toks))
    need = n if n == 2 else int(math.ceil(0.6 * n))
    return present >= need


def temas_por_contenido(texto, keywords):
    nt = normalizar(texto)
    ntok = [t for t in nt.split() if len(t) > 2 and t not in STOP]
    temas = set()
    for k in keywords or []:
        kw = str((k or {}).get("palabra") or "").strip()
        if not kw:
            continue
        kw_norm = normalizar(kw)
        kw_toks = _tokens(kw)
        if _matches(kw_norm, kw_toks, nt, ntok):
            temas.add((k or {}).get("tema") or "frontera_sur")
    return temas