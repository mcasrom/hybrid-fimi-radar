# Trazabilidad histórica del score en el histórico (findings)

## Situación del bug (punto 1)
El histórico (tabla `findings`) persistía `score 0/100` para clusters cuyo
score real sí existía en la vista activa. Causa: `cluster_summary` no devuelve
`overall_score`, y `persist_findings` leía `.get("overall_score", 0)`.

El fix (`run_fimi.py`) inyecta `summary[label]["overall_score"] = overall` tras
calcularlo, de modo que el histórico guarda el score del momento de detección.

## Backfill de filas antiguas (22 filas, 02/Sep)
Las 22 filas de `findings` tipo `cluster` con `score 0/100` se corrigieron
cruzando `cluster_label` + `date(fecha)` contra `clusters.overall_score`
(snapshot del mismo día). Resultado: 22/22 con match, backfill real (no
inventado), 0 filas restantes con 0/100.

Verificación manual (3 casos): cluster_001→80, cluster_002→65, cluster_009→36.
Coherente con la vista activa.

## Limitación conocida
El sistema **no tiene** un histórico por fecha del score de cada cluster.
`clusters.cluster_label` es `UNIQUE`, así que cada ciclo que reintenta insertar
el mismo label falla (constraint) y la tabla solo conserva un **único snapshot**
(el del primer ciclo que completó los 22). Por tanto:

- El backfill funcionó aquí porque todas las filas afectadas pertenecían al
  mismo snapshot del 02/Sep (match 1:1).
- En el futuro, si un `finding` de otro día no tuviera su snapshot (ej. si se
  corta el requisito de snapshot-por-día), el score de esa fecha **no es
  recuperable** y habría que marcarlo explícitamente (`no_disponible` / NULL),
  nunca reconstruirlo con el valor último.

No se reconstruyó con un valor inventado: cada fila se recuperó del snapshot
real del mismo `cluster_label` y del mismo día.

## 05/Sep — Alineación con detección de campañas (escala + narrativas + atribución)

Trabajo de viabilidad contrastada con el análisis externo (verificado con datos
reales antes de tocar código; ver docs/SCORING.md y docs/ATRIBUCION-LIMITACIONES.md).

1. **Escala (T1)**: se confirmó el orden invertido (2 cuentas >= 49 cuentas) y se
   corrigió con `solve_scale` (bonus por masa + piso híbrido + cap existente).
   Detalle, tablas antes/después y fórmula en docs/SCORING.md. Backups y verificación
   sobre copia `/tmp/radar_test_t1.db` (BD de prod intacta: 44 clusters tras el test).
2. **Narrativas alineadas (T2)**: nuevo `detection/narrativas_alineadas.py` agrupa
   clusters de la vista activa que hablan de lo mismo (TF-IDF + coseno sobre el
   texto real de cluster_events; sklearn ya en el venv). Bloque nuevo en el dashboard.
   Verificado en HTML de prueba: 5-6 grupos reales cruzando temas.
3. **Atribución / señal organizativa (T3)**: documentadas las limitaciones
   (atribución estructural-únicamente, 44/44 UNKNOWN, UNKNOWN != sin campaña) en
   docs/ATRIBUCION-LIMITACIONES.md. Nuevo `detection/whois_signal.py` (RDAP público)
   para clusters HIGH/CRITICAL: verificado (medios consolidados = dominio estable;
   dominio activista pro-saharaui = privacidad + transferencia 2023).
4. **Fecha de deploy (T4)**: el footer HTML ahora muestra "generado <fecha UTC>"
   (marca de generación del archivo, distinguible de la fecha del último commit).
