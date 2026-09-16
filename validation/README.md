# validation/ — validación independiente (prototipo de investigación)

**Estado: Fase 1 (2026-09-16). Prototipo, NO publicable todavía. NO usar sus
números como validación externa.**

## Qué es
Capa de TRANSPARENCIA: mide, para cada cluster real, cuántas **cuentas** coordinan
por encima del azar (exceso sobre un modelo nulo) y lo compara con el
`overall_score` del radar **solo** para señalar discrepancias a revisión humana.
No es atribución ni ground truth.

## Fase 0 (2026-09-15) y sus dos bloqueantes
1. **Dilución**: la métrica era la **fracción de TODOS los pares** (~N²) → ~0 en
   clusters grandes aunque un core coordinara.
2. **Nulo inválido**: permutaba la **etiqueta de autor**; en clusters de cuentas
   distintas (1 evento cada una) esa permutación **no cambia la partición** → la
   métrica es invariante → **satura** (std=0) → todo `AMBIGUOUS`/sin señal.

## Fase 1 (2026-09-16) — rediseño
- **Por cuenta** (`account_metrics.py`): el grado de cada cuenta = nº de OTRAS
  cuentas con las que enlaza (tiempo / contenido / url); `z(a) = (obs − nulo)/std`.
  Un core coordinado da z alto aunque el cluster sea grande (no hay fracción sobre N).
- **Nulo de ATRIBUTO**: se permuta el **atributo** de la dimensión (ts / url / texto)
  y se dejan los autores fijos → "¿enlazan estas cuentas MÁS que si sus eventos
  tuvieran ts/url/texto repartidos al azar?".
- `report_v2.py`: **core** = mayor componente conexa entre las cuentas coordinadas
  (`z ≥ 1.5` en **≥1** dimensión); score independiente = f(core); se compara con el
  radar (bandas) para el veredicto.

## Resultado (vista activa; 187 clusters elegibles)
| Métrica | Fase 0 (182 cl) | Fase 1 (187 cl) |
|---|---|---|
| POSSIBLE_FALSE_POSITIVE | 57 | **37** |
| STRONG_SUPPORTED | 38 | **66** |
| UNCERTAIN | 42 | 60 |
| corr(radar, independiente) | −0,3/−0,4 | **+0,43** |

La Fase 1 corrige la dilución (menos FP-artefacto) y mide algo **relacionado** con el
radar (corr +0,43) **sin ser circular** (no es un espejo). Coste: ~20 s (B=50).

## LÍMITE (por qué sigue congelado)
Sin **ground truth etiquetado** no se puede decidir si un `POSSIBLE_FALSE_POSITIVE` es
error del radar o del validador; los umbrales (`z_min`, nº de dims, mapeo core→score)
son **heurísticos**. Publicarlo daría números **con apariencia de autoridad** — justo
lo que el proyecto evita en todo lo demás.

## Para cerrarlo (siguiente)
1. **Meta-validación sintética**: correr la Fase 1 sobre los grupos del generador
   sintético (ground truth conocido: B/C/F coordinados, A/D orgánicos) → exigir core
   alto en B/C/F y core 0 en A/D. Es la validación del **validador**.
2. **Ground truth real**: etiquetar a mano una muestra de clusters (evidencia de
   `cluster_events`) y medir precisión/recall del radar por banda.
3. Solo entonces: API admin (`/api/admin/validation/*` con `x-admin-secret`) + UI.

## Ficheros
`loader.py` (read-only) · `nullmodel.py` + `dimensions.py` + `spike.py` + `report.py`
(Fase 0) · **`account_metrics.py`** (Fase 1: por cuenta + nulo de atributo) ·
**`report_v2.py`** (informe Fase 1). Ejecutar: `.venv/bin/python validation/report_v2.py`.
