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
