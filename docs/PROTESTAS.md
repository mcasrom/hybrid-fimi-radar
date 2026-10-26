# Piloto `protestas_juveniles`

Estado: **piloto**, ventana **14 días**, sin atribución.

## Qué hace

- Captura 12 keywords acotadas (blocus, protestas juveniles, student protests,
  protestas por país) en Bluesky y Google News.
- Corre su propio pipeline FIMI: eventos, clústeres, bandas y linaje.
- Publica una ficha curada en `/casos/protestas/` con:
  - cinco episodios (Barcelona, Francia, Milán, Albania y Nepal);
  - detonante, convocantes, demandas y llamada **citados**;
  - señal del radar y límites.

## Qué no hace

- No extrae objetivos ni llamadas automáticamente: los carga
  `data/protestas.yaml` desde fuentes públicas.
- No atribuye autoría, intención ni coordinación. Una banda alta es
  **amplificación anómala**, no una campaña confirmada.
- No geolocaliza: el alcance se describe con países/ciudades del registro.

## Operación

```bash
# backfill de 14 días (aditivo)
.venv/bin/python detection/backfill_tema_contenido.py --tema protestas_juveniles --dias 14

# pipeline del tema
.venv/bin/python detection/run_fimi.py --input data/radar.db --db data/radar.db \
  --tema protestas_juveniles --ventana-dias 14

# ficha + JSON
.venv/bin/python detection/protestas.py
```

El cron de 6 h ya incluye `detection/protestas.py` tras `gen_caso_electoral.py`.

## Medición inicial (26-oct-2026)

- 87 eventos, 35 cuentas, 1 clúster (score 39,0; ANOMALOUS).
- Run: 8,4 s y 255 MB de pico. No hubo issues en `check_sistema`.
- La página es `noindex` hasta revisión editorial.

## Archivos

- `config.yaml`: tema y keywords.
- `data/protestas.yaml`: registro curado.
- `detection/protestas.py`: ficha/JSON read-only.
- `tests/test_protestas.py`: contrato del registro y del tema.
