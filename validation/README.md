# validation/ — prototipo de investigación (CONGELADO, Fase 0)

**Estado: congelado 2026-09-15.** NO es producción. **NO publicar sus números.**

## Qué es
Motor mínimo que, desde los **eventos reales** de un cluster (`cluster_events`),
contrasta 3 dimensiones (`temporal_sync`, `content_similarity`, `network_density`)
contra un **modelo nulo** (permutación de autores con seed) y mide **exceso sobre
azar**, de forma independiente del `overall_score` del radar (que solo se usa para
**comparar**, nunca para decidir).

## Qué se aprendió (Fase 0)
1. **NO es circular**: corr(radar, independent) ≈ **−0,3/−0,4** → mide algo distinto.
2. **Hallazgo útil**: `intra_ratio` detecta **eco intra-cuenta** (una cuenta publicando
   en ráfaga) que el radar puede sobre-puntuar.
3. **PROBLEMA (bloqueante)**: la métrica **diluye en clusters grandes** — es "fracción
   de TODOS los pares de autores que co-ocurren" → sale ~0 aunque **un subconjunto**
   coordine. Por eso el informe (182 clusters) marcaba **57 "POSSIBLE_FALSE_POSITIVE"
   que son en su mayoría ARTEFACTO**, no falsos positivos reales.
4. La **saturación** (nulo invariante, z=0) generaba `MODERATE_SIGNAL` falsos → ahora
   se marca `AMBIGUOUS`.

## Por qué está congelado
La métrica necesita **rediseño** (agregar **por cuenta** o **por par-enlazado**, no por
todos los pares) → es **investigación, no un sprint**. Exponerlo en el panel admin o
publicarlo sería presentar números no fiables **con apariencia de autoridad** (justo lo
que el proyecto evita en todo lo demás).

## Para retomarlo (si algún día)
1. **Rediseñar la métrica** (agregación por cuenta / par-enlazado; evitar la dilución).
2. **Ground truth** etiquetado y **actual** para los temas activos (validación externa real).
3. **Solo entonces**: API admin (`/api/admin/validation/*` con `x-admin-secret`) + UI admin.

## Ficheros
`loader.py` (read-only) · `nullmodel.py` (permutación seed) · `dimensions.py`
(métricas + `intra_ratio`) · `spike.py` (muestra por banda) · `report.py` (informe de
discrepancias). Ejecutar: `.venv/bin/python validation/report.py`.
