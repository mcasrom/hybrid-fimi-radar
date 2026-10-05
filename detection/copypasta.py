#!/usr/bin/env python3
"""hybrid-fimi-radar — copypasta textual entre cuentas distintas (opción 2, 5-oct-2026).

Detecta el MISMO texto (exacto o casi-idéntico por simhash) publicado por cuentas
DISTINTAS dentro de un cluster. Es la versión textual de `cross_account_synchrony`:
no mira URLs ni dominios (esos ya los cubren `single_piece_echo`/`syndicated_wire`),
sino el contenido repetido palabra por palabra.

Reglas de diseño (acordadas):
  - Funciones PURAS (sin I/O), stdlib, para poder testearlas con casos sintéticos.
  - La evidencia son CONTEOS, nunca el texto crudo (tamaño del JSON + privacidad).
  - No decide nada: devuelve {n_pares, n_textos, n_autores}; el umbral
    supported/plausible/ruled_out vive en `explicaciones.para_cluster`.

Medido 5-oct sobre espana_elecciones 14d (2.792 docs): 33 textos exactos multi-autor
(92 docs) + 99 pares simhash<=3; 8,3 s y pico 22,5 MB en muestra. Por cluster el
coste es O(k^2) sobre enteros de 64 bits (k = tamaño del cluster).
"""
from __future__ import annotations

import hashlib
import re

MIN_LEN = 60          # textos más cortos no cuentan (saludos, "ok", titulares de 3 palabras)
HAMMING_MAX = 3       # distancia simhash para "casi-idéntico"

_URL = re.compile(r"https?://\S+|www\.\S+")
_NOISE = re.compile(r"[^a-z0-9áéíóúñü ]")
_WS = re.compile(r"\s+")


def normalizar_txt(s: str) -> str:
    """Minúsculas, sin URLs ni puntuación, espacios colapsados."""
    s = (s or "").lower()
    s = _URL.sub(" ", s)
    s = _NOISE.sub(" ", s)
    return _WS.sub(" ", s).strip()


def simhash64(s: str) -> int:
    """Simhash de 64 bits sobre shingles de 3 tokens (md5 como hash base)."""
    w = s.split()
    shingles = {" ".join(w[i:i + 3]) for i in range(max(len(w) - 2, 1))} or {s}
    v = [0] * 64
    for sh in shingles:
        h = int(hashlib.md5(sh.encode("utf-8")).hexdigest(), 16)
        for b in range(64):
            v[b] += 1 if (h >> b) & 1 else -1
    out = 0
    for b in range(64):
        if v[b] > 0:
            out |= (1 << b)
    return out


def _hamming(a: int, b: int) -> int:
    x = a ^ b
    n = 0
    while x:
        x &= x - 1
        n += 1
    return n


def resumen_pares(pares) -> dict:
    """parejas (texto, autor) -> {n_pares, n_textos, n_autores}.

    - n_textos: textos normalizados (>=MIN_LEN) repetidos por >=2 autores distintos.
    - n_pares: parejas de docs de autores distintos con texto exacto o simhash<=3.
    - n_autores: autores distintos implicados en alguna repetición.
    """
    docs = [(t or "", a or "?") for t, a in (pares or [])]
    docs = [(normalizar_txt(t), a) for t, a in docs]
    docs = [(t, a) for t, a in docs if len(t) >= MIN_LEN]
    por_txt: dict[str, set] = {}
    for t, a in docs:
        por_txt.setdefault(t, set()).add(a)
    textos = {t: aus for t, aus in por_txt.items() if len(aus) >= 2}
    hs = [(t, a, simhash64(t)) for t, a in docs]
    # Blocking: los casi-duplicados (hamming<=3) comparten al menos 1 de los
    # 4 bloques de 16 bits; solo se comparan candidatos del mismo bloque.
    # Los exactos ya están contados vía dict (O(n)); aquí van los cercanos.
    n_pares = 0
    implicados: set = set()
    for t in textos:
        implicados |= textos[t]
    vistos = set()
    bloques: dict = {}
    for idx, (t, a, h) in enumerate(hs):
        for k in range(4):
            bloques.setdefault(((h >> (16 * k)) & 0xFFFF, k), []).append(idx)
    for idxs in bloques.values():
        if len(idxs) > 400:
            continue  # bloque degenerado (texto boilerplate masivo): lo salta
        for x in range(len(idxs)):
            i = idxs[x]
            ti, ai, hi = hs[i]
            for y in range(x + 1, len(idxs)):
                j = idxs[y]
                if (i, j) in vistos:
                    continue
                vistos.add((i, j))
                tj, aj, hj = hs[j]
                if ai == aj:
                    continue
                if ti == tj or _hamming(hi, hj) <= HAMMING_MAX:
                    n_pares += 1
                    implicados.add(ai)
                    implicados.add(aj)
    return {"n_pares": n_pares, "n_textos": len(textos), "n_autores": len(implicados)}
