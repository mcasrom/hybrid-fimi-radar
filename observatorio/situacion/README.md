# Ficha de situación · Frontera Sur

Primera capa de análisis del observatorio: ordena las seis fichas existentes por actores, relaciones, evidencia y vacíos. No añade hechos ni reintroduce clústeres, bandas o puntuaciones.

## Datos

- `situacion_frontera_sur.json`: contexto curado, actores, relaciones, contradicciones, preguntas abiertas y papel documental de cada dominio.
- `../data/caso_frontera_sur_hibridos/episodios_curados.json`: fichas de origen.
- `source_roles`: clasifica el **tipo de pieza** (primaria, oficial, agencia, especializada, local, extranjera, estatal, medio). No mide independencia editorial.

## Generar

```bash
python3 observatorio/situacion/gen_situacion.py \
  --episodios data/caso_frontera_sur_hibridos/episodios_curados.json \
  --out observatorio/ceuta/situacion/index.html
```

En el servidor, `run_static.sh` lo regenera junto a las páginas estáticas y aplica la cabecera.

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
