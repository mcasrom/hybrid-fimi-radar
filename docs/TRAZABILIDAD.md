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

### Verificación en PRODUCCIÓN (05/Sep, cron 12:38 UTC)
Ciclo real completo tras el commit b21e473 — sin errores en la sección de hoy
(los IntegrityError `clusters.cluster_label` del fimi.log son de días previos al
fix de labels 4ebb0f3/8c46480; al revisar el log mirar SIEMPRE la última
sección `=== run_fimi ... ===`):
- 7897 eventos, 29 fuentes, 45 clusters activos (frontera_sur 35, geopolitica 3,
  politica_nacional 7). Dashboard version `b21e473`, footer "generado
  2026-09-05 12:38 UTC".
- Ranking corregido por escala: frontera_sur_cluster_000 (50 cuentas)=81.9
  CRITICAL y _001 (14 cuentas)=80.2 CRITICAL; pareja 2 cuentas/45 eventos
  (geopolitica_001)=79 HIGH conservada como señal por volumen. Un cluster de 2
  cuentas ya no supera a uno de 50.
- Piso híbrido: 26 clusters marcados "Posible ruido de bajo volumen" (WATCH 39).
  0 violaciones de la regla: los 2 únicos CRITICAL tienen 54 y 15 cuentas;
  ningún <3 cuentas sin excepción (>=10 eventos o infra >=80) está en banda
  alta. Nota: para auditar la masa usar SIEMPRE el regex "con N cuentas" del
  assessment (el conteo de autores distintos en cluster_events difiere del
  summary del clustering y da falsos positivos).
- politica_nacional (piloto) intacta: 7 clusters, max 58.7, 0 HIGH/CRITICAL —
  el override por tema de scale_floor/scale_bonus no rompe su calibración
  (anomalía 0.40).
- whois_signal.py (RDAP) en prod sobre 3 clusters >=79: medios consolidados =
  "dominio estable"; noteolvidesdelsaharaoccidental.org = registro 2016 /
  transferencia 2023 / privacidad (señal que lo estructural no ve).
- Bloque "Narrativas alineadas (cluster-of-clusters)" en vivo: grupo de 7
  clusters cruzando frontera_sur + politica_nacional sobre gobierno/Marruecos/
  España.
