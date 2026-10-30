# Calendario electoral oficial

Genera un JSON con las fechas del real decreto de convocatoria.

## Actualizar

```bash
cd /home/miguelc/fimi_local/repo
python3 observatorio/calendario/ingest_calendario.py --fetch
```

Salida: `calendario_oficial.json`.

Fuente: BOE, Real Decreto 806/2026 (`BOE-A-2026-20742`). El parser valida que la jornada sea domingo y que la campaña empiece y termine en viernes. Si el BOE cambia, falla en vez de inventar.

## Test

```bash
cd observatorio/calendario
python3 -m unittest -v test_calendario.py
```
