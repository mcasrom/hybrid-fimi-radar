# Observatorio de lo publicado

**Versión del software:** 0.1.0  
**Última actualización:** 30-oct-2026  
**Cadencia de captura:** cada 30 minutos  
**Dependencia manual diaria:** ninguna  
**Programación real:** `/etc/cron.d/observatorio-ingest` (`*/30 * * * *`)

## Qué es

Registro de lo publicado sobre cuatro temas:

- Frontera Sur (España-Marruecos)
- Protestas juveniles
- Elecciones generales
- Infraestructuras España

La captura automática usa Google News RSS y **75 feeds directos** heredados del FIMI anterior (España, Marruecos, Argelia, Francia, Reino Unido, Rusia y China), entre ellos medios locales de Ceuta y Melilla.

## Qué no es

No confirma hechos, no atribuye intención ni responsabilidad y no usa clústeres, bandas o puntuaciones internas. Un titular es una publicación, no una verificación.

## Fuentes primarias

En Infraestructuras, el Ministerio de Transportes y Movilidad Sostenible (`https://www.transportes.gob.es/`) es fuente primaria de **su propia documentación**; no es una fuente independiente sobre sus fallos. Para accidentes e incidencias hay que separar versión oficial, investigación técnica y prensa.

## Software y DOI

- Código: rama `ceuta-observatorio`.
- DOI del conjunto FIMI anterior: [10.5281/zenodo.23282710](https://doi.org/10.5281/zenodo.23282710). Sigue resolviendo; **no es el DOI del observatorio nuevo**.
- Los DOI `10.5281/zenodo.23282711` y `10.5281/zenodo.23413725` también resuelven.

## Retención

- Titulares: **90 días en caliente** y paso automático a histórico.
- Histórico: **2 años**.
- Fichas curadas: permanentes.
- Suscripciones: pendientes 30 días; confirmadas hasta baja.
- Política completa: `observatorio/RETENCION.md`.

## Estructura

- `observatorio/ingest.py`: captura automática.
- `observatorio/feeds.json`: registro de 75 feeds.
- `observatorio/live.js`: pintado de publicaciones.
- `observatorio/*/index.html`: páginas públicas.
- `observatorio/admin/`: panel privado de estado.
