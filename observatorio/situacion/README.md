# Fichas de situación

Primera capa de análisis del observatorio: ordena lo publicado, separa evidencia y vacíos y añade indicadores de actividad. No añade hechos ni reintroduce clústeres, bandas o puntuaciones.

## Datos

- `situacion_frontera_sur.json`: contexto curado, actores, relaciones, contradicciones, preguntas abiertas y papel documental de cada dominio.
- `../data/caso_frontera_sur_hibridos/episodios_curados.json`: fichas de origen.
- `source_roles`: clasifica el **tipo de pieza** (primaria, oficial, agencia, especializada, local, extranjera, estatal, medio). No mide independencia editorial.
- `situacion_kpis.json`: Frontera Sur, generado por `gen_kpis.py` desde `observatorio.db`; actividad, fuentes, idiomas y evidencia curada.
- `situacion_kpis_juventud.json`: Protestas juveniles (6 episodios; 0 fuentes primarias; 6 pendientes).
- `situacion_kpis_infraestructuras.json`: Infraestructuras (8 fuentes oficiales; 0 relaciones; no confirman incidencias).
- `kpi_render.py`: render compartido de los cuatro KPI y los dos gráficos SVG.
- Los KPI son datos derivados, no una interpretación.

## Generar

```bash
python3 observatorio/situacion/gen_kpis.py \
  --topic frontera_sur \
  --out observatorio/situacion/situacion_kpis.json

python3 observatorio/situacion/gen_kpis.py \
  --topic protestas_juveniles \
  --curated observatorio/situacion/situacion_temas.json \
  --curated-key juventud \
  --out observatorio/situacion/situacion_kpis_juventud.json

python3 observatorio/situacion/gen_kpis.py \
  --topic infraestructuras_espana \
  --curated observatorio/situacion/situacion_temas.json \
  --curated-key infraestructuras \
  --out observatorio/situacion/situacion_kpis_infraestructuras.json

python3 observatorio/situacion/gen_situacion.py \
  --episodios data/caso_frontera_sur_hibridos/episodios_curados.json \
  --out observatorio/ceuta/situacion/index.html
```

En el servidor, `run_static.sh` genera primero los KPI y después la ficha.

## Deduplicación y calidad\n\nEl KPI deduplica solo la misma pieza de la misma fuente el mismo día. No colapsa medios distintos que publican el mismo titular. Google News se mide aparte: no entra en la concentración de dominios directos. Los títulos vacíos se cuentan como vacío de calidad, no como publicación válida.\n\n## Indicadores

La ficha muestra cuatro KPI y dos gráficos reutilizables:

1. **Actividad:** publicaciones diarias, media móvil de 7 días y variación entre los dos últimos periodos completos de 7 días.
2. **Fuentes:** número de fuentes distintas, concentración top-1/top-3 y fuentes con más publicaciones.
3. **Idioma:** distribución por `source_lang`; no es un mapa territorial.
4. **Evidencia:** fuentes primarias, fichas pendientes, declaraciones públicas y relaciones documentadas.

Límites deliberados:

- La unidad es la **publicación capturada**, no el hecho confirmado.
- El día de hoy es parcial; la variación usa los 7 días completos anteriores.
- La fuente es la etiqueta de captura; no mide independencia editorial.
- No hay mapa: `source_lang` y la edición de Google News no son geografía del acontecimiento.
- No hay narrativas automáticas ni índice de riesgo.

## Criterios

- Una afirmación no es un hecho.
- Una relación documentada no es coordinación.
- Una fuente no es independiente por repetir la noticia.
- `0 fuentes primarias` es un límite declarado, no un fallo que deba ocultarse.

## Briefing de cambios

`gen_briefing.py` guarda un snapshot fechado de estados, fuentes, preguntas y contradicciones, y compara con el snapshot anterior. Genera `/observatorio/ceuta/situacion/cambios/` sin IA.

- Cron semanal: lunes 08:20 (`/etc/cron.d/observatorio-briefing`).
- Comando: `run_briefing.sh`.
- Si no hay snapshot anterior, la página indica «primera edición»; no inventa cambios.
- Un cambio de estado no es una prueba nueva: sigue siendo una corrección editorial.
