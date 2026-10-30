# Infraestructuras España

Cuarto tema del Observatorio de lo publicado.

**Última actualización:** 30-oct-2026.
**Cadencia:** captura automática cada 30 minutos.
**Dependencia manual:** ninguna para el listado diario.  
**Programación real:** `/etc/cron.d/observatorio-ingest` (`*/30 * * * *`).

## Qué es

Un registro de titulares publicados sobre alta velocidad, carreteras, cercanías, aeropuertos y puertos. Cada entrada conserva medio, fecha y enlace.

## Fuente primaria

El Ministerio de Transportes y Movilidad Sostenible (`https://www.transportes.gob.es/`) es fuente primaria de **su propia documentación**: notas, estadísticas, contratos y normativa. No es una fuente independiente sobre sus propios fallos.

Para accidentes e incidencias, la versión oficial debe separarse de la investigación técnica y de la prensa.

## Límites

- No confirma causas.
- No atribuye responsabilidad.
- No convierte un titular en un hecho verificado.
- No usa clústeres, bandas ni puntuaciones internas.

## Ejecución

La captura está en `observatorio/ingest.py` y el registro de fuentes en `observatorio/feeds.json`.
